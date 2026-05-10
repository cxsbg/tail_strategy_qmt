from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from trading.run_log import TradingCycleRun, TradingCycleRunRepository


@dataclass(frozen=True)
class TradingRunReportResult:
    markdown_path: Path
    run_count: int
    failed_count: int
    warning_count: int


def build_trading_run_report(
    *,
    db_path: str | Path,
    markdown_path: str | Path,
    limit: int = 20,
) -> TradingRunReportResult:
    runs = TradingCycleRunRepository(db_path).list_runs(limit=limit)
    output = Path(markdown_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_trading_run_markdown(runs), encoding="utf-8")
    return TradingRunReportResult(
        markdown_path=output,
        run_count=len(runs),
        failed_count=sum(run.status == "FAILED" for run in runs),
        warning_count=sum(run.status == "WARN" for run in runs),
    )


def render_trading_run_markdown(runs: list[TradingCycleRun]) -> str:
    lines = [
        "# Trading Run Monitor",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Runs: {len(runs)}",
        f"- Failed: {sum(run.status == 'FAILED' for run in runs)}",
        f"- Warnings: {sum(run.status == 'WARN' for run in runs)}",
        "",
        "## Recent Runs",
        "",
        "| Status | Date | Mode | Started | Duration | Drafts | Submitted | Syncs | Fills | Position Apps | Message |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    if not runs:
        lines.append("| - | - | - | - | - | - | - | - | - | - | no_runs |")
    for run in runs:
        lines.append(
            "| {status} | {date} | {mode} | {started} | {duration} | {drafts} | {submitted} | "
            "{syncs} | {fills} | {apps} | {message} |".format(
                status=run.status,
                date=run.trade_date,
                mode=run.mode or "",
                started=run.started_at,
                duration=_fmt_duration(run.duration_seconds),
                drafts=run.draft_count,
                submitted=run.submitted_count,
                syncs=run.sync_count,
                fills=run.fill_inserted_count,
                apps=run.position_application_count,
                message=_escape(run.message or ""),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _fmt_duration(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}s"


def _escape(value: str) -> str:
    return value.replace("|", "\\|")
