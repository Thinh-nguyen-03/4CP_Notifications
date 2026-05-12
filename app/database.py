from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings


def _normalize_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _connect_args_for_url(url: str) -> dict:
    """TLS and pooler tweaks for hosted Postgres (Render, Supabase, etc.)."""
    lowered = url.lower()
    parsed = urlparse(url)
    q = parsed.query.lower()
    args: dict = {}

    use_ssl = (
        "render.com" in lowered
        or "render.internal" in lowered
        or "supabase.co" in lowered
        or "pooler.supabase.com" in lowered
    )
    if use_ssl and "sslmode" not in q and "ssl=" not in q:
        args["ssl"] = True

    # Supabase "Transaction" pooler (port 6543 / PgBouncer): asyncpg must disable statement cache.
    if parsed.port == 6543:
        args["statement_cache_size"] = 0

    return args


_db_url = _normalize_async_url(settings.database_url)

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args_for_url(_db_url),
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
