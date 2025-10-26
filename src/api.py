from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import aiosmtplib
import markdown2
from email.message import EmailMessage
import os

from .skill import run_compare, _coerce_list
from .loaders import load_csv, select_skus
from .preprocess import preprocess
from .rules_registry import load_all_rules, select_rules
from .rules_engine import validate_with_rules

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

    response = CompareResponse(
        report_markdown=result.get("report_markdown", ""),
        draft=DraftDTO(**result.get("draft", {})),
        suggestions=suggestions,
        findings=findings,
        comparison=[_serialize_comparison(row) for row in result.get("comparison", [])],
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
    cfg = _smtp_config()
    if not cfg:
        raise HTTPException(status_code=500, detail="SMTP settings not configured")

    html_body = markdown2.markdown(req.body_markdown)
    msg = EmailMessage()
    msg["Subject"] = req.subject
    msg["From"] = req.from_email or cfg["from_email"]
    msg["To"] = req.to_email
    msg.set_content(req.body_markdown)
    msg.add_alternative(html_body, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg["host"],
            port=cfg["port"],
            start_tls=True,
            username=cfg["username"],
            password=cfg["password"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return EmailResponse(status="sent")


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


def _smtp_config() -> Optional[Dict[str, Any]]:
    host = os.getenv("MAILJET_SMTP_HOST", "in-v3.mailjet.com")
    port = int(os.getenv("MAILJET_SMTP_PORT", "587"))
    username = os.getenv("MAILJET_API_KEY")
    password = os.getenv("MAILJET_SECRET_KEY")
    from_email = os.getenv("MAILJET_FROM_EMAIL")

    if not (username and password and from_email):
        return None
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "from_email": from_email,
    }
