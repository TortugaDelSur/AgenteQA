import base64
import subprocess
from pathlib import Path

import pytest

import app.routers.chat as chat_router
from app.models.schemas import ContextProgress, RepoInfo, RepoSummary
from app.repo import clone as clone_mod
from app.repo import credentials, providers, workspace
from app.repo.clone import CloneError, cleanup, clone
from app.repo.inspector import format_repo_summary, inspect_repo

TOKEN = "ghp_" + "A" * 36
URL = "https://github.com/acme/app"


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    credentials._tokens.clear()
    for sid in set(workspace._clones) | set(workspace._failed):
        workspace.forget(sid)


# --- credentials ---

def test_credentials_in_memory_one_per_provider():
    assert credentials.status() == {"github": False, "bitbucket": False}
    credentials.set_token("github", TOKEN)
    assert credentials.get_token("github") == TOKEN
    assert credentials.get_token("bitbucket") is None
    assert credentials.status() == {"github": True, "bitbucket": False}
    assert credentials.known_secrets() == [TOKEN]
    credentials.forget("github")
    assert credentials.status() == {"github": False, "bitbucket": False}


# --- clone ---

class _Run:
    def __init__(self, returncode=0, stderr="", exc=None, make_dir=True):
        self.calls, self.returncode, self.stderr, self.exc, self.make_dir = [], returncode, stderr, exc, make_dir

    def __call__(self, args, env, **kwargs):
        self.calls.append((args, env, kwargs))
        if self.make_dir:
            Path(args[-1]).mkdir(parents=True)
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(args, self.returncode, "", self.stderr)


def test_clone_token_only_in_env_never_in_argv(tmp_path, monkeypatch):
    run = _Run()
    monkeypatch.setattr(clone_mod.subprocess, "run", run)
    dest = clone(URL, tmp_path / "repo", TOKEN)

    assert dest == tmp_path / "repo"
    args, env, kwargs = run.calls[0]
    assert all(TOKEN not in a for a in args)
    assert args[:4] == ["git", "clone", "--depth", "1"] and URL in args
    assert kwargs["timeout"] == clone_mod.CLONE_TIMEOUT_S
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    basic = env["GIT_CONFIG_VALUE_0"].removeprefix("Authorization: Basic ")
    assert base64.b64decode(basic).decode() == f"x-access-token:{TOKEN}"


def test_clone_bitbucket_user_and_no_token(tmp_path, monkeypatch):
    run = _Run()
    monkeypatch.setattr(clone_mod.subprocess, "run", run)
    clone("https://bitbucket.org/acme/app", tmp_path / "a", "tok123456")
    basic = run.calls[0][1]["GIT_CONFIG_VALUE_0"].removeprefix("Authorization: Basic ")
    assert base64.b64decode(basic).decode() == "x-token-auth:tok123456"

    clone(URL, tmp_path / "b", None)
    assert "GIT_CONFIG_VALUE_0" not in run.calls[1][1]


@pytest.mark.parametrize("url", ["https://evil.com/a/b", "http://github.com/a/b", "file:///etc", "https://u:p@github.com/a/b"])
def test_clone_rejects_hosts(tmp_path, url, monkeypatch):
    monkeypatch.setattr(clone_mod.subprocess, "run", _Run())
    with pytest.raises(CloneError):
        clone(url, tmp_path / "r", None)


def test_clone_failure_redacts_token_and_cleans(tmp_path, monkeypatch):
    monkeypatch.setattr(clone_mod.subprocess, "run", _Run(returncode=128, stderr=f"fatal: bad {TOKEN}"))
    with pytest.raises(CloneError) as e:
        clone(URL, tmp_path / "r", TOKEN)
    assert TOKEN not in str(e.value)
    assert not (tmp_path / "r").exists()


def test_clone_timeout_cleans(tmp_path, monkeypatch):
    monkeypatch.setattr(clone_mod.subprocess, "run", _Run(exc=subprocess.TimeoutExpired("git", 1)))
    with pytest.raises(CloneError, match="tardo"):
        clone(URL, tmp_path / "r", None)
    assert not (tmp_path / "r").exists()


def test_cleanup_missing_dir_is_noop(tmp_path):
    cleanup(tmp_path / "nope")


# --- inspector ---

