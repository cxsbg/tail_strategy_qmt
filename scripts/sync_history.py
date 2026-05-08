from __future__ import annotations

import argparse
from pathlib import Path

from data_layer.periods import resolve_period
from data_layer.symbols import load_symbols, parse_symbols
from data_layer.sync import MarketDataSynchronizer
from qmt.xtquant_adapter import XtQuantAdapter
from storage.parquet import ParquetStorage
from storage.sqlite import SQLiteStore
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync QMT history into local Parquet cache.")
    symbol_group = parser.add_mutually_exclusive_group(required=True)
    symbol_group.add_argument("--symbols", help="Comma separated symbols, for example 000001.SZ,600000.SH")
    symbol_group.add_argument("--symbols-file", help="Text file with one symbol per line.")
    parser.add_argument("--period", choices=["daily", "minute"], default="daily")
    parser.add_argument("--start-date", required=True, help="Start date, for example 20240101.")
    parser.add_argument("--end-date", required=True, help="End date, for example 20240501.")
    parser.add_argument("--config", default="config/data_source.yaml")
    parser.add_argument("--replace", action="store_true", help="Replace cache instead of appending.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.config))
    period = resolve_period(args.period)

    symbols = parse_symbols(args.symbols) if args.symbols else load_symbols(args.symbols_file)
    if not symbols:
        raise SystemExit("No symbols to sync.")

    storage_config = data_config["storage"]
    qmt_config = data_config["data_source"]["qmt"]
    sqlite_store = SQLiteStore(storage_config["sqlite_path"])
    sqlite_store.initialize()

    synchronizer = MarketDataSynchronizer(
        qmt_client=XtQuantAdapter(),
        parquet_storage=ParquetStorage(storage_config["parquet_root"]),
        sqlite_store=sqlite_store,
    )
    results = synchronizer.sync_history(
        symbols=symbols,
        period=period.qmt_period,
        storage_period=period.storage_period,
        start_date=args.start_date,
        end_date=args.end_date,
        adjust_type=qmt_config.get("adjust_type", "front"),
        append=not args.replace,
    )

    success_count = sum(result.status == "success" for result in results)
    failed_count = len(results) - success_count
    logger.info("History sync finished: success=%s failed=%s", success_count, failed_count)
    if failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
