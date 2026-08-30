import json
from typing import Literal

import markdown as markdown_lib
from fastapi import APIRouter, Depends, HTTPException, Response
from openai import OpenAIError
from sqlalchemy.orm import Session as OrmSession

from app.llm.client import generate_report
from app.models.db import Plan, Result, Session, get_db
from app.models.schemas import TestPlan, TestResult

router = APIRouter()


def _render_html(markdown_report: str) -> str:
    body = markdown_lib.markdown(markdown_report, extensions=["tables"])
    return (
        "<!DOCTYPE html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<title>Reporte de QA</title></head><body>" + body + "</body></html>"
    )


@router.get("/api/report/{session_id}")
def get_report(
    session_id: str, format: Literal["md", "html"] = "md", db: OrmSession = Depends(get_db),
) -> Response:
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    plan_row = (
        db.query(Plan).filter_by(session_id=session_id).order_by(Plan.id.desc()).first()
    )
    if plan_row is None:
        raise HTTPException(status_code=409, detail="la sesion todavia no tiene un plan generado")

    result_rows = db.query(Result).filter_by(session_id=session_id).order_by(Result.id).all()
    if not result_rows:
        raise HTTPException(status_code=409, detail="la sesion todavia no fue ejecutada")

    plan = TestPlan.model_validate_json(plan_row.plan_json)
    results = [
        TestResult(
            test_case_id=r.test_case_id, status=r.status, detail=r.detail, evidence=r.evidence
        )
        for r in result_rows
    ]

    try:
        markdown_report = generate_report(plan, results)
    except (OpenAIError, KeyError, ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=502, detail=f"el LLM no genero el reporte: {e}")

    if format == "html":
        return Response(
            content=_render_html(markdown_report),
            media_type="text/html",
            headers={"Content-Disposition": 'attachment; filename="reporte.html"'},
        )

    return Response(
        content=markdown_report,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="reporte.md"'},
    )
