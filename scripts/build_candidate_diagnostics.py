from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from strategy.candidates import build_candidate_diagnostics
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build candidate diagnostics and failure reason summary.")
    parser.add_argument("--features", default="data/processed/daily_features.parquet")
    parser.add_argument("--diagnostics-output", default="data/processed/candidate_diagnostics.parquet")
    parser.add_argument("--summary-output", default="data/processed/candidate_reason_summary.csv")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--date", help="Trade date to diagnose, for example 20260508. Default: latest date.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    strategy_config = load_config_file(Path(args.strategy_config))
    result = build_candidate_diagnostics(
        features_path=args.features,
        diagnostics_path=args.diagnostics_output,
        summary_path=args.summary_output,
        strategy_config=strategy_config,
        trade_date=args.date,
    )
    logger.info(
        "Candidate diagnostics built: date=%s input=%s passed=%s failed=%s diagnostics=%s summary=%s",
        result.date,
        result.input_count,
        result.passed_count,
        result.failed_count,
        result.diagnostics_path,
        result.summary_path,
    )


if __name__ == "__main__":
    main()
