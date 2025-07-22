import sys
import fitz  # PyMuPDF
import csv

def convert_color_int_to_rgb(color_int):
    """
    Converts an sRGB integer color value to a more readable (R, G, B) tuple.

    Args:
        color_int (int): The integer representation of the color.

    Returns:
        tuple: An (R, G, B) tuple, or None if input is invalid.
    """
    if color_int is None:
        return None
    # The color is stored as a single integer, we decode it to R, G, B components
    blue = color_int & 255
    green = (color_int >> 8) & 255
    red = (color_int >> 16) & 255
    return (red, green, blue)

def get_style_signature(span):
    """
    Creates a unique signature for a text span based on its style properties.
    This helps in identifying and merging text with identical styling.

    Args:
        span (dict): The span dictionary from PyMuPDF.

    Returns:
        tuple: A tuple representing the style signature, or None.
    """
    if not span:
        return None
    
    flags = span.get("flags", 0)
    # Flag 1 is for underline.
    is_underline = bool(flags & 1)
    # Flag 2 is for italic.
    is_italic = bool(flags & 2)
    # Flag 16 is for bold.
    is_bold = bool(flags & 16)
    
    # Check if the text is all uppercase.
    text = span.get("text", "").strip()
    is_all_caps = text.isupper() and any(c.isalpha() for c in text)

    # The signature is a combination of all relevant style properties.
    # We round font size to handle minor floating point variations.
    signature = (
        span.get("font", "Unknown"),
        round(span.get("size", 0), 2),
        span.get("color"),
        is_bold,
        is_italic,
        is_underline,
        is_all_caps
    )
    return signature

def normalize_value(value, min_val, max_val):
    """
    Normalizes a value to a 0-1 scale using min-max normalization.
    """
    if max_val == min_val:
        return 0.0  # Avoid division by zero if all values are the same
    return (value - min_val) / (max_val - min_val)

