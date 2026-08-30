import app.routers.chat as chat_router
import app.routers.execute as execute_router
import app.routers.plan as plan_router
import app.routers.report as report_router
from app.models.schemas import ContextProgress, TestResult
from tests.fixtures import SAMPLE_TEST_PLAN


def _session(client, monkeypatch) -> str:
    monkeypatch.setattr(
        chat_router, "llm_chat", lambda history, page_snapshot=None: ("hola", ContextProgress())
    )
    return client.post("/api/chat", json={"message": "hola"}).json()["session_id"]


def _session_with_plan(client, monkeypatch) -> str:
    session_id = _session(client, monkeypatch)
    monkeypatch.setattr(
        plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN
    )
    client.post("/api/plan", json={"session_id": session_id})
    return session_id


def test_execute_404_for_unknown_session(client):
    resp = client.post("/api/execute", json={"session_id": "no-existe"})
    assert resp.status_code == 404


def test_execute_409_when_session_has_no_plan(client, monkeypatch):
    session_id = _session(client, monkeypatch)

    resp = client.post("/api/execute", json={"session_id": session_id})

    assert resp.status_code == 409
    assert "plan" in resp.json()["detail"]


def test_execute_runs_plan_persists_results_and_returns_them(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)
    captured = {}

    async def fake_run_plan(sid, plan):
        captured["sid"] = sid
        captured["n_cases"] = len(plan.test_cases)
        return [
            TestResult(test_case_id="TC-01", status="pass", detail="ok"),
            TestResult(test_case_id="TC-02", status="fail", detail="status 500", evidence="HTTP 500"),
        ]

    monkeypatch.setattr(execute_router, "run_plan", fake_run_plan)

    resp = client.post("/api/execute", json={"session_id": session_id})

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert [r["status"] for r in data["results"]] == ["pass", "fail"]
    assert captured["sid"] == session_id
    assert captured["n_cases"] == len(SAMPLE_TEST_PLAN.test_cases)

    # los resultados quedaron persistidos: el reporte ya no responde 409 "no ejecutado"
    monkeypatch.setattr(report_router, "generate_report", lambda plan, results: "# Reporte de QA\n")
    report_resp = client.get(f"/api/report/{session_id}")
    assert report_resp.status_code == 200


def test_execute_uses_most_recent_plan(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)
    # se genera un segundo plan para la misma sesion
    client.post("/api/plan", json={"session_id": session_id})

    seen_ids = {}

    async def fake_run_plan(sid, plan):
        seen_ids["ids"] = [tc.id for tc in plan.test_cases]
        return []

    monkeypatch.setattr(execute_router, "run_plan", fake_run_plan)

    resp = client.post("/api/execute", json={"session_id": session_id})

    assert resp.status_code == 200
    assert seen_ids["ids"] == [tc.id for tc in SAMPLE_TEST_PLAN.test_cases]
