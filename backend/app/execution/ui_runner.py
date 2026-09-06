import base64
from pathlib import Path

from app.models.schemas import TestCase, TestResult, UiStep

# backend/app/execution/ui_runner.py -> parents[2] == backend/
SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "screenshots"


async def _do_goto(page, step: UiStep) -> None:
    await page.goto(step.url)


async def _do_click(page, step: UiStep) -> None:
    await page.click(step.selector)


async def _do_fill(page, step: UiStep) -> None:
    await page.fill(step.selector, step.value or "")


async def _do_assert_text(page, step: UiStep) -> None:
    actual = await page.text_content(step.selector)
    expected = step.expected or ""
    if actual is None or expected not in actual:
        raise AssertionError(
            f"esperaba el texto {expected!r} en '{step.selector}', encontro {actual!r}"
        )


async def _do_assert_visible(page, step: UiStep) -> None:
    if not await page.is_visible(step.selector):
        raise AssertionError(f"esperaba que '{step.selector}' estuviera visible, no lo esta")


# Dispatch fijo: NO agregar acciones sin actualizar el schema UiStep (contrato con Persona A).
ACTIONS = {
    "goto": _do_goto,
    "click": _do_click,
    "fill": _do_fill,
    "assert_text": _do_assert_text,
    "assert_visible": _do_assert_visible,
}


async def run_step(page, step: UiStep) -> None:
    handler = ACTIONS.get(step.action)
    if handler is None:
        raise ValueError(f"accion de UI desconocida: {step.action!r}")
    await handler(page, step)


async def _capture_screenshot(page, session_id: str, tc_id: str) -> str | None:
    path = SCREENSHOT_DIR / session_id / f"{tc_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(path))
    except Exception:
        return None
    return str(path)


async def _capture_screenshot_b64(page) -> str | None:
    """Captura en memoria (base64, nunca a disco) para que el front la muestre en vivo,
    tanto en un test que pasa como en uno que falla — a diferencia de `_capture_screenshot`,
    que solo guarda a disco como evidencia de un fallo.
    """
    try:
        screenshot_bytes = await page.screenshot()
    except Exception:
        return None
    return base64.b64encode(screenshot_bytes).decode()


async def run_ui(tc: TestCase, session_id: str, browser=None) -> TestResult:
    """Ejecuta los steps de un TestCase tipo "ui" en orden sobre una pagina de Playwright.

    `browser` es inyectable para tests; si no viene, arranca chromium headless.
    Corta en el primer step que falla, captura screenshot y lo referencia en `evidence`.
    """
    steps = tc.steps or []
    own_browser = browser is None
    playwright = None
    if own_browser:  # pragma: no cover - requiere el browser real de Playwright
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)

    page = await browser.new_page()
    try:
        for index, step in enumerate(steps, start=1):
            try:
                await run_step(page, step)
            except Exception as exc:
                evidence = await _capture_screenshot(page, session_id, tc.id)
                target = step.selector or step.url
                return TestResult(
                    test_case_id=tc.id,
                    status="fail",
                    detail=f"step {index} ({step.action} en {target!r}): {exc}",
                    evidence=evidence,
                    screenshot_b64=await _capture_screenshot_b64(page),
                )
        return TestResult(
            test_case_id=tc.id,
            status="pass",
            detail=f"{len(steps)} step(s) ejecutados sin errores",
            screenshot_b64=await _capture_screenshot_b64(page),
        )
    finally:
        await page.close()
        if own_browser:  # pragma: no cover - requiere el browser real de Playwright
            await browser.close()
            await playwright.stop()
