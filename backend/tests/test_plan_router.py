import app.routers.chat as chat_router
import app.routers.plan as plan_router
from app.models.schemas import ContextProgress
from tests.fixtures import SAMPLE_TEST_PLAN


def _new_session(client, monkeypatch) -> str:
    monkeypatch.setattr(chat_router, "llm_chat", lambda history: ("hola", ContextProgress()))
    return client.post("/api/chat", json={"message": "hola"}).json()["session_id"]


def test_post_plan_404_for_unknown_session(client):
    resp = client.post("/api/plan", json={"session_id": "no-existe"})
    assert resp.status_code == 404


def test_post_plan_success(client, monkeypatch):
    session_id = _new_session(client, monkeypatch)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history: SAMPLE_TEST_PLAN)

    resp = client.post("/api/plan", json={"session_id": session_id})

    assert resp.status_code == 200
    assert len(resp.json()["test_cases"]) == len(SAMPLE_TEST_PLAN.test_cases)


def test_post_plan_502_when_llm_output_invalid(client, monkeypatch):
    session_id = _new_session(client, monkeypatch)

    def raise_value_error(history):
        raise ValueError("json invalido")

    monkeypatch.setattr(plan_router, "generate_plan", raise_value_error)

    resp = client.post("/api/plan", json={"session_id": session_id})

    assert resp.status_code == 502
