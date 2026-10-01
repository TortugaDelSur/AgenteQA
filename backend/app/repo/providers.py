"""APIs de GitHub y Bitbucket: validar un token y listar los repos a los que da acceso.

El usuario elige el repo de esta lista en vez de pegar un link: el backend solo acepta repos que el
propio token ve (ver routers/repo.py::select_repo), asi no entra un link arbitrario o malicioso.
"""

import base64

import httpx

from app.models.schemas import RepoSummary
from app.security import redact

TIMEOUT_S = 20
# ponytail: 3 paginas de 100 = 300 repos, los mas recientes primero; si una cuenta tiene mas,
# agregar busqueda del lado del proveedor.
MAX_PAGES = 3


class ProviderError(Exception):
    pass


def _headers(provider: str, token: str, email: str | None) -> dict[str, str]:
    if provider == "github":
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    if email:  # Bitbucket API token: Basic email:token
        return {"Authorization": "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()}
    return {"Authorization": f"Bearer {token}"}


def _get(client: httpx.Client, url: str, token: str, **params) -> httpx.Response:
    try:
        r = client.get(url, params=params or None)
    except httpx.HTTPError as e:
        raise ProviderError(f"no se pudo contactar al proveedor: {type(e).__name__}") from e
    if r.status_code in (401, 403):
        raise ProviderError("token invalido o sin permiso de lectura de repositorios")
    if r.is_error:
        raise ProviderError(redact(f"el proveedor respondio {r.status_code}: {r.text[:200]}", [token]))
    return r


def _client(provider: str, token: str, email: str | None) -> httpx.Client:
    return httpx.Client(headers=_headers(provider, token, email), timeout=TIMEOUT_S, follow_redirects=False)


def verify(provider: str, token: str, email: str | None = None) -> None:
    """Falla con ProviderError si el token no sirve para listar repos."""
    with _client(provider, token, email) as client:
        if provider == "github":
            _get(client, "https://api.github.com/user", token)
        else:
            _get(client, "https://api.bitbucket.org/2.0/repositories", token, role="member", pagelen=1)


def list_repos(provider: str, token: str, email: str | None = None) -> list[RepoSummary]:
    repos: list[RepoSummary] = []
    with _client(provider, token, email) as client:
        if provider == "github":
            url: str | None = "https://api.github.com/user/repos"
            params = {"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator,organization_member"}
            for _ in range(MAX_PAGES):
                r = _get(client, url, token, **params)
                repos += [
                    RepoSummary(
                        provider="github", full_name=item["full_name"], url=item["html_url"],
                        private=item["private"], description=item.get("description"),
                        updated_at=item.get("pushed_at") or item.get("updated_at"),
                    )
                    for item in r.json()
                ]
                url = r.links.get("next", {}).get("url")
                params = {}
                if not url:
                    break
        else:
            url = "https://api.bitbucket.org/2.0/repositories"
            params = {"role": "member", "pagelen": 100, "sort": "-updated_on"}
            for _ in range(MAX_PAGES):
                data = _get(client, url, token, **params).json()
                repos += [
                    RepoSummary(
                        provider="bitbucket", full_name=item["full_name"],
                        url=item.get("links", {}).get("html", {}).get("href") or f"https://bitbucket.org/{item['full_name']}",
                        private=item["is_private"],
                        description=item.get("description") or None, updated_at=item.get("updated_on"),
                    )
                    for item in data.get("values", [])
                ]
                url, params = data.get("next"), {}
                if not url:
                    break
    return repos
