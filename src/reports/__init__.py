"""Report generation package."""

from reports.daily import DailyReportResult, build_daily_report, render_daily_markdown
from reports.decisions import DecisionReportResult, build_decision_report, render_decision_markdown
from reports.trading_cycle import (
    TradingCycleReportResult,
    build_trading_cycle_report,
    render_trading_cycle_markdown,
)

__all__ = [
    "DailyReportResult",
    "DecisionReportResult",
    "TradingCycleReportResult",
    "build_daily_report",
    "build_decision_report",
    "build_trading_cycle_report",
    "render_daily_markdown",
    "render_decision_markdown",
    "render_trading_cycle_markdown",
]
