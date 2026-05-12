from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
from typing import Literal, cast

import httpx

from app.config import settings

AMPERON_URL = "https://platform.amperon.co/export/peak-alerts/predictions/ercot_4cp"

_log = logging.getLogger(__name__)

Slot = Literal["3AM", "11AM"]


@dataclass(frozen=True)
class PredictionRow:
    forecast_date: date
    peak_load_gwh: float
    peak_hour: str
    cp_score: int


@dataclass(frozen=True)
class PredictionBatch:
    slot: Slot
    cp_day_called: date
    prediction_timestamp: datetime
    predictions: list[PredictionRow]


def _slot_from_timestamp(ts: datetime) -> Slot | None:
    central = ts - timedelta(hours=5)
    if 3 <= central.hour < 11:
        return "3AM"
    if central.hour >= 11:
        return "11AM"
    return None


async def fetch_amperon() -> PredictionBatch:
    if settings.use_mock_fetchers:
        from app.fetchers import mock_data

        slot = settings.mock_fetch_slot if settings.mock_fetch_slot in ("3AM", "11AM") else "11AM"
        _log.warning("USE_MOCK_FETCHERS: returning synthetic Amperon batch (slot=%s)", slot)
        return mock_data.mock_prediction_batch(slot=cast(Slot, slot))

    if not settings.amperon_client_id or not settings.amperon_client_secret:
        raise RuntimeError("AMPERON_CLIENT_ID / AMPERON_CLIENT_SECRET not configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            AMPERON_URL,
            auth=(settings.amperon_client_id, settings.amperon_client_secret),
        )
        response.raise_for_status()
        payload = response.json()

    raw_predictions = payload.get("data") or []
    if not raw_predictions:
        raise RuntimeError("Amperon returned no predictions")

    metadata = payload.get("metadata") or {}
    prediction_ts_raw = metadata.get("prediction_timestamp")
    if not prediction_ts_raw:
        raise RuntimeError("Amperon response missing metadata.prediction_timestamp")

    prediction_ts = datetime.strptime(prediction_ts_raw, "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    slot = _slot_from_timestamp(prediction_ts)
    if slot is None:
        raise RuntimeError(
            f"Prediction timestamp {prediction_ts_raw} does not fall in a 3AM/11AM slot"
        )

    cp_day_called = (prediction_ts - timedelta(hours=5)).date()

    rows = [
        PredictionRow(
            forecast_date=datetime.strptime(p["date"], "%Y-%m-%d").date(),
            peak_load_gwh=round(float(p["peak_load"]), 1),
            peak_hour=f"HE{int(p['peak_hour'])}",
            cp_score=int(p["prob"]),
        )
        for p in raw_predictions
    ]

    return PredictionBatch(
        slot=slot,
        cp_day_called=cp_day_called,
        prediction_timestamp=prediction_ts,
        predictions=rows,
    )
