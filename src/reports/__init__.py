"""Report generation package."""

from reports.daily import DailyReportResult, build_daily_report, render_daily_markdown
from reports.decisions import DecisionReportResult, build_decision_report, render_decision_markdown

__all__ = [
    "DailyReportResult",
    "DecisionReportResult",
    "build_daily_report",
    "build_decision_report",
    "render_daily_markdown",
    "render_decision_markdown",
]
