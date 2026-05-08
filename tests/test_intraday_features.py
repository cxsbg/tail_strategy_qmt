from __future__ import annotations

import pytest

from features.intraday import compute_tail_confirmation, build_tail_confirmations
from storage.parquet import ParquetStorage


def test_compute_tail_confirmation_passes_when_tail_is_orderly() -> None:
    frame = _minute_frame(close_end=10.2, high_tail_volume=False)

    result = compute_tail_confirmation(
        frame,
        intraday_config=_intraday_config(),
        trade_date="20260508",
    )

    row = result.iloc[0]
    assert row["tail_confirmed"]
    assert row["tail_return_1430_1500"] == pytest.approx(0.02)
    assert row["tail_return_1445_1500"] == pytest.approx((10.2 / 10.1) - 1)
    assert row["tail_volume_ratio"] <= 0.35
    assert row["failed_reasons"] == ""


def test_compute_tail_confirmation_fails_on_fast_tail_pull() -> None:
    frame = _minute_frame(close_end=10.6, high_tail_volume=True)

    result = compute_tail_confirmation(
        frame,
        intraday_config=_intraday_config(),
        trade_date="20260508",
    )

    row = result.iloc[0]
    assert not row["tail_confirmed"]
    assert "tail_return_1430_1500" in row["failed_reasons"]
    assert "tail_return_1445_1500" in row["failed_reasons"]
    assert "tail_volume_ratio" in row["failed_reasons"]


def test_build_tail_confirmations_writes_output_and_skips_missing_symbols(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    storage = ParquetStorage(tmp_path / "parquet")
    storage.write_frame("minute", "000001.SZ", _minute_frame())

    result = build_tail_confirmations(
        symbols=["000001.SZ", "600000.SH"],
        storage=storage,
        output_path=tmp_path / "tail.parquet",
        intraday_config=_intraday_config(),
        trade_date="20260508",
    )

    output = pd.read_parquet(result.output_path)
    assert result.symbol_count == 1
    assert result.row_count == 1
    assert result.skipped_symbols == ("600000.SH",)
    assert output.loc[0, "symbol"] == "000001.SZ"


def _minute_frame(close_end: float = 10.2, high_tail_volume: bool = False):
    pd = pytest.importorskip("pandas")
    rows = []
    for hour, minute in [(9, 30), (10, 0), (13, 0), (14, 0), (14, 30), (14, 45), (15, 0)]:
        time_value = f"20260508{hour:02d}{minute:02d}00"
        if (hour, minute) == (14, 30):
            close = 10.0
        elif (hour, minute) == (14, 45):
            close = 10.1
        elif (hour, minute) == (15, 0):
            close = close_end
        else:
            close = 9.8
        is_tail_bar = (hour, minute) in {(14, 30), (14, 45), (15, 0)}
        if high_tail_volume and is_tail_bar:
            volume = 500
        elif is_tail_bar:
            volume = 60
        else:
            volume = 100
        rows.append(
            {
                "symbol": "000001.SZ",
                "datetime": time_value,
                "open": close - 0.01,
                "high": close + 0.02,
                "low": close - 0.02,
                "close": close,
                "volume": volume,
                "amount": volume * close,
            }
        )
    return pd.DataFrame(rows)


def _intraday_config() -> dict[str, object]:
    return {
        "tail_start_time": "14:30",
        "tail_confirm_time": "14:45",
        "max_tail_return_1430_1500": 0.03,
        "max_tail_return_1445_1500": 0.02,
        "max_tail_volume_ratio": 0.35,
    }
