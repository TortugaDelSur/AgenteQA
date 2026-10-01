from typing import Literal

from fastapi import APIRouter

from app.models.schemas import IntegrationRequest
from app.repo import credentials, workspace

router = APIRouter()


@router.get("/api/integrations")
def get_integrations() -> dict[str, bool]:
    return credentials.status()


@router.post("/api/integrations")
def post_integration(req: IntegrationRequest) -> dict[str, bool]:
    # nunca devolver el token: solo que quedo conectado.
    credentials.set_token(req.provider, req.token.strip())
    return credentials.status()


@router.delete("/api/integrations/{provider}")
def delete_integration(provider: Literal["github", "bitbucket"]) -> dict[str, bool]:
    credentials.forget(provider)
    return credentials.status()


@router.get("/api/repo/status")
def get_status(session_id: str) -> dict[str, bool]:
    return {**credentials.status(), "cloned": workspace.repo_path(session_id) is not None}


@router.delete("/api/repo/{session_id}")
def delete_repo(session_id: str) -> dict[str, str]:
    workspace.forget(session_id)
    return {"status": "forgotten"}
