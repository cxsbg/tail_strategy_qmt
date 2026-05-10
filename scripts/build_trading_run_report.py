from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from reports.trading_runs import build_trading_run_report
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Markdown monitor report for recent trading cycle runs.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--output", default="outputs/trading_run_monitor.md")
    parser.add_argument("--limit", type=int, default=20)
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    result = build_trading_run_report(db_path=db_path, markdown_path=args.output, limit=args.limit)
    logger.info(
        "Trading run monitor written: runs=%s failed=%s warnings=%s report=%s",
        result.run_count,
        result.failed_count,
        result.warning_count,
        result.markdown_path,
    )


if __name__ == "__main__":
    main()
