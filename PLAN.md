# AgenteQA — plan de desarrollo (MVP tesis)

## Contexto

Tesis: agente QA conversacional. Usuario chatea para dar contexto (que testear, URL, repo opcional). LLM (DeepSeek) arma plan de pruebas estructurado, el sistema lo ejecuta (UI + endpoints) y genera reporte final con fallos, ubicacion, y pasos de reproduccion.

Repo `AgenteQA` esta vacio, arrancamos desde cero.

Decisiones ya tomadas con el usuario:
- Stack: **Python (FastAPI) + React**
- LLM: **DeepSeek** (API compatible con formato OpenAI), usado tanto para conversacion como para generar plan y reporte
- MVP: **UI + Endpoints** (analisis de repo queda como fase futura, no bloquea diseño pero no se implementa ahora)
- Entrega: documento **Markdown/HTML descargable**

## Arquitectura

```
AgenteQA/
  backend/
    app/
      main.py                 # FastAPI app + CORS + routers
      config.py                # pydantic Settings: DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DB_PATH
      llm/
        client.py              # wrapper OpenAI SDK apuntando a base_url de DeepSeek
        prompts.py              # system prompts: conversacion, generar_plan, generar_reporte
      models/
        schemas.py              # Pydantic: ChatMessage, TestCase, TestPlan, TestResult, Report
        db.py                    # SQLite + SQLAlchemy: Session, Message, Plan, Result (persistencia simple)
      routers/
        chat.py                  # POST /api/chat -> conversacion con DeepSeek, guarda historial
        plan.py                  # POST /api/plan  -> genera TestPlan estructurado desde historial
        execute.py               # POST /api/execute -> corre TestPlan, guarda resultados
        report.py                # GET  /api/report/{session_id} -> genera y descarga .md/.html
      execution/
        endpoint_runner.py       # httpx: ejecuta test cases tipo "endpoint"
        ui_runner.py              # Playwright: ejecuta test cases tipo "ui" (DSL de acciones)
        runner.py                 # dispatch por tipo, agrega resultados + screenshots en fallos
    requirements.txt
    tests/
      test_endpoint_runner.py    # check minimo: mock server, verifica pass/fail se detecta bien
      test_ui_runner.py          # check minimo: dispatch de acciones conocido/desconocido
  frontend/
    (Vite + React + TS)
    src/
      api/client.ts              # fetch wrapper a backend
      components/
        ChatPanel.tsx             # chat de contexto
        PlanView.tsx               # muestra plan generado, boton "Ejecutar"
        ResultsView.tsx            # resultados en vivo (pass/fail por caso)
        ReportDownload.tsx         # boton descarga reporte final
      App.tsx                      # orquesta los 4 pasos: chat -> plan -> ejecutar -> reporte
  README.md
```

## Flujo end-to-end

1. **Chat** (`ChatPanel` -> `POST /api/chat`): usuario describe que testear, URL, endpoints conocidos, repo (opcional, no se usa aun). Backend mantiene historial por `session_id` (generado al primer mensaje, guardado en SQLite). DeepSeek responde y guia la conversacion hasta tener contexto suficiente (prompt de sistema en `prompts.py` instruye al LLM a preguntar por URL, tipo de app, credenciales de prueba si aplica, endpoints clave).

2. **Generar plan** (boton en front -> `POST /api/plan`): se envia el historial completo a DeepSeek con un prompt que exige salida JSON con schema fijo:
   ```json
   {
     "test_cases": [
       {
         "id": "TC-01",
         "type": "ui",
         "title": "...",
         "steps": [
           {"action": "goto", "url": "..."},
           {"action": "click", "selector": "..."},
           {"action": "fill", "selector": "...", "value": "..."},
           {"action": "assert_text", "selector": "...", "expected": "..."},
           {"action": "assert_visible", "selector": "..."}
         ]
       },
       {
         "id": "TC-02",
         "type": "endpoint",
         "title": "...",
         "request": {"method": "GET", "url": "...", "headers": {}, "body": null},
         "expected_status": 200,
         "expected_body_contains": "..."
       }
     ]
   }
   ```
   Se valida con Pydantic (`TestPlan`/`TestCase`). Si el LLM devuelve JSON invalido, un solo reintento con el error como feedback (sin loop infinito).

3. **Ejecutar** (`POST /api/execute`): `runner.py` itera `test_cases`:
   - `type == "endpoint"` -> `endpoint_runner.py` con `httpx.AsyncClient`, compara status/body, guarda request/response.
   - `type == "ui"` -> `ui_runner.py` con Playwright (`async_playwright`, chromium headless). Dispatch de acciones limitado a un set fijo (`goto`, `click`, `fill`, `assert_text`, `assert_visible`) via diccionario accion->funcion. En fallo, captura screenshot y guarda referencia.
   - Resultados (`TestResult`: id, status pass/fail, detalle, evidencia) se guardan en SQLite asociados al `session_id`.

4. **Reporte** (`GET /api/report/{session_id}`): se envian `TestPlan` + `TestResult[]` a DeepSeek con prompt que arma Markdown: por cada fallo, seccion con ubicacion (endpoint o selector/pagina), descripcion del fallo, evidencia (respuesta HTTP o screenshot), y pasos de reproduccion numerados. Se devuelve el `.md` (y opcionalmente conversion simple a `.html` con `markdown` lib) para descarga directa desde el front.

## Puntos tecnicos clave

