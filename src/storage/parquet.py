from __future__ import annotations

from pathlib import Path
from typing import Iterable

from utils.exceptions import StorageError


DAILY_REQUIRED_COLUMNS = frozenset(
    {
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    }
)

MINUTE_REQUIRED_COLUMNS = frozenset(
    {
        "symbol",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    }
)

REQUIRED_COLUMNS_BY_PERIOD = {
    "daily": DAILY_REQUIRED_COLUMNS,
    "minute": MINUTE_REQUIRED_COLUMNS,
    "index": DAILY_REQUIRED_COLUMNS,
    "sector": DAILY_REQUIRED_COLUMNS,
}

DEDUP_COLUMNS_BY_PERIOD = {
    "daily": ["symbol", "date"],
    "minute": ["symbol", "datetime"],
    "index": ["symbol", "date"],
    "sector": ["symbol", "date"],
}

SORT_COLUMNS_BY_PERIOD = {
    "daily": ["symbol", "date"],
    "minute": ["symbol", "datetime"],
    "index": ["symbol", "date"],
    "sector": ["symbol", "date"],
}


class ParquetStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, period: str, symbol: str) -> Path:
        normalized_symbol = symbol.replace("/", "_").replace("\\", "_")
        return self.root / period / f"{normalized_symbol}.parquet"

    def required_columns(self, period: str) -> frozenset[str]:
        try:
            return REQUIRED_COLUMNS_BY_PERIOD[period]
        except KeyError as exc:
            raise StorageError(f"Unsupported parquet period: {period}") from exc

    def validate_columns(self, period: str, columns: Iterable[str]) -> None:
        present = set(columns)
        missing = self.required_columns(period) - present
        if missing:
            ordered = ", ".join(sorted(missing))
            raise StorageError(f"Missing required {period} columns: {ordered}")

    def write_frame(self, period: str, symbol: str, frame: object) -> Path:
        try:
            import pandas as pd
        except ModuleNotFoundError as exc:
            raise StorageError("pandas and pyarrow are required for Parquet storage.") from exc

        if not isinstance(frame, pd.DataFrame):
            raise StorageError("ParquetStorage.write_frame expects a pandas DataFrame.")

        self.validate_columns(period, frame.columns)
        path = self.path_for(period, symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        return path

    def append_frame(self, period: str, symbol: str, frame: object) -> Path:
        try:
            import pandas as pd
        except ModuleNotFoundError as exc:
            raise StorageError("pandas and pyarrow are required for Parquet storage.") from exc

        if not isinstance(frame, pd.DataFrame):
            raise StorageError("ParquetStorage.append_frame expects a pandas DataFrame.")

        self.validate_columns(period, frame.columns)
        path = self.path_for(period, symbol)
        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, frame], ignore_index=True)
        else:
            combined = frame.copy()

        dedup_columns = DEDUP_COLUMNS_BY_PERIOD[period]
        sort_columns = SORT_COLUMNS_BY_PERIOD[period]
        combined = (
            combined.drop_duplicates(subset=dedup_columns, keep="last")
            .sort_values(sort_columns)
            .reset_index(drop=True)
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(path, index=False)
        return path

    def read_frame(self, period: str, symbol: str) -> object:
        try:
            import pandas as pd
        except ModuleNotFoundError as exc:
            raise StorageError("pandas and pyarrow are required for Parquet storage.") from exc

        path = self.path_for(period, symbol)
        if not path.exists():
            raise StorageError(f"Parquet file not found: {path}")
        return pd.read_parquet(path)

    def max_cached_value(self, period: str, symbol: str) -> str | None:
        try:
            frame = self.read_frame(period, symbol)
        except StorageError:
            return None

        key = SORT_COLUMNS_BY_PERIOD[period][-1]
        if key not in frame.columns or frame.empty:
            return None
        return str(frame[key].max())
