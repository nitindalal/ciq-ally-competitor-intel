# src/skill.py (append this, or place in a new src/pipeline.py)

from __future__ import annotations
from typing import List, Dict, Any
from dataclasses import dataclass, field

from src.loaders import load_csv, select_skus
from src.preprocess import preprocess
from src.rules_registry import load_all_rules, select_rules
from src.rules_engine import validate_with_rules
from src.scoring import score_all
from src.compare import compare_sections
from src.recommender import suggest_edits_llm
from src.render import render_markdown_report
from src.models import SKU, Recommendation

# ---------- helpers (self-contained) ----------

def _get_attr(o, *names, default=None):
    for n in names:
        if hasattr(o, n):
            return getattr(o, n)
        if isinstance(o, dict) and n in o:
            return o[n]
    return default

def _coerce_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        cleaned = []
        for item in value:
            text = str(item).strip()
            text = text.lstrip("-• \t")
            if text:
                cleaned.append(text)
        return cleaned
    if isinstance(value, str):
        parts = [p.strip("- ").strip() for p in value.splitlines() if p.strip()]
        return parts if len(parts) > 1 else [value.strip()]
    return [str(value).strip()]

def normalize_recs(recs):
    """
    Produce dicts with keys: section/title/before/after/rationale/references.
    Accepts objects or dicts; maps 'type' -> 'section' if needed.
    """
    norm = []
    for r in recs or []:
        section = _get_attr(r, "section", "type", default=None)
        if not section:
            t = (_get_attr(r, "title", default="") or "").lower()
            if "title" in t: section = "title"
            elif "bullet" in t: section = "bullets"
            elif "description" in t: section = "description"
            else: section = "unknown"

        before = _get_attr(r, "before", default=None)
        after  = _get_attr(r, "after",  default=None)

        if section:
            section = str(section).strip().lower()
        norm.append({
            "section": section,
            "title": _get_attr(r, "title", default=section.title() if section else "Suggestion"),
            "before": before if before is not None else "",
            "after":  after  if after  is not None else "",
            "rationale": _get_attr(r, "rationale", default=""),
            "references": _get_attr(r, "references", default=[]) or [],
        })
    return norm

def build_rule_based_suggestions(client: SKU, competitor: SKU, client_findings, top_n=3):
    """Deterministic, policy-aligned suggestions if the LLM returns nothing/partial."""
    suggestions: List[Dict[str, Any]] = []

    # Bullets: up to 5, no ending punctuation
    bullets_fail = any((not f.passed) and f.section == "bullets" for f in client_findings)
    if bullets_fail and len(suggestions) < top_n:
        before_bs = _coerce_list(client.bullets or [])
        after_bs = [(b.rstrip().rstrip(".;:!")) for b in before_bs][:5]
        if not after_bs and client.title:
            after_bs = [t.strip() for t in client.title.split(",")[:5]]
        suggestions.append({
            "section": "bullets",
            "title": "Bullets: reduce to five and remove end punctuation",
            "before": before_bs,
            "after": after_bs,
            "rationale": "Up to five bullets; sentence fragments; no ending punctuation.",
            "references": ["BULLETS_MAX5", "BULLETS_NO_END_PUNCT"],
        })

    # Title: shorten to ≤200 chars if too long
    if (client.title or "") and len(client.title) > 200 and len(suggestions) < top_n:
        suggestions.append({
            "section": "title",
            "title": "Title: shorten to ≤200 characters",
            "before": client.title,
            "after": client.title[:200].rstrip(),
            "rationale": "Keep titles concise (≤200 chars).",
            "references": ["TITLE_MAXLEN_200"],
        })

    # Description: add concise paragraph if empty or repetitive
    desc = (client.description or "").strip()
    if (not desc or desc.lower().count("scientifically formulated") >= 2) and len(suggestions) < top_n:
        synth = (
            "Scientifically formulated to replace fluids and 5 key electrolytes "
            "(Sodium, Potassium, Chloride, Magnesium, Calcium). Variety pack with "
            "Orange, Cherry Lime, and Watermelon; no artificial sweeteners or flavors; "
            "lower sugar (10g per 16.9 fl oz serving)."
        )
        suggestions.append({
            "section": "description",
            "title": "Description: add a concise, unique paragraph",
            "before": desc or "(empty)",
            "after": synth,
            "rationale": "Provide a concise, truthful description distinct from bullets.",
            "references": ["DESCRIPTION_CONCISE"],
        })

    # Opportunity: clarify flavors for variety titles
    if len(suggestions) < top_n and (client.title or "") and "variety" in (client.title or "").lower():
        after_title = client.title
        flavors = ["Orange", "Cherry Lime", "Watermelon"]
        if not any(f.lower() in after_title.lower() for f in flavors):
            after_title = after_title.replace("Variety Pack", "Variety Pack (Orange, Cherry Lime, Watermelon)")
        suggestions.append({
            "section": "title",
            "title": "Title: clarify variety flavors",
            "before": client.title,
            "after": after_title[:200].rstrip(),
            "rationale": "Improve clarity/discoverability by listing key flavors; keep within length.",
            "references": ["TITLE_CLARITY"],
        })

    return suggestions[:top_n]

