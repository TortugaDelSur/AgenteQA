from types import SimpleNamespace

import httpx

from app.execution.endpoint_runner import run_endpoint
from app.models.schemas import TestCase


def _endpoint_case(**overrides) -> TestCase:
    data = {
        "id": "TC-EP",
        "type": "endpoint",
        "title": "endpoint de prueba",
        "request": {"method": "GET", "url": "https://api.test/health", "headers": {}, "body": None},
        "expected_status": 200,
        "expected_body_contains": "ok",
    }
    data.update(overrides)
    return TestCase(**data)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_pass_when_status_and_body_match():
    def handler(request):
        return httpx.Response(200, text='{"status": "ok"}')

    result = await run_endpoint(_endpoint_case(), client=_client(handler))

    assert result.status == "pass"
    assert result.test_case_id == "TC-EP"
    assert "HTTP 200" in result.evidence


async def test_fail_on_status_mismatch():
    def handler(request):
        return httpx.Response(404, text="not found")

    result = await run_endpoint(_endpoint_case(expected_body_contains=None), client=_client(handler))

    assert result.status == "fail"
    assert "esperaba status 200, recibio 404" in result.detail


async def test_fail_on_body_mismatch():
    def handler(request):
        return httpx.Response(200, text="una respuesta distinta")

    result = await run_endpoint(_endpoint_case(), client=_client(handler))

    assert result.status == "fail"
    assert "no contiene el texto esperado" in result.detail


async def test_fail_lists_both_problems():
    def handler(request):
        return httpx.Response(500, text="boom")

    result = await run_endpoint(_endpoint_case(), client=_client(handler))

    assert result.status == "fail"
    assert "esperaba status 200, recibio 500" in result.detail
    assert "no contiene el texto esperado" in result.detail


async def test_error_when_request_raises():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    result = await run_endpoint(_endpoint_case(), client=_client(handler))

    assert result.status == "error"
    assert "la request fallo" in result.detail


async def test_error_when_endpoint_case_has_no_request():
    result = await run_endpoint(TestCase(id="TC-X", type="endpoint", title="sin request"))

    assert result.status == "error"
    assert "no define 'request'" in result.detail


async def test_pass_when_no_expectations_declared():
    def handler(request):
        return httpx.Response(204, text="")

    result = await run_endpoint(
        _endpoint_case(expected_status=None, expected_body_contains=None), client=_client(handler)
    )

    assert result.status == "pass"


async def test_sends_method_headers_and_body():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, text="ok")

    case = _endpoint_case(
        request={
            "method": "POST",
            "url": "https://api.test/items",
            "headers": {"Authorization": "Bearer t"},
            "body": {"name": "x"},
        },
    )

    result = await run_endpoint(case, client=_client(handler))

    assert result.status == "pass"
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer t"
    assert b'"name"' in seen["body"]


async def test_creates_and_closes_its_own_client(monkeypatch):
    closed = {"value": False}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def request(self, method, url, headers=None, json=None):
            return SimpleNamespace(status_code=200, text="ok")

        async def aclose(self):
            closed["value"] = True

    monkeypatch.setattr("app.execution.endpoint_runner.httpx.AsyncClient", FakeClient)

    result = await run_endpoint(_endpoint_case())

    assert result.status == "pass"
    assert closed["value"] is True
