"""Backtest package."""

from backtest.simple import (
    BacktestResult,
    build_decision_backtest,
    build_equity_curve,
    build_mark_to_market_equity_curve,
    render_backtest_markdown,
    run_decision_backtest,
)
from backtest.sweep import (
    BacktestSweepResult,
    build_backtest_sweep,
    render_backtest_sweep_markdown,
    run_backtest_sweep,
)

__all__ = [
    "BacktestResult",
    "BacktestSweepResult",
    "build_decision_backtest",
    "build_equity_curve",
    "build_backtest_sweep",
    "build_mark_to_market_equity_curve",
    "render_backtest_sweep_markdown",
    "render_backtest_markdown",
    "run_backtest_sweep",
    "run_decision_backtest",
]
