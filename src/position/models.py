from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PositionStatus(str, Enum):
    NEW_POSITION = "NEW_POSITION"
    HOLD = "HOLD"
    WATCH = "WATCH"
    ADD_CANDIDATE = "ADD_CANDIDATE"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    CLOSED = "CLOSED"


class PositionAction(str, Enum):
    OPEN = "OPEN"
    HOLD = "HOLD"
    WATCH = "WATCH"
    MARK_ADD_CANDIDATE = "MARK_ADD_CANDIDATE"
    ADD = "ADD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    CLOSE = "CLOSE"


@dataclass(frozen=True)
class Position:
    id: int | None
    symbol: str
    name: str | None
    entry_date: str
    entry_time: str | None
    entry_price: float
    position_ratio: float
    max_position_ratio: float
    breakout_price: float | None
    stop_loss_price: float | None
    take_profit_price: float | None
    ma10_at_entry: float | None
    status: PositionStatus
    holding_days: int
    add_count: int
    reduce_count: int
    last_action: str | None
    updated_at: str | None


@dataclass(frozen=True)
class TradeRecord:
    id: int | None
    symbol: str
    trade_date: str
    trade_time: str | None
    action: PositionAction
    price: float
    quantity: float | None
    position_ratio: float | None
    reason: str | None
    strategy_version: str | None
    signal_score: float | None
    market_state: str | None
    created_at: str | None
