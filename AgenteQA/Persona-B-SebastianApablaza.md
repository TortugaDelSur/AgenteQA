# Modulo Persona B — Motor de ejecucion + Reporte (documentacion, no implementacion)

## Estado: implementado y revisado (2026-08-29)

- [x] `execution/endpoint_runner.py` — coincide con el spec (pass/fail/error, evidence con HTTP+body). Tests con `httpx.MockTransport` real (mejor que inventar un fake), cubre status/body mismatch, request que revienta, sin `request` definido, sin expectativas, y que cierra el client propio si no le inyectan uno.
- [x] `execution/ui_runner.py` — dispatch fijo de 5 acciones sobre Playwright, screenshot en fallo, browser inyectable para tests (mismo patron que se replico despues en `authenticated_inspector.py` de Persona A).
- [x] `execution/runner.py` — dispatch por tipo en serie (decision correcta: Playwright compite por recursos si se paraleliza).
- [x] `routers/execute.py` — agrego 409 explicito si la sesion no tiene plan (no estaba en el spec, buena adicion).
- [x] `routers/report.py` — agrego 409 explicito si no hay resultados, manejo de error del LLM igual al patron de `chat.py`/`plan.py` (502).
- [x] `llm/client.py::generate_report()` y `REPORT_SYSTEM_PROMPT` completados.
- [x] Tests: `test_endpoint_runner.py`, `test_ui_runner.py`, `test_runner.py`, `test_execute_router.py`, `test_report_router.py`. Suite completa (con el modulo de Persona A): 67 tests, 98.79% cobertura.
- [x] Verificado end-to-end real (Diego, 2026-08-29): chat -> plan -> execute (login real contra `the-internet.herokuapp.com`) -> reporte `.md` descargado, 2/2 casos pass. Funciona de punta a punta.
- [x] `playwright install chromium` ya esta en `README.md` (agregado por Diego en el setup inicial).

Todo lo de abajo es el plan original, dejado como referencia.

## Contexto

Fase siguiente del flujo AgenteQA: ejecutar el `TestPlan` que ya genera el modulo de Diego (Persona A) y armar el reporte final. Este modulo es scope de **Sebastian Apablaza (Persona B)** segun `00-Plan-General.md` — acá se documenta en detalle para que el lo implemente, sin escribir el motor de ejecucion nosotros.

Pregunta que origino esto: "necesitamos otro LLM/API key para que el agente siga el plan de pruebas?"

**Respuesta: no.** La ejecucion es deterministica, no agentic. El `TestPlan` ya sale de Persona A como JSON con un DSL fijo y acotado (`goto`, `click`, `fill`, `assert_text`, `assert_visible` para UI; `method/url/headers/body` para endpoints) — justamente se forzo ese schema para que un motor mecanico lo pueda ejecutar paso a paso sin razonar nada. El runner es un dispatcher (diccionario accion -> funcion), no un agente.

El LLM vuelve a aparecer una sola vez mas: al final, para redactar el reporte legible a partir de los resultados crudos (`generate_report`). Ahi se reusa el mismo cliente/API key ya armado en `llm/client.py` (Groq en dev, DeepSeek en prod) — no hace falta un segundo modelo ni una key aparte.

## Unica pieza que agrega Diego ahora (extension minima del contrato)

`backend/app/models/schemas.py` y `backend/app/models/db.py` son archivos que ya posee Persona A (schemas/DB son el contrato compartido). Para no bloquear a Sebastian con un archivo que el no toca, Diego agrega ahora:

```python
# schemas.py
class TestResult(BaseModel):
    test_case_id: str
    status: Literal["pass", "fail", "error"]
    detail: str                    # mensaje de error, diff de assertion, etc.
    evidence: str | None = None    # path a screenshot (ui) o snippet de response (endpoint)

class ExecutionResponse(BaseModel):
    session_id: str
    results: list[TestResult]
```

```python
# db.py
class Result(Base):
    __tablename__ = "results"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    test_case_id: Mapped[str]
    status: Mapped[str]
    detail: Mapped[str]
    evidence: Mapped[str | None]
    created_at: Mapped[datetime.datetime] = mapped_column(default=datetime.datetime.utcnow)
```

Todo lo demas de abajo lo implementa Sebastian.

## Archivos que implementa Sebastian

