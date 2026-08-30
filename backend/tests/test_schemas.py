import pytest
from pydantic import ValidationError

from app.models.schemas import ContextProgress, TestCase
from tests.fixtures import SAMPLE_TEST_PLAN


def test_ready_for_plan_requires_three_mandatory_nodes():
    assert not ContextProgress(objetivo=True, acceso=True).ready_for_plan
    assert ContextProgress(objetivo=True, acceso=True, alcance=True).ready_for_plan


def test_sample_plan_has_ui_and_endpoint_cases():
    types = {tc.type for tc in SAMPLE_TEST_PLAN.test_cases}
    assert types == {"ui", "endpoint"}


def test_testcase_id_rejects_path_traversal():
    # el id se usa para nombrar el screenshot en disco (ui_runner.py); un id con ".." podria
    # escribir fuera de backend/screenshots/.
    with pytest.raises(ValidationError):
        TestCase(id="../../../etc/evil", type="endpoint", title="x")


def test_testcase_id_accepts_normal_ids():
    TestCase(id="TC-01", type="endpoint", title="x")
