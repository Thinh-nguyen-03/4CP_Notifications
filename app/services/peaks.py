from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.fetchers.nrgstream import DemandReading
from app.models import DailyPeak, MonthlyPeak

TARGET_MONTHS = (6, 7, 8, 9)


def adjusted_interval(ts: datetime) -> datetime:
    """Round timestamp up to the next top-of-hour (HE convention)."""
    return ts.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def peak_hour_label(ts: datetime) -> str:
    """HE label for a peak timestamp, e.g. 17:00 -> 'HE18', 23:00 -> 'HE24'."""
    return f"HE{adjusted_interval(ts).hour or 24}"


def compute_monthly_peaks(
    readings: list[DemandReading],
) -> dict[tuple[int, int], DemandReading]:
    """Return {(season_year, month): peak_reading} for June–September."""
    buckets: dict[tuple[int, int], DemandReading] = {}
    for r in readings:
        if r.timestamp.month not in TARGET_MONTHS:
            continue
        key = (r.timestamp.year, r.timestamp.month)
        current = buckets.get(key)
        if current is None or r.mw > current.mw:
            buckets[key] = r
    return buckets


async def upsert_monthly_peaks(
    session: AsyncSession, peaks: dict[tuple[int, int], DemandReading]
) -> int:
    if not peaks:
        return 0

    rows = [
        {
            "season_year": year,
            "month": month,
            "peak_timestamp": reading.timestamp,
            "peak_mw": int(round(reading.mw)),
        }
        for (year, month), reading in peaks.items()
    ]

    stmt = insert(MonthlyPeak).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["season_year", "month"],
        set_={
            "peak_timestamp": stmt.excluded.peak_timestamp,
            "peak_mw": stmt.excluded.peak_mw,
        },
        where=(MonthlyPeak.peak_mw < stmt.excluded.peak_mw),
    )

    await session.execute(stmt)
    await session.commit()
    return len(rows)


def compute_daily_peaks(readings: list[DemandReading]) -> dict[date, DemandReading]:
    """Return {calendar_date: peak_reading} across every day present in the feed."""
    buckets: dict[date, DemandReading] = {}
    for r in readings:
        key = r.timestamp.date()
        current = buckets.get(key)
        if current is None or r.mw > current.mw:
            buckets[key] = r
    return buckets


async def upsert_daily_peaks(
    session: AsyncSession, peaks: dict[date, DemandReading]
) -> int:
    if not peaks:
        return 0

    rows = [
        {
            "peak_date": day,
            "peak_timestamp": reading.timestamp,
            "peak_mw": int(round(reading.mw)),
        }
        for day, reading in peaks.items()
    ]

    stmt = insert(DailyPeak).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["peak_date"],
        set_={
            "peak_timestamp": stmt.excluded.peak_timestamp,
            "peak_mw": stmt.excluded.peak_mw,
        },
        # A mid-day run sees a partial day; only ever revise the peak upward.
        where=(DailyPeak.peak_mw < stmt.excluded.peak_mw),
    )

    await session.execute(stmt)
    await session.commit()
    return len(rows)
