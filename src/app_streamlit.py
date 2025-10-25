# src/app_streamlit.py
import os
import streamlit as st
from typing import List, Dict, Any

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Your pipeline imports (adjust if paths differ)
from src.loaders import load_csv, select_skus
from src.preprocess import preprocess
from src.scoring import score_all
from src.compare import compare_sections
from src.render import render_markdown_report
from src.rules_registry import load_all_rules, select_rules
from src.rules_engine import validate_with_rules
from src.recommender import suggest_edits_llm  # uses your LLM backend
from src.models import SKU, Recommendation, Finding

# ---------------- Session state helpers ----------------
from typing import Optional

def _get_attr(o, *names, default=None):
    for n in names:
        if hasattr(o, n):
            return getattr(o, n)
        if isinstance(o, dict) and n in o:
            return o[n]
    return default

def normalize_recs(recs):
    """
    Coerce recommendations into a uniform shape the UI expects:
    {section, title, before, after, rationale, references}
    Accepts objects or dicts; maps 'type' -> 'section' if needed.
    """
    norm = []
    for r in recs or []:
        section = _get_attr(r, "section", "type", default=None)
        if section is None:
            # Guess from title text as a last resort
            t = (_get_attr(r, "title", default="") or "").lower()
            if "title" in t:
                section = "title"
            elif "bullet" in t:
                section = "bullets"
            elif "description" in t:
                section = "description"
            else:
                section = "unknown"

        item = {
            "section": section,
            "title": _get_attr(r, "title", default=section.title() if section else "Suggestion"),
            "before": _get_attr(r, "before", default=""),
            "after":  _get_attr(r, "after",  default=""),
            "rationale": _get_attr(r, "rationale", default=""),
            "references": _get_attr(r, "references", default=[]) or [],
        }
        norm.append(item)
    return norm


def _init_state():
    if "messages" not in st.session_state: st.session_state.messages = []
    if "draft" not in st.session_state:
        st.session_state.draft = {"title": "", "bullets": [], "description": ""}
    if "last_report_md" not in st.session_state: st.session_state.last_report_md = ""
    if "last_findings" not in st.session_state:
        st.session_state.last_findings = {"client": [], "competitor": []}
    if "last_comparison" not in st.session_state: st.session_state.last_comparison = []
    if "suggestions" not in st.session_state: st.session_state.suggestions = []
    if "approved" not in st.session_state: st.session_state.approved = False

def add_bot(msg: str):
    st.session_state.messages.append({"role": "assistant", "content": msg})

def add_user(msg: str):
    st.session_state.messages.append({"role": "user", "content": msg})

# ---------------- Core actions ----------------
def run_compare(client_id: str, competitor_id: str, csv_path: str, market: str = "AE"):
    df = load_csv(csv_path)
    client_row, comp_row = select_skus(df, client_id, competitor_id)
    client_p, comp_p = preprocess(client_row), preprocess(comp_row)

    packs = load_all_rules("data/policies")
    # For now: apply rules to all categories
    rules = select_rules(packs, market=market, categories=[])

    client_find: List[Finding] = validate_with_rules(client_p, rules)
    comp_find: List[Finding]   = validate_with_rules(comp_p, rules)

    client_scores = score_all(client_p)
    comp_scores   = score_all(comp_p)

    comparison = compare_sections(client_p, comp_p, client_scores, comp_scores, client_find, comp_find)

    styleguide_refs = [f"{r.get('policy_id','')}:{r['id']} – {r.get('message','')}".strip(": ") for r in rules]
    recs_raw = suggest_edits_llm(client_p, comp_p, comparison, styleguide_refs)
    recs = normalize_recs(recs_raw)  # ← normalize here

    # seed draft with suggested “after” if available
    def _first_after(section_name: str):
        for r in recs:
            if r["section"] == section_name:
                return r["after"]
        return None

    title_after   = _first_after("title")
    bullets_after = _first_after("bullets")
    desc_after    = _first_after("description")

    st.session_state.draft["title"] = title_after if isinstance(title_after, str) and title_after.strip() else (client_p.title or "")
    st.session_state.draft["bullets"] = bullets_after if isinstance(bullets_after, list) and bullets_after else (client_p.bullets or [])
    st.session_state.draft["description"] = desc_after if isinstance(desc_after, str) and desc_after.strip() else (client_p.description or "")

    # Normalize types for draft
    if isinstance(st.session_state.draft["bullets"], str):
        st.session_state.draft["bullets"] = [x.strip("- ").strip() for x in st.session_state.draft["bullets"].split("\n") if x.strip()]
    if isinstance(st.session_state.draft["after"] if "after" in st.session_state.draft else "", list):
        # no-op; bullets already list
        pass

    report_md = render_markdown_report(
        client_p, comp_p, comparison, recs, approved=False,
        client_findings=client_find, competitor_findings=comp_find
    )

    # save to session
    st.session_state.last_report_md = report_md
    st.session_state.last_findings = {"client": client_find, "competitor": comp_find}
    st.session_state.last_comparison = comparison
    st.session_state.suggestions = recs
    st.session_state.approved = False

    return client_p, comp_p, report_md

