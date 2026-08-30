import app.routers.chat as chat_router
from app.models.schemas import ContextProgress
from openai import OpenAIError


def test_post_chat_creates_new_session(client, monkeypatch):
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("hola, contame el objetivo", ContextProgress()),
    )

    resp = client.post("/api/chat", json={"message": "quiero testear mi app"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "hola, contame el objetivo"
    assert data["ready_for_plan"] is False
    assert data["session_id"]


def test_post_chat_reuses_session_and_sends_full_history(client, monkeypatch):
    captured_history = []

    def fake_llm_chat(history, page_snapshot=None):
        captured_history.append(list(history))
        return "segunda respuesta", ContextProgress(objetivo=True)

    monkeypatch.setattr(chat_router, "llm_chat", lambda history, page_snapshot=None: ("primera", ContextProgress()))
    session_id = client.post("/api/chat", json={"message": "hola"}).json()["session_id"]

    monkeypatch.setattr(chat_router, "llm_chat", fake_llm_chat)
    resp = client.post("/api/chat", json={"session_id": session_id, "message": "quiero testear web"})

    assert resp.status_code == 200
    assert resp.json()["context"]["objetivo"] is True
    # el historial mandado al LLM incluye los 3 mensajes previos (user, assistant, user)
    assert len(captured_history[0]) == 3


def test_post_chat_returns_502_on_llm_error(client, monkeypatch):
    def raise_error(history, page_snapshot=None):
        raise OpenAIError("boom")

    monkeypatch.setattr(chat_router, "llm_chat", raise_error)

    resp = client.post("/api/chat", json={"message": "hola"})

    assert resp.status_code == 502


def test_post_chat_passes_page_snapshot_when_target_url_already_known(client, monkeypatch):
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("ok", ContextProgress(objetivo=True, target_url="https://x.com")),
    )
    session_id = client.post("/api/chat", json={"message": "url https://x.com"}).json()["session_id"]

    monkeypatch.setattr(chat_router, "inspect_page", lambda url: "<input id=\"y\">")
    captured = {}

    def fake_llm_chat(history, page_snapshot=None):
        captured["page_snapshot"] = page_snapshot
        return "listo", ContextProgress(objetivo=True, target_url="https://x.com")

    monkeypatch.setattr(chat_router, "llm_chat", fake_llm_chat)
    client.post("/api/chat", json={"session_id": session_id, "message": "algo mas"})

    assert captured["page_snapshot"] == "<input id=\"y\">"


def test_post_chat_skips_inspection_without_known_target_url(client, monkeypatch):
    called = {"count": 0}

    def fake_inspect(url):
        called["count"] += 1
        return "no deberia llamarse"

    monkeypatch.setattr(chat_router, "inspect_page", fake_inspect)
    monkeypatch.setattr(chat_router, "llm_chat", lambda history, page_snapshot=None: ("hola", ContextProgress()))

    client.post("/api/chat", json={"message": "hola"})

    assert called["count"] == 0


def test_get_chat_history_404_for_unknown_session(client):
    resp = client.get("/api/chat/no-existe")
    assert resp.status_code == 404


def test_get_chat_history_returns_messages(client, monkeypatch):
    monkeypatch.setattr(chat_router, "llm_chat", lambda history, page_snapshot=None: ("hola", ContextProgress()))
    session_id = client.post("/api/chat", json={"message": "hola"}).json()["session_id"]

    resp = client.get(f"/api/chat/{session_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"
