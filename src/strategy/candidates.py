from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.exceptions import StorageError


REQUIRED_FEATURE_COLUMNS = {
    "symbol",
    "date",
    "close",
    "pct_chg",
    "ma5",
    "ma10",
    "ma20",
    "return_5d",
    "return_20d",
    "avg_amount_20d",
    "volume_ratio_5d",
    "close_position_20d",
    "distance_to_ma20",
    "upper_shadow_ratio",
    "is_paused",
}


@dataclass(frozen=True)
class CandidateBuildResult:
    output_path: Path
    date: str
    input_count: int
    candidate_count: int


def select_candidates(
    features: object,
    *,
    strategy_config: dict[str, Any],
    trade_date: str | None = None,
) -> object:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to select strategy candidates.") from exc

    if not isinstance(features, pd.DataFrame):
        raise StorageError("select_candidates expects a pandas DataFrame.")
    _validate_features(features)

    date = trade_date or str(features["date"].max())
    latest = features.loc[features["date"] == date].copy()
    if latest.empty:
        return _empty_candidates(pd)

    latest["listing_days"] = features.groupby("symbol")["date"].transform("count")
    latest["reasons"] = latest.apply(lambda row: _candidate_reasons(row, strategy_config), axis=1)
    latest["passed"] = latest["reasons"].map(lambda reasons: len(reasons) == 0)
    candidates = latest.loc[latest["passed"]].copy()
    if candidates.empty:
        return _empty_candidates(pd)

    candidates["score"] = candidates.apply(lambda row: _score_candidate(row, strategy_config), axis=1)
    candidates["candidate_level"] = candidates["score"].map(_candidate_level)
    candidates["reasons"] = candidates.apply(lambda row: _positive_reasons(row), axis=1)
    candidates = candidates.sort_values(["score", "volume_ratio_5d"], ascending=[False, False])

    return candidates[
        [
            "symbol",
            "date",
            "score",
            "candidate_level",
            "close",
            "pct_chg",
            "ma5",
            "ma10",
            "ma20",
            "return_5d",
            "return_20d",
            "avg_amount_20d",
            "volume_ratio_5d",
            "close_position_20d",
            "distance_to_ma20",
            "upper_shadow_ratio",
            "reasons",
        ]
    ].reset_index(drop=True)


def build_candidates(
    *,
    features_path: str | Path,
    output_path: str | Path,
    strategy_config: dict[str, Any],
    trade_date: str | None = None,
) -> CandidateBuildResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build candidates.") from exc

    feature_frame = pd.read_parquet(features_path)
    date = trade_date or str(feature_frame["date"].max())
    candidates = select_candidates(
        feature_frame,
        strategy_config=strategy_config,
        trade_date=date,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_parquet(path, index=False)
    return CandidateBuildResult(
        output_path=path,
        date=date,
        input_count=int((feature_frame["date"] == date).sum()),
        candidate_count=len(candidates),
    )


def _validate_features(features: object) -> None:
    missing = REQUIRED_FEATURE_COLUMNS - set(features.columns)
    if missing:
        raise StorageError(f"Feature frame missing required columns: {', '.join(sorted(missing))}")


def _candidate_reasons(row: object, config: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    universe = config.get("universe", {})
    trend = config.get("trend", {})
    strength = config.get("strength", {})
    volume = config.get("volume", {})

    _require(reasons, row["listing_days"] >= universe.get("min_listing_days", 0), "listing_days")
    _require(reasons, row["close"] >= universe.get("min_price", 0), "price")
    _require(reasons, row["avg_amount_20d"] >= universe.get("min_avg_amount_20d", 0), "avg_amount_20d")
    _require(reasons, not bool(row["is_paused"]), "paused")

    if trend.get("require_price_above_ma20", True):
        _require(reasons, row["close"] > row["ma20"], "price_above_ma20")
    if trend.get("require_ma_order", True):
        _require(reasons, row["ma5"] > row["ma10"] > row["ma20"], "ma_order")
    _require(reasons, row["distance_to_ma20"] <= trend.get("max_distance_to_ma20", 1), "distance_to_ma20")
    _require(reasons, row["return_5d"] <= trend.get("max_return_5d", 1), "return_5d")
    _require(reasons, row["return_20d"] <= trend.get("max_return_20d", 1), "return_20d")

    _require(reasons, row["pct_chg"] >= strength.get("min_return_today", -1), "min_return_today")
    _require(reasons, row["pct_chg"] <= strength.get("max_return_today", 1), "max_return_today")
    _require(reasons, row["close_position_20d"] >= strength.get("min_close_position", 0), "close_position")
    _require(reasons, row["upper_shadow_ratio"] <= strength.get("max_upper_shadow_ratio", 1), "upper_shadow")

    _require(reasons, row["volume_ratio_5d"] >= volume.get("min_volume_ratio_5d", 0), "min_volume_ratio")
    _require(reasons, row["volume_ratio_5d"] <= volume.get("max_volume_ratio_5d", 999), "max_volume_ratio")
    return reasons


def _require(reasons: list[str], condition: object, reason: str) -> None:
    try:
        import pandas as pd
    except ModuleNotFoundError:
        pd = None

    if pd is not None and pd.isna(condition):
        reasons.append(reason)
    elif not bool(condition):
        reasons.append(reason)


def _score_candidate(row: object, config: dict[str, Any]) -> float:
    strength = config.get("strength", {})
    volume = config.get("volume", {})
    trend = config.get("trend", {})

    pct_min = strength.get("min_return_today", 0.02)
    pct_max = strength.get("max_return_today", 0.065)
    vol_min = volume.get("min_volume_ratio_5d", 1.2)
    vol_max = volume.get("max_volume_ratio_5d", 2.5)
    distance_max = trend.get("max_distance_to_ma20", 0.12)

    score = 70.0
    score += 10.0 * _bounded_ratio(row["pct_chg"], pct_min, pct_max)
    score += 10.0 * _bounded_ratio(row["close_position_20d"], 0.75, 1.0)
    score += 8.0 * _bounded_ratio(row["volume_ratio_5d"], vol_min, vol_max)
    score += 7.0 * (1.0 - _bounded_ratio(row["distance_to_ma20"], 0.0, distance_max))
    score -= 5.0 * _bounded_ratio(row["upper_shadow_ratio"], 0.0, strength.get("max_upper_shadow_ratio", 0.35))
    return round(max(0.0, min(100.0, score)), 2)


def _bounded_ratio(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 0.0
    return max(0.0, min(1.0, (float(value) - minimum) / (maximum - minimum)))


def _candidate_level(score: float) -> str:
    if score >= 85:
        return "focus"
    if score >= 75:
        return "normal"
    if score >= 70:
        return "watch"
    return "ignore"


def _positive_reasons(row: object) -> str:
    reasons = [
        "price_above_ma20",
        "ma5_gt_ma10_gt_ma20",
        "strong_close_position",
        "volume_confirmed",
    ]
    return ",".join(reasons)


def _empty_candidates(pd: object) -> object:
    return pd.DataFrame(
        columns=[
            "symbol",
            "date",
            "score",
            "candidate_level",
            "close",
            "pct_chg",
            "ma5",
            "ma10",
            "ma20",
            "return_5d",
            "return_20d",
            "avg_amount_20d",
            "volume_ratio_5d",
            "close_position_20d",
            "distance_to_ma20",
            "upper_shadow_ratio",
            "reasons",
        ]
    )
