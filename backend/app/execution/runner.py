from collections.abc import AsyncIterator

from app.execution.endpoint_runner import run_endpoint
from app.execution.ui_runner import run_ui
from app.models.schemas import TestCase, TestPlan, TestResult


async def run_test_case(tc: TestCase, session_id: str) -> TestResult:
    try:
        if tc.type == "endpoint":
            return await run_endpoint(tc)
        if tc.type == "ui":
            return await run_ui(tc, session_id)
        return TestResult(
            test_case_id=tc.id, status="error", detail=f"tipo de test desconocido: {tc.type!r}"
        )
    except Exception as exc:  # un test que revienta no debe tumbar el resto del plan
        return TestResult(
            test_case_id=tc.id, status="error", detail=f"error inesperado ejecutando el test: {exc!r}"
        )


async def run_plan_stream(session_id: str, plan: TestPlan) -> AsyncIterator[TestResult]:
    """Ejecuta cada test case en serie, entregando cada resultado a medida que termina.

    Permite a quien llama (ej. el router) transmitir progreso en vivo en vez de esperar
    a que termine todo el plan.
    """
    for tc in plan.test_cases:
        yield await run_test_case(tc, session_id)


async def run_plan(session_id: str, plan: TestPlan) -> list[TestResult]:
    """Ejecuta cada test case en serie (los tests UI abren un browser y compiten por recursos)."""
    return [result async for result in run_plan_stream(session_id, plan)]