```
backend/app/execution/endpoint_runner.py
backend/app/execution/ui_runner.py
backend/app/execution/runner.py
backend/app/routers/execute.py
backend/app/routers/report.py
backend/app/llm/client.py::generate_report()   # completa la firma que dejo Diego (NotImplementedError)
backend/app/llm/prompts.py                      # agrega REPORT_SYSTEM_PROMPT
backend/tests/test_endpoint_runner.py
backend/tests/test_ui_runner.py
```

### `endpoint_runner.py`
- `async def run_endpoint(tc: TestCase) -> TestResult`.
- `httpx.AsyncClient` con el `tc.request` (method/url/headers/body).
- Compara `response.status_code == tc.expected_status` y `tc.expected_body_contains in response.text` (si viene seteado).
- `status="pass"` si ambas checks pasan, `"fail"` si alguna no, `"error"` si la request tira excepcion (timeout, conexion rechazada, etc — no dejar que tumbe todo el runner).
- `detail`: texto claro de que fallo (ej. "esperaba status 200, recibio 404").

### `ui_runner.py`
- `async def run_ui(tc: TestCase) -> TestResult` con `playwright.async_api.async_playwright()`, chromium headless.
- Dispatch fijo por `action` (diccionario `{"goto": ..., "click": ..., "fill": ..., "assert_text": ..., "assert_visible": ...}`), NO agregar acciones nuevas sin actualizar el schema `UiStep` de Persona A.
- Ejecuta los `steps` en orden; si un step falla (selector no encontrado, assertion no cumple), corta ahi, captura `page.screenshot()` a `backend/screenshots/{session_id}/{tc.id}.png`, guarda ese path en `evidence`.
- `detail`: que step fallo y por que (ej. "step 4 (assert_text en '.error-message'): esperaba 'Invalid credentials', no encontrado").

### `runner.py`
- `async def run_plan(session_id: str, plan: TestPlan) -> list[TestResult]`: itera `plan.test_cases`, dispatch por `tc.type` (`"ui"` -> `run_ui`, `"endpoint"` -> `run_endpoint`), corre todo con `asyncio.gather` si conviene paralelizar (ojo con Playwright: un browser context por test, o serializar si da problemas de recursos — decision de Sebastian segun lo que le funcione mas simple).

### `routers/execute.py`
- `POST /api/execute` — body `{session_id: str}`.
- Carga el `Plan` mas reciente de esa sesion desde `db.py` (`Plan.plan_json` -> `TestPlan.model_validate_json(...)`).
- Corre `runner.run_plan(session_id, plan)`, guarda cada `TestResult` como fila `Result` en DB.
- Devuelve `ExecutionResponse`.

### `routers/report.py`
- `GET /api/report/{session_id}` — carga `Plan` + todos los `Result` de esa sesion.
- Llama `llm.generate_report(plan, results)` (usa el mismo cliente de `llm/client.py`, agrega `REPORT_SYSTEM_PROMPT` en `prompts.py` con instrucciones: por cada fallo, seccion con ubicacion (selector/pagina o metodo+url del endpoint), descripcion del fallo, evidencia (referenciar el path de screenshot o el snippet de response), y pasos de reproduccion numerados).
- Devuelve el markdown como descarga (`Response(content=md, media_type="text/markdown", headers={"Content-Disposition": "attachment; filename=reporte.md"})`).

## Verificacion (para Sebastian)

- `pytest backend/tests` corre `test_endpoint_runner.py` (mockear un server con `httpx` o `respx`) y `test_ui_runner.py` (dispatch de accion conocida/desconocida, sin necesidad de un browser real para el check minimo).
- Manual: usar el fixture `SAMPLE_TEST_PLAN` de `backend/tests/fixtures.py` (ya armado por Diego) contra una pagina real de prueba (ej. `https://practicetestautomation.com/practice-test-login/`) para validar `run_ui` de punta a punta sin depender del LLM.
- End-to-end completo: `POST /api/chat` (varias veces) -> `POST /api/plan` -> `POST /api/execute` -> `GET /api/report/{session_id}` descarga un `.md` legible con los fallos reales.

## Fuera de alcance (no ahora)

- Paralelizacion agresiva de tests UI (un browser por test es mas simple y suficiente para el MVP).
- Reintentos automaticos de tests flaky.
- Conversion a `.html` del reporte (mencionada como opcional en el plan general, agregar solo si sobra tiempo).
