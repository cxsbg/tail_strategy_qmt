from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from trading.run_log import TradingCycleRun, TradingCycleRunRepository


@dataclass(frozen=True)
class TradingRunHealthCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class TradingRunHealthResult:
    checks: tuple[TradingRunHealthCheck, ...]
    latest_run: TradingCycleRun | None
    markdown_path: Path | None

    @property
    def failed_count(self) -> int:
        return sum(check.status == "FAIL" for check in self.checks)

    @property
    def warning_count(self) -> int:
        return sum(check.status == "WARN" for check in self.checks)

    @property
    def passed_count(self) -> int:
        return sum(check.status == "PASS" for check in self.checks)

    @property
    def ok(self) -> bool:
        return self.failed_count == 0


def check_trading_run_health(
    *,
    db_path: str | Path,
    trade_date: str | None = None,
    max_age_hours: float | None = None,
    allow_skipped: bool = False,
    output_path: str | Path | None = "outputs/trading_run_health.md",
) -> TradingRunHealthResult:
    repository = TradingCycleRunRepository(db_path)
    runs = repository.list_runs(trade_date=trade_date, limit=1)
    checks: list[TradingRunHealthCheck] = []
    latest_run = runs[0] if runs else None

    if latest_run is None:
        label = trade_date or "latest"
        checks.append(_check("trading_run.exists", "FAIL", f"No trading cycle run found for {label}."))
    else:
        checks.append(_check("trading_run.exists", "PASS", f"run_id={latest_run.id}; date={latest_run.trade_date}"))
        checks.append(_status_check(latest_run, allow_skipped=allow_skipped))
        if max_age_hours is not None:
            checks.append(_age_check(latest_run, max_age_hours=max_age_hours))

    markdown_path = Path(output_path) if output_path is not None else None
    result = TradingRunHealthResult(
        checks=tuple(checks),
        latest_run=latest_run,
        markdown_path=markdown_path,
    )
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_trading_run_health_markdown(result), encoding="utf-8")
    return result


def render_trading_run_health_markdown(result: TradingRunHealthResult) -> str:
    lines = [
        "# Trading Run Health",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- PASS: {result.passed_count}",
        f"- WARN: {result.warning_count}",
        f"- FAIL: {result.failed_count}",
        "",
    ]
    if result.latest_run is not None:
        run = result.latest_run
        lines.extend(
            [
                "## Latest Run",
                "",
                f"- Run ID: {run.id}",
                f"- Date: {run.trade_date}",
                f"- Status: {run.status}",
                f"- Started: {run.started_at}",
                f"- Finished: {run.finished_at or ''}",
                f"- Message: {run.message or ''}",
                "",
            ]
        )
    lines.extend(
        [
            "## Checks",
            "",
            "| Status | Check | Detail |",
            "|---|---|---|",
        ]
    )
    for check in result.checks:
        lines.append(f"| {check.status} | {check.name} | {_escape(check.detail)} |")
    lines.append("")
    return "\n".join(lines)


def _status_check(run: TradingCycleRun, *, allow_skipped: bool) -> TradingRunHealthCheck:
    if run.status == "SUCCESS":
        return _check("trading_run.status", "PASS", "SUCCESS")
    if run.status == "WARN":
        return _check("trading_run.status", "WARN", run.message or "WARN")
    if run.status == "SKIPPED" and allow_skipped:
        return _check("trading_run.status", "PASS", "SKIPPED allowed")
    if run.status == "SKIPPED":
        return _check("trading_run.status", "WARN", run.message or "SKIPPED")
    return _check("trading_run.status", "FAIL", f"{run.status}: {run.message or ''}".strip())


def _age_check(run: TradingCycleRun, *, max_age_hours: float) -> TradingRunHealthCheck:
    timestamp = run.finished_at or run.started_at
    try:
        run_time = datetime.fromisoformat(timestamp)
    except ValueError:
        return _check("trading_run.age", "WARN", f"Cannot parse run timestamp: {timestamp}")
    age_hours = (datetime.now() - run_time).total_seconds() / 3600
    if age_hours <= max_age_hours:
        return _check("trading_run.age", "PASS", f"age_hours={age_hours:.2f}; max={max_age_hours:.2f}")
    return _check("trading_run.age", "FAIL", f"age_hours={age_hours:.2f}; max={max_age_hours:.2f}")


def _check(name: str, status: str, detail: str) -> TradingRunHealthCheck:
    return TradingRunHealthCheck(name=name, status=status, detail=detail)


def _escape(value: str) -> str:
    return value.replace("|", "\\|")
