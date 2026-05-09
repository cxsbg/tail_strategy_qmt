from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from position import Position, PositionAction, PositionRepository, PositionService, PositionStatus
from position.service import PositionStateError
from storage.parquet import ParquetStorage
from storage.sqlite import SQLiteStore
from strategy.decisions import DecisionAction, DecisionRepository, StrategyDecision
from utils.exceptions import StorageError, TailStrategyError


class DecisionApplicationStatus(str, Enum):
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    DRY_RUN = "DRY_RUN"
    ALREADY_APPLIED = "ALREADY_APPLIED"


@dataclass(frozen=True)
class DecisionApplication:
    id: int | None
    decision_id: int
    symbol: str
    decision_date: str
    action: DecisionAction
    status: DecisionApplicationStatus
    message: str | None
    created_at: str | None


@dataclass(frozen=True)
class DecisionApplyResult:
    date: str
    decision_count: int
    applied_count: int
    skipped_count: int
    failed_count: int
    dry_run_count: int
    already_applied_count: int
    applications: list[DecisionApplication]
    db_path: Path


class DecisionApplicationRepository:
    def __init__(self, store: SQLiteStore | str | Path) -> None:
        self.store = store if isinstance(store, SQLiteStore) else SQLiteStore(store)
        self.store.initialize()

    def get_by_decision_id(self, decision_id: int) -> DecisionApplication | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM decision_applications WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        return _row_to_application(row) if row else None

    def insert_application(self, application: DecisionApplication) -> int:
        sql = """
        INSERT INTO decision_applications (
            decision_id, symbol, decision_date, action, status, message, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(decision_id) DO UPDATE SET
            symbol = excluded.symbol,
            decision_date = excluded.decision_date,
            action = excluded.action,
            status = excluded.status,
            message = excluded.message,
            created_at = excluded.created_at
        """
        with self.store.connect() as conn:
            cursor = conn.execute(sql, _application_values(application))
            conn.commit()
            row = conn.execute(
                "SELECT id FROM decision_applications WHERE decision_id = ?",
                (application.decision_id,),
            ).fetchone()
            return int(row["id"])

    def list_applications(
        self,
        *,
        decision_date: str | None = None,
        status: DecisionApplicationStatus | None = None,
    ) -> list[DecisionApplication]:
        clauses: list[str] = []
        params: list[object] = []
        if decision_date is not None:
            clauses.append("decision_date = ?")
            params.append(decision_date)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)

        sql = "SELECT * FROM decision_applications"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        with self.store.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_application(row) for row in rows]


def apply_decisions_to_positions(
    *,
    db_path: str | Path,
    parquet_root: str | Path,
    strategy_config: dict[str, Any],
    decision_date: str,
    strategy_version: str = "rule-v0",
    dry_run: bool = False,
) -> DecisionApplyResult:
    decision_repository = DecisionRepository(db_path)
    application_repository = DecisionApplicationRepository(db_path)
    position_repository = PositionRepository(db_path)
    position_service = PositionService(position_repository, strategy_version=strategy_version)
    storage = ParquetStorage(parquet_root)

    decisions = decision_repository.list_decisions(
        decision_date=decision_date,
        strategy_version=strategy_version,
    )
    applications: list[DecisionApplication] = []

    for decision in decisions:
        applications.append(
            _apply_one_decision(
                decision=decision,
                application_repository=application_repository,
                position_repository=position_repository,
                position_service=position_service,
                storage=storage,
                strategy_config=strategy_config,
                dry_run=dry_run,
            )
        )

    return DecisionApplyResult(
        date=decision_date,
        decision_count=len(decisions),
        applied_count=_count_status(applications, DecisionApplicationStatus.APPLIED),
        skipped_count=_count_status(applications, DecisionApplicationStatus.SKIPPED),
        failed_count=_count_status(applications, DecisionApplicationStatus.FAILED),
        dry_run_count=_count_status(applications, DecisionApplicationStatus.DRY_RUN),
        already_applied_count=_count_status(applications, DecisionApplicationStatus.ALREADY_APPLIED),
        applications=applications,
        db_path=Path(db_path),
    )


