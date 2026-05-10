from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.pre_trade import run_pre_trade
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and submit paper orders through the pre-trade risk gate.")
    parser.add_argument("--date", required=True, help="Trade date, for example 20260508.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--parquet-root", help="Override Parquet root from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    parser.add_argument("--report-output", default="outputs/pre_trade_report.md")
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Build order drafts and checks without paper submitting READY orders.",
    )
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    parquet_root = args.parquet_root or data_config["storage"]["parquet_root"]

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=strategy_config,
        trade_date=args.date,
        strategy_version=args.strategy_version,
        report_path=args.report_output,
        submit=not args.no_submit,
    )
    logger.info(
        (
            "Pre-trade finished: date=%s decisions=%s drafts=%s ready=%s blocked=%s "
            "paper_submitted=%s already_submitted=%s report=%s db=%s"
        ),
        result.date,
        result.decision_count,
        result.draft_count,
        result.ready_count,
        result.blocked_count,
        result.paper_submitted_count,
        result.already_submitted_count,
        result.report_path,
        result.db_path,
    )


if __name__ == "__main__":
    main()
