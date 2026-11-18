"""Binary-safe backups of the local PostgreSQL container."""

import argparse
import os
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

API_ROOT = Path(__file__).resolve().parents[2]


class LocalPostgresBackup:
    def __init__(self, env_file: Path, project: str = "medved_local"):
        env_file = env_file.resolve(strict=True)
        values = dotenv_values(env_file)
        self.user = values.get("POSTGRES_USER") or "medved"
        self.database = values.get("POSTGRES_DB") or "medved"
        self.prefix = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(env_file),
            "-f",
            str(API_ROOT / "compose.postgres.yaml"),
            "exec",
            "-T",
            "postgres",
        ]

    def _run(self, command: list[str], *, stdin=None, stdout=None) -> None:
        try:
            result = subprocess.run(
                self.prefix + command,
                stdin=stdin,
                stdout=stdout or subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError:
            raise RuntimeError(
                "Cannot start Docker; check that the local database container is running"
            ) from None
        if result.returncode:
            raise RuntimeError(
                f"{command[0]} failed (exit {result.returncode}); existing databases were not overwritten"
            )

    def backup(self, output: Path) -> Path:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as archive:
                self._run(
                    [
                        "pg_dump",
                        "--format=custom",
                        "--no-owner",
                        "--no-privileges",
                        "--username=" + self.user,
                        "--dbname=" + self.database,
                    ],
                    stdout=archive,
                )
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        return output

    def restore(self, archive: Path, database: str) -> str:
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}", database) or database in {
            self.database,
            "postgres",
            "template0",
            "template1",
        }:
            raise ValueError(
                "Choose a new database name, different from the source and system databases"
            )
        with archive.resolve(strict=True).open("rb") as source:
            # createdb refuses an existing target; pg_restore never uses --clean or --create.
            self._run(
                [
                    "createdb",
                    "--username=" + self.user,
                    "--template=template0",
                    "--",
                    database,
                ]
            )
            self._run(
                [
                    "pg_restore",
                    "--single-transaction",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    "--username=" + self.user,
                    "--dbname=" + database,
                ],
                stdin=source,
            )
        return database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--project", default="medved_local")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup").add_argument("output", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--database", required=True)
    args = parser.parse_args()
    manager = LocalPostgresBackup(args.env_file, args.project)
    if args.command == "backup":
        print(
            f"Backup created: {manager.backup(args.output)}; preserve the AES key separately"
        )
    else:
        print(
            f"Restored into new database: {manager.restore(args.archive, args.database)}"
        )


if __name__ == "__main__":
    main()
