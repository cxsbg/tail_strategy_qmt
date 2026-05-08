from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from storage.sqlite import SQLiteStore
from utils.exceptions import StorageError


SIGNAL_COLUMNS = [
    "symbol",
    "signal_date",
    "signal_time",
    "score",
    "suggested_action",
    "suggested_position_ratio",
    "reasons",
    "risks",
    "strategy_version",
    "created_at",
]


class SuggestedAction(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"
    SKIP = "SKIP"


@dataclass(frozen=True)
class StrategySignal:
    id: int | None
    symbol: str
    signal_date: str
    signal_time: str | None
    score: float | None
    suggested_action: SuggestedAction
    suggested_position_ratio: float | None
    reasons: str | None
    risks: str | None
    strategy_version: str | None
    created_at: str | None


@dataclass(frozen=True)
class SignalBuildResult:
    date: str
    input_count: int
    signal_count: int
    output_path: Path | None
    db_path: Path


class SignalRepository:
    def __init__(self, store: SQLiteStore | str | Path) -> None:
        self.store = store if isinstance(store, SQLiteStore) else SQLiteStore(store)
        self.store.initialize()

    def replace_signals(
        self,
        signals: Iterable[StrategySignal],
        *,
        signal_date: str,
        strategy_version: str,
    ) -> int:
        signal_list = list(signals)
        with self.store.connect() as conn:
            conn.execute(
                "DELETE FROM signals WHERE signal_date = ? AND strategy_version = ?",
                (signal_date, strategy_version),
            )
            conn.executemany(
                """
                INSERT INTO signals (
                    symbol, signal_date, signal_time, score, suggested_action,
                    suggested_position_ratio, reasons, risks, strategy_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_signal_values(signal) for signal in signal_list],
            )
            conn.commit()
        return len(signal_list)

    def list_signals(
        self,
        *,
        signal_date: str | None = None,
        strategy_version: str | None = None,
    ) -> list[StrategySignal]:
        clauses: list[str] = []
        params: list[object] = []
        if signal_date is not None:
            clauses.append("signal_date = ?")
            params.append(signal_date)
        if strategy_version is not None:
            clauses.append("strategy_version = ?")
            params.append(strategy_version)

        sql = "SELECT * FROM signals"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY score DESC, symbol"
        with self.store.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_signal(row) for row in rows]


def build_signals(
    candidates: object,
    *,
    strategy_config: dict[str, Any],
    tail_confirmations: object | None = None,
    trade_date: str | None = None,
    strategy_version: str = "rule-v0",
) -> object:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to build strategy signals.") from exc

    if not isinstance(candidates, pd.DataFrame):
        raise StorageError("build_signals expects candidates to be a pandas DataFrame.")
    _validate_candidates(candidates)
    if candidates.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    date = trade_date or str(candidates["date"].max())
    candidate_frame = candidates.loc[candidates["date"] == date].copy()
    if candidate_frame.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    merged = _merge_tail_confirmations(
        candidate_frame,
        tail_confirmations=tail_confirmations,
        trade_date=date,
        pd=pd,
    )
    rows = [
        _signal_row(
            row,
            strategy_config=strategy_config,
            strategy_version=strategy_version,
        )
        for _, row in merged.iterrows()
    ]
    return pd.DataFrame(rows, columns=SIGNAL_COLUMNS).sort_values(
        ["suggested_action", "score", "symbol"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def build_and_store_signals(
    *,
    candidates_path: str | Path,
    db_path: str | Path,
    strategy_config: dict[str, Any],
    tail_confirmation_path: str | Path | None = None,
    output_path: str | Path | None = None,
    trade_date: str | None = None,
    strategy_version: str = "rule-v0",
) -> SignalBuildResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build strategy signals.") from exc

    candidates = pd.read_parquet(candidates_path)
    date = trade_date or (str(candidates["date"].max()) if not candidates.empty else "")
    tail_confirmations = None
    if tail_confirmation_path is not None and Path(tail_confirmation_path).exists():
        tail_confirmations = pd.read_parquet(tail_confirmation_path)

    signals = build_signals(
        candidates,
        strategy_config=strategy_config,
        tail_confirmations=tail_confirmations,
        trade_date=date or trade_date,
        strategy_version=strategy_version,
    )

    output = Path(output_path) if output_path is not None else None
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        signals.to_parquet(output, index=False)

    repository = SignalRepository(db_path)
    stored_count = 0
    if date:
        stored_count = repository.replace_signals(
            _frame_to_signals(signals),
            signal_date=date,
            strategy_version=strategy_version,
        )
    return SignalBuildResult(
        date=date,
        input_count=len(candidates.loc[candidates["date"] == date]) if date and not candidates.empty else 0,
        signal_count=stored_count,
        output_path=output,
        db_path=Path(db_path),
    )


def _merge_tail_confirmations(
    candidates: object,
    *,
    tail_confirmations: object | None,
    trade_date: str,
    pd: object,
) -> object:
    if tail_confirmations is None:
        merged = candidates.copy()
        merged["tail_confirmed"] = pd.NA
        merged["tail_failed_reasons"] = pd.NA
        merged["tail_confirm_time"] = pd.NA
        return merged

    if not isinstance(tail_confirmations, pd.DataFrame):
        raise StorageError("tail_confirmations must be a pandas DataFrame when provided.")
    required = {"symbol", "date", "tail_confirmed", "failed_reasons"}
    missing = required - set(tail_confirmations.columns)
    if missing:
        raise StorageError(f"Tail confirmation frame missing required columns: {', '.join(sorted(missing))}")

    tail = tail_confirmations.loc[tail_confirmations["date"] == trade_date].copy()
    if tail.empty:
        return _merge_tail_confirmations(candidates, tail_confirmations=None, trade_date=trade_date, pd=pd)

    keep_columns = ["symbol", "date", "tail_confirmed", "failed_reasons"]
    if "tail_confirm_time" in tail.columns:
        keep_columns.append("tail_confirm_time")
    tail = tail[keep_columns].rename(columns={"failed_reasons": "tail_failed_reasons"})
    return candidates.merge(tail, on=["symbol", "date"], how="left")


def _signal_row(row: object, *, strategy_config: dict[str, Any], strategy_version: str) -> dict[str, object]:
    import pandas as pd

    score = float(row["score"]) if not pd.isna(row["score"]) else None
    level = str(row.get("candidate_level", "")).lower()
    confirmed_value = row.get("tail_confirmed")
    tail_missing = pd.isna(confirmed_value)
    tail_confirmed = False if tail_missing else bool(confirmed_value)

    risks: list[str] = []
    if tail_missing:
        risks.append("missing_tail_confirmation")
    elif not tail_confirmed:
        risks.append("tail_not_confirmed")
        risks.extend(_split_reasons(row.get("tail_failed_reasons")))

    if tail_confirmed and level in {"focus", "normal"}:
        suggested_action = SuggestedAction.OPEN
        suggested_ratio = _suggested_position_ratio(strategy_config)
    elif tail_confirmed:
        suggested_action = SuggestedAction.WATCH
        suggested_ratio = 0.0
    elif tail_missing:
        suggested_action = SuggestedAction.WATCH
        suggested_ratio = 0.0
    else:
        suggested_action = SuggestedAction.SKIP
        suggested_ratio = 0.0

    reasons = _split_reasons(row.get("reasons"))
    if tail_confirmed:
        reasons.append("tail_confirmed")

    signal_time = row.get("tail_confirm_time")
    if pd.isna(signal_time):
        signal_time = None

    return {
        "symbol": row["symbol"],
        "signal_date": row["date"],
        "signal_time": signal_time,
        "score": score,
        "suggested_action": suggested_action.value,
        "suggested_position_ratio": suggested_ratio,
        "reasons": ",".join(dict.fromkeys(reasons)) or None,
        "risks": ",".join(dict.fromkeys(risks)) or None,
        "strategy_version": strategy_version,
        "created_at": _now(),
    }


def _suggested_position_ratio(strategy_config: dict[str, Any]) -> float:
    position_config = strategy_config.get("position", {})
    initial_ratio = float(position_config.get("initial_position_ratio", 0.0))
    max_single_ratio = float(position_config.get("max_single_stock_ratio", initial_ratio))
    if max_single_ratio <= 0:
        return round(max(0.0, initial_ratio), 4)
    return round(max(0.0, min(initial_ratio, max_single_ratio)), 4)


def _frame_to_signals(frame: object) -> list[StrategySignal]:
    return [
        StrategySignal(
            id=None,
            symbol=row["symbol"],
            signal_date=row["signal_date"],
            signal_time=row["signal_time"],
            score=row["score"],
            suggested_action=SuggestedAction(row["suggested_action"]),
            suggested_position_ratio=row["suggested_position_ratio"],
            reasons=row["reasons"],
            risks=row["risks"],
            strategy_version=row["strategy_version"],
            created_at=row["created_at"],
        )
        for _, row in frame.iterrows()
    ]


def _signal_values(signal: StrategySignal) -> tuple[object, ...]:
    return (
        signal.symbol,
        signal.signal_date,
        signal.signal_time,
        signal.score,
        signal.suggested_action.value,
        signal.suggested_position_ratio,
        signal.reasons,
        signal.risks,
        signal.strategy_version,
        signal.created_at,
    )


def _row_to_signal(row: object) -> StrategySignal:
    return StrategySignal(
        id=row["id"],
        symbol=row["symbol"],
        signal_date=row["signal_date"],
        signal_time=row["signal_time"],
        score=row["score"],
        suggested_action=SuggestedAction(row["suggested_action"]),
        suggested_position_ratio=row["suggested_position_ratio"],
        reasons=row["reasons"],
        risks=row["risks"],
        strategy_version=row["strategy_version"],
        created_at=row["created_at"],
    )


def _validate_candidates(candidates: object) -> None:
    required = {"symbol", "date", "score", "candidate_level", "reasons"}
    missing = required - set(candidates.columns)
    if missing:
        raise StorageError(f"Candidate frame missing required columns: {', '.join(sorted(missing))}")


def _split_reasons(value: object) -> list[str]:
    if value is None:
        return []
    text = str(value)
    if text in {"", "nan", "<NA>"}:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
