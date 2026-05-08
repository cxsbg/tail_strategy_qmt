from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from strategy.candidates import build_candidates
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build rule-based daily candidates from feature parquet.")
    parser.add_argument("--features", default="data/processed/daily_features.parquet")
    parser.add_argument("--output", default="data/processed/candidates.parquet")
    parser.add_argument("--strategy-config", default="config/strategy.yaml")
    parser.add_argument("--date", help="Trade date to select, for example 20260508. Default: latest date.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    strategy_config = load_config_file(Path(args.strategy_config))
    result = build_candidates(
        features_path=args.features,
        output_path=args.output,
        strategy_config=strategy_config,
        trade_date=args.date,
    )
    logger.info(
        "Candidates built: date=%s input=%s candidates=%s output=%s",
        result.date,
        result.input_count,
        result.candidate_count,
        result.output_path,
    )


if __name__ == "__main__":
    main()