def _write(root, files):
    for name, content in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def test_inspect_compose_repo(tmp_path):
    _write(tmp_path, {
        "package.json": '{"dependencies": {"react": "18", "next": "14"}}',
        "docker-compose.yml": (
            "services:\n"
            "  web:\n    ports: ['127.0.0.1:3000:3000/tcp', '8000-8001:80', 9000]\n"
            "  db:\n    ports: [{target: 5432, published: 5433}, 'abc:1']\n"
            "  worker: {}\n"
        ),
        "Dockerfile": "FROM node\nEXPOSE 1234\n",
        ".env.example": "# c\nexport API_KEY=secret-value\nDB_URL = postgres://x\nAPI_KEY=dup\nnot a var\n",
        "src/server.js": "app.get('/api/users', h)\nrouter.post(\"/api/users\", h)\nnothing",
        "node_modules/x/index.js": "app.get('/hidden', h)",
    })
    info = inspect_repo(tmp_path)
    assert info.framework == "Next.js"
    assert info.has_compose and info.has_dockerfile
    assert info.services == ["web", "db", "worker"]
    assert info.ports == [3000, 8000, 9000, 5433]
    assert info.env_example_keys == ["API_KEY", "DB_URL"]
    assert info.api_routes == ["GET /api/users", "POST /api/users"]


def test_inspect_dockerfile_python_routes(tmp_path):
    _write(tmp_path, {
        "requirements.txt": "Flask==3\n",
        "Dockerfile": "FROM python\nEXPOSE 5000\nexpose 5001\n",
        "app.py": '@app.route("/health")\n@bp.delete("/items/<id>")\n',
        "urls.py": 'urlpatterns = [path("admin/", x), re_path(r"^api/", y)]',
        "Main.java": '@GetMapping("/a")\n@RequestMapping(value = "/b")\n@PostMapping("")',
        "big.py": "x" * 300_000,
    })
    (tmp_path / "link.py").symlink_to(tmp_path / "app.py")
    info = inspect_repo(tmp_path)
    assert info.framework == "Flask"
    assert not info.has_compose and info.has_dockerfile
    assert info.ports == [5000, 5001]
    assert set(info.api_routes) == {
        "ANY /health", "DELETE /items/<id>", "ANY /admin/", "ANY /^api/", "GET /a", "ANY /b", "POST /",
    }


@pytest.mark.parametrize("files,framework", [
    ({"pom.xml": "<artifactId>spring-boot-starter</artifactId>"}, "Spring Boot"),
    ({"Gemfile": "gem 'rails'"}, "Rails"),
    ({"pyproject.toml": "fastapi = '*'"}, "FastAPI"),
    ({"package.json": "[1]"}, None),
    ({"package.json": "{bad"}, None),
    ({}, None),
])
def test_inspect_frameworks(tmp_path, files, framework):
    _write(tmp_path, files)
    assert inspect_repo(tmp_path).framework == framework


@pytest.mark.parametrize("compose", ["services: [\n", "- a\n- b\n", "services: [a, b]\n"])
def test_inspect_broken_compose(tmp_path, compose):
    _write(tmp_path, {"compose.yaml": compose})
    info = inspect_repo(tmp_path)
    assert info.has_compose and info.services == [] and info.ports == []


def test_symlinked_env_example_is_ignored(tmp_path):
    (tmp_path / "real.env").write_text("SECRET=1\n")
    (tmp_path / ".env.example").symlink_to(tmp_path / "real.env")
    assert inspect_repo(tmp_path).env_example_keys == []


def test_route_and_file_caps(tmp_path, monkeypatch):
    import app.repo.inspector as insp
    _write(tmp_path, {f"f{i}.py": f'@app.get("/r{i}")' for i in range(5)})
    monkeypatch.setattr(insp, "MAX_ROUTES", 2)
    assert len(inspect_repo(tmp_path).api_routes) == 2
    monkeypatch.setattr(insp, "MAX_ROUTES", 100)
    monkeypatch.setattr(insp, "MAX_FILES", 3)
    assert len(inspect_repo(tmp_path).api_routes) == 3


def test_format_repo_summary_wrapped_and_redacted():
    info = RepoInfo(framework=None, has_dockerfile=True, api_routes=[f"GET /x?t={TOKEN}"])
    out = format_repo_summary(info)
    assert out.startswith("<<<CONTENIDO_NO_CONFIABLE origen=repo")
    assert TOKEN not in out and "Dockerfile" in out and "desconocido" in out
    empty = format_repo_summary(RepoInfo(has_compose=True, services=["web"], ports=[80], env_example_keys=["A"]))
    assert "docker-compose" in empty and "(no se detectaron)" in empty and "web" in empty
    assert "sin Docker" in format_repo_summary(RepoInfo())


