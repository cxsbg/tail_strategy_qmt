from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from data_layer.symbols import limit_symbols, load_symbols, parse_symbols
from features.daily import build_daily_features
from storage.parquet import ParquetStorage
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build daily feature parquet from cached daily bars.")
    symbol_group = parser.add_mutually_exclusive_group(required=True)
    symbol_group.add_argument("--symbols", help="Comma separated symbols, for example 000001.SZ,600000.SH")
    symbol_group.add_argument("--symbols-file", help="Text file with one symbol per line.")
    parser.add_argument("--config", default="config/data_source.yaml")
    parser.add_argument("--output", default="data/processed/daily_features.parquet")
    parser.add_argument("--limit", type=int, help="Only build features for the first N symbols.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.config))
    symbols = parse_symbols(args.symbols) if args.symbols else load_symbols(args.symbols_file)
    symbols = limit_symbols(symbols, args.limit)
    if not symbols:
        raise SystemExit("No symbols to build features for.")

    result = build_daily_features(
        symbols=symbols,
        storage=ParquetStorage(data_config["storage"]["parquet_root"]),
        output_path=args.output,
    )
    logger.info(
        "Daily features built: symbols=%s rows=%s skipped=%s output=%s",
        result.symbol_count,
        result.row_count,
        len(result.skipped_symbols),
        result.output_path,
    )


if __name__ == "__main__":
    main()
