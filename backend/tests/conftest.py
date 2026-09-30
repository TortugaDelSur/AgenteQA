import os

os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import db as db_module


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    testing_session_local = sessionmaker(bind=engine)
    db_module.Base.metadata.create_all(engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[db_module.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class FakeBrowserContext:
    """Browser/context de Playwright falso para los tests de /api/execute (run_test_case va mockeado)."""

    async def new_context(self):
        return self

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def fake_execute_browser(monkeypatch):
    import app.routers.execute as execute_router

    async def _launch():
        return None, FakeBrowserContext()

    monkeypatch.setattr(execute_router, "_launch_browser", _launch)
