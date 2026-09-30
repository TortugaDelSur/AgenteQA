# Trabajo en paralelo: repo + runner + vista en vivo + causa probable

Checklist operativo para que varias personas o agentes avancen a la vez sin pisarse.
La fuente de verdad del estado sigue siendo `PLAN.md`: al tomar una tarea, marcala `[~]` con tu nombre **aquí y en PLAN.md**.

## Orden y dependencias

```
Pista 0 (contratos) ──┬──> A (leer repo) ──┐
                      ├──> B (runner) ─────┼──> D (causa probable)
                      └──> C (en vivo + pausa)
```

- La pista 0 va primero y es chica. Congela los contratos de abajo.
- A, B y C corren en paralelo.
- D necesita que A y B estén listas.

## Contratos congelados

Si hay que cambiar uno, avisá a las otras pistas antes de hacerlo.

**`backend/app/security.py`**
```python
def redact(text: str, secrets: Iterable[str] = ()) -> str: ...
def wrap_untrusted(label: str, text: str) -> str: ...
```

**`backend/app/repo/credentials.py`** (solo en memoria, nunca DB ni logs)
```python
def set_token(session_id: str, provider: Literal["github", "bitbucket"], token: str) -> None: ...
def get_token(session_id: str, provider: str) -> str | None: ...
def status(session_id: str) -> dict[str, bool]: ...   # {"github": True, "bitbucket": False}
def known_secrets(session_id: str) -> list[str]: ...  # valores, para pasarlos a redact()
```

**`backend/app/repo/clone.py`**
```python
def clone(repo_url: str, dest: Path, token: str | None) -> Path: ...
def cleanup(dest: Path) -> None: ...
```

**`backend/app/repo/inspector.py`**
```python
def inspect_repo(path: Path) -> RepoInfo: ...
def format_repo_summary(info: RepoInfo) -> str: ...  # ya pasado por redact + wrap_untrusted
```

**`RepoInfo`** (en `models/schemas.py`)
```python
class RepoInfo(BaseModel):
    framework: str | None
    has_compose: bool
    has_dockerfile: bool
    services: list[str]
    ports: list[int]
    env_example_keys: list[str]   # solo nombres, nunca valores
    api_routes: list[str]
```

**API del runner** (`runner/`, puerto 8100, header `X-Runner-Token`)
- `POST /runs`, body `{"session_id": str, "repo_path": str}`. Responde `{"run_id": str, "urls": ["http://127.0.0.1:NNNN"]}`, o `422 {"detail": "sin docker-compose.yml ni Dockerfile"}`.
- `GET /runs/{run_id}/logs?tail=200` responde `{"logs": str}` (texto crudo; el backend lo redacta).
- `DELETE /runs/{run_id}` responde `{"status": "stopped"}`.

**WebSocket de vista en vivo**: `GET /ws/live/{session_id}`, solo servidor a cliente. Mensajes JSON:
- `{"type": "frame", "data": "<jpeg base64>"}`
- `{"type": "step", "test_case_id": str, "index": int, "action": str, "target": str}`
- `{"type": "paused", "reason": "login" | "question" | "unreachable", "detail": str}`
- `{"type": "done"}`

**Pausa de ejecución**, igual que sweep:
- `POST /api/execute/answer`, body `{"session_id", "answer"}`.
- `POST /api/execute/login`, body `{"session_id", "username", "password"}`.
- El NDJSON de `/api/execute` puede terminar con `{"type": "paused", ...}` como última línea.

**`TestResult.suspected_cause`** (opcional)
```python
class SuspectedCause(BaseModel):
    file: str
    line: int | None
    explanation: str
    confidence: Literal["alta", "media", "baja"]
```

## Pista 0: contratos (primero)

Estado: hecha (claude). Además, el chat redacta tokens pegados en el mensaje y el prompt pide `repo_url` sin pedir nunca el token.
Archivos: `backend/app/security.py`, `backend/app/models/schemas.py`, `runner/README.md`
- [x] `redact` + `wrap_untrusted`, con test
- [x] `ContextProgress.repo_url` con filtro de host (github.com, bitbucket.org), con test
- [x] `RepoInfo`, `SuspectedCause`, `TestResult.suspected_cause`
- [x] `runner/README.md` con el contrato HTTP

