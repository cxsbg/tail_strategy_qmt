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


class QmtClient(Protocol):
    def fetch_history(self, request: HistoryRequest) -> object:
        """Fetch historical bars and return a pandas-compatible frame."""

    def download_history(self, request: HistoryRequest) -> None:
        """Ask QMT to download or refresh local history for one symbol."""
