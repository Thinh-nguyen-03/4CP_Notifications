import io
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_session, require_client
from app.models import Prediction

router = APIRouter(prefix="/api", tags=["chart"], dependencies=[Depends(require_client)])


def _render_chart(slot: str, dates: list[date], scores: list[int]) -> bytes:
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=120)

    colors = ["#FF5353" if s >= 90 else "#FF832F" if s >= 70 else "#4A90E2" for s in scores]
    labels = [f"{d.strftime('%b')} {d.day}" for d in dates]
    bars = ax.bar(labels, scores, color=colors)

    ax.set_title(f"{slot} ERCOT 4CP Forecast", fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel("4CP Score")
    ax.set_ylim(0, 105)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for bar, score in zip(bars, scores):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2, str(score), ha="center", fontsize=9)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


@router.get("/chart.png", response_class=Response)
async def get_chart(
    slot: str | None = Query(None, pattern="^(3AM|11AM)$"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    stmt = select(Prediction.cp_day_called, Prediction.slot)
    if slot:
        stmt = stmt.where(Prediction.slot == slot)
    stmt = stmt.order_by(Prediction.cp_day_called.desc(), Prediction.fetched_at.desc()).limit(1)
    head = (await session.execute(stmt)).first()
    if head is None:
        raise HTTPException(status_code=404, detail="No predictions available")
    cp_day, resolved_slot = head

    rows = (
        await session.execute(
            select(Prediction)
            .where(Prediction.slot == resolved_slot, Prediction.cp_day_called == cp_day)
            .order_by(Prediction.forecast_date)
            .limit(7)
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No predictions available")

    png = _render_chart(resolved_slot, [r.forecast_date for r in rows], [r.cp_score for r in rows])
    return Response(content=png, media_type="image/png")
