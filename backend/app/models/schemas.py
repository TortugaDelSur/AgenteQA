from typing import Literal

from pydantic import BaseModel, Field


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

    @property
    def ready_for_plan(self) -> bool:
        return self.objetivo and self.acceso and self.alcance


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
    id: str
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


# --- Resultados de ejecucion (contrato compartido con Persona B) ---

class TestResult(BaseModel):
    test_case_id: str
    status: Literal["pass", "fail", "error"]
    detail: str
    evidence: str | None = None


class ExecutionResponse(BaseModel):
    session_id: str
    results: list[TestResult]
