# AgenteQA — mapa del repo

Agente QA conversacional: charla para juntar contexto, arma un plan de pruebas, lo ejecuta (UI + endpoints) y genera un reporte descargable. Backend FastAPI + SQLite, frontend React/Vite, LLM vía SDK OpenAI apuntando a Groq (`.env`: `DEEPSEEK_BASE_URL`).

## Conversar y juntar contexto {#chat}

- [x] Chat guiado que junta 4 nodos (objetivo, acceso, alcance, repo) antes de habilitar el plan
      tech: routers/chat.py::post_chat, llm/prompts.py::CHAT_SYSTEM_PROMPT, models/schemas.py::ContextProgress
- [x] Contrasta lo que dice el usuario contra la pagina real en cada turno (inspeccion estatica, sin login)
      tech: chat.py (llama `inspect_page`), llm/page_inspector.py::inspect_page
- [x] Sugiere paginas reales encontradas en la navegacion en vez de que el usuario tipee URLs a mano
      tech: llm/prompts.py::CHAT_SYSTEM_PROMPT (bloque "Sugerencia de paginas")
- [x] Filtro duro de `extra_urls` (mismo dominio, cap 8) — no depende de que el LLM se porte bien
      tech: models/schemas.py::ContextProgress._sanitize_extra_urls

files: [backend/app/routers/chat.py, backend/app/llm/prompts.py, backend/app/models/schemas.py]

## Armar el plan de pruebas, con barrido de pantallas {#plan}

needs: [chat]
links: [data]

- [x] Genera `TestPlan` estructurado (JSON validado con Pydantic, 1 reintento si el LLM devuelve algo invalido)
      tech: routers/plan.py::post_plan, llm/client.py::generate_plan
- [x] Inspecciona la pagina real (estatico o con login via Playwright) antes de generar el plan (endpoint bloqueante original, sigue vivo)
      tech: routers/plan.py::_build_page_snapshot, llm/authenticated_inspector.py::inspect_with_login
- [x] Barrido de pantallas en vivo: navega target_url + extra_urls, captura screenshot + elementos por pagina, streamea NDJSON al frontend
      tech: routers/plan.py::post_plan_sweep, _run_sweep, llm/screen_sweeper.py::capture_page
      by: claude
- [x] Pausa dura si el agente tiene una duda real sobre el comportamiento de una pantalla, retoma tras la respuesta del usuario sin re-visitarla
      tech: routers/plan.py::post_plan_sweep_answer, llm/client.py::check_page_doubt, models/db.py::SweepState
      by: claude
- [x] Pausa dura si se topa con un muro de login no anticipado (o credenciales ya conocidas que fallan), pide credenciales de prueba y retoma sin revisitar lo ya andado
      tech: routers/plan.py::post_plan_sweep_login, _looks_like_login, models/schemas.py::SweepLoginRequest
      by: claude
- [ ] Analisis/testing directo del repositorio de codigo (clonar, correr tests existentes)
      from: roadmap

files: [backend/app/routers/plan.py, backend/app/llm/screen_sweeper.py, backend/app/llm/page_inspector.py, backend/app/llm/authenticated_inspector.py]

## Ejecutar el plan {#execution}

needs: [plan]
links: [data]

- [x] Corre casos `endpoint` con httpx.AsyncClient, compara status/body
      tech: execution/endpoint_runner.py
- [x] Corre casos `ui` con Playwright headless (DSL fijo de 5 acciones), screenshot a disco en el primer step que falla
      tech: execution/ui_runner.py::_capture_screenshot
- [x] Progreso en vivo por streaming NDJSON (una linea por test case a medida que termina)
      tech: routers/execute.py::_execute_and_stream
- [x] Bloqueo duro de dominio: un test case que apunte fuera del dominio confirmado no se ejecuta, aunque el prompt del plan lo hubiera dejado pasar
      tech: routers/execute.py::_blocked_domain

files: [backend/app/execution/, backend/app/routers/execute.py]

## Generar el reporte {#report}

needs: [execution]

- [x] Arma reporte Markdown con fallos, ubicacion, evidencia y pasos de reproduccion
      tech: llm/client.py::generate_report, llm/prompts.py::REPORT_SYSTEM_PROMPT
- [x] Exporta tambien en HTML (`?format=html`, tabla de resultados)
      tech: routers/report.py (param `format`, lib `markdown`)

files: [backend/app/routers/report.py]

## Datos y contrato compartido {#data}

links: [chat, plan, execution]

- [x] Persistencia SQLite: sesiones, historial de mensajes, planes, resultados
      tech: models/db.py (Session, Message, Plan, Result)
- [x] Estado de barrido persistido por sesion, permite pausar/resumir entre requests HTTP sin WebSocket
      tech: models/db.py::SweepState
      by: claude
- [x] Validacion de `TestCase.id` contra path traversal (se usa para nombrar el screenshot en disco)
      tech: models/schemas.py::TestCase (Field pattern)
- [x] Migracion liviana automatica: agrega columnas nuevas a tablas SQLite existentes al arrancar (create_all nunca altera tablas ya creadas)
      tech: models/db.py::_add_missing_columns, init_db
      by: claude
- [ ] Autenticacion multi-usuario
      from: roadmap

files: [backend/app/models/db.py, backend/app/models/schemas.py]

## Frontend: chat, plan, ejecucion y reporte en una sola vista {#frontend}

needs: [chat, plan, execution, report]

- [x] Chat con stepper de progreso de los 4 nodos, dispara el plan solo cuando `ready_for_plan` es real
      tech: App.jsx::QaStepper, handleSendMessage
- [x] Panel de barrido en vivo: capturas + resumen por pantalla, input de respuesta cuando hay una pregunta pendiente
      tech: App.jsx::SweepPanel, api/client.js::sweepPlan/answerSweepQuestion
      by: claude
- [x] Ejecucion con progreso en vivo ("Ejecutando prueba X de Y...")
      tech: api/client.js::executePlan, App.jsx::handleExecutePlan
- [x] Descarga de reporte (Markdown/HTML)
      tech: api/client.js::downloadReport
- [x] Recupera el historial de chat al refrescar (via `session_id` en localStorage)
      tech: App.jsx (useEffect inicial + getChatHistory)
- [ ] Recuperar plan/resultados al refrescar (hoy solo se recupera el historial de chat; no hay endpoint para pedir el ultimo plan sin regenerarlo)
      from: roadmap
- [ ] Dashboard visual de resultados mas alla de una lista simple pass/fail
      from: roadmap

files: [frontend/src/App.jsx, frontend/src/api/client.js, frontend/src/styles.css]

## decisions

- Backfill inicial de este PLAN.md (reemplaza el plan de diseño original de la tesis, movido a `AgenteQA/00-Plan-General.md` como referencia historica — no se borro, solo dejo de ser la fuente de verdad de estado).
- 6 componentes elegidos: `chat`/`plan`/`execution`/`report` siguen el pipeline de 4 pasos del producto; `data` se separó porque es un contrato compartido activo (creció con `SweepState` esta misma sesión, no es plumbing estable); `frontend` es un solo componente porque hoy es un unico archivo (`App.jsx`) sin sub-partes independientes.
- Los 3 items "fuera de alcance fase 2" del plan de diseño original (analisis de repo, auth multi-usuario, dashboard visual) se migraron como tareas `from: roadmap` en el componente que mas de cerca les corresponde, en vez de quedar en una lista aparte.
- Todo lo marcado `[x]` se verifico contra el codigo actual (no contra la Bitacora ni el README) durante esta sesion; ningun estado se tomo prestado de la prosa sin confirmar la funcion/archivo citado en `tech:`.
