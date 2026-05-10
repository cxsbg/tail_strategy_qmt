from __future__ import annotations

import pytest

from backtest.sweep import build_backtest_sweep, render_backtest_sweep_markdown, run_backtest_sweep
from storage.parquet import ParquetStorage


def test_run_backtest_sweep_builds_parameter_grid(tmp_path) -> None:
    pd = pytest.importorskip("pandas")
    storage = ParquetStorage(tmp_path / "parquet")
    storage.write_frame("daily", "000001.SZ", _daily_frame(pd))
    decisions = _decisions(pd)

    result = run_backtest_sweep(
        decisions,
        storage=storage,
        base_config=_base_config(),
        holding_days_values=[2, 3],
        stop_loss_values=[0.03],
        take_profit_values=[0.08, 0.12],
        max_gross_exposure_values=[1.0],
    )

    assert len(result) == 4
    assert set(result["holding_days"]) == {2, 3}
    assert set(result["take_profit_pct"]) == {0.08, 0.12}
    assert result.iloc[0]["score"] >= result.iloc[-1]["score"]
    assert result["trade_count"].min() == 1


def test_build_backtest_sweep_writes_csv(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    storage = ParquetStorage(tmp_path / "parquet")
    storage.write_frame("daily", "000001.SZ", _daily_frame(pd))
    decisions_path = tmp_path / "decisions.parquet"
    output_path = tmp_path / "sweep.csv"
    report_path = tmp_path / "sweep.md"
    _decisions(pd).to_parquet(decisions_path, index=False)

    result = build_backtest_sweep(
        decisions_path=decisions_path,
        parquet_root=tmp_path / "parquet",
        output_path=output_path,
        report_path=report_path,
        base_config=_base_config(),
        holding_days_values=[2],
        stop_loss_values=[0.03],
        take_profit_values=[0.08, 0.12],
        max_gross_exposure_values=[1.0],
    )

    assert result.run_count == 2
    assert result.best_score is not None
    assert result.report_path == report_path
    assert output_path.exists()
    assert report_path.exists()
    assert "compounded_return" in output_path.read_text(encoding="utf-8")
    assert "Backtest Parameter Sweep" in report_path.read_text(encoding="utf-8")


def test_render_backtest_sweep_markdown_includes_top_runs(tmp_path) -> None:
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(
        [
            {
                "holding_days": 3,
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.08,
                "max_gross_exposure": 0.8,
                "trade_count": 5,
                "win_rate": 0.6,
                "compounded_return": 0.12,
                "max_drawdown": -0.04,
                "score": 0.13,
            }
        ]
    )

    markdown = render_backtest_sweep_markdown(frame)

    assert "# Backtest Parameter Sweep" in markdown
    assert "| holding_days | 3 |" in markdown
    assert "| 1 | 3 | 3.00% | 8.00% | 80.00% | 5 | 60.00% | 12.00% | -4.00% | 0.130000 |" in markdown


def _decisions(pd):
    return pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "decision_date": "20240103",
                "action": "OPEN_POSITION",
                "score": 88.0,
                "suggested_position_ratio": 0.3,
            }
        ]
    )


def _daily_frame(pd):
    rows = []
    for index in range(8):
        close = 10.0 + index
        rows.append(
            {
                "symbol": "000001.SZ",
                "date": f"202401{index + 1:02d}",
                "open": close - 0.5,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 1000 + index,
                "amount": 100_000_000 + index,
            }
        )
    return pd.DataFrame(rows)


def _base_config() -> dict[str, object]:
    return {
        "initial_equity": 1.0,
        "cost": {
            "slippage_rate": 0.0,
            "commission_rate": 0.0,
            "stamp_tax_rate": 0.0,
        },
        "limit": {
            "enabled": False,
        },
        "portfolio": {
            "enabled": True,
            "max_concurrent_positions": 5,
        },
    }
