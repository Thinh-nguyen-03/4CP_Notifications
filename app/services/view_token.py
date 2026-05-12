import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ViewToken


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_view_token(
    session: AsyncSession,
    slot: str,
    cp_day_called,
) -> str:
    """Generate a random view token, persist it, and return the raw value."""
    raw = secrets.token_urlsafe(32)
    token = ViewToken(
        token_hash=_hash(raw),
        slot=slot,
        cp_day_called=cp_day_called,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.token_ttl_hours),
    )
    session.add(token)
    await session.commit()
    return raw


async def validate_view_token(
    session: AsyncSession,
    raw: str,
) -> ViewToken | None:
    """Return the ViewToken row if the raw token is valid and unexpired, else None."""
    result = await session.execute(
        select(ViewToken).where(
            ViewToken.token_hash == _hash(raw),
            ViewToken.revoked.is_(False),
            ViewToken.expires_at > datetime.now(timezone.utc),
        )
    )
    return result.scalar_one_or_none()


async def mark_email_sent(session: AsyncSession, token: ViewToken) -> None:
    token.email_sent = True
    await session.commit()
