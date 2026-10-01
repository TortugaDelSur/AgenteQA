"""Tests del runner. Los de integracion levantan contenedores reales (nginx:alpine) y se
saltean si no hay Docker."""

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as runner

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "t0ken-de-test"
HEADERS = {"X-Runner-Token": TOKEN}

has_docker = shutil.which("docker") and subprocess.run(
    ["docker", "info"], capture_output=True
).returncode == 0
needs_docker = pytest.mark.skipif(not has_docker, reason="sin Docker")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("RUNNER_TOKEN", TOKEN)
    monkeypatch.setenv("RUNNER_HEALTH_TIMEOUT", "60")
    return TestClient(runner.app)


def test_rejects_missing_or_wrong_token(client, monkeypatch):
    assert client.get("/runs/aqa-x/logs").status_code == 401
    assert client.delete("/runs/aqa-x", headers={"X-Runner-Token": "otro"}).status_code == 401
    monkeypatch.setenv("RUNNER_TOKEN", "")
    assert client.delete("/runs/aqa-x", headers={"X-Runner-Token": ""}).status_code == 401


def test_422_without_compose_or_dockerfile(client, tmp_path):
    r = client.post("/runs", json={"session_id": "s1", "repo_path": str(tmp_path)}, headers=HEADERS)
    assert r.status_code == 422
    assert r.json() == {"detail": "sin docker-compose.yml ni Dockerfile"}


def test_rejects_bad_session_and_run_id(client, tmp_path):
    r = client.post("/runs", json={"session_id": "../x", "repo_path": str(tmp_path)}, headers=HEADERS)
    assert r.status_code == 422
    assert client.delete("/runs/--help", headers=HEADERS).status_code == 404


@needs_docker
def test_logs_of_unknown_run_is_404(client):
    assert client.get("/runs/aqa-no-existe-xyz/logs", headers=HEADERS).status_code == 404


def test_dummy_env_never_keeps_real_values(tmp_path):
    (tmp_path / ".env.example").write_text("# c\nexport A=\nB=3000\nnada\n")
    (tmp_path / ".env").write_text("A=real\n")
    (tmp_path / ".env.production").write_text("A=real-prod\n")
    runner._write_env_files(tmp_path)
    assert (tmp_path / ".env").read_text() == "A=dummy\nB=3000\n"
    assert (tmp_path / ".env.production").read_text() == "A=dummy\nB=3000\n"
    assert (tmp_path / ".env.example").read_text().startswith("# c")


def test_harden_limits_ports_and_host_access(tmp_path):
    config = {
        "name": "fijo",
        "networks": {"default": {"name": "fijo_default"}},
        "services": {"web": {
            "privileged": True,
            "cap_add": ["SYS_ADMIN"],
            "network_mode": "host",
            "deploy": {"resources": {"limits": {"memory": "8g"}}},
            "ports": [{"target": 80, "published": "8080", "protocol": "tcp"}],
            "volumes": [
                {"type": "bind", "source": "/var/run/docker.sock", "target": "/s"},
                {"type": "bind", "source": str(tmp_path / "src"), "target": "/src"},
                {"type": "volume", "source": "data", "target": "/data"},
            ],
        }},
    }
    svc = runner.harden(config, tmp_path)["services"]["web"]
    assert "name" not in config and "name" not in config["networks"]["default"]
    assert svc["privileged"] is False and svc["security_opt"] == ["no-new-privileges:true"]
    assert svc["mem_limit"] and svc["pids_limit"] and svc["cpus"]
    assert not {"cap_add", "network_mode", "deploy"} & svc.keys()
    assert svc["ports"] == [{"target": 80, "host_ip": "127.0.0.1", "protocol": "tcp"}]
    assert [v["target"] for v in svc["volumes"]] == ["/src", "/data"]


def test_harden_rejects_host_files_via_configs_secrets_and_build(tmp_path):
    for bad in (
        {"configs": {"c": {"file": "/etc/hostname"}}, "services": {}},
        {"secrets": {"s": {"file": "/etc/passwd"}}, "services": {}},
        {"services": {"web": {"build": {"context": str(tmp_path.parent)}}}},
    ):
        with pytest.raises(HTTPException) as err:
            runner.harden(bad, tmp_path)
        assert err.value.status_code == 422


def test_harden_neutralizes_volume_binds_and_extra_build_contexts(tmp_path):
    (tmp_path / "s.txt").write_text("x")
    config = {
        "secrets": {"ok": {"file": str(tmp_path / "s.txt")}},
        "volumes": {"v": {"name": "fijo", "external": True,
                          "driver_opts": {"type": "none", "o": "bind", "device": "/home"}}},
        "services": {"web": {"build": {"context": str(tmp_path), "additional_contexts": {"x": "/etc"}}}},
    }
    out = runner.harden(config, tmp_path)
    assert out["volumes"] == {"v": {}}
    assert "additional_contexts" not in out["services"]["web"]["build"]


def test_dockerfile_expose_parsing(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM x\nEXPOSE 3000/tcp 8080\nexpose 53/udp\n")
    assert runner._dockerfile_ports(tmp_path / "Dockerfile") == [3000, 8080]


def _containers(run_id: str) -> list[dict]:
    out = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={run_id}"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    if not out:
        return []
    return json.loads(subprocess.run(["docker", "inspect", *out], capture_output=True,
                                     text=True, check=True).stdout)


def _up_check_down(client, repo: Path, session_id: str) -> dict:
    r = client.post("/runs", json={"session_id": session_id, "repo_path": str(repo)},
                    headers=HEADERS)
    run_id = f"aqa-{session_id}"
    try:
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"] == run_id
        [url] = body["urls"]
        assert url.startswith("http://127.0.0.1:")
        assert "nginx" in httpx.get(url).text.lower()

        [c] = _containers(run_id)
        host = c["HostConfig"]
        assert host["Privileged"] is False
        assert "no-new-privileges:true" in host["SecurityOpt"]
        assert host["Memory"] > 0 and host["PidsLimit"] > 0
        assert {b["HostIp"] for bs in host["PortBindings"].values() for b in bs} == {"127.0.0.1"}

        logs = client.get(f"/runs/{run_id}/logs?tail=50", headers=HEADERS).json()["logs"]
        assert "GET / HTTP" in logs
        return c
    finally:
        assert client.delete(f"/runs/{run_id}", headers=HEADERS).json() == {"status": "stopped"}
        assert _containers(run_id) == []


@needs_docker
def test_compose_nginx_up_responds_logs_and_destroyed(client, tmp_path):
    repo = shutil.copytree(FIXTURES / "nginx-compose", tmp_path / "repo")
    (repo / ".env").write_text("APP_SECRET=secreto-real-no-usar\nAPP_MODE=prod\n")
    c = _up_check_down(client, repo, "test-compose")
    env = c["Config"]["Env"]
    assert "APP_SECRET=dummy" in env and "APP_MODE=demo" in env
    assert not any("secreto-real" in e for e in env)


@needs_docker
def test_dockerfile_only_builds_and_runs_with_same_limits(client, tmp_path):
    repo = shutil.copytree(FIXTURES / "nginx-dockerfile", tmp_path / "repo")
    _up_check_down(client, repo, "test-dockerfile")
