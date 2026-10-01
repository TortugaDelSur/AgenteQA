import base64

from app.llm.authenticated_inspector import _login
from app.llm.page_inspector import extract_elements

GOTO_TIMEOUT_MS = 15000


async def try_login(page, login_url: str, username: str, password: str) -> bool:
    try:
        await _login(page, login_url, username, password)
        return True
    except Exception:
        return False


async def capture_page(page, url: str) -> tuple[str | None, str]:
    """Navega a `url`, saca un screenshot full-page en memoria (base64, nunca a disco) y
    extrae los elementos reales de la pagina renderizada. Devuelve (elements_or_None, screenshot_b64).
    """
    await page.goto(url, timeout=GOTO_TIMEOUT_MS)
    screenshot_bytes = await page.screenshot(full_page=True)
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
    elements = extract_elements(await page.content())
    return elements, screenshot_b64
