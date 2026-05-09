from __future__ import annotations

from position import PositionAction, PositionRepository, PositionService, PositionStatus
from storage.parquet import ParquetStorage
from strategy.apply_decisions import (
    DecisionApplicationRepository,
    DecisionApplicationStatus,
    apply_decisions_to_positions,
)
from strategy.decisions import DecisionAction, DecisionRepository, StrategyDecision


STRATEGY_CONFIG = {
    "position": {
        "initial_position_ratio": 0.30,
        "max_single_stock_ratio": 0.15,
    }
}


def test_apply_open_position_creates_position_trade_and_application(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", close=12.34)
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.30))

    result = apply_decisions_to_positions(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=STRATEGY_CONFIG,
        decision_date="20260508",
        strategy_version="test-rule",
    )

    repository = PositionRepository(db_path)
    position = repository.get_open_position_by_symbol("000001.SZ")
    trades = repository.list_trades("000001.SZ")
    applications = DecisionApplicationRepository(db_path).list_applications(decision_date="20260508")

    assert result.applied_count == 1
    assert position is not None
    assert position.entry_price == 12.34
    assert position.position_ratio == 0.15
    assert trades[-1].action == PositionAction.OPEN
    assert trades[-1].reason == "tail_confirmed"
    assert applications[0].status == DecisionApplicationStatus.APPLIED


def test_apply_decisions_is_idempotent_for_applied_decision(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", close=12.34)
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    apply_decisions_to_positions(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=STRATEGY_CONFIG,
        decision_date="20260508",
        strategy_version="test-rule",
    )
    second = apply_decisions_to_positions(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=STRATEGY_CONFIG,
        decision_date="20260508",
        strategy_version="test-rule",
    )

    trades = PositionRepository(db_path).list_trades("000001.SZ")
    assert second.already_applied_count == 1
    assert len(trades) == 1


def test_apply_reduce_position_closes_existing_position(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", close=9.5)
    position = PositionService(PositionRepository(db_path), strategy_version="test-rule").open_position(
        symbol="000001.SZ",
        entry_date="20260507",
        entry_price=10.0,
        position_ratio=0.15,
        max_position_ratio=0.15,
    )
    _store_decision(
        db_path,
        _decision(
            "000001.SZ",
            DecisionAction.REDUCE_POSITION,
            position_id=position.id,
            risks="signal_skip",
        ),
    )

    result = apply_decisions_to_positions(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=STRATEGY_CONFIG,
        decision_date="20260508",
        strategy_version="test-rule",
    )

    repository = PositionRepository(db_path)
    updated = repository.get_position(position.id)
    trades = repository.list_trades("000001.SZ")

    assert result.applied_count == 1
    assert updated.status == PositionStatus.CLOSED
    assert updated.position_ratio == 0.0
    assert trades[-1].action == PositionAction.REDUCE
    assert trades[-1].price == 9.5
    assert trades[-1].reason == "tail_confirmed,signal_skip"


def test_apply_decisions_dry_run_does_not_write_positions_or_applications(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", close=12.34)
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = apply_decisions_to_positions(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=STRATEGY_CONFIG,
        decision_date="20260508",
        strategy_version="test-rule",
        dry_run=True,
    )

    assert result.dry_run_count == 1
    assert PositionRepository(db_path).list_open_positions() == []
    assert DecisionApplicationRepository(db_path).list_applications(decision_date="20260508") == []


def test_missing_daily_close_records_failed_application_and_can_retry(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    failed = apply_decisions_to_positions(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=STRATEGY_CONFIG,
        decision_date="20260508",
        strategy_version="test-rule",
    )
    _write_daily(parquet_root, "000001.SZ", close=12.34)
    retried = apply_decisions_to_positions(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=STRATEGY_CONFIG,
        decision_date="20260508",
        strategy_version="test-rule",
    )

    applications = DecisionApplicationRepository(db_path).list_applications(decision_date="20260508")
    assert failed.failed_count == 1
    assert retried.applied_count == 1
    assert applications[0].status == DecisionApplicationStatus.APPLIED
    assert PositionRepository(db_path).get_open_position_by_symbol("000001.SZ") is not None


def _store_decision(db_path, decision: StrategyDecision) -> None:
    DecisionRepository(db_path).replace_decisions(
        [decision],
        decision_date=decision.decision_date,
        strategy_version=decision.strategy_version,
    )


def _decision(
    symbol: str,
    action: DecisionAction,
    *,
    ratio: float | None = 0.15,
    position_id: int | None = None,
    risks: str | None = None,
) -> StrategyDecision:
    return StrategyDecision(
        id=None,
        symbol=symbol,
        decision_date="20260508",
        source_signal_id=None,
        position_id=position_id,
        action=action,
        score=80.0,
        suggested_position_ratio=ratio,
        reasons="tail_confirmed",
        risks=risks,
        strategy_version="test-rule",
        created_at="2026-05-08T15:00:00",
    )


def _write_daily(parquet_root, symbol: str, *, close: float) -> None:
    import pandas as pd

    ParquetStorage(parquet_root).write_frame(
        "daily",
        symbol,
        pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "date": "20260508",
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.3,
                    "close": close,
                    "volume": 1000000,
                    "amount": 12340000,
                }
            ]
        ),
    )
