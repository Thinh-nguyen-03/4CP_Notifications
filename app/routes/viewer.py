"""
Public viewer routes — authenticated via a time-limited ViewToken embedded in
the email link.  No bearer API key is required.

  GET /r/{token}                    → renders the dashboard HTML
  GET /api/report/{token}           → returns LatestResponse JSON
  GET /api/report/{token}/predictions?slot=3AM|11AM  → PredictionBatchResponse JSON
  GET /api/report/{token}/matrix?days=150            → MatrixResponse JSON
"""
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_session
from app.models import MonthlyPeak, Prediction
from app.routes.matrix import MatrixResponse, assemble_matrix
from app.routes.predictions import (
    LatestResponse,
    MonthlyPeakItem,
    PeaksResponse,
    PredictionBatchResponse,
    PredictionItem,
    format_forecast_interval,
    _get_latest_batch,
)
from app.services.peaks import adjusted_interval, peak_hour_label
from app.services.view_token import validate_view_token

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(tags=["viewer"])


async def _assemble_peaks(session: AsyncSession) -> PeaksResponse:
    """Most recent season with peak rows, or current calendar year with an empty list."""
    row = (
        await session.execute(
            select(MonthlyPeak.season_year).order_by(MonthlyPeak.season_year.desc()).limit(1)
        )
    ).first()
    if row is None:
        return PeaksResponse(season_year=date.today().year, monthly_peaks=[])
    season_year = row[0]
    rows = (
        await session.execute(
            select(MonthlyPeak)
            .where(MonthlyPeak.season_year == season_year)
            .order_by(MonthlyPeak.month)
        )
    ).scalars().all()
    if not rows:
        return PeaksResponse(season_year=season_year, monthly_peaks=[])
    return PeaksResponse(
        season_year=season_year,
        monthly_peaks=[
            MonthlyPeakItem(
                month=r.month,
                month_name=r.peak_timestamp.strftime("%B"),
                peak_timestamp=r.peak_timestamp,
                adjusted_interval=adjusted_interval(r.peak_timestamp),
                peak_mw=r.peak_mw,
                peak_gw=round(r.peak_mw / 1000, 3),
                peak_hour=peak_hour_label(r.peak_timestamp),
            )
            for r in rows
        ],
    )


async def _assemble_predictions(
    session: AsyncSession, slot: str | None
) -> PredictionBatchResponse | None:
    """Return latest prediction batch for the given slot (or overall latest)."""
    latest = await _get_latest_batch(session, slot)
    if latest is None:
        return None
    cp_day, resolved_slot = latest
    rows = (
        await session.execute(
            select(Prediction)
            .where(Prediction.slot == resolved_slot, Prediction.cp_day_called == cp_day)
            .order_by(Prediction.forecast_date)
        )
    ).scalars().all()
    if not rows:
        return None
    return PredictionBatchResponse(
        slot=resolved_slot,
        cp_day_called=cp_day,
        forecast_interval=format_forecast_interval([r.forecast_date for r in rows]),
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


@router.get("/r/{token}", response_class=HTMLResponse, include_in_schema=False)
async def view_dashboard(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Render the dashboard for a valid view token (no API key required)."""
    view_token = await validate_view_token(session, token)
    if view_token is None:
        raise HTTPException(
            status_code=404,
            detail="This link has expired or is invalid. Please request a new report.",
        )
    # Inject the raw token so the dashboard JS can call /api/report/{token}
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"view_token": token},
    )


@router.get("/api/report/{token}", response_model=LatestResponse)
async def get_report_latest(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> LatestResponse:
    """
    Return the latest forecast + peaks for a valid view token.
    Drop-in replacement for /api/latest when accessing via an email link.
    """
    view_token = await validate_view_token(session, token)
    if view_token is None:
        raise HTTPException(status_code=404, detail="Link expired or invalid")

    predictions = await _assemble_predictions(session, slot=None)
    peaks = await _assemble_peaks(session)

    last_updated_candidates: list[datetime] = []
    if predictions:
        last_updated_candidates.append(predictions.fetched_at)
    if peaks.monthly_peaks:
        peak_updated = (
            await session.execute(
                select(MonthlyPeak.updated_at).order_by(MonthlyPeak.updated_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if peak_updated:
            last_updated_candidates.append(peak_updated)

    return LatestResponse(
        predictions=predictions,
        peaks=peaks,
        last_updated=max(last_updated_candidates) if last_updated_candidates else None,
    )


@router.get("/api/report/{token}/predictions", response_model=PredictionBatchResponse)
async def get_report_predictions(
    token: str,
    slot: str | None = Query(None, pattern="^(3AM|11AM)$"),
    session: AsyncSession = Depends(get_session),
) -> PredictionBatchResponse:
    """
    Return a prediction batch for the given slot.
    Used by the dashboard slot toggle when accessed via an email link.
    """
    view_token = await validate_view_token(session, token)
    if view_token is None:
        raise HTTPException(status_code=404, detail="Link expired or invalid")

    predictions = await _assemble_predictions(session, slot=slot)
    if predictions is None:
        raise HTTPException(status_code=404, detail="No predictions available")
    return predictions


@router.get("/api/report/{token}/matrix", response_model=MatrixResponse)
async def get_report_matrix(
    token: str,
    days: int = Query(150, ge=1, le=365),  # matches app/routes/matrix.py's season-length default
    session: AsyncSession = Depends(get_session),
) -> MatrixResponse:
    """Prediction matrix + daily actuals for the evolution and rewind views."""
    view_token = await validate_view_token(session, token)
    if view_token is None:
        raise HTTPException(status_code=404, detail="Link expired or invalid")

    return await assemble_matrix(session, days)
