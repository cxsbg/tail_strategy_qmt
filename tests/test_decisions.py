from __future__ import annotations

from position import Position, PositionRepository, PositionService, PositionStatus
from storage.sqlite import SQLiteStore
from strategy.decisions import (
    DecisionAction,
    DecisionRepository,
    build_and_store_decisions,
    build_decisions,
)
from strategy.signals import SignalRepository, StrategySignal, SuggestedAction


STRATEGY_CONFIG = {
    "position": {
        "max_total_positions": 2,
        "max_new_positions_per_day": 1,
    }
}


def _signal(
    symbol: str,
    *,
    action: SuggestedAction = SuggestedAction.OPEN,
    score: float = 80.0,
    ratio: float = 0.15,
    signal_id: int | None = None,
    risks: str | None = None,
) -> StrategySignal:
    return StrategySignal(
        id=signal_id,
        symbol=symbol,
        signal_date="20260508",
        signal_time="14:45",
        score=score,
        suggested_action=action,
        suggested_position_ratio=ratio,
        reasons="tail_confirmed",
        risks=risks,
        strategy_version="test-rule",
        created_at="2026-05-08T15:00:00",
    )


def test_build_decisions_limits_new_opens_by_position_config() -> None:
    decisions = build_decisions(
        signals=[
            _signal("000001.SZ", score=90.0),
            _signal("600000.SH", score=85.0),
        ],
        open_positions=[],
        decision_date="20260508",
        strategy_config={
            "position": {
                "max_total_positions": 5,
                "max_new_positions_per_day": 1,
            }
        },
        strategy_version="test-rule",
    )

    by_symbol = {decision.symbol: decision for decision in decisions}
    assert by_symbol["000001.SZ"].action == DecisionAction.OPEN_POSITION
    assert by_symbol["000001.SZ"].suggested_position_ratio == 0.15
    assert by_symbol["600000.SH"].action == DecisionAction.WATCH_SIGNAL
    assert by_symbol["600000.SH"].risks == "new_position_quota_used"


def test_build_decisions_respects_max_total_positions() -> None:
    position = Position(
        id=1,
        symbol="000001.SZ",
        entry_date="20260507",
        entry_time=None,
        entry_price=10.0,
        position_ratio=0.15,
        max_position_ratio=0.15,
        name=None,
        breakout_price=None,
        stop_loss_price=None,
        take_profit_price=None,
        ma10_at_entry=None,
        status=PositionStatus.HOLD,
        holding_days=1,
        add_count=0,
        reduce_count=0,
        last_action=None,
        updated_at=None,
    )

    decisions = build_decisions(
        signals=[_signal("600000.SH", score=90.0)],
        open_positions=[position],
        decision_date="20260508",
        strategy_config={
            "position": {
                "max_total_positions": 1,
                "max_new_positions_per_day": 1,
            }
        },
        strategy_version="test-rule",
    )

    new_decision = next(decision for decision in decisions if decision.symbol == "600000.SH")
    assert new_decision.action == DecisionAction.WATCH_SIGNAL
    assert new_decision.risks == "max_total_positions"


def test_build_decisions_reduces_existing_position_on_skip_signal(tmp_path) -> None:
    service = PositionService(PositionRepository(SQLiteStore(tmp_path / "positions.db")))
    position = service.open_position(
        symbol="000001.SZ",
        entry_date="20260507",
        entry_price=10.0,
        position_ratio=0.15,
        max_position_ratio=0.15,
    )

    decisions = build_decisions(
        signals=[
            _signal(
                "000001.SZ",
                action=SuggestedAction.SKIP,
                score=70.0,
                ratio=0.0,
                risks="tail_not_confirmed",
            )
        ],
        open_positions=[position],
        decision_date="20260508",
        strategy_config=STRATEGY_CONFIG,
        strategy_version="test-rule",
    )

    assert len(decisions) == 1
    assert decisions[0].action == DecisionAction.REDUCE_POSITION
    assert decisions[0].position_id == position.id
    assert decisions[0].suggested_position_ratio == 0.15
    assert decisions[0].risks == "tail_not_confirmed,signal_skip"


def test_decision_repository_replaces_same_date_and_version(tmp_path) -> None:
    repository = DecisionRepository(SQLiteStore(tmp_path / "decisions.db"))
    decisions = build_decisions(
        signals=[_signal("000001.SZ"), _signal("600000.SH", score=75.0)],
        open_positions=[],
        decision_date="20260508",
        strategy_config={
            "position": {
                "max_total_positions": 5,
                "max_new_positions_per_day": 5,
            }
        },
        strategy_version="test-rule",
    )

    first_count = repository.replace_decisions(
        decisions,
        decision_date="20260508",
        strategy_version="test-rule",
    )
    second_count = repository.replace_decisions(
        decisions[:1],
        decision_date="20260508",
        strategy_version="test-rule",
    )

    stored = repository.list_decisions(decision_date="20260508", strategy_version="test-rule")
    assert first_count == 2
    assert second_count == 1
    assert len(stored) == 1
    assert stored[0].symbol == decisions[0].symbol


def test_build_and_store_decisions_reads_signals_and_positions(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    signal_repository = SignalRepository(SQLiteStore(db_path))
    signal_repository.replace_signals(
        [
            _signal("000001.SZ", score=90.0, signal_id=None),
            _signal("600000.SH", score=85.0, signal_id=None),
        ],
        signal_date="20260508",
        strategy_version="test-rule",
    )
    service = PositionService(PositionRepository(SQLiteStore(db_path)))
    service.open_position(
        symbol="300001.SZ",
        entry_date="20260507",
        entry_price=20.0,
        position_ratio=0.15,
        max_position_ratio=0.15,
    )

    output_path = tmp_path / "decisions.parquet"
    result = build_and_store_decisions(
        db_path=db_path,
        strategy_config=STRATEGY_CONFIG,
        decision_date="20260508",
        output_path=output_path,
        strategy_version="test-rule",
    )

    assert result.signal_count == 2
    assert result.open_position_count == 1
    assert result.decision_count == 3
    assert output_path.exists()

    stored = DecisionRepository(db_path).list_decisions(
        decision_date="20260508",
        strategy_version="test-rule",
    )
    assert {decision.action for decision in stored} == {
        DecisionAction.OPEN_POSITION,
        DecisionAction.WATCH_SIGNAL,
        DecisionAction.WATCH_POSITION,
    }
