import argparse
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.clinic_catalog import import_catalog
from app.db.engine import create_engine
from app.schemas.clinics import ClinicCatalog


async def run(path: Path):
    catalog = ClinicCatalog.model_validate_json(path.read_bytes())
    settings = Settings.from_env()
    if catalog.demo and not settings.demo_mode:
        raise SystemExit("Importing the demo catalog requires DEMO_MODE=true")
    engine = create_engine(settings=settings)
    try:
        async with async_sessionmaker(engine).begin() as db:
            await import_catalog(db, catalog)
    finally:
        await engine.dispose()
    print(f"Imported {len(catalog.branches)} clinic branches")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import a MedVed clinic catalog")
    parser.add_argument("path", type=Path)
    asyncio.run(run(parser.parse_args().path))
