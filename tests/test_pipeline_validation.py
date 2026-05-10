from __future__ import annotations

import sqlite3

import pytest

from storage.parquet import ParquetStorage
from storage.sqlite import SQLiteStore
from validation.pipeline import render_validation_markdown, validate_pipeline_outputs


def test_validate_pipeline_outputs_passes_complete_artifacts(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    sqlite_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    processed = tmp_path / "processed"
    outputs = tmp_path / "outputs"
    _create_sqlite(sqlite_path)
    _write_pipeline_parquet(pd, processed)
    _write_reports(outputs)
    ParquetStorage(parquet_root).write_frame("daily", "000001.SZ", _daily_frame(pd))

    result = validate_pipeline_outputs(
        data_config={
            "storage": {
                "sqlite_path": str(sqlite_path),
                "parquet_root": str(parquet_root),
            }
        },
        trade_date="20260508",
        output_path=outputs / "validation.md",
        symbols=["000001.SZ"],
        paths=_paths(processed, outputs),
    )

    assert result.failed_count == 0
    assert result.warning_count == 0
    assert result.passed_count > 0
    assert result.markdown_path is not None
    assert "Pipeline Validation" in result.markdown_path.read_text(encoding="utf-8")


def test_validate_pipeline_outputs_reports_missing_core_files(tmp_path) -> None:
    result = validate_pipeline_outputs(
        data_config={
            "storage": {
                "sqlite_path": str(tmp_path / "missing.db"),
                "parquet_root": str(tmp_path / "parquet"),
            }
        },
        trade_date="20260508",
        paths=_paths(tmp_path / "processed", tmp_path / "outputs"),
    )

    statuses = {check.name: check.status for check in result.checks}
    assert statuses["sqlite.database"] == "FAIL"
    assert statuses["daily_features"] == "FAIL"
    assert statuses["tail_confirmation"] == "WARN"
    assert result.failed_count >= 1


def test_render_validation_markdown_summarizes_status_counts() -> None:
    markdown = render_validation_markdown(
        trade_date="20260508",
        checks=[
            _check("a", "PASS", "ok"),
            _check("b", "WARN", "careful"),
            _check("c", "FAIL", "broken"),
        ],
    )

    assert "- PASS: 1" in markdown
    assert "- WARN: 1" in markdown
    assert "- FAIL: 1" in markdown
    assert "| FAIL | c | broken |" in markdown


def _create_sqlite(path) -> None:
    store = SQLiteStore(path)
    store.initialize()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO signals (
                symbol, signal_date, signal_time, score, suggested_action,
                suggested_position_ratio, reasons, risks, strategy_version, created_at
            )
            VALUES ('000001.SZ', '20260508', '14:45', 88, 'OPEN', 0.15, 'tail_confirmed', NULL, 'rule-v0', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO decisions (
                symbol, decision_date, source_signal_id, position_id, action, score,
                suggested_position_ratio, reasons, risks, strategy_version, created_at
            )
            VALUES ('000001.SZ', '20260508', 1, NULL, 'OPEN_POSITION', 88, 0.15, 'tail_confirmed', NULL, 'rule-v0', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO data_sync_status (
                symbol, period, start_date, end_date, last_sync_time, source, status, error_message
            )
            VALUES ('000001.SZ', '1d', '20240101', '20260508', 'now', 'qmt', 'success', NULL)
            """
        )


def _write_pipeline_parquet(pd, processed) -> None:
    processed.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"symbol": "000001.SZ", "date": "20260508"}]).to_parquet(
        processed / "daily_features.parquet",
        index=False,
    )
    pd.DataFrame([{"symbol": "000001.SZ", "date": "20260508"}]).to_parquet(
        processed / "candidates.parquet",
        index=False,
    )
    pd.DataFrame([{"symbol": "000001.SZ", "date": "20260508"}]).to_parquet(
        processed / "diagnostics.parquet",
        index=False,
    )
    pd.DataFrame([{"symbol": "000001.SZ", "date": "20260508"}]).to_parquet(
        processed / "tail.parquet",
        index=False,
    )
    pd.DataFrame([{"symbol": "000001.SZ", "signal_date": "20260508"}]).to_parquet(
        processed / "signals.parquet",
        index=False,
    )
    pd.DataFrame([{"symbol": "000001.SZ", "decision_date": "20260508"}]).to_parquet(
        processed / "decisions.parquet",
        index=False,
    )


def _write_reports(outputs) -> None:
    outputs.mkdir(parents=True, exist_ok=True)
    for name in [
        "daily_report.md",
        "decision_report.md",
        "pre_trade_report.md",
        "trading_cycle_report.md",
        "backtest_summary.csv",
        "backtest_report.md",
        "backtest_equity_curve.csv",
        "backtest_sweep.csv",
        "backtest_sweep_report.md",
    ]:
        (outputs / name).write_text("ok", encoding="utf-8")


def _daily_frame(pd):
    return pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "20260508",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 1000,
                "amount": 100_000_000,
            }
        ]
    )


def _paths(processed, outputs):
    return {
        "daily_features": processed / "daily_features.parquet",
        "candidates": processed / "candidates.parquet",
        "diagnostics": processed / "diagnostics.parquet",
        "tail_confirmation": processed / "tail.parquet",
        "signals": processed / "signals.parquet",
        "decisions": processed / "decisions.parquet",
        "daily_report": outputs / "daily_report.md",
        "decision_report": outputs / "decision_report.md",
        "pre_trade_report": outputs / "pre_trade_report.md",
        "trading_cycle_report": outputs / "trading_cycle_report.md",
        "backtest_summary": outputs / "backtest_summary.csv",
        "backtest_report": outputs / "backtest_report.md",
        "backtest_equity_curve": outputs / "backtest_equity_curve.csv",
        "backtest_sweep": outputs / "backtest_sweep.csv",
        "backtest_sweep_report": outputs / "backtest_sweep_report.md",
    }


def _check(name: str, status: str, detail: str):
    from validation.pipeline import ValidationCheck

    return ValidationCheck(name=name, status=status, detail=detail)
