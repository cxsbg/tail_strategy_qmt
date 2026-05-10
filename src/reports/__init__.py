"""Report generation package."""

from reports.daily import DailyReportResult, build_daily_report, render_daily_markdown
from reports.decisions import DecisionReportResult, build_decision_report, render_decision_markdown
from reports.trading_cycle import (
    TradingCycleReportResult,
    build_trading_cycle_report,
    render_trading_cycle_markdown,
)
from reports.trading_runs import TradingRunReportResult, build_trading_run_report, render_trading_run_markdown

__all__ = [
    "DailyReportResult",
    "DecisionReportResult",
    "TradingCycleReportResult",
    "TradingRunReportResult",
    "build_daily_report",
    "build_decision_report",
    "build_trading_cycle_report",
    "build_trading_run_report",
    "render_daily_markdown",
    "render_decision_markdown",
    "render_trading_cycle_markdown",
    "render_trading_run_markdown",
]
