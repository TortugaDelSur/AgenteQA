"""Tokens de GitHub/Bitbucket de la instalacion (uno por proveedor), SOLO en memoria.

Se cargan en la pantalla Integraciones antes de chatear. Nunca van a SQLite, a logs ni al LLM: se
pierden al reiniciar el backend y la UI los vuelve a pedir. ponytail: un token por proveedor para
toda la instalacion (AgenteQA es local y de un usuario); con multiusuario pasa a ser por usuario.
"""

from typing import Literal

PROVIDERS = ("github", "bitbucket")

# ponytail: dict global de un solo proceso; con varios workers cada uno tendria el suyo.
_tokens: dict[str, str] = {}


def set_token(provider: Literal["github", "bitbucket"], token: str) -> None:
    _tokens[provider] = token


def get_token(provider: str) -> str | None:
    return _tokens.get(provider)


def status() -> dict[str, bool]:
    return {p: p in _tokens for p in PROVIDERS}


def known_secrets() -> list[str]:
    return list(_tokens.values())


def forget(provider: str) -> None:
    _tokens.pop(provider, None)
