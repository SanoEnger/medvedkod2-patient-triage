import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.engine import create_engine
from app.db.repository import delete_expired_sessions


async def main() -> None:
    engine = create_engine()
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory.begin() as db:
            count = await delete_expired_sessions(db)
        print(json.dumps({"deleted_sessions": count}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Delete expired sessions, audit events and nonces"
    )
    parser.add_argument("--env-file")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    asyncio.run(main())
