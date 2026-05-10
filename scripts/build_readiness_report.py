from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.readiness import build_readiness_report
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a pre-live readiness report.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--parquet-root", help="Override Parquet root from data config.")
    parser.add_argument("--output", default="outputs/readiness_report.md")
    parser.add_argument("--require-live-config", action="store_true")
    parser.add_argument("--require-recent-run", action="store_true")
    parser.add_argument("--fail-on-warn", action="store_true")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    result = build_readiness_report(
        data_config=data_config,
        strategy_config=strategy_config,
        db_path=args.db_path,
        parquet_root=args.parquet_root,
        output_path=args.output,
        require_live_config=args.require_live_config,
        require_recent_run=args.require_recent_run,
    )
    logger.info(
        "Readiness report finished: pass=%s warn=%s fail=%s report=%s",
        result.passed_count,
        result.warning_count,
        result.failed_count,
        result.markdown_path,
    )
    if result.failed_count or (args.fail_on_warn and result.warning_count):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
