# src/policy_bootstrap.py
"""
Utility script to regenerate YAML policy rules from the PDF source.
Pairs simple regex pattern matching with rule templates so we can
automatically capture key guidance (e.g., bullet formatting requirements).
"""

import re
import yaml
from pathlib import Path

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional dependency
    fitz = None


def extract_text(pdf_path: str) -> str:
    if not fitz:
        raise RuntimeError("PyMuPDF (fitz) is required to parse the policy PDF.")
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text("text") for page in doc)


DEFAULT_SCOPE = {
    "market": ["AE"],
    "categories": ["PetSupplies"],
}

RULE_PATTERNS = [
    {
        "pattern": r"\b(up to\s*5|five key features|no more than 5)\b",
        "flags": re.I,
        "rules": [
            {
                "id": "BULLETS_MAX5",
                "section": "bullets",
                "type": "max_count",
                "params": {"value": 5},
                "severity": "error",
                "message": "Use up to 5 bullet points.",
                "citation": "Policy: Key Product Features — up to five features.",
            },
        ],
    },
    {
        "pattern": r"(no ending punctuation|sentence fragments|should not end with punctuation)",
        "flags": re.I,
        "rules": [
            {
                "id": "BULLETS_NO_END_PUNCT",
                "section": "bullets",
                "type": "no_ending_punct",
                "params": {"punctuation": ".;:!"},
                "severity": "warning",
                "message": "Bullets should not end with punctuation.",
                "citation": "Policy: Key Product Features — sentence fragments.",
            },
        ],
    },
    {
        "pattern": r"(start each bullet|begin each bullet).*capital",
        "flags": re.I,
        "rules": [
            {
                "id": "BULLETS_CAP_START",
                "section": "bullets",
                "type": "bullets_capitalized",
                "params": {},
                "severity": "warning",
                "message": "Bullets must begin with a capital letter.",
                "citation": "Policy: Key Product Features — start each bullet with a capital letter.",
            },
        ],
    },
    {
        "pattern": r"write all numbers as numerals",
        "flags": re.I,
        "rules": [
            {
                "id": "BULLETS_NUMERALS",
                "section": "bullets",
                "type": "bullets_numbers_as_numerals",
                "params": {},
                "severity": "warning",
                "message": "All numbers in bullets should be expressed as numerals.",
                "citation": "Policy: Key Product Features — write numbers as numerals.",
            },
        ],
    },
    {
        "pattern": r"(no promotional|no seller info)",
        "flags": re.I,
        "rules": [
            {
                "id": "TITLE_NO_PROMO",
                "section": "title",
                "type": "forbidden_regex",
                "params": {
                    "pattern": r"\b(sale|free shipping|free delivery|best seller|top seller)\b",
                    "flags": "i",
                },
                "severity": "error",
                "message": "No promotional/seller terms in title.",
                "citation": "Policy: Title — no promotional or seller info.",
            },
            {
                "id": "DESC_NO_URLS",
                "section": "description",
                "type": "no_urls_emails",
                "params": {},
                "severity": "error",
                "message": "No URLs or email addresses in description.",
                "citation": "Policy: Description — no seller/URL/email.",
            },
        ],
    },
]


def guess_rules(text: str) -> list[dict]:
    matches: dict[str, dict] = {}
    for entry in RULE_PATTERNS:
        if re.search(entry["pattern"], text, entry.get("flags", 0)):
            for rule_tpl in entry["rules"]:
                # clone template so we can attach scope without mutating base
                rule = dict(rule_tpl)
                rule["scope"] = dict(DEFAULT_SCOPE)
                matches[rule["id"]] = rule
    return list(matches.values())


def main():
    base = Path("data/policies/pet-supplies_ae_2018")
    pdf = base / "source.pdf"
    out = base / "rules.yaml"

    text = extract_text(str(pdf))
    rules = guess_rules(text)
    doc = {
        "meta": {
            "policy_id": "pet-supplies_ae_2018",
            "market": "AE",
            "categories": ["PetSupplies"],
        },
        "rules": rules or [],
    }
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    print(f"Wrote {out} with {len(rules)} rule(s).")


if __name__ == "__main__":
    main()
