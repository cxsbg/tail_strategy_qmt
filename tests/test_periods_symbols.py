from __future__ import annotations

from data_layer.periods import resolve_period
from data_layer.symbols import load_symbols, parse_symbols


def test_resolve_period_daily() -> None:
    spec = resolve_period("daily")

    assert spec.qmt_period == "1d"
    assert spec.storage_period == "daily"


def test_parse_symbols() -> None:
    assert parse_symbols("000001.SZ, 600000.SH,,") == ["000001.SZ", "600000.SH"]


def test_load_symbols(tmp_path) -> None:
    path = tmp_path / "symbols.txt"
    path.write_text("000001.SZ\n# comment\n600000.SH\n", encoding="utf-8")

    assert load_symbols(path) == ["000001.SZ", "600000.SH"]
