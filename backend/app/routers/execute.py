import asyncio
import json
from urllib.parse import urlparse

import httpx

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as OrmSession

from app import live
from app.diagnosis import diagnose
from app.execution import ExecutionPaused
from app.execution.runner import run_test_case
from app.llm.client import check_page_doubt
from app.llm.screen_sweeper import try_login
from app.repo import credentials, launch, workspace
from app.runner_client import RunnerError
from app.models.db import ExecutionState, Message, Plan, Result, Session, get_db
from app.models.schemas import (
    ChatMessage,
    ContextProgress,
    PlanRequest,
    SweepAnswerRequest,
    SweepLoginRequest,
    TestCase,
    TestPlan,
    TestResult,
)
from app.routers.plan import _launch_browser, _point_to_app

router = APIRouter()

MAX_EXECUTION_QUESTIONS = 3


def _test_case_urls(tc: TestCase) -> list[str]:
    if tc.type == "endpoint" and tc.request:
        return [tc.request.url]
    if tc.type == "ui" and tc.steps:
        return [step.url for step in tc.steps if step.action == "goto" and step.url]
    return []


def _blocked_domain(tc: TestCase, allowed_host: str) -> str | None:
    """Chequeo duro por si algo elude la restriccion de dominio del prompt del plan.

    Devuelve el host bloqueado, o None si el test case apunta solo al dominio confirmado.
    """
    for url in _test_case_urls(tc):
        host = urlparse(url).netloc
        if host and host != allowed_host:
            return host
    return None


async def _ensure_app(
    session_id: str, plan: TestPlan, plan_id: int, context: ContextProgress, db: OrmSession,
) -> tuple[TestPlan, ContextProgress, str | None]:
    """Si hay repo clonado y no esta levantado (se apago al terminar otra corrida, o por pagina
    cerrada), lo relevanta y muda plan + target_url al puerto nuevo. Devuelve (plan, context, error)."""
    repo = workspace.repo_path(session_id)
    if repo is None or launch.run_id(session_id):
        return plan, context, None
    live.publish(session_id, {"type": "launching"})
    try:
        await launch.start(session_id, str(repo))
    except (RunnerError, httpx.HTTPError) as e:
        detail = e.detail if isinstance(e, RunnerError) else "el runner no responde"
        return plan, context, f"no se pudo levantar el repo: {detail}"
    app_url = launch.chosen_url(session_id)
    if app_url is None:
        launch.stop(session_id)  # sin app elegida no sirve arriba: que el proximo intento relevante
        return plan, context, "el repo publica varias URLs y no se cual es la app: volve a generar el plan"
    old_host = urlparse(context.target_url).netloc if context.target_url else ""
    context = _point_to_app(session_id, context, app_url, db)
    if old_host:
        plan = launch.rebase_plan(plan, app_url, only_host=old_host)
        db.get(Plan, plan_id).plan_json = plan.model_dump_json()
        db.commit()
    return plan, context, None


async def _execute_and_stream(
    session_id: str, plan: TestPlan, plan_id: int, context: ContextProgress,
    history: list[ChatMessage], db: OrmSession,
):
    """NDJSON: una linea por resultado, a medida que cada test case termina.

    Formato de linea: {"index": 1, "total": 3, "result": {...TestResult...}}
    Si el agente no puede seguir solo (login, app caida, duda) la ultima linea es
    {"type": "paused", "reason": ..., "detail": ...} y el proximo POST retoma sin repetir casos.
    Persiste cada resultado en DB apenas llega (no espera al final).
    Con repo levantado: lo relevanta si hace falta, y lo apaga al terminar (no al pausar).
    """
    with launch.hold(session_id):
        async for line in _execute(session_id, plan, plan_id, context, history, db):
            yield line