def revalidate_current_draft(sku: SKU, rules: List[Dict[str, Any]]):
    """Validate current draft sections by temporarily creating a SKU-like object."""
    # Build a shallow clone with overridden fields
    class _Temp(SKU): pass
    tmp = _Temp(**{**sku.__dict__})
    tmp.title = st.session_state.draft["title"]
    tmp.bullets = st.session_state.draft["bullets"]
    tmp.description = st.session_state.draft["description"]
    return validate_with_rules(tmp, rules)

def finalize_markdown(client_p: SKU, comp_p: SKU):
    # Use the last comparison + suggestions but replace content with the draft if you want.
    # For speed, just present the final content block here.
    title = st.session_state.draft["title"]
    bullets = st.session_state.draft["bullets"]
    desc = st.session_state.draft["description"]
    md = [
        f"# FINAL – {client_p.sku_id}",
        "## Title", title or "(empty)",
        "## Bullets", *(f"- {b}" for b in (bullets or ["(none)"])),
        "## Description", desc or "(empty)"
    ]
    return "\n\n".join(md)

# ---------------- UI ----------------
def main():
    _init_state()
    st.set_page_config(page_title="CIQ Ally – Competitor Content Intelligence", layout="wide")

    st.sidebar.header("Run Comparison")
    csv_path = st.sidebar.text_input("CSV path", value="data/asin_data_filled.csv")
    client_id = st.sidebar.text_input("Client SKU", value="B0BPN423GH")
    competitor_id = st.sidebar.text_input("Competitor SKU", value="B0D8WP5BFG")
    market = st.sidebar.text_input("Market", value="AE")
    do_compare = st.sidebar.button("Compare")

    st.title("Competitor Content Intelligence (Ally Skill)")
    st.caption("Compare SKUs, see policy findings, iterate edits in chat, then approve a final version.")

    if do_compare:
        try:
            client_p, comp_p, report_md = run_compare(client_id, competitor_id, csv_path, market)
            add_bot("Report generated. Scroll to view. You can now propose edits (e.g., *“edit bullet 3: emphasize hydration speed”*) or say **approve**.")
        except Exception as e:
            add_bot(f"Error: {e}")

    # Report view
    if st.session_state.last_report_md:
        with st.expander("📄 Report (Markdown)", expanded=True):
            st.markdown(st.session_state.last_report_md)

    # Suggestions preview
    if st.session_state.suggestions:
        with st.expander("💡 Top Suggestions", expanded=False):
            for i, r in enumerate(st.session_state.suggestions[:3], 1):
                st.markdown(f"**{i}. {r.get('title') or r.get('section','Suggestion')}**")
                st.markdown("**Before**")
                b = r.get("before")
                if isinstance(b, list):
                    st.code("\n".join(f"- {x}" for x in b))
                else:
                    st.code(b or "")
                st.markdown("**After**")
                a = r.get("after")
                if isinstance(a, list):
                    st.code("\n".join(f"- {x}" for x in a))
                else:
                    st.code(a or "")
                if r.get("rationale"):
                    st.caption(r["rationale"])


    # Editable draft section (chat-like quick commands + form fields)
    st.subheader("✍️ Edit Draft (Live)")
    col1, col2 = st.columns(2)
    with col1:
        st.text_area("Title", key="draft_title", value=st.session_state.draft.get("title",""), height=4)
        # keep state in sync
        st.session_state.draft["title"] = st.session_state.get("draft_title", st.session_state.draft["title"])

        new_desc = st.text_area("Description", value=st.session_state.draft.get("description",""), height=10, key="draft_desc")
        st.session_state.draft["description"] = new_desc

    with col2:
        bullets_str = "\n".join(st.session_state.draft.get("bullets", []))
        new_bullets = st.text_area("Bullets (one per line)", value=bullets_str, height=14, key="draft_bullets")
        st.session_state.draft["bullets"] = [b.strip() for b in new_bullets.split("\n") if b.strip()]

    # Chat input for quick edit commands
    st.subheader("💬 Chat")
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    user_msg = st.chat_input("Type ‘approve’, or e.g., ‘edit bullet 3: emphasize hydration speed’")
    if user_msg:
        add_user(user_msg)
        handled = False

        # Simple command router
        txt = user_msg.strip().lower()

        # Approve
        if txt in {"approve", "finalize", "approve all"}:
            st.session_state.approved = True
            add_bot("Approved. Generating final Markdown…")
            # We need client_p/comp_p to render final; re-run a light load
            df = load_csv(csv_path)
            client_row, comp_row = select_skus(df, client_id, competitor_id)
            client_p, comp_p = preprocess(client_row), preprocess(comp_row)
            final_md = finalize_markdown(client_p, comp_p)
            st.session_state.last_final_md = final_md
            handled = True
        else:
            # Edit bullet N: <text>
            import re
            m = re.match(r"edit bullet\s+(\d+)\s*:\s*(.+)", txt, re.I)
            if m:
                idx = int(m.group(1)) - 1
                new_text = m.group(2).strip()
                bullets = st.session_state.draft.get("bullets", [])
                if 0 <= idx < len(bullets):
                    bullets[idx] = new_text
                    st.session_state.draft["bullets"] = bullets
                    add_bot(f"Updated bullet {idx+1}.")
                else:
                    add_bot(f"Bullet {idx+1} does not exist.")
                handled = True

            # Replace title:
            if txt.startswith("title:"):
                st.session_state.draft["title"] = user_msg.split(":",1)[1].strip()
                add_bot("Title updated.")
                handled = True

            # Replace description:
            if txt.startswith("description:"):
                st.session_state.draft["description"] = user_msg.split(":",1)[1].strip()
                add_bot("Description updated.")
                handled = True

        if not handled:
            add_bot("I can: `approve`, `edit bullet N: <text>`, `title: <new>`, `description: <new>`")

    # Validation + Finalization area
    packs = load_all_rules("data/policies")
    rules = select_rules(packs, market=market, categories=[])
    # Light inline revalidation of the draft (against the client SKU context)
    if "last_client_id" not in st.session_state:
        st.session_state.last_client_id = client_id
    try:
        df = load_csv(csv_path)
        client_row, _ = select_skus(df, client_id, competitor_id)
        client_p = preprocess(client_row)
        draft_findings = revalidate_current_draft(client_p, rules)
    except Exception:
        draft_findings = []

    with st.expander("✅ Draft Validation (Policy)", expanded=False):
        if draft_findings:
            fail = [f for f in draft_findings if not f.passed]
            if fail:
                st.error(f"{len(fail)} rule(s) failing:")
                for f in fail:
                    st.write(f"- **{f.rule_id}** ({f.section}): {f.message}")
            else:
                st.success("All rules passed for the current draft.")
        else:
            st.info("No findings available yet.")

    # Final output block + download
    if st.session_state.get("approved"):
        st.subheader("📦 Final Markdown")
        st.code(st.session_state.get("last_final_md", ""), language="markdown")
        st.download_button("Download Final Markdown", st.session_state.get("last_final_md",""), file_name="final.md", mime="text/markdown")

if __name__ == "__main__":
    main()
