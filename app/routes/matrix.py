"""
The prediction history as a matrix of (call day x target day).

Every Amperon run writes one *row*: seven forecast_dates called from a single
cp_day_called.  Reading down a *column* instead — fixing forecast_date and
walking cp_day_called forward — shows how one day's forecast evolved as it
approached.  Both the evolution and rewind views slice this one payload
client-side, so neither refetches on interaction.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_session, require_client
from app.models import DailyPeak, Prediction
from app.serialization import ApiDateTime
from app.services.peaks import adjusted_interval, peak_hour_label

router = APIRouter(prefix="/api", tags=["matrix"], dependencies=[Depends(require_client)])

SLOT_ORDER = {"3AM": 0, "11AM": 1}


class MatrixCell(BaseModel):
    cp_day_called: date
    slot: str
    forecast_date: date
    lead_days: int
    cp_score: int
    peak_load_gwh: float
    peak_hour: str


class MatrixSnapshot(BaseModel):
    """One Amperon run: identifies a row of the matrix."""

    cp_day_called: date
    slot: str
    fetched_at: ApiDateTime


class ActualPeak(BaseModel):
    peak_date: date
    peak_timestamp: ApiDateTime
    adjusted_interval: ApiDateTime
    peak_mw: int
    peak_gw: float
    peak_hour: str


class MatrixResponse(BaseModel):
    days: int
    snapshots: list[MatrixSnapshot]
    cells: list[MatrixCell]
    actuals: list[ActualPeak]


async def assemble_matrix(session: AsyncSession, days: int) -> MatrixResponse:
    cutoff = date.today() - timedelta(days=days)

    rows = (
        await session.execute(
            select(Prediction)
            .where(Prediction.cp_day_called >= cutoff)
            .order_by(Prediction.cp_day_called, Prediction.forecast_date)
        )
    ).scalars().all()

    actual_rows = (
        await session.execute(
            select(DailyPeak)
            .where(DailyPeak.peak_date >= cutoff)
            .order_by(DailyPeak.peak_date)
        )
    ).scalars().all()

    snapshots: dict[tuple[date, str], MatrixSnapshot] = {}
    for r in rows:
        key = (r.cp_day_called, r.slot)
        existing = snapshots.get(key)
        if existing is None or r.fetched_at > existing.fetched_at:
            snapshots[key] = MatrixSnapshot(
                cp_day_called=r.cp_day_called, slot=r.slot, fetched_at=r.fetched_at
            )

    return MatrixResponse(
        days=days,
        snapshots=sorted(
            snapshots.values(),
            key=lambda s: (s.cp_day_called, SLOT_ORDER.get(s.slot, 99)),
        ),
        cells=[
            MatrixCell(
                cp_day_called=r.cp_day_called,
                slot=r.slot,
                forecast_date=r.forecast_date,
                lead_days=(r.forecast_date - r.cp_day_called).days,
                cp_score=r.cp_score,
                peak_load_gwh=float(r.peak_load_gwh),
                peak_hour=r.peak_hour,
            )
            for r in rows
        ],
        actuals=[
            ActualPeak(
                peak_date=a.peak_date,
                peak_timestamp=a.peak_timestamp,
                adjusted_interval=adjusted_interval(a.peak_timestamp),
                peak_mw=a.peak_mw,
                peak_gw=round(a.peak_mw / 1000, 3),
                peak_hour=peak_hour_label(a.peak_timestamp),
            )
            for a in actual_rows
        ],
    )


@router.get("/matrix", response_model=MatrixResponse)
async def get_matrix(
    days: int = Query(30, ge=1, le=365, description="Look-back window on cp_day_called"),
    session: AsyncSession = Depends(get_session),
) -> MatrixResponse:
    return await assemble_matrix(session, days)