async def _execute(
    session_id: str, plan: TestPlan, plan_id: int, context: ContextProgress,
    history: list[ChatMessage], db: OrmSession,
):
    state = db.get(ExecutionState, session_id)
    if state is not None and state.plan_id != plan_id:
        db.delete(state)
        db.commit()
        state = None
    if state is None:
        state = ExecutionState(session_id=session_id, plan_id=plan_id)
        db.add(state)
        db.commit()

    def pause(reason: str, detail: str) -> str:
        state.paused_reason = reason
        state.paused_detail = detail
        if reason == "login":
            state.login_url = detail
        if reason == "question":
            state.questions_asked += 1
        db.commit()
        event = {"type": "paused", "reason": reason, "detail": detail}
        live.publish(session_id, event)
        return json.dumps(event, ensure_ascii=False) + "\n"

    plan, context, launch_error = await _ensure_app(session_id, plan, plan_id, context, db)
    if launch_error:
        yield pause("unreachable", launch_error)
        return
    allowed_host = urlparse(context.target_url).netloc if context.target_url else ""

    total = len(plan.test_cases)
    playwright = browser = browser_context = None
    try:
        for index in range(state.next_index, total):
            tc = plan.test_cases[index]
            blocked_host = _blocked_domain(tc, allowed_host)
            if blocked_host:
                result = TestResult(
                    test_case_id=tc.id,
                    status="error",
                    detail=f"bloqueado por seguridad: apunta a '{blocked_host}', distinto al dominio "
                           f"confirmado ('{allowed_host}'). No se ejecuto.",
                )
            else:
                # un solo browser (y un solo context, asi el login sirve para todos los casos) para
                # toda la corrida; se abre recien con el primer caso de UI.
                if tc.type == "ui" and browser_context is None:
                    playwright, browser = await _launch_browser()
                    browser_context = await browser.new_context()
                    if state.login_url and context.username and context.password:
                        page = await browser_context.new_page()
                        logged_in = await try_login(page, state.login_url, context.username, context.password)
                        await page.close()
                        if not logged_in:
                            yield pause("login", state.login_url)
                            return

                async def ask(url: str, elements: str, index=index) -> str | None:
                    if state.questions_asked >= MAX_EXECUTION_QUESTIONS or index == state.answered_index:
                        return None
                    return await asyncio.to_thread(check_page_doubt, history, url, elements)

                try:
                    result = await run_test_case(tc, session_id, browser=browser_context, ask=ask)
                except ExecutionPaused as paused:
                    yield pause(paused.reason, paused.detail)
                    return

            repo = workspace.repo_path(session_id)
            if repo is not None and result.status != "pass" and not blocked_host:
                secrets = credentials.known_secrets(session_id) + [context.password or ""]
                result.suspected_cause = await diagnose(session_id, repo, tc, result, secrets)

            db.add(Result(
                session_id=session_id,
                test_case_id=result.test_case_id,
                status=result.status,
                detail=result.detail,
                evidence=result.evidence,
                suspected_cause_json=result.suspected_cause.model_dump_json() if result.suspected_cause else None,
            ))
            state.next_index = index + 1
            db.commit()
            yield json.dumps(
                {"index": index + 1, "total": total, "result": result.model_dump()}, ensure_ascii=False,
            ) + "\n"
    finally:
        if browser_context is not None:
            await browser_context.close()
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    db.delete(state)
    db.commit()
    # pruebas terminadas y resultados guardados (con su causa probable): el repo ya no hace falta.
    # Si se vuelve a ejecutar, _ensure_app lo relevanta.
    launch.stop(session_id)
    live.publish(session_id, {"type": "done"})


@router.post("/api/execute")
async def post_execute(req: PlanRequest, db: OrmSession = Depends(get_db)) -> StreamingResponse:
    session = db.get(Session, req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    plan_row = (
        db.query(Plan)
        .filter_by(session_id=req.session_id)
        .order_by(Plan.id.desc())
        .first()
    )
    if plan_row is None:
        raise HTTPException(status_code=409, detail="la sesion todavia no tiene un plan generado")

    state = db.get(ExecutionState, req.session_id)
    if state is not None and state.plan_id == plan_row.id and state.paused_reason:
        raise HTTPException(status_code=409, detail="la ejecucion esta pausada esperando al usuario")

    plan = TestPlan.model_validate_json(plan_row.plan_json)
    context = ContextProgress(**json.loads(session.context_json))
    history = [
        ChatMessage(role=m.role, content=m.content)
        for m in db.query(Message).filter_by(session_id=req.session_id).order_by(Message.id)
    ]

    return StreamingResponse(
        _execute_and_stream(req.session_id, plan, plan_row.id, context, history, db),
        media_type="application/x-ndjson",
    )


@router.get("/api/execute/state/{session_id}")
async def get_execute_state(session_id: str, db: OrmSession = Depends(get_db)) -> dict:
    """Pausa pendiente, si la hay. La pausa llega en vivo por WS/NDJSON; esto es para despues de
    refrescar la pagina, si no la UI no la mostraria y POST /api/execute quedaria en 409 para siempre."""
    state = db.get(ExecutionState, session_id)
    if state is None or not state.paused_reason:
        return {"paused": None}
    return {"paused": {"type": "paused", "reason": state.paused_reason, "detail": state.paused_detail}}


@router.post("/api/execute/answer")
async def post_execute_answer(req: SweepAnswerRequest, db: OrmSession = Depends(get_db)) -> dict:
    state = db.get(ExecutionState, req.session_id)
    if state is None or state.paused_reason not in ("question", "unreachable"):
        raise HTTPException(status_code=409, detail="no hay una pregunta pendiente para esta sesion")

    db.add(Message(session_id=req.session_id, role="user", content=req.answer))
    if state.paused_reason == "question":
        state.answered_index = state.next_index
    state.paused_reason = None
    state.paused_detail = None
    db.commit()

    return {"status": "ok"}


@router.post("/api/execute/login")
async def post_execute_login(req: SweepLoginRequest, db: OrmSession = Depends(get_db)) -> dict:
    session = db.get(Session, req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    state = db.get(ExecutionState, req.session_id)
    if state is None or state.paused_reason != "login":
        raise HTTPException(status_code=409, detail="no hay un login pendiente para esta sesion")

    # igual que el barrido: se guardan para toda la sesion; el reintento real es en el proximo POST.
    context = ContextProgress(**json.loads(session.context_json))
    context.username = req.username
    context.password = req.password
    session.context_json = context.model_dump_json()
    state.paused_reason = None
    state.paused_detail = None
    db.commit()

    return {"status": "ok"}
