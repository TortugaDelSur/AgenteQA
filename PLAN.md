# AgenteQA — mapa del repo

Agente QA conversacional: charla para juntar contexto, arma un plan de pruebas, lo ejecuta (UI + endpoints) y genera un reporte descargable. Backend FastAPI + SQLite, frontend React/Vite, LLM vía SDK OpenAI apuntando a Groq (`.env`: `DEEPSEEK_BASE_URL`).

## Conversar y juntar contexto {#chat}

- [x] Chat guiado que junta 4 nodos (objetivo, acceso, alcance, repo) antes de habilitar el plan
      tech: routers/chat.py::post_chat, llm/prompts.py::CHAT_SYSTEM_PROMPT, models/schemas.py::ContextProgress
- [x] Aceptar "quiero validar/probar un repo" como pedido principal: pide el link primero y, con repo, no pide URL
      tech: llm/prompts.py::CHAT_SYSTEM_PROMPT (intro, nodo acceso, orden, fuera de alcance)
      by: claude
- [x] Preguntar si hay repositorio despues del objetivo: sin repo pide la URL (flujo original); con repo muestra bajo el chat el aviso de token o la lista de repos, y al elegir sigue solo
      tech: ContextProgress.wants_repo; chat.py fija repo/wants_repo; components/RepoPicker.jsx (RepoNeedsToken + lista); POST /api/repo/select guarda la siguiente pregunta en el historial
      by: claude
- [x] Contrasta lo que dice el usuario contra la pagina real en cada turno (inspeccion estatica, sin login)
      tech: chat.py (llama `inspect_page`), llm/page_inspector.py::inspect_page
- [x] Sugiere paginas reales encontradas en la navegacion en vez de que el usuario tipee URLs a mano
      tech: llm/prompts.py::CHAT_SYSTEM_PROMPT (bloque "Sugerencia de paginas")
- [x] Filtro duro de `extra_urls` (mismo dominio, cap 8) — no depende de que el LLM se porte bien
      tech: models/schemas.py::ContextProgress._sanitize_extra_urls
