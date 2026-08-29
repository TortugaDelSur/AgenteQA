import app.routers.chat as chat_router
from app.models.schemas import ContextProgress
from openai import OpenAIError


def test_post_chat_creates_new_session(client, monkeypatch):
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history: ("hola, contame el objetivo", ContextProgress()),
    )

    resp = client.post("/api/chat", json={"message": "quiero testear mi app"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "hola, contame el objetivo"
    assert data["ready_for_plan"] is False
    assert data["session_id"]


def test_post_chat_reuses_session_and_sends_full_history(client, monkeypatch):
    captured_history = []

    def fake_llm_chat(history):
        captured_history.append(list(history))
        return "segunda respuesta", ContextProgress(objetivo=True)

    monkeypatch.setattr(chat_router, "llm_chat", lambda history: ("primera", ContextProgress()))
    session_id = client.post("/api/chat", json={"message": "hola"}).json()["session_id"]

    monkeypatch.setattr(chat_router, "llm_chat", fake_llm_chat)
    resp = client.post("/api/chat", json={"session_id": session_id, "message": "quiero testear web"})

    assert resp.status_code == 200
    assert resp.json()["context"]["objetivo"] is True
    # el historial mandado al LLM incluye los 3 mensajes previos (user, assistant, user)
    assert len(captured_history[0]) == 3


def test_post_chat_returns_502_on_llm_error(client, monkeypatch):
    def raise_error(history):
        raise OpenAIError("boom")

    monkeypatch.setattr(chat_router, "llm_chat", raise_error)

    resp = client.post("/api/chat", json={"message": "hola"})

    assert resp.status_code == 502


def test_get_chat_history_404_for_unknown_session(client):
    resp = client.get("/api/chat/no-existe")
    assert resp.status_code == 404


def test_get_chat_history_returns_messages(client, monkeypatch):
    monkeypatch.setattr(chat_router, "llm_chat", lambda history: ("hola", ContextProgress()))
    session_id = client.post("/api/chat", json={"message": "hola"}).json()["session_id"]

    resp = client.get(f"/api/chat/{session_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"
