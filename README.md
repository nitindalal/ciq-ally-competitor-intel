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

### Run API
```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
# test: http://localhost:8000/docs
```

## Folder layout
```
ciq-ally-competitor-intel/
├─ src/                # core logic
├─ prompts/            # LLM prompt templates
├─ data/               # place asin_data_filled.csv here
├─ eval/               # optional eval assets
└─ tests/              # unit tests (skeleton)
```
