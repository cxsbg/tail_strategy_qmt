from __future__ import annotations

from pathlib import Path

from position.models import Position, PositionAction, PositionStatus, TradeRecord
from storage.sqlite import SQLiteStore


class PositionRepository:
    def __init__(self, store: SQLiteStore | str | Path) -> None:
        self.store = store if isinstance(store, SQLiteStore) else SQLiteStore(store)
        self.store.initialize()

    def insert_position(self, position: Position) -> int:
        sql = """
        INSERT INTO positions (
            symbol, name, entry_date, entry_time, entry_price, position_ratio,
            max_position_ratio, breakout_price, stop_loss_price, take_profit_price,
            ma10_at_entry, status, holding_days, add_count, reduce_count,
            last_action, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.store.connect() as conn:
            cursor = conn.execute(sql, _position_values(position))
            conn.commit()
            return int(cursor.lastrowid)

    def update_position(self, position: Position) -> None:
        if position.id is None:
            raise ValueError("Cannot update a position without id.")
        sql = """
        UPDATE positions
        SET
            symbol = ?,
            name = ?,
            entry_date = ?,
            entry_time = ?,
            entry_price = ?,
            position_ratio = ?,
            max_position_ratio = ?,
            breakout_price = ?,
            stop_loss_price = ?,
            take_profit_price = ?,
            ma10_at_entry = ?,
            status = ?,
            holding_days = ?,
            add_count = ?,
            reduce_count = ?,
            last_action = ?,
            updated_at = ?
        WHERE id = ?
        """
        with self.store.connect() as conn:
            conn.execute(sql, (*_position_values(position), position.id))
            conn.commit()

    def get_position(self, position_id: int) -> Position | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
        return _row_to_position(row) if row else None

    def get_open_position_by_symbol(self, symbol: str) -> Position | None:
        sql = """
        SELECT *
        FROM positions
        WHERE symbol = ? AND status != ?
        ORDER BY id DESC
        LIMIT 1
        """
        with self.store.connect() as conn:
            row = conn.execute(sql, (symbol, PositionStatus.CLOSED.value)).fetchone()
        return _row_to_position(row) if row else None

    def list_open_positions(self) -> list[Position]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status != ? ORDER BY entry_date, symbol",
                (PositionStatus.CLOSED.value,),
            ).fetchall()
        return [_row_to_position(row) for row in rows]

    def insert_trade(self, trade: TradeRecord) -> int:
        sql = """
        INSERT INTO trades (
            symbol, trade_date, trade_time, action, price, quantity, position_ratio,
            reason, strategy_version, signal_score, market_state, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.store.connect() as conn:
            cursor = conn.execute(sql, _trade_values(trade))
            conn.commit()
            return int(cursor.lastrowid)

    def list_trades(self, symbol: str | None = None) -> list[TradeRecord]:
        if symbol is None:
            sql = "SELECT * FROM trades ORDER BY id"
            params: tuple[object, ...] = ()
        else:
            sql = "SELECT * FROM trades WHERE symbol = ? ORDER BY id"
            params = (symbol,)
        with self.store.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_trade(row) for row in rows]


def _position_values(position: Position) -> tuple[object, ...]:
    return (
        position.symbol,
        position.name,
        position.entry_date,
        position.entry_time,
        position.entry_price,
        position.position_ratio,
        position.max_position_ratio,
        position.breakout_price,
        position.stop_loss_price,
        position.take_profit_price,
        position.ma10_at_entry,
        position.status.value,
        position.holding_days,
        position.add_count,
        position.reduce_count,
        position.last_action,
        position.updated_at,
    )


def _trade_values(trade: TradeRecord) -> tuple[object, ...]:
    return (
        trade.symbol,
        trade.trade_date,
        trade.trade_time,
        trade.action.value,
        trade.price,
        trade.quantity,
        trade.position_ratio,
        trade.reason,
        trade.strategy_version,
        trade.signal_score,
        trade.market_state,
        trade.created_at,
    )


def _row_to_position(row) -> Position:
    return Position(
        id=row["id"],
        symbol=row["symbol"],
        name=row["name"],
        entry_date=row["entry_date"],
        entry_time=row["entry_time"],
        entry_price=row["entry_price"],
        position_ratio=row["position_ratio"],
        max_position_ratio=row["max_position_ratio"],
        breakout_price=row["breakout_price"],
        stop_loss_price=row["stop_loss_price"],
        take_profit_price=row["take_profit_price"],
        ma10_at_entry=row["ma10_at_entry"],
        status=PositionStatus(row["status"]),
        holding_days=row["holding_days"],
        add_count=row["add_count"],
        reduce_count=row["reduce_count"],
        last_action=row["last_action"],
        updated_at=row["updated_at"],
    )


def _row_to_trade(row) -> TradeRecord:
    return TradeRecord(
        id=row["id"],
        symbol=row["symbol"],
        trade_date=row["trade_date"],
        trade_time=row["trade_time"],
        action=PositionAction(row["action"]),
        price=row["price"],
        quantity=row["quantity"],
        position_ratio=row["position_ratio"],
        reason=row["reason"],
        strategy_version=row["strategy_version"],
        signal_score=row["signal_score"],
        market_state=row["market_state"],
        created_at=row["created_at"],
    )
