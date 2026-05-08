from __future__ import annotations

from pathlib import Path

from qmt.client import HistoryRequest
from data_layer.universe import (
    UniverseConfig,
    build_universe,
    filter_symbols,
    universe_config_from_dict,
    write_symbols,
)


class FakeUniverseQmtClient:
    def __init__(self) -> None:
        self.refreshed = False

    def fetch_history(self, request: HistoryRequest) -> object:
        raise NotImplementedError

    def download_history(self, request: HistoryRequest) -> None:
        raise NotImplementedError

    def download_sector_data(self) -> None:
        self.refreshed = True

    def list_sector_symbols(self, sector_name: str) -> list[str]:
        assert sector_name == "沪深A股"
        return ["000001.SZ", "600000.SH", "688001.SH", "830001.BJ", "300001.SZ"]


def test_universe_config_from_dict(tmp_path) -> None:
    config = universe_config_from_dict(
        {
            "source": {
                "sector_name": "沪深A股",
                "output_path": str(tmp_path / "universe.txt"),
            },
            "markets": {
                "include_suffixes": ["SH", "SZ"],
                "exclude_prefixes": ["688"],
            },
        }
    )

    assert config.sector_name == "沪深A股"
    assert config.output_path == tmp_path / "universe.txt"
    assert config.exclude_prefixes == ("688",)


def test_filter_symbols_excludes_prefix_and_suffix() -> None:
    symbols = filter_symbols(
        ["000001.SZ", "600000.SH", "688001.SH", "830001.BJ", "300001.sz"],
        include_suffixes=["SH", "SZ"],
        exclude_prefixes=["688", "8", "4"],
    )

    assert symbols == ["000001.SZ", "300001.SZ", "600000.SH"]


def test_write_symbols(tmp_path) -> None:
    path = write_symbols(["000001.SZ", "600000.SH"], tmp_path / "symbols.txt")

    assert path.read_text(encoding="utf-8") == "000001.SZ\n600000.SH\n"


def test_build_universe(tmp_path) -> None:
    qmt_client = FakeUniverseQmtClient()
    config = UniverseConfig(
        sector_name="沪深A股",
        output_path=Path(tmp_path / "universe.txt"),
        include_suffixes=("SH", "SZ"),
        exclude_prefixes=("688", "8", "4"),
    )

    result = build_universe(qmt_client=qmt_client, config=config)

    assert qmt_client.refreshed
    assert result.source_count == 5
    assert result.filtered_count == 3
    assert config.output_path.read_text(encoding="utf-8").splitlines() == [
        "000001.SZ",
        "300001.SZ",
        "600000.SH",
    ]
