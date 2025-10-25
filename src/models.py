from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union

Number = Union[int, float]

@dataclass
class SKU:
    sku_id: str
    title: str
    bullets: List[str]
    description: str
    brand: Optional[str] = None
    category: Optional[str] = None
    image_urls: Optional[List[str]] = None

@dataclass
class Finding:
    section: str                 # 'title' | 'bullets' | 'description'
    rule_id: str                 # e.g., 'TITLE_LENGTH'
    passed: bool
    message: str
    citation: Optional[str] = None

@dataclass
class SectionScores:
    section: str
    metrics: Dict[str, Number]

@dataclass
class ComparisonRow:
    section: str
    metric: str
    client: Union[Number, str]
    competitor: Union[Number, str]
    gap: Union[Number, str]
    compliance_notes: List[str] = field(default_factory=list)

@dataclass
class Recommendation:
    title: str
    before: str
    after: str
    rationale: str
    references: List[str]
