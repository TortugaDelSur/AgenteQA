from app.execution import runner
from app.models.schemas import TestCase, TestPlan, TestResult


def _plan(*cases) -> TestPlan:
    return TestPlan(test_cases=list(cases))


def _ep_case(cid="TC-EP") -> TestCase:
    return TestCase(
        id=cid,
        type="endpoint",
        title="ep",
        request={"method": "GET", "url": "https://x.test/h", "headers": {}, "body": None},
        expected_status=200,
    )


def _ui_case(cid="TC-UI") -> TestCase:
    return TestCase(id=cid, type="ui", title="ui", steps=[])


async def test_run_plan_dispatches_by_type_and_keeps_order(monkeypatch):
    seen = []

    async def fake_run_endpoint(tc):
        seen.append(("endpoint", tc.id))
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    async def fake_run_ui(tc, session_id):
        seen.append(("ui", tc.id, session_id))
        return TestResult(test_case_id=tc.id, status="pass", detail="ok")

    monkeypatch.setattr(runner, "run_endpoint", fake_run_endpoint)
    monkeypatch.setattr(runner, "run_ui", fake_run_ui)

    results = await runner.run_plan("sess-9", _plan(_ep_case(), _ui_case()))

    assert [r.test_case_id for r in results] == ["TC-EP", "TC-UI"]
    assert seen == [("endpoint", "TC-EP"), ("ui", "TC-UI", "sess-9")]


async def test_run_test_case_unknown_type_returns_error():
    # model_construct saltea el Literal de Pydantic para simular un plan corrupto
    bogus = TestCase.model_construct(
        id="TC-Z", type="carrier-pigeon", title="?", steps=None, request=None
    )

    result = await runner.run_test_case(bogus, "s")

    assert result.status == "error"
    assert "tipo de test desconocido" in result.detail


async def test_run_test_case_wraps_unexpected_exception(monkeypatch):
    async def boom(tc):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(runner, "run_endpoint", boom)

    result = await runner.run_test_case(_ep_case(), "s")

    assert result.status == "error"
    assert "error inesperado" in result.detail
