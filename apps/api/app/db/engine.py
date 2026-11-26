import ssl

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


def create_engine(
    database_url: str | None = None,
    *,
    settings: Settings | None = None,
) -> AsyncEngine:
    settings = settings or Settings.from_env()
    database_url = database_url or settings.database_url
    if not database_url:
        raise ValueError("DATABASE_URL is required for PostgreSQL storage")
    url = make_url(database_url)
    if url.drivername != "postgresql+asyncpg":
        raise ValueError("DATABASE_URL must use postgresql+asyncpg")
    if any(key.lower() in {"ssl", "sslmode"} for key in url.query):
        raise ValueError("Database TLS cannot be overridden in DATABASE_URL")
    tls = ssl.create_default_context(cafile=settings.database_ssl_ca_file or None)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    return create_async_engine(
        url,
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={"ssl": tls},
    )
