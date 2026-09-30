import json

import httpx

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session as OrmSession

from app.llm.authenticated_inspector import inspect_with_login
from app.llm.client import check_page_doubt, generate_plan
from app.llm.page_inspector import format_snapshots, inspect_multiple, inspect_page
from app.llm.screen_sweeper import capture_page, try_login
from app.models.db import Message, Plan, Session, SweepState, get_db
from app.repo import launch, workspace
from app.runner_client import RunnerError
from app.models.schemas import (
    ChatMessage,
    ContextProgress,
    PlanRequest,
    SweepAnswerRequest,
    SweepLoginRequest,
    TestPlan,
)

router = APIRouter()

MAX_SWEEP_QUESTIONS = 3
# marca en SweepState.pending_question_url: la pregunta es "cual de las URLs del repo es la app",
# no una duda sobre una pantalla.
REPO_CHOICE = "repo:elegir-app"


async def _build_page_snapshot(context: ContextProgress) -> str | None:
    if not context.target_url:
        return None

    if context.username and context.password:
        snapshots = await inspect_with_login(
            context.target_url, context.username, context.password, context.extra_urls,
        )
        if snapshots:
            return format_snapshots(snapshots)
        # login fallo (selectores no encontrados, timeout, etc): cae al estatico de la principal.
        return inspect_page(context.target_url)

    # sin login: inspecciona la pagina principal + cualquier otra pestaña/pagina mencionada.
    snapshots = inspect_multiple([context.target_url, *context.extra_urls])
    return format_snapshots(snapshots) if snapshots else None


