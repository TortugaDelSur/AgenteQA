"""Runner: levanta el repo de la empresa en contenedores desechables (contrato en README.md).

Es el unico proceso que toca Docker. Cada run es un proyecto compose `aqa-<session_id>`
generado aca: se normaliza el compose del repo con `docker compose config`, se le aplican
los limites y se escribe a un archivo propio, asi el repo nunca decide privilegios ni puertos.
"""

import hmac
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
ENV_EXAMPLES = (".env.example", ".env.sample", ".env.template", ".env.dist")
# ponytail: limites fijos por servicio; si una app real no entra en 1g, volverlos env vars.
LIMITS = {
    "mem_limit": "1g",
    "cpus": 1.0,
    "pids_limit": 256,
    "security_opt": ["no-new-privileges:true"],
    "privileged": False,
}
RUNS_DIR = Path(tempfile.gettempdir()) / "aqa-runner"
RUN_ID = re.compile(r"^aqa-[a-z0-9_-]{1,64}$")

app = FastAPI(title="AgenteQA runner")


def _check_token(x_runner_token: str = Header(default="")) -> None:
    expected = os.environ.get("RUNNER_TOKEN", "")
    # sin RUNNER_TOKEN configurado se rechaza todo: nunca queda abierto por olvido
    if not expected or not hmac.compare_digest(x_runner_token, expected):
        raise HTTPException(401, "token invalido")


class RunRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    repo_path: str


def _docker(*args: str, timeout: int = 600) -> str:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[-2000:])
    return proc.stdout


def _dummy_env(repo: Path) -> str:
    """Contenido del `.env` generado: claves de `.env.example`, sin valores que no esten ahi."""
    example = next((repo / n for n in ENV_EXAMPLES if (repo / n).is_file()), None)
    lines = []
    for raw in example.read_text(errors="replace").splitlines() if example else []:
        line = raw.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # ponytail: el valor de ejemplo ya es publico en el repo y suele ser estructural
        # (puertos, hosts); solo se rellena lo vacio.
        lines.append(f"{key.strip()}={value.strip() or 'dummy'}")
    return "\n".join(lines) + "\n"


def _write_env_files(repo: Path) -> None:
    """Pisa todo `.env*` del repo (menos los ejemplos) con el dummy: nunca se usa uno real."""
    content = _dummy_env(repo)
    # ponytail: solo la raiz del repo; un env_file en subcarpetas se leeria tal cual.
    for f in repo.glob(".env*"):
        if f.is_file() and f.name not in ENV_EXAMPLES:
            f.write_text(content)
    (repo / ".env").write_text(content)


def _dockerfile_ports(dockerfile: Path) -> list[int]:
    ports = []
    for m in re.finditer(r"(?im)^\s*EXPOSE\s+(.+)$", dockerfile.read_text(errors="replace")):
        ports += [int(p) for p in re.findall(r"(?<!\S)(\d+)(?:/tcp)?(?!\S)", m.group(1))]
    return ports


def _load_config(repo: Path, run_id: str) -> dict:
    compose = next((repo / n for n in COMPOSE_FILES if (repo / n).is_file()), None)
    if compose:
        out = _docker(
            "compose", "-p", run_id, "-f", str(compose), "--env-file", str(repo / ".env"),
            "config", "--format", "json", timeout=60,
        )
        return json.loads(out)
    if (repo / "Dockerfile").is_file():
        # Dockerfile solo: se envuelve en un compose de un servicio, asi build + run pasa por
        # el mismo endurecimiento que un compose del repo.
        ports = _dockerfile_ports(repo / "Dockerfile")
        if not ports:
            raise HTTPException(422, "el Dockerfile no declara EXPOSE")
        return {"services": {"app": {
            "build": {"context": str(repo)},
            "env_file": [str(repo / ".env")],
            "ports": [{"target": p} for p in ports],
        }}}
    raise HTTPException(422, "sin docker-compose.yml ni Dockerfile")


