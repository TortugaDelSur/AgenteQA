import base64
from collections.abc import Awaitable, Callable
from pathlib import Path

from app import live
from app.execution import ExecutionPaused
from app.llm.page_inspector import extract_elements
from app.models.schemas import TestCase, TestResult, UiStep

# `ask(url, elements)` -> pregunta para el usuario, o None si no hay duda real.
AskFn = Callable[[str, str], Awaitable[str | None]]

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


async def _start_screencast(page, session_id: str) -> None:
    """Frames CDP al bus de la vista en vivo. Best-effort: sin CDP (firefox, fakes) no hay video."""
    try:
        cdp = await page.context.new_cdp_session(page)

        async def on_frame(params):
            live.publish(session_id, {"type": "frame", "data": params["data"]})
            await cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 50, "maxWidth": 1024})
    except Exception:
        pass


async def _password_filled(page) -> bool:
    """True si algun input password de la pagina ya tiene valor: el test mismo esta logueandose,
    asi que una falla ahi es un resultado, no un muro inesperado. Mira la pagina real en vez de
    adivinar por el selector (`#pwd`, `#clave` no dicen "pass")."""
    try:
        return bool(await page.evaluate(
            "() => [...document.querySelectorAll('input[type=password]')].some(i => i.value)"
        ))
    except Exception:
        return False


async def _check_pause(page, tc: TestCase, exc: Exception, ask: AskFn | None) -> ExecutionPaused | None:
    """Decide si una falla es algo que el agente no puede resolver solo.

    Un assert que falla es un resultado, nunca pausa por duda; solo pausa si detras hay un muro de
    login que el test no esperaba (el test no llena ningun password).
    """
    if "net::ERR_" in str(exc):
        return ExecutionPaused("unreachable", f"no se pudo abrir la app: {exc}")
    try:
        elements = extract_elements(await page.content()) or ""
        url = page.url
    except Exception:
        return None
    if 'type="password"' in elements and not await _password_filled(page):
        return ExecutionPaused("login", url)
    if ask and not isinstance(exc, AssertionError) and elements:
        question = await ask(url, elements)
        if question:
            return ExecutionPaused("question", question)
    return None


async def run_ui(tc: TestCase, session_id: str, browser=None, ask: AskFn | None = None) -> TestResult:
    """Ejecuta los steps de un TestCase tipo "ui" en orden sobre una pagina de Playwright.

    `browser` es inyectable (browser o context compartido); si no viene, arranca chromium headless.
    Corta en el primer step que falla, captura screenshot y lo referencia en `evidence`.
    Lanza ExecutionPaused si la falla es un login, la app caida o una duda (ver `_check_pause`).
    """
    steps = tc.steps or []
    own_browser = browser is None
    playwright = None
    if own_browser:  # pragma: no cover - requiere el browser real de Playwright
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)

    page = await browser.new_page()
    await _start_screencast(page, session_id)
    try:
        for index, step in enumerate(steps, start=1):
            live.publish(session_id, {
                "type": "step", "test_case_id": tc.id, "index": index,
                "action": step.action, "target": step.selector or step.url or "",
            })
            try:
                await run_step(page, step)
            except Exception as exc:
                paused = await _check_pause(page, tc, exc, ask)
                if paused:
                    raise paused from exc
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
