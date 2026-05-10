from __future__ import annotations

import pytest

from ml.dataset import ML_DATASET_COLUMNS, build_ml_dataset, build_ml_dataset_file
from utils.exceptions import StorageError


def test_build_ml_dataset_labels_forward_returns() -> None:
    pd = pytest.importorskip("pandas")
    features = _features(pd, symbol="000001.SZ", closes=[10, 11, 12, 11, 13, 14, 15])

    dataset = build_ml_dataset(features, horizon_days=2, min_forward_return=0.10)

    assert list(dataset.columns) == ML_DATASET_COLUMNS
    assert len(dataset) == 5
    first = dataset.iloc[0]
    assert first["forward_close"] == 12
    assert round(first["forward_return"], 6) == 0.2
    assert first["label"] == 1


def test_build_ml_dataset_can_restrict_to_candidates() -> None:
    pd = pytest.importorskip("pandas")
    features = _features(pd, symbol="000001.SZ", closes=[10, 11, 12, 13, 14, 15, 16])
    candidates = pd.DataFrame(
        [
            {"symbol": "000001.SZ", "date": "20260502", "score": 88.0, "candidate_level": "focus"},
            {"symbol": "000001.SZ", "date": "20260504", "score": 70.0, "candidate_level": "normal"},
        ]
    )

    dataset = build_ml_dataset(features, candidates=candidates, horizon_days=2)

    assert list(dataset["date"]) == ["20260502", "20260504"]
    assert list(dataset["source_score"]) == [88.0, 70.0]
    assert list(dataset["candidate_level"]) == ["focus", "normal"]


def test_build_ml_dataset_file_writes_parquet(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    features_path = tmp_path / "features.parquet"
    output_path = tmp_path / "ml_dataset.parquet"
    _features(pd, symbol="000001.SZ", closes=[10, 11, 12, 13, 14, 15, 16]).to_parquet(features_path, index=False)

    result = build_ml_dataset_file(
        features_path=features_path,
        output_path=output_path,
        horizon_days=2,
        min_forward_return=0.0,
    )

    saved = pd.read_parquet(output_path)
    assert result.row_count == 5
    assert result.positive_count == 5
    assert result.feature_count == 8
    assert len(saved) == 5


def test_build_ml_dataset_rejects_missing_columns() -> None:
    pd = pytest.importorskip("pandas")

    with pytest.raises(StorageError):
        build_ml_dataset(pd.DataFrame([{"symbol": "000001.SZ"}]))


def _features(pd, *, symbol: str, closes: list[float]):
    rows = []
    for index, close in enumerate(closes, start=1):
        rows.append(
            {
                "symbol": symbol,
                "date": f"202605{index:02d}",
                "close": float(close),
                "pct_chg": 0.01,
                "return_5d": 0.05,
                "return_20d": 0.20,
                "avg_amount_20d": 100000000.0,
                "volume_ratio_5d": 1.5,
                "close_position_20d": 0.8,
                "distance_to_ma20": 0.05,
                "upper_shadow_ratio": 0.1,
            }
        )
    return pd.DataFrame(rows)
