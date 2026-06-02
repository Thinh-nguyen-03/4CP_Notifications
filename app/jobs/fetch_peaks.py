"""
NRGStream monthly peaks only — no Amperon pull, no view token, no email.

Usage (from cloud_api/, with DATABASE_URL and NRGSTREAM_* set):

    python -m app.jobs.fetch_peaks
"""
import asyncio
import logging
import sys

from app.database import engine
from app.db_init import create_tables
from app.jobs.fetch_all import run_nrgstream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("fetch_peaks")


async def main() -> int:
    await create_tables()
    ok = await run_nrgstream()
    await engine.dispose()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
