from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from utils.exceptions import StorageError


@dataclass(frozen=True)
class DecisionReportResult:
    markdown_path: Path
    csv_path: Path
    report_date: str
    decision_count: int


def build_decision_report(
    *,
    decisions_path: str | Path,
    markdown_path: str | Path,
    csv_path: str | Path,
    report_date: str | None = None,
) -> DecisionReportResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build decision reports.") from exc

    decisions = _read_parquet_or_empty(decisions_path)
    date = report_date or _infer_report_date(decisions)
    if not decisions.empty and "decision_date" in decisions.columns:
        decisions = decisions.loc[decisions["decision_date"] == date].copy()

    markdown = render_decision_markdown(report_date=date, decisions=decisions)
    csv_output = decisions if not decisions.empty else pd.DataFrame(columns=_decision_columns())

    markdown_output = Path(markdown_path)
    csv_output_path = Path(csv_path)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    csv_output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(markdown, encoding="utf-8")
    csv_output.to_csv(csv_output_path, index=False, encoding="utf-8-sig")

    return DecisionReportResult(
        markdown_path=markdown_output,
        csv_path=csv_output_path,
        report_date=date,
        decision_count=len(decisions),
    )


def render_decision_markdown(*, report_date: str, decisions: object) -> str:
    lines: list[str] = [
        f"# Tail Strategy Decision Report - {report_date}",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
    ]
    lines.extend(_summary_lines(decisions))
    lines.extend(["", "## Actions", ""])
    lines.extend(_decision_lines(decisions))
    lines.append("")
    return "\n".join(lines)


def _read_parquet_or_empty(path: str | Path) -> object:
    import pandas as pd

    file_path = Path(path)
    if not file_path.exists():
        return pd.DataFrame(columns=_decision_columns())
    return pd.read_parquet(file_path)


def _infer_report_date(decisions: object) -> str:
    if not decisions.empty and "decision_date" in decisions.columns:
        return str(decisions["decision_date"].max())
    return datetime.now().strftime("%Y%m%d")


def _summary_lines(decisions: object) -> list[str]:
    if decisions.empty or "action" not in decisions.columns:
        return ["- Decisions: 0"]
    lines = [f"- Decisions: {len(decisions)}"]
    counts = decisions["action"].value_counts()
    for action, count in counts.items():
        lines.append(f"- {action}: {int(count)}")
    return lines


def _decision_lines(decisions: object) -> list[str]:
    if decisions.empty:
        return ["No decisions for this report date."]
    lines = ["| Symbol | Action | Score | Position Ratio | Reasons | Risks |"]
    lines.append("|---|---|---:|---:|---|---|")
    for _, row in decisions.head(50).iterrows():
        lines.append(
            "| {symbol} | {action} | {score} | {ratio} | {reasons} | {risks} |".format(
                symbol=row.get("symbol", ""),
                action=row.get("action", ""),
                score=_format_float(row.get("score")),
                ratio=_format_float(row.get("suggested_position_ratio")),
                reasons=row.get("reasons", "") or "",
                risks=row.get("risks", "") or "",
            )
        )
    return lines


def _format_float(value: object) -> str:
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except ModuleNotFoundError:
        if value is None:
            return ""
    if value is None:
        return ""
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _decision_columns() -> list[str]:
    return [
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
