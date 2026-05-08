from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from data_layer.dates import today_yyyymmdd
from data_layer.symbols import limit_symbols, load_symbols, parse_symbols
from qmt.xtquant_adapter import XtQuantAdapter
from reports.pipeline import DailyPipelinePaths, run_daily_pipeline
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run daily QMT sync, features, candidates, diagnostics, and report.")
    symbol_group = parser.add_mutually_exclusive_group(required=True)
    symbol_group.add_argument("--symbols", help="Comma separated symbols, for example 000001.SZ,600000.SH")
    symbol_group.add_argument("--symbols-file", help="Text file with one symbol per line.")
    parser.add_argument("--end-date", default=today_yyyymmdd(), help="Report and sync end date. Default: today.")
    parser.add_argument(
        "--fallback-start-date",
        required=True,
        help="Start date for symbols without local cache, for example 20240101.",
    )
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--limit", type=int, help="Only process the first N symbols.")
    parser.add_argument("--skip-sync", action="store_true", help="Use local cache without calling QMT.")
    parser.add_argument("--daily-features", default="data/processed/daily_features.parquet")
    parser.add_argument("--candidates", default="data/processed/candidates.parquet")
    parser.add_argument("--diagnostics", default="data/processed/candidate_diagnostics.parquet")
    parser.add_argument("--reason-summary", default="data/processed/candidate_reason_summary.csv")
    parser.add_argument("--markdown-report", default="outputs/daily_report.md")
    parser.add_argument("--csv-report", default="outputs/daily_report.csv")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    symbols = parse_symbols(args.symbols) if args.symbols else load_symbols(args.symbols_file)
    symbols = limit_symbols(symbols, args.limit)
    data_config = load_config_file(Path(args.data_config))
    strategy_config = load_config_file(Path(args.strategy_config))
    paths = DailyPipelinePaths(
        daily_features=Path(args.daily_features),
        candidates=Path(args.candidates),
        diagnostics=Path(args.diagnostics),
        reason_summary=Path(args.reason_summary),
        markdown_report=Path(args.markdown_report),
        csv_report=Path(args.csv_report),
    )
    result = run_daily_pipeline(
        symbols=symbols,
        data_config=data_config,
        strategy_config=strategy_config,
        qmt_client=None if args.skip_sync else XtQuantAdapter(),
        end_date=args.end_date,
        fallback_start_date=args.fallback_start_date,
        paths=paths,
        skip_sync=args.skip_sync,
    )
    success_count = sum(item.status == "success" for item in result.sync_results)
    skipped_count = sum(item.status == "skipped" for item in result.sync_results)
    failed_count = sum(item.status == "failed" for item in result.sync_results)
    logger.info(
        "Daily pipeline finished: sync_success=%s sync_skipped=%s sync_failed=%s features=%s candidates=%s report=%s",
        success_count,
        skipped_count,
        failed_count,
        result.feature_result.row_count,
        result.candidate_result.candidate_count,
        result.report_result.markdown_path,
    )
    if failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
