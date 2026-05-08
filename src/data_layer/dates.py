from __future__ import annotations

from datetime import date, datetime, timedelta

from utils.exceptions import ConfigError


def today_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def next_start_value(storage_period: str, cached_value: str) -> str:
    if storage_period in {"daily", "index", "sector"}:
        return _next_daily_date(cached_value)
    if storage_period == "minute":
        return _next_minute_datetime(cached_value)
    raise ConfigError(f"Unsupported storage period for incremental sync: {storage_period}")


def is_cache_current(storage_period: str, cached_value: str | None, end_value: str) -> bool:
    if cached_value is None:
        return False
    return normalize_compare_value(storage_period, cached_value) >= normalize_compare_value(
        storage_period,
        end_value,
    )


def normalize_compare_value(storage_period: str, value: str) -> str:
    if storage_period in {"daily", "index", "sector"}:
        return value[:8]
    if storage_period == "minute":
        return value if len(value) == 14 else f"{value[:8]}000000"
    raise ConfigError(f"Unsupported storage period: {storage_period}")


def _next_daily_date(value: str) -> str:
    parsed = datetime.strptime(value[:8], "%Y%m%d").date()
    return (parsed + timedelta(days=1)).strftime("%Y%m%d")


def _next_minute_datetime(value: str) -> str:
    normalized = value if len(value) == 14 else f"{value[:8]}000000"
    parsed = datetime.strptime(normalized, "%Y%m%d%H%M%S")
    return (parsed + timedelta(minutes=1)).strftime("%Y%m%d%H%M%S")