def harden(config: dict, repo: Path) -> dict:
    """Aplica limites y cierra las salidas del compose del repo hacia el host."""
    config.pop("name", None)  # el nombre lo pone `-p run_id`
    for net in config.get("networks", {}).values():
        if isinstance(net, dict):
            net.pop("name", None)  # un nombre fijo compartiria la red entre runs
    for svc in config.get("services", {}).values():
        svc.update(LIMITS)
        # deploy.resources chocaria con mem_limit/cpus
        for key in ("cap_add", "devices", "pid", "ipc", "userns_mode", "container_name", "deploy"):
            svc.pop(key, None)
        if (svc.get("network_mode") or "").startswith(("host", "container:", "service:")):
            svc.pop("network_mode")
        # bind mounts solo dentro del repo: nada de docker.sock ni rutas del host
        svc["volumes"] = [
            v for v in svc.get("volumes", [])
            if v.get("type") != "bind" or Path(v.get("source", "/")).resolve().is_relative_to(repo)
        ]
        # puerto de host al azar y solo en loopback: sin choques entre runs ni exposicion a la red
        svc["ports"] = [
            {"target": p["target"], "host_ip": "127.0.0.1", "protocol": p.get("protocol", "tcp")}
            for p in svc.get("ports", [])
        ]
    return config


def _published_ports(run_id: str, config: dict) -> list[int]:
    ports = []
    for name, svc in config["services"].items():
        for p in svc["ports"]:
            if p["protocol"] != "tcp":
                continue
            out = _docker("compose", "-p", run_id, "port", name, str(p["target"]), timeout=30)
            ports.append(int(out.strip().rsplit(":", 1)[1]))
    return ports


def wait_for_web(ports: list[int], timeout: float, grace: float = 10.0) -> list[str]:
    """Devuelve las URLs de los puertos que responden HTTP (cualquier status).

    Un puerto que no es web (postgres, redis) nunca responde; por eso, apenas aparece el primero
    web se esperan solo `grace` segundos mas a los otros en vez de agotar el timeout.
    """
    urls: dict[int, str] = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for port in ports:
            if port in urls:
                continue
            url = f"http://127.0.0.1:{port}"
            try:
                httpx.get(url, timeout=2)
                urls[port] = url
            except httpx.HTTPError:
                pass
        if len(urls) == len(ports):
            break
        if urls:
            deadline = min(deadline, time.monotonic() + grace)
        time.sleep(1)
    return [urls[p] for p in ports if p in urls]


def _down(run_id: str) -> None:
    _docker("compose", "-p", run_id, "down", "-v", "--rmi", "local", "--remove-orphans")
    (RUNS_DIR / f"{run_id}.json").unlink(missing_ok=True)


def _valid_run_id(run_id: str) -> str:
    if not RUN_ID.match(run_id):
        raise HTTPException(404, "run inexistente")
    return run_id


@app.post("/runs", dependencies=[Depends(_check_token)])
def start_run(req: RunRequest) -> dict:
    repo = Path(req.repo_path).resolve()
    if not repo.is_dir():
        raise HTTPException(422, "repo_path no existe")
    run_id = f"aqa-{req.session_id.lower()}"
    _write_env_files(repo)
    try:
        config = harden(_load_config(repo, run_id), repo)
    except RuntimeError as e:
        raise HTTPException(422, f"compose invalido: {e}")
    RUNS_DIR.mkdir(exist_ok=True)
    compose_file = RUNS_DIR / f"{run_id}.json"
    compose_file.write_text(json.dumps(config))

    timeout = int(os.environ.get("RUNNER_HEALTH_TIMEOUT", "180"))
    try:
        _docker("compose", "-p", run_id, "-f", str(compose_file), "up", "-d", "--build",
                timeout=900)
        urls = wait_for_web(_published_ports(run_id, config), timeout)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        _down(run_id)
        raise HTTPException(422, f"no se pudo levantar: {e}")
    if not urls:
        _down(run_id)
        raise HTTPException(504, f"la app no respondio en {timeout}s")
    return {"run_id": run_id, "urls": urls}


@app.get("/runs/{run_id}/logs", dependencies=[Depends(_check_token)])
def run_logs(run_id: str, tail: int = 200) -> dict:
    out = _docker("compose", "-p", _valid_run_id(run_id), "logs", "--no-color",
                  "--tail", str(max(1, min(tail, 5000))), timeout=60)
    return {"logs": out}


@app.delete("/runs/{run_id}", dependencies=[Depends(_check_token)])
def stop_run(run_id: str) -> dict:
    _down(_valid_run_id(run_id))
    return {"status": "stopped"}
