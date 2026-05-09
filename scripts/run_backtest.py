from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from backtest.simple import build_decision_backtest
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a simple decision-based backtest from local parquet cache.")
    parser.add_argument("--decisions", default="data/processed/decisions.parquet")
    parser.add_argument("--trades-output", default="outputs/backtest_trades.parquet")
    parser.add_argument("--summary-output", default="outputs/backtest_summary.csv")
    parser.add_argument("--equity-output", default="outputs/backtest_equity_curve.csv")
    parser.add_argument("--report-output", default="outputs/backtest_report.md")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--holding-days", type=int, help="Override strategy backtest holding_days.")
    parser.add_argument("--start-date", help="Only use decisions on or after this date, for example 20240101.")
    parser.add_argument("--end-date", help="Only use decisions on or before this date, for example 20260508.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    backtest_config = strategy_config.get("backtest", {})
    holding_days = args.holding_days or int(backtest_config.get("holding_days", 5))
    initial_equity = float(backtest_config.get("initial_equity", 1.0))
    cost_config = backtest_config.get("cost", {})
    exit_config = backtest_config.get("exit", {})
    limit_config = backtest_config.get("limit", {})

    result = build_decision_backtest(
        decisions_path=args.decisions,
        parquet_root=data_config["storage"]["parquet_root"],
        trades_output_path=args.trades_output,
        summary_output_path=args.summary_output,
        equity_output_path=args.equity_output,
        report_output_path=args.report_output,
        holding_days=holding_days,
        cost_config=cost_config,
        exit_config=exit_config,
        limit_config=limit_config,
        initial_equity=initial_equity,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    logger.info(
        "Backtest finished: decisions=%s trades=%s skipped=%s trades_output=%s summary=%s equity=%s report=%s",
        result.decision_count,
        result.trade_count,
        result.skipped_count,
        result.trades_path,
        result.summary_path,
        result.equity_path,
        result.report_path,
    )


if __name__ == "__main__":
    main()
