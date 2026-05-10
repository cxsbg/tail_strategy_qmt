from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.pre_trade import run_pre_trade
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and submit orders through the pre-trade risk gate.")
    parser.add_argument("--date", required=True, help="Trade date, for example 20260508.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--parquet-root", help="Override Parquet root from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    parser.add_argument("--report-output", default="outputs/pre_trade_report.md")
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Build order drafts and checks without submitting READY orders.",
    )
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    parquet_root = args.parquet_root or data_config["storage"]["parquet_root"]
    trader = _build_trader(strategy_config) if not args.no_submit else None

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=strategy_config,
        trade_date=args.date,
        strategy_version=args.strategy_version,
        report_path=args.report_output,
        submit=not args.no_submit,
        trader=trader,
    )
    logger.info(
        (
            "Pre-trade finished: date=%s decisions=%s drafts=%s ready=%s blocked=%s "
            "paper_submitted=%s submitted=%s rejected=%s already_submitted=%s report=%s db=%s"
        ),
        result.date,
        result.decision_count,
        result.draft_count,
        result.ready_count,
        result.blocked_count,
        result.paper_submitted_count,
        result.submitted_count,
        result.rejected_count,
        result.already_submitted_count,
        result.report_path,
        result.db_path,
    )


def _build_trader(strategy_config: dict[str, object]) -> object | None:
    trading_config = strategy_config.get("trading", {})
    if not isinstance(trading_config, dict) or trading_config.get("mode", "paper") != "live":
        return None

    qmt_config = trading_config.get("qmt", {})
    if not isinstance(qmt_config, dict):
        raise SystemExit("trading.qmt config is required when trading.mode is live.")
    trader_path = qmt_config.get("trader_path")
    account_id = qmt_config.get("account_id")
    if not trader_path or not account_id:
        raise SystemExit("trading.qmt.trader_path and trading.qmt.account_id are required for live trading.")

    from qmt.xtquant_trader_adapter import XtQuantTraderAdapter

    return XtQuantTraderAdapter(
        trader_path=str(trader_path),
        account_id=str(account_id),
        session_id=int(qmt_config.get("session_id", 1)),
        strategy_name=str(trading_config.get("strategy_name", "tail_strategy_qmt")),
    )


if __name__ == "__main__":
    main()