@router.post("/api/plan", response_model=TestPlan)
async def post_plan(req: PlanRequest, db: OrmSession = Depends(get_db)) -> TestPlan:
    session = db.get(Session, req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    history = [
        ChatMessage(role=m.role, content=m.content)
        for m in db.query(Message).filter_by(session_id=req.session_id).order_by(Message.id)
    ]

    context = ContextProgress(**json.loads(session.context_json))
    page_snapshot = await _build_page_snapshot(context)

    try:
        plan = generate_plan(history, page_snapshot=page_snapshot)
    except (ValidationError, ValueError, TypeError) as e:
        raise HTTPException(status_code=502, detail=f"LLM no genero un plan valido: {e}")

    db.add(Plan(session_id=req.session_id, plan_json=plan.model_dump_json()))
    db.commit()

    return plan


async def _launch_browser():
    from playwright.async_api import async_playwright  # pragma: no cover - requiere el browser real

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    return playwright, browser


def _summarize(elements: str | None) -> str:
    if not elements:
        return "no se encontraron elementos interactivos"
    n = len(elements.splitlines())
    return f"{n} elemento(s) encontrados"


def _looks_like_login(elements: str) -> bool:
    return 'type="password"' in elements


def _point_to_app(session_id: str, context: ContextProgress, app_url: str, db: OrmSession) -> ContextProgress:
    """La app local del repo pasa a ser `target_url`; las paginas extra se mudan a ese host (mismo path).
    Todo lo demas (barrido, bloqueo de dominio, ejecucion) sigue igual, contra la app local."""
    data = context.model_dump()
    data["target_url"] = app_url
    data["extra_urls"] = launch.rebase_urls(context.extra_urls, app_url)
    context = ContextProgress(**data)
    db.get(Session, session_id).context_json = context.model_dump_json()
    db.commit()
    return context


async def _run_sweep(session_id: str, context: ContextProgress, history: list[ChatMessage], db: OrmSession):
    """Barrido de pantallas con pausa dura por duda o por login, sobre `target_url` + `extra_urls`.

    Si la sesion tiene un repo clonado, antes lo levanta con el runner y prueba contra la app local.

    NDJSON: una linea por evento ("launching", "visiting", "page_result", "error", "question",
    "login_required", "plan_ready"). "question"/"login_required"/"plan_ready" son siempre la ultima
    linea del stream (cortan el generador).
    """
    repo = workspace.repo_path(session_id)
    if repo is not None and launch.chosen_url(session_id) is None:
        if not launch.urls(session_id):
            yield {"type": "launching", "detail": "Levantando el repo localmente (build + arranque, puede tardar unos minutos)..."}
            try:
                await launch.start(session_id, str(repo))
            except (RunnerError, httpx.HTTPError) as e:
                detail = e.detail if isinstance(e, RunnerError) else "el runner no responde (esta levantado?)"
                yield {"type": "error", "url": context.repo_url or "repo", "detail": f"no se pudo levantar el repo: {detail}"}
        if len(launch.urls(session_id)) > 1:
            state = db.get(SweepState, session_id) or SweepState(session_id=session_id, pages_json="[]")
            state.pending_question = (
                "El repo publica varias URLs web: " + ", ".join(launch.urls(session_id))
                + ". ¿Cual es la app a probar? (responde con la URL o el puerto)"
            )
            state.pending_question_url = REPO_CHOICE
            db.add(state)
            db.commit()
            yield {"type": "question", "url": REPO_CHOICE, "question": state.pending_question}
            return
    app_url = launch.chosen_url(session_id)
    if app_url and context.target_url != app_url:
        context = _point_to_app(session_id, context, app_url, db)

    if not context.target_url:
        plan = generate_plan(history, page_snapshot=None)
        db.add(Plan(session_id=session_id, plan_json=plan.model_dump_json()))
        db.commit()
        yield {"type": "plan_ready", "plan": plan.model_dump()}
        return

    state = db.get(SweepState, session_id)
    if state is None:
        pages = [context.target_url, *context.extra_urls]
        state = SweepState(session_id=session_id, pages_json=json.dumps(pages))
        db.add(state)
        db.commit()

    pages = json.loads(state.pages_json)
    visited: dict[str, str] = json.loads(state.visited_json)

    playwright, browser = await _launch_browser()
    page = await browser.new_page()
    authenticated = False
    try:
        if context.username and context.password:
            # login_url persistido: la pagina real de login, fijada la primera vez y reusada en
            # cada resume. Nunca se deriva de next_index (que avanza a paginas que no son la de
            # login) — cada resume relanza un browser nuevo sin cookies, asi que hay que
            # reautenticarse siempre, pero contra la pagina correcta.
            login_url = state.login_url or pages[min(state.next_index, len(pages) - 1)]
            authenticated = await try_login(page, login_url, context.username, context.password)
            if not authenticated:
                state.login_required = True
                state.login_url = login_url
                db.commit()
                yield {"type": "login_required", "url": login_url}
                return
            state.login_required = False
            state.login_url = login_url
            db.commit()

        for index in range(state.next_index, len(pages)):
            url = pages[index]
            yield {"type": "visiting", "url": url, "index": index + 1, "total": len(pages)}

            try:
                elements, screenshot_b64 = await capture_page(page, url)
            except Exception as e:
                yield {"type": "error", "url": url, "detail": str(e)}
                state.next_index = index + 1
                db.commit()
                continue

            if not authenticated and elements and _looks_like_login(elements):
                state.login_required = True
                state.login_url = url
                db.commit()
                yield {"type": "login_required", "url": url}
                return

            if elements:
                visited[url] = elements
            yield {
                "type": "page_result", "url": url, "index": index + 1, "total": len(pages),
                "screenshot_b64": screenshot_b64, "summary": _summarize(elements),
            }

            question = None
            if elements and state.questions_asked < MAX_SWEEP_QUESTIONS:
                question = check_page_doubt(history, url, elements)

            state.visited_json = json.dumps(visited)
            state.next_index = index + 1
            if question:
                state.pending_question = question
                state.pending_question_url = url
                state.questions_asked += 1
                db.commit()
                yield {"type": "question", "url": url, "question": question}
                return
            db.commit()
    finally:
        await page.close()
        await browser.close()
        if playwright is not None:
            await playwright.stop()

    page_snapshot = format_snapshots(visited) if visited else None
    plan = generate_plan(history, page_snapshot=page_snapshot)
    db.add(Plan(session_id=session_id, plan_json=plan.model_dump_json()))
    db.delete(state)
    db.commit()
    yield {"type": "plan_ready", "plan": plan.model_dump()}


@router.post("/api/plan/sweep")
async def post_plan_sweep(req: PlanRequest, db: OrmSession = Depends(get_db)) -> StreamingResponse:
    session = db.get(Session, req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    state = db.get(SweepState, req.session_id)
    if state is not None and state.pending_question:
        raise HTTPException(status_code=409, detail="hay una pregunta pendiente sin responder")
    if state is not None and state.login_required:
        raise HTTPException(status_code=409, detail="hace falta iniciar sesion antes de continuar")

    context = ContextProgress(**json.loads(session.context_json))
    history = [
        ChatMessage(role=m.role, content=m.content)
        for m in db.query(Message).filter_by(session_id=req.session_id).order_by(Message.id)
    ]

    async def gen():
        # mientras barre, el repo levantado no se apaga por inactividad (ver repo/launch.py).
        with launch.hold(req.session_id):
            async for event in _run_sweep(req.session_id, context, history, db):
                yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.post("/api/plan/sweep/answer")
async def post_plan_sweep_answer(req: SweepAnswerRequest, db: OrmSession = Depends(get_db)) -> dict:
    state = db.get(SweepState, req.session_id)
    if state is None or not state.pending_question:
        raise HTTPException(status_code=409, detail="no hay una pregunta pendiente para esta sesion")

    if state.pending_question_url == REPO_CHOICE:
        if launch.choose(req.session_id, req.answer) is None:
            raise HTTPException(
                status_code=422, detail="responde con una de las URLs (o su puerto): " + ", ".join(launch.urls(req.session_id)),
            )
        # el barrido arranca de cero contra la app elegida (las paginas se arman con esa URL).
        db.delete(state)
        db.commit()
        return {"status": "ok"}

    db.add(Message(session_id=req.session_id, role="user", content=req.answer))
    state.pending_question = None
    state.pending_question_url = None
    db.commit()

    return {"status": "ok"}


@router.post("/api/plan/sweep/login")
async def post_plan_sweep_login(req: SweepLoginRequest, db: OrmSession = Depends(get_db)) -> dict:
    session = db.get(Session, req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    state = db.get(SweepState, req.session_id)
    if state is None or not state.login_required:
        raise HTTPException(status_code=409, detail="no hay un login pendiente para esta sesion")

    # se guardan para toda la sesion: otras paginas del barrido (o el plan final) pueden
    # necesitar el mismo login. El reintento real ocurre en el proximo POST /api/plan/sweep.
    context = ContextProgress(**json.loads(session.context_json))
    context.username = req.username
    context.password = req.password
    session.context_json = context.model_dump_json()
    state.login_required = False
    db.commit()

    return {"status": "ok"}
