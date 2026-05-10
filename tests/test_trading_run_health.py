from __future__ import annotations

from datetime import datetime, timedelta

from trading.health import check_trading_run_health, render_trading_run_health_markdown
from trading.run_log import TradingCycleRunRepository, build_run_record


def test_check_trading_run_health_fails_when_no_run_exists(tmp_path) -> None:
    result = check_trading_run_health(
        db_path=tmp_path / "tail_strategy.db",
        trade_date="20260508",
        output_path=tmp_path / "health.md",
    )

    assert result.failed_count == 1
    assert result.latest_run is None
    assert "No trading cycle run" in result.markdown_path.read_text(encoding="utf-8")


def test_check_trading_run_health_passes_success_run(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    _insert_run(db_path, status="SUCCESS", trade_date="20260508")

    result = check_trading_run_health(
        db_path=db_path,
        trade_date="20260508",
        max_age_hours=24 * 365 * 10,
        output_path=None,
    )

    assert result.failed_count == 0
    assert result.warning_count == 0
    assert result.latest_run.status == "SUCCESS"


def test_check_trading_run_health_fails_failed_run(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    _insert_run(db_path, status="FAILED", message="qmt_disconnected")

    result = check_trading_run_health(db_path=db_path, output_path=None)
    status_check = {check.name: check for check in result.checks}["trading_run.status"]

    assert result.failed_count == 1
    assert status_check.status == "FAIL"
    assert "qmt_disconnected" in status_check.detail


def test_check_trading_run_health_can_allow_skipped(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    _insert_run(db_path, status="SKIPPED", message="weekend")

    result = check_trading_run_health(db_path=db_path, allow_skipped=True, output_path=None)

    assert result.failed_count == 0
    assert result.warning_count == 0


def test_check_trading_run_health_fails_stale_run(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    _insert_run(db_path, status="SUCCESS", finished_at=datetime(2020, 1, 1, 15, 0, 0))

    result = check_trading_run_health(db_path=db_path, max_age_hours=1, output_path=None)
    age_check = {check.name: check for check in result.checks}["trading_run.age"]

    assert age_check.status == "FAIL"


def test_render_trading_run_health_markdown_handles_empty_result(tmp_path) -> None:
    result = check_trading_run_health(db_path=tmp_path / "tail_strategy.db", output_path=None)

    markdown = render_trading_run_health_markdown(result)

    assert "# Trading Run Health" in markdown
    assert "| FAIL | trading_run.exists |" in markdown


def _insert_run(
    db_path,
    *,
    status: str,
    trade_date: str = "20260508",
    finished_at: datetime | None = None,
    message: str | None = None,
) -> None:
    started_at = finished_at or datetime.now() - timedelta(seconds=2)
    done_at = finished_at or datetime.now()
    TradingCycleRunRepository(db_path).insert_run(
        build_run_record(
            trade_date=trade_date,
            strategy_version="test-rule",
            mode="paper",
            status=status,
            started_at=started_at,
            finished_at=done_at,
            message=message,
        )
    )
