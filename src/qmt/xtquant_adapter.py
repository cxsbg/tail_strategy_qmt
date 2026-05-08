from __future__ import annotations

from qmt.client import HistoryRequest
from utils.exceptions import QmtUnavailableError


class XtQuantAdapter:
    """Thin xtquant adapter.

    xtquant is imported lazily here so the rest of the project can run on
    machines that do not have QMT installed.
    """

    def __init__(self) -> None:
        try:
            from xtquant import xtdata
        except ModuleNotFoundError as exc:
            raise QmtUnavailableError(
                "xtquant is not available. Install QMT/xtquant before using QMT data access."
            ) from exc
        self._xtdata = xtdata

    def fetch_history(self, request: HistoryRequest) -> object:
        return self._xtdata.get_market_data_ex(
            [],
            [request.symbol],
            period=request.period,
            start_time=request.start_date,
            end_time=request.end_date,
            dividend_type=request.adjust_type,
        )

    def download_history(self, request: HistoryRequest) -> None:
        self._xtdata.download_history_data(
            request.symbol,
            period=request.period,
            start_time=request.start_date,
            end_time=request.end_date,
            incrementally=True,
        )
