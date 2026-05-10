from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.smoke_test import run_qmt_smoke_test
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run safe pre-live QMT checks without submitting orders.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--parquet-root", help="Override Parquet root from data config.")
    parser.add_argument("--output", default="outputs/qmt_smoke_test.md")
    parser.add_argument("--connect", action="store_true", help="Connect to QMT and query positions/orders/fills.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    result = run_qmt_smoke_test(
        data_config=data_config,
        strategy_config=strategy_config,
        db_path=args.db_path,
        parquet_root=args.parquet_root,
        output_path=args.output,
        connect=args.connect,
    )
    logger.info(
        "QMT smoke test finished: pass=%s warn=%s fail=%s report=%s",
        result.passed_count,
        result.warning_count,
        result.failed_count,
        result.markdown_path,
    )
    if result.failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
