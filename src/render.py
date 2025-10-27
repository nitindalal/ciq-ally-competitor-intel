# src/render.py
from typing import List, Any
from .models import SKU, ComparisonRow

def _get_attr(o, name, default=None):
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)

def _fmt_block(val):
    if isinstance(val, list):
        return "\n".join(f"- {v}" for v in val)
    return val or ""

def _blockquote(text):
    if not text:
        return ">\n"
    return "> " + text.replace("\n", "\n> ") + "\n"

def render_markdown_report(
    client: SKU,
    competitor: SKU,
    comparison: List[ComparisonRow],
    recs: List[Any],
    approved: bool,
    client_findings=None,
    competitor_findings=None
) -> str:
    lines = []
    lines.append(f"# Competitor Content Intelligence: {client.sku_id} vs {competitor.sku_id}")
    lines.append(f"**Client title:** {client.title or ''}")
    lines.append(f"**Competitor title:** {competitor.title or ''}\n")
    lines.append("## Summary")
    lines.append("Compared title, bullets, and description; flagged compliance gaps.\n")

    # Snapshot of raw listing values to confirm correct products
    def _cell(value):
        text = (value or "").strip() if isinstance(value, str) else str(value or "")
        if not text:
            text = "(empty)"
        return text.replace("|", "\\|").replace("\n", "<br>")

    def _join_bullets(items):
        if not items:
            return "(none)"
        joined = "<br>".join(f"{idx+1}. {item}" for idx, item in enumerate(items))
        return _cell(joined)

    lines.append("## Listing Snapshot")
    lines.append("| Field | Client | Competitor |")
    lines.append("|---|---|---|")
    lines.append(f"| SKU | {_cell(client.sku_id)} | {_cell(competitor.sku_id)} |")
    lines.append(f"| Title | {_cell(client.title)} | {_cell(competitor.title)} |")
    lines.append(f"| Brand | {_cell(getattr(client, 'brand', '') or '(unknown)')} | {_cell(getattr(competitor, 'brand', '') or '(unknown)')} |")
    lines.append(f"| Category | {_cell(getattr(client, 'category', '') or '(unknown)')} | {_cell(getattr(competitor, 'category', '') or '(unknown)')} |")
    lines.append(f"| Bullet Count | {_cell(len(client.bullets or []))} | {_cell(len(competitor.bullets or []))} |")
    lines.append(f"| Bullets | {_join_bullets(client.bullets or [])} | {_join_bullets(competitor.bullets or [])} |")
    lines.append(f"| Description | {_cell(client.description)} | {_cell(competitor.description)} |")
    lines.append("")

    # Comparison table
    lines.append("## Comparison Table")
    lines.append("| Section | Metric | Client | Competitor | Gap |")
    lines.append("|---|---|---:|---:|---:|")
    for r in comparison:
        lines.append(f"| {r.section} | {r.metric} | {r.client} | {r.competitor} | {r.gap} |")
    lines.append("")

    # Findings tables (optional)
    def _findings_table(title, finds):
        lines.append(f"### {title}")
        lines.append("| Rule | Section | Passed | Message | Citation |")
        lines.append("|---|---|:--:|---|---|")
        if not finds:
            lines.append("| (none) | - | - | - | - |")
            return
        for f in finds:
            passed = "✅" if getattr(f, "passed", False) else "❌"
            rid = getattr(f, "rule_id", "")
            sec = getattr(f, "section", "")
            msg = getattr(f, "message", "")
            cit = getattr(f, "citation", "")
            lines.append(f"| {rid} | {sec} | {passed} | {msg} | {cit} |")

    lines.append("## Compliance Findings")
    _findings_table("Client", client_findings or [])
    _findings_table("Competitor", competitor_findings or [])
    lines.append("")

    # Top 3 suggestions
    lines.append("## Top 3 Suggested Edits (Compliant)")
    if not recs:
        lines.append("_No suggestions available._\n")
    else:
        for i, rec in enumerate(recs[:3], 1):
            title = _get_attr(rec, "title", f"Suggestion {i}")
            before = _get_attr(rec, "before", "")
            after  = _get_attr(rec, "after", "")
            rationale = _get_attr(rec, "rationale", "")
            refs = _get_attr(rec, "references", []) or []

            lines.append(f"### {i}. {title}")
            lines.append("**Before**")
            lines.append(_blockquote(_fmt_block(before)))
            lines.append("**After**")
            lines.append(_blockquote(_fmt_block(after)))
            if rationale:
                lines.append(f"_Rationale:_ {rationale}")
            if refs:
                lines.append(f"_References:_ " + "; ".join(str(x) for x in refs))
            lines.append("")

    lines.append(f"**Approved:** {'Yes' if approved else 'No'}")
    return "\n".join(lines)   # ← IMPORTANT
