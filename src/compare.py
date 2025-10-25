# src/compare.py
from typing import List, Optional
from .models import SKU, SectionScores, ComparisonRow, Finding

def _fmt(v):
    return "n/a" if v is None else v

def _rows_for_section(section: str, cs: SectionScores, ks: SectionScores) -> List[ComparisonRow]:
    rows: List[ComparisonRow] = []
    for m, v in cs.metrics.items():
        kv = ks.metrics.get(m)
        gap = (v - kv) if isinstance(v, (int, float)) and isinstance(kv, (int, float)) else "-"
        rows.append(ComparisonRow(section=section, metric=m, client=_fmt(v), competitor=_fmt(kv), gap=gap))
    return rows

# -------- Policy aggregation helpers --------

def _policy_counts(findings: List[Finding], section: Optional[str] = None):
    fs = [f for f in findings if (section is None or f.section == section)]
    total = len(fs)
    errors = sum(1 for f in fs if (not f.passed) and getattr(f, "severity", "warning") == "error")
    warnings = sum(1 for f in fs if (not f.passed) and getattr(f, "severity", "warning") != "error")
    return total, errors, warnings

def _policy_rows(tag: str, client_find: List[Finding], comp_find: List[Finding]) -> List[ComparisonRow]:
    rows: List[ComparisonRow] = []
    ct, ce, cw = _policy_counts(client_find)
    kt, ke, kw = _policy_counts(comp_find)
    rows.append(ComparisonRow(section=f'policy:{tag}', metric='rules_total', client=ct, competitor=kt, gap='-'))
    rows.append(ComparisonRow(section=f'policy:{tag}', metric='errors',      client=ce, competitor=ke, gap=ce-ke))
    rows.append(ComparisonRow(section=f'policy:{tag}', metric='warnings',    client=cw, competitor=kw, gap=cw-kw))
    return rows

def _policy_rows_per_section(client_find: List[Finding], comp_find: List[Finding]) -> List[ComparisonRow]:
    rows: List[ComparisonRow] = []
    for sec in ['title', 'bullets', 'description']:
        ct, ce, cw = _policy_counts(client_find, sec)
        kt, ke, kw = _policy_counts(comp_find, sec)
        rows.append(ComparisonRow(section=f'policy:{sec}', metric='errors',   client=ce, competitor=ke, gap=ce-ke))
        rows.append(ComparisonRow(section=f'policy:{sec}', metric='warnings', client=cw, competitor=kw, gap=cw-kw))
    return rows

def _failed_ids(findings: List[Finding]) -> List[str]:
    return [getattr(f, "rule_id", "") for f in findings if not getattr(f, "passed", True)]

def _compact_rules(ids: List[str], n: int = 3) -> str:
    if not ids:
        return "none"
    head = [i for i in ids if i][:n]
    rest = max(0, len([i for i in ids if i]) - len(head))
    s = ", ".join(head)
    if rest > 0:
        s += f" +{rest} more"
    return s

# -------- Main compare --------

def compare_sections(client: SKU, comp: SKU,
                     client_scores: dict, comp_scores: dict,
                     client_findings: List[Finding], comp_findings: List[Finding]) -> List[ComparisonRow]:
    table: List[ComparisonRow] = []

    # Content metrics
    for section in ['title', 'bullets', 'description']:
        table.extend(_rows_for_section(section, client_scores[section], comp_scores[section]))

    # Policy-aware compact violations row (replaces old generic "compliance | violations")
    client_failed = _failed_ids(client_findings)
    comp_failed   = _failed_ids(comp_findings)
    table.append(ComparisonRow(
        section='policy:violations',
        metric='failed_rules',
        client=_compact_rules(client_failed, 3),
        competitor=_compact_rules(comp_failed, 3),
        gap='-'
    ))

    # Policy overview (overall + per-section)
    table.extend(_policy_rows('overall', client_findings, comp_findings))
    table.extend(_policy_rows_per_section(client_findings, comp_findings))

    return table
