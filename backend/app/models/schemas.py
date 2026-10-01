from typing import Literal
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field, model_validator

MAX_EXTRA_URLS = 8

REPO_HOSTS = {"github.com": "github", "bitbucket.org": "bitbucket"}


def repo_provider(repo_url: str) -> Literal["github", "bitbucket"] | None:
    """Proveedor del repo si la URL es https a un host permitido y sin user:pass@; si no, None."""
    parsed = urlparse(repo_url.strip())
    try:
        has_port = parsed.port is not None
    except ValueError:  # puerto no numerico ("host:abc")
        return None
    owner_and_repo = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https" or parsed.username or parsed.password or has_port or len(owner_and_repo) < 2:
        return None
    return REPO_HOSTS.get((parsed.hostname or "").lower())  # type: ignore[return-value]


class ContextProgress(BaseModel):
    objetivo: bool = False
    acceso: bool = False
    alcance: bool = False
    repo: bool = False
    target_url: str | None = None
    # credenciales de prueba (no reales) para poder loguearse durante la inspeccion de pagina.
    username: str | None = None
    password: str | None = None
    # paginas extra mencionadas por el usuario en el alcance (post-login), si dio URLs concretas.
    extra_urls: list[str] = []
    # repo de la empresa a clonar/levantar. Solo hosts de REPO_HOSTS (filtro duro abajo).
    repo_url: str | None = None
    # el usuario dijo que tiene repositorio: el front muestra el aviso de integracion o la lista de
    # repos hasta que elija uno (POST /api/repo/select). "repo" queda en false hasta entonces.
    wants_repo: bool = False

    @property
    def ready_for_plan(self) -> bool:
        # "repo" tambien bloquea (aunque el usuario no tenga uno, igual hay que preguntarle):
        # si no bloqueara, el front puede disparar el plan en el mismo turno en que el chat
        # todavia esta preguntando por el repo, cortandole la respuesta al usuario.
        return self.objetivo and self.acceso and self.alcance and self.repo and (
            not self.wants_repo or bool(self.repo_url)
        )

    @model_validator(mode="after")
    def _sanitize_extra_urls(self) -> "ContextProgress":
        """El LLM a veces vuelca TODOS los links de navegacion que ve en vez de solo los que el
        usuario confirmo (probado en vivo: 44 urls, incluyendo rutas relativas rotas y dominios
        externos tipo github.com). Filtro duro: solo mismo dominio que target_url, resuelve rutas
        relativas contra esa URL, y limita la cantidad — no depende de que el prompt se porte bien.
        """
        if not self.target_url or not self.extra_urls:
            self.extra_urls = []
            return self

        target_host = urlparse(self.target_url).netloc
        sanitized: list[str] = []
        for url in self.extra_urls:
            resolved = urljoin(self.target_url, url)
            if urlparse(resolved).netloc == target_host and resolved not in sanitized:
                sanitized.append(resolved)
            if len(sanitized) >= MAX_EXTRA_URLS:
                break
        self.extra_urls = sanitized
        return self

    @model_validator(mode="after")
    def _sanitize_repo_url(self) -> "ContextProgress":
        """Filtro duro: solo https a GitHub/Bitbucket, sin credenciales embebidas. El clone usa
        esta URL tal cual; aceptar cualquier host seria un SSRF (clonar desde la red interna)."""
        if self.repo_url is not None and repo_provider(self.repo_url) is None:
            self.repo_url = None
        return self


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    context: ContextProgress
    ready_for_plan: bool


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    context: ContextProgress
    ready_for_plan: bool


# --- Test plan (contrato compartido con Persona B) ---

class UiStep(BaseModel):
    action: Literal["goto", "click", "fill", "assert_text", "assert_visible"]
    url: str | None = None
    selector: str | None = None
    value: str | None = None
    expected: str | None = None


class HttpRequestSpec(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    url: str
    headers: dict[str, str] = {}
    body: dict | None = None


class TestCase(BaseModel):
    # sin caracteres de path traversal: el id se usa para nombrar el screenshot en disco
    # (backend/screenshots/{session_id}/{id}.png), un id malicioso podria escribir fuera de esa carpeta.
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=50)
    type: Literal["ui", "endpoint"]
    title: str
    steps: list[UiStep] | None = None
    request: HttpRequestSpec | None = None
    expected_status: int | None = None
    expected_body_contains: str | None = None


class TestPlan(BaseModel):
    test_cases: list[TestCase]


class PlanRequest(BaseModel):
    session_id: str


class SweepAnswerRequest(BaseModel):
    session_id: str
    answer: str = Field(min_length=1, max_length=4000)


class SweepLoginRequest(BaseModel):
    session_id: str
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


# --- Repo de la empresa (ver TRABAJO-PARALELO.md, contratos congelados) ---

class RepoInfo(BaseModel):
    framework: str | None = None
    has_compose: bool = False
    has_dockerfile: bool = False
    services: list[str] = []
    ports: list[int] = []
    # solo los NOMBRES de las variables de .env.example, nunca valores.
    env_example_keys: list[str] = []
    api_routes: list[str] = []


class IntegrationRequest(BaseModel):
    provider: Literal["github", "bitbucket"]
    token: str = Field(min_length=1, max_length=500)
    # solo Bitbucket: email de la cuenta Atlassian para Basic auth del API token (sin el, Bearer).
    email: str | None = Field(default=None, max_length=200)


class RepoSummary(BaseModel):
    provider: Literal["github", "bitbucket"]
    full_name: str
    url: str
    private: bool
    description: str | None = None
    updated_at: str | None = None


class RepoSelectRequest(BaseModel):
    session_id: str | None = None
    provider: Literal["github", "bitbucket"]
    full_name: str = Field(min_length=3, max_length=200)


class SuspectedCause(BaseModel):
    file: str
    line: int | None = None
    explanation: str
    confidence: Literal["alta", "media", "baja"]


# --- Resultados de ejecucion (contrato compartido con Persona B) ---

class TestResult(BaseModel):
    test_case_id: str
    status: Literal["pass", "fail", "error"]
    detail: str
    evidence: str | None = None
    # captura en memoria del estado final de la pantalla (solo tests "ui"), para que el front
    # la muestre en vivo mientras ejecuta. No se persiste en DB (execute.py arma el Result
    # campo por campo, este no esta entre ellos) — es solo para la corrida en curso.
    screenshot_b64: str | None = None
    # solo si hay repo levantado y el test fallo: donde esta probablemente el problema.
    suspected_cause: SuspectedCause | None = None


class ExecutionResponse(BaseModel):
    session_id: str
    results: list[TestResult]
