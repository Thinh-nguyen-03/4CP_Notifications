from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_session, require_client
from app.models import Prediction

router = APIRouter(prefix="/api", tags=["predictions"], dependencies=[Depends(require_client)])


class PredictionItem(BaseModel):
    forecast_date: date
    peak_load_gwh: float
    peak_hour: str
    cp_score: int


class PredictionBatchResponse(BaseModel):
    slot: str
    cp_day_called: date
    forecast_interval: str
    fetched_at: datetime
    predictions: list[PredictionItem]


class MonthlyPeakItem(BaseModel):
    month: int
    month_name: str
    peak_timestamp: datetime
    adjusted_interval: datetime
    peak_mw: int
    peak_gw: float
    peak_hour: str


class PeaksResponse(BaseModel):
    season_year: int
    monthly_peaks: list[MonthlyPeakItem]


class LatestResponse(BaseModel):
    predictions: PredictionBatchResponse | None
    peaks: PeaksResponse | None
    last_updated: datetime | None


def _format_interval_str(start: date) -> str:
    end = start + timedelta(days=6)
    return f"{start.strftime('%B')} {start.day}, {start.year} - {end.strftime('%B')} {end.day}, {end.year}"


async def _get_latest_batch(
    session: AsyncSession, slot: str | None
) -> tuple[date, str] | None:
    stmt = select(Prediction.cp_day_called, Prediction.slot)
    if slot:
        stmt = stmt.where(Prediction.slot == slot)
    stmt = stmt.order_by(Prediction.cp_day_called.desc(), Prediction.fetched_at.desc()).limit(1)
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return row[0], row[1]


@router.get("/predictions", response_model=PredictionBatchResponse)
async def get_predictions(
    slot: str | None = Query(None, pattern="^(3AM|11AM)$"),
    cp_day: date | None = Query(None, description="cp_day_called date (default: latest)"),
    session: AsyncSession = Depends(get_session),
) -> PredictionBatchResponse:
    if cp_day is None or slot is None:
        latest = await _get_latest_batch(session, slot)
        if latest is None:
            raise HTTPException(status_code=404, detail="No predictions available")
        cp_day, slot = latest

    stmt = (
        select(Prediction)
        .where(Prediction.slot == slot, Prediction.cp_day_called == cp_day)
        .order_by(Prediction.forecast_date)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No predictions for given slot/day")

    return PredictionBatchResponse(
        slot=slot,
        cp_day_called=cp_day,
        forecast_interval=_format_interval_str(cp_day),
        fetched_at=max(r.fetched_at for r in rows),
        predictions=[
            PredictionItem(
                forecast_date=r.forecast_date,
                peak_load_gwh=float(r.peak_load_gwh),
                peak_hour=r.peak_hour,
                cp_score=r.cp_score,
            )
            for r in rows
        ],
    )
