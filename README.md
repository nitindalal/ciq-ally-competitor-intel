# CIQ Ally — Competitor Content Intelligence
Builds a rule-driven + LLM-assisted skill that compares a **client SKU** vs a **competitor SKU**, flags compliance gaps (Amazon style guide), and generates **Top‑3** compliant edits. Includes:
- **CLI** (`src/main.py`)
- **Streamlit UI** (`src/app_streamlit.py`) — demo friendly
- **FastAPI** (`src/api.py`) — exposable service

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add your OPENAI_API_KEY, optional
# Put your CSV at data/asin_data_filled.csv
```

### Run CLI
```bash
python -m src.main --client_id <CLIENT_SKU_ID> --competitor_id <COMP_SKU_ID> --csv data/asin_data_filled.csv --out report.md
```

### Run Streamlit (Demo)
```bash
streamlit run src/app_streamlit.py
```

### Run Eval Set (Optional)
```bash
python3 -m eval.run_eval            # run every case in eval/cases
python3 -m eval.run_eval --case foo # run a single case
python3 -m eval.run_eval --verbose  # include diagnostics per case
```

### Regenerate Policy Rules (Optional)
```bash
python3 -m src.policy_llm_extract --pdf data/policies/pet-supplies_ae_2018/source.pdf \
    --out data/policies/pet-supplies_ae_2018/rules.yaml --dump-dir eval/generated_rules
```

### Run API
```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
# test: http://localhost:8000/docs
```
- `POST /compare` → full pipeline (report + draft + suggestions)
- `POST /validate` → re-check a draft `{client_id, draft{title,bullets,description}}` against policy
- `POST /finalize` → return final markdown plus validation findings for the supplied draft

### Wire Into a Custom GPT (Optional)
1. **Deploy the API** somewhere reachable over HTTPS (same FastAPI app above; Render/Fly/Railway works).
2. In ChatGPT → *Explore GPTs* → *Create*, add the action(s) using a snippet like:
   ```json
   {
     "openapi": "3.1.0",
     "info": { "title": "CIQ Ally API", "version": "1.0.0" },
     "servers": [{ "url": "https://<your-host>" }],
     "paths": {
       "/compare": {
         "post": {
           "operationId": "compareSkus",
           "summary": "Compare client and competitor SKUs",
           "requestBody": {
             "required": true,
             "content": {
               "application/json": {
                 "schema": {
                   "type": "object",
                   "required": ["client_id", "competitor_id"],
                   "properties": {
                     "client_id": { "type": "string" },
                     "competitor_id": { "type": "string" },
                     "market": { "type": "string", "default": "AE" },
                     "csv_path": { "type": "string", "default": "data/asin_data_filled.csv" }
                   }
                 }
               }
             }
           }
         }
       },
       "/validate": {
         "post": {
           "operationId": "validateDraft",
           "summary": "Validate an edited draft",
           "requestBody": {
             "required": true,
             "content": {
               "application/json": {
                 "schema": {
                   "type": "object",
                   "required": ["client_id", "draft"],
                   "properties": {
                     "client_id": { "type": "string" },
                     "market": { "type": "string", "default": "AE" },
                     "csv_path": { "type": "string", "default": "data/asin_data_filled.csv" },
                     "draft": {
                       "type": "object",
                       "properties": {
                         "title": { "type": "string" },
                         "bullets": { "type": "array", "items": { "type": "string" } },
                         "description": { "type": "string" }
                       }
                     }
                   }
                 }
               }
             }
           }
         }
       },
       "/finalize": {
         "post": {
           "operationId": "finalizeDraft",
           "summary": "Render final markdown",
           "requestBody": { "$ref": "#/paths/~1validate/post/requestBody" }
         }
       }
     }
   }
   ```
3. Response examples: copy the JSON produced by each endpoint from `http://localhost:8000/docs`.
4. In the GPT instructions, outline the flow (call `compare` with two SKUs, update the draft in-chat, call `validate` when asked, and call `finalize` once the user approves).

## Folder layout
```
ciq-ally-competitor-intel/
├─ src/                # core logic
├─ prompts/            # LLM prompt templates
├─ data/               # place asin_data_filled.csv here
├─ eval/               # optional eval assets
└─ tests/              # unit tests (skeleton)
```
