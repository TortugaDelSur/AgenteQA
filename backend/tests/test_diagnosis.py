import asyncio
import json

import httpx
import pytest

import app.routers.chat as chat_router
import app.routers.execute as execute_router
import app.routers.plan as plan_router
import app.routers.report as report_router
from app import diagnosis, runner_client
from app.models.schemas import ContextProgress, HttpRequestSpec, SuspectedCause, TestCase, TestResult, UiStep
from app.repo import launch, workspace
from tests.fixtures import SAMPLE_TEST_PLAN
from tests.test_plan_sweep_router import _browser_factory

SECRET = "super-secreto-123"


@pytest.fixture(autouse=True)
def _clean_launch(monkeypatch):
    async def fake_stop(run_id):
        pass

    monkeypatch.setattr(runner_client, "stop_run", fake_stop)
    yield
    for sid in list(launch._runs):
        launch.forget(sid)
    for sid in list(workspace._clones):
        workspace.forget(sid)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "users.py").write_text('@app.get("/api/users")\ndef users():\n    return db.all()\n')
    (repo / "web").mkdir()
    (repo / "web" / "login.html").write_text('<button id="login-btn">Entrar</button>\n')
    return repo


def _endpoint_case():
    return TestCase(
        id="TC-01", type="endpoint", title="lista usuarios",
        request=HttpRequestSpec(method="GET", url="http://127.0.0.1:5555/api/users"), expected_status=200,
    )


# --- piezas ---

def test_search_terms_from_url_selector_and_expected():
    tc = TestCase(id="TC-02", type="ui", title="login", steps=[
        UiStep(action="goto", url="http://127.0.0.1:5555/login"),
        UiStep(action="click", selector="#login-btn"),
        UiStep(action="assert_text", selector="text=Bienvenido", expected="Hola Ana"),
    ])
    terms = diagnosis._search_terms(tc, TestResult(test_case_id="TC-02", status="fail", detail="x"))
    assert terms == ["/login", "login-btn", "Bienvenido", "Hola Ana"]


def test_trace_hits_map_container_paths_to_the_repo(tmp_path):
    repo = _repo(tmp_path)
    (repo / "web" / "api.js").write_text("fetch('/x')\n")
    logs = (
        'Traceback:\n  File "/srv/app/users.py", line 3, in users\n'
        "    at handler (/usr/src/web/api.js:1:5)\n"
        '  File "/usr/lib/python3/site.py", line 9\n'
    )
    assert diagnosis._trace_hits(logs, repo) == ["app/users.py:3 (stack trace)", "web/api.js:1 (stack trace)"]


def test_grep_finds_route_and_selector(tmp_path):
    repo = _repo(tmp_path)
    hits = diagnosis._grep(repo, ["/api/users", "login-btn"])
    assert any(h.startswith("app/users.py:1:") for h in hits)
    assert any(h.startswith("web/login.html:1:") for h in hits)
    assert diagnosis._grep(repo, []) == []


# --- diagnose ---

