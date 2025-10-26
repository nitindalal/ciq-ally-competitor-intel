"""
Lightweight regression checks for the CIQ Ally skill.

Usage:
    python3 -m eval.run_eval                     # run every case in eval/cases
    python3 -m eval.run_eval --case foo          # run just foo.json
    python3 -m eval.run_eval --verbose           # echo extra diagnostics
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skill import run_compare  # noqa

CASES_DIR = Path(__file__).resolve().parent / "cases"


def _load_case(path: Path) -> Dict[str, object]:
    with path.open() as f:
        data = json.load(f)
    data.setdefault("name", path.stem)
    return data


def _evaluate_case(case: Dict[str, object]) -> tuple[List[str], Dict[str, object]]:
    """Run the pipeline for a given case and collect human-friendly errors."""
    errors: List[str] = []
    try:
        result = run_compare(
            case["client_id"],
            case["competitor_id"],
            csv_path=case.get("csv_path", "data/asin_data_filled.csv"),
            market=case.get("market", "AE"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"runtime error: {exc}")
        return errors

    suggestions = result.get("suggestions") or []
    info: Dict[str, object] = {
        "client_id": case["client_id"],
        "competitor_id": case["competitor_id"],
        "suggestion_count": len(suggestions),
        "suggestion_sections": [],
        "draft_snapshot": {},
    }
    sections = [s.get("section") for s in suggestions if isinstance(s, dict)]
    info["suggestion_sections"] = sections
    expectations: Dict[str, object] = case.get("expectations", {})

    min_suggestions = expectations.get("min_suggestions")
    if isinstance(min_suggestions, int) and len(suggestions) < min_suggestions:
        errors.append(f"expected >= {min_suggestions} suggestions, saw {len(suggestions)}")

    required_sections = expectations.get("required_sections") or []
    missing_sections = [sec for sec in required_sections if sec not in sections]
    if missing_sections:
        errors.append(f"missing sections in suggestions: {', '.join(missing_sections)}")

    if expectations.get("require_references"):
        for idx, sugg in enumerate(suggestions, start=1):
            refs = sugg.get("references") if isinstance(sugg, dict) else []
            if not refs:
                errors.append(f"suggestion #{idx} has no references")
                break

    changed_sections = expectations.get("require_changed_sections") or []
    for sec in changed_sections:
        changed = any(
            (s.get("section") == sec)
            and (s.get("after") is not None)
            and (s.get("after") != s.get("before"))
            for s in suggestions
            if isinstance(s, dict)
        )
        if not changed:
            errors.append(f"no suggestion produced a change for section '{sec}'")

    draft_expectations = expectations.get("draft") or {}
    draft = result.get("draft", {})
    if draft:
        bullets_raw = draft.get("bullets") or []
        if isinstance(bullets_raw, str):
            bullets_list = [bullets_raw]
        else:
            bullets_list = list(bullets_raw)
        info["draft_snapshot"] = {
            "title_len": len(draft.get("title", "")),
            "bullets_count": len(bullets_list),
            "description_len": len(draft.get("description", "")),
            "title": draft.get("title", ""),
            "bullets": bullets_list,
        }
        title_max_len = draft_expectations.get("title_max_length")
        if isinstance(title_max_len, int) and len(draft.get("title", "")) > title_max_len:
            errors.append(f"draft title length {len(draft.get('title',''))} exceeds {title_max_len}")

        bullets = bullets_list

        min_bullets = draft_expectations.get("bullets_min_count")
        if isinstance(min_bullets, int) and len(bullets) < min_bullets:
            errors.append(f"draft bullets count {len(bullets)} below {min_bullets}")

        max_bullets = draft_expectations.get("bullets_max_count")
        if isinstance(max_bullets, int) and len(bullets) > max_bullets:
            errors.append(f"draft bullets count {len(bullets)} exceeds {max_bullets}")

    return errors, info


def _print_debug(info: Dict[str, object]) -> None:
    """Pretty-print core signals to help validate failures."""
    if not info:
        return
    print("    client:", info.get("client_id"), "vs", info.get("competitor_id"))
    print("    suggestions:", info.get("suggestion_count"), info.get("suggestion_sections"))
    draft = info.get("draft_snapshot") or {}
    if draft:
        print(
            "    draft: title_len={title_len} bullets={bullets_count} desc_len={description_len}".format(
                **{k: draft.get(k, "-") for k in ("title_len", "bullets_count", "description_len")}
            )
        )
        bullets = draft.get("bullets") or []
        if isinstance(bullets, str):
            bullets = [bullets]
        if bullets:
            sample = bullets[:3]
            more = "" if len(bullets) <= 3 else f" … (+{len(bullets) - 3} more)"
            for idx, bullet in enumerate(sample, start=1):
                print(f"      {idx}. {bullet}")
            if more:
                print(f"      {more}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run small eval cases for CIQ Ally.")
    parser.add_argument(
        "--case",
        metavar="NAME",
        help="Run a single case (matches <NAME>.json inside eval/cases).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra diagnostics (always shown on failures).",
    )
    args = parser.parse_args()

    if not CASES_DIR.exists():
        print("No cases found. Add JSON files under eval/cases.", file=sys.stderr)
        return 1

    case_paths = sorted(CASES_DIR.glob("*.json"))
    if args.case:
        matches = [p for p in case_paths if p.stem == args.case]
        if not matches:
            print(f"Case '{args.case}' not found.", file=sys.stderr)
            return 1
        case_paths = matches

    overall_errors = 0
    for path in case_paths:
        case = _load_case(path)
        errors, info = _evaluate_case(case)
        if errors:
            overall_errors += 1
            print(f"[FAIL] {case['name']}")
            for err in errors:
                print(f"  - {err}")
            _print_debug(info)
        else:
            print(f"[PASS] {case['name']}")
            if args.verbose:
                _print_debug(info)

    return 1 if overall_errors else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
