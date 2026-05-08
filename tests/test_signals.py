from __future__ import annotations

import pandas as pd

from strategy.signals import (
    SignalRepository,
    SuggestedAction,
    build_and_store_signals,
    build_signals,
)
from storage.sqlite import SQLiteStore


STRATEGY_CONFIG = {
    "position": {
        "initial_position_ratio": 0.30,
        "max_single_stock_ratio": 0.15,
    }
}


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "20260508",
                "score": 88.0,
                "candidate_level": "focus",
                "reasons": "price_above_ma20,volume_confirmed",
            },
            {
                "symbol": "600000.SH",
                "date": "20260508",
                "score": 76.0,
                "candidate_level": "normal",
                "reasons": "price_above_ma20",
            },
            {
                "symbol": "300001.SZ",
                "date": "20260508",
                "score": 72.0,
                "candidate_level": "watch",
                "reasons": "price_above_ma20",
            },
        ]
    )


def _tail_confirmations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "20260508",
                "tail_confirmed": True,
                "failed_reasons": "",
                "tail_confirm_time": "14:45",
            },
            {
                "symbol": "600000.SH",
                "date": "20260508",
                "tail_confirmed": False,
                "failed_reasons": "tail_volume_ratio",
                "tail_confirm_time": "14:45",
            },
        ]
    )


def test_build_signals_combines_candidates_and_tail_confirmation() -> None:
    signals = build_signals(
        _candidates(),
        strategy_config=STRATEGY_CONFIG,
        tail_confirmations=_tail_confirmations(),
        strategy_version="test-rule",
    )

    by_symbol = signals.set_index("symbol")

    assert by_symbol.loc["000001.SZ", "suggested_action"] == SuggestedAction.OPEN.value
    assert by_symbol.loc["000001.SZ", "suggested_position_ratio"] == 0.15
    assert by_symbol.loc["000001.SZ", "risks"] is None
    assert "tail_confirmed" in by_symbol.loc["000001.SZ", "reasons"]
    assert by_symbol.loc["000001.SZ", "signal_time"] == "14:45"

    assert by_symbol.loc["600000.SH", "suggested_action"] == SuggestedAction.SKIP.value
    assert by_symbol.loc["600000.SH", "suggested_position_ratio"] == 0.0
    assert by_symbol.loc["600000.SH", "risks"] == "tail_not_confirmed,tail_volume_ratio"

    assert by_symbol.loc["300001.SZ", "suggested_action"] == SuggestedAction.WATCH.value
    assert by_symbol.loc["300001.SZ", "risks"] == "missing_tail_confirmation"


def test_build_signals_returns_empty_for_missing_date() -> None:
    signals = build_signals(
        _candidates(),
        strategy_config=STRATEGY_CONFIG,
        tail_confirmations=_tail_confirmations(),
        trade_date="20260509",
    )

    assert list(signals.columns) == [
        "symbol",
        "signal_date",
        "signal_time",
        "score",
        "suggested_action",
        "suggested_position_ratio",
        "reasons",
        "risks",
        "strategy_version",
        "created_at",
    ]
    assert signals.empty


def test_signal_repository_replaces_same_date_and_version(tmp_path) -> None:
    repository = SignalRepository(SQLiteStore(tmp_path / "signals.db"))
    signals = build_signals(
        _candidates().head(2),
        strategy_config=STRATEGY_CONFIG,
        tail_confirmations=_tail_confirmations(),
        strategy_version="test-rule",
    )

    first_count = repository.replace_signals(
        _to_signal_models(signals),
        signal_date="20260508",
        strategy_version="test-rule",
    )
    second_count = repository.replace_signals(
        _to_signal_models(signals.head(1)),
        signal_date="20260508",
        strategy_version="test-rule",
    )

    stored = repository.list_signals(signal_date="20260508", strategy_version="test-rule")
    assert first_count == 2
    assert second_count == 1
    assert len(stored) == 1
    assert stored[0].symbol == "000001.SZ"
    assert stored[0].suggested_action == SuggestedAction.OPEN


def test_build_and_store_signals_writes_parquet_and_sqlite(tmp_path) -> None:
    candidates_path = tmp_path / "candidates.parquet"
    tail_path = tmp_path / "tail.parquet"
    output_path = tmp_path / "signals.parquet"
    db_path = tmp_path / "signals.db"
    _candidates().to_parquet(candidates_path, index=False)
    _tail_confirmations().to_parquet(tail_path, index=False)

    result = build_and_store_signals(
        candidates_path=candidates_path,
        tail_confirmation_path=tail_path,
        output_path=output_path,
        db_path=db_path,
        strategy_config=STRATEGY_CONFIG,
        strategy_version="test-rule",
    )

    assert result.date == "20260508"
    assert result.input_count == 3
    assert result.signal_count == 3
    assert output_path.exists()

    stored = SignalRepository(db_path).list_signals(
        signal_date="20260508",
        strategy_version="test-rule",
    )
    assert len(stored) == 3
    assert {signal.suggested_action for signal in stored} == {
        SuggestedAction.OPEN,
        SuggestedAction.SKIP,
        SuggestedAction.WATCH,
    }


def _to_signal_models(frame: pd.DataFrame):
    from strategy.signals import StrategySignal

    return [
        StrategySignal(
            id=None,
            symbol=row["symbol"],
            signal_date=row["signal_date"],
            signal_time=row["signal_time"],
            score=row["score"],
            suggested_action=SuggestedAction(row["suggested_action"]),
            suggested_position_ratio=row["suggested_position_ratio"],
            reasons=row["reasons"],
            risks=row["risks"],
            strategy_version=row["strategy_version"],
            created_at=row["created_at"],
        )
        for _, row in frame.iterrows()
    ]