- [x] Pedir la URL del repo y aceptar solo GitHub o Bitbucket {#repo-url}
      tech: ContextProgress.repo_url + filtro duro de host, mismo estilo que _sanitize_extra_urls
      from: agent
      by: claude
- [x] Usar el resumen del repo clonado (framework, servicios, rutas) como contexto del chat
      tech: routers/chat.py -> repo/workspace.py::repo_context (mensaje efimero, no se guarda); redact con known_secrets
      by: claude

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

files: [backend/app/routers/plan.py, backend/app/llm/screen_sweeper.py, backend/app/llm/page_inspector.py, backend/app/llm/authenticated_inspector.py]

## Ejecutar el plan {#execution}

needs: [plan]
links: [data]

- [x] Con credenciales, loguearse recien en la pagina que tiene el campo password, no en la home (antes pedia credenciales en bucle)
      tech: routers/plan.py::_run_sweep (try_login al detectar _looks_like_login; login_url solo si ya se encontro)
      by: claude
- [x] Corre casos `endpoint` con httpx.AsyncClient, compara status/body
      tech: execution/endpoint_runner.py
- [x] Corre casos `ui` con Playwright headless (DSL fijo de 5 acciones), screenshot a disco en el primer step que falla
      tech: execution/ui_runner.py::_capture_screenshot
- [x] Progreso en vivo por streaming NDJSON (una linea por test case a medida que termina)
      tech: routers/execute.py::_execute_and_stream
- [x] Bloqueo duro de dominio: un test case que apunte fuera del dominio confirmado no se ejecuta, aunque el prompt del plan lo hubiera dejado pasar
      tech: routers/execute.py::_blocked_domain
- [x] Usar un solo navegador para toda la ejecucion (requisito de la vista en vivo) {#shared-browser}
      tech: _execute_and_stream abre el browser y lo pasa a run_ui(browser=...)
      from: agent
      by: claude
- [x] Ver el navegador en vivo mientras corre cada prueba, solo lectura: el usuario mira, no puede hacer clic ni escribir
      tech: Playwright CDP `Page.startScreencast`, WebSocket en FastAPI (solo servidor a cliente, sin eventos de entrada), canvas en el front
      from: agent
      by: claude
- [x] Si el agente se topa con algo que no puede resolver (login, duda, error inesperado), pausa la prueba y le pregunta al usuario; retoma con la respuesta
      tech: ExecutionState (copia de SweepState) + POST /api/execute/answer y /login; un assert que falla NO pausa, es un resultado
      from: agent
      by: claude
- [x] Levantar el repo antes del barrido y probar contra su URL local {#wire-runner}
      tech: repo/launch.py + routers/plan.py::_run_sweep (evento "launching"); varias URLs -> pregunta REPO_CHOICE en el barrido; _point_to_app muda target_url y extra_urls
      from: agent
      by: claude
- [x] Apagar el repo levantado al terminar las pruebas, o si la pagina del agente se cierra o se corta internet; un refresco no lo apaga
      tech: launch.stop al final de _execute; launch.reap_idle (WS sin mirar > 90 s y sin barrido/ejecucion en curso, launch.hold); relevanta solo en _ensure_app y muda el plan al puerto nuevo
      by: claude
- [x] Con repo levantado, todas las URLs del plan apuntan a la app local (el LLM las armaba desde lo que dijo el usuario en el chat)
      tech: launch.rebase_plan tras generate_plan en _run_sweep; en _ensure_app solo el host viejo
      by: claude
- [x] La vista en vivo se entera cuando la pagina se cierra aunque no haya mensajes (sin esto el repo nunca se apagaba)
      tech: live.py::_until_disconnect corre junto al envio; lo que manda el cliente se descarta
      by: claude
- [x] Tras refrescar la pagina, la pausa pendiente sigue visible y se puede responder
      tech: GET /api/execute/state/{session_id}; LivePanel lo consulta al montarse
      by: claude
- [x] Detectar muro de login mirando si el password de la pagina ya tiene valor, no por el nombre del selector
      tech: ui_runner._password_filled (page.evaluate)
      by: claude

files: [backend/app/execution/, backend/app/routers/execute.py, backend/app/live.py]

## Generar el reporte {#report}

needs: [execution]

- [x] Arma reporte Markdown con fallos, ubicacion, evidencia y pasos de reproduccion
      tech: llm/client.py::generate_report, llm/prompts.py::REPORT_SYSTEM_PROMPT
- [x] Exporta tambien en HTML (`?format=html`, tabla de resultados)
      tech: routers/report.py (param `format`, lib `markdown`)
- [x] Senalar la posible causa de cada fallo (archivo y linea del repo) con su nivel de confianza
      tech: backend/app/diagnosis.py — logs del runner (stack trace mapeado al repo) + grep por ruta/selector/texto; solo archivos que existen; Result.suspected_cause_json; se muestra en ejecucion y reporte
      from: agent
      by: claude

files: [backend/app/routers/report.py, backend/app/diagnosis.py]

## Leer el repo de la empresa {#repo}

needs: [chat]
links: [runner, report]

- [x] Conectar GitHub o Bitbucket con un token sin que el modelo lo vea
      tech: campo password en la UI -> POST /api/repo/credentials; repo/credentials.py guarda solo en memoria por sesion; el LLM solo ve "conectado"
      from: agent
      by: claude
- [x] Verificar el token contra el proveedor al conectarlo, y listar los repos a los que da acceso
      tech: repo/providers.py (GitHub /user/repos, Bitbucket /2.0/repositories?role=member con API token + email opcional), hasta 300 repos
      by: claude
- [ ] Probar el listado y el clone contra una cuenta real de Bitbucket (solo verificado con la documentacion y mocks)
      from: agent
- [x] Bajar una copia liviana del repo a una carpeta temporal por sesion y borrarla al terminar
      tech: git clone --depth 1 con validacion de dominio del proveedor (anti-SSRF)
      from: agent
      by: claude
- [x] Entender el repo: estructura, framework, rutas de la API y como se levanta
      tech: repo/inspector.py, contenido del repo tratado como no confiable (wrap_untrusted)
      from: agent
      by: claude

files: [backend/app/repo/**, backend/app/routers/repo.py]

## Levantar el repo de forma aislada {#runner}

needs: [repo]
links: [execution]

- [x] Levantar el repo en un contenedor desechable con limites y sin privilegios
      tech: servicio runner separado, API start/logs/stop, rootless, sin docker.sock en el backend
      from: agent
      by: claude
- [x] Usar `docker-compose.yml` o `Dockerfile` del repo; si no hay, avisar claro
      from: agent
      by: claude
- [x] Generar valores dummy para los `.env`; nunca arrancar con un `.env` que no genero el runner
      from: agent
      by: claude
- [x] Impedir que el compose del repo lea archivos de la maquina (configs/secrets con file, volumenes bind disfrazados, build fuera del repo)
      tech: runner/app.py::harden -> 422; volumenes quedan vacios del run; additional_contexts se quitan
      by: claude
- [ ] Cortar la salida a internet de la app mientras se prueba
      tech: red `internal` + Playwright dentro de esa red; hacerlo al migrar a instancia
      from: roadmap

files: [runner/**, backend/app/runner_client.py]

## Datos y contrato compartido {#data}

links: [chat, plan, execution, repo]

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
- [x] Ocultar secretos antes de hablar con el modelo {#redact}
      tech: backend/app/security.py — redact() + wrap_untrusted(); todo lo que viene del repo, logs o pagina pasa por ahi
      from: agent
      by: claude
- [x] Guardar donde quedo pausada una ejecucion para retomarla {#exec-state}
      tech: models/db.py::ExecutionState
      from: agent
      by: claude
- [ ] Autenticacion multi-usuario
      from: roadmap
- [ ] Proteger la vista en vivo y la API al pasar a instancia (WebSocket sin auth y CORS `*` hoy)
      tech: /ws/live/{session_id} solo pide el session_id; main.py allow_origins=["*"]
      from: roadmap

files: [backend/app/models/db.py, backend/app/models/schemas.py, backend/app/security.py]

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
- [x] Pantalla de Integraciones para conectar GitHub o Bitbucket (el chat ya no se bloquea: se pide recien si el usuario dice que tiene repo) {#live-ui}
      tech: components/IntegrationsPage.jsx + IntegrationGate.jsx (modal); nav Agente/Integraciones en la sidebar; backend /api/integrations (token por proveedor, solo memoria)
      by: claude
- [x] Mostrar el navegador en vivo y el cuadro de respuesta cuando la ejecucion pausa
      tech: components/LivePanel.jsx (img con el ultimo frame JPEG, clases sweep-*), api/client.js::openLiveSocket, proxy /ws en vite.config.js
      by: claude
- [ ] Recuperar plan/resultados al refrescar (hoy solo se recupera el historial de chat; no hay endpoint para pedir el ultimo plan sin regenerarlo)
      from: roadmap
- [ ] Dashboard visual de resultados mas alla de una lista simple pass/fail
      from: roadmap

files: [frontend/src/App.jsx, frontend/src/api/client.js, frontend/src/styles.css, frontend/src/components/**, frontend/vite.config.js]

## decisions

- Backfill inicial de este PLAN.md (reemplaza el plan de diseño original de la tesis, movido a `AgenteQA/00-Plan-General.md` como referencia historica — no se borro, solo dejo de ser la fuente de verdad de estado).
- 6 componentes elegidos: `chat`/`plan`/`execution`/`report` siguen el pipeline de 4 pasos del producto; `data` se separó porque es un contrato compartido activo (creció con `SweepState` esta misma sesión, no es plumbing estable); `frontend` es un solo componente porque hoy es un unico archivo (`App.jsx`) sin sub-partes independientes.
- Los 3 items "fuera de alcance fase 2" del plan de diseño original (analisis de repo, auth multi-usuario, dashboard visual) se migraron como tareas `from: roadmap` en el componente que mas de cerca les corresponde, en vez de quedar en una lista aparte.
- Todo lo marcado `[x]` se verifico contra el codigo actual (no contra la Bitacora ni el README) durante esta sesion; ningun estado se tomo prestado de la prosa sin confirmar la funcion/archivo citado en `tech:`.
- Nueva necesidad (2026-09-30): el agente debe leer un repo de la empresa (GitHub/Bitbucket por token), levantarlo localmente y probarlo, y si algo falla senalar donde esta el problema. Se evaluaron `agent-toolkit` y `ai-factory-agents/qa-agent` como base: ninguno se adopta. Del primero se toma solo el patron de sandbox (sin docker.sock, efectos reales con aprobacion humana); del segundo `wrap_untrusted` (prompt guardrail) y `qa_json_repair`, reescritos aqui, sin depender de `shared/`.
- 2 componentes nuevos, `repo` y `runner`: son partes durables (`runner` necesita `repo`, borrarlos cambia lo que hace el producto, cada uno tiene mas de una tarea previsible y files propios). La vista en vivo y el diagnostico de causa NO son componentes: son tareas bajo `execution` y `report`, porque tocan los archivos de esos.
- Alcance: repos propios de la empresa (confiables), despliegue local primero y a una instancia despues. Aun asi el repo corre aislado: contenedor efimero, no root, con limites, y un servicio runner separado; el backend nunca monta `docker.sock`.
- Secretos: el token del proveedor y los secretos del repo nunca pasan por el LLM ni por logs. El LLM solo ve nombres (`GITHUB_TOKEN: configurado`). Los `.env` del repo se levantan con valores dummy; un secreto real solo se inyecta como variable del contenedor, nunca como texto en un prompt.
- MVP de `runner`: solo repos con `docker-compose.yml` o `Dockerfile`. Sin eso falla con mensaje claro en vez de adivinar. Para repos sin Docker, una receta propuesta por el LLM exige aprobacion del usuario antes de correr.
- Vista en vivo: screencast CDP de Playwright (`Page.startScreencast`) por WebSocket, pintado en canvas. Reemplaza las capturas sueltas en la pantalla de ejecucion; el NDJSON queda para eventos de texto.
- Vista en vivo de solo lectura: el usuario no controla el navegador. La unica interaccion es responder cuando el agente pausa por si mismo (duda, login, error). Reutiliza la mecanica de pausa del barrido, no se crea una nueva.
- Token (2026-09-30, confirmado por el owner): se ingresa en un campo de la UI, fuera del chat; el backend lo guarda solo en memoria por sesion (se pierde al reiniciar y la UI lo vuelve a pedir). Git lo recibe por variables de entorno (`GIT_CONFIG_*`, `http.extraHeader`), nunca en la URL, argv ni `.git/config`. Reemplaza la opcion `.env` mencionada antes.
- Redaccion centralizada en `backend/app/security.py`: `redact()` enmascara secretos conocidos y patrones (ghp_, github_pat_, Bearer, x-token-auth:), `wrap_untrusted()` marca contenido ajeno. Vive en `data` porque la usan repo, runner, reporte y chat.
- Runner: servicio aparte (`runner/`, FastAPI) que es el unico que toca Docker; el backend le habla por HTTP con token interno. `docker compose -p aqa-<sesion>` + override generado con limites de memoria/CPU/procesos, `no-new-privileges` y puertos solo en 127.0.0.1.
- Red abierta en el MVP (confirmado por el owner): la app probada puede salir a internet, mitigado con `.env` dummy obligatorio. Cortarla exige red `internal` y Playwright dentro de ella; queda como roadmap para la instancia.
- Con repo levantado, su URL local reemplaza a `target_url`: barrido, bloqueo de dominio y ejecucion no cambian. Si el compose publica varios puertos web, el agente pausa y pregunta cual es la app.
- Pausa en ejecucion solo por muro de login, app caida o duda real (con tope). Un assert que falla no pausa.
- Vista en vivo: WebSocket `/ws/live/{session_id}` solo servidor->cliente, bus en memoria de un solo proceso, frames de CDP `Page.startScreencast`. El NDJSON de `/api/execute` sigue para resultados.
- Trabajo en paralelo coordinado en `TRABAJO-PARALELO.md` (pistas 0/A/B/C/D con contratos congelados); PLAN.md sigue siendo la fuente de verdad del estado.
- Vista en vivo (pista C): el frame se pinta en un `<img>` con el ultimo JPEG en vez de un canvas (mismo resultado, sin codigo de dibujo). La pausa se detecta en el runner y viaja como excepcion `ExecutionPaused`: app caida = `net::ERR_*` o `httpx.ConnectError`; login = la pagina del fallo tiene un password y el test no llena ninguno; duda = elemento no encontrado (nunca un assert), max 3 por ejecucion y nunca dos veces para el mismo caso. Al retomar tras un login, se loguea una vez en un context compartido por todos los casos.
- Integracion (2026-09-30): las 3 sesiones paralelas escribieron en la carpeta principal en vez de sus worktrees; se commitearon por separado (B, A, C) en `feature/vision-ejecucion` y se borraron los worktrees. Para la proxima tanda en paralelo, abrir cada sesion desde su carpeta de worktree.
- Runner sin usuario no root forzado: forzar `user:` rompe muchas imagenes. Se compensa con `no-new-privileges`, sin `cap_add`/`privileged` y sin accesos al host. `env_file` fuera del repo no se puede frenar (compose ya lo inlinea); aceptado con repos de la empresa.
- Nadie tomo la decision "la URL del repo levantado reemplaza a target_url": pasa a ser la primera tarea de la pista D (`{#wire-runner}`), porque la causa probable necesita un run activo del que leer logs.
- Vista en vivo y API sin autenticacion en local (WS por session_id, CORS `*`): aceptado para local, tarea de roadmap antes de la instancia.
- Pista D (2026-09-30): el repo levantado queda arriba durante toda la sesion y se apaga al olvidar el repo (`DELETE /api/repo/{id}`, cambio de URL) o al cerrar el backend, no al terminar cada ejecucion: el runner publica puertos al azar, y relevantarlo dejaria las URLs del plan apuntando a un puerto viejo. La causa probable se calcula en el momento en que falla cada caso (logs frescos) y se guarda en `Result`; el reporte solo la presenta. El LLM solo puede señalar archivos que existen en el repo; si inventa uno, no se muestra causa.
- Apagado del repo levantado (2026-09-30, pedido del owner; reemplaza "queda arriba toda la sesion"): se apaga (1) al terminar una ejecucion completa (no al pausar), (2) cuando la pagina del agente se cierra o el usuario pierde internet: nadie mira el WebSocket de la sesion por mas de 90 s y no hay barrido/ejecucion en curso. Un refresco reconecta en segundos, asi que no lo apaga. Si despues se vuelve a barrer o ejecutar, se relevanta solo: se recuerda cual de las URLs era la app (por posicion) y las URLs del plan guardado se mudan al puerto nuevo.
- E2E real (2026-09-30) contra `github.com/TortugaDelSur/agenteqa-demo` (Flask + compose, bug a proposito en `/api/users/<id>`): chat -> clone -> barrido levanta el repo -> plan -> ejecucion en vivo -> reporte con causa `app/main.py:44` (confianza alta). Encontro 5 bugs que los tests con mocks no veian: `.env` con claves extra tumbaba el backend (y pydantic imprimia parte del secreto al log), login en la home en bucle, URLs del plan con el puerto dicho en el chat, WS que no detectaba cierre de pagina, y Playwright del `.venv` nuevo sin su navegador (`playwright install chromium`). Apagado verificado en real: al terminar la ejecucion, por pagina cerrada (~111 s) y NO por refresco. Ningun secreto (API key, RUNNER_TOKEN) en DB, logs ni reporte; las credenciales de prueba (`demo123`) si quedan en la DB, como ya estaba aceptado.
- Integraciones (2026-09-30, pedido del owner): el token de GitHub/Bitbucket se configura en una pantalla "Integraciones" antes de chatear, y el chat queda bloqueado (modal) hasta que haya al menos una conectada. Por eso el token pasa de ser por sesion a ser de la instalacion (uno por proveedor), sigue SOLO en memoria: si el backend se reinicia, el modal vuelve a pedirlo. Valido mientras AgenteQA es local y de un usuario; con multiusuario pasa a ser por usuario (tarea de auth). El bloqueo es de UX en el front; el backend no rechaza chats sin integracion.
- Merge del rediseño del front de `main` (5d1e696, 2026-09-30): se toma todo lo visual (fondo animado con burbujas y glow, barra de progreso, boton copiar, loader, estilos). Se descarta su cambio de comportamiento "al recargar se reinicia el chat": rompia recuperar la conversacion al refrescar (tarea ya hecha) y la regla del owner de que refrescar no interfiera con la ejecucion ni con las pausas. A confirmar con quien hizo el rediseño.
- Prompt del chat (2026-09-30): el agente respondia "no puedo validar repositorios directamente" porque el prompt seguia escrito para el producto anterior (probar una URL desplegada; repo como dato opcional y ultimo; "fuera de alcance" todo lo que no sea juntar contexto). Ahora el repo es el camino principal: si el usuario arranca hablando de un repo se pide el link primero, y con repo el acceso no pide URL (la app se levanta local), solo login y credenciales de prueba. Verificado en 2 corridas reales: listo para el plan en 5 mensajes, target_url null hasta que el barrido levanta el repo.
- Selector de repositorios (2026-09-30, pedido del owner): el usuario ya no escribe el link del repo. Con el token (obligatorio) el backend lista los repos a los que tiene acceso y el usuario elige uno; el backend solo acepta un repo que aparezca en esa lista (evita links arbitrarios o maliciosos). El LLM ya no puede fijar `repo_url`. Al conectar un token se valida contra el proveedor. GitHub: fine-grained token, `GET /user/repos`. Bitbucket: API token de usuario (scope read:repository) con email opcional, `GET /2.0/repositories?role=member`; el "repository access token" no sirve porque no puede listar. El chat queda deshabilitado hasta elegir repo.
- Flujo con repo como añadido (2026-09-30, pedido del owner; reemplaza "chat bloqueado hasta conectar integracion y elegir repo"): el chat arranca sin bloqueo. Despues del objetivo, el agente pregunta si hay repositorio. "No" -> pide la URL a probar (flujo original). "Si" -> nuevo campo `wants_repo`: sin integracion, aviso dentro del chat con boton a Integraciones; con integracion, lista de repos debajo del chat (panel, no modal). Al elegir, el backend guarda en el historial la siguiente pregunta del agente y el flujo sigue normal. El plan no se habilita mientras `wants_repo` sin repo elegido.
