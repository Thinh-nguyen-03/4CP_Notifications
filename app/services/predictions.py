from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.fetchers.amperon import PredictionBatch
from app.models import Prediction


async def upsert_predictions(session: AsyncSession, batch: PredictionBatch) -> int:
    if not batch.predictions:
        return 0

    rows = [
        {
            "slot": batch.slot,
            "cp_day_called": batch.cp_day_called,
            "forecast_date": p.forecast_date,
            "peak_load_gwh": p.peak_load_gwh,
            "peak_hour": p.peak_hour,
            "cp_score": p.cp_score,
        }
        for p in batch.predictions
    ]

    stmt = insert(Prediction).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["slot", "cp_day_called", "forecast_date"],
        set_={
            "peak_load_gwh": stmt.excluded.peak_load_gwh,
            "peak_hour": stmt.excluded.peak_hour,
            "cp_score": stmt.excluded.cp_score,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )

    await session.execute(stmt)
    await session.commit()
    return len(rows)
