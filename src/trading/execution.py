from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from storage.sqlite import SQLiteStore


class BrokerOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BrokerOrder:
    id: int | None
    order_draft_id: int | None
    decision_id: int | None
    broker_order_id: str | None
    symbol: str
    trade_date: str
    side: str
    quantity: float | None
    price: float | None
    order_type: str | None
    status: BrokerOrderStatus
    raw_status: str | None
    message: str | None
    strategy_version: str | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True)
class BrokerFill:
    id: int | None
    broker_order_id: str | None
    symbol: str
    side: str
    fill_date: str | None
    fill_time: str | None
    quantity: float
    price: float
    amount: float | None
    fee: float | None
    created_at: str | None


class TradeExecutionRepository:
    def __init__(self, store: SQLiteStore | str | Path) -> None:
        self.store = store if isinstance(store, SQLiteStore) else SQLiteStore(store)
        self.store.initialize()

    def upsert_order(self, order: BrokerOrder) -> int:
        sql = """
        INSERT INTO broker_orders (
            order_draft_id, decision_id, broker_order_id, symbol, trade_date, side,
            quantity, price, order_type, status, raw_status, message,
            strategy_version, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(broker_order_id) DO UPDATE SET
            order_draft_id = excluded.order_draft_id,
            decision_id = excluded.decision_id,
            symbol = excluded.symbol,
            trade_date = excluded.trade_date,
            side = excluded.side,
            quantity = excluded.quantity,
            price = excluded.price,
            order_type = excluded.order_type,
            status = excluded.status,
            raw_status = excluded.raw_status,
            message = excluded.message,
            strategy_version = excluded.strategy_version,
            updated_at = excluded.updated_at
        """
        with self.store.connect() as conn:
            conn.execute(sql, _order_values(order))
            conn.commit()
            if order.broker_order_id is not None:
                row = conn.execute(
                    "SELECT id FROM broker_orders WHERE broker_order_id = ?",
                    (order.broker_order_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
            return int(row["id"])

    def update_order_status(
        self,
        *,
        broker_order_id: str,
        status: BrokerOrderStatus,
        raw_status: str | None = None,
        message: str | None = None,
    ) -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                UPDATE broker_orders
                SET status = ?, raw_status = ?, message = ?, updated_at = ?
                WHERE broker_order_id = ?
                """,
                (status.value, raw_status, message, _now(), broker_order_id),
            )
            conn.commit()

    def insert_fill(self, fill: BrokerFill) -> int:
        sql = """
        INSERT INTO broker_fills (
            broker_order_id, symbol, side, fill_date, fill_time,
            quantity, price, amount, fee, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.store.connect() as conn:
            cursor = conn.execute(sql, _fill_values(fill))
            conn.commit()
            return int(cursor.lastrowid)

    def list_orders(
        self,
        *,
        trade_date: str | None = None,
        status: BrokerOrderStatus | None = None,
    ) -> list[BrokerOrder]:
        clauses: list[str] = []
        params: list[object] = []
        if trade_date is not None:
            clauses.append("trade_date = ?")
            params.append(trade_date)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)

        sql = "SELECT * FROM broker_orders"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        with self.store.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_order(row) for row in rows]

    def list_fills(self, *, broker_order_id: str | None = None) -> list[BrokerFill]:
        if broker_order_id is None:
            sql = "SELECT * FROM broker_fills ORDER BY id"
            params: tuple[object, ...] = ()
        else:
            sql = "SELECT * FROM broker_fills WHERE broker_order_id = ? ORDER BY id"
            params = (broker_order_id,)
        with self.store.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_fill(row) for row in rows]


def _order_values(order: BrokerOrder) -> tuple[object, ...]:
    return (
        order.order_draft_id,
        order.decision_id,
        order.broker_order_id,
        order.symbol,
        order.trade_date,
        order.side,
        order.quantity,
        order.price,
        order.order_type,
        order.status.value,
        order.raw_status,
        order.message,
        order.strategy_version,
        order.created_at,
        order.updated_at,
    )


def _fill_values(fill: BrokerFill) -> tuple[object, ...]:
    return (
        fill.broker_order_id,
        fill.symbol,
        fill.side,
        fill.fill_date,
        fill.fill_time,
        fill.quantity,
        fill.price,
        fill.amount,
        fill.fee,
        fill.created_at,
    )


def _row_to_order(row: object) -> BrokerOrder:
    return BrokerOrder(
        id=row["id"],
        order_draft_id=row["order_draft_id"],
        decision_id=row["decision_id"],
        broker_order_id=row["broker_order_id"],
        symbol=row["symbol"],
        trade_date=row["trade_date"],
        side=row["side"],
        quantity=row["quantity"],
        price=row["price"],
        order_type=row["order_type"],
        status=BrokerOrderStatus(row["status"]),
        raw_status=row["raw_status"],
        message=row["message"],
        strategy_version=row["strategy_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_fill(row: object) -> BrokerFill:
    return BrokerFill(
        id=row["id"],
        broker_order_id=row["broker_order_id"],
        symbol=row["symbol"],
        side=row["side"],
        fill_date=row["fill_date"],
        fill_time=row["fill_time"],
        quantity=row["quantity"],
        price=row["price"],
        amount=row["amount"],
        fee=row["fee"],
        created_at=row["created_at"],
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
