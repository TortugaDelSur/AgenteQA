import datetime

from sqlalchemy import ForeignKey, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session as OrmSession, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(default=datetime.datetime.utcnow)
    context_json: Mapped[str] = mapped_column(default="{}")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    role: Mapped[str]
    content: Mapped[str]
    created_at: Mapped[datetime.datetime] = mapped_column(default=datetime.datetime.utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    plan_json: Mapped[str]
    created_at: Mapped[datetime.datetime] = mapped_column(default=datetime.datetime.utcnow)


class SweepState(Base):
    """Estado del barrido de pantallas en curso para una sesion (una fila por sesion).

    NDJSON es unidireccional: la pausa por duda se resuelve cortando el stream y guardando
    aca por donde retomar, en vez de mantener una conexion abierta (evita WebSocket).
    """
    __tablename__ = "sweep_states"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    pages_json: Mapped[str]
    next_index: Mapped[int] = mapped_column(default=0)
    visited_json: Mapped[str] = mapped_column(default="{}")
    pending_question: Mapped[str | None] = mapped_column(default=None)
    pending_question_url: Mapped[str | None] = mapped_column(default=None)
    questions_asked: Mapped[int] = mapped_column(default=0)
    # true si se topo con un muro de login no anticipado, o si las credenciales conocidas
    # fallaron: hace falta credenciales de prueba para reintentar.
    login_required: Mapped[bool] = mapped_column(default=False)
    # URL real donde hay que loguearse (la del login conocido, o donde se detecto el muro).
    # Se fija una vez y se reusa en cada resume — nunca se recalcula desde next_index, porque
    # next_index avanza a paginas que no son la de login (bug real: reintentaba el login contra
    # la pagina siguiente del barrido en vez de la de login de verdad).
    login_url: Mapped[str | None] = mapped_column(default=None)


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    test_case_id: Mapped[str]
    status: Mapped[str]
    detail: Mapped[str]
    evidence: Mapped[str | None]
    created_at: Mapped[datetime.datetime] = mapped_column(default=datetime.datetime.utcnow)


engine = create_engine(f"sqlite:///{settings.db_path}")
SessionLocal = sessionmaker(bind=engine)


def _sql_literal(value) -> str | None:
    """Literal SQL para usar en un DEFAULT de ALTER TABLE. None si no se puede representar
    (ej. un default callable como datetime.utcnow) — en ese caso la columna se agrega nullable.
    """
    if callable(value):
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _add_missing_columns() -> None:
    """Migracion liviana: `create_all` crea tablas nuevas pero NUNCA altera una tabla ya
    existente, asi que un campo agregado a un modelo (ej. `SweepState.login_required`) rompe
    con "no such column" contra un `.db` de una corrida anterior al cambio. Compara las
    columnas declaradas en cada modelo contra las que existen de verdad y agrega las que falten.

    ponytail: cubre agregar columnas (nullable, o NOT NULL con default simple); no renombra
    ni borra ni cambia tipos. Si el schema empieza a necesitar eso, subir a Alembic.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue

                ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(engine.dialect)}"
                if not column.nullable:
                    default_value = column.default.arg if column.default is not None else None
                    literal = _sql_literal(default_value)
                    if literal is not None:
                        ddl += f" NOT NULL DEFAULT {literal}"
                conn.execute(text(ddl))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def get_db() -> OrmSession:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