## Pista A: leer el repo

Archivos: `backend/app/repo/**`, `backend/app/routers/repo.py`, `backend/app/main.py` (solo el include del router), `llm/prompts.py` (bloque del repo en chat)
- [ ] `credentials.py` en memoria + `POST /api/repo/credentials` + `GET /api/repo/status`
- [ ] `clone.py`: `--depth 1`, token por `GIT_CONFIG_*`, timeout. Test: el token nunca aparece en argv
- [ ] `inspector.py`: framework, compose, servicios, puertos, claves de `.env.example`, rutas de la API
- [ ] Chat usa `format_repo_summary` como contexto, junto a `page_snapshot`
- [ ] Front: campo password del token más estado conectado (coordinar con C por `App.jsx`)

## Pista B: levantar el repo

Archivos: `runner/**`, `backend/app/runner_client.py`
- [ ] Servicio FastAPI con los 3 endpoints del contrato
- [ ] Override de compose generado: límites, `no-new-privileges`, puertos en 127.0.0.1
- [ ] `.env` dummy desde `.env.example`; nunca usar un `.env` existente del repo
- [ ] Detección de puerto web y healthcheck HTTP hasta que responda (con timeout)
- [ ] Dockerfile sin compose: `docker build` + `docker run` con los mismos límites
- [ ] `runner_client.py` (httpx) en el backend
- [ ] Test con fixture mínimo (compose con nginx): sube, responde, logs, se destruye

## Pista C: en vivo y pausa

Estado: en curso (claude).
Archivos: `backend/app/execution/**`, `backend/app/routers/execute.py`, `backend/app/live.py` (bus + WS), `models/db.py` (`ExecutionState`), `frontend/src/**`
- [~] Browser compartido en `_execute_and_stream`, pasado a `run_ui(browser=...)`
- [~] Bus en memoria + `/ws/live/{session_id}` (solo servidor a cliente)
- [~] Screencast CDP publicando frames al bus; eventos `step` por paso
- [~] `ExecutionState` + `/api/execute/answer` + `/api/execute/login`; retomar sin repetir casos
- [~] Pausar solo por login, app inalcanzable o duda (con tope); un assert fallido no pausa
- [~] Front: `LivePanel` (solo lectura) + cuadro de respuesta que reutiliza la UI de `SweepPanel`

## Pista D: causa probable (después de A y B)

Archivos: `backend/app/diagnosis.py`, `backend/app/routers/report.py`, `llm/prompts.py` (`REPORT_SYSTEM_PROMPT`)
- [ ] Juntar logs (`runner_client`), detalle y evidencia del test fallido
- [ ] Grep en el repo por path de la URL, texto del selector y mensaje de error
- [ ] Prompt a LLM con `redact` + `wrap_untrusted`, que devuelva `SuspectedCause` validado
- [ ] Mostrar la causa en el reporte (Markdown y HTML)

## Archivos compartidos (coordinar antes de tocarlos)

- `frontend/src/App.jsx`: lo tocan A (campo de token) y C (LivePanel). Cada pista agrega su componente en un archivo propio bajo `frontend/src/components/` y solo toca `App.jsx` para montarlo.
- `backend/app/llm/prompts.py`: lo tocan A (chat) y D (reporte). Son bloques distintos.
- `backend/app/models/schemas.py`: se cierra en la pista 0. Después, solo agregar campos.

## Verificación final (end-to-end)

- [ ] Backend, runner y front arriba; en el chat, URL de un repo de la empresa y token por la UI
- [ ] Clona, levanta, y el barrido corre contra `127.0.0.1:<puerto>`
- [ ] Ejecutar y ver el navegador en vivo; forzar un login y ver la pausa con la pregunta
- [ ] Forzar un fallo y ver la causa probable en el reporte
- [ ] `grep` del token en `agenteqa.db`, logs y respuestas del LLM: cero apariciones
