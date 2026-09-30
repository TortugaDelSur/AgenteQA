from fastapi import APIRouter

from app.models.schemas import RepoCredentialsRequest
from app.repo import credentials, workspace

router = APIRouter()


@router.post("/api/repo/credentials")
def post_credentials(req: RepoCredentialsRequest) -> dict[str, bool]:
    # nunca devolver el token: solo si quedo conectado.
    credentials.set_token(req.session_id, req.provider, req.token.strip())
    return credentials.status(req.session_id)


@router.get("/api/repo/status")
def get_status(session_id: str) -> dict[str, bool]:
    return {**credentials.status(session_id), "cloned": workspace.repo_path(session_id) is not None}


@router.delete("/api/repo/{session_id}")
def delete_repo(session_id: str) -> dict[str, str]:
    credentials.forget(session_id)
    workspace.forget(session_id)
    return {"status": "forgotten"}
