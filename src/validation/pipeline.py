from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from utils.exceptions import StorageError


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class ValidationResult:
    checks: tuple[ValidationCheck, ...]
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


def validate_pipeline_outputs(
    *,
    data_config: dict[str, object],
    trade_date: str,
    output_path: str | Path | None = None,
    symbols: Iterable[str] | None = None,
    paths: dict[str, str | Path] | None = None,
) -> ValidationResult:
    checks: list[ValidationCheck] = []
    storage_config = data_config["storage"]
    sqlite_path = Path(storage_config["sqlite_path"])
    parquet_root = Path(storage_config["parquet_root"])
    resolved_paths = _default_paths() | {key: Path(value) for key, value in (paths or {}).items()}

    checks.extend(_validate_sqlite(sqlite_path=sqlite_path, trade_date=trade_date))
    checks.extend(_validate_parquet_outputs(paths=resolved_paths, trade_date=trade_date))
    checks.extend(_validate_reports(paths=resolved_paths))
    checks.extend(_validate_backtest_outputs(paths=resolved_paths))
    checks.extend(_validate_daily_cache(parquet_root=parquet_root, symbols=symbols))

    markdown_output = Path(output_path) if output_path is not None else None
    if markdown_output is not None:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(
            render_validation_markdown(trade_date=trade_date, checks=checks),
            encoding="utf-8",
        )
    return ValidationResult(checks=tuple(checks), markdown_path=markdown_output)


def render_validation_markdown(*, trade_date: str, checks: Iterable[ValidationCheck]) -> str:
    check_list = list(checks)
    passed = sum(check.status == "PASS" for check in check_list)
    warnings = sum(check.status == "WARN" for check in check_list)
    failed = sum(check.status == "FAIL" for check in check_list)
    lines = [
        f"# Tail Strategy Pipeline Validation - {trade_date}",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- PASS: {passed}",
        f"- WARN: {warnings}",
        f"- FAIL: {failed}",
        "",
        "## Checks",
        "",
        "| Status | Check | Detail |",
        "|---|---|---|",
    ]
    for check in check_list:
        lines.append(f"| {check.status} | {check.name} | {check.detail} |")
    lines.append("")
    return "\n".join(lines)


