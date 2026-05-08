from __future__ import annotations

from pathlib import Path

from utils.config import load_config_dir, load_config_file


def test_load_strategy_config() -> None:
    config = load_config_file(Path("config/strategy.yaml"))

    assert config["universe"]["min_listing_days"] == 120
    assert config["position"]["max_total_positions"] == 5


def test_load_config_dir() -> None:
    configs = load_config_dir("config")

    assert {"data_source", "risk", "strategy", "universe"}.issubset(configs)
    assert configs["data_source"]["data_source"]["provider"] == "qmt"
