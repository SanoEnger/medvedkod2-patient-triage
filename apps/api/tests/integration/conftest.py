import asyncio
import os
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="Install the postgres extra")
pytest.importorskip("alembic", reason="Install the postgres extra")
pytest.importorskip("asyncpg", reason="Install the postgres extra")
pytest_asyncio = pytest.importorskip("pytest_asyncio", reason="Install the test extra")

from alembic import command
from alembic.config import Config
from app.db.engine import create_engine
from app.db.models import AuditEventRecord, IntegrationNonceRecord
from sqlalchemy import delete, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

API_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def database_url():
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated empty PostgreSQL *_test database")
    parsed = make_url(value)
    if parsed.drivername != "postgresql+asyncpg" or not (parsed.database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must use postgresql+asyncpg and a database ending in _test")

    async def tables():
        engine = create_engine(value)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        finally:
            await engine.dispose()

    if set(asyncio.run(tables())) - {"alembic_version"}:
        pytest.fail("PostgreSQL tests require an empty database; existing tables are never removed")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = value
    config = Config(str(API_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    try:
        yield value
    finally:
        async def clear_technical_events():
            engine = create_engine(value)
            try:
                async with engine.begin() as connection:
                    await connection.execute(delete(AuditEventRecord))
                    await connection.execute(delete(IntegrationNonceRecord))
            finally:
                await engine.dispose()
        asyncio.run(clear_technical_events())
        command.downgrade(config, "base")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest_asyncio.fixture
async def engine(database_url):
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AuditEventRecord))
        await engine.dispose()


@pytest_asyncio.fixture
async def db(engine):
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
