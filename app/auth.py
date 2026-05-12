import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_maker
from app.models import ApiKey

_bearer = HTTPBearer(auto_error=False)


def generate_key() -> str:
    return f"4cp_{secrets.token_urlsafe(32)}"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session


def _extract_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    token = _extract_token(credentials)
    if not hmac.compare_digest(token, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin key required",
        )


async def require_client(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    token = _extract_token(credentials)
    token_hash = hash_key(token)

    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == token_hash, ApiKey.revoked.is_(False))
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked API key",
        )

    await session.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key.id)
        .values(last_used_at=datetime.now(timezone.utc))
    )
    await session.commit()
    request.state.api_key_id = api_key.id
    return api_key
