from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from strategy.decisions import build_and_store_decisions
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build daily risk decisions from signals and open positions.")
    parser.add_argument("--date", required=True, help="Decision date, for example 20260508.")
    parser.add_argument("--output", default="data/processed/decisions.parquet")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]

    result = build_and_store_decisions(
        db_path=db_path,
        strategy_config=strategy_config,
        decision_date=args.date,
        output_path=args.output,
        strategy_version=args.strategy_version,
    )
    logger.info(
        "Decisions built: date=%s signals=%s open_positions=%s decisions=%s output=%s db=%s",
        result.date,
        result.signal_count,
        result.open_position_count,
        result.decision_count,
        result.output_path,
        result.db_path,
    )


if __name__ == "__main__":
    main()
