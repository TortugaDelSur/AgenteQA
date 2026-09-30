"""Clon por sesion: se baja una vez a una carpeta temporal, se inspecciona y se borra al terminar.

`repo_path` es lo que el runner (pista B) recibe como `repo_path`.
"""

import atexit
import shutil
import tempfile
from pathlib import Path

from app.models.schemas import RepoInfo, repo_provider
from app.repo import credentials
from app.repo.clone import CloneError, clone
from app.repo.inspector import format_repo_summary, inspect_repo

# ponytail: cache en memoria de un solo proceso; dos turnos simultaneos de la misma sesion
# podrian clonar dos veces (el segundo pisa al primero y la carpeta vieja queda hasta atexit).
_clones: dict[str, tuple[str, Path, RepoInfo]] = {}


def repo_path(session_id: str) -> Path | None:
    entry = _clones.get(session_id)
    return entry[1] if entry else None


def forget(session_id: str) -> None:
    entry = _clones.pop(session_id, None)
    if entry:
        shutil.rmtree(entry[1].parent, ignore_errors=True)


def repo_context(session_id: str, repo_url: str) -> str:
    """Bloque de contexto del repo para el chat: estado del token + resumen (o por que no hay)."""
    provider = repo_provider(repo_url) or "github"
    connected = credentials.status(session_id).get(provider, False)
    header = f"Repo {repo_url} ({provider}). Token: {'conectado' if connected else 'no conectado'}."

    entry = _clones.get(session_id)
    if entry is None or entry[0] != repo_url:
        forget(session_id)
        workdir = Path(tempfile.mkdtemp(prefix="aqa-repo-"))
        try:
            dest = clone(repo_url, workdir / "repo", credentials.get_token(session_id, provider))
        except CloneError:
            shutil.rmtree(workdir, ignore_errors=True)
            hint = "" if connected else " Si es privado, pedile al usuario que cargue el token en \"Conectar repo\"."
            return f"{header} No se pudo clonar.{hint}"
        entry = (repo_url, dest, inspect_repo(dest))
        _clones[session_id] = entry
    return f"{header}\n{format_repo_summary(entry[2])}"


@atexit.register
def _cleanup_all() -> None:
    for session_id in list(_clones):
        forget(session_id)
