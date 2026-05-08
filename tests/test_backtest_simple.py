from __future__ import annotations

import pytest

from backtest.simple import build_decision_backtest, render_backtest_markdown, run_decision_backtest
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
        cost_config={
            "slippage_rate": 0.001,
            "commission_rate": 0.0003,
            "stamp_tax_rate": 0.0005,
        },
    )

    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade["symbol"] == "000001.SZ"
    assert trade["entry_date"] == "20240104"
    assert trade["exit_date"] == "20240106"
    assert trade["entry_price"] == pytest.approx(13.0)
    assert trade["exit_price"] == pytest.approx(16.0)
    assert trade["gross_return"] == pytest.approx((16.0 / 13.0) - 1.0)
    expected_net_return = (16.0 * (1 - 0.0018)) / (13.0 * (1 + 0.0013)) - 1.0
    assert trade["net_return"] == pytest.approx(expected_net_return)
    assert trade["weighted_return"] == pytest.approx(((16.0 / 13.0) - 1.0) * 0.15)
    assert trade["weighted_net_return"] == pytest.approx(expected_net_return * 0.15)
    assert trade["cost_rate"] == pytest.approx(0.0031)
    assert summary["decision_count"] == 1
    assert summary["trade_count"] == 1
    assert summary["skipped_count"] == 0
    assert summary["win_rate"] == 1.0
    assert summary["avg_net_return"] == pytest.approx(expected_net_return)


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
    report_path = tmp_path / "report.md"
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
        report_output_path=report_path,
        holding_days=3,
    )

    assert result.decision_count == 1
    assert result.trade_count == 1
    assert result.skipped_count == 0
    assert trades_path.exists()
    assert summary_path.exists()
    assert result.report_path == report_path
    assert "Tail Strategy Backtest Report" in report_path.read_text(encoding="utf-8")


def test_render_backtest_markdown_includes_summary_and_trades() -> None:
    pd = pytest.importorskip("pandas")
    trades = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "decision_date": "20240103",
                "entry_date": "20240104",
                "exit_date": "20240106",
                "entry_price": 13.0,
                "exit_price": 16.0,
                "position_ratio": 0.15,
                "score": 88.0,
                "gross_return": 0.23,
                "net_return": 0.22,
            }
        ]
    )
    summary = {
        "decision_count": 1,
        "trade_count": 1,
        "skipped_count": 0,
        "win_rate": 1.0,
        "avg_return": 0.23,
        "avg_net_return": 0.22,
        "total_weighted_net_return": 0.033,
        "best_net_return": 0.22,
        "worst_net_return": 0.22,
    }

    markdown = render_backtest_markdown(summary=summary, trades=trades)

    assert "- Trades: 1" in markdown
    assert "- Avg net return: 22.00%" in markdown
    assert "| 000001.SZ | 20240103 | 20240104 @ 13.000 |" in markdown


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
