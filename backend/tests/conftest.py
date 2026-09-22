import asyncio
import os
import sys

# psycopg async (LangGraph checkpointer) requires the selector loop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Point the app at a dedicated test database before any app import touches
# settings. Requires the docker-compose Postgres to be running. These are
# hard assignments — an ambient POSTGRES_DB (e.g. from docker env_file) must
# never steer the fixtures at the real database.
os.environ["POSTGRES_DB"] = "sectors_agent_test"
os.environ["SECRET_KEY"] = "test-secret-key-test-secret-key"
os.environ["OPENROUTER_API_KEY"] = "test-key"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.ratelimit import limiter
from app.db.base import Base
from app.main import app
from app.models.user import User

limiter.enabled = False

# Sync (psycopg) URLs for one-time schema setup — keeps async fixtures free of
# cross-loop session fixtures.
_SYNC_URI = str(settings.SQLALCHEMY_DATABASE_URI).replace("+asyncpg", "+psycopg")
_SYNC_ADMIN_URI = _SYNC_URI.rsplit("/", 1)[0] + "/postgres"


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    """Create the test database (if missing) and all tables once per session."""
    if not settings.POSTGRES_DB.endswith("_test"):
        raise RuntimeError(
            f"Refusing to create/drop tables on non-test database "
            f"{settings.POSTGRES_DB!r}"
        )
    admin = create_engine(_SYNC_ADMIN_URI, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": settings.POSTGRES_DB},
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{settings.POSTGRES_DB}"'))
    admin.dispose()

    sync_engine = create_engine(_SYNC_URI)
    with sync_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(sync_engine)
    yield
    Base.metadata.drop_all(sync_engine)
    sync_engine.dispose()


@pytest_asyncio.fixture
async def engine(_prepare_database):
    eng = create_async_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def user(db):
    u = User(username="testuser")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
async def db(engine):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    # Committed rows would leak into the next test — truncate everything.
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def bound_session_maker(engine):
    """Rebind the app's global session maker to the per-test engine — required
    for modules that open their own sessions (e.g. the Sectors cache), or their
    connections pool against a dead event loop."""
    from app.db import session as db_session

    db_session.async_session_maker.configure(bind=engine)
    yield
    db_session.async_session_maker.configure(bind=db_session.engine)


@pytest_asyncio.fixture
async def client(engine):
    """API client; the app's session maker is rebound to the per-test engine."""
    from app.db import session as db_session

    db_session.async_session_maker.configure(bind=engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    db_session.async_session_maker.configure(bind=db_session.engine)

    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
