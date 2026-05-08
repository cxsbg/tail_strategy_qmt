from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from storage.parquet import ParquetStorage
from utils.exceptions import StorageError
from utils.logging import get_logger


logger = get_logger(__name__)


FEATURE_COLUMNS = [
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pre_close",
    "pct_chg",
    "ma5",
    "ma10",
    "ma20",
    "return_5d",
    "return_20d",
    "avg_amount_20d",
    "volume_ma5",
    "volume_ratio_5d",
    "high_20d",
    "low_20d",
    "close_position_20d",
    "distance_to_ma20",
    "upper_shadow_ratio",
    "is_paused",
]


@dataclass(frozen=True)
class FeatureBuildResult:
    output_path: Path
    symbol_count: int
    row_count: int
    skipped_symbols: tuple[str, ...]


def compute_daily_features(frame: object) -> object:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to compute daily features.") from exc

    if not isinstance(frame, pd.DataFrame):
        raise StorageError("compute_daily_features expects a pandas DataFrame.")

    _validate_daily_frame(frame)
    features = frame.copy()
    features = features.sort_values(["symbol", "date"]).reset_index(drop=True)

    grouped = features.groupby("symbol", group_keys=False)
    if "pre_close" not in features.columns:
        features["pre_close"] = grouped["close"].shift(1)
    features["pct_chg"] = _safe_divide(features["close"], features["pre_close"]) - 1
    features["ma5"] = grouped["close"].transform(lambda item: item.rolling(5, min_periods=5).mean())
    features["ma10"] = grouped["close"].transform(lambda item: item.rolling(10, min_periods=10).mean())
    features["ma20"] = grouped["close"].transform(lambda item: item.rolling(20, min_periods=20).mean())
    features["return_5d"] = grouped["close"].pct_change(5)
    features["return_20d"] = grouped["close"].pct_change(20)
    features["avg_amount_20d"] = grouped["amount"].transform(lambda item: item.rolling(20, min_periods=20).mean())
    features["volume_ma5"] = grouped["volume"].transform(lambda item: item.rolling(5, min_periods=5).mean())
    features["volume_ratio_5d"] = _safe_divide(features["volume"], features["volume_ma5"])
    features["high_20d"] = grouped["high"].transform(lambda item: item.rolling(20, min_periods=20).max())
    features["low_20d"] = grouped["low"].transform(lambda item: item.rolling(20, min_periods=20).min())
    features["close_position_20d"] = _safe_divide(
        features["close"] - features["low_20d"],
        features["high_20d"] - features["low_20d"],
    )
    features["distance_to_ma20"] = _safe_divide(features["close"], features["ma20"]) - 1
    features["upper_shadow_ratio"] = _safe_divide(
        features["high"] - features[["open", "close"]].max(axis=1),
        features["high"] - features["low"],
    )
    features["is_paused"] = _paused_flag(features)

    return features[FEATURE_COLUMNS]


def build_daily_features(
    *,
    symbols: Iterable[str],
    storage: ParquetStorage,
    output_path: str | Path,
) -> FeatureBuildResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build daily features.") from exc

    feature_frames = []
    skipped_symbols: list[str] = []
    for symbol in symbols:
        try:
            daily_frame = storage.read_frame("daily", symbol)
        except StorageError:
            logger.warning("Skip %s because daily parquet cache is missing.", symbol)
            skipped_symbols.append(symbol)
            continue
        feature_frames.append(compute_daily_features(daily_frame))

    if feature_frames:
        result_frame = pd.concat(feature_frames, ignore_index=True)
        result_frame = result_frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    else:
        result_frame = pd.DataFrame(columns=FEATURE_COLUMNS)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    result_frame.to_parquet(path, index=False)
    return FeatureBuildResult(
        output_path=path,
        symbol_count=len(feature_frames),
        row_count=len(result_frame),
        skipped_symbols=tuple(skipped_symbols),
    )


def _validate_daily_frame(frame: object) -> None:
    required = {"symbol", "date", "open", "high", "low", "close", "volume", "amount"}
    missing = required - set(frame.columns)
    if missing:
        raise StorageError(f"Daily frame missing required columns: {', '.join(sorted(missing))}")


def _safe_divide(numerator: object, denominator: object) -> object:
    import pandas as pd

    result = numerator / denominator
    return result.where(pd.notna(result) & (denominator != 0))


def _paused_flag(frame: object) -> object:
    if "suspendflag" in frame.columns:
        return frame["suspendflag"].fillna(0).astype(int) != 0
    return False
