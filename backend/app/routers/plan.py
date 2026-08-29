from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session as OrmSession

from app.llm.client import generate_plan
from app.models.db import Message, Plan, Session, get_db
from app.models.schemas import ChatMessage, PlanRequest, TestPlan

router = APIRouter()


@router.post("/api/plan", response_model=TestPlan)
def post_plan(req: PlanRequest, db: OrmSession = Depends(get_db)) -> TestPlan:
    session = db.get(Session, req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    history = [
        ChatMessage(role=m.role, content=m.content)
        for m in db.query(Message).filter_by(session_id=req.session_id).order_by(Message.id)
    ]

    try:
        plan = generate_plan(history)
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"LLM no genero un plan valido: {e}")

    db.add(Plan(session_id=req.session_id, plan_json=plan.model_dump_json()))
    db.commit()

    return plan
