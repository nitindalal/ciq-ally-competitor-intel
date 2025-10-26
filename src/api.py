from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx
import markdown2
import os

from .skill import run_compare, _coerce_list
from .loaders import load_csv, select_skus
from .preprocess import preprocess
from .rules_registry import load_all_rules, select_rules
from .rules_engine import validate_with_rules
from eval.run_eval import CASES_DIR as EVAL_CASES_DIR, _load_case as eval_load_case, _evaluate_case as eval_evaluate_case, _print_debug as eval_print_debug

# ---------- Pydantic DTOs ----------

ContentField = Union[str, List[str]]


class CompareRequest(BaseModel):
    client_id: str = Field(..., description="Client SKU identifier.")
    competitor_id: str = Field(..., description="Competitor SKU identifier.")
    market: str = Field(default="AE", description="Market code to filter policy packs.")
    csv_path: str = Field(default="data/asin_data_filled.csv", description="Path to the catalog CSV.")


class DraftDTO(BaseModel):
    title: str
    bullets: List[str]
    description: str


class SuggestionDTO(BaseModel):
    section: str
    title: str
    before: Optional[ContentField] = None
    after: Optional[ContentField] = None
    rationale: str = ""
    references: List[str] = []


class FindingDTO(BaseModel):
    section: str
    rule_id: str
    passed: bool
    message: str
    citation: Optional[str] = None
    severity: Optional[str] = None


class ComparisonRowDTO(BaseModel):
    section: str
    metric: str
    client: Union[str, float, int]
    competitor: Union[str, float, int]
    gap: Union[str, float, int]
    compliance_notes: List[str] = []


class SKUDetailsDTO(BaseModel):
    sku_id: str
    title: str
    bullets: List[str]
    description: str
    brand: Optional[str] = None
    category: Optional[str] = None


class CompareResponse(BaseModel):
    report_markdown: str
    draft: DraftDTO
    suggestions: List[SuggestionDTO]
    findings: Dict[str, List[FindingDTO]]
    comparison: List[ComparisonRowDTO]
    client: SKUDetailsDTO
    competitor: SKUDetailsDTO


class DraftPayload(BaseModel):
    title: str
    bullets: List[str]
    description: str


class ValidateRequest(BaseModel):
    client_id: str
    market: str = "AE"
    csv_path: str = "data/asin_data_filled.csv"
    draft: DraftPayload


class ValidateResponse(BaseModel):
    passed: bool
    findings: List[FindingDTO]


class FinalizeRequest(BaseModel):
    client_id: str
    market: str = "AE"
    csv_path: str = "data/asin_data_filled.csv"
    draft: DraftPayload


class FinalizeResponse(BaseModel):
    final_markdown: str
    draft: DraftDTO
    findings: List[FindingDTO] = []


class EmailRequest(BaseModel):
    to_email: str = Field(..., description="Recipient email address.")
    subject: str = Field(default="CIQ Ally Draft", description="Email subject line.")
    from_email: Optional[str] = Field(default=None, description="Sender email override.")
    body_markdown: str = Field(..., description="Markdown content to send.")


class EmailResponse(BaseModel):
    status: str


# ---------- Serialization helpers ----------

def _serialize_finding(finding: Any) -> FindingDTO:
    data = _coerce_to_dict(finding)
    severity = getattr(finding, "severity", data.get("severity"))
    payload = {
        "section": data.get("section"),
        "rule_id": data.get("rule_id"),
        "passed": data.get("passed"),
        "message": data.get("message"),
        "citation": data.get("citation"),
        "severity": severity,
    }
    return FindingDTO(**payload)


def _serialize_comparison(row: Any) -> ComparisonRowDTO:
    data = _coerce_to_dict(row)
    return ComparisonRowDTO(
        section=data.get("section"),
        metric=data.get("metric"),
        client=data.get("client"),
        competitor=data.get("competitor"),
        gap=data.get("gap"),
        compliance_notes=data.get("compliance_notes") or [],
    )


