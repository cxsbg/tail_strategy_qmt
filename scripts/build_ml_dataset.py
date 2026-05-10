from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from ml.dataset import build_ml_dataset_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a labeled ML research dataset from daily features.")
    parser.add_argument("--features", default="data/processed/daily_features.parquet")
    parser.add_argument("--candidates", help="Optional candidate parquet to restrict rows to rule candidates.")
    parser.add_argument("--output", default="data/processed/ml_dataset.parquet")
    parser.add_argument("--horizon-days", type=int, default=5)
    parser.add_argument("--min-forward-return", type=float, default=0.0)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    result = build_ml_dataset_file(
        features_path=args.features,
        candidates_path=Path(args.candidates) if args.candidates else None,
        output_path=args.output,
        horizon_days=args.horizon_days,
        min_forward_return=args.min_forward_return,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    logger.info(
        "ML dataset built: rows=%s positives=%s features=%s horizon=%s output=%s",
        result.row_count,
        result.positive_count,
        result.feature_count,
        result.horizon_days,
        result.output_path,
    )


if __name__ == "__main__":
    main()
