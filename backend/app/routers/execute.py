from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from app.execution.runner import run_plan
from app.models.db import Plan, Result, Session, get_db
from app.models.schemas import ExecutionResponse, PlanRequest, TestPlan

router = APIRouter()


@router.post("/api/execute", response_model=ExecutionResponse)
async def post_execute(req: PlanRequest, db: OrmSession = Depends(get_db)) -> ExecutionResponse:
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
    results = await run_plan(req.session_id, plan)

    for r in results:
        db.add(
            Result(
                session_id=req.session_id,
                test_case_id=r.test_case_id,
                status=r.status,
                detail=r.detail,
                evidence=r.evidence,
            )
        )
    db.commit()

    return ExecutionResponse(session_id=req.session_id, results=results)
