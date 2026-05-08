from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from data_layer.symbols import limit_symbols, load_symbols, parse_symbols
from features.intraday import build_tail_confirmations
from storage.parquet import ParquetStorage
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build intraday tail confirmation from cached minute bars.")
    symbol_group = parser.add_mutually_exclusive_group(required=True)
    symbol_group.add_argument("--symbols", help="Comma separated symbols, for example 000001.SZ,600000.SH")
    symbol_group.add_argument("--symbols-file", help="Text file with one symbol per line.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--output", default="data/processed/tail_confirmation.parquet")
    parser.add_argument("--date", help="Trade date to confirm, for example 20260508. Default: all cached dates.")
    parser.add_argument("--limit", type=int, help="Only build confirmations for the first N symbols.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    symbols = parse_symbols(args.symbols) if args.symbols else load_symbols(args.symbols_file)
    symbols = limit_symbols(symbols, args.limit)
    if not symbols:
        raise SystemExit("No symbols to build tail confirmations for.")

    result = build_tail_confirmations(
        symbols=symbols,
        storage=ParquetStorage(data_config["storage"]["parquet_root"]),
        output_path=args.output,
        intraday_config=strategy_config["intraday"],
        trade_date=args.date,
    )
    logger.info(
        "Tail confirmations built: symbols=%s rows=%s skipped=%s output=%s",
        result.symbol_count,
        result.row_count,
        len(result.skipped_symbols),
        result.output_path,
    )


if __name__ == "__main__":
    main()
