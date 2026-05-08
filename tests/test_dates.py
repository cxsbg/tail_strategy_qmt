from __future__ import annotations

from data_layer.dates import is_cache_current, next_start_value, normalize_compare_value


def test_next_start_value_daily() -> None:
    assert next_start_value("daily", "20240501") == "20240502"


def test_next_start_value_minute() -> None:
    assert next_start_value("minute", "20240501143000") == "20240501143100"


def test_is_cache_current_daily() -> None:
    assert is_cache_current("daily", "20240501", "20240501")
    assert is_cache_current("daily", "20240502", "20240501")
    assert not is_cache_current("daily", "20240430", "20240501")


def test_normalize_compare_value_minute_accepts_date_only() -> None:
    assert normalize_compare_value("minute", "20240501") == "20240501000000"
