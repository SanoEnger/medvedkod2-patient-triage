"""Backend environment settings. No secrets are placed in source control."""

import os
from dataclasses import dataclass, field


def _csv(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    core_url: str = "https://tm-test-yakut.hostco.ru"
    core_service_token: str = ""
    session_signing_key: str = ""
    demo_mode: bool = False
    cors_origins: tuple[str, ...] = field(default_factory=tuple)
    frame_ancestors: tuple[str, ...] = ("'self'",)
    auth_ttl_seconds: int = 3600
    survey_ttl_seconds: int = 86400
    core_timeout_seconds: float = 6.0
    database_url: str = field(default="", repr=False)
    database_ssl_ca_file: str = ""
    data_encryption_key_file: str = field(default="", repr=False)
    api_tls_cert_file: str = ""
    api_tls_key_file: str = field(default="", repr=False)
    api_host: str = "127.0.0.1"
    api_port: int = 8443

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            core_url=os.getenv("CORE_URL", cls.core_url).rstrip("/"),
            core_service_token=os.getenv("CORE_SERVICE_TOKEN", ""),
            session_signing_key=os.getenv("SESSION_SIGNING_KEY", ""),
            demo_mode=os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes"),
            cors_origins=_csv(os.getenv("CORS_ORIGINS", "")),
            frame_ancestors=_csv(os.getenv("FRAME_ANCESTORS", "'self'")),
            auth_ttl_seconds=int(os.getenv("AUTH_TTL_SECONDS", "3600")),
            survey_ttl_seconds=min(int(os.getenv("SURVEY_TTL_SECONDS", "86400")), 86400),
            core_timeout_seconds=float(os.getenv("CORE_TIMEOUT_SECONDS", "6")),
            database_url=os.getenv("DATABASE_URL", ""),
            database_ssl_ca_file=os.getenv("DATABASE_SSL_CA_FILE", ""),
            data_encryption_key_file=os.getenv("DATA_ENCRYPTION_KEY_FILE", ""),
            api_tls_cert_file=os.getenv("API_TLS_CERT_FILE", ""),
            api_tls_key_file=os.getenv("API_TLS_KEY_FILE", ""),
            api_host=os.getenv("API_HOST", "127.0.0.1"),
            api_port=int(os.getenv("API_PORT", "8443")),
        )

    def validate(self) -> None:
        if not self.session_signing_key or len(self.session_signing_key) < 32:
            raise ValueError("SESSION_SIGNING_KEY must contain at least 32 characters")
        if self.auth_ttl_seconds < 60 or self.auth_ttl_seconds > 86400:
            raise ValueError("Invalid AUTH_TTL_SECONDS")
        if self.survey_ttl_seconds < 60 or self.survey_ttl_seconds > 86400:
            raise ValueError("Invalid SURVEY_TTL_SECONDS")
        if not self.core_url.startswith("https://"):
            raise ValueError("CORE_URL must be HTTPS")
        if self.core_timeout_seconds <= 0 or self.core_timeout_seconds > 8:
            raise ValueError("Invalid CORE_TIMEOUT_SECONDS")
        for origin in self.cors_origins:
            if not origin.startswith(("https://", "http://localhost", "http://127.0.0.1")):
                raise ValueError("CORS_ORIGINS must contain explicit trusted origins")
