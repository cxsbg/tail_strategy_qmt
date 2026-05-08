from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from qmt.client import HistoryRequest, QmtClient
from data_layer.normalize import normalize_market_data
from storage.parquet import ParquetStorage
from storage.sqlite import SQLiteStore
from utils.logging import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class SyncResult:
    symbol: str
    period: str
    status: str
    error_message: str | None = None


class MarketDataSynchronizer:
    def __init__(
        self,
        *,
        qmt_client: QmtClient,
        parquet_storage: ParquetStorage,
        sqlite_store: SQLiteStore,
        source: str = "qmt",
    ) -> None:
        self.qmt_client = qmt_client
        self.parquet_storage = parquet_storage
        self.sqlite_store = sqlite_store
        self.source = source

    def sync_history(
        self,
        *,
        symbols: Iterable[str],
        period: str,
        storage_period: str,
        start_date: str,
        end_date: str,
        adjust_type: str = "front",
        append: bool = True,
    ) -> list[SyncResult]:
        results: list[SyncResult] = []
        for symbol in symbols:
            request = HistoryRequest(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust_type=adjust_type,
            )
            try:
                self.qmt_client.download_history(request)
                raw_frame = self.qmt_client.fetch_history(request)
                frame = normalize_market_data(
                    raw_frame,
                    symbol=symbol,
                    storage_period=storage_period,
                )
                if append:
                    self.parquet_storage.append_frame(storage_period, symbol, frame)
                else:
                    self.parquet_storage.write_frame(storage_period, symbol, frame)
                self._record_status(symbol, period, start_date, end_date, "success", None)
                results.append(SyncResult(symbol=symbol, period=period, status="success"))
            except Exception as exc:
                logger.exception("Failed to sync %s %s", symbol, period)
                message = str(exc)
                self._record_status(symbol, period, start_date, end_date, "failed", message)
                results.append(
                    SyncResult(
                        symbol=symbol,
                        period=period,
                        status="failed",
                        error_message=message,
                    )
                )
        return results

    def _record_status(
        self,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        status: str,
        error_message: str | None,
    ) -> None:
        self.sqlite_store.upsert_sync_status(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            last_sync_time=datetime.now().isoformat(timespec="seconds"),
            source=self.source,
            status=status,
            error_message=error_message,
        )
