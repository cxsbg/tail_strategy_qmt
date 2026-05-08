from __future__ import annotations

import pytest

from backtest.simple import build_decision_backtest, run_decision_backtest
from storage.parquet import ParquetStorage


def test_run_decision_backtest_simulates_open_position_decisions(tmp_path) -> None:
    pd = pytest.importorskip("pandas")
    storage = ParquetStorage(tmp_path / "parquet")
    storage.write_frame("daily", "000001.SZ", _daily_frame())
    decisions = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "decision_date": "20240103",
                "action": "OPEN_POSITION",
                "score": 88.0,
                "suggested_position_ratio": 0.15,
            },
            {
                "symbol": "600000.SH",
                "decision_date": "20240103",
                "action": "WATCH_SIGNAL",
                "score": 80.0,
                "suggested_position_ratio": 0.0,
            },
        ]
    )

    trades, summary = run_decision_backtest(
        decisions,
        storage=storage,
        holding_days=3,
    )

    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade["symbol"] == "000001.SZ"
    assert trade["entry_date"] == "20240104"
    assert trade["exit_date"] == "20240106"
    assert trade["entry_price"] == pytest.approx(13.0)
    assert trade["exit_price"] == pytest.approx(16.0)
    assert trade["gross_return"] == pytest.approx((16.0 / 13.0) - 1.0)
    assert trade["weighted_return"] == pytest.approx(((16.0 / 13.0) - 1.0) * 0.15)
    assert summary["decision_count"] == 1
    assert summary["trade_count"] == 1
    assert summary["skipped_count"] == 0
    assert summary["win_rate"] == 1.0


def test_run_decision_backtest_counts_missing_daily_cache_as_skipped(tmp_path) -> None:
    pd = pytest.importorskip("pandas")
    decisions = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "decision_date": "20240103",
                "action": "OPEN_POSITION",
                "score": 88.0,
                "suggested_position_ratio": 0.15,
            }
        ]
    )

    trades, summary = run_decision_backtest(
        decisions,
        storage=ParquetStorage(tmp_path / "parquet"),
        holding_days=3,
    )

    assert trades.empty
    assert summary["decision_count"] == 1
    assert summary["trade_count"] == 0
    assert summary["skipped_count"] == 1


def test_build_decision_backtest_writes_outputs(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    storage = ParquetStorage(tmp_path / "parquet")
    storage.write_frame("daily", "000001.SZ", _daily_frame())
    decisions_path = tmp_path / "decisions.parquet"
    trades_path = tmp_path / "trades.parquet"
    summary_path = tmp_path / "summary.csv"
    pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "decision_date": "20240103",
                "action": "OPEN_POSITION",
                "score": 88.0,
                "suggested_position_ratio": 0.15,
            }
        ]
    ).to_parquet(decisions_path, index=False)

    result = build_decision_backtest(
        decisions_path=decisions_path,
        parquet_root=tmp_path / "parquet",
        trades_output_path=trades_path,
        summary_output_path=summary_path,
        holding_days=3,
    )

    assert result.decision_count == 1
    assert result.trade_count == 1
    assert result.skipped_count == 0
    assert trades_path.exists()
    assert summary_path.exists()


def _daily_frame(symbol: str = "000001.SZ"):
    pd = pytest.importorskip("pandas")
    rows = []
    for index in range(8):
        close = float(index + 11)
        rows.append(
            {
                "symbol": symbol,
                "date": f"202401{index + 1:02d}",
                "open": close - 1.0,
                "high": close + 0.5,
                "low": close - 1.5,
                "close": close,
                "volume": 1000 + index,
                "amount": 100_000_000 + index,
            }
        )
    return pd.DataFrame(rows)
