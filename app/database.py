from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings


def _normalize_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(
    _normalize_async_url(settings.database_url),
    echo=False,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
