from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from storage.sqlite import SQLiteStore


@dataclass(frozen=True)
class TradingCycleRun:
    id: int | None
    trade_date: str
    strategy_version: str | None
    mode: str | None
    status: str
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    draft_count: int
    blocked_count: int
    submitted_count: int
    rejected_count: int
    sync_count: int
    fill_inserted_count: int
    position_application_count: int
    report_path: str | None
    message: str | None


class TradingCycleRunRepository:
    def __init__(self, store: SQLiteStore | str | Path) -> None:
        self.store = store if isinstance(store, SQLiteStore) else SQLiteStore(store)
        self.store.initialize()

    def insert_run(self, run: TradingCycleRun) -> int:
        sql = """
        INSERT INTO trading_cycle_runs (
            trade_date, strategy_version, mode, status, started_at, finished_at,
            duration_seconds, draft_count, blocked_count, submitted_count,
            rejected_count, sync_count, fill_inserted_count, position_application_count,
            report_path, message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.store.connect() as conn:
            cursor = conn.execute(sql, _run_values(run))
            conn.commit()
            return int(cursor.lastrowid)

    def list_runs(
        self,
        *,
        trade_date: str | None = None,
        limit: int | None = None,
    ) -> list[TradingCycleRun]:
        clauses: list[str] = []
        params: list[object] = []
        if trade_date is not None:
            clauses.append("trade_date = ?")
            params.append(trade_date)
        sql = "SELECT * FROM trading_cycle_runs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.store.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_run(row) for row in rows]


def build_run_record(
    *,
    trade_date: str,
    strategy_version: str | None,
    mode: str | None,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    draft_count: int = 0,
    blocked_count: int = 0,
    submitted_count: int = 0,
    rejected_count: int = 0,
    sync_count: int = 0,
    fill_inserted_count: int = 0,
    position_application_count: int = 0,
    report_path: str | Path | None = None,
    message: str | None = None,
) -> TradingCycleRun:
    return TradingCycleRun(
        id=None,
        trade_date=trade_date,
        strategy_version=strategy_version,
        mode=mode,
        status=status,
        started_at=started_at.isoformat(timespec="seconds"),
        finished_at=finished_at.isoformat(timespec="seconds"),
        duration_seconds=(finished_at - started_at).total_seconds(),
        draft_count=draft_count,
        blocked_count=blocked_count,
        submitted_count=submitted_count,
        rejected_count=rejected_count,
        sync_count=sync_count,
        fill_inserted_count=fill_inserted_count,
        position_application_count=position_application_count,
        report_path=str(report_path) if report_path is not None else None,
        message=message,
    )


def _run_values(run: TradingCycleRun) -> tuple[object, ...]:
    return (
        run.trade_date,
        run.strategy_version,
        run.mode,
        run.status,
        run.started_at,
        run.finished_at,
        run.duration_seconds,
        run.draft_count,
        run.blocked_count,
        run.submitted_count,
        run.rejected_count,
        run.sync_count,
        run.fill_inserted_count,
        run.position_application_count,
        run.report_path,
        run.message,
    )


def _row_to_run(row: object) -> TradingCycleRun:
    return TradingCycleRun(
        id=row["id"],
        trade_date=row["trade_date"],
        strategy_version=row["strategy_version"],
        mode=row["mode"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_seconds=row["duration_seconds"],
        draft_count=row["draft_count"],
        blocked_count=row["blocked_count"],
        submitted_count=row["submitted_count"],
        rejected_count=row["rejected_count"],
        sync_count=row["sync_count"],
        fill_inserted_count=row["fill_inserted_count"],
        position_application_count=row["position_application_count"],
        report_path=row["report_path"],
        message=row["message"],
    )
