import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import settings

_log = logging.getLogger(__name__)

NRG_BASE_URL = "https://api.nrgstream.com"
TOKEN_PATH = "/api/security/token"
RELEASE_PATH = "/api/ReleaseToken"
DEMAND_STREAM_ID = "24039"

SEASON_START_MONTH = 5
SEASON_START_DAY = 30
SEASON_END_MONTH = 9
SEASON_END_DAY = 30

_DATE_FORMATS = (
    "%b %d %Y %H:%M",
    "%b %d %Y %H:%M:%S",
    "%d-%b-%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


@dataclass(frozen=True)
class DemandReading:
    timestamp: datetime
    mw: float


def _parse_timestamp(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


async def _get_token(client: httpx.AsyncClient) -> str:
    response = await client.post(
        TOKEN_PATH,
        data=f"grant_type=password&username={settings.nrgstream_username}&password={settings.nrgstream_password}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def _release_token(client: httpx.AsyncClient, token: str) -> None:
    try:
        await client.delete(RELEASE_PATH, headers={"Authorization": f"Bearer {token}"})
    except Exception:
        pass


async def fetch_demand_readings(season_year: int) -> list[DemandReading]:
    if settings.use_mock_fetchers:
        from app.fetchers import mock_data

        _log.warning("USE_MOCK_FETCHERS: returning synthetic NRGStream readings (year=%s)", season_year)
        return mock_data.mock_demand_readings(season_year)

    if not settings.nrgstream_username or not settings.nrgstream_password:
        raise RuntimeError("NRGSTREAM_USERNAME / NRGSTREAM_PASSWORD not configured")

    from_date = f"{SEASON_START_MONTH:02d}/{SEASON_START_DAY:02d}/{season_year}"
    to_date = f"{SEASON_END_MONTH:02d}/{SEASON_END_DAY:02d}/{season_year}"

    async with httpx.AsyncClient(base_url=NRG_BASE_URL, timeout=60.0) as client:
        token = await _get_token(client)
        try:
            response = await client.get(
                f"/api/StreamData/{DEMAND_STREAM_ID}",
                params={"fromDate": from_date, "toDate": to_date},
                headers={
                    "Accept": "text/csv",
                    "Authorization": f"Bearer {token}",
                },
            )
            response.raise_for_status()
            body = response.text
        finally:
            await _release_token(client, token)

    return _parse_csv(body)


def _parse_csv(body: str) -> list[DemandReading]:
    lines = body.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        lower = line.lower()
        if "effective date" in lower and (
            "actual system demand" in lower or "system demand" in lower
        ):
            header_idx = i
            break
    if header_idx is None:
        preview = "\n".join(lines[:8])[:500]
        _log.warning(
            "NRGStream CSV has no demand header; skipping monthly peaks. Preview: %s",
            preview or "(empty body)",
        )
        return []

    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    rows = list(reader)
    if not rows:
        return []

    readings: list[DemandReading] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        ts = _parse_timestamp(row[0])
        if ts is None:
            continue
        try:
            mw = float(row[1])
        except (TypeError, ValueError):
            continue
        readings.append(DemandReading(timestamp=ts, mw=mw))

    return readings
