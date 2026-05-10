from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.sync import sync_broker_executions
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync QMT broker orders and fills into local SQLite.")
    parser.add_argument("--date", help="Optional trade date filter, for example 20260508.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--db-path", help="Override SQLite database path from data config.")
    parser.add_argument("--strategy-version", default="rule-v0")
    parser.add_argument(
        "--apply-positions",
        action="store_true",
        help="Apply fully filled broker orders to the local position state machine.",
    )
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    db_path = args.db_path or data_config["storage"]["sqlite_path"]
    result = sync_broker_executions(
        db_path=db_path,
        trader=_build_trader(strategy_config),
        trade_date=args.date,
        apply_positions=args.apply_positions,
        strategy_version=args.strategy_version,
    )
    logger.info(
        (
            "Broker sync finished: orders=%s upserts=%s fills=%s inserted_fills=%s "
            "position_applications=%s db=%s"
        ),
        result.order_snapshot_count,
        result.order_upsert_count,
        result.fill_snapshot_count,
        result.fill_inserted_count,
        result.position_application_count,
        result.db_path,
    )


def _build_trader(strategy_config: dict[str, object]) -> object:
    trading_config = strategy_config.get("trading", {})
    if not isinstance(trading_config, dict):
        raise SystemExit("trading config is required for broker sync.")
    qmt_config = trading_config.get("qmt", {})
    if not isinstance(qmt_config, dict):
        raise SystemExit("trading.qmt config is required for broker sync.")
    trader_path = qmt_config.get("trader_path")
    account_id = qmt_config.get("account_id")
    if not trader_path or not account_id:
        raise SystemExit("trading.qmt.trader_path and trading.qmt.account_id are required for broker sync.")

    from qmt.xtquant_trader_adapter import XtQuantTraderAdapter

    return XtQuantTraderAdapter(
        trader_path=str(trader_path),
        account_id=str(account_id),
        session_id=int(qmt_config.get("session_id", 1)),
        strategy_name=str(trading_config.get("strategy_name", "tail_strategy_qmt")),
    )


if __name__ == "__main__":
    main()
