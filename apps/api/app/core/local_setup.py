"""Generate local synthetic-development keys and TLS certificates; never production credentials."""

import argparse
import base64
import ipaddress
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def write(path: Path, value: bytes, private: bool = False) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644)
    with os.fdopen(descriptor, "wb") as output:
        output.write(value)


def private_key(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def generate(directory: Path, db_port: int = 55432, api_port: int = 8443, *, test_db_port: int = 55433) -> Path:
    if db_port == test_db_port or not all(1 <= port <= 65535 for port in (db_port, api_port, test_db_port)):
        raise ValueError("Choose valid, separate database ports")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("Choose an empty directory; existing keys are never overwritten")
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MedVed local test CA")])
    ca = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    write(directory / "ca.key", private_key(ca_key), private=True)
    write(directory / "ca.crt", ca.public_bytes(serialization.Encoding.PEM))
    for name in ("api", "postgres"):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        cert = (
            x509.CertificateBuilder().subject_name(subject).issuer_name(ca.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.DNSName("postgres-test"), x509.DNSName("postgres"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.IPAddress(ipaddress.ip_address("::1")),
            ]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        write(directory / f"{name}.key", private_key(key), private=True)
        write(directory / f"{name}.crt", cert.public_bytes(serialization.Encoding.PEM))
    write(directory / "encryption.key", base64.urlsafe_b64encode(secrets.token_bytes(32)), private=True)
    database_password = secrets.token_urlsafe(32)
    values = {
        "DATABASE_URL": f"postgresql+asyncpg://medved:{database_password}@127.0.0.1:{db_port}/medved",
        "POSTGRES_DB": "medved", "POSTGRES_USER": "medved",
        "POSTGRES_PASSWORD": database_password, "POSTGRES_PORT": str(db_port),
        "TEST_DATABASE_URL": f"postgresql+asyncpg://medved_test:synthetic-test-only@127.0.0.1:{test_db_port}/medved_test",
        "DATABASE_SSL_CA_FILE": (directory / "ca.crt").as_posix(),
        "DATA_ENCRYPTION_KEY_FILE": (directory / "encryption.key").as_posix(),
        "SESSION_SIGNING_KEY": secrets.token_urlsafe(48),
        "API_TLS_CERT_FILE": (directory / "api.crt").as_posix(),
        "API_TLS_KEY_FILE": (directory / "api.key").as_posix(),
        "API_HOST": "127.0.0.1", "API_PORT": str(api_port),
        "DEMO_MODE": "true", "TLS_DIR": directory.as_posix(),
        "TEST_POSTGRES_PORT": str(test_db_port),
        "CORS_ORIGINS": "http://127.0.0.1:5173,http://localhost:5173",
    }
    content = "".join(f'{key}="{value}"\n' for key, value in values.items())
    write(directory / "backend.env", content.encode("utf-8"), private=True)
    return directory / "backend.env"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--db-port", type=int, default=55432)
    parser.add_argument("--test-db-port", type=int, default=55433)
    parser.add_argument("--api-port", type=int, default=8443)
    args = parser.parse_args()
    path = generate(args.directory, args.db_port, args.api_port, test_db_port=args.test_db_port)
    print(f"Local credentials written to {path}; keep this directory out of Git")


if __name__ == "__main__":
    main()