async def test_diagnose_returns_cause_redacts_secrets_and_wraps_untrusted(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    launch._runs["s"] = {"run_id": "aqa-s", "urls": [], "chosen": None, "started_at": 0.0}

    async def fake_logs(run_id, tail=200):
        return f'error DB password={SECRET}\n  File "/srv/app/users.py", line 3, in users\nKeyError: all'

    seen = {}

    def fake_llm(prompt):
        seen["prompt"] = prompt
        return {"file": "app/users.py", "line": 3, "explanation": "db.all() revienta", "confidence": "alta"}

    monkeypatch.setattr(runner_client, "get_logs", fake_logs)
    monkeypatch.setattr(diagnosis, "diagnose_failure", fake_llm)

    result = TestResult(test_case_id="TC-01", status="fail", detail="esperaba 200, recibio 500")
    cause = await diagnosis.diagnose("s", repo, _endpoint_case(), result, [SECRET])

    assert cause == SuspectedCause(file="app/users.py", line=3, explanation="db.all() revienta", confidence="alta")
    assert SECRET not in seen["prompt"]
    assert "app/users.py:3 (stack trace)" in seen["prompt"]
    assert seen["prompt"].count("<<<CONTENIDO_NO_CONFIABLE") == 2


@pytest.mark.parametrize("llm_answer", [
    {"file": None},                                                                    # sin fundamento
    {"file": "app/inventado.py", "line": 1, "explanation": "x", "confidence": "alta"},  # alucinado
    {"file": "../../etc/passwd", "line": 1, "explanation": "x", "confidence": "alta"},  # fuera del repo
    {"file": "app/users.py", "explanation": "x", "confidence": "altisima"},             # schema invalido
    RuntimeError("LLM caido"),
])
async def test_diagnose_returns_none_when_answer_is_unusable(tmp_path, monkeypatch, llm_answer):
    repo = _repo(tmp_path)

    def fake_llm(prompt):
        if isinstance(llm_answer, Exception):
            raise llm_answer
        return llm_answer

    monkeypatch.setattr(diagnosis, "diagnose_failure", fake_llm)
    result = TestResult(test_case_id="TC-01", status="fail", detail="x")
    assert await diagnosis.diagnose("s", repo, _endpoint_case(), result, []) is None


async def test_diagnose_without_runner_logs_still_uses_repo(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    launch._runs["s"] = {"run_id": "aqa-s", "urls": [], "chosen": None, "started_at": 0.0}

    async def runner_down(run_id, tail=200):
        raise httpx.ConnectError("sin runner")

    seen = {}

    def fake_llm(prompt):
        seen["prompt"] = prompt
        return {"file": "/app/users.py:1", "line": 1, "explanation": "ruta", "confidence": "media"}

    monkeypatch.setattr(runner_client, "get_logs", runner_down)
    monkeypatch.setattr(diagnosis, "diagnose_failure", fake_llm)
    result = TestResult(test_case_id="TC-01", status="fail", detail="x")

    cause = await diagnosis.diagnose("s", repo, _endpoint_case(), result, [])

    assert cause.file == "app/users.py"
    assert "(sin logs)" in seen["prompt"]


# --- launch ---

async def test_launch_start_choose_rebase_and_forget(monkeypatch):
    stopped = []

    async def fake_start(session_id, repo_path):
        return {"run_id": "aqa-s", "urls": ["http://127.0.0.1:18080", "http://127.0.0.1:18443"]}

    async def fake_stop(run_id):
        stopped.append(run_id)

    monkeypatch.setattr(runner_client, "start_run", fake_start)
    monkeypatch.setattr(runner_client, "stop_run", fake_stop)

    assert launch.urls("s") == [] and launch.run_id("s") is None and launch.choose("s", "x") is None
    await launch.start("s", "/repo")
    assert launch.chosen_url("s") is None
    assert launch.choose("s", "no se") is None
    assert launch.choose("s", "la del 18443") == "http://127.0.0.1:18443"
    assert launch.chosen_url("s") == "http://127.0.0.1:18443"

    assert launch.rebase_urls(["https://prod.com/dash?x=1", "https://prod.com"], "http://127.0.0.1:1") == [
        "http://127.0.0.1:1/dash?x=1", "http://127.0.0.1:1/",
    ]

    launch.forget("s")  # dentro de un event loop: apaga en segundo plano
    await asyncio.gather(*launch._pending)
    assert stopped == ["aqa-s"] and launch.run_id("s") is None
    launch.forget("s")  # idempotente


def test_launch_forget_survives_runner_down(monkeypatch):
    async def boom(run_id):
        raise httpx.ConnectError("sin runner")

    monkeypatch.setattr(runner_client, "stop_run", boom)
    launch._runs["s"] = {"run_id": "aqa-s", "urls": [], "chosen": None, "started_at": 0.0}
    launch.forget("s")
    assert launch.run_id("s") is None


# --- enganche en el barrido ---

def _session_with_repo(client, monkeypatch, tmp_path, **ctx) -> str:
    monkeypatch.setattr(
        chat_router, "llm_chat", lambda history, page_snapshot=None: ("hola", ContextProgress(**ctx)),
    )
    sid = client.post("/api/chat", json={"message": "hola"}).json()["session_id"]
    workspace._clones[sid] = ("https://github.com/acme/app", _repo(tmp_path), None)
    return sid


def _ndjson(text):
    return [json.loads(line) for line in text.strip().splitlines() if line]


def test_sweep_launches_repo_and_tests_the_local_app(client, monkeypatch, tmp_path):
    sid = _session_with_repo(
        client, monkeypatch, tmp_path, repo_url="https://github.com/acme/app",
        target_url="https://prod.acme.com", extra_urls=["https://prod.acme.com/dash"],
    )

    async def fake_start(session_id, repo_path):
        assert repo_path.endswith("repo")
        return {"run_id": f"aqa-{session_id}", "urls": ["http://127.0.0.1:18080"]}

    monkeypatch.setattr(runner_client, "start_run", fake_start)
    visited = []
    monkeypatch.setattr(plan_router, "_launch_browser", _browser_factory(created_pages=visited))
    monkeypatch.setattr(plan_router, "check_page_doubt", lambda history, url, elements: None)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    lines = _ndjson(client.post("/api/plan/sweep", json={"session_id": sid}).text)

    assert lines[0]["type"] == "launching"
    assert [l["url"] for l in lines if l["type"] == "visiting"] == [
        "http://127.0.0.1:18080", "http://127.0.0.1:18080/dash",
    ]
    context = client.get(f"/api/chat/{sid}").json()["context"]
    assert context["target_url"] == "http://127.0.0.1:18080"
    # el LLM arma URLs desde el chat (prod, o el puerto que dijo el usuario): todas pasan a la app local.
    plan = lines[-1]["plan"]
    urls = [tc["request"]["url"] for tc in plan["test_cases"] if tc.get("request")]
    urls += [s["url"] for tc in plan["test_cases"] for s in tc.get("steps") or [] if s.get("url")]
    assert urls and all(u.startswith("http://127.0.0.1:18080/") or u == "http://127.0.0.1:18080" for u in urls)


def test_sweep_asks_which_url_is_the_app_and_resumes_with_the_answer(client, monkeypatch, tmp_path):
    sid = _session_with_repo(client, monkeypatch, tmp_path, repo_url="https://github.com/acme/app")

    async def fake_start(session_id, repo_path):
        return {"run_id": f"aqa-{session_id}", "urls": ["http://127.0.0.1:18080", "http://127.0.0.1:15432"]}

    monkeypatch.setattr(runner_client, "start_run", fake_start)
    monkeypatch.setattr(plan_router, "_launch_browser", _browser_factory())
    monkeypatch.setattr(plan_router, "check_page_doubt", lambda history, url, elements: None)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    lines = _ndjson(client.post("/api/plan/sweep", json={"session_id": sid}).text)
    assert lines[-1]["type"] == "question" and "18080" in lines[-1]["question"]

    bad = client.post("/api/plan/sweep/answer", json={"session_id": sid, "answer": "la primera"})
    assert bad.status_code == 422 and "18080" in bad.json()["detail"]

    assert client.post("/api/plan/sweep/answer", json={"session_id": sid, "answer": "18080"}).status_code == 200
    lines = _ndjson(client.post("/api/plan/sweep", json={"session_id": sid}).text)

    assert lines[0] == {"type": "visiting", "url": "http://127.0.0.1:18080", "index": 1, "total": 1}
    assert lines[-1]["type"] == "plan_ready"


@pytest.mark.parametrize("error", [runner_client.RunnerError(422, "sin docker-compose.yml ni Dockerfile"),
                                   httpx.ConnectError("sin runner")])
def test_sweep_reports_launch_failure_and_keeps_going(client, monkeypatch, tmp_path, error):
    sid = _session_with_repo(client, monkeypatch, tmp_path, repo_url="https://github.com/acme/app")

    async def fake_start(session_id, repo_path):
        raise error

    monkeypatch.setattr(runner_client, "start_run", fake_start)
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)

    lines = _ndjson(client.post("/api/plan/sweep", json={"session_id": sid}).text)

    assert [l["type"] for l in lines] == ["launching", "error", "plan_ready"]
    assert "no se pudo levantar el repo" in lines[1]["detail"]


# --- ejecucion + reporte ---

def test_failed_case_gets_suspected_cause_saved_and_reported(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("hola", ContextProgress(target_url="https://example.com")),
    )
    sid = client.post("/api/chat", json={"message": "hola"}).json()["session_id"]
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)
    client.post("/api/plan", json={"session_id": sid})
    workspace._clones[sid] = ("https://github.com/acme/app", _repo(tmp_path), None)
    launch._runs[sid] = {"run_id": f"aqa-{sid}", "urls": ["https://example.com"],
                         "chosen": "https://example.com", "started_at": 0.0}

    async def fake_run(tc, session_id, browser=None, ask=None):
        status = "fail" if tc.id == SAMPLE_TEST_PLAN.test_cases[0].id else "pass"
        return TestResult(test_case_id=tc.id, status=status, detail="boom")

    cause = SuspectedCause(file="app/users.py", line=3, explanation="db.all() revienta", confidence="alta")
    diagnosed = []

    async def fake_diagnose(session_id, repo, tc, result, secrets):
        diagnosed.append(tc.id)
        return cause

    monkeypatch.setattr(execute_router, "run_test_case", fake_run)
    monkeypatch.setattr(execute_router, "diagnose", fake_diagnose)

    lines = _ndjson(client.post("/api/execute", json={"session_id": sid}).text)

    assert diagnosed == [SAMPLE_TEST_PLAN.test_cases[0].id]  # solo el que fallo
    assert lines[0]["result"]["suspected_cause"]["file"] == "app/users.py"
    assert lines[1]["result"]["suspected_cause"] is None

    seen = {}

    def fake_report(plan, results):
        seen["results"] = results
        return "# Reporte de QA"

    monkeypatch.setattr(report_router, "generate_report", fake_report)
    assert client.get(f"/api/report/{sid}").status_code == 200
    assert seen["results"][0].suspected_cause == cause
    # pruebas terminadas y resultados entregados: el repo se apaga.
    assert launch.run_id(sid) is None


