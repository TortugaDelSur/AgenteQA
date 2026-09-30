"""Lectura estatica del repo clonado: framework, como se levanta y rutas de la API.

El contenido del repo es ajeno: solo se extraen nombres (nunca valores de `.env.example`) y el
resumen para el LLM sale por `redact` + `wrap_untrusted`.
"""

import json
import os
import re
from pathlib import Path

import yaml

from app.models.schemas import RepoInfo
from app.security import redact, wrap_untrusted

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
MAX_FILE_BYTES = 200_000
MAX_FILES = 5000
MAX_ROUTES = 100
_SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", "target", "vendor", "__pycache__"}
_SOURCE_EXT = {".py", ".js", ".ts", ".mjs", ".cjs", ".java", ".kt", ".rb", ".php", ".go"}

# (dependencia, framework). Orden = prioridad: el primero que aparezca gana.
_JS_FRAMEWORKS = [
    ("next", "Next.js"), ("nuxt", "Nuxt"), ("@nestjs/core", "NestJS"), ("@angular/core", "Angular"),
    ("@sveltejs/kit", "SvelteKit"), ("svelte", "Svelte"), ("vue", "Vue"), ("react", "React"),
    ("express", "Express"), ("fastify", "Fastify"), ("koa", "Koa"),
]
_PY_FRAMEWORKS = [("django", "Django"), ("fastapi", "FastAPI"), ("flask", "Flask")]
_OTHER_FRAMEWORKS = [
    ("pom.xml", "spring-boot", "Spring Boot"), ("build.gradle", "spring-boot", "Spring Boot"),
    ("build.gradle.kts", "spring-boot", "Spring Boot"), ("Gemfile", "rails", "Rails"),
    ("composer.json", "laravel/framework", "Laravel"), ("go.mod", "gin-gonic/gin", "Gin"),
]

_ROUTE_PATTERNS = [
    # FastAPI / Flask / Express / Koa: @app.get("/x"), router.post('/x', ...)
    re.compile(r"""\b(?:app|router|api|bp|blueprint|server)\.(get|post|put|patch|delete)\(\s*["'`](/[^"'`]*)["'`]""", re.I),
    # Flask: @app.route("/x")
    re.compile(r"""\.route\(\s*["'](/[^"']*)["']"""),
    # Spring: @GetMapping("/x"), @RequestMapping("/x")
    re.compile(r"""@(Get|Post|Put|Patch|Delete|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?["'](/?[^"']*)["']"""),
    # Django: path("x/", ...)
    re.compile(r"""\b(?:re_)?path\(\s*r?["']([^"']*)["']\s*,"""),
]


def _read(path: Path) -> str:
    """Texto del archivo, o "" si no existe, es un symlink (podria apuntar fuera del repo) o es enorme."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        return ""
    return path.read_text(errors="ignore")


def _framework(root: Path) -> str | None:
    try:
        pkg = json.loads(_read(root / "package.json") or "{}")
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    except (json.JSONDecodeError, AttributeError, TypeError):
        deps = {}
    for dep, name in _JS_FRAMEWORKS:
        if dep in deps:
            return name
    py_deps = (_read(root / "requirements.txt") + _read(root / "pyproject.toml") + _read(root / "Pipfile")).lower()
    for dep, name in _PY_FRAMEWORKS:
        if re.search(rf"\b{dep}\b", py_deps):
            return name
    for file, marker, name in _OTHER_FRAMEWORKS:
        if marker in _read(root / file):
            return name
    return None


def _port(value) -> int | None:
    """Puerto publicado de una entrada de `ports:` de compose ("8080:80", "127.0.0.1:8080:80/tcp", 80, {published: 8080})."""
    if isinstance(value, dict):
        value = value.get("published") or value.get("target")
    text = str(value).split("/")[0].split(":")
    candidate = text[-2] if len(text) >= 2 else text[-1]
    candidate = candidate.split("-")[0]  # rangos "8000-8005"
    return int(candidate) if candidate.isdigit() else None


def _compose(root: Path) -> tuple[bool, list[str], list[int]]:
    for name in COMPOSE_FILES:
        text = _read(root / name)
        if not text:
            continue
        try:
            services = (yaml.safe_load(text) or {}).get("services") or {}
        except (yaml.YAMLError, AttributeError):
            return True, [], []
        if not isinstance(services, dict):
            return True, [], []
        ports = [
            p for svc in services.values() if isinstance(svc, dict)
            for p in map(_port, svc.get("ports") or []) if p is not None
        ]
        return True, [str(s) for s in services], ports
    return False, [], []


def _env_keys(root: Path) -> list[str]:
    keys = []
    for line in _read(root / ".env.example").splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) not in keys:
            keys.append(m.group(1))
    return keys


def _source_files(root: Path):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for f in filenames:
            if Path(f).suffix in _SOURCE_EXT:
                count += 1
                if count > MAX_FILES:
                    return
                yield Path(dirpath) / f


def _api_routes(root: Path) -> list[str]:
    routes: list[str] = []
    for path in _source_files(root):
        text = _read(path)
        for pattern in _ROUTE_PATTERNS:
            for m in pattern.finditer(text):
                method, route = (m.group(1), m.group(2)) if m.lastindex == 2 else ("ANY", m.group(1))
                method = "ANY" if method.lower() == "request" else method.upper()
                entry = f"{method} {route if route.startswith('/') else '/' + route}"
                if entry not in routes:
                    routes.append(entry)
                if len(routes) >= MAX_ROUTES:
                    return routes
    return routes


def inspect_repo(path: Path) -> RepoInfo:
    has_compose, services, ports = _compose(path)
    dockerfile = _read(path / "Dockerfile")
    if not has_compose:
        ports = [int(p) for p in re.findall(r"(?im)^\s*EXPOSE\s+(\d+)", dockerfile)]
    return RepoInfo(
        framework=_framework(path),
        has_compose=has_compose,
        has_dockerfile=bool(dockerfile),
        services=services,
        ports=ports,
        env_example_keys=_env_keys(path),
        api_routes=_api_routes(path),
    )


def format_repo_summary(info: RepoInfo) -> str:
    how = "docker-compose" if info.has_compose else "Dockerfile" if info.has_dockerfile else "sin Docker (no se puede levantar)"
    lines = [
        f"Framework: {info.framework or 'desconocido'}",
        f"Como se levanta: {how}",
        f"Servicios: {', '.join(info.services) or 'ninguno'}",
        f"Puertos: {', '.join(map(str, info.ports)) or 'ninguno'}",
        f"Variables de .env.example (solo nombres): {', '.join(info.env_example_keys) or 'ninguna'}",
        "Rutas de la API:",
        *(f"- {r}" for r in info.api_routes or ["(no se detectaron)"]),
    ]
    return wrap_untrusted("repo", redact("\n".join(lines)))
