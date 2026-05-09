"""Backtest package."""

from backtest.simple import (
    BacktestResult,
    build_decision_backtest,
    build_equity_curve,
    render_backtest_markdown,
    run_decision_backtest,
)

__all__ = [
    "BacktestResult",
    "build_decision_backtest",
    "build_equity_curve",
    "render_backtest_markdown",
    "run_decision_backtest",
]
