from types import SimpleNamespace

import httpx

from app.llm import page_inspector


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def test_extracts_form_elements(monkeypatch):
    html = '<html><body><form><input id="username" name="username" type="text">' \
           '<input id="password" type="password"><button id="login">Login</button></form></body></html>'
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(html))

    result = page_inspector.inspect_page("https://x.com")

    assert 'id="username"' in result
    assert 'id="password"' in result
    assert 'id="login"' in result


def test_returns_none_on_http_error(monkeypatch):
    def raise_error(*a, **k):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(httpx, "get", raise_error)

    assert page_inspector.inspect_page("https://x.com") is None


def test_returns_none_when_no_relevant_elements(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse("<html><body><p>hola</p></body></html>"))

    assert page_inspector.inspect_page("https://x.com") is None
