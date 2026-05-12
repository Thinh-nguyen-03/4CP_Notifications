import ssl
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings


def _ssl_context_encrypted_no_verify() -> ssl.SSLContext:
    """Encrypted but no cert verification — required for Supabase Supavisor pooler.

    Supabase's connection pooler (Supavisor) presents a self-signed certificate that
    no public CA bundle can verify.  Disabling verification is the standard workaround
    documented by Supabase; the connection is still fully encrypted.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


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

    is_supabase = "supabase.co" in lowered or "pooler.supabase.com" in lowered
    is_render_db = "render.com" in lowered or "render.internal" in lowered

    if (is_supabase or is_render_db) and "sslmode=disable" not in q:
        if is_supabase:
            # Supabase Supavisor uses a self-signed cert — encrypt without verify.
            args["ssl"] = _ssl_context_encrypted_no_verify()
        else:
            # Render managed Postgres has a CA-signed cert; full verification is fine.
            args["ssl"] = True

    # Supabase transaction pooler (port 6543 / PgBouncer): asyncpg must not cache prepared statements.
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
