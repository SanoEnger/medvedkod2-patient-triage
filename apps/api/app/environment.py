"""Load only the API's local .env; deployment environment takes precedence."""

import os
from pathlib import Path

from dotenv import load_dotenv


def load_local_environment() -> None:
    if os.getenv("MEDVED_DISABLE_DOTENV") != "1":
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False, encoding="utf-8-sig")
