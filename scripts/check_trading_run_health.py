from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.health import check_trading_run_health
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check recent trading-cycle run health and return a scheduler-friendly exit code.")
    parser.add_argument("--date", help="Trade date to require, for example 20260508. Omit to check latest run.")
    parser.add_argument("--today", action="store_true", help="Require a run for today's date.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--output", default="outputs/trading_run_health.md")
    parser.add_argument("--max-age-hours", type=float, help="Fail if the latest matching run is older than this.")
    parser.add_argument("--allow-skipped", action="store_true", help="Treat SKIPPED as PASS.")
    parser.add_argument("--fail-on-warn", action="store_true", help="Return non-zero when WARN checks exist.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    trade_date = datetime.now().strftime("%Y%m%d") if args.today else args.date
    result = check_trading_run_health(
        db_path=db_path,
        trade_date=trade_date,
        max_age_hours=args.max_age_hours,
        allow_skipped=args.allow_skipped,
        output_path=args.output,
    )
    logger.info(
        "Trading run health finished: pass=%s warn=%s fail=%s report=%s",
        result.passed_count,
        result.warning_count,
        result.failed_count,
        result.markdown_path,
    )
    if result.failed_count or (args.fail_on_warn and result.warning_count):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
