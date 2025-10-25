from pathlib import Path
import yaml

def _safe_load(path: Path):
    if not path.exists(): return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def load_all_rules(root="data/policies"):
    packs = []
    for policy_dir in Path(root).iterdir():
        if not policy_dir.is_dir():
            continue
        rules_path = policy_dir / "rules.yaml"
        meta_path  = policy_dir / "meta.yaml"

        if not rules_path.exists():
            continue

        rules_doc = _safe_load(rules_path) or {}
        meta_doc  = _safe_load(meta_path)  or {}

        # Accept both shapes:
        # (A) rules.yaml has {meta:{...}, rules:[...]}
        # (B) rules.yaml has just rules:[...] and meta.yaml has meta:{...}
        # (C) rules.yaml is literally a list of rules
        if isinstance(rules_doc, list):
            rules = rules_doc
            meta  = meta_doc.get("meta", {})
        else:
            rules = rules_doc.get("rules") or []
            meta  = (rules_doc.get("meta") or {}) | (meta_doc.get("meta") or {})

        # Fallback meta
        if "policy_id" not in meta or not meta["policy_id"]:
            meta["policy_id"] = policy_dir.name

        packs.append({"meta": meta, "rules": rules})
    return packs

def _norm(s): return (s or "").strip().lower()

def _cat_match(rule_scope_cats, want_cats):
    # If caller passes [] -> accept all
    if not want_cats:
        return True
    if not rule_scope_cats:
        return True
    rc = [_norm(c) for c in rule_scope_cats]
    wc = [_norm(c) for c in want_cats if c]
    for a in rc:
        for b in wc:
            if a == b or a in b or b in a:
                return True
    return False

def select_rules(packs, market: str, categories: list[str]):
    sel = []
    for p in packs:
        meta = p.get("meta") or {}
        for r in p.get("rules", []) or []:
            scope = r.get("scope") or {}
            ok_market = (not scope.get("market")) or (market in scope["market"])
            ok_cat    = _cat_match(scope.get("categories"), categories)
            if ok_market and ok_cat:
                # Attach policy_id for traceability
                r = dict(r)
                r["policy_id"] = meta.get("policy_id", "unknown_policy")
                sel.append(r)
    return sel
