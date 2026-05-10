from __future__ import annotations

from datetime import datetime, timedelta

from reports.trading_runs import build_trading_run_report
from trading.run_log import TradingCycleRunRepository, build_run_record


def test_build_trading_run_report_summarizes_recent_runs(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    repository = TradingCycleRunRepository(db_path)
    started = datetime(2026, 5, 8, 14, 50, 0)
    repository.insert_run(
        build_run_record(
            trade_date="20260508",
            strategy_version="test-rule",
            mode="paper",
            status="SUCCESS",
            started_at=started,
            finished_at=started + timedelta(seconds=2),
            draft_count=1,
            submitted_count=1,
            message=None,
        )
    )
    repository.insert_run(
        build_run_record(
            trade_date="20260509",
            strategy_version="test-rule",
            mode="live",
            status="FAILED",
            started_at=started,
            finished_at=started + timedelta(seconds=1),
            message="qmt_disconnected",
        )
    )

    result = build_trading_run_report(
        db_path=db_path,
        markdown_path=tmp_path / "trading_run_monitor.md",
        limit=20,
    )
    markdown = result.markdown_path.read_text(encoding="utf-8")

    assert result.run_count == 2
    assert result.failed_count == 1
    assert "# Trading Run Monitor" in markdown
    assert "qmt_disconnected" in markdown
