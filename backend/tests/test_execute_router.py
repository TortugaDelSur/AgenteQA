import json

import app.routers.chat as chat_router
import app.routers.execute as execute_router
import app.routers.plan as plan_router
import app.routers.report as report_router
from app.models.schemas import ContextProgress, TestResult
from tests.fixtures import SAMPLE_TEST_PLAN


def _session(client, monkeypatch) -> str:
    # target_url coincide con el dominio de SAMPLE_TEST_PLAN (example.com) para que los tests
    # "felices" no choquen con el chequeo de dominio agregado en execute.py.
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


def _parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.strip().splitlines() if line]


def test_execute_404_for_unknown_session(client):
    resp = client.post("/api/execute", json={"session_id": "no-existe"})
    assert resp.status_code == 404


def test_execute_409_when_session_has_no_plan(client, monkeypatch):
    session_id = _session(client, monkeypatch)

    resp = client.post("/api/execute", json={"session_id": session_id})

    assert resp.status_code == 409
    assert "plan" in resp.json()["detail"]


def test_execute_streams_progress_and_persists_results(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)
    captured = []

    async def fake_run_test_case(tc, sid):
        captured.append((tc.id, sid))
        if tc.id == "TC-01":
            return TestResult(test_case_id="TC-01", status="pass", detail="ok")
        return TestResult(test_case_id="TC-02", status="fail", detail="status 500", evidence="HTTP 500")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    resp = client.post("/api/execute", json={"session_id": session_id})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = _parse_ndjson(resp.text)

    assert [line["result"]["status"] for line in lines] == ["pass", "fail"]
    assert [line["index"] for line in lines] == [1, 2]
    assert all(line["total"] == 2 for line in lines)
    assert [c[0] for c in captured] == ["TC-01", "TC-02"]
    assert all(c[1] == session_id for c in captured)

    # los resultados quedaron persistidos: el reporte ya no responde 409 "no ejecutado"
    monkeypatch.setattr(report_router, "generate_report", lambda plan, results: "# Reporte de QA\n")
    report_resp = client.get(f"/api/report/{session_id}")
    assert report_resp.status_code == 200


def test_execute_uses_most_recent_plan(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)
    # se genera un segundo plan para la misma sesion
    client.post("/api/plan", json={"session_id": session_id})

    seen_ids = []

    async def fake_run_test_case(tc, sid):
        seen_ids.append(tc.id)
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    resp = client.post("/api/execute", json={"session_id": session_id})

    assert resp.status_code == 200
    assert seen_ids == [tc.id for tc in SAMPLE_TEST_PLAN.test_cases]


def test_execute_blocks_test_case_pointing_to_different_domain(client, monkeypatch):
    # chequeo duro: aunque el prompt del plan deberia restringir el dominio, si algo lo elude
    # (bug del LLM, injection), execute.py no debe ejecutar la request/navegacion real igual.
    session_id = _session(client, monkeypatch)
    rogue_plan = SAMPLE_TEST_PLAN.__class__(test_cases=[{
        "id": "TC-ROGUE",
        "type": "endpoint",
        "title": "intento de pegarle a otro dominio",
        "request": {"method": "GET", "url": "https://attacker.example/steal", "headers": {}, "body": None},
        "expected_status": 200,
    }])
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: rogue_plan)
    client.post("/api/plan", json={"session_id": session_id})

    called = {"count": 0}

    async def fake_run_test_case(tc, sid):
        called["count"] += 1
        return TestResult(test_case_id=tc.id, status="pass", detail="no deberia llegar aca")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    resp = client.post("/api/execute", json={"session_id": session_id})

    assert resp.status_code == 200
    lines = _parse_ndjson(resp.text)
    assert lines[0]["result"]["status"] == "error"
    assert "attacker.example" in lines[0]["result"]["detail"]
    assert called["count"] == 0  # nunca se ejecuto la request real


def test_execute_allows_test_case_matching_confirmed_domain(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)

    async def fake_run_test_case(tc, sid):
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    resp = client.post("/api/execute", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert all(line["result"]["status"] == "pass" for line in lines)
