from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_session, require_client
from app.models import FetchRun, Prediction
from app.routes.predictions import PredictionItem

router = APIRouter(prefix="/api", tags=["history"], dependencies=[Depends(require_client)])


class HistorySnapshot(BaseModel):
    cp_day_called: date
    slot: str
    fetched_at: datetime
    predictions: list[PredictionItem]


class HistoryResponse(BaseModel):
    snapshots: list[HistorySnapshot]


class FetchRunInfo(BaseModel):
    id: int
    source: str
    slot: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    error: str | None
    rows_written: int | None


class FetchHealthResponse(BaseModel):
    recent_runs: list[FetchRunInfo]


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    days: int = Query(30, ge=1, le=365),
    slot: str | None = Query(None, pattern="^(3AM|11AM)$"),
    session: AsyncSession = Depends(get_session),
) -> HistoryResponse:
    cutoff = date.today() - timedelta(days=days)
    stmt = select(Prediction).where(Prediction.cp_day_called >= cutoff)
    if slot:
        stmt = stmt.where(Prediction.slot == slot)
    stmt = stmt.order_by(
        Prediction.cp_day_called.desc(),
        Prediction.slot,
        Prediction.forecast_date,
    )
    rows = (await session.execute(stmt)).scalars().all()

    grouped: dict[tuple[date, str], list[Prediction]] = {}
    for r in rows:
        grouped.setdefault((r.cp_day_called, r.slot), []).append(r)

    snapshots = [
        HistorySnapshot(
            cp_day_called=key[0],
            slot=key[1],
            fetched_at=max(p.fetched_at for p in preds),
            predictions=[
                PredictionItem(
                    forecast_date=p.forecast_date,
                    peak_load_gwh=float(p.peak_load_gwh),
                    peak_hour=p.peak_hour,
                    cp_score=p.cp_score,
                )
                for p in preds
            ],
        )
        for key, preds in sorted(grouped.items(), reverse=True)
    ]
    return HistoryResponse(snapshots=snapshots)


@router.get("/fetches", response_model=FetchHealthResponse)
async def get_fetch_health(
    limit: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> FetchHealthResponse:
    rows = (
        await session.execute(
            select(FetchRun).order_by(FetchRun.started_at.desc()).limit(limit)
        )
    ).scalars().all()
    return FetchHealthResponse(
        recent_runs=[
            FetchRunInfo(
                id=r.id,
                source=r.source,
                slot=r.slot,
                started_at=r.started_at,
                finished_at=r.finished_at,
                status=r.status,
                error=r.error,
                rows_written=r.rows_written,
            )
            for r in rows
        ]
    )
