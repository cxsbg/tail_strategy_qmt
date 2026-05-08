from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from utils.exceptions import StorageError


@dataclass(frozen=True)
class DailyReportResult:
    markdown_path: Path
    csv_path: Path
    report_date: str
    candidate_count: int
    diagnostics_count: int


def build_daily_report(
    *,
    candidates_path: str | Path,
    diagnostics_path: str | Path,
    reason_summary_path: str | Path,
    sqlite_path: str | Path,
    markdown_path: str | Path,
    csv_path: str | Path,
    report_date: str | None = None,
) -> DailyReportResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build daily reports.") from exc

    candidates = _read_parquet_or_empty(candidates_path)
    diagnostics = _read_parquet_or_empty(diagnostics_path)
    reason_summary = _read_csv_or_empty(reason_summary_path)
    date = report_date or _infer_report_date(candidates, diagnostics)
    sync_summary = load_sync_summary(sqlite_path)

    markdown = render_daily_markdown(
        report_date=date,
        candidates=candidates,
        diagnostics=diagnostics,
        reason_summary=reason_summary,
        sync_summary=sync_summary,
    )

    csv_output = _candidate_csv_frame(candidates, diagnostics, pd)
    markdown_output = Path(markdown_path)
    csv_path_output = Path(csv_path)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    csv_path_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(markdown, encoding="utf-8")
    csv_output.to_csv(csv_path_output, index=False, encoding="utf-8-sig")

    return DailyReportResult(
        markdown_path=markdown_output,
        csv_path=csv_path_output,
        report_date=date,
        candidate_count=len(candidates),
        diagnostics_count=len(diagnostics),
    )


def load_sync_summary(sqlite_path: str | Path) -> list[dict[str, object]]:
    path = Path(sqlite_path)
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT symbol, period, start_date, end_date, last_sync_time, source, status, error_message
            FROM data_sync_status
            ORDER BY last_sync_time DESC, symbol ASC
            LIMIT 20
            """
        ).fetchall()
    return [dict(row) for row in rows]


def render_daily_markdown(
    *,
    report_date: str,
    candidates: object,
    diagnostics: object,
    reason_summary: object,
    sync_summary: list[dict[str, object]],
) -> str:
    lines: list[str] = [
        f"# Tail Strategy Daily Report - {report_date}",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Candidates: {len(candidates)}",
        f"- Diagnosed symbols: {len(diagnostics)}",
        f"- Passed diagnostics: {_passed_count(diagnostics)}",
        f"- Failed diagnostics: {max(0, len(diagnostics) - _passed_count(diagnostics))}",
        "",
        "## Candidates",
        "",
    ]
    lines.extend(_candidate_lines(candidates))
    lines.extend(["", "## Failure Reasons", ""])
    lines.extend(_reason_lines(reason_summary))
    lines.extend(["", "## Sync Status", ""])
    lines.extend(_sync_lines(sync_summary))
    lines.append("")
    return "\n".join(lines)


def _read_parquet_or_empty(path: str | Path) -> object:
    import pandas as pd

    file_path = Path(path)
    if not file_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(file_path)


def _read_csv_or_empty(path: str | Path) -> object:
    import pandas as pd

    file_path = Path(path)
    if not file_path.exists():
        return pd.DataFrame()
    return pd.read_csv(file_path)


def _infer_report_date(candidates: object, diagnostics: object) -> str:
    if not candidates.empty and "date" in candidates.columns:
        return str(candidates["date"].max())
    if not diagnostics.empty and "date" in diagnostics.columns:
        return str(diagnostics["date"].max())
    return datetime.now().strftime("%Y%m%d")


def _candidate_csv_frame(candidates: object, diagnostics: object, pd: object) -> object:
    if not candidates.empty:
        return candidates
    if diagnostics.empty:
        return pd.DataFrame(columns=["symbol", "date", "passed", "failed_reasons"])
    return diagnostics.loc[
        :,
        [
            "symbol",
            "date",
            "passed",
            "failed_reason_count",
            "failed_reasons",
            "close",
            "pct_chg",
            "volume_ratio_5d",
            "close_position_20d",
        ],
    ]


def _candidate_lines(candidates: object) -> list[str]:
    if candidates.empty:
        return ["No candidates for this report date."]
    lines = ["| Symbol | Score | Level | Close | Pct Chg | Volume Ratio | Reasons |"]
    lines.append("|---|---:|---|---:|---:|---:|---|")
    for _, row in candidates.head(20).iterrows():
        lines.append(
            "| {symbol} | {score:.2f} | {level} | {close:.3f} | {pct:.2%} | {volume:.2f} | {reasons} |".format(
                symbol=row["symbol"],
                score=float(row["score"]),
                level=row["candidate_level"],
                close=float(row["close"]),
                pct=float(row["pct_chg"]),
                volume=float(row["volume_ratio_5d"]),
                reasons=row.get("reasons", ""),
            )
        )
    return lines


def _reason_lines(reason_summary: object) -> list[str]:
    if reason_summary.empty:
        return ["No failure reasons recorded."]
    lines = ["| Reason | Count |", "|---|---:|"]
    for _, row in reason_summary.head(20).iterrows():
        lines.append(f"| {row['reason']} | {int(row['count'])} |")
    return lines


def _sync_lines(sync_summary: list[dict[str, object]]) -> list[str]:
    if not sync_summary:
        return ["No sync status records found."]
    lines = ["| Symbol | Period | End Date | Status | Last Sync |", "|---|---|---|---|---|"]
    for row in sync_summary[:10]:
        lines.append(
            "| {symbol} | {period} | {end_date} | {status} | {last_sync_time} |".format(
                symbol=row.get("symbol", ""),
                period=row.get("period", ""),
                end_date=row.get("end_date", ""),
                status=row.get("status", ""),
                last_sync_time=row.get("last_sync_time", ""),
            )
        )
    return lines


def _passed_count(diagnostics: object) -> int:
    if diagnostics.empty or "passed" not in diagnostics.columns:
        return 0
    return int(diagnostics["passed"].sum())
