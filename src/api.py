from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .skill import run_compare

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


# ---------- Serialization helpers ----------

def _serialize_finding(finding: Any) -> FindingDTO:
    if is_dataclass(finding):
        data = asdict(finding)
    elif hasattr(finding, "__dict__"):
        data = finding.__dict__
    else:
        data = dict(finding)

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
    data = getattr(row, "__dict__", dict(row))
    return ComparisonRowDTO(
        section=data.get("section"),
        metric=data.get("metric"),
        client=data.get("client"),
        competitor=data.get("competitor"),
        gap=data.get("gap"),
        compliance_notes=data.get("compliance_notes") or [],
    )


def _serialize_sku(sku: Any) -> SKUDetailsDTO:
    data = getattr(sku, "__dict__", dict(sku))
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
