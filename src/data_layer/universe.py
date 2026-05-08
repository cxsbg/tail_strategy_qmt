from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from qmt.client import QmtClient


@dataclass(frozen=True)
class UniverseConfig:
    sector_name: str
    output_path: Path
    include_suffixes: tuple[str, ...]
    exclude_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class UniverseBuildResult:
    sector_name: str
    source_count: int
    filtered_count: int
    output_path: Path


def universe_config_from_dict(config: dict[str, object]) -> UniverseConfig:
    source = config.get("source", {})
    markets = config.get("markets", {})
    if not isinstance(source, dict) or not isinstance(markets, dict):
        raise ValueError("universe.yaml must contain source and markets mappings.")

    return UniverseConfig(
        sector_name=str(source.get("sector_name", "沪深A股")),
        output_path=Path(str(source.get("output_path", "data/processed/universe_symbols.txt"))),
        include_suffixes=tuple(str(item) for item in markets.get("include_suffixes", ["SH", "SZ"])),
        exclude_prefixes=tuple(str(item) for item in markets.get("exclude_prefixes", [])),
    )


def filter_symbols(
    symbols: Iterable[str],
    *,
    include_suffixes: Iterable[str],
    exclude_prefixes: Iterable[str],
) -> list[str]:
    suffixes = tuple(suffix.upper().lstrip(".") for suffix in include_suffixes)
    prefixes = tuple(exclude_prefixes)
    filtered: set[str] = set()

    for raw_symbol in symbols:
        symbol = normalize_symbol(raw_symbol)
        code, suffix = split_symbol(symbol)
        if suffixes and suffix not in suffixes:
            continue
        if prefixes and code.startswith(prefixes):
            continue
        filtered.add(symbol)

    return sorted(filtered)


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def split_symbol(symbol: str) -> tuple[str, str]:
    if "." not in symbol:
        return symbol, ""
    code, suffix = symbol.rsplit(".", 1)
    return code, suffix


def write_symbols(symbols: Iterable[str], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(symbols)
    if text:
        text += "\n"
    output_path.write_text(text, encoding="utf-8")
    return output_path


def build_universe(
    *,
    qmt_client: QmtClient,
    config: UniverseConfig,
    refresh_sector_data: bool = True,
) -> UniverseBuildResult:
    if refresh_sector_data:
        qmt_client.download_sector_data()

    source_symbols = qmt_client.list_sector_symbols(config.sector_name)
    filtered_symbols = filter_symbols(
        source_symbols,
        include_suffixes=config.include_suffixes,
        exclude_prefixes=config.exclude_prefixes,
    )
    output_path = write_symbols(filtered_symbols, config.output_path)
    return UniverseBuildResult(
        sector_name=config.sector_name,
        source_count=len(source_symbols),
        filtered_count=len(filtered_symbols),
        output_path=output_path,
    )
