# AgenteQA

Agente QA conversacional. Ver plan completo en [PLAN.md](./PLAN.md).

## Estructura

```
backend/app/
  llm/          # cliente DeepSeek + prompts
  models/       # schemas Pydantic + db
  routers/      # chat, plan, execute, report
  execution/    # endpoint_runner, ui_runner, runner
frontend/src/
  api/          # cliente HTTP al backend
  components/   # ChatPanel, PlanView, ResultsView, ReportDownload
```

## Division de trabajo (ver PLAN.md para detalle)

- **Persona A**: `backend/app/llm/`, `backend/app/routers/chat.py`, `backend/app/routers/plan.py`, `backend/app/models/db.py`, `backend/app/config.py`
- **Persona B**: `backend/app/execution/`, `backend/app/routers/execute.py`, `backend/app/routers/report.py`
- **Persona C**: `frontend/` completo

## Setup backend

```
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # completar DEEPSEEK_API_KEY
uvicorn app.main:app --reload
```
