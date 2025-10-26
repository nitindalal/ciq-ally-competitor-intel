# src/skill.py
from __future__ import annotations
from typing import Dict, Any, List
from src.loaders import load_csv, select_skus
from src.preprocess import preprocess
from src.rules_registry import load_all_rules, select_rules
from src.rules_engine import validate_with_rules
from src.scoring import score_all
from src.compare import compare_sections
from src.recommender import suggest_edits_llm
from src.render import render_markdown_report
from src.models import SKU, Recommendation

DATA_PATH = "data/asin_data_filled.csv"
POLICY_PATH = "data/policies"
DEFAULT_MARKET = "AE"

# ---------- helpers ----------
def _get_attr(o, *names, default=None):
    for n in names:
        if hasattr(o, n):
            return getattr(o, n)
        if isinstance(o, dict) and n in o:
            return o[n]
    return default

def _coerce_list(x):
    """
    Normalizes bullets into a clean list (accepts list or multiline string).
    """
    if x is None:
        return []
    if isinstance(x, list):
        cleaned = []
        for item in x:
            text = str(item).strip()
            text = text.lstrip("-• \t")
            if text:
                cleaned.append(text)
        return cleaned
    if isinstance(x, str):
        parts = [p.strip("-• \t") for p in x.split("\n")]
        return [p for p in parts if p]
    return [str(x).strip()]

def _normalize_recs(recs):
    """
    Normalize LLM output to dicts with: section/title/before/after/rationale/references
    """
    out = []
    for r in (recs or []):
        section = _get_attr(r, "section", "type", default=None)
        if not section:
            t = (_get_attr(r, "title", default="") or "").lower()
            if "title" in t: section = "title"
            elif "bullet" in t: section = "bullets"
            elif "description" in t: section = "description"
            else: section = "unknown"
        if section:
            section = str(section).strip().lower()
        out.append({
            "section": section,
            "title": _get_attr(r, "title", default=section.title() if section else "Suggestion"),
            "before": _get_attr(r, "before", default=""),
            "after":  _get_attr(r, "after",  default=""),
            "rationale": _get_attr(r, "rationale", default=""),
            "references": _get_attr(r, "references", default=[]) or [],
        })
    return out

def _rule_fallbacks(client: SKU, competitor: SKU, client_findings, top_n=3):
    """
    Deterministic, policy-aligned suggestions to guarantee we always have 3.
    """
    suggestions: List[Dict[str, Any]] = []

    # Bullets: max 5 + no ending punctuation
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

    # Title: shorten to ≤200 chars
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

    # Opportunity: clarify flavors if title has “Variety”
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
            "rationale": "List key flavors for clarity; keep within length.",
            "references": ["TITLE_CLARITY"],
        })

    return suggestions[:top_n]

def _to_rec_obj(r: Dict[str, Any]):
    """
    Convert normalized dict -> your models.Recommendation.
    Avoid passing fields (like 'section' or 'references') that the dataclass may not accept.
    """
    try:
        # common case: Recommendation(title, before, after, rationale=...)
        return Recommendation(
            title=r.get("title") or "Suggestion",
            before=r.get("before") or "",
            after=r.get("after") or "",
            rationale=r.get("rationale") or ""
        )
    except TypeError:
        # fallback if your dataclass doesn't have 'rationale'
        return Recommendation(
            title=r.get("title") or "Suggestion",
            before=r.get("before") or "",
            after=r.get("after") or ""
        )


# ---------- main orchestration ----------
def run_compare(client_id: str,
                competitor_id: str,
                csv_path: str = DATA_PATH,
                market: str = DEFAULT_MARKET) -> Dict[str, Any]:
    """
    Full pipeline:
      - load + preprocess
      - rules validate
      - score + compare
      - LLM suggestions (normalized) with deterministic fallbacks to ensure 3
      - seed draft from suggestions
      - render full markdown report (with findings)
    Returns a dict with report, draft, suggestions, findings, comparison, and SKU objects.
    """
    # Load + preprocess
    df = load_csv(csv_path)
    c_row, k_row = select_skus(df, client_id, competitor_id)
    client_p, comp_p = preprocess(c_row), preprocess(k_row)

    # Rules
    packs = load_all_rules(POLICY_PATH)
    rules = select_rules(packs, market=market, categories=[])

    # Validate
    client_find = validate_with_rules(client_p, rules)
    comp_find   = validate_with_rules(comp_p, rules)

    # Score + compare
    c_scores, k_scores = score_all(client_p), score_all(comp_p)
    comparison = compare_sections(client_p, comp_p, c_scores, k_scores, client_find, comp_find)

    # Suggestions (LLM → normalize → drop empties → fallbacks → exactly 3)
    styleguide_refs = [f"{r.get('policy_id','')}:{r['id']} – {r.get('message','')}".strip(": ") for r in rules]
    recs_raw = suggest_edits_llm(client_p, comp_p, comparison, styleguide_refs)
    recs_norm = _normalize_recs(recs_raw)
    recs_norm = [r for r in recs_norm if r.get("after")]
    if len(recs_norm) < 3:
        needed = 3 - len(recs_norm)
        recs_norm.extend(_rule_fallbacks(client_p, comp_p, client_find, top_n=needed))
    recs_norm = recs_norm[:3]
    # recs_objs = [_to_rec_obj(r) for r in recs_norm]

    # Seed draft
    def _first_after(section_name: str):
        for r in recs_norm:
            if r["section"] == section_name and r.get("after"):
                return r["after"]
        return None
    title_after   = _first_after("title")
    bullets_after = _first_after("bullets")
    desc_after    = _first_after("description")

    draft = {
        "title": (title_after if isinstance(title_after, str) and title_after.strip() else (client_p.title or "")),
        "bullets": (_coerce_list(bullets_after) if bullets_after else (client_p.bullets or [])),
        "description": (desc_after if isinstance(desc_after, str) and desc_after.strip() else (client_p.description or "")),
    }

    # Render report (renderer already supports findings & policy sections)
    report_md = render_markdown_report(
    client_p, comp_p, comparison, recs_norm, False, client_find, comp_find)


    return {
        "client": client_p,
        "competitor": comp_p,
        "comparison": comparison,
        "report_markdown": report_md,
        "draft": draft,
        "suggestions": recs_norm,          # exactly 3
        "findings": {"client": client_find, "competitor": comp_find},
    }
