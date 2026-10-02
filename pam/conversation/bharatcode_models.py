"""Safe local BharatCode model-catalog diagnostic."""

from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from pam.config import Settings


async def run() -> None:
    """Print only public model IDs from the configured BharatCode endpoint."""
    settings = Settings()
    if settings.bharatcode_api_key is None:
        raise ValueError("PAM_BHARATCODE_API_KEY is required")
    client = AsyncOpenAI(
        api_key=settings.bharatcode_api_key.get_secret_value(),
        base_url=settings.bharatcode_base_url,
        max_retries=1,
        timeout=20.0,
    )
    models = await client.models.list()
    for model in models.data:
        print(model.id)


def main() -> None:
    """Run model discovery without printing credentials or headers."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
