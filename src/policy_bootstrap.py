# src/policy_bootstrap.py
import re, yaml, fitz
from pathlib import Path

def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    return "\n".join([p.get_text("text") for p in doc])

def guess_rules(text: str) -> list[dict]:
    rules = []

    # Bullets count
    if re.search(r"\b(up to\s*5|five key features|no more than 5)\b", text, re.I):
        rules.append({
            "id":"BULLETS_MAX5","section":"bullets","type":"max_count",
            "params":{"value":5},"severity":"error",
            "message":"Use up to 5 bullet points.",
            "citation":"Policy: Key Product Features — up to five features.",
            "scope":{"market":["AE"],"categories":["PetSupplies"]}
        })

    # No end punctuation
    if re.search(r"(no ending punctuation|sentence fragments)", text, re.I):
        rules.append({
            "id":"BULLETS_NO_END_PUNCT","section":"bullets","type":"no_ending_punct",
            "params":{"punctuation":".;:!"},"severity":"warning",
            "message":"Bullets should not end with punctuation.",
            "citation":"Policy: Key Product Features — sentence fragments.",
            "scope":{"market":["AE"],"categories":["PetSupplies"]}
        })

    # No promo in title/desc
    if re.search(r"(no promotional|no seller info)", text, re.I):
        rules += [
            {
              "id":"TITLE_NO_PROMO","section":"title","type":"forbidden_regex",
              "params":{"pattern":r"\\b(sale|free shipping|free delivery|best seller|top seller)\\b","flags":"i"},
              "severity":"error","message":"No promotional/seller terms in title.",
              "citation":"Policy: Title — no promotional or seller info.",
              "scope":{"market":["AE"],"categories":["PetSupplies"]}
            },
            {
              "id":"DESC_NO_URLS","section":"description","type":"no_urls_emails",
              "params":{},"severity":"error",
              "message":"No URLs or email addresses in description.",
              "citation":"Policy: Description — no seller/URL/email.",
              "scope":{"market":["AE"],"categories":["PetSupplies"]}
            }
        ]
    return rules

def main():
    base = Path("data/policies/pet-supplies_ae_2018")
    pdf = base / "source.pdf"
    out = base / "rules.yaml"
    meta = base / "meta.yaml"

    text = extract_text(str(pdf))
    rules = guess_rules(text)
    doc = {
        "meta": {
            "policy_id": "pet-supplies_ae_2018",
            "market": "AE",
            "categories": ["PetSupplies"]
        },
        "rules": rules or []  # keep empty if nothing matched; you can edit later
    }
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    print(f"Wrote {out} with {len(rules)} rule(s).")

if __name__ == "__main__":
    main()
