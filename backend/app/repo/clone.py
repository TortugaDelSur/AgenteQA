"""Clon liviano (`--depth 1`) del repo de la empresa.

El token viaja a git SOLO por variables de entorno (`GIT_CONFIG_*` -> `http.<host>.extraHeader`):
nunca en la URL, en argv (visible en `ps`) ni en `.git/config`.
"""

import base64
import os
import shutil
import subprocess
from pathlib import Path

from app.models.schemas import repo_provider
from app.security import redact

CLONE_TIMEOUT_S = 120

# usuario que cada proveedor acepta junto a un token en Basic auth.
_TOKEN_USER = {"github": "x-access-token", "bitbucket": "x-token-auth"}


class CloneError(Exception):
    pass


def _git_env(repo_url: str, provider: str, token: str | None) -> dict[str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
    if token:
        basic = base64.b64encode(f"{_TOKEN_USER[provider]}:{token}".encode()).decode()
        host = repo_url.split("/")[2]
        env |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.https://{host}/.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        }
    return env


def clone(repo_url: str, dest: Path, token: str | None) -> Path:
    provider = repo_provider(repo_url)
    if provider is None:
        # anti-SSRF: solo https a github.com / bitbucket.org, igual que ContextProgress.repo_url.
        raise CloneError("URL de repo no permitida (solo https de github.com o bitbucket.org)")
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", "--no-tags", "--", repo_url.strip(), str(dest)],
            env=_git_env(repo_url.strip(), provider, token),
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        cleanup(dest)
        raise CloneError(f"git clone tardo mas de {CLONE_TIMEOUT_S}s")
    if proc.returncode != 0:
        cleanup(dest)
        raise CloneError(redact(proc.stderr.strip()[-500:], [token] if token else []))
    return dest


def cleanup(dest: Path) -> None:
    shutil.rmtree(dest, ignore_errors=True)
