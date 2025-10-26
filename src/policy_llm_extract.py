"""
LLM-backed policy extraction utility.

Usage:
    python3 -m src.policy_llm_extract --pdf data/policies/pet-supplies_ae_2018/source.pdf --out data/policies/pet-supplies_ae_2018/rules.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional dependency
    fitz = None

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover - allow offline dev
    genai = None


ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"

SYSTEM_PROMPT_PATH = PROMPTS_DIR / "policy_rules_system_prompt.md"
USER_PROMPT_PATH = PROMPTS_DIR / "policy_rules_user_prompt.md"

KNOWN_SECTIONS = {"title", "bullets", "description", "images"}
ALLOWED_SECTIONS = {"title", "bullets", "description"}
SECTION_ALIASES = {
    "key product features": "bullets",
    "product title": "title",
    "product descriptions": "description",
    "product description": "description",
    "additional images": "images",
    "product images": "images",
}

KNOWN_TYPES = {
    "max_length",
    "min_length",
    "max_count",
    "min_count",
    "forbidden_regex",
    "required_regex",
    "forbidden_regex_each",
    "no_ending_punct",
    "no_urls_emails",
    "bullets_capitalized",
    "bullets_numbers_as_numerals",
}


@dataclass
class Rule:
    id: str
    section: str
    type: str
    params: Dict[str, Any]
    severity: str
    message: str
    citation: str
    scope: Dict[str, Any]


def read_text(pdf_path: Path) -> str:
    if not fitz:
        raise RuntimeError("PyMuPDF (pymupdf) is required to extract text from the policy PDF.")
    doc = fitz.open(str(pdf_path))
    return "\n".join(page.get_text("text") for page in doc)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\xa0", " ")).strip()


def split_sections(raw_text: str) -> Dict[str, str]:
    """
    Heuristic splitter that looks for known headings and maps them to rule sections.
    """
    normalized = normalize_whitespace(raw_text)
    # Preserve line breaks for heading detection
    lines = [line.strip() for line in raw_text.splitlines()]

    sections: Dict[str, List[str]] = {}
    current_section_key: Optional[str] = None

    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        lower = clean.lower()
        alias = None
        for name, section in SECTION_ALIASES.items():
            if lower.startswith(name):
                alias = section
                break
        if alias:
            current_section_key = alias
            sections.setdefault(alias, [])
            continue
        if current_section_key:
            sections[current_section_key].append(clean)

    return {k: "\n".join(v).strip() for k, v in sections.items() if v}


def load_prompts() -> tuple[str, str]:
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    user_template = USER_PROMPT_PATH.read_text(encoding="utf-8")
    return system_prompt, user_template


def configure_genai(model_id: str) -> Any:
    if not genai:
        raise RuntimeError("google-generativeai is not installed.")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is required for LLM extraction.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_id)


def call_llm(model: Any, system_prompt: str, user_prompt: str) -> str:
    prompt = f"{system_prompt.strip()}\n\n{user_prompt.strip()}"
    response = model.generate_content(prompt)
    if hasattr(response, "text") and response.text:
        return response.text.strip()
    parts: List[str] = []
    for cand in getattr(response, "candidates", []) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            if getattr(part, "text", None):
                parts.append(part.text)
    return "\n".join(parts).strip()


def extract_json_array(text: str) -> List[Dict[str, Any]]:
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        return json.loads(match.group(0))
    except Exception:
        return []


def normalize_section(name: str) -> Optional[str]:
    if not name:
        return None
    lowered = name.strip().lower()
    if lowered in KNOWN_SECTIONS:
        return lowered
    return SECTION_ALIASES.get(lowered)


def slugify(text: str, length: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:length] if length else slug


def normalize_rule(raw: Dict[str, Any], default_scope: Dict[str, Any]) -> Optional[Rule]:
    section = normalize_section(str(raw.get("section", "")))
    if not section:
        return None
    if section not in ALLOWED_SECTIONS:
        return None
    rule_type = str(raw.get("type", "")).strip()
    if rule_type not in KNOWN_TYPES:
        return None
    message = str(raw.get("message", "")).strip()
    citation = str(raw.get("citation", "")).strip()
    severity = str(raw.get("severity", "")).strip().lower() or "warning"
    if severity not in {"info", "warning", "error"}:
        severity = "warning"
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    required_fields = {
        "max_length": ["value"],
        "min_length": ["value"],
        "max_count": ["value"],
        "min_count": ["value"],
        "forbidden_regex": ["pattern"],
        "required_regex": ["pattern"],
        "forbidden_regex_each": ["pattern"],
    }.get(rule_type, [])
    for field in required_fields:
        if field not in params:
            return None
    rid = str(raw.get("id", "")).strip()
    if not rid:
        rid = f"{section}_{rule_type}_{slugify(message or rule_type)}"
    return Rule(
        id=rid,
        section=section,
        type=rule_type,
        params=params,
        severity=severity,
        message=message or rule_type.replace("_", " ").title(),
        citation=citation,
        scope=default_scope,
    )


def dedupe_rules(rules: List[Rule]) -> List[Rule]:
    seen: Dict[str, Rule] = {}
    for rule in rules:
        key = (rule.section, rule.type, rule.id)
        # Keep the first occurrence; manual edits can adjust later
        if key not in seen:
            seen[key] = rule
    return list(seen.values())


def rules_to_yaml(rules: List[Rule]) -> Dict[str, Any]:
    payload = {
        "meta": {
            "policy_id": "pet-supplies_ae_2018",
            "market": "AE",
            "categories": ["PetSupplies"],
        },
        "rules": [asdict(rule) for rule in rules],
    }
    return payload


def save_yaml(doc: Dict[str, Any], out_path: Path) -> None:
    out_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def extract_rules_from_pdf(pdf_path: Path, model_id: str, dump_dir: Optional[Path] = None) -> List[Rule]:
    text = read_text(pdf_path)
    sections = split_sections(text)
    system_prompt, user_template = load_prompts()
    model = configure_genai(model_id)
    default_scope = {"market": ["AE"], "categories": ["PetSupplies"]}

    all_rules: List[Rule] = []
    raw_dump: Dict[str, Any] = {}

    for section_name, section_text in sections.items():
        user_prompt = user_template.format(section_name=section_name.title(), section_text=section_text)
        response_text = call_llm(model, system_prompt, user_prompt)
        raw_rules = extract_json_array(response_text)
        normalized = [
            normalize_rule(rule, default_scope)
            for rule in raw_rules
        ]
        normalized = [rule for rule in normalized if rule is not None]
        all_rules.extend(normalized)
        raw_dump[section_name] = {
            "prompt": user_prompt,
            "response": response_text,
            "parsed": raw_rules,
        }

    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_file = dump_dir / f"rules_raw_{pdf_path.stem}.json"
        dump_file.write_text(json.dumps(raw_dump, indent=2), encoding="utf-8")

    return dedupe_rules(all_rules)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract policy rules from PDF using an LLM.")
    parser.add_argument("--pdf", required=True, help="Path to the policy PDF (e.g., data/policies/.../source.pdf)")
    parser.add_argument("--out", required=True, help="Path to write the YAML rules file.")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), help="Gemini model id.")
    parser.add_argument("--dump-dir", help="Optional directory to store raw LLM responses.")
    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf)
    out_path = Path(args.out)
    dump_dir = Path(args.dump_dir) if args.dump_dir else None

    try:
        rules = extract_rules_from_pdf(pdf_path, args.model, dump_dir=dump_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    doc = rules_to_yaml(rules)
    save_yaml(doc, out_path)
    print(f"Wrote {len(rules)} rules to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
