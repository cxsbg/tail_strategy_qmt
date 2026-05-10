from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from reports.trading_runs import build_trading_run_report
from trading.cycle import run_trading_cycle
from trading.run_log import TradingCycleRunRepository, build_run_record
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scheduled trading-cycle entrypoint for Windows Task Scheduler.")
    parser.add_argument("--date", default="today", help="Trade date, or today. Default: today.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--parquet-root", help="Override Parquet root from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    parser.add_argument("--report-output", default="outputs/pre_trade_report.md")
    parser.add_argument("--cycle-report-output", default="outputs/trading_cycle_report.md")
    parser.add_argument("--monitor-output", default="outputs/trading_run_monitor.md")
    parser.add_argument("--no-submit", action="store_true", help="Build checks without submitting orders.")
    parser.add_argument("--no-sync", action="store_true", help="Skip broker order/fill sync after submission.")
    parser.add_argument("--apply-positions", action="store_true")
    parser.add_argument("--sync-attempts", type=int, default=1)
    parser.add_argument("--sync-interval-seconds", type=float, default=0.0)
    parser.add_argument("--skip-weekend", action="store_true", help="Record SKIPPED and exit on Saturday/Sunday.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    parquet_root = args.parquet_root or data_config["storage"]["parquet_root"]
    trade_date = _resolve_date(args.date)

    if args.skip_weekend and datetime.now().weekday() >= 5:
        _record_skipped(db_path=db_path, trade_date=trade_date, strategy_version=args.strategy_version)
        _build_monitor(db_path=db_path, output=args.monitor_output)
        logger.info("Trading cycle skipped on weekend: date=%s", trade_date)
        return

    trader = _build_trader(strategy_config) if _needs_trader(strategy_config, args) else None
    result = run_trading_cycle(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=strategy_config,
        trade_date=trade_date,
        strategy_version=args.strategy_version,
        report_path=args.report_output,
        cycle_report_path=args.cycle_report_output,
        submit=not args.no_submit,
        sync_broker=not args.no_sync,
        apply_positions=args.apply_positions,
        sync_attempts=args.sync_attempts,
        sync_interval_seconds=args.sync_interval_seconds,
        trader=trader,
    )
    monitor = _build_monitor(db_path=db_path, output=args.monitor_output)
    logger.info(
        "Scheduled trading cycle finished: run_id=%s date=%s monitor=%s",
        result.run_id,
        result.date,
        monitor.markdown_path,
    )


def _resolve_date(value: str) -> str:
    if value == "today":
        return datetime.now().strftime("%Y%m%d")
    return value


def _record_skipped(*, db_path: str | Path, trade_date: str, strategy_version: str) -> None:
    now = datetime.now()
    TradingCycleRunRepository(db_path).insert_run(
        build_run_record(
            trade_date=trade_date,
            strategy_version=strategy_version,
            mode=None,
            status="SKIPPED",
            started_at=now,
            finished_at=now,
            message="weekend",
        )
    )


def _build_monitor(*, db_path: str | Path, output: str | Path):
    return build_trading_run_report(db_path=db_path, markdown_path=output)


def _needs_trader(strategy_config: dict[str, object], args: argparse.Namespace) -> bool:
    trading_config = strategy_config.get("trading", {})
    return (
        isinstance(trading_config, dict)
        and trading_config.get("mode", "paper") == "live"
        and (not args.no_submit or not args.no_sync)
    )


def _build_trader(strategy_config: dict[str, object]) -> object:
    trading_config = strategy_config.get("trading", {})
    if not isinstance(trading_config, dict):
        raise SystemExit("trading config is required for live trading cycle.")
    qmt_config = trading_config.get("qmt", {})
    if not isinstance(qmt_config, dict):
        raise SystemExit("trading.qmt config is required for live trading cycle.")
    trader_path = qmt_config.get("trader_path")
    account_id = qmt_config.get("account_id")
    if not trader_path or not account_id:
        raise SystemExit("trading.qmt.trader_path and trading.qmt.account_id are required for live trading cycle.")

    from qmt.xtquant_trader_adapter import XtQuantTraderAdapter

    return XtQuantTraderAdapter(
        trader_path=str(trader_path),
        account_id=str(account_id),
        session_id=int(qmt_config.get("session_id", 1)),
        strategy_name=str(trading_config.get("strategy_name", "tail_strategy_qmt")),
    )


if __name__ == "__main__":
    main()
