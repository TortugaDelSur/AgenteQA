import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from app.models.db import Session, get_db
from app.models.schemas import ContextProgress, IntegrationRequest, RepoSelectRequest
from app.repo import credentials, providers, workspace

router = APIRouter()


@router.get("/api/integrations")
def get_integrations() -> dict[str, bool]:
    return credentials.status()


@router.post("/api/integrations")
def post_integration(req: IntegrationRequest) -> dict[str, bool]:
    token = req.token.strip()
    email = (req.email or "").strip() or None
    # se valida contra el proveedor antes de guardarlo: un token que no lista repos no sirve.
    try:
        providers.verify(req.provider, token, email)
    except providers.ProviderError as e:
        raise HTTPException(status_code=422, detail=str(e))
    credentials.set_token(req.provider, token, email)  # nunca se devuelve: solo el estado
    return credentials.status()


@router.delete("/api/integrations/{provider}")
def delete_integration(provider: Literal["github", "bitbucket"]) -> dict[str, bool]:
    credentials.forget(provider)
    return credentials.status()


def _accessible(provider: str) -> list:
    token = credentials.get_token(provider)
    if token is None:
        raise HTTPException(status_code=409, detail=f"{provider} no esta conectado en Integraciones")
    try:
        return providers.list_repos(provider, token, credentials.get_email(provider))
    except providers.ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/repos")
def get_repos() -> dict:
    """Repos a los que dan acceso los tokens conectados; el usuario elige de aca (no pega links)."""
    repos, errors = [], {}
    for provider, connected in credentials.status().items():
        if not connected:
            continue
        try:
            repos += [r.model_dump() for r in _accessible(provider)]
        except HTTPException as e:
            errors[provider] = e.detail
    return {"repos": repos, "errors": errors}


@router.post("/api/repo/select")
def select_repo(req: RepoSelectRequest, db: OrmSession = Depends(get_db)) -> dict:
    # solo un repo que el token realmente ve: nunca una URL armada o pegada por el usuario.
    repo = next((r for r in _accessible(req.provider) if r.full_name == req.full_name), None)
    if repo is None:
        raise HTTPException(status_code=404, detail="ese repositorio no esta entre los que tu token puede ver")

    session = db.get(Session, req.session_id) if req.session_id else None
    if session is None:
        session = Session(id=str(uuid.uuid4()), context_json=ContextProgress().model_dump_json())
        db.add(session)
    context = ContextProgress(**json.loads(session.context_json))
    context.repo_url = repo.url
    context.repo = True
    session.context_json = ContextProgress(**context.model_dump()).model_dump_json()  # revalida repo_url
    db.commit()

    workspace.repo_context(session.id, repo.url)  # clona ahora: el error se ve al elegir, no en el chat
    cloned = workspace.repo_path(session.id) is not None
    return {
        "session_id": session.id,
        "repo": repo.model_dump(),
        "cloned": cloned,
        "detail": None if cloned else (
            "No se pudo clonar el repositorio. Revisa que el token tenga permiso de lectura del contenido "
            "(GitHub: Contents read-only; Bitbucket: read:repository)."
        ),
    }


@router.get("/api/repo/status")
def get_status(session_id: str) -> dict[str, bool]:
    return {**credentials.status(), "cloned": workspace.repo_path(session_id) is not None}


@router.delete("/api/repo/{session_id}")
def delete_repo(session_id: str) -> dict[str, str]:
    workspace.forget(session_id)
    return {"status": "forgotten"}