def extract_and_process_pdf(pdf_path, csv_path):
    """
    Performs a two-pass process on a PDF. First, it gathers all text block data
    to find min/max values for normalization. Second, it calculates normalized
    values and writes the complete, ML-ready data to a CSV file.

    Args:
        pdf_path (str): The file path to the PDF document.
        csv_path (str): The file path for the output CSV file.
    """
    doc = None
    try:
        doc = fitz.open(pdf_path)
        print(f"Successfully opened '{pdf_path}'")
        print(f"Number of pages: {doc.page_count}\n")
        print("-" * 30)
        
        # --- PASS 1: Gather all data to determine normalization ranges ---
        print("Starting Pass 1: Analyzing document structure...")
        all_blocks_raw_data = []
        for page_num, page in enumerate(doc, 1):
            page_width = page.rect.width
            page_height = page.rect.height
            
            blocks = page.get_text("dict").get("blocks", [])
            if not blocks:
                continue

            # Merge lines with identical styles for the current page
            merged_blocks_on_page = []
            current_text = ""
            current_style_sig = None
            current_bbox = None

            for block in blocks:
                if block['type'] == 0:  # Text block
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        if not spans: continue
                        
                        longest_span = max(spans, key=lambda s: len(s.get("text", "").strip()), default=None)
                        if not longest_span or not longest_span.get("text", "").strip(): continue

                        line_style_sig = get_style_signature(longest_span)
                        line_text = "".join(span.get("text", "") for span in spans).strip()
                        line_bbox = fitz.Rect(line["bbox"])

                        if line_style_sig == current_style_sig:
                            current_text += " " + line_text
                            current_bbox.include_rect(line_bbox)
                        else:
                            if current_text:
                                merged_blocks_on_page.append({"text": current_text, "style": current_style_sig, "bbox": current_bbox})
                            current_style_sig = line_style_sig
                            current_text = line_text
                            current_bbox = fitz.Rect(line_bbox)
            
            if current_text:
                merged_blocks_on_page.append({"text": current_text, "style": current_style_sig, "bbox": current_bbox})

            # Calculate raw spacing values for the page and store all data
            for i, block_data in enumerate(merged_blocks_on_page):
                block_data['page_num'] = page_num
                block_data['page_width'] = page_width
                block_data['page_height'] = page_height
                
                # Calculate raw space values
                bbox = block_data["bbox"]
                block_data['space_left'] = bbox.x0
                block_data['space_right'] = page_width - bbox.x1
                block_data['space_above'] = bbox.y0 if i == 0 else bbox.y0 - merged_blocks_on_page[i-1]["bbox"].y1
                block_data['space_below'] = page_height - bbox.y1 if i == len(merged_blocks_on_page) - 1 else merged_blocks_on_page[i+1]["bbox"].y0 - bbox.y1
                
                all_blocks_raw_data.append(block_data)

        if not all_blocks_raw_data:
            print("No text content found in the PDF.")
            return

        # --- Calculate Min/Max for normalization ---
        font_sizes = [b['style'][1] for b in all_blocks_raw_data]
        spaces_above = [b['space_above'] for b in all_blocks_raw_data]
        spaces_below = [b['space_below'] for b in all_blocks_raw_data]
        spaces_left = [b['space_left'] for b in all_blocks_raw_data]
        spaces_right = [b['space_right'] for b in all_blocks_raw_data]

        min_font, max_font = min(font_sizes), max(font_sizes)
        min_sa, max_sa = min(spaces_above), max(spaces_above)
        min_sb, max_sb = min(spaces_below), max(spaces_below)
        min_sl, max_sl = min(spaces_left), max(spaces_left)
        min_sr, max_sr = min(spaces_right), max(spaces_right)
        
        # --- PASS 2: Normalize data and write to CSV ---
        print("Starting Pass 2: Normalizing data and writing to CSV...")
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            csv_writer = csv.writer(csvfile)
            # Reordered header with ML-relevant columns first
            csv_writer.writerow([
                'page_number', 'is_bold', 'is_italic', 'is_underline', 'is_all_caps', 
                'is_centered', 'contains_number', 'contains_fullstop', 'word_count', 
                'norm_font_size', 'norm_space_above', 'norm_space_below', 
                'norm_space_left', 'norm_space_right', 'norm_r', 'norm_g', 'norm_b', 
                'norm_x0', 'norm_y0', 'norm_x1', 'norm_y1', 
                'font', 'font_size', 'color_rgb', 'x0', 'y0', 'x1', 'y1', 
                'space_above', 'space_below', 'space_left', 'space_right', 'text'
            ])

            for block_data in all_blocks_raw_data:
                text = block_data["text"]
                style = block_data["style"]
                bbox = block_data["bbox"]
                font, size, color_int, bold, italic, underline, all_caps = style
                
                # Normalize positional and style values
                norm_font_size = normalize_value(size, min_font, max_font)
                norm_sa = normalize_value(block_data['space_above'], min_sa, max_sa)
                norm_sb = normalize_value(block_data['space_below'], min_sb, max_sb)
                norm_sl = normalize_value(block_data['space_left'], min_sl, max_sl)
                norm_sr = normalize_value(block_data['space_right'], min_sr, max_sr)
                
                # Normalize coordinates by page dimensions
                page_width = block_data['page_width']
                page_height = block_data['page_height']
                norm_x0 = bbox.x0 / page_width if page_width else 0
                norm_y0 = bbox.y0 / page_height if page_height else 0
                norm_x1 = bbox.x1 / page_width if page_width else 0
                norm_y1 = bbox.y1 / page_height if page_height else 0

                # Other properties
                contains_number = any(char.isdigit() for char in text)
                contains_fullstop = '.' in text
                word_count = len(text.split())
                is_centered = abs(block_data['space_left'] - block_data['space_right']) < 5
                
                # Color conversion and normalization
                color_rgb = convert_color_int_to_rgb(color_int)
                if color_rgb:
                    color_str = f"({color_rgb[0]}, {color_rgb[1]}, {color_rgb[2]})"
                    norm_r = color_rgb[0] / 255.0
                    norm_g = color_rgb[1] / 255.0
                    norm_b = color_rgb[2] / 255.0
                else:
                    color_str = "(0, 0, 0)"
                    norm_r, norm_g, norm_b = 0.0, 0.0, 0.0

                # Write the final row in the new order
                csv_writer.writerow([
                    block_data['page_num'], int(bold), int(italic), int(underline), int(all_caps),
                    int(is_centered), int(contains_number), int(contains_fullstop), word_count,
                    round(norm_font_size, 4), round(norm_sa, 4), round(norm_sb, 4),
                    round(norm_sl, 4), round(norm_sr, 4),
                    round(norm_r, 4), round(norm_g, 4), round(norm_b, 4),
                    round(norm_x0, 4), round(norm_y0, 4), round(norm_x1, 4), round(norm_y1, 4),
                    font, size, color_str, 
                    round(bbox.x0, 2), round(bbox.y0, 2), round(bbox.x1, 2), round(bbox.y1, 2),
                    round(block_data['space_above'], 2), round(block_data['space_below'], 2), 
                    round(block_data['space_left'], 2), round(block_data['space_right'], 2), 
                    text
                ])

    except FileNotFoundError:
        print(f"Error: The file '{pdf_path}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if doc:
            doc.close()
            print("\n" + "-" * 30)
            print("Processing complete. Document closed.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python your_script_name.py <path_to_pdf_file> <output_csv_file>")
        sys.exit(1)

    pdf_file_path = sys.argv[1]
    csv_file_path = sys.argv[2]
    extract_and_process_pdf(pdf_file_path, csv_file_path)
