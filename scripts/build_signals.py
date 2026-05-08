from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from strategy.signals import build_and_store_signals
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build strategy signals from candidates and tail confirmations.")
    parser.add_argument("--candidates", default="data/processed/candidates.parquet")
    parser.add_argument("--tail-confirmation", default="data/processed/tail_confirmation.parquet")
    parser.add_argument("--output", default="data/processed/signals.parquet")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    parser.add_argument("--date", help="Trade date to build, for example 20260508. Default: latest candidate date.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]

    result = build_and_store_signals(
        candidates_path=args.candidates,
        tail_confirmation_path=args.tail_confirmation,
        output_path=args.output,
        db_path=db_path,
        strategy_config=strategy_config,
        trade_date=args.date,
        strategy_version=args.strategy_version,
    )
    logger.info(
        "Signals built: date=%s input=%s signals=%s output=%s db=%s",
        result.date,
        result.input_count,
        result.signal_count,
        result.output_path,
        result.db_path,
    )


if __name__ == "__main__":
    main()
