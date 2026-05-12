"""
Synthetic Amperon + NRGStream payloads for end-to-end testing without real APIs.

Enable with USE_MOCK_FETCHERS=true (see app.config.Settings).
"""
from datetime import date, datetime, timedelta, timezone

from app.fetchers.amperon import PredictionBatch, PredictionRow, Slot
from app.fetchers.nrgstream import DemandReading


def mock_prediction_batch(*, slot: Slot, cp_day_called: date | None = None) -> PredictionBatch:
    """Seven-day forecast and metadata aligned with the dashboard preview shape."""
    if cp_day_called is None:
        cp_day_called = date.today()

    scores = [38, 84, 98, 91, 6, 12, 72]
    gw = [76.9, 78.6, 78.4, 76.1, 73.2, 75.0, 77.1]
    hours = ["HE17", "HE18", "HE18", "HE18", "HE18", "HE17", "HE18"]
    predictions = [
        PredictionRow(
            forecast_date=cp_day_called + timedelta(days=i),
            peak_load_gwh=gw[i],
            peak_hour=hours[i],
            cp_score=scores[i],
        )
        for i in range(7)
    ]
    return PredictionBatch(
        slot=slot,
        cp_day_called=cp_day_called,
        prediction_timestamp=datetime.now(timezone.utc),
        predictions=predictions,
    )


def mock_demand_readings(season_year: int) -> list[DemandReading]:
    """One synthetic peak per month June–September so monthly_peaks upserts succeed."""
    specs: list[tuple[int, int, int, float]] = [
        (6, 15, 17, 78200.0),
        (7, 20, 18, 82300.0),
        (8, 18, 17, 84100.0),
        (9, 4, 18, 80200.0),
    ]
    return [
        DemandReading(timestamp=datetime(season_year, month, day, hour, 0), mw=mw)
        for month, day, hour, mw in specs
    ]
