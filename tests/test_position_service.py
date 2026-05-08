from __future__ import annotations

import pytest

from position import (
    PositionAction,
    PositionRepository,
    PositionService,
    PositionStateError,
    PositionStatus,
)
from storage.sqlite import SQLiteStore


def _service(tmp_path) -> tuple[PositionService, PositionRepository]:
    store = SQLiteStore(tmp_path / "positions.db")
    repository = PositionRepository(store)
    return PositionService(repository, strategy_version="test-rule"), repository


def test_open_position_creates_position_and_trade(tmp_path):
    service, repository = _service(tmp_path)

    position = service.open_position(
        symbol="000001.SZ",
        name="平安银行",
        entry_date="20260508",
        entry_time="14:55:00",
        entry_price=10.0,
        position_ratio=0.3,
        max_position_ratio=0.5,
        breakout_price=9.8,
        stop_loss_price=9.2,
        take_profit_price=11.0,
        ma10_at_entry=9.5,
        reason="tail breakout",
        signal_score=82.5,
    )

    assert position.id is not None
    assert position.status == PositionStatus.NEW_POSITION
    assert position.last_action == PositionAction.OPEN.value

    saved = repository.get_open_position_by_symbol("000001.SZ")
    assert saved is not None
    assert saved.symbol == "000001.SZ"
    assert saved.position_ratio == 0.3

    trades = repository.list_trades("000001.SZ")
    assert len(trades) == 1
    assert trades[0].action == PositionAction.OPEN
    assert trades[0].price == 10.0
    assert trades[0].position_ratio == 0.3
    assert trades[0].reason == "tail breakout"
    assert trades[0].strategy_version == "test-rule"
    assert trades[0].signal_score == 82.5


def test_open_position_rejects_duplicate_open_symbol(tmp_path):
    service, _ = _service(tmp_path)
    service.open_position(
        symbol="000001.SZ",
        entry_date="20260508",
        entry_price=10.0,
        position_ratio=0.3,
        max_position_ratio=0.5,
    )

    with pytest.raises(PositionStateError, match="Open position already exists"):
        service.open_position(
            symbol="000001.SZ",
            entry_date="20260509",
            entry_price=10.2,
            position_ratio=0.2,
            max_position_ratio=0.5,
        )


def test_mark_status_updates_state_and_records_action(tmp_path):
    service, repository = _service(tmp_path)
    position = service.open_position(
        symbol="000001.SZ",
        entry_date="20260508",
        entry_price=10.0,
        position_ratio=0.3,
        max_position_ratio=0.5,
    )

    updated = service.mark_status(
        position.id,
        status=PositionStatus.ADD_CANDIDATE,
        action=PositionAction.MARK_ADD_CANDIDATE,
        reason="pullback held",
    )

    assert updated.status == PositionStatus.ADD_CANDIDATE
    assert updated.last_action == PositionAction.MARK_ADD_CANDIDATE.value

    trades = repository.list_trades("000001.SZ")
    assert [trade.action for trade in trades] == [
        PositionAction.OPEN,
        PositionAction.MARK_ADD_CANDIDATE,
    ]
    assert trades[-1].reason == "pullback held"


def test_add_position_allows_one_add_within_max_ratio(tmp_path):
    service, repository = _service(tmp_path)
    position = service.open_position(
        symbol="000001.SZ",
        entry_date="20260508",
        entry_price=10.0,
        position_ratio=0.3,
        max_position_ratio=0.5,
    )

    added = service.add_position(
        position.id,
        add_ratio=0.2,
        price=10.5,
        trade_date="20260509",
        trade_time="14:50:00",
        reason="confirmed strength",
    )

    assert added.position_ratio == pytest.approx(0.5)
    assert added.add_count == 1
    assert added.status == PositionStatus.HOLD
    assert added.last_action == PositionAction.ADD.value

    with pytest.raises(PositionStateError, match="only be added once"):
        service.add_position(
            position.id,
            add_ratio=0.1,
            price=10.7,
            trade_date="20260510",
        )

    trades = repository.list_trades("000001.SZ")
    assert trades[-1].action == PositionAction.ADD
    assert trades[-1].position_ratio == pytest.approx(0.5)


def test_add_position_rejects_exceeding_max_ratio(tmp_path):
    service, _ = _service(tmp_path)
    position = service.open_position(
        symbol="000001.SZ",
        entry_date="20260508",
        entry_price=10.0,
        position_ratio=0.3,
        max_position_ratio=0.5,
    )

    with pytest.raises(PositionStateError, match="exceed max_position_ratio"):
        service.add_position(
            position.id,
            add_ratio=0.25,
            price=10.5,
            trade_date="20260509",
        )


def test_reduce_and_close_position_update_open_list(tmp_path):
    service, repository = _service(tmp_path)
    position = service.open_position(
        symbol="000001.SZ",
        entry_date="20260508",
        entry_price=10.0,
        position_ratio=0.5,
        max_position_ratio=0.5,
    )

    reduced = service.reduce_position(
        position.id,
        reduce_ratio=0.2,
        price=10.8,
        trade_date="20260510",
        reason="trim risk",
    )
    assert reduced.position_ratio == pytest.approx(0.3)
    assert reduced.reduce_count == 1
    assert reduced.status == PositionStatus.REDUCE
    assert repository.list_open_positions()[0].id == position.id

    closed = service.close_position(
        position.id,
        price=10.3,
        trade_date="20260511",
        reason="exit signal",
    )
    assert closed.position_ratio == 0.0
    assert closed.status == PositionStatus.CLOSED
    assert repository.get_open_position_by_symbol("000001.SZ") is None
    assert repository.list_open_positions() == []

    with pytest.raises(PositionStateError, match="already closed"):
        service.reduce_position(
            position.id,
            reduce_ratio=0.1,
            price=10.2,
            trade_date="20260512",
        )

    assert [trade.action for trade in repository.list_trades("000001.SZ")] == [
        PositionAction.OPEN,
        PositionAction.REDUCE,
        PositionAction.CLOSE,
    ]
