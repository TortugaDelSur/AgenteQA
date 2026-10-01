from sqlalchemy import create_engine, inspect, text

from app.models import db as db_module


def test_init_db_adds_missing_column_to_existing_table(monkeypatch):
    """Reproduce el bug real: un .db creado ANTES de agregar `SweepState.login_required`
    (create_all nunca altera tablas ya existentes) no debe romper con "no such column"
    la proxima vez que arranca el backend.
    """
    test_engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(db_module, "engine", test_engine)

    with test_engine.begin() as conn:
        # forma vieja de sweep_states, sin la columna login_required
        conn.execute(text(
            "CREATE TABLE sweep_states ("
            "session_id VARCHAR PRIMARY KEY, pages_json VARCHAR NOT NULL, "
            "next_index INTEGER NOT NULL DEFAULT 0, visited_json VARCHAR NOT NULL DEFAULT '{}', "
            "pending_question VARCHAR, pending_question_url VARCHAR, "
            "questions_asked INTEGER NOT NULL DEFAULT 0)"
        ))
        conn.execute(text("INSERT INTO sweep_states (session_id, pages_json) VALUES ('s1', '[]')"))

    db_module.init_db()

    columns = {c["name"] for c in inspect(test_engine).get_columns("sweep_states")}
    assert "login_required" in columns

    with test_engine.connect() as conn:
        value = conn.execute(
            text("SELECT login_required FROM sweep_states WHERE session_id = 's1'")
        ).scalar()
        assert value == 0  # default False, aplicado a la fila que ya existia

    # la tabla sigue siendo usable via ORM despues del parche.
    with db_module.SessionLocal(bind=test_engine) as session:
        state = session.get(db_module.SweepState, "s1")
        assert state.login_required is False


def test_init_db_is_idempotent_when_schema_already_matches(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(db_module, "engine", test_engine)

    db_module.init_db()
    db_module.init_db()  # no debe fallar ni duplicar columnas la segunda vez

    columns = {c["name"] for c in inspect(test_engine).get_columns("sweep_states")}
    assert "login_required" in columns
