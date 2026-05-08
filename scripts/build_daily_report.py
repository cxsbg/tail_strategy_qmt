from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from reports.daily import build_daily_report
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Markdown and CSV daily strategy report.")
    parser.add_argument("--candidates", default="data/processed/candidates.parquet")
    parser.add_argument("--diagnostics", default="data/processed/candidate_diagnostics.parquet")
    parser.add_argument("--reason-summary", default="data/processed/candidate_reason_summary.csv")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--markdown-output", default="outputs/daily_report.md")
    parser.add_argument("--csv-output", default="outputs/daily_report.csv")
    parser.add_argument("--date", help="Report date override, for example 20260508.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    data_config = load_config_file(Path(args.data_config))
    result = build_daily_report(
        candidates_path=args.candidates,
        diagnostics_path=args.diagnostics,
        reason_summary_path=args.reason_summary,
        sqlite_path=data_config["storage"]["sqlite_path"],
        markdown_path=args.markdown_output,
        csv_path=args.csv_output,
        report_date=args.date,
    )
    logger.info(
        "Daily report built: date=%s candidates=%s diagnostics=%s markdown=%s csv=%s",
        result.report_date,
        result.candidate_count,
        result.diagnostics_count,
        result.markdown_path,
        result.csv_path,
    )


if __name__ == "__main__":
    main()
