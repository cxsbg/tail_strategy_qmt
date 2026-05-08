from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from data_layer.universe import build_universe, universe_config_from_dict
from qmt.xtquant_adapter import XtQuantAdapter
from utils.config import load_config_file
from utils.logging import configure_logging, get_logger


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build local stock universe from QMT sector data.")
    parser.add_argument("--config", default="config/universe.yaml")
    parser.add_argument("--sector", help="Override QMT sector name from config.")
    parser.add_argument("--output", help="Override output symbol file path.")
    parser.add_argument(
        "--refresh-sector-data",
        action="store_true",
        help="Refresh QMT sector metadata before building the universe.",
    )
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    config = universe_config_from_dict(load_config_file(Path(args.config)))

    if args.sector or args.output:
        config = type(config)(
            sector_name=args.sector or config.sector_name,
            output_path=Path(args.output) if args.output else config.output_path,
            include_suffixes=config.include_suffixes,
            exclude_prefixes=config.exclude_prefixes,
        )

    result = build_universe(
        qmt_client=XtQuantAdapter(),
        config=config,
        refresh_sector_data=args.refresh_sector_data,
    )
    logger.info(
        "Universe built: sector=%s source=%s filtered=%s output=%s",
        result.sector_name,
        result.source_count,
        result.filtered_count,
        result.output_path,
    )


if __name__ == "__main__":
    main()
