from __future__ import annotations

import pytest

from data_layer.normalize import normalize_market_data


def test_normalize_daily_dataframe_adds_symbol() -> None:
    pd = pytest.importorskip("pandas")
    raw = pd.DataFrame(
        [
            {
                "date": "20240102",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "amount": 1000,
            }
        ]
    )

    normalized = normalize_market_data(raw, symbol="000001.SZ", storage_period="daily")

    assert normalized.loc[0, "symbol"] == "000001.SZ"
    assert normalized.loc[0, "date"] == "20240102"


def test_normalize_qmt_dict_payload() -> None:
    pd = pytest.importorskip("pandas")
    raw = {
        "000001.SZ": pd.DataFrame(
            [
                {
                    "time": "2024-01-02 14:30:00",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "vol": 100,
                    "amount": 1000,
                }
            ]
        )
    }

    normalized = normalize_market_data(raw, symbol="000001.SZ", storage_period="minute")

    assert normalized.loc[0, "datetime"] == "20240102143000"
    assert normalized.loc[0, "volume"] == 100


def test_normalize_qmt_daily_uses_trade_date_index_before_epoch_time() -> None:
    pd = pytest.importorskip("pandas")
    raw = pd.DataFrame(
        [
            {
                "time": 1704124800000,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "amount": 1000,
            }
        ],
        index=["20240102"],
    )

    normalized = normalize_market_data(raw, symbol="000001.SZ", storage_period="daily")

    assert normalized.loc[0, "date"] == "20240102"
