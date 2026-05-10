from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import floor
from typing import TYPE_CHECKING, Any, Protocol

from qmt.trader import QmtOrderRequest, QmtOrderSide, QmtOrderStatus, QmtPriceType, QmtTrader
from trading.execution import BrokerOrder, BrokerOrderStatus, TradeExecutionRepository

if TYPE_CHECKING:
    from trading.pre_trade import OrderDraft


@dataclass(frozen=True)
class OrderSubmitResult:
    order_id: int
    status: str
    broker_order_id: str | None
    message: str | None


class OrderSubmitter(Protocol):
    def submit(self, draft: OrderDraft) -> OrderSubmitResult:
        """Submit one READY order draft."""


class PaperOrderSubmitter:
    def __init__(
        self,
        *,
        execution_repository: TradeExecutionRepository,
    ) -> None:
        self.execution_repository = execution_repository

    def submit(self, draft: OrderDraft) -> OrderSubmitResult:
        if draft.id is None:
            raise ValueError("Cannot submit order draft without id.")
        broker_order_id = f"paper-{draft.id}"
        now = _now()
        self.execution_repository.upsert_order(
            BrokerOrder(
                id=None,
                order_draft_id=draft.id,
                decision_id=draft.decision_id,
                broker_order_id=broker_order_id,
                symbol=draft.symbol,
                trade_date=draft.trade_date,
                side=draft.side.value,
                quantity=None,
                price=draft.reference_price,
                order_type="PAPER",
                status=BrokerOrderStatus.SUBMITTED,
                raw_status="paper_submitted",
                message="paper submitted",
                strategy_version=draft.strategy_version,
                created_at=now,
                updated_at=now,
            )
        )
        return OrderSubmitResult(
            order_id=draft.id,
            status="PAPER_SUBMITTED",
            broker_order_id=broker_order_id,
            message="paper submitted",
        )


class LiveOrderSubmitter:
    def __init__(
        self,
        *,
        trader: QmtTrader,
        execution_repository: TradeExecutionRepository,
        trading_config: dict[str, Any],
    ) -> None:
        self.trader = trader
        self.execution_repository = execution_repository
        self.trading_config = trading_config

    def submit(self, draft: OrderDraft) -> OrderSubmitResult:
        if draft.id is None:
            raise ValueError("Cannot submit order draft without id.")
        try:
            quantity = _quantity_for_draft(draft, self.trader, self.trading_config)
            submitted = self.trader.submit_order(
                QmtOrderRequest(
                    symbol=draft.symbol,
                    side=_qmt_side(draft.side),
                    quantity=quantity,
                    price=draft.reference_price,
                    price_type=QmtPriceType.LIMIT,
                    strategy_name=str(self.trading_config.get("strategy_name", "tail_strategy_qmt")),
                    order_remark=f"decision_id={draft.decision_id};draft_id={draft.id}",
                )
            )
            broker_status = _broker_status(submitted.status)
            draft_status = "REJECTED" if broker_status == BrokerOrderStatus.REJECTED else "SUBMITTED"
            broker_order_id = submitted.broker_order_id
            message = submitted.message
            raw_status = submitted.raw_status
        except Exception as exc:  # noqa: BLE001 - live submission should persist rejection details.
            quantity = None
            broker_status = BrokerOrderStatus.REJECTED
            draft_status = "REJECTED"
            broker_order_id = f"local-rejected-{draft.id}"
            message = str(exc)
            raw_status = "local_exception"

        now = _now()
        self.execution_repository.upsert_order(
            BrokerOrder(
                id=None,
                order_draft_id=draft.id,
                decision_id=draft.decision_id,
                broker_order_id=broker_order_id,
                symbol=draft.symbol,
                trade_date=draft.trade_date,
                side=draft.side.value,
                quantity=quantity,
                price=draft.reference_price,
                order_type="LIMIT",
                status=broker_status,
                raw_status=raw_status,
                message=message,
                strategy_version=draft.strategy_version,
                created_at=now,
                updated_at=now,
            )
        )
        return OrderSubmitResult(
            order_id=draft.id,
            status=draft_status,
            broker_order_id=broker_order_id,
            message=message,
        )


def _quantity_for_draft(
    draft: OrderDraft,
    trader: QmtTrader,
    trading_config: dict[str, Any],
) -> float:
    if draft.reference_price is None or draft.reference_price <= 0:
        raise ValueError("reference_price is required for live submission.")

    lot_size = int(trading_config.get("order_lot_size", 100))
    if lot_size <= 0:
        raise ValueError("order_lot_size must be positive.")

    if draft.side.value == "SELL":
        position = next((item for item in trader.query_positions() if item.symbol == draft.symbol), None)
        if position is None:
            raise ValueError(f"Broker position not found for {draft.symbol}.")
        raw_quantity = position.available_quantity if position.available_quantity is not None else position.quantity
        return _round_lot(raw_quantity, lot_size)

    order_value_base = trading_config.get("order_value_base") or trading_config.get("account_equity")
    if order_value_base is None:
        raise ValueError("trading.order_value_base or trading.account_equity is required for live BUY orders.")
    raw_quantity = float(order_value_base) * float(draft.position_ratio) / float(draft.reference_price)
    return _round_lot(raw_quantity, lot_size)


def _round_lot(raw_quantity: float, lot_size: int) -> float:
    quantity = floor(float(raw_quantity) / lot_size) * lot_size
    if quantity <= 0:
        raise ValueError(f"Order quantity rounds to zero: raw={raw_quantity:.4f}, lot_size={lot_size}")
    return float(quantity)


def _qmt_side(side: object) -> QmtOrderSide:
    return QmtOrderSide.BUY if side.value == "BUY" else QmtOrderSide.SELL


def _broker_status(status: QmtOrderStatus) -> BrokerOrderStatus:
    return {
        QmtOrderStatus.SUBMITTED: BrokerOrderStatus.SUBMITTED,
        QmtOrderStatus.PARTIAL_FILLED: BrokerOrderStatus.PARTIAL_FILLED,
        QmtOrderStatus.FILLED: BrokerOrderStatus.FILLED,
        QmtOrderStatus.CANCELED: BrokerOrderStatus.CANCELED,
        QmtOrderStatus.REJECTED: BrokerOrderStatus.REJECTED,
        QmtOrderStatus.UNKNOWN: BrokerOrderStatus.UNKNOWN,
    }[status]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
