"""Consistent datetime strings in JSON API responses (no fractional seconds)."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import PlainSerializer

_ERCOT_TZ = ZoneInfo("America/Chicago")


def format_api_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(_ERCOT_TZ)
    return value.replace(microsecond=0, tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


# Response models: serializes as "2026-05-21T11:05:45" (US Central when stored as UTC)
ApiDateTime = Annotated[datetime, PlainSerializer(format_api_datetime, return_type=str)]
