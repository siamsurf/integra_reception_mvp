# INTEGRA Reception Hub + Quote Precheck (FastAPI MVP)

Minimal code-first FastAPI MVP for reception intake with two service flows:
- `delivery`
- `supplier_check`

Uses SQLite in MVP and is structured so DB settings can later be switched to Postgres.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run Web

```bash
uvicorn app.main:app --reload
```

## Run VK Worker
Start this worker in a separate terminal after launching the FastAPI app.

```bash
python3 -m app.adapters.vk_longpoll
```

## Open in Browser

- Home: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- New Lead Form: [http://127.0.0.1:8000/new](http://127.0.0.1:8000/new)
- Manager View: [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin)
- Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## Environment Variables

- `OPENAI_API_KEY` (optional): if set, app can use OpenAI both for AI-generated summary/reply and for LLM fallback extraction in delivery precheck.
  - If unavailable, app automatically falls back to deterministic/local logic.
- `OPENAI_MODEL` (optional, default: `gpt-4o-mini`)
- `SQLITE_URL` (optional, default: `sqlite:///./integra_mvp.db`)

### VK Long Poll Worker

- `VK_TOKEN` (required)
- `VK_GROUP_ID` (required)
- `VK_API_VERSION` (optional, default: `5.131`)
- `VK_WAIT` (optional, default: `25`)
- `VK_LANG` (optional, default: `ru`)
