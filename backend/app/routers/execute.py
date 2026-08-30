import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as OrmSession

from app.execution.runner import run_plan_stream
from app.models.db import Plan, Result, Session, get_db
from app.models.schemas import PlanRequest, TestPlan

router = APIRouter()


async def _execute_and_stream(session_id: str, plan: TestPlan, db: OrmSession):
    """NDJSON: una linea por resultado, a medida que cada test case termina.

    Formato de linea: {"index": 1, "total": 3, "result": {...TestResult...}}
    Persiste cada resultado en DB apenas llega, igual que antes (no espera al final).
    """
    total = len(plan.test_cases)
    index = 0
    async for result in run_plan_stream(session_id, plan):
        index += 1
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

    return StreamingResponse(
        _execute_and_stream(req.session_id, plan, db), media_type="application/x-ndjson",
    )
