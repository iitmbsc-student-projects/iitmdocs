from __future__ import annotations

"""
SQLAlchemy model and session setup for the PG FAQ database.

This file answers: "What does the FAQ table look like to Python code, and how
do we open safe ORM sessions against Postgres?"

It intentionally does not contain product operations like "search FAQs" or
"replace seed rows". Those actions live in `repository.py`.

The `Faq` model below is the ONLY definition of the `faqs` table. `embed.py`
creates the table from it with `Base.metadata.create_all`, so there is no separate
hand-written schema to keep in sync. `pg/init/001_vector_extension.sql` only enables
the pgvector extension, which SQLAlchemy cannot express.

Connection settings come from the same `PG*` environment variables used by the
Django service and the bootstrap job.
"""

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Index, Text, UniqueConstraint, create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


REQUIRED_PG_ENV_VARS = ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")


class Base(DeclarativeBase):
    """Base class for PG FAQ ORM models."""


class Faq(Base):
    """ORM model for the Postgres `faqs` table.

    One row is one question/answer pair belonging to one programme. `program_id` is
    "ds", "es", "mg", "ae", or "common" for the pool shared by all four - see
    programs.py. A programme reads its own rows plus the common ones.
    """

    __tablename__ = "faqs"
    __table_args__ = (
        # The same question may exist for several programmes with different answers,
        # so uniqueness is per programme rather than per question.
        UniqueConstraint("program_id", "question", name="faqs_program_question_unique"),
        Index("idx_faqs_program_id", "program_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    program_id: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1024), nullable=True)


def required_pg_env() -> dict[str, str]:
    """Return required Postgres env vars, failing before any weak defaults are used."""

    values = {key: os.getenv(key) for key in REQUIRED_PG_ENV_VARS}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required Postgres env vars: {', '.join(missing)}")
    return {key: value for key, value in values.items() if value is not None}


def database_url_from_env() -> URL:
    """Build a SQLAlchemy database URL from the existing PG* environment variables."""

    pg_env = required_pg_env()
    query: dict[str, str] = {}
    sslmode = os.getenv("PGSSLMODE")
    connect_timeout = os.getenv("PGCONNECT_TIMEOUT")
    if sslmode:
        query["sslmode"] = sslmode
    if connect_timeout:
        query["connect_timeout"] = connect_timeout

    return URL.create(
        "postgresql+psycopg",
        username=pg_env["PGUSER"],
        password=pg_env["PGPASSWORD"],
        host=pg_env["PGHOST"],
        port=int(os.getenv("PGPORT", "5432")),
        database=pg_env["PGDATABASE"],
        query=query,
    )


def create_pg_engine() -> Engine:
    """Create a SQLAlchemy engine for the FAQ Postgres database."""

    return create_engine(database_url_from_env(), pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the FAQ database engine."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional SQLAlchemy session scope."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