def _serialize_sku(sku: Any) -> SKUDetailsDTO:
    data = _coerce_to_dict(sku)
    return SKUDetailsDTO(
        sku_id=data.get("sku_id", ""),
        title=data.get("title", ""),
        bullets=list(data.get("bullets") or []),
        description=data.get("description", ""),
        brand=data.get("brand"),
        category=data.get("category"),
    )


def _serialize_suggestion(s: Dict[str, Any]) -> SuggestionDTO:
    # Ensure lists instead of None
    references = s.get("references") or []
    return SuggestionDTO(
        section=s.get("section", "unknown"),
        title=s.get("title", "Suggestion"),
        before=s.get("before"),
        after=s.get("after"),
        rationale=s.get("rationale", ""),
        references=references,
    )


def _serialize_findings_bucket(findings: List[Any]) -> List[FindingDTO]:
    return [_serialize_finding(f) for f in findings]


def _coerce_to_dict(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    if hasattr(obj, "_asdict"):
        return obj._asdict()  # type: ignore[attr-defined]
    try:
        return dict(obj)
    except TypeError:
        try:
            return vars(obj)
        except TypeError:
            return {}


# ---------- FastAPI application ----------

app = FastAPI(
    title="CIQ Ally — Competitor Content Intelligence API",
    version="1.0.0",
    description="LLM-assisted SKU comparison service that powers the CIQ Ally demo.",
)


@app.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest) -> CompareResponse:
    try:
        result = run_compare(
            client_id=req.client_id,
            competitor_id=req.competitor_id,
            csv_path=req.csv_path,
            market=req.market,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - bubble unexpected errors
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    findings = {
        "client": _serialize_findings_bucket(result.get("findings", {}).get("client", [])),
        "competitor": _serialize_findings_bucket(result.get("findings", {}).get("competitor", [])),
    }
    suggestions = [_serialize_suggestion(s) for s in result.get("suggestions", [])]

    include_report = getattr(req, "include_report", True)
    include_draft = getattr(req, "include_draft", True)
    include_suggestions = getattr(req, "include_suggestions", True)
    include_findings = getattr(req, "include_findings", True)
    include_comparison = getattr(req, "include_comparison", True)

    report_markdown = result.get("report_markdown", "") if include_report else ""
    draft_payload = DraftDTO(**result.get("draft", {})) if include_draft else DraftDTO(title="", bullets=[], description="")
    suggestions_payload = suggestions if include_suggestions else []
    findings_payload = findings if include_findings else {"client": [], "competitor": []}
    comparison_payload = [_serialize_comparison(row) for row in result.get("comparison", [])] if include_comparison else []

    response = CompareResponse(
        report_markdown=report_markdown,
        draft=draft_payload,
        suggestions=suggestions_payload,
        findings=findings_payload,
        comparison=comparison_payload,
        client=_serialize_sku(result.get("client")),
        competitor=_serialize_sku(result.get("competitor")),
    )
    return response


@app.post("/validate", response_model=ValidateResponse)
def validate(req: ValidateRequest) -> ValidateResponse:
    client = _load_client(req.client_id, req.csv_path)
    draft = _sanitize_draft(req.draft)

    client.title = draft.title
    client.bullets = draft.bullets
    client.description = draft.description

    rules = _load_rules(req.market)
    findings = validate_with_rules(client, rules)
    serialized = [_serialize_finding(f) for f in findings]
    passed = all(f.passed for f in findings)
    return ValidateResponse(passed=passed, findings=serialized)


@app.post("/finalize", response_model=FinalizeResponse)
def finalize(req: FinalizeRequest) -> FinalizeResponse:
    client = _load_client(req.client_id, req.csv_path)
    draft = _sanitize_draft(req.draft)

    client.title = draft.title
    client.bullets = draft.bullets
    client.description = draft.description

    rules = _load_rules(req.market)
    findings = validate_with_rules(client, rules)
    serialized = [_serialize_finding(f) for f in findings]

    final_markdown = _render_final_markdown(client.sku_id, draft)
    return FinalizeResponse(final_markdown=final_markdown, draft=draft, findings=serialized)


@app.post("/email", response_model=EmailResponse)
async def send_email(req: EmailRequest) -> EmailResponse:
    cfg = _mailjet_config()
    if not cfg:
        raise HTTPException(status_code=500, detail="Mailjet settings not configured")

    html_body = markdown2.markdown(req.body_markdown or "")
    from_email = req.from_email or cfg["from_email"]
    from_name = cfg.get("from_name") or "CIQ Ally"

    payload = {
        "Messages": [
            {
                "From": {"Email": from_email, "Name": from_name},
                "To": [{"Email": req.to_email}],
                "Subject": req.subject,
                "TextPart": req.body_markdown,
                "HTMLPart": html_body,
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.mailjet.com/v3.1/send",
                json=payload,
                auth=(cfg["api_key"], cfg["secret_key"]),
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=resp.text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return EmailResponse(status="sent")


@app.post("/eval", response_model=EvalResponse)
def run_eval(req: EvalRequest) -> EvalResponse:
    case_paths = sorted(EVAL_CASES_DIR.glob("*.json"))
    if req.case:
        match = [p for p in case_paths if p.stem == req.case]
        if not match:
            raise HTTPException(status_code=404, detail=f"Case '{req.case}' not found.")
        case_paths = match

    results: List[EvalCaseResult] = []
    overall_pass = True

    for path in case_paths:
        case = eval_load_case(path)
        errors, info = eval_evaluate_case(case)
        passed = not errors
        overall_pass = overall_pass and passed
        payload = info if req.verbose else {}
        results.append(EvalCaseResult(name=case["name"], passed=passed, errors=errors, info=payload))

    return EvalResponse(overall_pass=overall_pass, results=results)


def _load_client(client_id: str, csv_path: str):
    df = load_csv(csv_path)
    client_row, _ = select_skus(df, client_id, client_id)
    return preprocess(client_row)


def _load_rules(market: str):
    packs = load_all_rules("data/policies")
    return select_rules(packs, market=market, categories=[])


def _sanitize_draft(draft: DraftPayload) -> DraftDTO:
    title = (draft.title or "").strip()
    bullets = _coerce_list(draft.bullets)
    description = (draft.description or "").strip()
    return DraftDTO(title=title, bullets=bullets, description=description)


def _render_final_markdown(sku_id: str, draft: DraftDTO) -> str:
    lines = [
        f"# FINAL – {sku_id}",
        "",
        "## Title",
        draft.title or "(empty)",
        "",
        "## Bullets",
    ]
    if draft.bullets:
        lines.extend(f"- {bullet}" for bullet in draft.bullets)
    else:
        lines.append("(none)")
    lines.extend(
        [
            "",
            "## Description",
            draft.description or "(empty)",
        ]
    )
    return "\n".join(lines)


def _mailjet_config() -> Optional[Dict[str, Any]]:
    api_key = os.getenv("MAILJET_API_KEY")
    secret_key = os.getenv("MAILJET_SECRET_KEY")
    from_email = os.getenv("MAILJET_FROM_EMAIL")
    from_name = os.getenv("MAILJET_FROM_NAME")

    if not (api_key and secret_key and from_email):
        return None
    return {
        "api_key": api_key,
        "secret_key": secret_key,
        "from_email": from_email,
        "from_name": from_name,
    }
class EvalRequest(BaseModel):
    case: Optional[str] = Field(default=None, description="Optional case name to run (without .json). Run all cases if omitted.")
    verbose: bool = Field(default=False, description="Include debug information for each case.")


class EvalCaseResult(BaseModel):
    name: str
    passed: bool
    errors: List[str] = []
    info: Dict[str, Any] = {}


class EvalResponse(BaseModel):
    overall_pass: bool
    results: List[EvalCaseResult]
