import httpx
import pytest

from app import runner_client


@pytest.fixture
def fake_runner(monkeypatch):
    monkeypatch.setenv("RUNNER_TOKEN", "tok")
    monkeypatch.setenv("RUNNER_URL", "http://runner.test")
    seen = []
    responses = {}
    real_client = runner_client._client

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = responses[(request.method, request.url.path)]
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    def client(timeout=60):
        c = real_client(timeout)
        c._transport = httpx.MockTransport(handler)
        return c

    monkeypatch.setattr(runner_client, "_client", client)
    return seen, responses


async def test_start_logs_stop_follow_contract(fake_runner):
    seen, responses = fake_runner
    responses[("POST", "/runs")] = (200, {"run_id": "aqa-s1", "urls": ["http://127.0.0.1:18080"]})
    responses[("GET", "/runs/aqa-s1/logs")] = (200, {"logs": "web | ok"})
    responses[("DELETE", "/runs/aqa-s1")] = (200, {"status": "stopped"})

    run = await runner_client.start_run("s1", "/tmp/repo")
    assert run == {"run_id": "aqa-s1", "urls": ["http://127.0.0.1:18080"]}
    assert await runner_client.get_logs("aqa-s1", tail=50) == "web | ok"
    assert await runner_client.stop_run("aqa-s1") is None

    assert all(r.headers["X-Runner-Token"] == "tok" and r.url.host == "runner.test" for r in seen)
    assert seen[0].read() == b'{"session_id":"s1","repo_path":"/tmp/repo"}'
    assert seen[1].url.params["tail"] == "50"


async def test_error_carries_status_and_detail(fake_runner):
    _, responses = fake_runner
    responses[("POST", "/runs")] = (422, {"detail": "sin docker-compose.yml ni Dockerfile"})
    with pytest.raises(runner_client.RunnerError) as e:
        await runner_client.start_run("s1", "/tmp/repo")
    assert (e.value.status, e.value.detail) == (422, "sin docker-compose.yml ni Dockerfile")

    responses[("DELETE", "/runs/aqa-s1")] = (500, "Internal Server Error")
    with pytest.raises(runner_client.RunnerError, match="Internal Server Error"):
        await runner_client.stop_run("aqa-s1")
