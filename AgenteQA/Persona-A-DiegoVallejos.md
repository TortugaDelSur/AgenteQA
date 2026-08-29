# Persona A — Diego Vallejos — LLM + Conversacion + Plan de pruebas

## Estado
- [x] `config.py`
- [x] `models/schemas.py`
- [x] `models/db.py`
- [x] `llm/client.py` (`generate_report` queda con `NotImplementedError` para Persona B)
- [x] `llm/prompts.py`
- [x] `routers/chat.py`
- [x] `routers/plan.py`
- [x] `main.py`
- [x] Probado end-to-end con curl (chat -> historial -> plan) usando Groq (`openai/gpt-oss-120b`)
- [x] Fixture `tests/fixtures.py` con `TestPlan` de ejemplo para Persona B
- [x] Tests minimos (`tests/test_schemas.py`) pasando

## Contexto

Primera etapa del flujo: conversacion con el usuario para levantar contexto, y generacion del plan de pruebas estructurado que despues ejecuta el modulo de Persona B (Sebastian Apablaza). Sin esto, no hay `TestPlan` que ejecutar.

Dos decisiones de diseño:
1. **Recuperar sesion ante refresh/caida de conexion**: el historial vive en SQLite server-side; el front solo necesita recordar el `session_id` (localStorage) y poder pedir el historial de vuelta.
2. **Contexto por nodos en vez de un solo boton**: checklist fija de temas (nodos) que el LLM va marcando como completos a medida que la conversacion avanza. El front muestra el progreso y habilita "Generar plan" cuando estan los obligatorios — el usuario siempre puede forzarlo antes.

## Nodos de contexto (checklist fija)

| Nodo | Obligatorio | Que cubre |
|---|---|---|
| `objetivo` | si | que se quiere testear, tipo de app (web/API) |
| `acceso` | si | URL de la app, credenciales de prueba si aplica |
| `alcance` | si | endpoints/funcionalidades clave a cubrir |
| `repo` | no | link al repositorio (si lo tiene, se guarda para fase 2, no se usa aun) |

`ready_for_plan = objetivo AND acceso AND alcance`. Lista fija en `prompts.py`, no motor de grafos — se amplia despues si hace falta (YAGNI por ahora).

## Contrato de datos

`backend/app/models/schemas.py`:
```python
class ContextProgress(BaseModel):
    objetivo: bool = False
    acceso: bool = False
    alcance: bool = False
    repo: bool = False

class ChatRequest(BaseModel):
    session_id: str | None = None   # None -> backend crea uno nuevo
    message: str

class ChatResponse(BaseModel):
    session_id: str
    reply: str
    context: ContextProgress
    ready_for_plan: bool

class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]      # role: "user" | "assistant"
    context: ContextProgress
    ready_for_plan: bool

# TestCase / TestPlan: igual al schema fijado en 00-Plan-General.md (seccion "Generar plan")
```

## Modelo de datos (SQLite)

`backend/app/models/db.py` (SQLAlchemy):
- `Session(id: str PK, created_at, context_json: str)` — `context_json` guarda el `ContextProgress` serializado.
- `Message(id PK autoincrement, session_id FK, role, content, created_at)`.
- `Plan(id PK autoincrement, session_id FK, plan_json: str, created_at)`.

Sin expiracion/TTL de sesiones en el MVP.

## Endpoints

- **`POST /api/chat`** — body `ChatRequest`.
  - Si `session_id` es `None` o no existe: crea `Session` nueva (uuid4), `context_json` default.
  - Guarda `Message(role="user", ...)`.
  - Llama `llm.chat(history, context_actual)` -> LLM devuelve JSON `{reply, context}`.
  - Actualiza `Session.context_json`, guarda `Message(role="assistant", ...)`.
  - Devuelve `ChatResponse`.

- **`GET /api/chat/{session_id}`** — recuperar sesion tras refresh/caida.
  - No existe: 404 (front arranca sesion nueva).
  - Existe: devuelve `ChatHistoryResponse` con mensajes + progreso actual.

- **`POST /api/plan`** — body `{session_id: str}`.
  - Carga historial completo.
  - Llama `llm.generate_plan(history)` -> pide JSON con schema `TestPlan` fijo.
  - `json.loads` + validacion Pydantic. Si falla: 1 reintento con el error como feedback. Si vuelve a fallar: 502.
  - Guarda `Plan` en DB, devuelve `TestPlan`.

## LLM (`backend/app/llm/`)

`client.py`:
- `get_client()`: `openai.OpenAI(base_url=settings.DEEPSEEK_BASE_URL, api_key=settings.DEEPSEEK_API_KEY)` — funciona igual con Groq o DeepSeek, solo cambia `.env`.
- `chat(history, context) -> tuple[str, ContextProgress]`: `response_format={"type": "json_object"}`, parsea `{reply, context}`.
- `generate_plan(history) -> TestPlan`: idem, valida contra `TestPlan`, 1 reintento si invalido.
- `generate_report(plan, results)`: firma vacia (`raise NotImplementedError`) — la implementa Persona B.

`prompts.py`:
- `CHAT_SYSTEM_PROMPT`: describe los 4 nodos, instruye a preguntar por los que falten uno a la vez, devolver siempre JSON `{"reply": "...", "context": {...}}`.
- `PLAN_SYSTEM_PROMPT`: instruye a generar `TestPlan` con el JSON schema fijo (pegar schema completo de `00-Plan-General.md`), basado en todo el historial.

## Config (`backend/app/config.py`)

`pydantic-settings.BaseSettings`: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` (default `"deepseek-chat"`, en Groq se pisa por `.env` con `llama-3.3-70b-versatile`), `DB_PATH`.

## Archivos a crear/tocar

```
backend/app/config.py
backend/app/models/schemas.py
backend/app/models/db.py
backend/app/llm/client.py
backend/app/llm/prompts.py
backend/app/routers/chat.py
backend/app/routers/plan.py
backend/app/main.py            # minimo, para poder levantar el server
```

## Verificacion

- `uvicorn app.main:app --reload`, probar con `curl`:
  1. `POST /api/chat` sin `session_id` -> `session_id` nuevo + pregunta del nodo `objetivo`.
  2. Repetir con mismo `session_id` contestando cada nodo -> `context` marca `true` hasta `ready_for_plan: true`.
  3. `GET /api/chat/{session_id}` -> historial completo (simula refresh).
  4. `POST /api/plan` -> `TestPlan` valido.
- Fixture de `TestPlan` de ejemplo exportada para que Persona B arranque sin depender del LLM real.
- `.env` con la key no se commitea (ya en `.gitignore`).

## Notas / avances (ir actualizando)

- 2026-08-29: plan del modulo definido y aprobado. Sin codigo escrito aun.
- 2026-08-29: modulo implementado completo y probado. Nota: Groq deprecó `llama-3.3-70b-versatile`, se uso `openai/gpt-oss-120b` en su lugar. `DEEPSEEK_MODEL` agregado a `.env` para que quede explicito. `.venv` de backend creado localmente (no se commitea).
