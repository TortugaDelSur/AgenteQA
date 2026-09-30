import json

import app.routers.chat as chat_router
import app.routers.execute as execute_router
import app.routers.plan as plan_router
import app.routers.report as report_router
from app.execution import ExecutionPaused
from app.models.schemas import ContextProgress, TestResult
from tests.conftest import FakeBrowserContext
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

    async def fake_run_test_case(tc, sid, **kwargs):
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

    async def fake_run_test_case(tc, sid, **kwargs):
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

    async def fake_run_test_case(tc, sid, **kwargs):
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

    async def fake_run_test_case(tc, sid, **kwargs):
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    resp = client.post("/api/execute", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert all(line["result"]["status"] == "pass" for line in lines)


# --- pausa y retomar (mismo patron que el barrido) ---

def test_execute_pauses_and_resumes_without_repeating_cases(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)
    calls = []

    async def fake_run_test_case(tc, sid, browser=None, ask=None):
        calls.append(tc.id)
        if tc.id == "TC-02" and calls.count("TC-02") == 1:
            raise ExecutionPaused("unreachable", "no se pudo conectar")
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    lines = _parse_ndjson(client.post("/api/execute", json={"session_id": session_id}).text)
    assert lines[-1] == {"type": "paused", "reason": "unreachable", "detail": "no se pudo conectar"}
    assert lines[0]["result"]["test_case_id"] == "TC-01"

    # pausado: no se puede relanzar sin responder
    assert client.post("/api/execute", json={"session_id": session_id}).status_code == 409
    assert client.post(
        "/api/execute/login", json={"session_id": session_id, "username": "u", "password": "p"},
    ).status_code == 409

    assert client.post(
        "/api/execute/answer", json={"session_id": session_id, "answer": "ya la levante"},
    ).status_code == 200

    lines = _parse_ndjson(client.post("/api/execute", json={"session_id": session_id}).text)
    assert [(line["index"], line["result"]["test_case_id"]) for line in lines] == [(2, "TC-02")]
    assert calls == ["TC-01", "TC-02", "TC-02"]  # TC-01 no se repite

    # termino: el estado se borra y una corrida nueva arranca de cero
    assert client.post("/api/execute/answer", json={"session_id": session_id, "answer": "x"}).status_code == 409


def test_execute_question_is_not_asked_again_for_the_answered_case(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)
    monkeypatch.setattr(execute_router, "check_page_doubt", lambda history, url, elements: "¿que boton?")
    answers = []

    async def fake_run_test_case(tc, sid, browser=None, ask=None):
        if tc.type == "ui":
            question = await ask("https://example.com/login", "<button>")
            answers.append(question)
            if question:
                raise ExecutionPaused("question", question)
        return TestResult(test_case_id=tc.id, status="fail", detail="no esta el boton")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    lines = _parse_ndjson(client.post("/api/execute", json={"session_id": session_id}).text)
    assert lines == [{"type": "paused", "reason": "question", "detail": "¿que boton?"}]

    client.post("/api/execute/answer", json={"session_id": session_id, "answer": "se llama Entrar"})
    lines = _parse_ndjson(client.post("/api/execute", json={"session_id": session_id}).text)

    assert [line["result"]["status"] for line in lines] == ["fail", "fail"]
    assert answers == ["¿que boton?", None]


def test_execute_state_exposes_pending_pause_after_refresh(client, monkeypatch):
    # tras refrescar, la UI no recibe la pausa por WS: sin este endpoint quedaria trabada en 409.
    session_id = _session_with_plan(client, monkeypatch)
    assert client.get(f"/api/execute/state/{session_id}").json() == {"paused": None}

    async def fake_run_test_case(tc, sid, browser=None, ask=None):
        raise ExecutionPaused("unreachable", "no se pudo conectar")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)
    client.post("/api/execute", json={"session_id": session_id})

    assert client.get(f"/api/execute/state/{session_id}").json() == {
        "paused": {"type": "paused", "reason": "unreachable", "detail": "no se pudo conectar"},
    }
    client.post("/api/execute/answer", json={"session_id": session_id, "answer": "ya la levante"})
    assert client.get(f"/api/execute/state/{session_id}").json() == {"paused": None}


