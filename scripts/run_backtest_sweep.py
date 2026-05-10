from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from backtest.sweep import build_backtest_sweep
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run parameter sweep for decision-based backtest.")
    parser.add_argument("--decisions", default="data/processed/decisions.parquet")
    parser.add_argument("--output", default="outputs/backtest_sweep.csv")
    parser.add_argument("--report-output", default="outputs/backtest_sweep_report.md")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--holding-days", default="3,5,8", help="Comma separated holding days.")
    parser.add_argument("--stop-loss", default="0.03,0.05,0.08", help="Comma separated stop loss percentages.")
    parser.add_argument("--take-profit", default="0.08,0.12,0.16", help="Comma separated take profit percentages.")
    parser.add_argument("--max-gross-exposure", default="0.6,0.8,1.0", help="Comma separated gross exposure limits.")
    parser.add_argument("--start-date", help="Only use decisions on or after this date, for example 20240101.")
    parser.add_argument("--end-date", help="Only use decisions on or before this date, for example 20260508.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    result = build_backtest_sweep(
        decisions_path=args.decisions,
        parquet_root=data_config["storage"]["parquet_root"],
        output_path=args.output,
        report_path=args.report_output,
        base_config=strategy_config.get("backtest", {}),
        holding_days_values=_int_values(args.holding_days),
        stop_loss_values=_float_values(args.stop_loss),
        take_profit_values=_float_values(args.take_profit),
        max_gross_exposure_values=_float_values(args.max_gross_exposure),
        start_date=args.start_date,
        end_date=args.end_date,
    )
    logger.info(
        "Backtest sweep finished: runs=%s best_score=%s output=%s report=%s",
        result.run_count,
        result.best_score,
        result.output_path,
        result.report_path,
    )


def _int_values(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def _float_values(text: str) -> list[float]:
    return [float(item.strip()) for item in text.split(",") if item.strip()]


if __name__ == "__main__":
    main()
