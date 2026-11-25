import asyncio

from alembic import context
from app.core.config import Settings
from app.db.engine import create_engine
from app.db import clinic_addresses, clinic_catalog, clinic_sources  # noqa: F401 - register catalog tables
from app.db.models import Base

env_file = context.get_x_argument(as_dictionary=True).get("env_file")
if env_file:
    from dotenv import load_dotenv

    load_dotenv(env_file, override=False)

target_metadata = Base.metadata


def configure(connection=None) -> None:
    options = {
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
    }
    if connection is None:
        url = Settings.from_env().database_url
        if not url:
            raise ValueError("DATABASE_URL is required for migrations")
        context.configure(
            url=url, literal_binds=True,
            dialect_opts={"paramstyle": "named"}, **options,
        )
    else:
        context.configure(connection=connection, **options)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            await connection.run_sync(configure)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    configure()
else:
    asyncio.run(run_online())