def _apply_one_decision(
    *,
    decision: StrategyDecision,
    application_repository: DecisionApplicationRepository,
    position_repository: PositionRepository,
    position_service: PositionService,
    storage: ParquetStorage,
    strategy_config: dict[str, Any],
    dry_run: bool,
) -> DecisionApplication:
    if decision.id is None:
        return _transient_application(
            decision=decision,
            status=DecisionApplicationStatus.FAILED,
            message="decision_id_missing",
        )

    existing = application_repository.get_by_decision_id(decision.id)
    if existing is not None and existing.status in {
        DecisionApplicationStatus.APPLIED,
        DecisionApplicationStatus.SKIPPED,
    }:
        return DecisionApplication(
            id=existing.id,
            decision_id=existing.decision_id,
            symbol=existing.symbol,
            decision_date=existing.decision_date,
            action=existing.action,
            status=DecisionApplicationStatus.ALREADY_APPLIED,
            message=existing.message,
            created_at=existing.created_at,
        )

    try:
        status, message = _apply_action(
            decision=decision,
            position_repository=position_repository,
            position_service=position_service,
            storage=storage,
            strategy_config=strategy_config,
            dry_run=dry_run,
        )
    except (StorageError, PositionStateError, TailStrategyError, ValueError) as exc:
        status = DecisionApplicationStatus.FAILED
        message = str(exc)

    application = _transient_application(decision=decision, status=status, message=message)
    if not dry_run:
        application_id = application_repository.insert_application(application)
        application = DecisionApplication(
            id=application_id,
            decision_id=application.decision_id,
            symbol=application.symbol,
            decision_date=application.decision_date,
            action=application.action,
            status=application.status,
            message=application.message,
            created_at=application.created_at,
        )
    return application


def _apply_action(
    *,
    decision: StrategyDecision,
    position_repository: PositionRepository,
    position_service: PositionService,
    storage: ParquetStorage,
    strategy_config: dict[str, Any],
    dry_run: bool,
) -> tuple[DecisionApplicationStatus, str]:
    if decision.action in {DecisionAction.WATCH_SIGNAL, DecisionAction.SKIP_SIGNAL}:
        return _skip_or_dry_run(dry_run, "no_position_change")

    position = _resolve_open_position(decision, position_repository)

    if decision.action == DecisionAction.OPEN_POSITION:
        if position is not None:
            return _skip_or_dry_run(dry_run, "open_position_exists")
        price = _daily_close(storage, decision.symbol, decision.decision_date)
        ratio, max_ratio = _position_ratios(decision, strategy_config)
        if dry_run:
            return DecisionApplicationStatus.DRY_RUN, f"would_open_position price={price} ratio={ratio}"
        position_service.open_position(
            symbol=decision.symbol,
            entry_date=decision.decision_date,
            entry_price=price,
            position_ratio=ratio,
            max_position_ratio=max_ratio,
            reason=_decision_reason(decision),
            signal_score=decision.score,
        )
        return DecisionApplicationStatus.APPLIED, f"opened_position price={price} ratio={ratio}"

    if position is None:
        return _skip_or_dry_run(dry_run, "open_position_not_found")

    if decision.action == DecisionAction.HOLD_POSITION:
        if dry_run:
            return DecisionApplicationStatus.DRY_RUN, f"would_mark_hold position_id={position.id}"
        position_service.mark_status(
            position.id,
            status=PositionStatus.HOLD,
            action=PositionAction.HOLD,
            reason=_decision_reason(decision),
        )
        return DecisionApplicationStatus.APPLIED, f"marked_hold position_id={position.id}"

    if decision.action == DecisionAction.WATCH_POSITION:
        if dry_run:
            return DecisionApplicationStatus.DRY_RUN, f"would_mark_watch position_id={position.id}"
        position_service.mark_status(
            position.id,
            status=PositionStatus.WATCH,
            action=PositionAction.WATCH,
            reason=_decision_reason(decision),
        )
        return DecisionApplicationStatus.APPLIED, f"marked_watch position_id={position.id}"

    if decision.action == DecisionAction.REDUCE_POSITION:
        price = _daily_close(storage, decision.symbol, decision.decision_date)
        if dry_run:
            return DecisionApplicationStatus.DRY_RUN, (
                f"would_reduce_position position_id={position.id} price={price}"
            )
        position_service.reduce_position(
            position.id,
            reduce_ratio=position.position_ratio,
            price=price,
            trade_date=decision.decision_date,
            reason=_decision_reason(decision),
        )
        return DecisionApplicationStatus.APPLIED, f"reduced_position position_id={position.id} price={price}"

    raise TailStrategyError(f"Unsupported decision action: {decision.action.value}")


