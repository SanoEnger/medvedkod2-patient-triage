"""Bootstrap and run the local Compose stack without credentials in images."""

import argparse
import os
import shutil
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

from dotenv import dotenv_values, load_dotenv
from sqlalchemy.engine import make_url

from app.core.local_setup import generate

RUNTIME = Path("/run/medved")
POSTGRES_SECRETS = Path("/run/postgres-secrets")
WEB_SECRETS = Path("/run/web-secrets")


def initialize(runtime: Path, postgres: Path, web: Path) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    if not any(runtime.iterdir()):
        generate(runtime)
    required = (
        "backend.env", "encryption.key", "ca.crt", "ca.key",
        "api.crt", "api.key", "postgres.crt", "postgres.key",
    )
    if not all((runtime / name).is_file() for name in required):
        raise ValueError("Incomplete Docker secrets; restore the existing volume, do not replace keys")
    values = dotenv_values(runtime / "backend.env")
    postgres.mkdir(parents=True, exist_ok=True)
    web.mkdir(parents=True, exist_ok=True)
    for source, target in (
        (runtime / "postgres.crt", postgres / "postgres.crt"),
        (runtime / "postgres.key", postgres / "postgres.key"),
        (runtime / "ca.crt", web / "ca.crt"),
        (runtime / "api.crt", web / "web.crt"),
        (runtime / "api.key", web / "web.key"),
    ):
        shutil.copyfile(source, target)
    (postgres / "password").write_text(values["POSTGRES_PASSWORD"], encoding="utf-8")
    for path in (runtime / "backend.env", runtime / "encryption.key", runtime / "api.key"):
        path.chmod(0o600)
        if hasattr(os, "chown"):
            os.chown(path, 10001, 10001)
    for path, uid in ((runtime / "ca.key", 0), (runtime / "postgres.key", 0),
                      (postgres / "postgres.key", 0), (postgres / "password", 0),
                      (web / "web.key", 101)):
        path.chmod(0o600)
        if hasattr(os, "chown"):
            os.chown(path, uid, uid)


def configure(runtime: Path = RUNTIME) -> None:
    load_dotenv(runtime / "backend.env", override=False)
    url = make_url(os.environ["DATABASE_URL"]).set(host="postgres", port=5432)
    os.environ.update(
        DATABASE_URL=url.render_as_string(hide_password=False),
        DATABASE_SSL_CA_FILE=str(runtime / "ca.crt"),
        DATA_ENCRYPTION_KEY_FILE=str(runtime / "encryption.key"),
        API_TLS_CERT_FILE=str(runtime / "api.crt"),
        API_TLS_KEY_FILE=str(runtime / "api.key"),
        API_HOST="0.0.0.0", API_PORT="8443",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "serve", "health"))
    command = parser.parse_args().command
    if command == "init":
        initialize(RUNTIME, POSTGRES_SECRETS, WEB_SECRETS)
    elif command == "health":
        context = ssl.create_default_context(cafile=str(RUNTIME / "ca.crt"))
        with urlopen("https://localhost:8443/health", context=context, timeout=3) as response:
            if response.status != 200:
                raise SystemExit(1)
    else:
        configure()
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
        os.execv(sys.executable, [sys.executable, "-m", "app.run_api"])


if __name__ == "__main__":
    main()
