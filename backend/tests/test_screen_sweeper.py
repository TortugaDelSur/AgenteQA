from app.llm.screen_sweeper import capture_page, try_login
from tests.test_authenticated_inspector import FakeLocator, FakePage


class SweepFakePage(FakePage):
    """FakePage + screenshot en memoria, sin tocar el fake compartido con authenticated_inspector."""

    def __init__(self, *args, screenshot_bytes=b"fake-png-bytes", **kwargs):
        super().__init__(*args, **kwargs)
        self.screenshot_bytes = screenshot_bytes

    async def screenshot(self, full_page=True):
        return self.screenshot_bytes


async def test_try_login_returns_true_on_success():
    page = SweepFakePage()
    assert await try_login(page, "https://x.com/login", "user", "pass") is True


async def test_try_login_returns_false_on_failure():
    page = SweepFakePage(fail_selector='input[type="password"]')
    assert await try_login(page, "https://x.com/login", "user", "pass") is False


async def test_capture_page_returns_elements_and_b64_screenshot():
    page = SweepFakePage(html_by_url={"https://x.com/dash": '<input id="search">'})

    elements, screenshot_b64 = await capture_page(page, "https://x.com/dash")

    assert elements is not None and 'id="search"' in elements
    import base64
    assert base64.b64decode(screenshot_b64) == b"fake-png-bytes"


async def test_capture_page_elements_none_when_no_interactive_elements():
    page = SweepFakePage(html_by_url={"https://x.com/about": "<p>solo texto</p>"})

    elements, _ = await capture_page(page, "https://x.com/about")

    assert elements is None