def _validate_sqlite(*, sqlite_path: Path, trade_date: str) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    if not sqlite_path.exists():
        return [_check("sqlite.database", "FAIL", f"Missing database: {sqlite_path}")]

    required_tables = {
        "positions",
        "trades",
        "signals",
        "decisions",
        "decision_applications",
        "data_sync_status",
    }
    try:
        with sqlite3.connect(sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            table_names = {row["name"] for row in rows}
            missing = required_tables - table_names
            if missing:
                checks.append(_check("sqlite.tables", "FAIL", f"Missing tables: {', '.join(sorted(missing))}"))
            else:
                checks.append(_check("sqlite.tables", "PASS", f"Found {len(required_tables)} required tables."))
            checks.append(_date_count_check(conn, "signals", "signal_date", trade_date))
            checks.append(_date_count_check(conn, "decisions", "decision_date", trade_date))
            checks.append(_sync_status_check(conn))
    except sqlite3.Error as exc:
        checks.append(_check("sqlite.read", "FAIL", str(exc)))
    return checks


def _validate_parquet_outputs(*, paths: dict[str, Path], trade_date: str) -> list[ValidationCheck]:
    checks = [
        _parquet_date_check(paths["daily_features"], "daily_features", "date", trade_date, required=True),
        _parquet_date_check(paths["candidates"], "candidates", "date", trade_date, required=True, empty_status="WARN"),
        _parquet_date_check(paths["diagnostics"], "candidate_diagnostics", "date", trade_date, required=True),
        _parquet_date_check(
            paths["tail_confirmation"],
            "tail_confirmation",
            "date",
            trade_date,
            required=False,
            empty_status="WARN",
        ),
        _parquet_date_check(paths["signals"], "signals", "signal_date", trade_date, required=True, empty_status="WARN"),
        _parquet_date_check(
            paths["decisions"],
            "decisions",
            "decision_date",
            trade_date,
            required=True,
            empty_status="WARN",
        ),
    ]
    return checks


def _validate_reports(*, paths: dict[str, Path]) -> list[ValidationCheck]:
    return [
        _file_nonempty_check(paths["daily_report"], "daily_report", required=True),
        _file_nonempty_check(paths["decision_report"], "decision_report", required=True),
    ]


def _validate_backtest_outputs(*, paths: dict[str, Path]) -> list[ValidationCheck]:
    return [
        _file_nonempty_check(paths["backtest_summary"], "backtest_summary", required=False),
        _file_nonempty_check(paths["backtest_report"], "backtest_report", required=False),
        _file_nonempty_check(paths["backtest_equity_curve"], "backtest_equity_curve", required=False),
    ]


def _validate_daily_cache(*, parquet_root: Path, symbols: Iterable[str] | None) -> list[ValidationCheck]:
    if symbols is None:
        daily_root = parquet_root / "daily"
        if not daily_root.exists():
            return [_check("daily_cache", "WARN", f"Daily cache directory not found: {daily_root}")]
        files = list(daily_root.glob("*.parquet"))
        status = "PASS" if files else "WARN"
        return [_check("daily_cache", status, f"Daily cache parquet files: {len(files)}")]

    symbol_list = list(symbols)
    if not symbol_list:
        return [_check("daily_cache.symbols", "WARN", "No symbols provided for cache validation.")]
    missing = [symbol for symbol in symbol_list if not (parquet_root / "daily" / _symbol_file_name(symbol)).exists()]
    if missing:
        return [_check("daily_cache.symbols", "WARN", f"Missing daily cache for {len(missing)} symbols.")]
    return [_check("daily_cache.symbols", "PASS", f"Found daily cache for {len(symbol_list)} symbols.")]


def _parquet_date_check(
    path: Path,
    name: str,
    date_column: str,
    trade_date: str,
    *,
    required: bool,
    empty_status: str = "FAIL",
) -> ValidationCheck:
    if not path.exists():
        return _check(name, "FAIL" if required else "WARN", f"Missing file: {path}")
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to validate parquet outputs.") from exc

    frame = pd.read_parquet(path)
    if date_column not in frame.columns:
        return _check(name, "FAIL", f"Missing date column: {date_column}")
    count = int((frame[date_column].astype(str) == trade_date).sum())
    if count == 0:
        return _check(name, empty_status, f"No rows for {trade_date}; total rows={len(frame)}")
    return _check(name, "PASS", f"Rows for {trade_date}: {count}; total rows={len(frame)}")


def _file_nonempty_check(path: Path, name: str, *, required: bool) -> ValidationCheck:
    if not path.exists():
        return _check(name, "FAIL" if required else "WARN", f"Missing file: {path}")
    size = path.stat().st_size
    status = "PASS" if size > 0 else ("FAIL" if required else "WARN")
    return _check(name, status, f"Size bytes: {size}")


def _date_count_check(conn: sqlite3.Connection, table: str, column: str, trade_date: str) -> ValidationCheck:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {column} = ?", (trade_date,)).fetchone()
    except sqlite3.Error as exc:
        return _check(f"sqlite.{table}", "FAIL", str(exc))
    count = int(row["count"])
    status = "PASS" if count else "WARN"
    return _check(f"sqlite.{table}", status, f"Rows for {trade_date}: {count}")


def _sync_status_check(conn: sqlite3.Connection) -> ValidationCheck:
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM data_sync_status").fetchone()
    except sqlite3.Error as exc:
        return _check("sqlite.data_sync_status", "FAIL", str(exc))
    count = int(row["count"])
    status = "PASS" if count else "WARN"
    return _check("sqlite.data_sync_status", status, f"Sync status rows: {count}")


def _check(name: str, status: str, detail: str) -> ValidationCheck:
    return ValidationCheck(name=name, status=status, detail=detail.replace("|", "\\|"))


def _default_paths() -> dict[str, Path]:
    return {
        "daily_features": Path("data/processed/daily_features.parquet"),
        "candidates": Path("data/processed/candidates.parquet"),
        "diagnostics": Path("data/processed/candidate_diagnostics.parquet"),
        "tail_confirmation": Path("data/processed/tail_confirmation.parquet"),
        "signals": Path("data/processed/signals.parquet"),
        "decisions": Path("data/processed/decisions.parquet"),
        "daily_report": Path("outputs/daily_report.md"),
        "decision_report": Path("outputs/decision_report.md"),
        "backtest_summary": Path("outputs/backtest_summary.csv"),
        "backtest_report": Path("outputs/backtest_report.md"),
        "backtest_equity_curve": Path("outputs/backtest_equity_curve.csv"),
    }


def _symbol_file_name(symbol: str) -> str:
    return f"{symbol.replace('/', '_').replace(chr(92), '_')}.parquet"
