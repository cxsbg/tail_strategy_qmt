from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from position.models import Position, PositionStatus
from position.repository import PositionRepository
from storage.sqlite import SQLiteStore
from strategy.signals import SignalRepository, StrategySignal, SuggestedAction
from utils.exceptions import StorageError


DECISION_COLUMNS = [
    "symbol",
    "decision_date",
    "source_signal_id",
    "position_id",
    "action",
    "score",
    "suggested_position_ratio",
    "reasons",
    "risks",
    "strategy_version",
    "created_at",
]


class DecisionAction(str, Enum):
    OPEN_POSITION = "OPEN_POSITION"
    HOLD_POSITION = "HOLD_POSITION"
    WATCH_POSITION = "WATCH_POSITION"
    REDUCE_POSITION = "REDUCE_POSITION"
    WATCH_SIGNAL = "WATCH_SIGNAL"
    SKIP_SIGNAL = "SKIP_SIGNAL"


@dataclass(frozen=True)
class StrategyDecision:
    id: int | None
    symbol: str
    decision_date: str
    source_signal_id: int | None
    position_id: int | None
    action: DecisionAction
    score: float | None
    suggested_position_ratio: float | None
    reasons: str | None
    risks: str | None
    strategy_version: str | None
    created_at: str | None


@dataclass(frozen=True)
class DecisionBuildResult:
    date: str
    signal_count: int
    open_position_count: int
    decision_count: int
    output_path: Path | None
    db_path: Path