def _resolve_open_position(
    decision: StrategyDecision,
    position_repository: PositionRepository,
) -> Position | None:
    if decision.position_id is not None:
        position = position_repository.get_position(decision.position_id)
        if position is not None and position.status != PositionStatus.CLOSED:
            return position
    return position_repository.get_open_position_by_symbol(decision.symbol)


def _daily_close(storage: ParquetStorage, symbol: str, decision_date: str) -> float:
    frame = storage.read_frame("daily", symbol)
    if "date" not in frame.columns or "close" not in frame.columns:
        raise StorageError(f"Daily cache for {symbol} must contain date and close columns.")
    rows = frame.loc[frame["date"].astype(str) == str(decision_date)]
    if rows.empty:
        raise StorageError(f"No daily close found for {symbol} on {decision_date}.")
    close = rows.iloc[-1]["close"]
    if close is None:
        raise StorageError(f"Daily close is empty for {symbol} on {decision_date}.")
    return float(close)


def _position_ratios(
    decision: StrategyDecision,
    strategy_config: dict[str, Any],
) -> tuple[float, float]:
    position_config = strategy_config.get("position", {})
    max_ratio = float(position_config.get("max_single_stock_ratio", 1.0))
    fallback_ratio = float(position_config.get("initial_position_ratio", max_ratio))
    raw_ratio = decision.suggested_position_ratio
    ratio = float(raw_ratio if raw_ratio is not None and raw_ratio > 0 else fallback_ratio)
    if ratio <= 0:
        raise ValueError("Position ratio must be positive.")
    if max_ratio <= 0:
        raise ValueError("max_single_stock_ratio must be positive.")
    return min(ratio, max_ratio), max_ratio


def _decision_reason(decision: StrategyDecision) -> str | None:
    parts = [decision.reasons, decision.risks]
    values = [str(part) for part in parts if part not in {None, ""}]
    return ",".join(values) or None


def _skip_or_dry_run(dry_run: bool, message: str) -> tuple[DecisionApplicationStatus, str]:
    if dry_run:
        return DecisionApplicationStatus.DRY_RUN, f"would_skip:{message}"
    return DecisionApplicationStatus.SKIPPED, message


def _transient_application(
    *,
    decision: StrategyDecision,
    status: DecisionApplicationStatus,
    message: str | None,
) -> DecisionApplication:
    return DecisionApplication(
        id=None,
        decision_id=int(decision.id or 0),
        symbol=decision.symbol,
        decision_date=decision.decision_date,
        action=decision.action,
        status=status,
        message=message,
        created_at=_now(),
    )


def _application_values(application: DecisionApplication) -> tuple[object, ...]:
    return (
        application.decision_id,
        application.symbol,
        application.decision_date,
        application.action.value,
        application.status.value,
        application.message,
        application.created_at,
    )


def _row_to_application(row: object) -> DecisionApplication:
    return DecisionApplication(
        id=row["id"],
        decision_id=row["decision_id"],
        symbol=row["symbol"],
        decision_date=row["decision_date"],
        action=DecisionAction(row["action"]),
        status=DecisionApplicationStatus(row["status"]),
        message=row["message"],
        created_at=row["created_at"],
    )


def _count_status(
    applications: list[DecisionApplication],
    status: DecisionApplicationStatus,
) -> int:
    return sum(1 for application in applications if application.status == status)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
