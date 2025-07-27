import fitz  # PyMuPDF
import json
import re
from pathlib import Path


def is_heading_nlp(text):
    """
    Heuristic for heading detection based on text style:
    - No trailing punctuation
    - Short (<=10 words)
    - Majority title-case words
    - Filter out very short or symbol-only text
    """
    txt = text.strip()
    if not txt or txt[-1] in ".?!":
        return False
    words = txt.split()
    if len(words) > 10:
        return False
    # Must have at least 3 alphanumeric characters
    alnum_count = sum(1 for c in txt if c.isalnum())
    if alnum_count < 3:
        return False
    cap = sum(1 for w in words if w and w[0].isupper())
    return (cap / len(words)) >= 0.5


def adjust_hierarchy(outline):
    """
    Adjust heading levels so hierarchy is relative:
    - If no H1 has appeared, promote any higher levels to H1
    - Prevent gaps: if level > last_level + 1, promote to last_level + 1
    """
    last_level = 0
    for node in outline:
        orig = int(node.get('level', 'H1')[1])
        if last_level == 0 and orig > 1:
            new = 1
        elif orig > last_level + 1:
            new = last_level + 1
        else:
            new = orig
        node['level'] = f"H{new}"
        last_level = new
    return outline


def extract_pdf_structure(pdf_path):
    doc = fitz.open(pdf_path)
    blocks = []
    font_sizes = []

    # Collect text blocks and style metrics
    for page_num, page in enumerate(doc):  # page numbers start at 0
        print(f"Processing page {page_num}")
        for blk in page.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            block_text = ""
            max_font_size = 0
            bold_spans = 0
            italic_spans = 0
            total_spans = 0
            for line in blk.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    total_spans += 1
                    font_name = span.get("font", "")
                    if re.search(r"Bold", font_name, re.IGNORECASE):
                        bold_spans += 1
                    if re.search(r"Italic|Oblique", font_name, re.IGNORECASE):
                        italic_spans += 1
                    size = span.get("size", 0)
                    font_sizes.append(size)
                    max_font_size = max(max_font_size, size)
                    block_text += text + " "
            if block_text.strip():
                blocks.append({
                    "page": page_num,
                    "text": block_text.strip(),
                    "font_size": max_font_size,
                    "bold_ratio": (bold_spans / total_spans) if total_spans else 0,
                    "italic_ratio": (italic_spans / total_spans) if total_spans else 0
                })

    # Determine heading size threshold
    avg_font = (sum(font_sizes) / len(font_sizes)) if font_sizes else 0
    heading_thresh = avg_font + 1.5

    title = None
    outline = []

    for b in blocks:
        txt = b["text"]
        page = b["page"]
        size = b["font_size"]
        bold_ratio = b.get("bold_ratio", 0)
        italic_ratio = b.get("italic_ratio", 0)
        words = txt.split()

        # Title detection on page 0
        if page == 0 and title is None and len(words) > 4 and txt[-1] not in ".?!":
            title = txt
            continue

        # Filter out too-short or symbol-only text
        alnum_count = sum(1 for c in txt if c.isalnum())
        if alnum_count < 3 or len(txt) < 4:
            continue

        # Heading detection combining metrics
        is_big = size >= heading_thresh
        is_bold = bold_ratio > 0.5
        is_italic = italic_ratio > 0.5
        is_nlp = is_heading_nlp(txt)
        if (is_big or is_bold or is_italic or is_nlp) and len(words) <= 10:
            level = "H1" if (is_big and size >= heading_thresh * 1.2) or is_bold else "H2"
            outline.append({"level": level, "text": txt, "page": page})

    # Normalize hierarchy
    outline = adjust_hierarchy(outline)
    return {"title": title or "", "outline": outline}


def process_pdfs(input_dir: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = list(input_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return
    for pdf in pdf_files:
        result = extract_pdf_structure(pdf)
        out_file = output_dir / f"{pdf.stem}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Processed {pdf.name} -> {out_file.name}")


if __name__ == "__main__":
    input_path = Path("/app/input")
    output_path = Path("/app/output")
    print("Starting processing PDFs...")
    process_pdfs(input_path, output_path)
    print("Completed processing PDFs.")
