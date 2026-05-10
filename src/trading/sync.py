from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from position import PositionRepository, PositionService
from position.service import PositionStateError
from qmt.trader import QmtFillSnapshot, QmtOrderSide, QmtOrderSnapshot, QmtOrderStatus, QmtTrader
from trading.execution import (
    BrokerFill,
    BrokerOrder,
    BrokerOrderApplication,
    BrokerOrderStatus,
    TradeExecutionRepository,
)
from trading.pre_trade import OrderDraftRepository


@dataclass(frozen=True)
class BrokerSyncResult:
    order_snapshot_count: int
    order_upsert_count: int
    fill_snapshot_count: int
    fill_inserted_count: int
    position_application_count: int
    db_path: Path


def sync_broker_executions(
    *,
    db_path: str | Path,
    trader: QmtTrader,
    trade_date: str | None = None,
    apply_positions: bool = False,
    strategy_version: str = "rule-v0",
) -> BrokerSyncResult:
    execution_repository = TradeExecutionRepository(db_path)

    order_snapshots = trader.query_orders()
    order_upsert_count = 0
    for snapshot in order_snapshots:
        _upsert_order_snapshot(
            repository=execution_repository,
            snapshot=snapshot,
            trade_date=trade_date,
            strategy_version=strategy_version,
        )
        order_upsert_count += 1

    fill_inserted_count = 0
    fill_snapshots = trader.query_fills()
    for snapshot in fill_snapshots:
        _, inserted = execution_repository.upsert_fill(_fill_from_snapshot(snapshot))
        if inserted:
            fill_inserted_count += 1

    position_application_count = 0
    if apply_positions:
        position_application_count = _apply_filled_orders(
            db_path=db_path,
            execution_repository=execution_repository,
            trade_date=trade_date,
            strategy_version=strategy_version,
        )

    return BrokerSyncResult(
        order_snapshot_count=len(order_snapshots),
        order_upsert_count=order_upsert_count,
        fill_snapshot_count=len(fill_snapshots),
        fill_inserted_count=fill_inserted_count,
        position_application_count=position_application_count,
        db_path=Path(db_path),
    )


def _upsert_order_snapshot(
    *,
    repository: TradeExecutionRepository,
    snapshot: QmtOrderSnapshot,
    trade_date: str | None,
    strategy_version: str,
) -> None:
    existing = repository.get_order_by_broker_order_id(snapshot.broker_order_id)
    now = _now()
    repository.upsert_order(
        BrokerOrder(
            id=None,
            order_draft_id=existing.order_draft_id if existing is not None else None,
            decision_id=existing.decision_id if existing is not None else None,
            broker_order_id=snapshot.broker_order_id,
            symbol=snapshot.symbol,
            trade_date=existing.trade_date if existing is not None else (trade_date or ""),
            side=snapshot.side.value,
            quantity=snapshot.quantity,
            price=snapshot.price,
            order_type=existing.order_type if existing is not None else None,
            status=_broker_status(snapshot.status),
            raw_status=snapshot.raw_status,
            message=snapshot.message,
            strategy_version=existing.strategy_version if existing is not None else strategy_version,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
    )


def _fill_from_snapshot(snapshot: QmtFillSnapshot) -> BrokerFill:
    return BrokerFill(
        id=None,
        broker_order_id=snapshot.broker_order_id,
        symbol=snapshot.symbol,
        side=snapshot.side.value,
        fill_date=snapshot.fill_date,
        fill_time=snapshot.fill_time,
        quantity=snapshot.quantity,
        price=snapshot.price,
        amount=snapshot.amount,
        fee=snapshot.fee,
        created_at=_now(),
    )


def _apply_filled_orders(
    *,
    db_path: str | Path,
    execution_repository: TradeExecutionRepository,
    trade_date: str | None,
    strategy_version: str,
) -> int:
    position_repository = PositionRepository(db_path)
    position_service = PositionService(position_repository, strategy_version=strategy_version)
    draft_repository = OrderDraftRepository(db_path)
    applied = 0

    for order in execution_repository.list_orders(trade_date=trade_date, status=BrokerOrderStatus.FILLED):
        if order.broker_order_id is None:
            continue
        if execution_repository.get_order_application(order.broker_order_id) is not None:
            continue
        fills = execution_repository.list_fills(broker_order_id=order.broker_order_id)
        if not fills:
            _record_application(
                execution_repository,
                order=order,
                status="SKIPPED",
                message="no_fills",
            )
            continue

        try:
            message = _apply_order_to_position(
                order=order,
                fills=fills,
                position_repository=position_repository,
                position_service=position_service,
                draft_repository=draft_repository,
            )
            _record_application(execution_repository, order=order, status="APPLIED", message=message)
            applied += 1
        except (PositionStateError, ValueError) as exc:
            _record_application(execution_repository, order=order, status="FAILED", message=str(exc))
    return applied


def _apply_order_to_position(
    *,
    order: BrokerOrder,
    fills: list[BrokerFill],
    position_repository: PositionRepository,
    position_service: PositionService,
    draft_repository: OrderDraftRepository,
) -> str:
    avg_price = _average_price(fills)
    trade_date = _fill_trade_date(fills, order.trade_date)
    trade_time = next((fill.fill_time for fill in fills if fill.fill_time), None)
    open_position = position_repository.get_open_position_by_symbol(order.symbol)

    if order.side == QmtOrderSide.BUY.value:
        if open_position is not None:
            return "open_position_exists"
        draft = draft_repository.get_draft(order.order_draft_id) if order.order_draft_id is not None else None
        if draft is None:
            raise ValueError("order_draft_not_found")
        position_service.open_position(
            symbol=order.symbol,
            entry_date=trade_date,
            entry_time=trade_time,
            entry_price=avg_price,
            position_ratio=draft.position_ratio,
            max_position_ratio=draft.position_ratio,
            reason=f"broker_fill:{order.broker_order_id}",
        )
        return "opened_position"

    if open_position is None:
        return "open_position_not_found"
    position_service.reduce_position(
        open_position.id,
        reduce_ratio=open_position.position_ratio,
        price=avg_price,
        trade_date=trade_date,
        trade_time=trade_time,
        reason=f"broker_fill:{order.broker_order_id}",
    )
    return "closed_position"


def _record_application(
    repository: TradeExecutionRepository,
    *,
    order: BrokerOrder,
    status: str,
    message: str,
) -> None:
    repository.insert_order_application(
        BrokerOrderApplication(
            id=None,
            broker_order_id=order.broker_order_id or "",
            symbol=order.symbol,
            side=order.side,
            status=status,
            message=message,
            created_at=_now(),
        )
    )


def _average_price(fills: list[BrokerFill]) -> float:
    total_quantity = sum(float(fill.quantity) for fill in fills)
    if total_quantity <= 0:
        raise ValueError("fill_quantity_is_zero")
    total_amount = sum(float(fill.quantity) * float(fill.price) for fill in fills)
    return total_amount / total_quantity


def _fill_trade_date(fills: list[BrokerFill], fallback: str) -> str:
    return next((fill.fill_date for fill in fills if fill.fill_date), fallback)


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
