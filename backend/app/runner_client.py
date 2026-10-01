"""Cliente HTTP del runner (contrato en runner/README.md). El backend nunca toca Docker.

Los logs vuelven crudos: quien los mande a un prompt los pasa antes por `app.security.redact`.
"""

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict


class _RunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    runner_url: str = "http://127.0.0.1:8100"
    runner_token: str = ""


# levantar un repo incluye build + healthcheck (hasta 180s en el runner)
START_TIMEOUT = 20 * 60


class RunnerError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _client(timeout: float = 60) -> httpx.AsyncClient:
    s = _RunnerSettings()
    return httpx.AsyncClient(
        base_url=s.runner_url, headers={"X-Runner-Token": s.runner_token}, timeout=timeout
    )


async def _call(method: str, path: str, timeout: float = 60, **kwargs) -> dict:
    async with _client(timeout) as client:
        r = await client.request(method, path, **kwargs)
    if r.is_error:
        try:
            detail = r.json()["detail"]
        except (ValueError, KeyError, TypeError):
            detail = r.text
        raise RunnerError(r.status_code, str(detail))
    return r.json()


async def start_run(session_id: str, repo_path: str) -> dict:
    """Devuelve `{"run_id", "urls"}`. RunnerError 422 si no hay compose/Dockerfile, 504 si no responde."""
    return await _call("POST", "/runs", timeout=START_TIMEOUT,
                       json={"session_id": session_id, "repo_path": repo_path})


async def get_logs(run_id: str, tail: int = 200) -> str:
    return (await _call("GET", f"/runs/{run_id}/logs", params={"tail": tail}))["logs"]


async def stop_run(run_id: str) -> None:
    await _call("DELETE", f"/runs/{run_id}")
