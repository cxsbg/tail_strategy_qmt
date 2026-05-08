from __future__ import annotations

import pytest

from qmt.client import HistoryRequest
from data_layer.sync import MarketDataSynchronizer


class FakeQmtClient:
    def __init__(self) -> None:
        self.downloaded: list[HistoryRequest] = []

    def download_history(self, request: HistoryRequest) -> None:
        self.downloaded.append(request)

    def fetch_history(self, request: HistoryRequest) -> object:
        pd = pytest.importorskip("pandas")
        return pd.DataFrame(
            [
                {
                    "date": "20240501",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "volume": 100,
                    "amount": 1000,
                }
            ]
        )


class FakeParquetStorage:
    def __init__(self, cached_values: dict[str, str | None] | None = None) -> None:
        self.appends: list[tuple[str, str, object]] = []
        self.cached_values = cached_values or {}

    def append_frame(self, period: str, symbol: str, frame: object) -> None:
        self.appends.append((period, symbol, frame))

    def write_frame(self, period: str, symbol: str, frame: object) -> None:
        self.appends.append((period, symbol, frame))

    def max_cached_value(self, period: str, symbol: str) -> str | None:
        return self.cached_values.get(symbol)


class FakeSQLiteStore:
    def __init__(self) -> None:
        self.statuses: list[dict[str, object]] = []

    def upsert_sync_status(self, **kwargs: object) -> None:
        self.statuses.append(kwargs)


def test_market_data_synchronizer_records_success() -> None:
    qmt_client = FakeQmtClient()
    parquet_storage = FakeParquetStorage()
    sqlite_store = FakeSQLiteStore()
    synchronizer = MarketDataSynchronizer(
        qmt_client=qmt_client,
        parquet_storage=parquet_storage,
        sqlite_store=sqlite_store,
    )

    results = synchronizer.sync_history(
        symbols=["000001.SZ"],
        period="1d",
        storage_period="daily",
        start_date="20240101",
        end_date="20240501",
    )

    assert results[0].status == "success"
    assert qmt_client.downloaded[0].symbol == "000001.SZ"
    assert parquet_storage.appends[0][0] == "daily"
    assert "symbol" in parquet_storage.appends[0][2].columns
    assert sqlite_store.statuses[0]["status"] == "success"


def test_sync_incremental_starts_after_cached_date() -> None:
    qmt_client = FakeQmtClient()
    parquet_storage = FakeParquetStorage(cached_values={"000001.SZ": "20240430"})
    sqlite_store = FakeSQLiteStore()
    synchronizer = MarketDataSynchronizer(
        qmt_client=qmt_client,
        parquet_storage=parquet_storage,
        sqlite_store=sqlite_store,
    )

    results = synchronizer.sync_incremental(
        symbols=["000001.SZ"],
        period="1d",
        storage_period="daily",
        end_date="20240508",
        fallback_start_date="20240101",
    )

    assert results[0].status == "success"
    assert qmt_client.downloaded[0].start_date == "20240501"
    assert qmt_client.downloaded[0].end_date == "20240508"


def test_sync_incremental_skips_current_cache() -> None:
    qmt_client = FakeQmtClient()
    parquet_storage = FakeParquetStorage(cached_values={"000001.SZ": "20240508"})
    sqlite_store = FakeSQLiteStore()
    synchronizer = MarketDataSynchronizer(
        qmt_client=qmt_client,
        parquet_storage=parquet_storage,
        sqlite_store=sqlite_store,
    )

    results = synchronizer.sync_incremental(
        symbols=["000001.SZ"],
        period="1d",
        storage_period="daily",
        end_date="20240508",
        fallback_start_date="20240101",
    )

    assert results[0].status == "skipped"
    assert qmt_client.downloaded == []
    assert sqlite_store.statuses[0]["status"] == "skipped"
