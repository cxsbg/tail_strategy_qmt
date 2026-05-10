from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, Callable

from qmt.trader import QmtTrader
from trading.cycle import TradingCycleResult, run_trading_cycle
from trading.sync import BrokerSyncResult, sync_broker_executions


@dataclass(frozen=True)
class IntradayMonitorConfig:
    enabled: bool = True
    sell_start_time: str = "09:30"
    tail_start_time: str = "14:30"
    order_start_time: str = "14:50"
    stop_time: str = "15:01"
    sell_poll_seconds: int = 60
    tail_poll_seconds: int = 30
    execution_poll_seconds: int = 10


@dataclass(frozen=True)
class IntradayMonitorEvent:
    timestamp: str
    phase: str
    action: str
    status: str
    message: str


@dataclass(frozen=True)
class IntradayMonitorResult:
    trade_date: str
    events: tuple[IntradayMonitorEvent, ...]
    report_path: Path | None

    @property
    def failed_count(self) -> int:
        return sum(event.status == "FAILED" for event in self.events)

    @property
    def cycle_count(self) -> int:
        return sum(event.action == "trading_cycle" for event in self.events)

    @property
    def sync_count(self) -> int:
        return sum(event.action == "broker_sync" for event in self.events)


def run_intraday_monitor(
    *,
    db_path: str | Path,
    parquet_root: str | Path,
    strategy_config: dict[str, Any],
    trade_date: str,
    strategy_version: str = "rule-v0",
    submit: bool = False,
    apply_positions: bool = False,
    trader: QmtTrader | None = None,
    report_path: str | Path | None = "outputs/intraday_monitor_report.md",
    max_iterations: int | None = None,
    now_fn: Callable[[], datetime] = datetime.now,
    sleep_fn: Callable[[float], None] = sleep,
    cycle_runner: Callable[..., TradingCycleResult] = run_trading_cycle,
    sync_runner: Callable[..., BrokerSyncResult] = sync_broker_executions,
) -> IntradayMonitorResult:
    config = monitor_config_from_strategy(strategy_config)
    events: list[IntradayMonitorEvent] = []
    if not config.enabled:
        events.append(_event(now_fn(), "DISABLED", "monitor", "SKIPPED", "monitor_disabled"))
        return _finish(trade_date=trade_date, events=events, report_path=report_path)

    mode = str(strategy_config.get("trading", {}).get("mode", "paper"))
    cycle_done = False
    iterations = 0
    while True:
        current = now_fn()
        phase = _phase(current, config)
        if phase == "CLOSED":
            events.append(_event(current, phase, "monitor", "SUCCESS", "market_closed"))
            break
        if max_iterations is not None and iterations >= max_iterations:
            events.append(_event(current, phase, "monitor", "SUCCESS", "max_iterations_reached"))
            break
        iterations += 1

        if phase == "WAIT":
            events.append(_event(current, phase, "monitor", "SUCCESS", "waiting_for_sell_window"))
        elif phase == "SELL":
            events.append(_event(current, phase, "sell_monitor", "SUCCESS", "sell_window_tick"))
            if mode == "live" and trader is not None:
                events.append(_sync_event(current, phase, db_path, trader, trade_date, apply_positions, strategy_version, sync_runner))
        elif phase == "TAIL":
            events.append(_event(current, phase, "tail_monitor", "SUCCESS", "tail_window_tick"))
        elif phase == "EXECUTION":
            if not cycle_done:
                events.append(
                    _cycle_event(
                        current=current,
                        db_path=db_path,
                        parquet_root=parquet_root,
                        strategy_config=strategy_config,
                        trade_date=trade_date,
                        strategy_version=strategy_version,
                        submit=submit,
                        apply_positions=apply_positions,
                        trader=trader,
                        cycle_runner=cycle_runner,
                    )
                )
                cycle_done = True
            elif mode == "live" and trader is not None:
                events.append(_sync_event(current, phase, db_path, trader, trade_date, apply_positions, strategy_version, sync_runner))
            else:
                events.append(_event(current, phase, "broker_sync", "SKIPPED", "not_live_or_no_trader"))

        sleep_fn(_poll_seconds(phase, config))

    return _finish(trade_date=trade_date, events=events, report_path=report_path)


