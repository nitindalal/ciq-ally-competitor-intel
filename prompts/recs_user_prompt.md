Task: Compare a client SKU and a competitor SKU, then produce **Top 3** compliant edits to improve the client content.

Client
Title:
{client_title}

Bullets:
{client_bullets}

Description:
{client_desc}

Competitor
Title:
{comp_title}

Bullets:
{comp_bullets}

Description:
{comp_desc}

Quantitative Comparison
{comparison_rows}

Style-Guide References
{styleguide_refs}

Output format (strict JSON array of 3 objects):
[
  {{
    "title": "...",
    "before": "...",
    "after": "...",
    "rationale": "...",
    "references": ["competitor:<signal>", "styleguide:<marker>"]
  }},
  ...
]