def test_launch_forget_from_sync_context_awaits_the_stop(monkeypatch):
    stopped = []

    async def fake_stop(run_id):
        stopped.append(run_id)

    monkeypatch.setattr(runner_client, "stop_run", fake_stop)
    launch._runs["s"] = {"run_id": "aqa-s", "urls": [], "chosen": None, "started_at": 0.0}
    launch.forget("s")
    assert stopped == ["aqa-s"]


async def test_launch_background_stop_swallows_runner_errors(monkeypatch):
    async def boom(run_id):
        raise httpx.ConnectError("sin runner")

    monkeypatch.setattr(runner_client, "stop_run", boom)
    launch._runs["s"] = {"run_id": "aqa-s", "urls": [], "chosen": None, "started_at": 0.0}
    launch.forget("s")
    await asyncio.gather(*launch._pending, return_exceptions=True)
    await asyncio.sleep(0)
    assert not launch._pending


# --- apagado ---

def test_reap_idle_only_stops_unwatched_and_idle_sessions(monkeypatch):
    stopped = []

    async def fake_stop(run_id):
        stopped.append(run_id)

    monkeypatch.setattr(runner_client, "stop_run", fake_stop)
    from app import live

    for sid in ("cerrada", "mirando", "refresco", "ocupada", "recien"):
        launch._runs[sid] = {"run_id": f"aqa-{sid}", "urls": [], "chosen": None, "started_at": 0.0}
    launch._runs["recien"]["started_at"] = 950.0
    monkeypatch.setitem(live._subscribers, "mirando", {object()})
    monkeypatch.setitem(live._last_seen, "cerrada", 100.0)    # se fue hace 900s
    monkeypatch.setitem(live._last_seen, "refresco", 990.0)   # se desconecto hace 10s (refresco)

    with launch.hold("ocupada"):
        assert sorted(launch.reap_idle(1000.0)) == ["cerrada"]
    assert stopped == ["aqa-cerrada"]
    assert launch.run_id("ocupada") and launch.run_id("mirando") and launch.run_id("refresco")

    # la ejecucion termino y la pagina no volvio: ahora si se apaga.
    assert "ocupada" in launch.reap_idle(1000.0)
    live._subscribers.pop("mirando", None)


