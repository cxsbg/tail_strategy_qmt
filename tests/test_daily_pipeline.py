from __future__ import annotations

import pytest

from reports.pipeline import DailyPipelinePaths, run_daily_pipeline
from storage.parquet import ParquetStorage


def test_run_daily_pipeline_skip_sync_builds_outputs(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    parquet_root = tmp_path / "parquet"
    sqlite_path = tmp_path / "tail_strategy.db"
    paths = DailyPipelinePaths(
        daily_features=tmp_path / "daily_features.parquet",
        candidates=tmp_path / "candidates.parquet",
        diagnostics=tmp_path / "diagnostics.parquet",
        reason_summary=tmp_path / "reason_summary.csv",
        tail_confirmation=tmp_path / "tail_confirmation.parquet",
        signals=tmp_path / "signals.parquet",
        decisions=tmp_path / "decisions.parquet",
        markdown_report=tmp_path / "daily_report.md",
        csv_report=tmp_path / "daily_report.csv",
        decision_markdown_report=tmp_path / "decision_report.md",
        decision_csv_report=tmp_path / "decision_report.csv",
    )
    storage = ParquetStorage(parquet_root)
    storage.write_frame("daily", "000001.SZ", _daily_frame())

    result = run_daily_pipeline(
        symbols=["000001.SZ"],
        data_config={
            "storage": {
                "parquet_root": str(parquet_root),
                "sqlite_path": str(sqlite_path),
            },
            "data_source": {"qmt": {"adjust_type": "front"}},
        },
        strategy_config=_strategy_config(),
        qmt_client=None,
        end_date="20240125",
        fallback_start_date="20240101",
        paths=paths,
        skip_sync=True,
    )

    assert result.sync_results == ()
    assert result.feature_result.row_count == 25
    assert result.signal_result.signal_count == 1
    assert result.decision_result.decision_count == 1
    assert result.report_result.markdown_path.exists()
    assert result.report_result.csv_path.exists()
    assert result.decision_report_result.markdown_path.exists()
    assert result.decision_report_result.csv_path.exists()
    assert pd.read_parquet(paths.diagnostics).shape[0] == 1
    assert pd.read_parquet(paths.signals).shape[0] == 1
    assert pd.read_parquet(paths.decisions).shape[0] == 1


def test_run_daily_pipeline_requires_qmt_client_when_sync_enabled(tmp_path) -> None:
    with pytest.raises(ValueError, match="qmt_client is required"):
        run_daily_pipeline(
            symbols=["000001.SZ"],
            data_config={
                "storage": {
                    "parquet_root": str(tmp_path / "parquet"),
                    "sqlite_path": str(tmp_path / "tail_strategy.db"),
                },
                "data_source": {"qmt": {"adjust_type": "front"}},
            },
            strategy_config=_strategy_config(),
            qmt_client=None,
            end_date="20240125",
            fallback_start_date="20240101",
            skip_sync=False,
        )


def _daily_frame(symbol: str = "000001.SZ", days: int = 25):
    pd = pytest.importorskip("pandas")
    rows = []
    for index in range(days):
        close = float(index + 10)
        rows.append(
            {
                "symbol": symbol,
                "date": f"202401{index + 1:02d}",
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100 + index,
                "amount": 200_000_000,
                "pre_close": close - 1 if index else close,
                "suspendflag": 0,
            }
        )
    return pd.DataFrame(rows)


def _strategy_config() -> dict[str, object]:
    return {
        "universe": {
            "min_listing_days": 20,
            "min_price": 3,
            "min_avg_amount_20d": 100_000_000,
        },
        "trend": {
            "require_price_above_ma20": True,
            "require_ma_order": True,
            "max_distance_to_ma20": 1,
            "max_return_5d": 1,
            "max_return_20d": 5,
        },
        "strength": {
            "min_return_today": -1,
            "max_return_today": 1,
            "min_close_position": 0,
            "max_upper_shadow_ratio": 1,
        },
        "volume": {
            "min_volume_ratio_5d": 0,
            "max_volume_ratio_5d": 999,
        },
        "position": {
            "initial_position_ratio": 0.3,
            "max_single_stock_ratio": 0.15,
            "max_total_positions": 5,
            "max_new_positions_per_day": 2,
        },
    }
