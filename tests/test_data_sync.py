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
    def __init__(self) -> None:
        self.appends: list[tuple[str, str, object]] = []

    def append_frame(self, period: str, symbol: str, frame: object) -> None:
        self.appends.append((period, symbol, frame))

    def write_frame(self, period: str, symbol: str, frame: object) -> None:
        self.appends.append((period, symbol, frame))


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
