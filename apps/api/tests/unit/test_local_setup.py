from app.core.local_setup import generate
from cryptography import x509
from dotenv import dotenv_values


def test_local_setup_preserves_existing_keys_and_separates_databases(tmp_path):
    directory = tmp_path / "runtime"
    env_path = generate(directory)
    values = dotenv_values(env_path)
    assert values["DATABASE_URL"].endswith(":55432/medved")
    assert values["TEST_DATABASE_URL"].endswith(":55433/medved_test")
    assert len(values["POSTGRES_PASSWORD"]) >= 32
    assert values["POSTGRES_PASSWORD"] in values["DATABASE_URL"]
    for name in ("api", "postgres"):
        cert = x509.load_pem_x509_certificate((directory / f"{name}.crt").read_bytes())
        cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
        assert "localhost" in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    before = (directory / "encryption.key").read_bytes()
    import pytest

    with pytest.raises(ValueError, match="never overwritten"):
        generate(directory)
    assert (directory / "encryption.key").read_bytes() == before
