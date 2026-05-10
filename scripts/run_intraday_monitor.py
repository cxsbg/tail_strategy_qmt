from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.intraday_monitor import run_intraday_monitor
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run intraday polling monitor for sell checks, tail confirmation, and execution sync.")
    parser.add_argument("--date", default="today", help="Trade date, or today. Default: today.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--parquet-root", help="Override Parquet root from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    parser.add_argument("--report-output", default="outputs/intraday_monitor_report.md")
    parser.add_argument("--submit", action="store_true", help="Allow live order submission during the execution phase.")
    parser.add_argument("--apply-positions", action="store_true")
    parser.add_argument("--max-iterations", type=int, help="Limit loop iterations, useful for rehearsal.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    parquet_root = args.parquet_root or data_config["storage"]["parquet_root"]
    trade_date = datetime.now().strftime("%Y%m%d") if args.date == "today" else args.date
    trader = _build_trader(strategy_config) if _needs_trader(strategy_config, submit=args.submit) else None
    result = run_intraday_monitor(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=strategy_config,
        trade_date=trade_date,
        strategy_version=args.strategy_version,
        submit=args.submit,
        apply_positions=args.apply_positions,
        trader=trader,
        report_path=args.report_output,
        max_iterations=args.max_iterations,
    )
    logger.info(
        "Intraday monitor finished: events=%s cycles=%s syncs=%s failed=%s report=%s",
        len(result.events),
        result.cycle_count,
        result.sync_count,
        result.failed_count,
        result.report_path,
    )
    if result.failed_count:
        raise SystemExit(1)


def _needs_trader(strategy_config: dict[str, object], *, submit: bool) -> bool:
    trading_config = strategy_config.get("trading", {})
    return isinstance(trading_config, dict) and trading_config.get("mode", "paper") == "live" and submit


def _build_trader(strategy_config: dict[str, object]) -> object:
    trading_config = strategy_config.get("trading", {})
    if not isinstance(trading_config, dict):
        raise SystemExit("trading config is required for live intraday monitor.")
    qmt_config = trading_config.get("qmt", {})
    if not isinstance(qmt_config, dict):
        raise SystemExit("trading.qmt config is required for live intraday monitor.")
    trader_path = qmt_config.get("trader_path")
    account_id = qmt_config.get("account_id")
    if not trader_path or not account_id:
        raise SystemExit("trading.qmt.trader_path and trading.qmt.account_id are required for live intraday monitor.")

    from qmt.xtquant_trader_adapter import XtQuantTraderAdapter

    return XtQuantTraderAdapter(
        trader_path=str(trader_path),
        account_id=str(account_id),
        session_id=int(qmt_config.get("session_id", 1)),
        strategy_name=str(trading_config.get("strategy_name", "tail_strategy_qmt")),
    )


if __name__ == "__main__":
    main()
