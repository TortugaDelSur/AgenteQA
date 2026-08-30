from app.llm.page_inspector import extract_elements, format_snapshots  # noqa: F401 (reexportado)

LOGIN_TIMEOUT_MS = 15000


async def _login(page, login_url: str, username: str, password: str) -> None:
    await page.goto(login_url, timeout=LOGIN_TIMEOUT_MS)

    password_input = page.locator('input[type="password"]').first
    await password_input.fill(password)

    # heuristica: el campo de usuario suele ser el primer input de texto/email de la pagina.
    user_input = page.locator('input[type="email"], input[type="text"], input[name*="user" i]').first
    await user_input.fill(username)

    submit = page.locator('button[type="submit"], input[type="submit"]').first
    await submit.click()
    await page.wait_for_load_state("networkidle", timeout=LOGIN_TIMEOUT_MS)


async def inspect_with_login(
    login_url: str,
    username: str,
    password: str,
    extra_urls: list[str],
    browser=None,
) -> dict[str, str] | None:
    """Loguea con un browser real y saca los elementos de la pagina post-login + paginas extra.

    `browser` es inyectable para tests; si no viene, arranca chromium headless.
    Devuelve None si el login o la navegacion fallan (el caller cae al inspect_page estatico).
    """
    own_browser = browser is None
    playwright = None
    if own_browser:  # pragma: no cover - requiere el browser real de Playwright
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)

    page = await browser.new_page()
    snapshots: dict[str, str] = {}
    try:
        try:
            await _login(page, login_url, username, password)
        except Exception:
            return None

        post_login_html = await page.content()
        elements = extract_elements(post_login_html)
        if elements:
            snapshots[page.url] = elements

        for url in extra_urls:
            try:
                await page.goto(url, timeout=LOGIN_TIMEOUT_MS)
                elements = extract_elements(await page.content())
                if elements:
                    snapshots[url] = elements
            except Exception:
                continue  # una pagina extra que falla no tumba el resto

        return snapshots or None
    finally:
        await page.close()
        if own_browser:  # pragma: no cover - requiere el browser real de Playwright
            await browser.close()
            await playwright.stop()
