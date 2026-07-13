"""
Daily fetch job — runs at 3:05 AM and 11:05 AM CT.

Workflow per run:
  1. Pull predictions from Amperon
  2. Pull/update monthly peaks from NRGStream
  3. Generate a single time-limited view token
  4. Email the dashboard link (BCC) to all configured recipients
"""
import asyncio
import logging
import sys
import traceback
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_maker, engine
from app.db_init import create_tables
from app.fetchers.amperon import PredictionBatch, fetch_amperon
from app.fetchers.nrgstream import fetch_demand_readings
from app.models import FetchRun
from app.routes.predictions import format_forecast_interval
from app.services.email import send_dashboard_email
from app.services.peaks import (
    compute_daily_peaks,
    compute_monthly_peaks,
    upsert_daily_peaks,
    upsert_monthly_peaks,
)
from app.services.predictions import upsert_predictions
from app.services.view_token import create_view_token, mark_email_sent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("fetch_all")


async def _record_run_start(
    session: AsyncSession, source: str, slot: str | None = None
) -> FetchRun:
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


async def run_amperon() -> tuple[bool, PredictionBatch | None]:
    """Fetch and store Amperon predictions.  Returns (success, batch)."""
    async with async_session_maker() as session:
        run = await _record_run_start(session, source="amperon")
        try:
            batch = await fetch_amperon()
            run.slot = batch.slot
            written = await upsert_predictions(session, batch)
            await _record_run_end(session, run, "success", rows_written=written)
            log.info(
                "amperon: stored %d predictions slot=%s cp_day=%s",
                written,
                batch.slot,
                batch.cp_day_called,
            )
            return True, batch
        except Exception as e:
            log.exception("amperon fetch failed")
            await _record_run_end(session, run, "failed", error=f"{e}\n{traceback.format_exc()}")
            return False, None


async def run_nrgstream() -> bool:
    """Fetch and store NRGStream monthly peaks."""
    async with async_session_maker() as session:
        run = await _record_run_start(session, source="nrgstream")
        try:
            season_year = datetime.now().year
            readings = await fetch_demand_readings(season_year)
            monthly = await upsert_monthly_peaks(session, compute_monthly_peaks(readings))
            daily = await upsert_daily_peaks(session, compute_daily_peaks(readings))
            await _record_run_end(session, run, "success", rows_written=monthly + daily)
            log.info(
                "nrgstream: updated %d monthly peaks, %d daily peaks year=%s",
                monthly,
                daily,
                season_year,
            )
            return True
        except Exception as e:
            log.warning("nrgstream fetch failed: %s", e)
            await _record_run_end(session, run, "failed", error=str(e))
            return False


async def run_notify(batch: PredictionBatch) -> None:
    """
    Create a view token for the just-fetched report and email the dashboard link.
    A fresh token is generated on every successful Amperon run so the link in the
    latest email always works independently of the previous one.
    """
    async with async_session_maker() as session:
        raw_token = await create_view_token(session, batch.slot, batch.cp_day_called)

        view_url = f"{settings.base_url.rstrip('/')}/r/{raw_token}"
        interval = format_forecast_interval([p.forecast_date for p in batch.predictions])

        try:
            await send_dashboard_email(view_url, interval, slot=batch.slot)
            # Reload the token row (created in the session above, then committed)
            from app.services.view_token import validate_view_token
            token_row = await validate_view_token(session, raw_token)
            if token_row:
                await mark_email_sent(session, token_row)
        except Exception:
            log.exception("Email delivery failed (token was still created: %s)", view_url)


async def main() -> int:
    await create_tables()

    if settings.use_mock_fetchers:
        log.warning(
            "USE_MOCK_FETCHERS is enabled — Amperon and NRGStream use synthetic data only "
            "(unset for production)."
        )

    amperon_ok, batch = await run_amperon()
    nrgstream_ok = await run_nrgstream()

    if amperon_ok and batch:
        await run_notify(batch)
    else:
        log.warning("Skipping email notification because Amperon fetch failed")

    await engine.dispose()
    # Amperon + notify are required; NRGStream peaks are best-effort
    return 0 if amperon_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
