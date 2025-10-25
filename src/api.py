from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
from .loaders import load_csv, select_skus
from .preprocess import preprocess
from .rules import validate_all
from .scoring import score_all
from .compare import compare_sections
from .recommender import suggest_edits_llm
from .approvals import ask_approval

app = FastAPI(title='CIQ Ally — Competitor Content Intelligence API')

STYLEGUIDE_REFS = [
    'Titles: concise; avoid ALL CAPS/promo/seller info【9†PetSupplies_PetFood_Styleguide_EN_AE._CB1198675309_.pdf†L96-L116】',
    'Bullets: up to 5; start with capital; no ending punctuation; be specific【9†...†L162-L212】',
    'Descriptions: concise, truthful; no promo/URLs【9†...†L214-L274】'
]

class CompareRequest(BaseModel):
    csv_path: str
    client_id: str
    competitor_id: str

class RecommendationDTO(BaseModel):
    title: str
    before: str
    after: str
    rationale: str
    references: List[str]

@app.post('/compare')
def compare(req: CompareRequest):
    df = load_csv(req.csv_path)
    client, competitor = select_skus(df, req.client_id, req.competitor_id)

    client_p, comp_p = preprocess(client), preprocess(competitor)
    client_find, comp_find = validate_all(client_p), validate_all(comp_p)
    client_scores, comp_scores = score_all(client_p), score_all(comp_p)
    comparison = compare_sections(client_p, comp_p, client_scores, comp_scores, client_find, comp_find)
    recs = suggest_edits_llm(client_p, comp_p, comparison, STYLEGUIDE_REFS)
    approved = ask_approval(recs)

    comp_rows = [r.__dict__ for r in comparison]
    rec_rows = [RecommendationDTO(**r.__dict__).dict() for r in recs]

    return {
        'client': client_p.__dict__,
        'competitor': comp_p.__dict__,
        'comparison': comp_rows,
        'recommendations': rec_rows,
        'approved': approved
    }
