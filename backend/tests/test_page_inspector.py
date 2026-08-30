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


def test_marks_links_with_landmark_context(monkeypatch):
    # bug real: el mismo href aparece en el menu mobile oculto y en el nav visible, un selector
    # generico matchea el duplicado equivocado. El contexto [nav]/[footer] le permite al LLM
    # acotar el selector para evitar eso.
    html = (
        '<html><body>'
        '<header><nav><a href="/x">X</a></nav></header>'
        '<footer><a href="/x">X (footer)</a></footer>'
        '<form><input id="search"></form>'
        '</body></html>'
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(html))

    result = page_inspector.inspect_page("https://x.com")

    assert '[nav] <a href="/x">' in result
    assert '[footer] <a href="/x">' in result
    # los elementos de formulario (sin landmark en este caso) no llevan prefijo
    assert 'id="search"' in result and "[form]" not in result


def test_returns_none_on_http_error(monkeypatch):
    def raise_error(*a, **k):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(httpx, "get", raise_error)

    assert page_inspector.inspect_page("https://x.com") is None


def test_nav_links_dont_crowd_out_form_elements(monkeypatch):
    # muchos <a> de navegacion antes del form real en el HTML
    nav = "".join(f'<a href="/page{i}">link{i}</a>' for i in range(page_inspector.MAX_ELEMENTS + 10))
    html = f'<html><body>{nav}<form><input id="real-input" name="x"></form></body></html>'
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(html))

    result = page_inspector.inspect_page("https://x.com")

    assert 'id="real-input"' in result


def test_returns_none_when_no_relevant_elements(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse("<html><body><p>hola</p></body></html>"))

    assert page_inspector.inspect_page("https://x.com") is None


def test_inspect_multiple_returns_snapshot_per_reachable_url(monkeypatch):
    html_by_url = {
        "https://x.com/a": '<input id="a-input">',
        "https://x.com/c": '<input id="c-input">',
    }

    def fake_get(url, **kwargs):
        if url not in html_by_url:
            raise httpx.ConnectTimeout("timeout")
        return FakeResponse(html_by_url[url])

    monkeypatch.setattr(httpx, "get", fake_get)

    result = page_inspector.inspect_multiple(["https://x.com/a", "https://x.com/b", "https://x.com/c"])

    assert set(result.keys()) == {"https://x.com/a", "https://x.com/c"}
    assert 'id="a-input"' in result["https://x.com/a"]


def test_format_snapshots_labels_each_url():
    text = page_inspector.format_snapshots({"https://a.com": "<input>", "https://b.com": "<button>"})
    assert "== https://a.com ==" in text
    assert "== https://b.com ==" in text


def test_format_snapshots_truncates_when_too_large():
    # bug real: 8 paginas de un e-commerce generaron >12000 tokens en un solo request y
    # exploto el limite por-minuto de un plan gratis de Groq.
    huge_snapshots = {f"https://x.com/page{i}": "<input>" * 200 for i in range(10)}

    text = page_inspector.format_snapshots(huge_snapshots)

    assert len(text) <= page_inspector.MAX_SNAPSHOT_CHARS + len("\n... (truncado, habia mas elementos/paginas de los que entran aca)")
    assert "truncado" in text