- **DeepSeek**: `openai` SDK oficial, `base_url="https://api.deepseek.com"`, modelo `deepseek-chat`. Un solo wrapper (`llm/client.py`) con 3 funciones: `chat(history)`, `generate_plan(history)`, `generate_report(plan, results)`. Reutilizar el mismo client para las 3, evita duplicar boilerplate.
- **DSL de acciones UI**: fijo y pequeño a proposito (5 acciones) para que sea ejecutable sin ambiguedad. Ampliar solo si el uso real lo pide.
- **Persistencia**: SQLite + SQLAlchemy, un archivo `.db` local. Sin Docker ni Postgres para el MVP — evita complejidad de infra que la tesis no necesita.
- **Sin autenticacion** en el MVP (uso personal/demo). Si se despliega publico despues, se agrega.
- **Repo access**: queda fuera del MVP. El schema de `TestCase.type` es extensible (`"repo"` a futuro) sin romper lo existente.

## Division de trabajo (3 personas en paralelo)

Contrato compartido primero (1 persona lo define en 30 min, o se acuerda en grupo antes de arrancar), para que las 3 partes se integren sin bloquearse:
- `backend/app/models/schemas.py`: `ChatMessage`, `TestCase`, `TestPlan`, `TestResult`, `Report` (Pydantic).
- Rutas y contratos HTTP: `POST /api/chat`, `POST /api/plan`, `POST /api/execute`, `GET /api/report/{session_id}` (paths, request/response shape ya descritos arriba en "Flujo end-to-end").
- El schema JSON del `TestPlan` (seccion "Generar plan" arriba) es el contrato entre LLM/backend y el runner de ejecucion — no cambia sin avisar a las otras 2 personas.

Con eso fijado, cada persona puede mockear lo que las otras 2 todavia no entregaron.

### Persona A — LLM + Conversacion + Plan
Archivos: `backend/app/llm/client.py`, `backend/app/llm/prompts.py`, `backend/app/routers/chat.py`, `backend/app/routers/plan.py`, `backend/app/models/db.py` (setup inicial SQLite/SQLAlchemy), `backend/app/config.py`.
- Wrapper DeepSeek (`chat()`, `generate_plan()`, `generate_report()` — implementa las primeras dos, deja `generate_report()` con firma lista para Persona B).
- Prompts de sistema: conversacion guiada + prompt que fuerza salida JSON del `TestPlan` con el schema fijo.
- Endpoints `/api/chat` y `/api/plan`, con historial persistido en SQLite por `session_id`.
- Validacion Pydantic del JSON que devuelve el LLM + 1 reintento si es invalido.
- Mock necesario: ninguno externo, es la base. Expone `TestPlan` de ejemplo (fixture) para que Persona B pruebe su runner sin depender del LLM real.

### Persona B — Motor de ejecucion + Reporte
Archivos: `backend/app/execution/endpoint_runner.py`, `backend/app/execution/ui_runner.py`, `backend/app/execution/runner.py`, `backend/app/routers/execute.py`, `backend/app/routers/report.py`, `backend/app/llm/client.py::generate_report()` (completa la firma que dejo Persona A).
- `endpoint_runner.py`: ejecuta `TestCase` tipo `endpoint` con `httpx.AsyncClient`.
- `ui_runner.py`: Playwright headless, dispatch fijo de 5 acciones (`goto`, `click`, `fill`, `assert_text`, `assert_visible`), screenshot en fallo.
- `runner.py`: orquesta por tipo, guarda `TestResult[]` en SQLite.
- `/api/execute` y `/api/report/{session_id}` (arma Markdown/HTML via `generate_report`).
- Mientras Persona A no tenga `/api/plan` listo: trabajar contra el `TestPlan` de ejemplo fijado en el contrato (JSON de la seccion "Generar plan"), no contra el endpoint real.
- Tests minimos: `test_endpoint_runner.py`, `test_ui_runner.py`.

### Persona C — Frontend completo
Archivos: `frontend/` completo (`api/client.ts`, `components/ChatPanel.tsx`, `PlanView.tsx`, `ResultsView.tsx`, `ReportDownload.tsx`, `App.tsx`).
- Los 4 pasos del flujo (chat -> plan -> ejecutar -> reporte) como estados de `App.tsx`.
- `api/client.ts` contra los 4 endpoints del contrato — mientras el backend no este listo, mockear las respuestas con los JSON de ejemplo del contrato (`TestPlan`, `TestResult[]`, reporte markdown de muestra) para poder maquetar y probar la UI en paralelo.
- Integracion real con backend al final, cuando A y B ya tengan sus endpoints andando.

### Orden sugerido
1. Dia 1: las 3 personas acuerdan el contrato (schemas + shape de endpoints), cada una arranca con mocks del resto.
2. Persona A entrega `/api/chat` + `/api/plan` reales -> Persona B deja de usar el `TestPlan` de ejemplo y prueba con el real.
3. Persona B entrega `/api/execute` + `/api/report` reales -> Persona C conecta el front real, deja de mockear.
4. Integracion final conjunta + prueba end-to-end contra una app de prueba real.

## Verificacion

- Backend: `pytest backend/tests` corre los 2 checks minimos (dispatch de acciones UI, deteccion pass/fail en endpoint runner con mock).
- Manual end-to-end: levantar `uvicorn app.main:app --reload`, levantar `npm run dev` en frontend, probar contra una URL/API real (ej. una app de prueba propia) y confirmar que el reporte final descargado tiene fallos con pasos de reproduccion coherentes.
- Confirmar que `DEEPSEEK_API_KEY` se lee de `.env` (no hardcodeada) y que `.env` esta en `.gitignore`.

## Fuera de alcance (fase 2, no ahora)

- Analisis/testing directo del repositorio (clonar, correr tests existentes, static analysis).
- Autenticacion multi-usuario.
- Dashboard visual de resultados mas alla de lista simple pass/fail.