# --- workspace ---

def _fake_clone(calls):
    def fake(url, dest, token):
        calls.append((url, token))
        _write(dest, {"requirements.txt": "django\n"})
        return dest
    return fake


def test_repo_context_clones_once_and_reclones_on_new_url(monkeypatch):
    calls = []
    monkeypatch.setattr(workspace, "clone", _fake_clone(calls))
    credentials.set_token("github", TOKEN)

    out = workspace.repo_context("s", URL)
    assert "Token: conectado" in out and "Django" in out and TOKEN not in out
    first = workspace.repo_path("s")
    assert first.exists()

    workspace.repo_context("s", URL)
    assert calls == [(URL, TOKEN)]

    workspace.repo_context("s", "https://bitbucket.org/acme/other")
    assert calls[-1] == ("https://bitbucket.org/acme/other", None)
    assert not first.exists()

    workspace._cleanup_all()
    assert workspace.repo_path("s") is None


def test_repo_context_clone_failure(monkeypatch):
    attempts = []

    def boom(url, dest, token):
        attempts.append(token)
        raise CloneError("nope")
    monkeypatch.setattr(workspace, "clone", boom)
    out = workspace.repo_context("s", URL)
    assert "No se pudo clonar" in out and "Integraciones" in out and "no conectado" in out
    assert workspace.repo_path("s") is None

    # mismo url + token: no se reintenta en cada turno (cada intento puede bloquear 120s).
    assert "No se pudo clonar" in workspace.repo_context("s", URL)
    assert attempts == [None]

    # token nuevo: si se reintenta.
    credentials.set_token("github", TOKEN)
    assert "Integraciones" not in workspace.repo_context("s", URL)
    assert attempts == [None, TOKEN]


# --- router + chat ---

def test_integrations_router(client, monkeypatch):
    monkeypatch.setattr(providers, "verify", lambda provider, token, email=None: None)
    assert client.get("/api/integrations").json() == {"github": False, "bitbucket": False}

    resp = client.post("/api/integrations", json={"provider": "github", "token": f" {TOKEN} "})
    assert resp.status_code == 200
    assert resp.json() == {"github": True, "bitbucket": False}
    assert TOKEN not in resp.text
    assert credentials.get_token("github") == TOKEN
    assert client.get("/api/integrations").json() == {"github": True, "bitbucket": False}
    assert client.post("/api/integrations", json={"provider": "gitlab", "token": "x"}).status_code == 422
    assert client.post("/api/integrations", json={"provider": "github", "token": ""}).status_code == 422

    assert client.get("/api/repo/status", params={"session_id": "s"}).json() == {
        "github": True, "bitbucket": False, "cloned": False,
    }
    assert client.delete("/api/integrations/github").json() == {"github": False, "bitbucket": False}
    assert client.delete("/api/integrations/gitlab").status_code == 422
    assert client.delete("/api/repo/s").json() == {"status": "forgotten"}


def _repos(*names, provider="github"):
    host = "github.com" if provider == "github" else "bitbucket.org"
    return [RepoSummary(provider=provider, full_name=n, url=f"https://{host}/{n}", private=True) for n in names]


def test_chat_sends_repo_context_and_redacts_known_token(client, monkeypatch):
    calls, seen = [], []
    monkeypatch.setattr(workspace, "clone", _fake_clone(calls))
    monkeypatch.setattr(providers, "list_repos", lambda provider, token, email=None: _repos("acme/app"))
    credentials.set_token("github", "plain-secret-token")
    sid = client.post("/api/repo/select", json={"provider": "github", "full_name": "acme/app"}).json()["session_id"]

    def fake(history, page_snapshot=None):
        seen.extend(history)
        return "ok", ContextProgress(repo=True)
    monkeypatch.setattr(chat_router, "llm_chat", fake)
    client.post("/api/chat", json={"session_id": sid, "message": "mi token es plain-secret-token"})

    assert "plain-secret-token" not in " ".join(m.content for m in seen)
    assert "Django" in seen[-1].content and seen[-1].role == "user"
    assert calls == [(URL, "plain-secret-token")]  # se clono al elegirlo, no otra vez en el chat
    history = client.get(f"/api/chat/{sid}").json()["messages"]
    assert all("plain-secret-token" not in m["content"] and "Django" not in m["content"] for m in history)


