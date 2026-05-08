from __future__ import annotations

import pytest

from features.daily import compute_daily_features, build_daily_features
from storage.parquet import ParquetStorage


def _daily_frame(symbol: str = "000001.SZ", days: int = 25):
    pd = pytest.importorskip("pandas")
    rows = []
    for index in range(days):
        close = float(index + 1)
        rows.append(
            {
                "symbol": symbol,
                "date": f"202401{index + 1:02d}",
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100 + index,
                "amount": 1000 + index * 10,
                "pre_close": close - 1 if index else close,
                "suspendflag": 0,
            }
        )
    return pd.DataFrame(rows)


def test_compute_daily_features_calculates_core_columns() -> None:
    frame = _daily_frame()

    features = compute_daily_features(frame)
    row = features.loc[features["date"] == "20240120"].iloc[0]

    assert row["ma5"] == pytest.approx(18.0)
    assert row["ma10"] == pytest.approx(15.5)
    assert row["ma20"] == pytest.approx(10.5)
    assert row["return_5d"] == pytest.approx((20 / 15) - 1)
    assert row["return_20d"] != row["return_20d"]
    assert row["avg_amount_20d"] == pytest.approx(1095.0)
    assert row["volume_ratio_5d"] == pytest.approx(119 / 117)
    assert 0 <= row["close_position_20d"] <= 1
    assert row["upper_shadow_ratio"] == pytest.approx(0.5)
    assert not row["is_paused"]


def test_compute_daily_features_gets_20d_return_after_window() -> None:
    features = compute_daily_features(_daily_frame(days=25))
    row = features.loc[features["date"] == "20240125"].iloc[0]

    assert row["return_20d"] == pytest.approx((25 / 5) - 1)


def test_build_daily_features_writes_output_and_skips_missing_symbols(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    storage = ParquetStorage(tmp_path / "parquet")
    storage.write_frame("daily", "000001.SZ", _daily_frame())

    result = build_daily_features(
        symbols=["000001.SZ", "600000.SH"],
        storage=storage,
        output_path=tmp_path / "features.parquet",
    )

    output = pd.read_parquet(result.output_path)
    assert result.symbol_count == 1
    assert result.row_count == 25
    assert result.skipped_symbols == ("600000.SH",)
    assert set(output["symbol"]) == {"000001.SZ"}
