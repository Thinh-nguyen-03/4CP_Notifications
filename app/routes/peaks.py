from calendar import month_name as _month_name
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_session, require_client
from app.models import MonthlyPeak
from app.routes.predictions import MonthlyPeakItem, PeaksResponse
from app.services.peaks import adjusted_interval

router = APIRouter(prefix="/api", tags=["peaks"], dependencies=[Depends(require_client)])


def _peak_hour_label(ts: datetime) -> str:
    return f"HE{adjusted_interval(ts).hour or 24}"


@router.get("/peaks", response_model=PeaksResponse)
async def get_peaks(
    season_year: int | None = Query(None, description="Defaults to most recent year with data"),
    session: AsyncSession = Depends(get_session),
) -> PeaksResponse:
    if season_year is None:
        stmt = select(MonthlyPeak.season_year).order_by(MonthlyPeak.season_year.desc()).limit(1)
        row = (await session.execute(stmt)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="No peak data available")
        season_year = row[0]

    rows = (
        await session.execute(
            select(MonthlyPeak)
            .where(MonthlyPeak.season_year == season_year)
            .order_by(MonthlyPeak.month)
        )
    ).scalars().all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No peak data for {season_year}")

    return PeaksResponse(
        season_year=season_year,
        monthly_peaks=[
            MonthlyPeakItem(
                month=r.month,
                month_name=_month_name[r.month],
                peak_timestamp=r.peak_timestamp,
                adjusted_interval=adjusted_interval(r.peak_timestamp),
                peak_mw=r.peak_mw,
                peak_gw=round(r.peak_mw / 1000, 3),
                peak_hour=_peak_hour_label(r.peak_timestamp),
            )
            for r in rows
        ],
    )
