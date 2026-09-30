"""Causa probable de un test fallido: donde del repo esta el problema, con su nivel de confianza.

Se calcula en el momento en que falla el caso (logs frescos del contenedor) y solo si hay repo
levantado. Todo lo que viene del repo o de los logs pasa por `redact` + `wrap_untrusted` antes del
LLM, y la respuesta solo vale si apunta a un archivo que existe en el repo (anti-alucinacion).
"""

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app import runner_client
from app.llm.client import diagnose_failure
from app.models.schemas import SuspectedCause, TestCase, TestResult
from app.repo import launch
from app.repo.inspector import _SOURCE_EXT, _read, _source_files
from app.security import redact, wrap_untrusted

LOG_TAIL = 200
MAX_HITS = 30
MAX_LINE_LEN = 200
_SEARCH_EXT = _SOURCE_EXT | {".html", ".jsx", ".tsx", ".vue", ".svelte", ".erb", ".hbs", ".twig"}

# rutas de archivos en stack traces: Python (File "x", line N), Node (at f (x:N:C)), Java (X.java:N).
_TRACE_PATTERNS = [
    re.compile(r'File "([^"]+)", line (\d+)'),
    re.compile(r"\(?((?:/|\.{0,2}/)?[\w./-]+\.(?:js|ts|mjs|cjs|jsx|tsx)):(\d+):\d+\)?"),
    re.compile(r"\(([\w$]+\.(?:java|kt)):(\d+)\)"),
]


def _search_terms(tc: TestCase, result: TestResult) -> list[str]:
    """Lo que buscar en el repo: path de la URL, ids/clases/texto del selector y texto esperado."""
    terms: list[str] = []
    if tc.request:
        terms.append(urlparse(tc.request.url).path)
    for step in tc.steps or []:
        if step.url:
            terms.append(urlparse(step.url).path)
        if step.selector:
            terms += re.findall(r"[#.]([\w-]{3,})", step.selector)
            terms += re.findall(r"""(?:text=|has-text\()["']?([^"')]{3,})""", step.selector)
        if step.expected:
            terms.append(step.expected)
    if tc.expected_body_contains:
        terms.append(tc.expected_body_contains)
    unique = []
    for term in terms:
        term = term.strip()
        if len(term) >= 3 and term != "/" and term not in unique:
            unique.append(term)
    return unique


def _trace_hits(logs: str, repo: Path) -> list[str]:
    """Archivos del stack trace mapeados al repo por sufijo (en el contenedor el path es otro, ej. /app/src/x.py)."""
    hits = []
    for pattern in _TRACE_PATTERNS:
        for path, line in pattern.findall(logs):
            parts = Path(path).parts
            for i in range(len(parts)):
                candidate = repo.joinpath(*parts[i:])
                if parts[i:] and candidate.is_file() and not candidate.is_symlink():
                    entry = f"{candidate.relative_to(repo)}:{line} (stack trace)"
                    if entry not in hits:
                        hits.append(entry)
                    break
    return hits


def _grep(repo: Path, terms: list[str]) -> list[str]:
    hits: list[str] = []
    if not terms:
        return hits
    for path in _source_files(repo, _SEARCH_EXT):
        for number, line in enumerate(_read(path).splitlines(), start=1):
            if any(term in line for term in terms):
                hits.append(f"{path.relative_to(repo)}:{number}: {line.strip()[:MAX_LINE_LEN]}")
                if len(hits) >= MAX_HITS:
                    return hits
    return hits


def _existing_file(repo: Path, file: str) -> bool:
    candidate = (repo / file).resolve()
    return candidate.is_relative_to(repo.resolve()) and candidate.is_file()


async def diagnose(
    session_id: str, repo: Path, tc: TestCase, result: TestResult, secrets: list[str],
) -> SuspectedCause | None:
    """Best-effort: si algo falla (runner, LLM, respuesta invalida) devuelve None y el test sigue
    siendo un fallo normal, sin causa."""
    logs = ""
    run_id = launch.run_id(session_id)
    if run_id:
        try:
            logs = await runner_client.get_logs(run_id, tail=LOG_TAIL)
        except (runner_client.RunnerError, httpx.HTTPError):
            logs = ""

    hits = _trace_hits(logs, repo) + _grep(repo, _search_terms(tc, result))
    evidence = "\n".join([
        f"Test: {tc.id} — {tc.title} ({tc.type})",
        f"Definicion: {tc.model_dump_json(exclude_none=True)}",
        f"Resultado: {result.status} — {result.detail}",
        "Coincidencias en el repo (archivo:linea):",
        *(hits or ["(ninguna)"]),
    ])
    prompt = "\n\n".join([
        wrap_untrusted("test y repo", redact(evidence, secrets)),
        wrap_untrusted("logs del contenedor", redact(logs[-8000:], secrets) or "(sin logs)"),
    ])

    try:
        data = await asyncio.to_thread(diagnose_failure, prompt)
        if not isinstance(data, dict) or not data.get("file"):
            return None
        cause = SuspectedCause(**data)
    except Exception:  # LLM caido o respuesta invalida: sin causa, el fallo se reporta igual
        return None
    # el LLM solo puede senalar archivos que existen en el repo; si inventa uno, no hay causa.
    cause.file = cause.file.split(":")[0].lstrip("/")
    return cause if _existing_file(repo, cause.file) else None
