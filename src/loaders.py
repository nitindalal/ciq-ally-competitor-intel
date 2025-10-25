import pandas as pd
from typing import Tuple, List, Optional
from .models import SKU

# Map your exact columns (+ keep generic fallbacks for safety)
ID_ALIASES       = ["product_id", "sku_id", "sku", "asin", "id"]
TITLE_ALIASES    = ["title", "product_title", "name"]
BULLET_ALIASES   = ["bullet_points", "about_this_item", "highlights", "key_features", "features"]
DESC_ALIASES     = ["description_filled", "description", "product_description", "long_description", "details"]
BRAND_ALIASES    = ["retailer_brand_name", "brand", "brand_name", "manufacturer"]
CATEGORY_ALIASES = ["retailer_category_node", "universe", "category", "dept", "vertical"]
IMG_ALIASES      = ["image_url", "image_urls", "images", "image_links"]

def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)

def _first_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _id_col(df: pd.DataFrame) -> str:
    col = _first_col(df, ID_ALIASES)
    if not col:
        raise ValueError(f"No identifier column found. Columns: {df.columns.tolist()}")
    return col

def _split_bullets(raw) -> List[str]:
    """Handle strings like 'a||b||c', 'a|b', 'a; b', newlines, bullets, or JSON arrays."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []
    # JSON-ish list
    if s.startswith("[") and s.endswith("]"):
        try:
            import json
            arr = json.loads(s)
            return [str(x).strip() for x in (arr or []) if str(x).strip()]
        except Exception:
            pass
    # Common separators in retailer exports
    for sep in ["||", "|", "\n", "•", ";", "‣", "·", "—"]:
        if sep in s:
            return [b.strip(" -•\t") for b in s.split(sep) if b.strip(" -•\t")]
    # Fallback: single bullet
    return [s]

def _text_from_aliases(row: pd.Series, aliases: List[str]) -> str:
    for c in aliases:
        if c in row and isinstance(row[c], str) and row[c].strip():
            return row[c].strip()
    return ""

def _bullets_from_row(row: pd.Series) -> List[str]:
    for c in BULLET_ALIASES:
        if c in row and str(row[c]).strip():
            return _split_bullets(row[c])
    return []

def _images_from_row(row: pd.Series) -> Optional[List[str]]:
    for c in IMG_ALIASES:
        if c in row and str(row[c]).strip():
            val = str(row[c]).strip()
            if "|" in val:
                return [u.strip() for u in val.split("|") if u.strip()]
            return [val]
    return None

def row_to_sku(row: pd.Series) -> SKU:
    # pick the first available id-like col
    sid = ""
    for c in ID_ALIASES:
        if c in row and str(row[c]).strip():
            sid = str(row[c]).strip()
            break
    return SKU(
        sku_id=sid,
        title=_text_from_aliases(row, TITLE_ALIASES),
        bullets=_bullets_from_row(row),
        description=_text_from_aliases(row, DESC_ALIASES),
        brand=_text_from_aliases(row, BRAND_ALIASES) or None,
        category=_text_from_aliases(row, CATEGORY_ALIASES) or None,
        image_urls=_images_from_row(row)
    )

def select_skus(df: pd.DataFrame, client_id: str, competitor_id: str) -> Tuple[SKU, SKU]:
    idcol = _id_col(df)
    c_row = df[df[idcol].astype(str) == str(client_id)].head(1)
    k_row = df[df[idcol].astype(str) == str(competitor_id)].head(1)
    if c_row.empty: raise ValueError(f"Client ID '{client_id}' not found in '{idcol}'.")
    if k_row.empty: raise ValueError(f"Competitor ID '{competitor_id}' not found in '{idcol}'.")
    return row_to_sku(c_row.iloc[0]), row_to_sku(k_row.iloc[0])
