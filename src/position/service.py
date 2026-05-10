from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from position.models import Position, PositionAction, PositionStatus, TradeRecord
from position.repository import PositionRepository
from utils.exceptions import TailStrategyError


class PositionStateError(TailStrategyError):
    """Raised when a requested position transition is invalid."""


class PositionService:
    def __init__(
        self,
        repository: PositionRepository,
        *,
        strategy_version: str = "rule-v0",
    ) -> None:
        self.repository = repository
        self.strategy_version = strategy_version

    def open_position(
        self,
        *,
        symbol: str,
        entry_date: str,
        entry_price: float,
        position_ratio: float,
        max_position_ratio: float,
        name: str | None = None,
        entry_time: str | None = None,
        breakout_price: float | None = None,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
        ma10_at_entry: float | None = None,
        reason: str | None = None,
        signal_score: float | None = None,
    ) -> Position:
        if self.repository.get_open_position_by_symbol(symbol) is not None:
            raise PositionStateError(f"Open position already exists for {symbol}.")

        now = _now()
        position = Position(
            id=None,
            symbol=symbol,
            name=name,
            entry_date=entry_date,
            entry_time=entry_time,
            entry_price=entry_price,
            position_ratio=position_ratio,
            max_position_ratio=max_position_ratio,
            breakout_price=breakout_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            ma10_at_entry=ma10_at_entry,
            status=PositionStatus.NEW_POSITION,
            holding_days=0,
            add_count=0,
            reduce_count=0,
            last_action=PositionAction.OPEN.value,
            updated_at=now,
        )
        position_id = self.repository.insert_position(position)
        saved = replace(position, id=position_id)
        self._record_trade(
            position=saved,
            action=PositionAction.OPEN,
            trade_date=entry_date,
            trade_time=entry_time,
            price=entry_price,
            reason=reason,
            signal_score=signal_score,
        )
        return saved

    def mark_status(
        self,
        position_id: int,
        *,
        status: PositionStatus,
        action: PositionAction,
        reason: str | None = None,
    ) -> Position:
        position = self._require_position(position_id)
        updated = replace(
            position,
            status=status,
            last_action=action.value,
            updated_at=_now(),
        )
        self.repository.update_position(updated)
        self._record_trade(
            position=updated,
            action=action,
            trade_date=updated.entry_date,
            trade_time=None,
            price=updated.entry_price,
            reason=reason,
        )
        return updated

    def add_position(
        self,
        position_id: int,
        *,
        add_ratio: float,
        price: float,
        trade_date: str,
        trade_time: str | None = None,
        reason: str | None = None,
    ) -> Position:
        position = self._require_position(position_id)
        if position.add_count >= 1:
            raise PositionStateError("Single position can only be added once.")
        next_ratio = position.position_ratio + add_ratio
        if next_ratio > position.max_position_ratio:
            raise PositionStateError("Position ratio would exceed max_position_ratio.")

        updated = replace(
            position,
            position_ratio=next_ratio,
            status=PositionStatus.HOLD,
            add_count=position.add_count + 1,
            last_action=PositionAction.ADD.value,
            updated_at=_now(),
        )
        self.repository.update_position(updated)
        self._record_trade(
            position=updated,
            action=PositionAction.ADD,
            trade_date=trade_date,
            trade_time=trade_time,
            price=price,
            reason=reason,
        )
        return updated

    def increase_position_from_fill(
        self,
        position_id: int,
        *,
        add_ratio: float,
        price: float,
        trade_date: str,
        trade_time: str | None = None,
        reason: str | None = None,
    ) -> Position:
        position = self._require_position(position_id)
        if add_ratio <= 0:
            raise PositionStateError("add_ratio must be positive.")
        next_ratio = position.position_ratio + add_ratio
        if next_ratio > position.max_position_ratio + 1e-9:
            raise PositionStateError("Position ratio would exceed max_position_ratio.")

        updated = replace(
            position,
            position_ratio=min(next_ratio, position.max_position_ratio),
            status=PositionStatus.HOLD,
            add_count=position.add_count + 1,
            last_action=PositionAction.ADD.value,
            updated_at=_now(),
        )
        self.repository.update_position(updated)
        self._record_trade(
            position=updated,
            action=PositionAction.ADD,
            trade_date=trade_date,
            trade_time=trade_time,
            price=price,
            reason=reason,
        )
        return updated

    def reduce_position(
        self,
        position_id: int,
        *,
        reduce_ratio: float,
        price: float,
        trade_date: str,
        trade_time: str | None = None,
        reason: str | None = None,
    ) -> Position:
        position = self._require_position(position_id)
        next_ratio = max(0.0, position.position_ratio - reduce_ratio)
        next_status = PositionStatus.CLOSED if next_ratio == 0 else PositionStatus.REDUCE
        updated = replace(
            position,
            position_ratio=next_ratio,
            status=next_status,
            reduce_count=position.reduce_count + 1,
            last_action=PositionAction.REDUCE.value,
            updated_at=_now(),
        )
        self.repository.update_position(updated)
        self._record_trade(
            position=updated,
            action=PositionAction.REDUCE,
            trade_date=trade_date,
            trade_time=trade_time,
            price=price,
            reason=reason,
        )
        return updated

    def close_position(
        self,
        position_id: int,
        *,
        price: float,
        trade_date: str,
        trade_time: str | None = None,
        reason: str | None = None,
    ) -> Position:
        position = self._require_position(position_id)
        updated = replace(
            position,
            position_ratio=0.0,
            status=PositionStatus.CLOSED,
            last_action=PositionAction.CLOSE.value,
            updated_at=_now(),
        )
        self.repository.update_position(updated)
        self._record_trade(
            position=updated,
            action=PositionAction.CLOSE,
            trade_date=trade_date,
            trade_time=trade_time,
            price=price,
            reason=reason,
        )
        return updated

    def _require_position(self, position_id: int) -> Position:
        position = self.repository.get_position(position_id)
        if position is None:
            raise PositionStateError(f"Position not found: {position_id}")
        if position.status == PositionStatus.CLOSED:
            raise PositionStateError(f"Position is already closed: {position_id}")
        return position

    def _record_trade(
        self,
        *,
        position: Position,
        action: PositionAction,
        trade_date: str,
        trade_time: str | None,
        price: float,
        reason: str | None,
        signal_score: float | None = None,
    ) -> None:
        self.repository.insert_trade(
            TradeRecord(
                id=None,
                symbol=position.symbol,
                trade_date=trade_date,
                trade_time=trade_time,
                action=action,
                price=price,
                quantity=None,
                position_ratio=position.position_ratio,
                reason=reason,
                strategy_version=self.strategy_version,
                signal_score=signal_score,
                market_state=None,
                created_at=_now(),
            )
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
