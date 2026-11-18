import argparse
import ssl
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from app.core.config import Settings


def create_config(settings: Settings) -> uvicorn.Config:
    if not settings.api_tls_cert_file or not settings.api_tls_key_file:
        raise ValueError("API_TLS_CERT_FILE and API_TLS_KEY_FILE are required")
    if not Path(settings.api_tls_cert_file).is_file() or not Path(settings.api_tls_key_file).is_file():
        raise ValueError("API TLS certificate/key files do not exist")
    config = uvicorn.Config(
        "app.main:create_app", factory=True,
        host=settings.api_host, port=settings.api_port,
        ssl_certfile=settings.api_tls_cert_file, ssl_keyfile=settings.api_tls_key_file,
        ssl_version=ssl.PROTOCOL_TLS_SERVER, proxy_headers=False, access_log=False,
    )
    config.load()
    config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the API with HTTPS only")
    parser.add_argument("--env-file")
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    settings = Settings.from_env()
    settings.validate()
    uvicorn.Server(create_config(settings)).run()


if __name__ == "__main__":
    main()