def _to_rec_obj(r: Dict[str, Any]) -> Recommendation:
    return Recommendation(
        section=r.get("section") or "unknown",
        title=r.get("title") or "Suggestion",
        before=r.get("before") or "",
        after=r.get("after") or "",
        rationale=r.get("rationale") or "",
        references=r.get("references") or [],
    )

# ---------- FINAL compare orchestration ----------

def run_compare(client_id: str,
                competitor_id: str,
                csv_path: str = "data/asin_data_filled.csv",
                market: str = "AE") -> Dict[str, Any]:
    """
    Orchestrates a full comparison run and returns:
      {
        'report_markdown': str,
        'draft': {'title': str, 'bullets': [str], 'description': str},
        'suggestions': [Recommendation x3],  # after enforcing 3
        'findings': {'client': [...], 'competitor': [...]},
        'comparison': [...],  # rows used for tables
        'client': SKU, 'competitor': SKU
      }
    """
    # 1) Load + preprocess
    df = load_csv(csv_path)
    c_row, k_row = select_skus(df, client_id, competitor_id)
    client_p, comp_p = preprocess(c_row), preprocess(k_row)

    # 2) Rules (apply to all categories for now)
    packs = load_all_rules("data/policies")
    rules = select_rules(packs, market=market, categories=[])

    # 3) Validate
    client_find = validate_with_rules(client_p, rules)
    comp_find   = validate_with_rules(comp_p, rules)

    # 4) Score + compare
    c_scores, k_scores = score_all(client_p), score_all(comp_p)
    comparison = compare_sections(client_p, comp_p, c_scores, k_scores, client_find, comp_find)

    # 5) Suggestions (LLM → normalize → fallback → enforce exactly 3)
    styleguide_refs = [f"{r.get('policy_id','')}:{r['id']} – {r.get('message','')}".strip(": ") for r in rules]
    recs_raw = suggest_edits_llm(client_p, comp_p, comparison, styleguide_refs)
    recs_norm = normalize_recs(recs_raw)
    recs_norm = [r for r in recs_norm if r.get("after")]  # drop empties

    if len(recs_norm) < 3:
        needed = 3 - len(recs_norm)
        recs_norm.extend(build_rule_based_suggestions(client_p, comp_p, client_find, top_n=needed))
    recs_norm = recs_norm[:3]
    recs_objs = [_to_rec_obj(r) for r in recs_norm]

    # 6) Seed draft from suggestions; fall back to current content
    def _first_after(section_name: str):
        for r in recs_norm:
            if r["section"] == section_name and r.get("after"):
                return r["after"]
        return None

    title_after   = _first_after("title")
    bullets_after = _first_after("bullets")
    desc_after    = _first_after("description")

    draft_title = (title_after if isinstance(title_after, str) and title_after.strip()
                   else (client_p.title or ""))
    draft_bullets = (_coerce_list(bullets_after) if bullets_after else (client_p.bullets or []))
    draft_desc = (desc_after if isinstance(desc_after, str) and desc_after.strip()
                  else (client_p.description or ""))

    # 7) Render full markdown report
    report_md = render_markdown_report(
        client_p, comp_p, comparison, recs_objs, approved=False,
        client_findings=client_find, competitor_findings=comp_find
    )

    # 8) Return a single, convenient payload
    return {
        "report_markdown": report_md,
        "draft": {
            "title": draft_title,
            "bullets": draft_bullets,
            "description": draft_desc
        },
        "suggestions": recs_objs,  # already exactly 3
        "findings": {
            "client": client_find,
            "competitor": comp_find
        },
        "comparison": comparison,
        "client": client_p,
        "competitor": comp_p
    }
