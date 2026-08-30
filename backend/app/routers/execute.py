import json
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as OrmSession

from app.execution.runner import run_test_case
from app.models.db import Plan, Result, Session, get_db
from app.models.schemas import ContextProgress, PlanRequest, TestCase, TestPlan, TestResult

router = APIRouter()


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


async def _execute_and_stream(session_id: str, plan: TestPlan, allowed_host: str, db: OrmSession):
    """NDJSON: una linea por resultado, a medida que cada test case termina.

    Formato de linea: {"index": 1, "total": 3, "result": {...TestResult...}}
    Persiste cada resultado en DB apenas llega, igual que antes (no espera al final).
    """
    total = len(plan.test_cases)
    for index, tc in enumerate(plan.test_cases, start=1):
        blocked_host = _blocked_domain(tc, allowed_host)
        if blocked_host:
            result = TestResult(
                test_case_id=tc.id,
                status="error",
                detail=f"bloqueado por seguridad: apunta a '{blocked_host}', distinto al dominio "
                       f"confirmado ('{allowed_host}'). No se ejecuto.",
            )
        else:
            result = await run_test_case(tc, session_id)

        db.add(Result(
            session_id=session_id,
            test_case_id=result.test_case_id,
            status=result.status,
            detail=result.detail,
            evidence=result.evidence,
        ))
        db.commit()
        yield json.dumps(
            {"index": index, "total": total, "result": result.model_dump()}, ensure_ascii=False,
        ) + "\n"


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

    plan = TestPlan.model_validate_json(plan_row.plan_json)
    context = ContextProgress(**json.loads(session.context_json))
    allowed_host = urlparse(context.target_url).netloc if context.target_url else ""

    return StreamingResponse(
        _execute_and_stream(req.session_id, plan, allowed_host, db), media_type="application/x-ndjson",
    )
