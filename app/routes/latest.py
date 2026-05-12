from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_session, require_client
from app.models import MonthlyPeak
from app.routes.peaks import get_peaks
from app.routes.predictions import LatestResponse, get_predictions

router = APIRouter(prefix="/api", tags=["latest"], dependencies=[Depends(require_client)])


@router.get("/latest", response_model=LatestResponse)
async def get_latest(session: AsyncSession = Depends(get_session)) -> LatestResponse:
    predictions = None
    peaks = None

    try:
        predictions = await get_predictions(slot=None, cp_day=None, session=session)
    except Exception:
        predictions = None

    try:
        peaks = await get_peaks(season_year=None, session=session)
    except Exception:
        peaks = None

    last_updated_candidates: list[datetime] = []
    if predictions:
        last_updated_candidates.append(predictions.fetched_at)
    if peaks:
        peak_updated = (
            await session.execute(select(MonthlyPeak.updated_at).order_by(MonthlyPeak.updated_at.desc()).limit(1))
        ).scalar_one_or_none()
        if peak_updated:
            last_updated_candidates.append(peak_updated)

    return LatestResponse(
        predictions=predictions,
        peaks=peaks,
        last_updated=max(last_updated_candidates) if last_updated_candidates else None,
    )