async def test_relaunch_remembers_the_chosen_app_by_position(monkeypatch):
    ports = iter([["http://127.0.0.1:1000", "http://127.0.0.1:1001"], ["http://127.0.0.1:2000", "http://127.0.0.1:2001"]])

    async def fake_start(session_id, repo_path):
        return {"run_id": "aqa-s", "urls": next(ports)}

    monkeypatch.setattr(runner_client, "start_run", fake_start)
    await launch.start("s", "/repo")
    launch.choose("s", "1001")
    launch.stop("s")
    await asyncio.gather(*launch._pending)

    await launch.start("s", "/repo")
    assert launch.chosen_url("s") == "http://127.0.0.1:2001"

    launch.forget("s")  # repo nuevo: se olvida la eleccion
    await asyncio.gather(*launch._pending)
    assert "s" not in launch._chosen_index


def test_execute_relaunches_stopped_repo_and_moves_plan_to_new_port(client, monkeypatch, tmp_path):
    old = "http://127.0.0.1:18080"
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("hola", ContextProgress(target_url=old)),
    )
    sid = client.post("/api/chat", json={"message": "hola"}).json()["session_id"]
    plan = SAMPLE_TEST_PLAN.model_copy(deep=True)
    for tc in plan.test_cases:
        if tc.request:
            tc.request.url = old + "/api/users"
        for step in tc.steps or []:
            if step.url:
                step.url = old + "/login"
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: plan)
    client.post("/api/plan", json={"session_id": sid})
    workspace._clones[sid] = ("https://github.com/acme/app", _repo(tmp_path), None)

    async def fake_start(session_id, repo_path):
        return {"run_id": f"aqa-{session_id}", "urls": ["http://127.0.0.1:29999"]}

    ran = []

    async def fake_run(tc, session_id, browser=None, ask=None):
        ran.append(tc.request.url if tc.request else [s.url for s in tc.steps if s.url])
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(runner_client, "start_run", fake_start)
    monkeypatch.setattr(execute_router, "run_test_case", fake_run)

    lines = _ndjson(client.post("/api/execute", json={"session_id": sid}).text)

    assert all(line["result"]["status"] == "pass" for line in lines)  # sin bloqueo de dominio
    assert "http://127.0.0.1:29999/api/users" in ran or ["http://127.0.0.1:29999/login"] in ran
    assert "18080" not in json.dumps(ran)
    assert client.get(f"/api/chat/{sid}").json()["context"]["target_url"] == "http://127.0.0.1:29999"
    assert launch.run_id(sid) is None  # termino: se apago


