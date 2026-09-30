"""Tokens de GitHub/Bitbucket por sesion, SOLO en memoria.

Nunca van a SQLite, a logs ni al LLM: se pierden al reiniciar el backend y la UI los vuelve a pedir.
"""

from typing import Literal

PROVIDERS = ("github", "bitbucket")

# ponytail: dict global de un solo proceso; con varios workers cada uno tendria el suyo.
_tokens: dict[tuple[str, str], str] = {}


def set_token(session_id: str, provider: Literal["github", "bitbucket"], token: str) -> None:
    _tokens[(session_id, provider)] = token


def get_token(session_id: str, provider: str) -> str | None:
    return _tokens.get((session_id, provider))


def status(session_id: str) -> dict[str, bool]:
    return {p: (session_id, p) in _tokens for p in PROVIDERS}


def known_secrets(session_id: str) -> list[str]:
    return [t for (sid, _), t in _tokens.items() if sid == session_id]


def forget(session_id: str) -> None:
    for p in PROVIDERS:
        _tokens.pop((session_id, p), None)
