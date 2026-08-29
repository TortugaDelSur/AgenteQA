import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError
from sqlalchemy.orm import Session as OrmSession

from app.llm.client import chat as llm_chat
from app.models.db import Message, Session, get_db
from app.models.schemas import ChatHistoryResponse, ChatMessage, ChatRequest, ChatResponse, ContextProgress

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
def post_chat(req: ChatRequest, db: OrmSession = Depends(get_db)) -> ChatResponse:
    session = db.get(Session, req.session_id) if req.session_id else None
    if session is None:
        session = Session(id=str(uuid.uuid4()), context_json=ContextProgress().model_dump_json())
        db.add(session)
        db.flush()

    db.add(Message(session_id=session.id, role="user", content=req.message))
    db.flush()

    history = [
        ChatMessage(role=m.role, content=m.content)
        for m in db.query(Message).filter_by(session_id=session.id).order_by(Message.id)
    ]

    try:
        reply, context = llm_chat(history)
    except (OpenAIError, KeyError, ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=502, detail=f"El LLM no respondio correctamente: {e}")

    session.context_json = context.model_dump_json()
    db.add(Message(session_id=session.id, role="assistant", content=reply))
    db.commit()

    return ChatResponse(
        session_id=session.id,
        reply=reply,
        context=context,
        ready_for_plan=context.ready_for_plan,
    )


@router.get("/api/chat/{session_id}", response_model=ChatHistoryResponse)
def get_chat_history(session_id: str, db: OrmSession = Depends(get_db)) -> ChatHistoryResponse:
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    messages = [
        ChatMessage(role=m.role, content=m.content)
        for m in db.query(Message).filter_by(session_id=session_id).order_by(Message.id)
    ]
    context = ContextProgress(**json.loads(session.context_json))

    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
        context=context,
        ready_for_plan=context.ready_for_plan,
    )
