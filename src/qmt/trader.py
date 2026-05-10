from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class QmtOrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class QmtPriceType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class QmtOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class QmtOrderRequest:
    symbol: str
    side: QmtOrderSide
    quantity: float
    price: float | None
    price_type: QmtPriceType = QmtPriceType.LIMIT
    strategy_name: str | None = None
    order_remark: str | None = None


@dataclass(frozen=True)
class QmtSubmittedOrder:
    broker_order_id: str
    symbol: str
    side: QmtOrderSide
    status: QmtOrderStatus
    raw_status: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class QmtOrderSnapshot:
    broker_order_id: str
    symbol: str
    side: QmtOrderSide
    status: QmtOrderStatus
    quantity: float | None = None
    traded_quantity: float | None = None
    price: float | None = None
    raw_status: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class QmtFillSnapshot:
    broker_order_id: str | None
    symbol: str
    side: QmtOrderSide
    quantity: float
    price: float
    fill_date: str | None = None
    fill_time: str | None = None
    amount: float | None = None
    fee: float | None = None


@dataclass(frozen=True)
class QmtPositionSnapshot:
    symbol: str
    quantity: float
    available_quantity: float | None = None
    market_value: float | None = None
    cost_price: float | None = None


class QmtTrader(Protocol):
    def connect(self) -> None:
        """Connect to QMT trading service and subscribe the account."""

    def submit_order(self, request: QmtOrderRequest) -> QmtSubmittedOrder:
        """Submit one stock order and return the broker order id."""

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel one stock order by broker order id."""

    def query_orders(self) -> list[QmtOrderSnapshot]:
        """Return current broker order snapshots."""

    def query_fills(self) -> list[QmtFillSnapshot]:
        """Return current broker fill snapshots."""

    def query_positions(self) -> list[QmtPositionSnapshot]:
        """Return current broker position snapshots."""
