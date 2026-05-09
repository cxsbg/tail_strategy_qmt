from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from data_layer.dates import today_yyyymmdd
from data_layer.symbols import limit_symbols, load_symbols, parse_symbols
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger
from validation.pipeline import validate_pipeline_outputs


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate local pipeline artifacts and SQLite rows.")
    parser.add_argument("--date", default=today_yyyymmdd(), help="Trade date to validate, for example 20260508.")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--output", default="outputs/pipeline_validation.md")
    symbol_group = parser.add_mutually_exclusive_group()
    symbol_group.add_argument("--symbols", help="Comma separated symbols to check daily cache.")
    symbol_group.add_argument("--symbols-file", help="Text file with one symbol per line.")
    parser.add_argument("--limit", type=int, help="Only check the first N symbols.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    symbols = None
    if args.symbols:
        symbols = parse_symbols(args.symbols)
    elif args.symbols_file:
        symbols = load_symbols(args.symbols_file)
    if symbols is not None:
        symbols = limit_symbols(symbols, args.limit)

    result = validate_pipeline_outputs(
        data_config=data_config,
        trade_date=args.date,
        output_path=args.output,
        symbols=symbols,
    )
    logger.info(
        "Pipeline validation finished: pass=%s warn=%s fail=%s output=%s",
        result.passed_count,
        result.warning_count,
        result.failed_count,
        result.markdown_path,
    )
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
