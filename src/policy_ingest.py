# src/policy_ingest.py
import json, re, fitz  # PyMuPDF
from pathlib import Path

def extract_text_blocks(pdf_path: str) -> list[str]:
    doc = fitz.open(pdf_path)
    blocks = []
    for p in doc:
        text = p.get_text("text")
        if text and text.strip():
            blocks.append(text)
    return blocks

def segment_sections(blocks: list[str]) -> dict:
    text = "\n".join(blocks)
    def sect(name): 
        return re.split(rf"\n(?=^[A-Z][A-Za-z ]*?$)", text, flags=re.M)[0]
    # In practice, use robust finders; simplified here
    return {
        "title": re.search(r"Product Title(.+?)Product Images", text, re.S),
        "images": re.search(r"Product Images(.+?)Key Product Features", text, re.S),
        "bullets": re.search(r"Key Product Features(.+?)Product Descriptions", text, re.S),
        "description": re.search(r"Product Descriptions(.+?)\n[A-Z]", text, re.S),
    }

def derive_rules_from_sections(sections: dict) -> list[dict]:
    rules = []
    # Example: look for "five" or "up to five"
    if sections["bullets"] and re.search(r"\b(up to )?five\b", sections["bullets"].group(1), re.I):
        rules.append({
          "id":"BULLETS_MAX5","section":"bullets","type":"max_count",
          "params":{"value":5},"severity":"error",
          "message":"Use up to 5 bullet points.",
          "citation":"Policy: Key Product Features — highlight five key features."
        })
    # … repeat for other phrases
    return rules
