"""Repo levantado por el runner, por sesion: run_id, URLs publicadas y cual es la app.

Queda arriba toda la sesion (el runner publica puertos al azar: relevantarlo dejaria las URLs del
plan apuntando a un puerto viejo). Se apaga al olvidar el repo o al cerrar el backend.
"""

import asyncio
import atexit
import re
from urllib.parse import urljoin, urlparse

from app import runner_client

# ponytail: dict de un solo proceso, igual que credentials/workspace.
_runs: dict[str, dict] = {}


async def start(session_id: str, repo_path: str) -> list[str]:
    """Levanta el repo y devuelve sus URLs web. Si hay una sola, queda elegida como la app."""
    run = await runner_client.start_run(session_id, repo_path)
    urls = run["urls"]
    _runs[session_id] = {"run_id": run["run_id"], "urls": urls, "chosen": urls[0] if len(urls) == 1 else None}
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
    for url in run["urls"]:
        port = str(urlparse(url).port)
        if url in answer or re.search(rf"(?<!\d){port}(?!\d)", answer):
            run["chosen"] = url
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


def forget(session_id: str) -> None:
    """Apaga el repo levantado (best-effort: si el runner no responde, se olvida igual)."""
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


# referencias fuertes a las tareas de apagado (si no, el GC puede cortarlas a mitad de camino).
_pending: set[asyncio.Task] = set()


def _done(task: asyncio.Task) -> None:
    _pending.discard(task)
    if not task.cancelled():
        task.exception()  # consumida: el runner caido no es un error de la app


@atexit.register
def _stop_all() -> None:
    for session_id in list(_runs):
        forget(session_id)
