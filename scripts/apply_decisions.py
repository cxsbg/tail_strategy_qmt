from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from strategy.apply_decisions import apply_decisions_to_positions
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply stored strategy decisions to the local position state machine."
    )
    parser.add_argument("--date", required=True, help="Decision date, for example 20260508.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--parquet-root", help="Override Parquet root from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without writing positions, trades, or application records.",
    )
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    parquet_root = args.parquet_root or data_config["storage"]["parquet_root"]

    result = apply_decisions_to_positions(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=strategy_config,
        decision_date=args.date,
        strategy_version=args.strategy_version,
        dry_run=args.dry_run,
    )
    logger.info(
        (
            "Decision apply finished: date=%s decisions=%s applied=%s skipped=%s "
            "failed=%s dry_run=%s already_applied=%s db=%s"
        ),
        result.date,
        result.decision_count,
        result.applied_count,
        result.skipped_count,
        result.failed_count,
        result.dry_run_count,
        result.already_applied_count,
        result.db_path,
    )
    if result.failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
