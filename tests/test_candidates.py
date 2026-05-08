from __future__ import annotations

import pytest

from strategy.candidates import (
    build_candidate_diagnostics,
    build_candidates,
    diagnose_candidates,
    select_candidates,
    summarize_failure_reasons,
)


def _strategy_config() -> dict[str, object]:
    return {
        "universe": {
            "min_listing_days": 3,
            "min_price": 3,
            "min_avg_amount_20d": 100_000_000,
        },
        "trend": {
            "require_price_above_ma20": True,
            "require_ma_order": True,
            "max_distance_to_ma20": 0.12,
            "max_return_5d": 0.20,
            "max_return_20d": 0.35,
        },
        "strength": {
            "min_return_today": 0.02,
            "max_return_today": 0.065,
            "min_close_position": 0.75,
            "max_upper_shadow_ratio": 0.35,
        },
        "volume": {
            "min_volume_ratio_5d": 1.2,
            "max_volume_ratio_5d": 2.5,
        },
    }


def _feature_frame():
    pd = pytest.importorskip("pandas")
    rows = []
    for index, date in enumerate(["20240101", "20240102", "20240103"]):
        rows.append(_row("000001.SZ", date, close=10 + index, pct_chg=0.03 if index == 2 else 0.01))
        rows.append(_row("600000.SH", date, close=10 + index, pct_chg=0.08 if index == 2 else 0.01))
    return pd.DataFrame(rows)


def _row(symbol: str, date: str, *, close: float, pct_chg: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": date,
        "close": close,
        "pct_chg": pct_chg,
        "ma5": close - 0.2,
        "ma10": close - 0.4,
        "ma20": close - 0.8,
        "return_5d": 0.10,
        "return_20d": 0.20,
        "avg_amount_20d": 200_000_000,
        "volume_ratio_5d": 1.5,
        "close_position_20d": 0.85,
        "distance_to_ma20": 0.06,
        "upper_shadow_ratio": 0.2,
        "is_paused": False,
    }


def test_select_candidates_filters_and_scores() -> None:
    candidates = select_candidates(
        _feature_frame(),
        strategy_config=_strategy_config(),
        trade_date="20240103",
    )

    assert list(candidates["symbol"]) == ["000001.SZ"]
    assert candidates.loc[0, "score"] >= 70
    assert candidates.loc[0, "candidate_level"] in {"watch", "normal", "focus"}


def test_select_candidates_returns_empty_when_no_trade_date_rows() -> None:
    candidates = select_candidates(
        _feature_frame(),
        strategy_config=_strategy_config(),
        trade_date="20240104",
    )

    assert candidates.empty


def test_build_candidates_writes_parquet(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    feature_path = tmp_path / "features.parquet"
    output_path = tmp_path / "candidates.parquet"
    _feature_frame().to_parquet(feature_path, index=False)

    result = build_candidates(
        features_path=feature_path,
        output_path=output_path,
        strategy_config=_strategy_config(),
        trade_date="20240103",
    )

    output = pd.read_parquet(output_path)
    assert result.input_count == 2
    assert result.candidate_count == 1
    assert output.loc[0, "symbol"] == "000001.SZ"


def test_diagnose_candidates_marks_failures() -> None:
    diagnostics = diagnose_candidates(
        _feature_frame(),
        strategy_config=_strategy_config(),
        trade_date="20240103",
    )

    passed = diagnostics.loc[diagnostics["symbol"] == "000001.SZ"].iloc[0]
    failed = diagnostics.loc[diagnostics["symbol"] == "600000.SH"].iloc[0]
    assert passed["passed"]
    assert not failed["passed"]
    assert "max_return_today" in failed["failed_reasons"]


def test_summarize_failure_reasons_counts_each_reason() -> None:
    diagnostics = diagnose_candidates(
        _feature_frame(),
        strategy_config=_strategy_config(),
        trade_date="20240103",
    )

    summary = summarize_failure_reasons(diagnostics)

    assert summary.loc[summary["reason"] == "max_return_today", "count"].item() == 1


def test_build_candidate_diagnostics_writes_outputs(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    feature_path = tmp_path / "features.parquet"
    diagnostics_path = tmp_path / "diagnostics.parquet"
    summary_path = tmp_path / "summary.csv"
    _feature_frame().to_parquet(feature_path, index=False)

    result = build_candidate_diagnostics(
        features_path=feature_path,
        diagnostics_path=diagnostics_path,
        summary_path=summary_path,
        strategy_config=_strategy_config(),
        trade_date="20240103",
    )

    diagnostics = pd.read_parquet(diagnostics_path)
    summary = pd.read_csv(summary_path)
    assert result.input_count == 2
    assert result.passed_count == 1
    assert result.failed_count == 1
    assert len(diagnostics) == 2
    assert "max_return_today" in set(summary["reason"])
