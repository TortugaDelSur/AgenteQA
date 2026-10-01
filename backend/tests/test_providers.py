import base64

import httpx
import pytest

from app.repo import providers

TOKEN = "ghp_" + "B" * 36


@pytest.fixture
def fake_api(monkeypatch):
    seen, routes = [], {}
    real = providers._client

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body, headers = routes[(request.url.host, request.url.path, request.url.params.get("page", "1"))]
        return httpx.Response(status, json=body, headers=headers)

    def client(provider, token, email):
        c = real(provider, token, email)
        c._transport = httpx.MockTransport(handler)
        return c

    monkeypatch.setattr(providers, "_client", client)
    return seen, routes


def test_github_lists_all_pages_and_sends_bearer(fake_api):
    seen, routes = fake_api
    repo = lambda n, priv: {"full_name": n, "html_url": f"https://github.com/{n}", "private": priv,
                            "description": None, "pushed_at": "2026-09-30T10:00:00Z"}
    routes[("api.github.com", "/user/repos", "1")] = (
        200, [repo("me/a", True)], {"link": '<https://api.github.com/user/repos?page=2>; rel="next"'},
    )
    routes[("api.github.com", "/user/repos", "2")] = (200, [repo("org/b", False)], {})

    repos = providers.list_repos("github", TOKEN)

    assert [(r.full_name, r.private, r.url) for r in repos] == [
        ("me/a", True, "https://github.com/me/a"), ("org/b", False, "https://github.com/org/b"),
    ]
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert seen[0].url.params["affiliation"] == "owner,collaborator,organization_member"


def test_bitbucket_basic_with_email_and_next_page(fake_api):
    seen, routes = fake_api
    item = lambda n: {"full_name": n, "is_private": True, "description": "", "updated_on": "2026-09-30",
                      "links": {"html": {"href": f"https://bitbucket.org/{n}"}}}
    routes[("api.bitbucket.org", "/2.0/repositories", "1")] = (
        200, {"values": [item("ws/a")], "next": "https://api.bitbucket.org/2.0/repositories?page=2"}, {},
    )
    routes[("api.bitbucket.org", "/2.0/repositories", "2")] = (200, {"values": [item("ws/b")]}, {})

    repos = providers.list_repos("bitbucket", "bb-token", "yo@acme.com")

    assert [r.url for r in repos] == ["https://bitbucket.org/ws/a", "https://bitbucket.org/ws/b"]
    assert repos[0].description is None
    expected = base64.b64encode(b"yo@acme.com:bb-token").decode()
    assert seen[0].headers["authorization"] == f"Basic {expected}"
    assert seen[0].url.params["role"] == "member"


def test_bitbucket_without_email_uses_bearer(fake_api):
    seen, routes = fake_api
    routes[("api.bitbucket.org", "/2.0/repositories", "1")] = (200, {"values": []}, {})
    providers.verify("bitbucket", "bb-token")
    assert seen[0].headers["authorization"] == "Bearer bb-token"


@pytest.mark.parametrize("status", [401, 403])
def test_bad_token_is_a_clear_error(fake_api, status):
    _, routes = fake_api
    routes[("api.github.com", "/user", "1")] = (status, {"message": "Bad credentials"}, {})
    with pytest.raises(providers.ProviderError, match="token invalido"):
        providers.verify("github", TOKEN)


def test_other_errors_are_redacted(fake_api):
    _, routes = fake_api
    routes[("api.github.com", "/user", "1")] = (500, {"echo": TOKEN}, {})
    with pytest.raises(providers.ProviderError) as err:
        providers.verify("github", TOKEN)
    assert TOKEN not in str(err.value) and "500" in str(err.value)


def test_network_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("sin red")
    real = providers._client

    def client(provider, token, email):
        c = real(provider, token, email)
        c._transport = httpx.MockTransport(handler)
        return c
    monkeypatch.setattr(providers, "_client", client)
    with pytest.raises(providers.ProviderError, match="no se pudo contactar"):
        providers.list_repos("github", TOKEN)
