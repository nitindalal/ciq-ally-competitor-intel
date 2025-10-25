"""
Lightweight, high-signal scoring for title/bullets/description.

Adds richer metrics so the table is more diagnostic:
- title: has_size_or_count, has_flavor, has_brand
- bullets: count, avg_len, end_punct_count, unique_ratio
- description: length, has_numbers
"""

import re
from typing import Dict, Optional
from .models import SKU, SectionScores

# Simple heuristics that work well for CPG / consumables
UNITS   = re.compile(r'\b(oz|fl\s*oz|lb|g|kg|ml|l|pack|count|ct|sticks?)\b', re.I)
FLAVOR  = re.compile(r'\b(vanilla|chocolate|strawberry|watermelon|orange|cherry|lime|grape|lemon|raspberry)\b', re.I)
NUMBERS = re.compile(r'\b\d+[xX]?\b')


def score_title(sku: SKU) -> SectionScores:
    t = sku.title or ""
    has_brand = 1.0 if (sku.brand and t and sku.brand.lower() in t.lower()) else 0.0
    has_size_or_count = 1.0 if (t and (UNITS.search(t) or NUMBERS.search(t))) else 0.0
    has_flavor = 1.0 if (t and FLAVOR.search(t)) else 0.0
    return SectionScores(section='title', metrics={
        'length': len(t) if t else None,
        'has_brand': has_brand,
        'has_size_or_count': has_size_or_count,
        'has_flavor': has_flavor,
    })


def score_bullets(sku: SKU) -> SectionScores:
    bs = sku.bullets or []
    avg_len: Optional[float] = (sum(len(b) for b in bs)/len(bs)) if bs else None
    end_punct = sum(1 for b in bs if b.strip().endswith(('.', ';', ':', '!'))) if bs else None
    unique_ratio = (len(set(b.strip().lower() for b in bs))/len(bs)) if bs else None
    return SectionScores(section='bullets', metrics={
        'count': float(len(bs)) if bs else None,
        'avg_len': avg_len,
        'end_punct_count': end_punct,
        'unique_ratio': unique_ratio
    })


def score_description(sku: SKU) -> SectionScores:
    d = sku.description or ""
    return SectionScores(section='description', metrics={
        'length': len(d) if d else None,
        'has_numbers': 1.0 if (d and NUMBERS.search(d)) else 0.0
    })


def score_all(sku: SKU) -> Dict[str, SectionScores]:
    return {
        'title': score_title(sku),
        'bullets': score_bullets(sku),
        'description': score_description(sku)
    }
