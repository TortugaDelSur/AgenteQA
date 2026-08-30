from app.llm.authenticated_inspector import format_snapshots, inspect_with_login


class FakeLocator:
    def __init__(self, selector, calls, fail=False):
        self.selector = selector
        self.calls = calls
        self.fail = fail

    @property
    def first(self):
        return self

    async def fill(self, value):
        if self.fail:
            raise RuntimeError(f"no encontro {self.selector!r}")
        self.calls.append(("fill", self.selector, value))

    async def click(self):
        if self.fail:
            raise RuntimeError(f"no encontro {self.selector!r}")
        self.calls.append(("click", self.selector))


class FakePage:
    def __init__(self, html_by_url=None, fail_selector=None, fail_extra_url=None):
        self.calls = []
        self.html_by_url = html_by_url or {}
        self.current_url = None
        self.fail_selector = fail_selector
        self.fail_extra_url = fail_extra_url
        self.closed = False

    def locator(self, selector):
        return FakeLocator(selector, self.calls, fail=(selector == self.fail_selector))

    async def goto(self, url, timeout=None):
        if url == self.fail_extra_url:
            raise RuntimeError("no se pudo navegar")
        self.calls.append(("goto", url))
        self.current_url = url

    async def wait_for_load_state(self, state, timeout=None):
        self.calls.append(("wait", state))

    async def content(self):
        return self.html_by_url.get(self.current_url, "")

    @property
    def url(self):
        return self.current_url

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


DASHBOARD_HTML = '<input id="search" name="search">'
SETTINGS_HTML = '<button id="save">Guardar</button>'


async def test_inspect_with_login_success_and_extra_urls():
    page = FakePage(html_by_url={
        "https://x.com/login": DASHBOARD_HTML,
        "https://x.com/settings": SETTINGS_HTML,
    })

    result = await inspect_with_login(
        "https://x.com/login", "user", "pass", ["https://x.com/settings"], browser=FakeBrowser(page),
    )

    assert result is not None
    assert 'id="search"' in result["https://x.com/login"]
    assert 'id="save"' in result["https://x.com/settings"]
    assert page.closed is True


async def test_inspect_with_login_returns_none_on_login_failure():
    page = FakePage(fail_selector='input[type="password"]')

    result = await inspect_with_login("https://x.com/login", "user", "pass", [], browser=FakeBrowser(page))

    assert result is None
    assert page.closed is True


async def test_inspect_with_login_skips_failing_extra_url():
    page = FakePage(
        html_by_url={"https://x.com/login": DASHBOARD_HTML},
        fail_extra_url="https://x.com/broken",
    )

    result = await inspect_with_login(
        "https://x.com/login", "user", "pass",
        ["https://x.com/broken"], browser=FakeBrowser(page),
    )

    assert result is not None
    assert "https://x.com/login" in result
    assert "https://x.com/broken" not in result


def test_format_snapshots_labels_each_url():
    text = format_snapshots({"https://a.com": "<input>", "https://b.com": "<button>"})
    assert "== https://a.com ==" in text
    assert "== https://b.com ==" in text
