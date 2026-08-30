import app.routers.chat as chat_router
import app.routers.plan as plan_router
from app.models.schemas import ContextProgress
from tests.fixtures import SAMPLE_TEST_PLAN


def _new_session(client, monkeypatch) -> str:
    monkeypatch.setattr(chat_router, "llm_chat", lambda history, page_snapshot=None: ("hola", ContextProgress()))
    return client.post("/api/chat", json={"message": "hola"}).json()["session_id"]


def test_post_plan_404_for_unknown_session(client):
    resp = client.post("/api/plan", json={"session_id": "no-existe"})
    assert resp.status_code == 404


def test_post_plan_success(client, monkeypatch):
    session_id = _new_session(client, monkeypatch)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    resp = client.post("/api/plan", json={"session_id": session_id})

    assert resp.status_code == 200
    assert len(resp.json()["test_cases"]) == len(SAMPLE_TEST_PLAN.test_cases)


def test_post_plan_502_when_llm_output_invalid(client, monkeypatch):
    session_id = _new_session(client, monkeypatch)

    def raise_value_error(history, page_snapshot=None):
        raise ValueError("json invalido")

    monkeypatch.setattr(plan_router, "generate_plan", raise_value_error)

    resp = client.post("/api/plan", json={"session_id": session_id})

    assert resp.status_code == 502


def test_post_plan_inspects_page_when_target_url_known(client, monkeypatch):
    session_id = _new_session(client, monkeypatch)

    monkeypatch.setattr(plan_router, "inspect_page", lambda url: "<input id=\"x\">")
    captured = {}

    def fake_generate_plan(history, page_snapshot=None):
        captured["page_snapshot"] = page_snapshot
        return SAMPLE_TEST_PLAN

    monkeypatch.setattr(plan_router, "generate_plan", fake_generate_plan)

    # setea target_url directo en la sesion via un segundo turno de chat
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("ok", ContextProgress(objetivo=True, acceso=True, target_url="https://x.com")),
    )
    client.post("/api/chat", json={"session_id": session_id, "message": "url https://x.com"})

    resp = client.post("/api/plan", json={"session_id": session_id})

    assert resp.status_code == 200
    assert captured["page_snapshot"] == "<input id=\"x\">"


def test_post_plan_uses_authenticated_inspection_when_credentials_known(client, monkeypatch):
    session_id = _new_session(client, monkeypatch)

    async def fake_inspect_with_login(login_url, username, password, extra_urls, browser=None):
        assert (login_url, username, password, extra_urls) == ("https://x.com", "user", "pass", ["https://x.com/dash"])
        return {"https://x.com": "<input id=\"real\">"}

    monkeypatch.setattr(plan_router, "inspect_with_login", fake_inspect_with_login)
    monkeypatch.setattr(plan_router, "inspect_page", lambda url: "no deberia usarse")

    captured = {}

    def fake_generate_plan(history, page_snapshot=None):
        captured["page_snapshot"] = page_snapshot
        return SAMPLE_TEST_PLAN

    monkeypatch.setattr(plan_router, "generate_plan", fake_generate_plan)

    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("ok", ContextProgress(
            objetivo=True, acceso=True, target_url="https://x.com",
            username="user", password="pass", extra_urls=["https://x.com/dash"],
        )),
    )
    client.post("/api/chat", json={"session_id": session_id, "message": "login user/pass"})

    resp = client.post("/api/plan", json={"session_id": session_id})

    assert resp.status_code == 200
    assert "== https://x.com ==" in captured["page_snapshot"]
    assert 'id="real"' in captured["page_snapshot"]


def test_post_plan_falls_back_to_static_when_login_fails(client, monkeypatch):
    session_id = _new_session(client, monkeypatch)

    async def failing_login(*args, **kwargs):
        return None

    monkeypatch.setattr(plan_router, "inspect_with_login", failing_login)
    monkeypatch.setattr(plan_router, "inspect_page", lambda url: "<input id=\"fallback\">")

    captured = {}

    def fake_generate_plan(history, page_snapshot=None):
        captured["page_snapshot"] = page_snapshot
        return SAMPLE_TEST_PLAN

    monkeypatch.setattr(plan_router, "generate_plan", fake_generate_plan)

    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("ok", ContextProgress(
            objetivo=True, acceso=True, target_url="https://x.com", username="user", password="pass",
        )),
    )
    client.post("/api/chat", json={"session_id": session_id, "message": "login user/pass"})

    resp = client.post("/api/plan", json={"session_id": session_id})

    assert resp.status_code == 200
    assert captured["page_snapshot"] == "<input id=\"fallback\">"


def test_post_plan_skips_inspection_without_target_url(client, monkeypatch):
    session_id = _new_session(client, monkeypatch)
    called = {"count": 0}

    def fake_inspect(url):
        called["count"] += 1
        return "no deberia llamarse"

    monkeypatch.setattr(plan_router, "inspect_page", fake_inspect)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    client.post("/api/plan", json={"session_id": session_id})

    assert called["count"] == 0
