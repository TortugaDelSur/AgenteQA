import app.routers.chat as chat_router
import app.routers.execute as execute_router
import app.routers.plan as plan_router
import app.routers.report as report_router
from openai import OpenAIError

from app.models.schemas import ContextProgress, TestResult
from tests.fixtures import SAMPLE_TEST_PLAN


def _session(client, monkeypatch) -> str:
    # target_url coincide con el dominio de SAMPLE_TEST_PLAN (example.com) para que el chequeo
    # de dominio de execute.py no bloquee estos tests.
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("hola", ContextProgress(target_url="https://example.com")),
    )
    return client.post("/api/chat", json={"message": "hola"}).json()["session_id"]


def _session_with_plan(client, monkeypatch) -> str:
    session_id = _session(client, monkeypatch)
    monkeypatch.setattr(
        plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN
    )
    client.post("/api/plan", json={"session_id": session_id})
    return session_id


def _executed_session(client, monkeypatch) -> str:
    session_id = _session_with_plan(client, monkeypatch)

    async def fake_run_test_case(tc, sid):
        if tc.id == "TC-01":
            return TestResult(test_case_id="TC-01", status="fail", detail="boom", evidence="TC-01.png")
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)
    client.post("/api/execute", json={"session_id": session_id})
    return session_id


def test_report_404_for_unknown_session(client):
    resp = client.get("/api/report/no-existe")
    assert resp.status_code == 404


def test_report_409_when_no_plan(client, monkeypatch):
    session_id = _session(client, monkeypatch)

    resp = client.get(f"/api/report/{session_id}")

    assert resp.status_code == 409
    assert "plan" in resp.json()["detail"]


def test_report_409_when_plan_not_executed_yet(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)

    resp = client.get(f"/api/report/{session_id}")

    assert resp.status_code == 409
    assert "ejecut" in resp.json()["detail"]


def test_report_returns_markdown_attachment(client, monkeypatch):
    session_id = _executed_session(client, monkeypatch)
    captured = {}

    def fake_generate_report(plan, results):
        captured["n_cases"] = len(plan.test_cases)
        captured["n_results"] = len(results)
        captured["result_status"] = results[0].status
        return "# Reporte de QA\n\nUn caso fallo.\n"

    monkeypatch.setattr(report_router, "generate_report", fake_generate_report)

    resp = client.get(f"/api/report/{session_id}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert "reporte.md" in resp.headers["content-disposition"]
    assert resp.text.startswith("# Reporte de QA")
    assert captured["n_cases"] == len(SAMPLE_TEST_PLAN.test_cases)
    assert captured["n_results"] == len(SAMPLE_TEST_PLAN.test_cases)
    assert captured["result_status"] == "fail"


def test_report_502_when_llm_fails(client, monkeypatch):
    session_id = _executed_session(client, monkeypatch)

    def boom(plan, results):
        raise OpenAIError("modelo caido")

    monkeypatch.setattr(report_router, "generate_report", boom)

    resp = client.get(f"/api/report/{session_id}")

    assert resp.status_code == 502
    assert "reporte" in resp.json()["detail"]
