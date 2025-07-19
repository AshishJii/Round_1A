#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
A Python script to process a text-based PDF file, extract structured information,
and generate a CSV with detailed features for each text block, including
normalized values for size and spacing, and a label for centered text.

This script uses the PyMuPDF library (fitz) to parse the PDF, as it provides
excellent access to low-level details like font information, bounding boxes,
and text flags.

Requirements:
    - PyMuPDF: a.k.a. fitz, can be installed with `pip install PyMuPDF`

Usage:
    python extract_pdf_features.py <input_pdf_path> <output_csv_path>

Example:
    python extract_pdf_features.py "reports/annual_report.pdf" "analysis/report_features.csv"
"""

import fitz  # PyMuPDF
import csv
import sys
import os
from collections import Counter

def analyze_block_text_features(block):
    """
    Analyzes the spans within a text block to determine dominant font properties.
    
    Args:
        block (dict): A text block dictionary from page.get_text("dict").
        
    Returns:
        tuple: A tuple containing (dominant_font, dominant_size, is_bold, is_italic, full_text).
    """
    spans_info = []
    full_text = ""

    # A block is composed of lines, and lines are composed of spans.
    # A span is a contiguous run of text with the same font, size, and flags.
    for line in block.get('lines', []):
        for span in line.get('spans', []):
            spans_info.append({
                'size': span.get('size', 0),
                'font': span.get('font', ''),
                'flags': span.get('flags', 0),
            })
            full_text += span.get('text', '') + ' '
    
    full_text = full_text.strip()
    if not spans_info:
        return "N/A", 0, False, False, full_text

    # --- Determine dominant font and size ---
    # Count occurrences of each font and size
    font_counter = Counter(s['font'] for s in spans_info)
    size_counter = Counter(round(s['size']) for s in spans_info)
    
    dominant_font = font_counter.most_common(1)[0][0] if font_counter else "N/A"
    dominant_size = size_counter.most_common(1)[0][0] if size_counter else 0

    # --- Determine font styles (bold/italic) ---
    # PyMuPDF uses flags to denote styles. Flag 2^4=16 is bold, 2^1=2 is italic.
    flags = [s['flags'] for s in spans_info]
    is_bold = any(f & (1 << 4) for f in flags)
    is_italic = any(f & (1 << 1) for f in flags)

    return dominant_font, dominant_size, is_bold, is_italic, full_text


def process_pdf(input_pdf_path, output_csv_path):
    """
    Main function to process the PDF and generate the feature-rich CSV.
    
    Args:
        input_pdf_path (str): The file path of the input PDF.
        output_csv_path (str): The file path for the output CSV.
    """
    try:
        doc = fitz.open(input_pdf_path)
    except Exception as e:
        print(f"Error: Could not open or process PDF file '{input_pdf_path}'.")
        print(f"Reason: {e}")
        return

    all_blocks_data = []

    print(f"Processing {len(doc)} pages in '{os.path.basename(input_pdf_path)}'...")

    # Iterate through each page of the PDF
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        page_height = page.rect.height
        page_width = page.rect.width

        # Get text blocks from the page, already grouped by layout
        # Sorting by vertical position (y0) is crucial for calculating space between blocks
        blocks = sorted(page.get_text("dict")["blocks"], key=lambda b: b['bbox'][1])

        # Iterate through each text block
        for i, block in enumerate(blocks):
            # Skip empty or image blocks
            if block['type'] != 0 or not block.get('lines'):
                continue

            # --- 1. Basic Text and Font Features ---
            font, font_size, is_bold, is_italic, text = analyze_block_text_features(block)
            
            # Skip blocks with no text content
            if not text.strip():
                continue

            # --- 2. Content-based Features ---
            cleaned_text_for_caps = ''.join(c for c in text if c.isalpha())
            is_all_caps = bool(cleaned_text_for_caps) and cleaned_text_for_caps.isupper()
            contains_number = any(char.isdigit() for char in text)
            contains_fullstop = '.' in text
            word_count = len(text.split())

            # --- 3. Positional and Bounding Box Features ---
            x0, y0, x1, y1 = block['bbox']

            # --- 4. Whitespace and Alignment Features ---
            # Space Above: Distance from the top of this block to the bottom of the previous block.
            prev_block_y1 = blocks[i-1]['bbox'][3] if i > 0 else 0
            space_above = y0 - prev_block_y1

            # Space Below: Distance from the bottom of this block to the top of the next block.
            next_block_y0 = blocks[i+1]['bbox'][1] if i < len(blocks) - 1 else page_height
            space_below = next_block_y0 - y1
            
            # Space on Left/Right
            space_left = x0
            space_right = page_width - x1
            
            # **NEW**: Centering check with a margin of error
            page_midpoint_x = page_width / 2
            block_midpoint_x = (x0 + x1) / 2
            margin_of_error = 5.0  # in points (1/72 inch). Adjust this value as needed.
            is_centered = abs(block_midpoint_x - page_midpoint_x) < margin_of_error

            # --- 5. Underline Detection (Advanced) ---
            # Search for horizontal drawing paths near the text's baseline.
            is_underline = False
            drawings = page.get_drawings()
            for path in drawings:
                # Check for a horizontal line by ensuring its bounding box has a very small height.
                is_horizontal_line = path['rect'].height < 1.0 and path['rect'].width > 0

                if is_horizontal_line:
                    # Check if the line's vertical position is near the text block's baseline (y1).
                    line_y = path['rect'].y0
                    if line_y > (y1 - font_size * 0.2) and line_y < (y1 + font_size * 0.2):
                        # Finally, check if the line's horizontal span overlaps with the block's text.
                        if max(x0, path['rect'].x0) < min(x1, path['rect'].x1):
                            is_underline = True
                            break # Found an underline for this block

            # --- Assemble the feature dictionary for this block ---
            block_data = {
                'text': text,
                'font': font,
                'font_size': font_size,
                'is_bold': is_bold,
                'is_italic': is_italic,
                'is_underline': is_underline,
                'is_all_caps': is_all_caps,
                'is_centered': is_centered, # Added new feature
                'contains_number': contains_number,
                'contains_fullstop': contains_fullstop,
                'word_count': word_count,
                'x0': round(x0, 2),
                'y0': round(y0, 2),
                'x1': round(x1, 2),
                'y1': round(y1, 2),
                'space_above': round(space_above, 2),
                'space_below': round(space_below, 2),
                'space_left': round(space_left, 2),
                'space_right': round(space_right, 2),
                'page_number': page_num + 1, # Page numbers are 1-based for human readability
            }
            all_blocks_data.append(block_data)

    doc.close()

    if not all_blocks_data:
        print("Warning: No text blocks were extracted from the PDF.")
        return

    # --- 6. Normalize features across the entire document ---
    features_to_normalize = ['font_size', 'space_above', 'space_below', 'space_left', 'space_right']
    min_max_values = {key: {'min': float('inf'), 'max': float('-inf')} for key in features_to_normalize}

    for block in all_blocks_data:
        for key in features_to_normalize:
            min_max_values[key]['min'] = min(min_max_values[key]['min'], block[key])
            min_max_values[key]['max'] = max(min_max_values[key]['max'], block[key])

    # Second pass: calculate and insert normalized values.
    for block in all_blocks_data:
        for key in features_to_normalize:
            min_val = min_max_values[key]['min']
            max_val = min_max_values[key]['max']
            range_val = max_val - min_val
            
            # Handle division by zero if all values for a feature are the same.
            norm_val = 0.0 if range_val == 0 else (block[key] - min_val) / range_val
            
            block[f'norm_{key}'] = round(norm_val, 4)

    # --- 7. Write all extracted data to a CSV file ---
    print(f"Writing {len(all_blocks_data)} text blocks to '{output_csv_path}'...")
    try:
        with open(output_csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            # Dynamically get headers from the first dictionary's keys
            if all_blocks_data:
                fieldnames = all_blocks_data[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                writer.writerows(all_blocks_data)
        print("Successfully created the CSV file.")
    except IOError as e:
        print(f"Error: Could not write to CSV file '{output_csv_path}'.")
        print(f"Reason: {e}")


def main():
    """
    Entry point of the script. Parses command-line arguments.
    """
    if len(sys.argv) != 3:
        print("Usage: python extract_pdf_features.py <input_pdf_path> <output_csv_path>")
        sys.exit(1)

    input_pdf = sys.argv[1]
    output_csv = sys.argv[2]

    if not os.path.exists(input_pdf):
        print(f"Error: Input file not found at '{input_pdf}'")
        sys.exit(1)
        
    output_dir = os.path.dirname(output_csv)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: '{output_dir}'")

    process_pdf(input_pdf, output_csv)


if __name__ == '__main__':
    main()