class DecisionRepository:
    def __init__(self, store: SQLiteStore | str | Path) -> None:
        self.store = store if isinstance(store, SQLiteStore) else SQLiteStore(store)
        self.store.initialize()

    def replace_decisions(
        self,
        decisions: Iterable[StrategyDecision],
        *,
        decision_date: str,
        strategy_version: str,
    ) -> int:
        decision_list = list(decisions)
        with self.store.connect() as conn:
            conn.execute(
                "DELETE FROM decisions WHERE decision_date = ? AND strategy_version = ?",
                (decision_date, strategy_version),
            )
            conn.executemany(
                """
                INSERT INTO decisions (
                    symbol, decision_date, source_signal_id, position_id, action,
                    score, suggested_position_ratio, reasons, risks, strategy_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_decision_values(decision) for decision in decision_list],
            )
            conn.commit()
        return len(decision_list)

    def list_decisions(
        self,
        *,
        decision_date: str | None = None,
        strategy_version: str | None = None,
    ) -> list[StrategyDecision]:
        clauses: list[str] = []
        params: list[object] = []
        if decision_date is not None:
            clauses.append("decision_date = ?")
            params.append(decision_date)
        if strategy_version is not None:
            clauses.append("strategy_version = ?")
            params.append(strategy_version)

        sql = "SELECT * FROM decisions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY action, score DESC, symbol"
        with self.store.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_decision(row) for row in rows]


def build_decisions(
    *,
    signals: Iterable[StrategySignal],
    open_positions: Iterable[Position],
    decision_date: str,
    strategy_config: dict[str, Any],
    strategy_version: str = "rule-v0",
) -> list[StrategyDecision]:
    signal_list = list(signals)
    position_list = list(open_positions)
    signals_by_symbol = {signal.symbol: signal for signal in signal_list}
    positions_by_symbol = {position.symbol: position for position in position_list}
    decisions: list[StrategyDecision] = []

    for position in sorted(position_list, key=lambda item: item.symbol):
        signal = signals_by_symbol.get(position.symbol)
        decisions.append(
            _position_decision(
                position=position,
                signal=signal,
                decision_date=decision_date,
                strategy_version=strategy_version,
            )
        )

    position_config = strategy_config.get("position", {})
    max_total_positions = int(position_config.get("max_total_positions", 999999))
    max_new_positions = int(position_config.get("max_new_positions_per_day", 999999))
    available_slots = max(0, max_total_positions - len(position_list))
    new_open_quota = min(max_new_positions, available_slots)
    opened = 0

    new_signals = [
        signal
        for signal in signal_list
        if signal.symbol not in positions_by_symbol
    ]
    new_signals.sort(key=lambda signal: ((signal.score or 0.0), signal.symbol), reverse=True)
    for signal in new_signals:
        action, ratio, risks = _new_signal_decision(
            signal=signal,
            can_open=opened < new_open_quota,
            available_slots=available_slots,
            max_new_positions=max_new_positions,
        )
        if action == DecisionAction.OPEN_POSITION:
            opened += 1
        decisions.append(
            StrategyDecision(
                id=None,
                symbol=signal.symbol,
                decision_date=decision_date,
                source_signal_id=signal.id,
                position_id=None,
                action=action,
                score=signal.score,
                suggested_position_ratio=ratio,
                reasons=_join_reasons(signal.reasons, _action_reason(action)),
                risks=_join_reasons(signal.risks, *risks),
                strategy_version=strategy_version,
                created_at=_now(),
            )
        )

    return sorted(
        decisions,
        key=lambda decision: (
            _action_rank(decision.action),
            -(decision.score or 0.0),
            decision.symbol,
        ),
    )


def build_and_store_decisions(
    *,
    db_path: str | Path,
    strategy_config: dict[str, Any],
    decision_date: str,
    output_path: str | Path | None = None,
    strategy_version: str = "rule-v0",
) -> DecisionBuildResult:
    signal_repository = SignalRepository(db_path)
    position_repository = PositionRepository(db_path)
    decision_repository = DecisionRepository(db_path)

    signals = signal_repository.list_signals(
        signal_date=decision_date,
        strategy_version=strategy_version,
    )
    open_positions = position_repository.list_open_positions()
    decisions = build_decisions(
        signals=signals,
        open_positions=open_positions,
        decision_date=decision_date,
        strategy_config=strategy_config,
        strategy_version=strategy_version,
    )

    output = Path(output_path) if output_path is not None else None
    if output is not None:
        _write_decision_parquet(decisions, output)

    stored_count = decision_repository.replace_decisions(
        decisions,
        decision_date=decision_date,
        strategy_version=strategy_version,
    )
    return DecisionBuildResult(
        date=decision_date,
        signal_count=len(signals),
        open_position_count=len(open_positions),
        decision_count=stored_count,
        output_path=output,
        db_path=Path(db_path),
    )


def _position_decision(
    *,
    position: Position,
    signal: StrategySignal | None,
    decision_date: str,
    strategy_version: str,
) -> StrategyDecision:
    action = DecisionAction.HOLD_POSITION
    reasons = ["position_open"]
    risks: list[str] = []
    score = None

    if signal is None:
        risks.append("missing_signal")
        action = DecisionAction.WATCH_POSITION
    else:
        score = signal.score
        reasons.extend(_split_reasons(signal.reasons))
        risks.extend(_split_reasons(signal.risks))
        if signal.suggested_action == SuggestedAction.SKIP:
            action = DecisionAction.REDUCE_POSITION
            risks.append("signal_skip")
        elif signal.suggested_action == SuggestedAction.WATCH:
            action = DecisionAction.WATCH_POSITION
        elif position.status in {PositionStatus.NEW_POSITION, PositionStatus.HOLD, PositionStatus.ADD_CANDIDATE}:
            action = DecisionAction.HOLD_POSITION

    return StrategyDecision(
        id=None,
        symbol=position.symbol,
        decision_date=decision_date,
        source_signal_id=signal.id if signal is not None else None,
        position_id=position.id,
        action=action,
        score=score,
        suggested_position_ratio=position.position_ratio,
        reasons=",".join(dict.fromkeys(reasons)) or None,
        risks=",".join(dict.fromkeys(risks)) or None,
        strategy_version=strategy_version,
        created_at=_now(),
    )


def _new_signal_decision(
    *,
    signal: StrategySignal,
    can_open: bool,
    available_slots: int,
    max_new_positions: int,
) -> tuple[DecisionAction, float, list[str]]:
    risks: list[str] = []
    if signal.suggested_action == SuggestedAction.OPEN:
        if can_open:
            return (
                DecisionAction.OPEN_POSITION,
                float(signal.suggested_position_ratio or 0.0),
                risks,
            )
        if available_slots <= 0:
            risks.append("max_total_positions")
        elif max_new_positions <= 0:
            risks.append("max_new_positions_per_day")
        else:
            risks.append("new_position_quota_used")
        return DecisionAction.WATCH_SIGNAL, 0.0, risks
    if signal.suggested_action == SuggestedAction.SKIP:
        return DecisionAction.SKIP_SIGNAL, 0.0, ["signal_skip"]
    return DecisionAction.WATCH_SIGNAL, 0.0, []


def _write_decision_parquet(decisions: list[StrategyDecision], output_path: Path) -> None:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to write decisions.") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "symbol": decision.symbol,
                "decision_date": decision.decision_date,
                "source_signal_id": decision.source_signal_id,
                "position_id": decision.position_id,
                "action": decision.action.value,
                "score": decision.score,
                "suggested_position_ratio": decision.suggested_position_ratio,
                "reasons": decision.reasons,
                "risks": decision.risks,
                "strategy_version": decision.strategy_version,
                "created_at": decision.created_at,
            }
            for decision in decisions
        ],
        columns=DECISION_COLUMNS,
    ).to_parquet(output_path, index=False)


def _decision_values(decision: StrategyDecision) -> tuple[object, ...]:
    return (
        decision.symbol,
        decision.decision_date,
        decision.source_signal_id,
        decision.position_id,
        decision.action.value,
        decision.score,
        decision.suggested_position_ratio,
        decision.reasons,
        decision.risks,
        decision.strategy_version,
        decision.created_at,
    )


def _row_to_decision(row: object) -> StrategyDecision:
    return StrategyDecision(
        id=row["id"],
        symbol=row["symbol"],
        decision_date=row["decision_date"],
        source_signal_id=row["source_signal_id"],
        position_id=row["position_id"],
        action=DecisionAction(row["action"]),
        score=row["score"],
        suggested_position_ratio=row["suggested_position_ratio"],
        reasons=row["reasons"],
        risks=row["risks"],
        strategy_version=row["strategy_version"],
        created_at=row["created_at"],
    )


def _join_reasons(*values: object) -> str | None:
    reasons: list[str] = []
    for value in values:
        if isinstance(value, list):
            reasons.extend(value)
        else:
            reasons.extend(_split_reasons(value))
    return ",".join(dict.fromkeys(reasons)) or None


def _split_reasons(value: object) -> list[str]:
    if value is None:
        return []
    text = str(value)
    if text in {"", "nan", "<NA>"}:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _action_reason(action: DecisionAction) -> str:
    return action.value.lower()


def _action_rank(action: DecisionAction) -> int:
    return {
        DecisionAction.REDUCE_POSITION: 0,
        DecisionAction.OPEN_POSITION: 1,
        DecisionAction.HOLD_POSITION: 2,
        DecisionAction.WATCH_POSITION: 3,
        DecisionAction.WATCH_SIGNAL: 4,
        DecisionAction.SKIP_SIGNAL: 5,
    }[action]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
