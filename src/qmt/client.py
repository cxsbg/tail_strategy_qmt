from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HistoryRequest:
    symbol: str
    period: str
    start_date: str
    end_date: str
    adjust_type: str = "front"
    count: int = 1_000_000


class QmtClient(Protocol):
    def fetch_history(self, request: HistoryRequest) -> object:
        """Fetch historical bars and return a pandas-compatible frame."""

    def download_history(self, request: HistoryRequest) -> None:
        """Ask QMT to download or refresh local history for one symbol."""

    def download_sector_data(self) -> None:
        """Refresh QMT sector metadata."""

    def list_sector_symbols(self, sector_name: str) -> list[str]:
        """Return symbols in a QMT sector."""
