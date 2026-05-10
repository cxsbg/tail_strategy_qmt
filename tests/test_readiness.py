from __future__ import annotations

from datetime import datetime, timedelta

from trading.readiness import build_readiness_report, render_readiness_markdown
from trading.run_log import TradingCycleRunRepository, build_run_record


def test_build_readiness_report_warns_for_missing_rehearsal_artifacts(tmp_path) -> None:
    result = build_readiness_report(
        data_config=_data_config(tmp_path),
        strategy_config=_strategy_config(mode="paper"),
        output_path=tmp_path / "readiness.md",
    )
    statuses = {check.name: check.status for check in result.checks}

    assert result.failed_count == 0
    assert statuses["config.trading_mode"] == "PASS"
    assert statuses["run.trading_run.exists"] == "WARN"
    assert result.markdown_path.read_text(encoding="utf-8").startswith("# Tail Strategy Readiness")


def test_build_readiness_report_can_require_live_config(tmp_path) -> None:
    result = build_readiness_report(
        data_config=_data_config(tmp_path),
        strategy_config=_strategy_config(mode="paper"),
        output_path=None,
        require_live_config=True,
    )
    statuses = {check.name: check.status for check in result.checks}

    assert statuses["config.qmt.trader_path"] == "FAIL"
    assert statuses["config.qmt.account_id"] == "FAIL"
    assert statuses["config.capital_base"] == "FAIL"


def test_build_readiness_report_passes_recent_successful_run(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    started = datetime.now() - timedelta(seconds=2)
    TradingCycleRunRepository(db_path).insert_run(
        build_run_record(
            trade_date="20260508",
            strategy_version="test-rule",
            mode="paper",
            status="SUCCESS",
            started_at=started,
            finished_at=datetime.now(),
        )
    )

    result = build_readiness_report(
        data_config=_data_config(tmp_path, db_path=db_path),
        strategy_config=_strategy_config(mode="paper"),
        output_path=None,
        require_recent_run=True,
    )
    statuses = {check.name: check.status for check in result.checks}

    assert statuses["run.trading_run.exists"] == "PASS"
    assert statuses["run.trading_run.status"] == "PASS"


def test_render_readiness_markdown_summarizes_counts(tmp_path) -> None:
    result = build_readiness_report(
        data_config=_data_config(tmp_path),
        strategy_config=_strategy_config(mode="paper"),
        output_path=None,
    )

    markdown = render_readiness_markdown(result)

    assert "## Summary" in markdown
    assert "| Status | Check | Detail |" in markdown


def _data_config(tmp_path, *, db_path=None) -> dict[str, object]:
    return {
        "storage": {
            "sqlite_path": str(db_path or tmp_path / "tail_strategy.db"),
            "parquet_root": str(tmp_path / "parquet"),
        }
    }


def _strategy_config(*, mode: str) -> dict[str, object]:
    return {
        "trading": {
            "mode": mode,
            "strategy_name": "tail_strategy_qmt",
            "account_equity": None,
            "order_value_base": None,
            "qmt": {
                "trader_path": "",
                "account_id": "",
                "session_id": 1,
            },
        }
    }