def test_execute_pauses_when_repo_cannot_be_relaunched(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        chat_router, "llm_chat",
        lambda history, page_snapshot=None: ("hola", ContextProgress(target_url="https://example.com")),
    )
    sid = client.post("/api/chat", json={"message": "hola"}).json()["session_id"]
    monkeypatch.setattr(plan_router, "generate_plan", lambda history, page_snapshot=None: SAMPLE_TEST_PLAN)
    client.post("/api/plan", json={"session_id": sid})
    workspace._clones[sid] = ("https://github.com/acme/app", _repo(tmp_path), None)

    async def two_urls(session_id, repo_path):
        return {"run_id": f"aqa-{session_id}", "urls": ["http://127.0.0.1:1", "http://127.0.0.1:2"]}

    async def runner_down(session_id, repo_path):
        raise httpx.ConnectError("sin runner")

    monkeypatch.setattr(runner_client, "start_run", runner_down)
    lines = _ndjson(client.post("/api/execute", json={"session_id": sid}).text)
    assert lines == [{"type": "paused", "reason": "unreachable", "detail": "no se pudo levantar el repo: el runner no responde"}]

    client.post("/api/execute/answer", json={"session_id": sid, "answer": "ya esta"})
    monkeypatch.setattr(runner_client, "start_run", two_urls)
    lines = _ndjson(client.post("/api/execute", json={"session_id": sid}).text)
    assert lines[0]["reason"] == "unreachable" and "varias URLs" in lines[0]["detail"]
