import pytest
from pydantic import ValidationError

from app.models.schemas import ContextProgress, TestCase
from tests.fixtures import SAMPLE_TEST_PLAN


def test_ready_for_plan_requires_all_four_nodes():
    # "repo" tambien bloquea: si no, el front puede disparar el plan mientras el chat
    # todavia esta preguntando por el repo en el mismo mensaje, cortandole el flujo al usuario.
    assert not ContextProgress(objetivo=True, acceso=True, alcance=True).ready_for_plan
    assert not ContextProgress(objetivo=True, acceso=True).ready_for_plan
    assert ContextProgress(objetivo=True, acceso=True, alcance=True, repo=True).ready_for_plan


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


def test_extra_urls_drops_external_domains_and_resolves_relative_paths():
    # bug real: el LLM volco 44 urls, incluyendo rutas relativas y dominios externos
    # (github.com, elementalselenium.com) sin que el usuario las confirmara.
    context = ContextProgress(
        target_url="https://the-internet.herokuapp.com",
        extra_urls=[
            "https://github.com/tourdedave/the-internet",
            "/checkboxes",
            "/dropdown",
            "http://elementalselenium.com/",
        ],
    )

    assert context.extra_urls == [
        "https://the-internet.herokuapp.com/checkboxes",
        "https://the-internet.herokuapp.com/dropdown",
    ]


def test_extra_urls_capped_at_max():
    many_urls = [f"/page{i}" for i in range(20)]
    context = ContextProgress(target_url="https://x.com", extra_urls=many_urls)

    assert len(context.extra_urls) == 8


def test_extra_urls_empty_without_target_url():
    context = ContextProgress(extra_urls=["/foo", "https://x.com/bar"])
    assert context.extra_urls == []
