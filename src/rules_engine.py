# src/rules_engine.py
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable, Union
from .models import SKU, Finding

# ---- Rule model (dicts from YAML are fine; dataclass helps type hints)
@dataclass
class Rule:
    id: str
    section: str                 # title | bullets | description | images
    type: str                    # max_length | max_count | forbidden_regex | ...
    params: Dict[str, Any]
    severity: str = "warning"    # info | warning | error
    message: str = ""
    citation: Optional[str] = None
    policy_id: Optional[str] = None  # set by rules_registry.select_rules()
    scope: Optional[Dict[str, Any]] = None

RuleLike = Union[Rule, Dict[str, Any]]

# ---- Getters for each section
SectionGetter = Callable[[SKU], Any]
SECTION_GETTERS: Dict[str, SectionGetter] = {
    "title": lambda s: s.title or "",
    "bullets": lambda s: s.bullets or [],
    "description": lambda s: s.description or "",
    "images": lambda s: s.image_urls or [],
}

# ---- Helpers
def _rx(pattern: str, flags: str = "") -> re.Pattern:
    f = 0
    if "i" in flags.lower(): f |= re.IGNORECASE
    return re.compile(pattern, f)

# ---- Check implementations
def check_max_length(value: Any, params: Dict[str, Any]) -> bool:
    if not isinstance(value, str): return True
    return len(value) <= int(params["value"])

def check_min_length(value: Any, params: Dict[str, Any]) -> bool:
    if not isinstance(value, str): return True
    return len(value) >= int(params["value"])

def check_max_count(value: Any, params: Dict[str, Any]) -> bool:
    if not isinstance(value, list): return True
    return len(value) <= int(params["value"])

def check_min_count(value: Any, params: Dict[str, Any]) -> bool:
    if not isinstance(value, list): return True
    return len(value) >= int(params["value"])

def check_forbidden_regex(value: Any, params: Dict[str, Any]) -> bool:
    if not isinstance(value, str): return True
    return _rx(params["pattern"], params.get("flags","")).search(value) is None

def check_required_regex(value: Any, params: Dict[str, Any]) -> bool:
    if not isinstance(value, str): return True
    return _rx(params["pattern"], params.get("flags","")).search(value) is not None

def check_forbidden_regex_each(value: Any, params: Dict[str, Any]) -> bool:
    if not isinstance(value, list): return True
    r = _rx(params["pattern"], params.get("flags",""))
    return all(r.search((v or "")) is None for v in value)

def check_no_ending_punct(value: Any, params: Dict[str, Any]) -> bool:
    if not isinstance(value, list): return True
    bad = set(list(params.get("punctuation", ".;:!")))
    return all((not v) or (str(v).rstrip() and str(v).rstrip()[-1] not in bad) for v in value)

def check_no_urls_emails(value: Any, _params: Dict[str, Any]) -> bool:
    if not isinstance(value, str): return True
    return not re.search(r"(https?://|www\.|\S+@\S+)", value, re.I)

def check_image_constraint(value: Any, params: Dict[str, Any]) -> bool:
    """
    Placeholder: without downloading/analyzing the image we return True.
    You can wire an image-audit module later and use params like:
      {white_bg: true, min_px: 500, occupancy_min: 0.8}
    """
    return True

CHECKS: Dict[str, Callable[[Any, Dict[str, Any]], bool]] = {
    "max_length": check_max_length,
    "min_length": check_min_length,
    "max_count": check_max_count,
    "min_count": check_min_count,
    "forbidden_regex": check_forbidden_regex,
    "required_regex": check_required_regex,
    "forbidden_regex_each": check_forbidden_regex_each,
    "no_ending_punct": check_no_ending_punct,
    "no_urls_emails": check_no_urls_emails,
    "image_constraint": check_image_constraint,
}

def _as_rule(r: RuleLike) -> Rule:
    if isinstance(r, Rule): return r
    return Rule(
        id=r["id"],
        section=r["section"],
        type=r["type"],
        params=r.get("params", {}),
        severity=r.get("severity", "warning"),
        message=r.get("message", ""),
        citation=r.get("citation"),
        policy_id=r.get("policy_id"),
        scope=r.get("scope"),
    )

def validate_with_rules(sku, rules: List):  # rules can be dicts or Rule objects
    """
    Run all policy rules against a single SKU and return Finding[].

    - Namespaces rule_id as "<policy_id>:<id>" when policy_id is present.
    - Copies the rule's severity onto the Finding (for aggregation later).
    - Includes the human-readable rule message (prefixed with policy_id for traceability).
    """
    findings: List[Finding] = []

    for raw in rules:
        # Normalize to a Rule object (handles dicts from YAML)
        rule = _as_rule(raw)

        # Get section value (title/bullets/description/images)
        getter = SECTION_GETTERS.get(rule.section)
        if not getter:
            continue
        value = getter(sku)

        # Find the check implementation
        check_fn = CHECKS.get(rule.type)
        if not check_fn:
            continue

        # Evaluate
        passed = check_fn(value, rule.params)

        # Build a namespaced rule id and message
        namespaced_id = f"{rule.policy_id}:{rule.id}" if rule.policy_id else rule.id
        message = rule.message or rule.id
        if rule.policy_id:
            message = f"{rule.policy_id}:{rule.id} – {message}"

        # Create the finding
        finding = Finding(
            section=rule.section,
            rule_id=namespaced_id,
            passed=passed,
            message=message,
            citation=rule.citation
        )

        # Carry severity through so compare/render can aggregate counts
        setattr(finding, "severity", getattr(rule, "severity", "warning"))

        findings.append(finding)

    return findings