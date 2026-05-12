import asyncio
import logging
import sys
import traceback
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker, engine
from app.db_init import create_tables
from app.fetchers.amperon import fetch_amperon
from app.fetchers.nrgstream import fetch_demand_readings
from app.models import FetchRun
from app.services.peaks import compute_monthly_peaks, upsert_monthly_peaks
from app.services.predictions import upsert_predictions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("fetch_all")


async def _record_run_start(session: AsyncSession, source: str, slot: str | None = None) -> FetchRun:
    run = FetchRun(source=source, slot=slot, status="running")
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def _record_run_end(
    session: AsyncSession,
    run: FetchRun,
    status: str,
    rows_written: int | None = None,
    error: str | None = None,
) -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.rows_written = rows_written
    run.error = error
    await session.commit()


async def run_amperon() -> bool:
    async with async_session_maker() as session:
        run = await _record_run_start(session, source="amperon")
        try:
            batch = await fetch_amperon()
            run.slot = batch.slot
            written = await upsert_predictions(session, batch)
            await _record_run_end(session, run, "success", rows_written=written)
            log.info("amperon: stored %d predictions for slot=%s cp_day=%s", written, batch.slot, batch.cp_day_called)
            return True
        except Exception as e:
            log.exception("amperon fetch failed")
            await _record_run_end(session, run, "failed", error=f"{e}\n{traceback.format_exc()}")
            return False


async def run_nrgstream() -> bool:
    async with async_session_maker() as session:
        run = await _record_run_start(session, source="nrgstream")
        try:
            season_year = datetime.now().year
            readings = await fetch_demand_readings(season_year)
            peaks = compute_monthly_peaks(readings)
            written = await upsert_monthly_peaks(session, peaks)
            await _record_run_end(session, run, "success", rows_written=written)
            log.info("nrgstream: updated %d monthly peaks for year=%s", written, season_year)
            return True
        except Exception as e:
            log.exception("nrgstream fetch failed")
            await _record_run_end(session, run, "failed", error=f"{e}\n{traceback.format_exc()}")
            return False


async def main() -> int:
    await create_tables()
    amperon_ok = await run_amperon()
    nrgstream_ok = await run_nrgstream()
    await engine.dispose()
    return 0 if (amperon_ok and nrgstream_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
