from __future__ import annotations

import pytest

from storage.parquet import ParquetStorage
from utils.exceptions import StorageError


def test_path_for_sanitizes_symbol(tmp_path) -> None:
    storage = ParquetStorage(tmp_path)

    path = storage.path_for("daily", "000001/SZ")

    assert path == tmp_path / "daily" / "000001_SZ.parquet"


def test_validate_columns_rejects_missing_required_columns(tmp_path) -> None:
    storage = ParquetStorage(tmp_path)

    with pytest.raises(StorageError, match="Missing required daily columns"):
        storage.validate_columns("daily", ["symbol", "date", "open"])


def test_validate_columns_accepts_daily_columns(tmp_path) -> None:
    storage = ParquetStorage(tmp_path)

    storage.validate_columns(
        "daily",
        [
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover",
        ],
    )


def test_append_frame_merges_and_deduplicates(tmp_path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    storage = ParquetStorage(tmp_path)
    first = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "20240102",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "amount": 1000,
            },
            {
                "symbol": "000001.SZ",
                "date": "20240103",
                "open": 10.5,
                "high": 11.5,
                "low": 10,
                "close": 11,
                "volume": 110,
                "amount": 1100,
            },
        ]
    )
    second = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "20240103",
                "open": 10.8,
                "high": 12,
                "low": 10.6,
                "close": 11.8,
                "volume": 120,
                "amount": 1200,
            }
        ]
    )

    storage.append_frame("daily", "000001.SZ", first)
    storage.append_frame("daily", "000001.SZ", second)

    cached = storage.read_frame("daily", "000001.SZ")
    assert list(cached["date"]) == ["20240102", "20240103"]
    assert cached.loc[cached["date"] == "20240103", "close"].item() == 11.8
    assert storage.max_cached_value("daily", "000001.SZ") == "20240103"
