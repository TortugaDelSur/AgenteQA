import json

import app.routers.chat as chat_router
import app.routers.plan as plan_router
from app.models.schemas import ContextProgress
from tests.fixtures import SAMPLE_TEST_PLAN
from tests.test_screen_sweeper import SweepFakePage


class FakeSweepBrowser:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page

    async def close(self):
        pass


def _browser_factory(html_by_url=None, created_pages=None, fail_selector=None):
    async def _launch(*args, **kwargs):
        page = SweepFakePage(html_by_url=html_by_url or {}, fail_selector=fail_selector)
        if created_pages is not None:
            created_pages.append(page)
        return None, FakeSweepBrowser(page)

    return _launch


def _new_session(client, monkeypatch, **context_kwargs) -> str:
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("hola", ContextProgress(**context_kwargs)),
    )
    return client.post("/api/chat", json={"message": "hola"}).json()["session_id"]


def _parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.strip().splitlines() if line]


def test_sweep_without_target_url_goes_straight_to_plan(client, monkeypatch):
    session_id = _new_session(client, monkeypatch, objetivo=True, acceso=True)

    def fail_if_called(*a, **kw):
        raise AssertionError("no deberia lanzar un browser sin target_url")

    monkeypatch.setattr(plan_router, "_launch_browser", fail_if_called)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert [line["type"] for line in lines] == ["plan_ready"]
    assert len(lines[0]["plan"]["test_cases"]) == len(SAMPLE_TEST_PLAN.test_cases)


def test_sweep_visits_all_pages_without_doubt(client, monkeypatch):
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True,
        target_url="https://x.com", extra_urls=["https://x.com/dash"],
    )
    html_by_url = {"https://x.com": '<input id="a">', "https://x.com/dash": '<input id="b">'}
    monkeypatch.setattr(plan_router, "_launch_browser", _browser_factory(html_by_url))
    monkeypatch.setattr(plan_router, "check_page_doubt", lambda history, url, elements: None)

    captured = {}

    def fake_generate_plan(history, page_snapshot=None):
        captured["page_snapshot"] = page_snapshot
        return SAMPLE_TEST_PLAN

    monkeypatch.setattr(plan_router, "generate_plan", fake_generate_plan)

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    types = [line["type"] for line in lines]
    assert types == ["visiting", "page_result", "visiting", "page_result", "plan_ready"]
    assert "== https://x.com ==" in captured["page_snapshot"]
    assert "== https://x.com/dash ==" in captured["page_snapshot"]


def test_sweep_pauses_on_doubt_and_persists_state(client, monkeypatch):
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True,
        target_url="https://x.com", extra_urls=["https://x.com/dash"],
    )
    html_by_url = {"https://x.com": '<input id="a">', "https://x.com/dash": '<input id="b">'}
    monkeypatch.setattr(plan_router, "_launch_browser", _browser_factory(html_by_url))
    monkeypatch.setattr(
        plan_router, "check_page_doubt",
        lambda history, url, elements: "¿que pasa si falla?" if url == "https://x.com" else None,
    )
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert lines[-1] == {"type": "question", "url": "https://x.com", "question": "¿que pasa si falla?"}
    assert not any(line["type"] == "plan_ready" for line in lines)

    # el barrido quedo pausado (persistido): un segundo intento sin responder es 409.
    conflict = client.post("/api/plan/sweep", json={"session_id": session_id})
    assert conflict.status_code == 409


def test_sweep_answer_requires_pending_question(client, monkeypatch):
    session_id = _new_session(client, monkeypatch, objetivo=True, acceso=True)

    resp = client.post("/api/plan/sweep/answer", json={"session_id": session_id, "answer": "listo"})

    assert resp.status_code == 409


def test_sweep_start_conflicts_while_question_pending(client, monkeypatch):
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True, target_url="https://x.com",
    )
    monkeypatch.setattr(
        plan_router, "_launch_browser", _browser_factory({"https://x.com": '<input id="a">'}),
    )
    monkeypatch.setattr(plan_router, "check_page_doubt", lambda history, url, elements: "duda")
    client.post("/api/plan/sweep", json={"session_id": session_id})

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    assert resp.status_code == 409


def test_sweep_resumes_after_answer_without_revisiting_page(client, monkeypatch):
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True,
        target_url="https://x.com", extra_urls=["https://x.com/dash"],
    )
    html_by_url = {"https://x.com": '<input id="a">', "https://x.com/dash": '<input id="b">'}
    created_pages = []
    monkeypatch.setattr(
        plan_router, "_launch_browser", _browser_factory(html_by_url, created_pages=created_pages),
    )
    monkeypatch.setattr(
        plan_router, "check_page_doubt",
        lambda history, url, elements: "¿duda?" if url == "https://x.com" else None,
    )
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    client.post("/api/plan/sweep", json={"session_id": session_id})
    answer_resp = client.post(
        "/api/plan/sweep/answer", json={"session_id": session_id, "answer": "reintenta 3 veces"},
    )
    assert answer_resp.status_code == 200

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert lines[-1]["type"] == "plan_ready"
    second_page = created_pages[-1]
    visited_urls = [call[1] for call in second_page.calls if call[0] == "goto"]
    assert visited_urls == ["https://x.com/dash"]

    history = client.get(f"/api/chat/{session_id}").json()["messages"]
    assert any(m["content"] == "reintenta 3 veces" for m in history)


def test_sweep_logs_in_when_credentials_known(client, monkeypatch):
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True,
        target_url="https://x.com/login", username="user", password="pass",
    )
    monkeypatch.setattr(
        plan_router, "_launch_browser",
        _browser_factory({"https://x.com/login": '<input id="dashboard">'}),
    )
    monkeypatch.setattr(plan_router, "check_page_doubt", lambda history, url, elements: None)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert lines[-1]["type"] == "plan_ready"


