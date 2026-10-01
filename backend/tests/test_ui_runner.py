import base64
import types

import pytest

from app.execution import ui_runner
from app.execution.ui_runner import _capture_screenshot, run_step, run_ui
from app.models.schemas import TestCase, UiStep


class FakePage:
    def __init__(self, *, text_by_selector=None, visible_selectors=None, screenshot_error=False):
        self.text_by_selector = text_by_selector or {}
        self.visible_selectors = set(visible_selectors or [])
        self.screenshot_error = screenshot_error
        self.calls: list[tuple] = []
        self.closed = False

    async def goto(self, url):
        self.calls.append(("goto", url))

    async def click(self, selector):
        self.calls.append(("click", selector))

    async def fill(self, selector, value):
        self.calls.append(("fill", selector, value))

    async def text_content(self, selector):
        self.calls.append(("text_content", selector))
        return self.text_by_selector.get(selector)

    async def is_visible(self, selector):
        self.calls.append(("is_visible", selector))
        return selector in self.visible_selectors

    async def screenshot(self, path=None):
        self.calls.append(("screenshot", path))
        if self.screenshot_error:
            raise RuntimeError("no se pudo capturar")
        if path is None:
            return b"fake-png-bytes"

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


# --- run_step: dispatch de acciones conocidas ---

async def test_run_step_goto():
    page = FakePage()
    await run_step(page, UiStep(action="goto", url="https://x.test"))
    assert page.calls == [("goto", "https://x.test")]


async def test_run_step_click():
    page = FakePage()
    await run_step(page, UiStep(action="click", selector="#btn"))
    assert page.calls == [("click", "#btn")]


async def test_run_step_fill_defaults_missing_value_to_empty():
    page = FakePage()
    await run_step(page, UiStep(action="fill", selector="#in"))
    assert page.calls == [("fill", "#in", "")]


async def test_run_step_assert_text_pass():
    page = FakePage(text_by_selector={"h1": "Hola mundo"})
    await run_step(page, UiStep(action="assert_text", selector="h1", expected="mundo"))


async def test_run_step_assert_text_fail_on_mismatch():
    page = FakePage(text_by_selector={"h1": "otra cosa"})
    with pytest.raises(AssertionError):
        await run_step(page, UiStep(action="assert_text", selector="h1", expected="mundo"))


async def test_run_step_assert_text_fail_when_selector_missing():
    page = FakePage()
    with pytest.raises(AssertionError):
        await run_step(page, UiStep(action="assert_text", selector="h1", expected="x"))


async def test_run_step_assert_visible_pass():
    page = FakePage(visible_selectors=["#ok"])
    await run_step(page, UiStep(action="assert_visible", selector="#ok"))


async def test_run_step_assert_visible_fail():
    page = FakePage()
    with pytest.raises(AssertionError):
        await run_step(page, UiStep(action="assert_visible", selector="#ok"))


async def test_run_step_unknown_action_raises():
    bogus = types.SimpleNamespace(action="teleport", selector=None, url=None, value=None, expected=None)
    with pytest.raises(ValueError):
        await run_step(FakePage(), bogus)


# --- run_ui: orquestacion sobre un browser inyectado ---

def _ui_case(steps):
    return TestCase(id="TC-UI", type="ui", title="flujo ui", steps=steps)


async def test_run_ui_all_steps_pass():
    page = FakePage(text_by_selector={"h1": "Bienvenido"}, visible_selectors=["#home"])
    case = _ui_case([
        UiStep(action="goto", url="https://x.test"),
        UiStep(action="fill", selector="#email", value="a@b.c"),
        UiStep(action="click", selector="#go"),
        UiStep(action="assert_text", selector="h1", expected="Bienvenido"),
        UiStep(action="assert_visible", selector="#home"),
    ])

    result = await run_ui(case, "sess-1", browser=FakeBrowser(page))

    assert result.status == "pass"
    assert "5 step(s)" in result.detail
    assert result.evidence is None
    assert result.screenshot_b64 == base64.b64encode(b"fake-png-bytes").decode()
    assert page.closed is True


async def test_run_ui_no_steps_passes():
    result = await run_ui(_ui_case(None), "sess-0", browser=FakeBrowser(FakePage()))
    assert result.status == "pass"
    assert "0 step(s)" in result.detail


async def test_run_ui_stops_at_first_failing_step_and_screenshots(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_runner, "SCREENSHOT_DIR", tmp_path)
    page = FakePage(text_by_selector={"h1": "algo"})
    case = _ui_case([
        UiStep(action="goto", url="https://x.test"),
        UiStep(action="assert_text", selector="h1", expected="Bienvenido"),
        UiStep(action="click", selector="#nunca"),
    ])

    result = await run_ui(case, "sess-2", browser=FakeBrowser(page))

    assert result.status == "fail"
    assert "step 2" in result.detail
    assert result.evidence == str(tmp_path / "sess-2" / "TC-UI.png")
    assert result.screenshot_b64 == base64.b64encode(b"fake-png-bytes").decode()
    assert ("click", "#nunca") not in page.calls  # corta antes del step 3
    assert (tmp_path / "sess-2").is_dir()
    assert page.closed is True


