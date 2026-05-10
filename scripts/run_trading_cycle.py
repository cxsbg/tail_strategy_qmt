from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.cycle import run_trading_cycle
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run pre-trade submission and broker execution sync.")
    parser.add_argument("--date", required=True, help="Trade date, for example 20260508.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--parquet-root", help="Override Parquet root from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    parser.add_argument("--report-output", default="outputs/pre_trade_report.md")
    parser.add_argument("--cycle-report-output", default="outputs/trading_cycle_report.md")
    parser.add_argument("--no-submit", action="store_true", help="Build checks without submitting orders.")
    parser.add_argument("--no-sync", action="store_true", help="Skip broker order/fill sync after submission.")
    parser.add_argument(
        "--apply-positions",
        action="store_true",
        help="Apply fully filled broker orders to the local position state machine during sync.",
    )
    parser.add_argument("--sync-attempts", type=int, default=1, help="Number of broker sync attempts.")
    parser.add_argument(
        "--sync-interval-seconds",
        type=float,
        default=0.0,
        help="Sleep seconds between broker sync attempts.",
    )
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    parquet_root = args.parquet_root or data_config["storage"]["parquet_root"]
    trader = _build_trader(strategy_config) if _needs_trader(strategy_config, args) else None

    result = run_trading_cycle(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=strategy_config,
        trade_date=args.date,
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
    logger.info(
        (
            "Trading cycle finished: date=%s drafts=%s blocked=%s paper_submitted=%s submitted=%s "
            "rejected=%s syncs=%s inserted_fills=%s position_applications=%s pre_trade_report=%s "
            "cycle_report=%s db=%s"
        ),
        result.date,
        result.pre_trade.draft_count,
        result.pre_trade.blocked_count,
        result.pre_trade.paper_submitted_count,
        result.pre_trade.submitted_count,
        result.pre_trade.rejected_count,
        result.sync_count,
        result.total_fill_inserted_count,
        result.total_position_application_count,
        result.pre_trade.report_path,
        result.report_path,
        result.db_path,
    )


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
