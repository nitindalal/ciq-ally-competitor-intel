import os, json
from typing import List
from .models import SKU, ComparisonRow, Recommendation
from dotenv import load_dotenv
import google.generativeai as genai 


def _extract_json_array(text: str):
    # Be lenient: extract the first [...] JSON array
    import re, json
    m = re.search(r"\[.*\]", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def _llm_suggest_gemini(client: SKU, comp: SKU, comparison: List[ComparisonRow], styleguide_refs: List[str]) -> List[Recommendation]:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    model_id = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set (in environment or .env)")

    import google.generativeai as genai
    genai.configure(api_key=api_key)

    # Optional: sanity check model supports generateContent
    try:
        # This call can be expensive; skip in hot path once verified.
        # models = [m.name for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
        # print("Gemini models available:", models)
        pass
    except Exception:
        pass

    sys_prompt = open("prompts/recs_system_prompt.md","r",encoding="utf-8").read()
    user_prompt = open("prompts/recs_user_prompt.md","r",encoding="utf-8").read().format(
        client_title=client.title,
        client_bullets="\n".join(f"- {b}" for b in client.bullets),
        client_desc=client.description,
        comp_title=comp.title,
        comp_bullets="\n".join(f"- {b}" for b in comp.bullets),
        comp_desc=comp.description,
        comparison_rows="\n".join(f"{r.section} | {r.metric} | {r.client} | {r.competitor} | {r.gap}" for r in comparison),
        styleguide_refs="\n".join(styleguide_refs)
    )

    # Use the current model id
    model = genai.GenerativeModel(model_id)
    # Gemini doesn’t truly have a separate “system” channel in this SDK; prepend it
    prompt = sys_prompt.strip() + "\n\n" + user_prompt.strip()

    response = model.generate_content(prompt)
    # Prefer .text, but if absent, fallback to parts
    if hasattr(response, "text") and response.text:
        text = response.text.strip()
    else:
        # Fallback: stitch parts
        parts = []
        for cand in getattr(response, "candidates", []) or []:
            for part in getattr(cand, "content", {}).parts or []:
                if getattr(part, "text", None):
                    parts.append(part.text)
        text = "\n".join(parts).strip()

    # Expect our strict JSON array (3 objects); be lenient if needed
    arr = _extract_json_array(text)
    if not arr:
        # Graceful fallback so UI doesn’t break
        return [Recommendation(
            title="Shorten title and clarify attributes",
            before=client.title,
            after=(client.title[:180] + ("…" if len(client.title) > 180 else "")),
            rationale="Keep titles concise and include key attributes; improve parity with competitor.",
            references=["competitor:title.length", "styleguide:title"]
        )]

    recs: List[Recommendation] = []
    for r in arr[:3]:
        recs.append(Recommendation(
            title=r.get("title", "Improve listing clarity"),
            before=r.get("before", client.title),
            after=r.get("after", client.title[:180]),
            rationale=r.get("rationale", "Improves compliance and clarity."),
            references=r.get("references", [])
        ))
    return recs

def _llm_available() -> bool:
    try:
        from openai import OpenAI  # noqa
        return True if os.getenv('OPENAI_API_KEY') else False
    except Exception:
        return False

def suggest_edits_llm(client: SKU, comp: SKU, comparison: List[ComparisonRow], styleguide_refs: List[str]) -> List[Recommendation]:
    # Use Gemini by default now
    try:
        return _llm_suggest_gemini(client, comp, comparison, styleguide_refs)
    except Exception as e:
        # deterministic fallback
        recs = []
        if len(client.title) > 200:
            recs.append(Recommendation(
                title='Shorten title under 200 chars',
                before=client.title,
                after=client.title[:180] + ('…' if len(client.title) > 180 else ''),
                rationale='Amazon prefers concise titles; improves scanability and search relevance.',
                references=['Comparison:title.length', 'AE Guide: Titles']
            ))
        if len(client.bullets) < 5:
            old = '\n'.join(f'- {b}' for b in client.bullets)
            add_count = 5 - len(client.bullets)
            new_bullets = client.bullets + [f'Add specific feature {i+1}' for i in range(add_count)]
            recs.append(Recommendation(
                title='Complete up to 5 specific bullets',
                before=old,
                after='\n'.join(f'- {b}' for b in new_bullets),
                rationale='Up to five concise, specific bullets improve conversion and filterability.',
                references=['AE Guide: Bullets']
            ))
        if not recs:
            recs.append(Recommendation(
                title='Tighten description and remove promos/URLs',
                before=client.description,
                after=client.description[:380],
                rationale='Descriptions should be concise, factual, and avoid promotional language or URLs.',
                references=['AE Guide: Description']
            ))
        return recs[:3]

def _llm_suggest(client: SKU, comp: SKU, comparison: List[ComparisonRow], styleguide_refs: List[str]) -> List[Recommendation]:
    from openai import OpenAI
    load_dotenv()
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('MODEL', 'gpt-4o')
    oai = OpenAI(api_key=api_key)

    sys = open('prompts/recs_system_prompt.md','r',encoding='utf-8').read()
    user = open('prompts/recs_user_prompt.md','r',encoding='utf-8').read().format(
        client_title=client.title,
        client_bullets='\n'.join(f'- {b}' for b in client.bullets),
        client_desc=client.description,
        comp_title=comp.title,
        comp_bullets='\n'.join(f'- {b}' for b in comp.bullets),
        comp_desc=comp.description,
        comparison_rows='\n'.join(f"{r.section} | {r.metric} | {r.client} | {r.competitor} | {r.gap}" for r in comparison),
        styleguide_refs='\n'.join(styleguide_refs)
    )

    resp = oai.chat.completions.create(model=model, temperature=0.2,
        messages=[{'role':'system','content':sys},{'role':'user','content':user}])
    text = resp.choices[0].message.content.strip()
    try:
        arr = json.loads(text)
        recs = []
        for r in arr[:3]:
            recs.append(Recommendation(
                title=r['title'],
                before=r['before'],
                after=r['after'],
                rationale=r['rationale'],
                references=r.get('references', [])
            ))
        return recs
    except Exception:
        # fallback parsing: single generic rec
        return [Recommendation(
            title='Shorten title and clarify attributes',
            before=client.title,
            after=(client.title[:180] + ('…' if len(client.title) > 180 else '')),
            rationale='Keep titles concise (<=200 chars) and include key attributes; competitor length/clarity indicates improvement room.',
            references=['Comparison:title.length', 'AE Guide: Titles']
        )]

def suggest_edits_llm(client: SKU, comp: SKU, comparison: List[ComparisonRow], styleguide_refs: List[str]) -> List[Recommendation]:
    if _llm_available():
        # return _llm_suggest(client, comp, comparison, styleguide_refs)
        return _llm_suggest_gemini(client, comp, comparison, styleguide_refs)
    # deterministic fallback (offline)
    recs = []
    if len(client.title) > 200:
        recs.append(Recommendation(
            title='Shorten title under 200 chars',
            before=client.title,
            after=client.title[:180] + ('…' if len(client.title) > 180 else ''),
            rationale='Amazon prefers concise titles; improves scanability and search relevance.',
            references=['Comparison:title.length', 'AE Guide: Titles']
        ))
    if len(client.bullets) < 5:
        old = '\n'.join(f'- {b}' for b in client.bullets)
        add_count = 5 - len(client.bullets)
        new_bullets = client.bullets + [f'Add specific feature {i+1}' for i in range(add_count)]
        recs.append(Recommendation(
            title='Complete up to 5 specific bullets',
            before=old,
            after='\n'.join(f'- {b}' for b in new_bullets),
            rationale='Up to five concise, specific bullets improve conversion and filterability.',
            references=['AE Guide: Bullets']
        ))
    if not recs:
        recs.append(Recommendation(
            title='Tighten description and remove promos/URLs',
            before=client.description,
            after=client.description[:380],
            rationale='Descriptions should be concise, factual, and avoid promotional language or URLs.',
            references=['AE Guide: Description']
        ))
    return recs[:3]