async def test_run_ui_evidence_none_when_screenshot_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_runner, "SCREENSHOT_DIR", tmp_path)
    page = FakePage(screenshot_error=True)
    case = _ui_case([UiStep(action="assert_visible", selector="#nope")])

    result = await run_ui(case, "sess-3", browser=FakeBrowser(page))

    assert result.status == "fail"
    assert result.evidence is None
    assert result.screenshot_b64 is None


async def test_capture_screenshot_writes_under_session_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_runner, "SCREENSHOT_DIR", tmp_path)
    page = FakePage()

    path = await _capture_screenshot(page, "s", "TC-1")

    assert path == str(tmp_path / "s" / "TC-1.png")
    assert ("screenshot", path) in page.calls


# --- pausa: login, app caida, duda; y eventos de la vista en vivo ---

class PausePage(FakePage):
    def __init__(self, html="", goto_error=None, password_filled=False, **kwargs):
        super().__init__(**kwargs)
        self.html = html
        self.password_filled = password_filled
        self.goto_error = goto_error
        self.url = "https://x.test/admin"

    async def goto(self, url):
        if self.goto_error:
            raise RuntimeError(self.goto_error)
        await super().goto(url)

    async def click(self, selector):
        raise TimeoutError(f"no encontre {selector}")

    async def content(self):
        return self.html

    async def evaluate(self, script):
        return self.password_filled


async def test_run_ui_pauses_on_unexpected_login_wall():
    page = PausePage(html='<input type="password" name="pw">')
    case = _ui_case([UiStep(action="goto", url="https://x.test/admin"), UiStep(action="click", selector="#x")])

    with pytest.raises(ui_runner.ExecutionPaused) as info:
        await run_ui(case, "s", browser=FakeBrowser(page))

    assert info.value.reason == "login"
    assert info.value.detail == "https://x.test/admin"
    assert page.closed is True


async def test_run_ui_login_test_that_fails_is_a_result_not_a_pause(tmp_path, monkeypatch):
    # el test mismo llena el password: si falla, es un fallo del login, no un muro inesperado.
    monkeypatch.setattr(ui_runner, "SCREENSHOT_DIR", tmp_path)
    # selector sin "pass" a proposito: se mira si el campo password de la pagina tiene valor.
    page = PausePage(html='<input type="password" id="pwd">', password_filled=True)
    case = _ui_case([UiStep(action="fill", selector="#pwd", value="x"), UiStep(action="click", selector="#go")])

    result = await run_ui(case, "s", browser=FakeBrowser(page))

    assert result.status == "fail"


async def test_run_ui_pauses_when_app_is_unreachable():
    page = PausePage(goto_error="net::ERR_CONNECTION_REFUSED at http://127.0.0.1:9")
    case = _ui_case([UiStep(action="goto", url="http://127.0.0.1:9")])

    with pytest.raises(ui_runner.ExecutionPaused) as info:
        await run_ui(case, "s", browser=FakeBrowser(page))

    assert info.value.reason == "unreachable"


async def test_run_ui_asks_on_missing_element_but_never_on_failed_assert(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_runner, "SCREENSHOT_DIR", tmp_path)
    asked = []

    async def ask(url, elements):
        asked.append(url)
        return "¿el boton se llama distinto?"

    page = PausePage(html='<button id="otro">Ir</button>', text_by_selector={"h1": "otra"})
    with pytest.raises(ui_runner.ExecutionPaused) as info:
        await run_ui(_ui_case([UiStep(action="click", selector="#go")]), "s", browser=FakeBrowser(page), ask=ask)
    assert info.value.reason == "question"

    result = await run_ui(
        _ui_case([UiStep(action="assert_text", selector="h1", expected="hola")]), "s",
        browser=FakeBrowser(page), ask=ask,
    )
    assert result.status == "fail"
    assert asked == ["https://x.test/admin"]  # solo la primera vez


async def test_run_ui_publishes_steps_and_screencast_frames(monkeypatch):
    published = []
    monkeypatch.setattr(ui_runner.live, "publish", lambda sid, msg: published.append((sid, msg)))

    class FakeCdp:
        def __init__(self):
            self.handlers, self.sent = {}, []

        def on(self, event, handler):
            self.handlers[event] = handler

        async def send(self, method, params):
            self.sent.append(method)

    cdp = FakeCdp()
    page = FakePage()

    async def new_cdp_session(p):
        return cdp

    page.context = types.SimpleNamespace(new_cdp_session=new_cdp_session)

    await run_ui(_ui_case([UiStep(action="goto", url="https://x.test")]), "s", browser=FakeBrowser(page))
    await cdp.handlers["Page.screencastFrame"]({"data": "JPEG", "sessionId": 7})

    assert cdp.sent == ["Page.startScreencast", "Page.screencastFrameAck"]
    assert ("s", {"type": "step", "test_case_id": "TC-UI", "index": 1, "action": "goto", "target": "https://x.test"}) in published
    assert ("s", {"type": "frame", "data": "JPEG"}) in published
