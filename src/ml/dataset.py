from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from utils.exceptions import StorageError


ML_FEATURE_COLUMNS = [
    "pct_chg",
    "return_5d",
    "return_20d",
    "avg_amount_20d",
    "volume_ratio_5d",
    "close_position_20d",
    "distance_to_ma20",
    "upper_shadow_ratio",
]

ML_DATASET_COLUMNS = [
    "symbol",
    "date",
    "forward_close",
    "forward_return",
    "label",
    "horizon_days",
    "source_score",
    "candidate_level",
    *ML_FEATURE_COLUMNS,
]


@dataclass(frozen=True)
class MLDatasetBuildResult:
    output_path: Path
    row_count: int
    positive_count: int
    feature_count: int
    horizon_days: int


def build_ml_dataset(
    features: object,
    *,
    candidates: object | None = None,
    horizon_days: int = 5,
    min_forward_return: float = 0.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> object:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to build ML datasets.") from exc

    if not isinstance(features, pd.DataFrame):
        raise StorageError("build_ml_dataset expects features to be a pandas DataFrame.")
    if horizon_days <= 0:
        raise StorageError("horizon_days must be positive.")
    _validate_features(features)

    frame = features.copy().sort_values(["symbol", "date"]).reset_index(drop=True)
    if start_date is not None:
        frame = frame.loc[frame["date"].astype(str) >= start_date].copy()
    if end_date is not None:
        frame = frame.loc[frame["date"].astype(str) <= end_date].copy()

    grouped = frame.groupby("symbol", group_keys=False)
    frame["forward_close"] = grouped["close"].shift(-horizon_days)
    frame["forward_return"] = frame["forward_close"] / frame["close"] - 1.0
    frame["label"] = (frame["forward_return"] >= float(min_forward_return)).astype("int64")
    frame["horizon_days"] = int(horizon_days)

    frame = _attach_candidates(frame, candidates=candidates, pd=pd)
    frame = frame.dropna(subset=["forward_close", "forward_return", *ML_FEATURE_COLUMNS]).copy()
    if frame.empty:
        return pd.DataFrame(columns=ML_DATASET_COLUMNS)
    return frame[ML_DATASET_COLUMNS].sort_values(["date", "symbol"]).reset_index(drop=True)


def build_ml_dataset_file(
    *,
    features_path: str | Path,
    output_path: str | Path,
    candidates_path: str | Path | None = None,
    horizon_days: int = 5,
    min_forward_return: float = 0.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> MLDatasetBuildResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build ML datasets.") from exc

    features = pd.read_parquet(features_path)
    candidates = pd.read_parquet(candidates_path) if candidates_path is not None and Path(candidates_path).exists() else None
    dataset = build_ml_dataset(
        features,
        candidates=candidates,
        horizon_days=horizon_days,
        min_forward_return=min_forward_return,
        start_date=start_date,
        end_date=end_date,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(output, index=False)
    return MLDatasetBuildResult(
        output_path=output,
        row_count=len(dataset),
        positive_count=int(dataset["label"].sum()) if not dataset.empty else 0,
        feature_count=len(ML_FEATURE_COLUMNS),
        horizon_days=horizon_days,
    )


def _attach_candidates(frame: object, *, candidates: object | None, pd: object) -> object:
    result = frame.copy()
    if candidates is None:
        result["source_score"] = pd.NA
        result["candidate_level"] = pd.NA
        return result
    if not isinstance(candidates, pd.DataFrame):
        raise StorageError("candidates must be a pandas DataFrame when provided.")
    required = {"symbol", "date", "score", "candidate_level"}
    missing = required - set(candidates.columns)
    if missing:
        raise StorageError(f"Candidate frame missing required columns: {', '.join(sorted(missing))}")
    candidate_frame = candidates[["symbol", "date", "score", "candidate_level"]].rename(
        columns={"score": "source_score"}
    )
    return result.merge(candidate_frame, on=["symbol", "date"], how="inner")


def _validate_features(features: object) -> None:
    required = {"symbol", "date", "close", *ML_FEATURE_COLUMNS}
    missing = required - set(features.columns)
    if missing:
        raise StorageError(f"Feature frame missing required columns: {', '.join(sorted(missing))}")
