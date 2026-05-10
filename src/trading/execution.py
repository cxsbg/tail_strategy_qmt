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


@dataclass(frozen=True)
class BrokerOrderApplication:
    id: int | None
    broker_order_id: str
    symbol: str
    side: str
    status: str
    message: str | None
    created_at: str | None


@dataclass(frozen=True)
class BrokerFillApplication:
    id: int | None
    fill_id: int
    broker_order_id: str | None
    symbol: str
    side: str
    status: str
    message: str | None
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

    def get_order_by_broker_order_id(self, broker_order_id: str) -> BrokerOrder | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM broker_orders WHERE broker_order_id = ?",
                (broker_order_id,),
            ).fetchone()
        return _row_to_order(row) if row else None

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

    def upsert_fill(self, fill: BrokerFill) -> tuple[int, bool]:
        existing = self._find_matching_fill(fill)
        if existing is not None:
            return existing.id or 0, False
        return self.insert_fill(fill), True

    def get_order_application(self, broker_order_id: str) -> BrokerOrderApplication | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM broker_order_applications WHERE broker_order_id = ?",
                (broker_order_id,),
            ).fetchone()
        return _row_to_application(row) if row else None

    def insert_order_application(self, application: BrokerOrderApplication) -> int:
        sql = """
        INSERT INTO broker_order_applications (
            broker_order_id, symbol, side, status, message, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(broker_order_id) DO UPDATE SET
            symbol = excluded.symbol,
            side = excluded.side,
            status = excluded.status,
            message = excluded.message,
            created_at = excluded.created_at
        """
        with self.store.connect() as conn:
            conn.execute(sql, _application_values(application))
            conn.commit()
            row = conn.execute(
                "SELECT id FROM broker_order_applications WHERE broker_order_id = ?",
                (application.broker_order_id,),
            ).fetchone()
            return int(row["id"])

    def get_fill_application(self, fill_id: int) -> BrokerFillApplication | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM broker_fill_applications WHERE fill_id = ?",
                (fill_id,),
            ).fetchone()
        return _row_to_fill_application(row) if row else None

    def insert_fill_application(self, application: BrokerFillApplication) -> int:
        sql = """
        INSERT INTO broker_fill_applications (
            fill_id, broker_order_id, symbol, side, status, message, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fill_id) DO UPDATE SET
            broker_order_id = excluded.broker_order_id,
            symbol = excluded.symbol,
            side = excluded.side,
            status = excluded.status,
            message = excluded.message,
            created_at = excluded.created_at
        """
        with self.store.connect() as conn:
            conn.execute(sql, _fill_application_values(application))
            conn.commit()
            row = conn.execute(
                "SELECT id FROM broker_fill_applications WHERE fill_id = ?",
                (application.fill_id,),
            ).fetchone()
            return int(row["id"])

    def list_fill_applications(self) -> list[BrokerFillApplication]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT * FROM broker_fill_applications ORDER BY id").fetchall()
        return [_row_to_fill_application(row) for row in rows]

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

    def _find_matching_fill(self, fill: BrokerFill) -> BrokerFill | None:
        sql = """
        SELECT *
        FROM broker_fills
        WHERE
            COALESCE(broker_order_id, '') = COALESCE(?, '')
            AND symbol = ?
            AND side = ?
            AND COALESCE(fill_date, '') = COALESCE(?, '')
            AND COALESCE(fill_time, '') = COALESCE(?, '')
            AND quantity = ?
            AND price = ?
        LIMIT 1
        """
        with self.store.connect() as conn:
            row = conn.execute(
                sql,
                (
                    fill.broker_order_id,
                    fill.symbol,
                    fill.side,
                    fill.fill_date,
                    fill.fill_time,
                    fill.quantity,
                    fill.price,
                ),
            ).fetchone()
        return _row_to_fill(row) if row else None


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


def _application_values(application: BrokerOrderApplication) -> tuple[object, ...]:
    return (
        application.broker_order_id,
        application.symbol,
        application.side,
        application.status,
        application.message,
        application.created_at,
    )


def _fill_application_values(application: BrokerFillApplication) -> tuple[object, ...]:
    return (
        application.fill_id,
        application.broker_order_id,
        application.symbol,
        application.side,
        application.status,
        application.message,
        application.created_at,
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


def _row_to_application(row: object) -> BrokerOrderApplication:
    return BrokerOrderApplication(
        id=row["id"],
        broker_order_id=row["broker_order_id"],
        symbol=row["symbol"],
        side=row["side"],
        status=row["status"],
        message=row["message"],
        created_at=row["created_at"],
    )


def _row_to_fill_application(row: object) -> BrokerFillApplication:
    return BrokerFillApplication(
        id=row["id"],
        fill_id=row["fill_id"],
        broker_order_id=row["broker_order_id"],
        symbol=row["symbol"],
        side=row["side"],
        status=row["status"],
        message=row["message"],
        created_at=row["created_at"],
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
