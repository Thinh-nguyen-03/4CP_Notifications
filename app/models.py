from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column



class Base(DeclarativeBase):
    pass


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    slot: Mapped[str] = mapped_column(String(10))
    cp_day_called: Mapped[date] = mapped_column(Date, index=True)
    forecast_date: Mapped[date] = mapped_column(Date)
    peak_load_gwh: Mapped[float] = mapped_column(Numeric(5, 1))
    peak_hour: Mapped[str] = mapped_column(String(10))
    cp_score: Mapped[int] = mapped_column(SmallInteger)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("slot", "cp_day_called", "forecast_date", name="uq_prediction_slot_day_forecast"),
    )


class MonthlyPeak(Base):
    __tablename__ = "monthly_peaks"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(SmallInteger)
    peak_timestamp: Mapped[datetime] = mapped_column(DateTime)
    peak_mw: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("season_year", "month", name="uq_monthly_peak_year_month"),
    )


class FetchRun(Base):
    __tablename__ = "fetch_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    slot: Mapped[str | None] = mapped_column(String(10), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rows_written: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ViewToken(Base):
    """Single-use-style time-limited token embedded in dashboard email links."""

    __tablename__ = "view_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    slot: Mapped[str] = mapped_column(String(10))
    cp_day_called: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    email_sent: Mapped[bool] = mapped_column(Boolean, server_default="false")


class EmailList(Base):
    """BCC recipients for dashboard report emails (one row per address)."""

    __tablename__ = "email_list"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
