import re
from .models import SKU

WHITESPACE = re.compile(r'\s+')

def normalize_text(s: str) -> str:
    s = s.replace('\u00A0', ' ')
    s = WHITESPACE.sub(' ', s).strip()
    return s

def preprocess(sku: SKU) -> SKU:
    return SKU(
        sku_id=sku.sku_id,
        title=normalize_text(sku.title),
        bullets=[normalize_text(b) for b in sku.bullets],
        description=normalize_text(sku.description),
        brand=sku.brand,
        category=sku.category,
        image_urls=sku.image_urls
    )