# --- selector de repos ---

def test_repos_lists_only_connected_providers_and_reports_errors(client, monkeypatch):
    def fake_list(provider, token, email=None):
        if provider == "bitbucket":
            raise providers.ProviderError("token invalido o sin permiso de lectura de repositorios")
        return _repos("acme/app", "acme/web")

    monkeypatch.setattr(providers, "list_repos", fake_list)
    assert client.get("/api/repos").json() == {"repos": [], "errors": {}}
    credentials.set_token("github", TOKEN)
    credentials.set_token("bitbucket", "bb-token", "yo@acme.com")
    data = client.get("/api/repos").json()
    assert [r["full_name"] for r in data["repos"]] == ["acme/app", "acme/web"]
    assert "bitbucket" in data["errors"] and TOKEN not in str(data)


def test_select_only_accepts_repos_the_token_can_see(client, monkeypatch):
    monkeypatch.setattr(workspace, "clone", _fake_clone([]))
    monkeypatch.setattr(providers, "list_repos", lambda provider, token, email=None: _repos("acme/app"))
    body = {"provider": "github", "full_name": "acme/app"}
    assert client.post("/api/repo/select", json=body).status_code == 409  # sin integracion

    credentials.set_token("github", TOKEN)
    assert client.post("/api/repo/select", json={**body, "full_name": "evil/malware"}).status_code == 404
    data = client.post("/api/repo/select", json=body).json()
    assert data["cloned"] is True and data["repo"]["url"] == URL
    context = client.get(f"/api/chat/{data['session_id']}").json()["context"]
    assert context["repo_url"] == URL and context["repo"] is True

    # elegir otro repo en la misma sesion reemplaza el anterior
    monkeypatch.setattr(providers, "list_repos", lambda provider, token, email=None: _repos("acme/app", "acme/web"))
    again = client.post("/api/repo/select", json={**body, "full_name": "acme/web", "session_id": data["session_id"]}).json()
    assert again["session_id"] == data["session_id"] and again["repo"]["full_name"] == "acme/web"


def test_select_reports_clone_failure(client, monkeypatch):
    def boom(url, dest, token):
        raise CloneError("nope")
    monkeypatch.setattr(workspace, "clone", boom)
    monkeypatch.setattr(providers, "list_repos", lambda provider, token, email=None: _repos("acme/app"))
    credentials.set_token("github", TOKEN)
    data = client.post("/api/repo/select", json={"provider": "github", "full_name": "acme/app"}).json()
    assert data["cloned"] is False and "No se pudo clonar el repositorio" in data["detail"]


def test_provider_outage_is_502(client, monkeypatch):
    def down(provider, token, email=None):
        raise providers.ProviderError("no se pudo contactar al proveedor: ConnectError")
    monkeypatch.setattr(providers, "list_repos", down)
    credentials.set_token("github", TOKEN)
    assert client.post("/api/repo/select", json={"provider": "github", "full_name": "acme/app"}).status_code == 502


def test_chat_ignores_repo_url_from_the_llm(client, monkeypatch):
    # un link pegado en el chat nunca llega a clonarse: el repo solo lo fija el selector.
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("ok", ContextProgress(repo=True, repo_url="https://github.com/evil/malware")),
    )
    data = client.post("/api/chat", json={"message": "https://github.com/evil/malware"}).json()
    assert data["context"]["repo_url"] is None


def test_integration_is_verified_before_saving(client, monkeypatch):
    def bad(provider, token, email=None):
        raise providers.ProviderError("token invalido o sin permiso de lectura de repositorios")
    monkeypatch.setattr(providers, "verify", bad)
    resp = client.post("/api/integrations", json={"provider": "github", "token": TOKEN})
    assert resp.status_code == 422 and TOKEN not in resp.text
    assert credentials.status() == {"github": False, "bitbucket": False}

    seen = {}
    monkeypatch.setattr(providers, "verify", lambda provider, token, email=None: seen.update(email=email))
    client.post("/api/integrations", json={"provider": "bitbucket", "token": "bb", "email": " yo@acme.com "})
    assert seen["email"] == "yo@acme.com" and credentials.get_email("bitbucket") == "yo@acme.com"
