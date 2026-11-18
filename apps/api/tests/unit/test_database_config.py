import pytest

pytest.importorskip("sqlalchemy", reason="Install the postgres extra")
pytest.importorskip("asyncpg", reason="Install the postgres extra")

from app.core.config import Settings
from app.db.engine import create_engine


def test_database_url_comes_from_environment_and_is_hidden(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://synthetic:secret@localhost/medved")
    settings = Settings.from_env()
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert "synthetic:secret" not in repr(settings)
    engine = create_engine()
    assert engine.sync_engine.hide_parameters is True
    assert engine.echo is False


@pytest.mark.parametrize("value", ["", "sqlite+aiosqlite:///test.db", "postgresql://localhost/test"])
def test_database_url_requires_postgres_asyncpg(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(ValueError):
        create_engine()
