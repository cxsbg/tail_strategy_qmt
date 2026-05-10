from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from position import PositionRepository, PositionService
from position.service import PositionStateError
from qmt.trader import QmtFillSnapshot, QmtOrderSide, QmtOrderSnapshot, QmtOrderStatus, QmtTrader
from trading.execution import (
    BrokerFill,
    BrokerFillApplication,
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

    orders = [
        order
        for order in execution_repository.list_orders(trade_date=trade_date)
        if order.status in {BrokerOrderStatus.PARTIAL_FILLED, BrokerOrderStatus.FILLED}
    ]
    for order in orders:
        if order.broker_order_id is None:
            continue
        fills = execution_repository.list_fills(broker_order_id=order.broker_order_id)
        if not fills:
            if order.status == BrokerOrderStatus.FILLED:
                _record_order_application(
                    execution_repository,
                    order=order,
                    status="SKIPPED",
                    message="no_fills",
                )
            continue

        order_applied = 0
        order_failures = 0
        try:
            for fill in fills:
                if fill.id is None:
                    continue
                if execution_repository.get_fill_application(fill.id) is not None:
                    continue
                message = _apply_fill_to_position(
                    order=order,
                    fill=fill,
                    position_repository=position_repository,
                    position_service=position_service,
                    draft_repository=draft_repository,
                )
                status = "SKIPPED" if message.endswith("_not_found") or message.endswith("_exists") else "APPLIED"
                _record_fill_application(
                    execution_repository,
                    fill=fill,
                    status=status,
                    message=message,
                )
                if status == "APPLIED":
                    applied += 1
                    order_applied += 1
        except (PositionStateError, ValueError) as exc:
            order_failures += 1
            if fill.id is not None:
                _record_fill_application(
                    execution_repository,
                    fill=fill,
                    status="FAILED",
                    message=str(exc),
                )

        if order.status == BrokerOrderStatus.FILLED:
            order_applied = _count_fill_applications(
                execution_repository,
                fills=fills,
                status="APPLIED",
            )
            order_failures = _count_fill_applications(
                execution_repository,
                fills=fills,
                status="FAILED",
            )
            _record_order_completion(
                repository=execution_repository,
                order=order,
                fill_count=len(fills),
                applied_count=order_applied,
                failure_count=order_failures,
            )
    return applied


def _apply_fill_to_position(
    *,
    order: BrokerOrder,
    fill: BrokerFill,
    position_repository: PositionRepository,
    position_service: PositionService,
    draft_repository: OrderDraftRepository,
) -> str:
    if fill.quantity <= 0:
        raise ValueError("fill_quantity_is_zero")
    trade_date = fill.fill_date or order.trade_date
    trade_time = fill.fill_time
    open_position = position_repository.get_open_position_by_symbol(order.symbol)

    if order.side == QmtOrderSide.BUY.value:
        draft = draft_repository.get_draft(order.order_draft_id) if order.order_draft_id is not None else None
        if draft is None:
            raise ValueError("order_draft_not_found")
        fill_ratio = _buy_fill_position_ratio(order=order, fill=fill, target_ratio=draft.position_ratio)
        if open_position is not None:
            position_service.increase_position_from_fill(
                open_position.id,
                add_ratio=fill_ratio,
                price=fill.price,
                trade_date=trade_date,
                trade_time=trade_time,
                reason=f"broker_fill:{order.broker_order_id}:{fill.id}",
            )
            return "added_position"
        position_service.open_position(
            symbol=order.symbol,
            entry_date=trade_date,
            entry_time=trade_time,
            entry_price=fill.price,
            position_ratio=fill_ratio,
            max_position_ratio=draft.position_ratio,
            reason=f"broker_fill:{order.broker_order_id}:{fill.id}",
        )
        return "opened_position"

    if open_position is None:
        return "open_position_not_found"
    draft = draft_repository.get_draft(order.order_draft_id) if order.order_draft_id is not None else None
    target_ratio = draft.position_ratio if draft is not None else open_position.max_position_ratio
    reduce_ratio = _sell_fill_reduce_ratio(
        order=order,
        fill=fill,
        current_ratio=open_position.position_ratio,
        target_ratio=target_ratio,
    )
    position_service.reduce_position(
        open_position.id,
        reduce_ratio=reduce_ratio,
        price=fill.price,
        trade_date=trade_date,
        trade_time=trade_time,
        reason=f"broker_fill:{order.broker_order_id}:{fill.id}",
    )
    return "closed_position" if reduce_ratio >= open_position.position_ratio else "reduced_position"


def _buy_fill_position_ratio(*, order: BrokerOrder, fill: BrokerFill, target_ratio: float) -> float:
    if order.quantity is None or order.quantity <= 0:
        raise ValueError("order_quantity_missing")
    fill_fraction = min(1.0, float(fill.quantity) / float(order.quantity))
    fill_ratio = target_ratio * fill_fraction
    if fill_ratio <= 0:
        raise ValueError("fill_position_ratio_is_zero")
    return fill_ratio


def _sell_fill_reduce_ratio(
    *,
    order: BrokerOrder,
    fill: BrokerFill,
    current_ratio: float,
    target_ratio: float,
) -> float:
    if order.quantity is None or order.quantity <= 0:
        return current_ratio
    fill_fraction = min(1.0, float(fill.quantity) / float(order.quantity))
    reduce_ratio = target_ratio * fill_fraction
    if reduce_ratio <= 0:
        raise ValueError("fill_reduce_ratio_is_zero")
    return min(current_ratio, reduce_ratio)


def _record_order_completion(
    *,
    repository: TradeExecutionRepository,
    order: BrokerOrder,
    fill_count: int,
    applied_count: int,
    failure_count: int,
) -> None:
    existing = repository.get_order_application(order.broker_order_id or "")
    if existing is not None:
        return
    if failure_count:
        status = "FAILED"
        message = f"fills={fill_count}; applied={applied_count}; failed={failure_count}"
    elif applied_count:
        status = "APPLIED"
        message = f"fills={fill_count}; applied={applied_count}"
    else:
        status = "SKIPPED"
        message = f"fills={fill_count}; applied=0"
    _record_order_application(repository, order=order, status=status, message=message)


def _count_fill_applications(
    repository: TradeExecutionRepository,
    *,
    fills: list[BrokerFill],
    status: str,
) -> int:
    count = 0
    for fill in fills:
        if fill.id is None:
            continue
        application = repository.get_fill_application(fill.id)
        if application is not None and application.status == status:
            count += 1
    return count


def _record_order_application(
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


def _record_fill_application(
    repository: TradeExecutionRepository,
    *,
    fill: BrokerFill,
    status: str,
    message: str,
) -> None:
    if fill.id is None:
        return
    repository.insert_fill_application(
        BrokerFillApplication(
            id=None,
            fill_id=fill.id,
            broker_order_id=fill.broker_order_id,
            symbol=fill.symbol,
            side=fill.side,
            status=status,
            message=message,
            created_at=_now(),
        )
    )


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