def monitor_config_from_strategy(strategy_config: dict[str, Any]) -> IntradayMonitorConfig:
    raw = strategy_config.get("monitor", {})
    if not isinstance(raw, dict):
        raw = {}
    return IntradayMonitorConfig(
        enabled=bool(raw.get("enabled", True)),
        sell_start_time=str(raw.get("sell_start_time", "09:30")),
        tail_start_time=str(raw.get("tail_start_time", "14:30")),
        order_start_time=str(raw.get("order_start_time", "14:50")),
        stop_time=str(raw.get("stop_time", "15:01")),
        sell_poll_seconds=max(1, int(raw.get("sell_poll_seconds", 60))),
        tail_poll_seconds=max(1, int(raw.get("tail_poll_seconds", 30))),
        execution_poll_seconds=max(1, int(raw.get("execution_poll_seconds", 10))),
    )


def render_intraday_monitor_markdown(result: IntradayMonitorResult) -> str:
    lines = [
        f"# Intraday Monitor Report - {result.trade_date}",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Events: {len(result.events)}",
        f"- Trading cycles: {result.cycle_count}",
        f"- Broker syncs: {result.sync_count}",
        f"- Failed: {result.failed_count}",
        "",
        "## Events",
        "",
        "| Time | Phase | Action | Status | Message |",
        "|---|---|---|---|---|",
    ]
    for event in result.events:
        lines.append(
            f"| {event.timestamp} | {event.phase} | {event.action} | {event.status} | {_escape_markdown_cell(event.message)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _cycle_event(
    *,
    current: datetime,
    db_path: str | Path,
    parquet_root: str | Path,
    strategy_config: dict[str, Any],
    trade_date: str,
    strategy_version: str,
    submit: bool,
    apply_positions: bool,
    trader: QmtTrader | None,
    cycle_runner: Callable[..., TradingCycleResult],
) -> IntradayMonitorEvent:
    try:
        result = cycle_runner(
            db_path=db_path,
            parquet_root=parquet_root,
            strategy_config=strategy_config,
            trade_date=trade_date,
            strategy_version=strategy_version,
            submit=submit,
            sync_broker=submit,
            apply_positions=apply_positions,
            sync_attempts=1,
            sync_interval_seconds=0,
            trader=trader,
        )
    except Exception as exc:
        return _event(current, "EXECUTION", "trading_cycle", "FAILED", str(exc))
    return _event(
        current,
        "EXECUTION",
        "trading_cycle",
        "SUCCESS",
        f"drafts={result.pre_trade.draft_count}; submitted={result.pre_trade.submitted_count + result.pre_trade.paper_submitted_count}",
    )


def _sync_event(
    current: datetime,
    phase: str,
    db_path: str | Path,
    trader: QmtTrader,
    trade_date: str,
    apply_positions: bool,
    strategy_version: str,
    sync_runner: Callable[..., BrokerSyncResult],
) -> IntradayMonitorEvent:
    try:
        result = sync_runner(
            db_path=db_path,
            trader=trader,
            trade_date=trade_date,
            apply_positions=apply_positions,
            strategy_version=strategy_version,
        )
    except Exception as exc:
        return _event(current, phase, "broker_sync", "FAILED", str(exc))
    return _event(
        current,
        phase,
        "broker_sync",
        "SUCCESS",
        f"orders={result.order_upsert_count}; fills={result.fill_inserted_count}; applications={result.position_application_count}",
    )


def _finish(
    *,
    trade_date: str,
    events: list[IntradayMonitorEvent],
    report_path: str | Path | None,
) -> IntradayMonitorResult:
    output = Path(report_path) if report_path is not None else None
    result = IntradayMonitorResult(trade_date=trade_date, events=tuple(events), report_path=output)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_intraday_monitor_markdown(result), encoding="utf-8")
    return result


def _phase(current: datetime, config: IntradayMonitorConfig) -> str:
    minute = current.strftime("%H:%M")
    if minute < config.sell_start_time:
        return "WAIT"
    if minute < config.tail_start_time:
        return "SELL"
    if minute < config.order_start_time:
        return "TAIL"
    if minute < config.stop_time:
        return "EXECUTION"
    return "CLOSED"


def _poll_seconds(phase: str, config: IntradayMonitorConfig) -> int:
    if phase == "TAIL":
        return config.tail_poll_seconds
    if phase == "EXECUTION":
        return config.execution_poll_seconds
    return config.sell_poll_seconds


def _event(current: datetime, phase: str, action: str, status: str, message: str) -> IntradayMonitorEvent:
    return IntradayMonitorEvent(
        timestamp=current.isoformat(timespec="seconds"),
        phase=phase,
        action=action,
        status=status,
        message=message,
    )
