from __future__ import annotations

from pathlib import Path


def parse_symbols(value: str) -> list[str]:
    symbols = [item.strip() for item in value.split(",")]
    return [symbol for symbol in symbols if symbol]


def load_symbols(path: str | Path) -> list[str]:
    symbol_path = Path(path)
    lines = symbol_path.read_text(encoding="utf-8").splitlines()
    symbols: list[str] = []
    for line in lines:
        cleaned = line.split("#", 1)[0].strip()
        if cleaned:
            symbols.append(cleaned)
    return symbols
