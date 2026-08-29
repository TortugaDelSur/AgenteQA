from app.models.schemas import ContextProgress
from tests.fixtures import SAMPLE_TEST_PLAN


def test_ready_for_plan_requires_three_mandatory_nodes():
    assert not ContextProgress(objetivo=True, acceso=True).ready_for_plan
    assert ContextProgress(objetivo=True, acceso=True, alcance=True).ready_for_plan


def test_sample_plan_has_ui_and_endpoint_cases():
    types = {tc.type for tc in SAMPLE_TEST_PLAN.test_cases}
    assert types == {"ui", "endpoint"}
