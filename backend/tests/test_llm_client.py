import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.llm import client as llm_client
from app.models.schemas import ChatMessage


class FakeCompletions:
    def __init__(self, contents):
        self._contents = list(contents)
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        content = self._contents.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeClient:
    def __init__(self, contents):
        self.chat = SimpleNamespace(completions=FakeCompletions(contents))


HISTORY = [ChatMessage(role="user", content="quiero testear mi app")]


def test_chat_parses_reply_and_context(monkeypatch):
    fake = FakeClient([json.dumps({
        "reply": "hola",
        "context": {"objetivo": True, "acceso": False, "alcance": False, "repo": False},
    })])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)

    reply, context = llm_client.chat(HISTORY)

    assert reply == "hola"
    assert context.objetivo is True
    assert context.ready_for_plan is False


def test_generate_plan_valid_on_first_try(monkeypatch):
    valid_plan = json.dumps({
        "test_cases": [{
            "id": "TC-01", "type": "endpoint", "title": "health check",
            "request": {"method": "GET", "url": "https://x.com/health"},
            "expected_status": 200,
        }]
    })
    fake = FakeClient([valid_plan])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)

    plan = llm_client.generate_plan(HISTORY)

    assert len(plan.test_cases) == 1
    assert plan.test_cases[0].type == "endpoint"


def test_generate_plan_retries_once_then_succeeds(monkeypatch):
    valid_plan = json.dumps({
        "test_cases": [{
            "id": "TC-01", "type": "endpoint", "title": "health check",
            "request": {"method": "GET", "url": "https://x.com/health"},
            "expected_status": 200,
        }]
    })
    fake = FakeClient(["esto no es json valido {{{", valid_plan])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)

    plan = llm_client.generate_plan(HISTORY)

    assert len(plan.test_cases) == 1


def test_generate_plan_raises_after_two_bad_attempts(monkeypatch):
    fake = FakeClient(["no es json {{{", "sigue sin ser json {{{"])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)

    with pytest.raises(json.JSONDecodeError):
        llm_client.generate_plan(HISTORY)


def test_generate_plan_raises_validation_error_after_retry(monkeypatch):
    invalid_schema = json.dumps({"test_cases": [{"id": "TC-01", "type": "not-a-real-type", "title": "x"}]})
    fake = FakeClient([invalid_schema, invalid_schema])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)

    with pytest.raises(ValidationError):
        llm_client.generate_plan(HISTORY)


def test_generate_plan_includes_page_snapshot_when_given(monkeypatch):
    valid_plan = json.dumps({
        "test_cases": [{
            "id": "TC-01", "type": "endpoint", "title": "health check",
            "request": {"method": "GET", "url": "https://x.com/health"},
            "expected_status": 200,
        }]
    })
    fake = FakeClient([valid_plan])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)

    llm_client.generate_plan(HISTORY, page_snapshot='<input id="username">')

    sent_messages = fake.chat.completions.last_kwargs["messages"]
    assert any('<input id="username">' in m["content"] for m in sent_messages)


def test_generate_report_not_implemented():
    with pytest.raises(NotImplementedError):
        llm_client.generate_report(plan=None, results=[])