def test_sweep_reuses_the_real_login_url_across_resumes_after_a_question(client, monkeypatch):
    # bug real: un resume disparado por una pausa de duda (no de login) recalculaba login_url
    # como "la proxima pagina a visitar" en vez de reusar la pagina de login real, e intentaba
    # loguearse contra checkboxes (sin form de login) -> fallaba -> pedia credenciales de nuevo.
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True,
        target_url="https://x.com/login", username="user", password="pass",
        extra_urls=["https://x.com/secure", "https://x.com/checkboxes"],
    )
    html_by_url = {
        "https://x.com/login": '<input id="a">',
        "https://x.com/secure": '<input id="b">',
        "https://x.com/checkboxes": '<input id="c">',
    }
    monkeypatch.setattr(plan_router, "_launch_browser", _browser_factory(html_by_url))

    login_calls = []

    async def fake_try_login(page, login_url, username, password):
        login_calls.append(login_url)
        return True

    monkeypatch.setattr(plan_router, "try_login", fake_try_login)
    monkeypatch.setattr(
        plan_router, "check_page_doubt",
        lambda history, url, elements: "¿duda?" if url == "https://x.com/secure" else None,
    )
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    client.post("/api/plan/sweep", json={"session_id": session_id})  # visita login+secure, pausa por duda
    client.post("/api/plan/sweep/answer", json={"session_id": session_id, "answer": "ok"})

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})  # resume en checkboxes

    lines = _parse_ndjson(resp.text)
    assert lines[-1]["type"] == "plan_ready"
    assert not any(line["type"] == "login_required" for line in lines)
    assert login_calls == ["https://x.com/login", "https://x.com/login"]


def test_sweep_pauses_for_login_when_known_credentials_fail(client, monkeypatch):
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True,
        target_url="https://x.com/login", username="user", password="wrong",
    )
    monkeypatch.setattr(
        plan_router, "_launch_browser",
        _browser_factory({"https://x.com/login": '<input id="dashboard">'}, fail_selector='input[type="password"]'),
    )

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert lines == [{"type": "login_required", "url": "https://x.com/login"}]

    # pausado: un segundo intento directo (sin pasar por /sweep/login) es 409.
    conflict = client.post("/api/plan/sweep", json={"session_id": session_id})
    assert conflict.status_code == 409


def test_sweep_pauses_for_unexpected_login_wall_mid_sweep(client, monkeypatch):
    # target_url no pide login, pero la 2da pagina (extra_url) resulta ser un muro de login
    # que el chat no anticipo (sin username/password en el contexto).
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True,
        target_url="https://x.com", extra_urls=["https://x.com/admin"],
    )
    html_by_url = {
        "https://x.com": '<input id="a">',
        "https://x.com/admin": '<input id="user"><input type="password" id="pass">',
    }
    monkeypatch.setattr(plan_router, "_launch_browser", _browser_factory(html_by_url))
    monkeypatch.setattr(plan_router, "check_page_doubt", lambda history, url, elements: None)

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert lines[-1] == {"type": "login_required", "url": "https://x.com/admin"}
    # la primera pagina si se proceso normalmente antes del muro.
    assert any(line["type"] == "page_result" and line["url"] == "https://x.com" for line in lines)


def test_sweep_login_endpoint_requires_pending_login(client, monkeypatch):
    session_id = _new_session(client, monkeypatch, objetivo=True, acceso=True)

    resp = client.post(
        "/api/plan/sweep/login", json={"session_id": session_id, "username": "u", "password": "p"},
    )

    assert resp.status_code == 409


def test_sweep_resumes_after_login_and_continues_without_revisiting_wall(client, monkeypatch):
    session_id = _new_session(
        client, monkeypatch, objetivo=True, acceso=True,
        target_url="https://x.com", extra_urls=["https://x.com/admin"],
    )
    created_pages = []

    def html_for(success: bool) -> dict:
        return {
            "https://x.com": '<input id="a">',
            "https://x.com/admin": (
                '<input id="dashboard">' if success else
                '<input id="user"><input type="password" id="pass">'
            ),
        }

    # 1ra pasada: /admin es un muro de login (sin credenciales todavia).
    monkeypatch.setattr(
        plan_router, "_launch_browser", _browser_factory(html_for(False), created_pages=created_pages),
    )
    monkeypatch.setattr(plan_router, "check_page_doubt", lambda history, url, elements: None)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    first = client.post("/api/plan/sweep", json={"session_id": session_id})
    assert _parse_ndjson(first.text)[-1] == {"type": "login_required", "url": "https://x.com/admin"}

    login_resp = client.post(
        "/api/plan/sweep/login", json={"session_id": session_id, "username": "user", "password": "pass"},
    )
    assert login_resp.status_code == 200

    # 2da pasada: ahora con credenciales, el login en /admin funciona y muestra contenido real.
    monkeypatch.setattr(
        plan_router, "_launch_browser", _browser_factory(html_for(True), created_pages=created_pages),
    )

    resp = client.post("/api/plan/sweep", json={"session_id": session_id})

    lines = _parse_ndjson(resp.text)
    assert lines[-1]["type"] == "plan_ready"
    # no se revisito https://x.com (ya estaba en visited antes del muro).
    second_page = created_pages[-1]
    visited_urls = [call[1] for call in second_page.calls if call[0] == "goto"]
    assert "https://x.com" not in visited_urls
    assert "https://x.com/admin" in visited_urls
