from __future__ import annotations

from typing import Any

from utils.exceptions import StorageError


RENAME_COLUMNS = {
    "time": "datetime",
    "trade_time": "datetime",
    "trading_day": "date",
    "vol": "volume",
    "turnoverrate": "turnover",
    "preclose": "pre_close",
}


def normalize_market_data(raw: object, *, symbol: str, storage_period: str) -> object:
    """Normalize provider output into the project's standard bar schema."""

    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to normalize market data.") from exc

    frame = _extract_frame(raw, symbol=symbol)
    if not isinstance(frame, pd.DataFrame):
        raise StorageError(f"Unsupported market data payload for {symbol}: {type(raw)!r}")

    normalized = frame.copy()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    normalized = normalized.rename(columns=RENAME_COLUMNS)

    if "symbol" not in normalized.columns:
        normalized.insert(0, "symbol", symbol)

    normalized = _ensure_time_columns(normalized, storage_period)
    return normalized.reset_index(drop=True)


def _extract_frame(raw: object, *, symbol: str) -> Any:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to normalize market data.") from exc

    if isinstance(raw, pd.DataFrame):
        return raw

    if isinstance(raw, dict):
        if symbol in raw:
            return raw[symbol]
        if len(raw) == 1:
            return next(iter(raw.values()))

    return raw


def _ensure_time_columns(frame: object, storage_period: str) -> object:
    import pandas as pd

    normalized = frame.copy()

    if storage_period == "daily":
        if "date" not in normalized.columns:
            if "datetime" in normalized.columns:
                normalized["date"] = pd.to_datetime(normalized["datetime"]).dt.strftime("%Y%m%d")
            else:
                normalized["date"] = _index_as_time_column(normalized, "%Y%m%d")
        normalized["date"] = normalized["date"].map(_format_daily_date)
        return normalized

    if storage_period == "minute":
        if "datetime" not in normalized.columns:
            if "date" in normalized.columns:
                normalized["datetime"] = normalized["date"]
            else:
                normalized["datetime"] = _index_as_time_column(normalized, "%Y%m%d%H%M%S")
        normalized["datetime"] = normalized["datetime"].map(_format_minute_datetime)
        return normalized

    return normalized


def _index_as_time_column(frame: object, fmt: str) -> object:
    import pandas as pd

    index = frame.index
    if isinstance(index, pd.RangeIndex):
        raise StorageError("Market data has no date/datetime column or meaningful index.")
    return pd.to_datetime(index).strftime(fmt)


def _format_daily_date(value: object) -> str:
    import pandas as pd

    text = str(value)
    if text.isdigit() and len(text) == 8:
        return text
    return pd.to_datetime(value).strftime("%Y%m%d")


def _format_minute_datetime(value: object) -> str:
    import pandas as pd

    text = str(value)
    if text.isdigit() and len(text) in {12, 14}:
        return text
    return pd.to_datetime(value).strftime("%Y%m%d%H%M%S")