def test_execute_login_pause_saves_credentials_and_logs_in_once_on_resume(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)
    logins = []

    async def fake_try_login(page, url, username, password):
        logins.append((url, username, password))
        return True

    class Page:
        async def close(self):
            pass

    async def new_page():
        return Page()

    monkeypatch.setattr(execute_router, "try_login", fake_try_login)
    monkeypatch.setattr(FakeBrowserContext, "new_page", lambda self: new_page(), raising=False)

    async def fake_run_test_case(tc, sid, browser=None, ask=None):
        if not logins:
            raise ExecutionPaused("login", "https://example.com/admin")
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    lines = _parse_ndjson(client.post("/api/execute", json={"session_id": session_id}).text)
    assert lines[-1]["reason"] == "login"
    assert client.post("/api/execute/answer", json={"session_id": session_id, "answer": "x"}).status_code == 409

    assert client.post(
        "/api/execute/login", json={"session_id": session_id, "username": "qa", "password": "pw"},
    ).status_code == 200
    lines = _parse_ndjson(client.post("/api/execute", json={"session_id": session_id}).text)

    assert [line["result"]["status"] for line in lines] == ["pass", "pass"]
    assert logins == [("https://example.com/admin", "qa", "pw")]


def test_execute_pauses_again_when_saved_login_fails(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)

    async def fake_try_login(page, url, username, password):
        return False

    class Page:
        async def close(self):
            pass

    async def new_page():
        return Page()

    monkeypatch.setattr(execute_router, "try_login", fake_try_login)
    monkeypatch.setattr(FakeBrowserContext, "new_page", lambda self: new_page(), raising=False)

    async def fake_run_test_case(tc, sid, browser=None, ask=None):
        raise ExecutionPaused("login", "https://example.com/admin")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)
    client.post("/api/execute", json={"session_id": session_id})
    client.post("/api/execute/login", json={"session_id": session_id, "username": "qa", "password": "mal"})

    lines = _parse_ndjson(client.post("/api/execute", json={"session_id": session_id}).text)

    assert lines == [{"type": "paused", "reason": "login", "detail": "https://example.com/admin"}]


def test_execute_new_plan_discards_paused_state(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)

    async def pause_once(tc, sid, browser=None, ask=None):
        raise ExecutionPaused("unreachable", "caida")

    monkeypatch.setattr(execute_router, "run_test_case", pause_once)
    client.post("/api/execute", json={"session_id": session_id})

    client.post("/api/plan", json={"session_id": session_id})  # plan nuevo

    async def ok(tc, sid, browser=None, ask=None):
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(execute_router, "run_test_case", ok)
    lines = _parse_ndjson(client.post("/api/execute", json={"session_id": session_id}).text)

    assert [line["index"] for line in lines] == [1, 2]


def test_execute_login_404_for_unknown_session(client):
    resp = client.post("/api/execute/login", json={"session_id": "nope", "username": "u", "password": "p"})
    assert resp.status_code == 404


def test_live_ws_receives_pause_and_done_events(client, monkeypatch):
    session_id = _session_with_plan(client, monkeypatch)
    state = {"paused": False}

    async def fake_run_test_case(tc, sid, browser=None, ask=None):
        if not state["paused"]:
            state["paused"] = True
            raise ExecutionPaused("unreachable", "caida")
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(execute_router, "run_test_case", fake_run_test_case)

    with client.websocket_connect(f"/ws/live/{session_id}") as ws:
        client.post("/api/execute", json={"session_id": session_id})
        assert ws.receive_json() == {"type": "paused", "reason": "unreachable", "detail": "caida"}
        client.post("/api/execute/answer", json={"session_id": session_id, "answer": "listo"})
        client.post("/api/execute", json={"session_id": session_id})
        assert ws.receive_json() == {"type": "done"}


def test_live_publish_drops_messages_for_slow_clients():
    import asyncio

    from app import live

    queue = asyncio.Queue(maxsize=1)
    live._subscribers["s-slow"].add(queue)
    try:
        live.publish("s-slow", {"type": "frame", "data": "1"})
        live.publish("s-slow", {"type": "frame", "data": "2"})  # no revienta, se descarta
        assert queue.qsize() == 1
    finally:
        live._subscribers.pop("s-slow")


def test_ws_notices_client_leaving_even_without_messages(client):
    # bug real en la e2e: sin mensajes para la sesion, el WS quedaba colgado en queue.get() y la
    # sesion seguia "mirada" aunque la pagina se cerrara, asi que el repo levantado nunca se apagaba.
    import time

    from app import live

    with client.websocket_connect("/ws/live/s-ws") as ws:
        ws.send_text("lo que mande el cliente se ignora")
        deadline = time.monotonic() + 2
        while not live.is_watched("s-ws") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert live.is_watched("s-ws")
    deadline = time.monotonic() + 2
    while live.is_watched("s-ws") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not live.is_watched("s-ws")
    assert live.last_seen("s-ws") is not None
