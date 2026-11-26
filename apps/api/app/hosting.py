"""Translate managed PostgreSQL URLs; certificate verification stays in engine.py."""
import os
import subprocess
import sys

from sqlalchemy.engine import make_url


def prepare_environment():
    if os.getenv("VERCEL") != "1" or not os.getenv("DATABASE_URL"):
        return
    url = make_url(os.environ["DATABASE_URL"])
    if url.drivername not in ("postgres", "postgresql", "postgresql+asyncpg"):
        raise ValueError("Hosted database must be PostgreSQL")
    options = dict(url.query)
    if options.pop("sslmode", "verify-full") not in ("require", "verify-ca", "verify-full"):
        raise ValueError("Hosted database requires verified TLS")
    # libpq-only options are not asyncpg arguments. The engine always verifies
    # the server hostname and certificate using a TLS 1.2+ SSLContext.
    options.pop("channel_binding", None)
    os.environ["DATABASE_URL"] = url.set(drivername="postgresql+asyncpg", query=options).render_as_string(hide_password=False)


if __name__ == "__main__":
    prepare_environment()
    raise SystemExit(subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"]))
