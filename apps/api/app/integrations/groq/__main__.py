"""Offline synthetic demonstration: python -m app.integrations.groq."""

import asyncio

from . import MockGroqClient, SymptomExtractor


async def main() -> None:
    result = await SymptomExtractor(MockGroqClient()).extract("У меня сильно болит грудь, тяжело дышать")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
