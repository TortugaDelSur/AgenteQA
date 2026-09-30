"""Repo levantado por el runner, por sesion: run_id, URLs publicadas y cual es la app.

Cuando se apaga:
- al terminar una ejecucion completa (`stop`, lo llama execute.py; una pausa NO lo apaga);
- cuando nadie mira la pagina del agente (WebSocket de la sesion cerrado: pagina cerrada o sin
  internet) por mas de IDLE_GRACE_S y no hay barrido/ejecucion en curso (`reap_idle`). Un refresco
  reconecta en segundos, asi que no lo apaga;
- al olvidar el repo (`forget`) o al cerrar el backend.

Si se vuelve a necesitar, se relevanta: la app elegida se recuerda por posicion entre las URLs
(el runner publica puertos al azar, asi que la URL en si cambia).
"""

import asyncio
import atexit
import re
import time
from contextlib import contextmanager
from urllib.parse import urljoin, urlparse, urlunparse

from app import live, runner_client
from app.models.schemas import TestPlan

# ponytail: 90s cubre un refresco o un corte breve de wifi; si los usuarios se quejan de que el repo
# se apaga en cortes mas largos, subirlo.
IDLE_GRACE_S = 90
REAP_EVERY_S = 15

# ponytail: dicts de un solo proceso, igual que credentials/workspace.
_runs: dict[str, dict] = {}
_chosen_index: dict[str, int] = {}  # sobrevive a `stop`: al relevantar se elige la misma app
_busy: dict[str, int] = {}  # barridos/ejecuciones en curso por sesion


async def start(session_id: str, repo_path: str) -> list[str]:
    """Levanta el repo y devuelve sus URLs web. Si hay una sola, o ya se habia elegido la app en un
    levantado anterior, queda elegida."""
    run = await runner_client.start_run(session_id, repo_path)
    urls = run["urls"]
    index = 0 if len(urls) == 1 else _chosen_index.get(session_id)
    chosen = urls[index] if index is not None and index < len(urls) else None
    _runs[session_id] = {"run_id": run["run_id"], "urls": urls, "chosen": chosen, "started_at": time.monotonic()}
    return urls


def run_id(session_id: str) -> str | None:
    run = _runs.get(session_id)
    return run["run_id"] if run else None


def urls(session_id: str) -> list[str]:
    run = _runs.get(session_id)
    return run["urls"] if run else []


def chosen_url(session_id: str) -> str | None:
    run = _runs.get(session_id)
    return run["chosen"] if run else None


def choose(session_id: str, answer: str) -> str | None:
    """Elige la app entre las URLs publicadas segun la respuesta del usuario (la URL o el puerto)."""
    run = _runs.get(session_id)
    if not run:
        return None
    for index, url in enumerate(run["urls"]):
        port = str(urlparse(url).port)
        if url in answer or re.search(rf"(?<!\d){port}(?!\d)", answer):
            run["chosen"] = url
            _chosen_index[session_id] = index
            return url
    return None


def rebase_urls(extra_urls: list[str], app_url: str) -> list[str]:
    """Las paginas que el usuario nombro (quizas contra produccion) pasan a la app local: mismo path."""
    rebased = []
    for url in extra_urls:
        parsed = urlparse(url)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        rebased.append(urljoin(app_url, path or "/"))
    return rebased


def rebase_plan(plan: TestPlan, app_url: str, only_host: str | None = None) -> TestPlan:
    """Muda las URLs del plan a la app local (mismo path). Con `only_host`, solo las de ese host
    (relevantado: cambia el puerto); sin el, todas: el LLM arma las URLs desde lo que dijo el
    usuario en el chat (bug real en la e2e: `127.0.0.1:5000` en vez del puerto del runner)."""
    new = urlparse(app_url)

    def move(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.netloc or (only_host is not None and parsed.netloc != only_host):
            return url
        return urlunparse(parsed._replace(scheme=new.scheme, netloc=new.netloc))

    data = plan.model_copy(deep=True)
    for tc in data.test_cases:
        if tc.request:
            tc.request.url = move(tc.request.url)
        for step in tc.steps or []:
            if step.url:
                step.url = move(step.url)
    return data


@contextmanager
def hold(session_id: str):
    """Marca un barrido/ejecucion en curso: mientras dure, `reap_idle` no apaga el repo."""
    _busy[session_id] = _busy.get(session_id, 0) + 1
    try:
        yield
    finally:
        _busy[session_id] -= 1
        if not _busy[session_id]:
            del _busy[session_id]


def stop(session_id: str) -> None:
    """Apaga el repo levantado (best-effort: si el runner no responde, se olvida igual).
    Recuerda cual era la app, para relevantarlo igual."""
    run = _runs.pop(session_id, None)
    if run is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # contexto sync (rutas def, atexit): se espera el apagado
        try:
            asyncio.run(runner_client.stop_run(run["run_id"]))
        except Exception:
            pass
        return
    # dentro de un event loop no se puede bloquear: el apagado corre en segundo plano.
    task = loop.create_task(runner_client.stop_run(run["run_id"]))
    _pending.add(task)
    task.add_done_callback(_done)


def forget(session_id: str) -> None:
    """Apaga y olvida tambien cual era la app (el repo cambio o se desconecto)."""
    stop(session_id)
    _chosen_index.pop(session_id, None)


# referencias fuertes a las tareas de apagado (si no, el GC puede cortarlas a mitad de camino).
_pending: set[asyncio.Task] = set()


def _done(task: asyncio.Task) -> None:
    _pending.discard(task)
    if not task.cancelled():
        task.exception()  # consumida: el runner caido no es un error de la app


def reap_idle(now: float) -> list[str]:
    """Apaga los repos que nadie mira hace mas de IDLE_GRACE_S y que no tienen trabajo en curso."""
    idle = [
        sid for sid, run in _runs.items()
        if sid not in _busy
        and not live.is_watched(sid)
        and now - max(run["started_at"], live.last_seen(sid) or 0.0) > IDLE_GRACE_S
    ]
    for sid in idle:
        stop(sid)
    return idle


async def reap_forever() -> None:  # pragma: no cover - loop infinito; la logica esta en reap_idle
    while True:
        await asyncio.sleep(REAP_EVERY_S)
        reap_idle(time.monotonic())


@atexit.register
def _stop_all() -> None:
    for session_id in list(_runs):
        stop(session_id)
