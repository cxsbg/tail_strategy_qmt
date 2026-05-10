from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any

from qmt.trader import QmtTrader
from trading.pre_trade import PreTradeResult, run_pre_trade
from trading.run_log import TradingCycleRunRepository, build_run_record
from trading.sync import BrokerSyncResult, sync_broker_executions


@dataclass(frozen=True)
class TradingCycleResult:
    date: str
    pre_trade: PreTradeResult
    broker_syncs: tuple[BrokerSyncResult, ...]
    report_path: Path | None
    db_path: Path
    run_id: int | None = None

    @property
    def sync_count(self) -> int:
        return len(self.broker_syncs)

    @property
    def total_fill_inserted_count(self) -> int:
        return sum(item.fill_inserted_count for item in self.broker_syncs)

    @property
    def total_position_application_count(self) -> int:
        return sum(item.position_application_count for item in self.broker_syncs)


def run_trading_cycle(
    *,
    db_path: str | Path,
    parquet_root: str | Path,
    strategy_config: dict[str, Any],
    trade_date: str,
    strategy_version: str = "rule-v0",
    report_path: str | Path | None = "outputs/pre_trade_report.md",
    cycle_report_path: str | Path | None = "outputs/trading_cycle_report.md",
    submit: bool = True,
    sync_broker: bool = True,
    apply_positions: bool = False,
    sync_attempts: int = 1,
    sync_interval_seconds: float = 0.0,
    trader: QmtTrader | None = None,
    record_run: bool = True,
) -> TradingCycleResult:
    started_at = datetime.now()
    mode = str(strategy_config.get("trading", {}).get("mode", "paper"))
    run_repository = TradingCycleRunRepository(db_path) if record_run else None
    try:
        pre_trade = run_pre_trade(
            db_path=db_path,
            parquet_root=parquet_root,
            strategy_config=strategy_config,
            trade_date=trade_date,
            strategy_version=strategy_version,
            report_path=report_path,
            submit=submit,
            trader=trader,
        )

        sync_results: list[BrokerSyncResult] = []
        if sync_broker and submit and mode == "live":
            if trader is None:
                raise ValueError("A QmtTrader is required to sync live broker executions.")
            attempts = max(1, int(sync_attempts))
            for index in range(attempts):
                if index > 0 and sync_interval_seconds > 0:
                    sleep(sync_interval_seconds)
                sync_results.append(
                    sync_broker_executions(
                        db_path=db_path,
                        trader=trader,
                        trade_date=trade_date,
                        apply_positions=apply_positions,
                        strategy_version=strategy_version,
                    )
                )

        output_report_path = Path(cycle_report_path) if cycle_report_path is not None else None
        result = TradingCycleResult(
            date=trade_date,
            pre_trade=pre_trade,
            broker_syncs=tuple(sync_results),
            report_path=output_report_path,
            db_path=Path(db_path),
        )
        if output_report_path is not None:
            from reports.trading_cycle import build_trading_cycle_report

            build_trading_cycle_report(result=result, markdown_path=output_report_path)
        run_id = _record_success(
            repository=run_repository,
            result=result,
            strategy_version=strategy_version,
            mode=mode,
            started_at=started_at,
        )
        return TradingCycleResult(
            date=result.date,
            pre_trade=result.pre_trade,
            broker_syncs=result.broker_syncs,
            report_path=result.report_path,
            db_path=result.db_path,
            run_id=run_id,
        )
    except Exception as exc:
        _record_failure(
            repository=run_repository,
            trade_date=trade_date,
            strategy_version=strategy_version,
            mode=mode,
            started_at=started_at,
            message=str(exc),
        )
        raise


def _record_success(
    *,
    repository: TradingCycleRunRepository | None,
    result: TradingCycleResult,
    strategy_version: str,
    mode: str,
    started_at: datetime,
) -> int | None:
    if repository is None:
        return None
    status = "WARN" if result.pre_trade.blocked_count or result.pre_trade.rejected_count else "SUCCESS"
    run = build_run_record(
        trade_date=result.date,
        strategy_version=strategy_version,
        mode=mode,
        status=status,
        started_at=started_at,
        finished_at=datetime.now(),
        draft_count=result.pre_trade.draft_count,
        blocked_count=result.pre_trade.blocked_count,
        submitted_count=result.pre_trade.paper_submitted_count + result.pre_trade.submitted_count,
        rejected_count=result.pre_trade.rejected_count,
        sync_count=result.sync_count,
        fill_inserted_count=result.total_fill_inserted_count,
        position_application_count=result.total_position_application_count,
        report_path=result.report_path,
        message=None if status == "SUCCESS" else "blocked_or_rejected_orders",
    )
    return repository.insert_run(run)


def _record_failure(
    *,
    repository: TradingCycleRunRepository | None,
    trade_date: str,
    strategy_version: str,
    mode: str,
    started_at: datetime,
    message: str,
) -> None:
    if repository is None:
        return
    repository.insert_run(
        build_run_record(
            trade_date=trade_date,
            strategy_version=strategy_version,
            mode=mode,
            status="FAILED",
            started_at=started_at,
            finished_at=datetime.now(),
            message=message,
        )
    )
