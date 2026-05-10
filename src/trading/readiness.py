from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from trading.health import check_trading_run_health
from trading.smoke_test import run_qmt_smoke_test


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class ReadinessResult:
    checks: tuple[ReadinessCheck, ...]
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


def build_readiness_report(
    *,
    data_config: dict[str, Any],
    strategy_config: dict[str, Any],
    db_path: str | Path | None = None,
    parquet_root: str | Path | None = None,
    output_path: str | Path | None = "outputs/readiness_report.md",
    require_live_config: bool = False,
    require_recent_run: bool = False,
) -> ReadinessResult:
    storage_config = _dict(data_config.get("storage"))
    resolved_db_path = Path(db_path or storage_config.get("sqlite_path", "data/database/tail_strategy.db"))
    resolved_parquet_root = Path(parquet_root or storage_config.get("parquet_root", "data/parquet"))

    checks: list[ReadinessCheck] = []
    checks.extend(_config_checks(strategy_config=strategy_config, require_live_config=require_live_config))
    checks.extend(_smoke_checks(data_config, strategy_config, resolved_db_path, resolved_parquet_root))
    checks.extend(_run_health_checks(resolved_db_path, require_recent_run=require_recent_run))
    checks.extend(_artifact_checks())

    markdown_path = Path(output_path) if output_path is not None else None
    result = ReadinessResult(checks=tuple(checks), markdown_path=markdown_path)
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_readiness_markdown(result), encoding="utf-8")
    return result


def render_readiness_markdown(result: ReadinessResult) -> str:
    lines = [
        "# Tail Strategy Readiness",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- PASS: {result.passed_count}",
        f"- WARN: {result.warning_count}",
        f"- FAIL: {result.failed_count}",
        "",
        "## Checks",
        "",
        "| Status | Check | Detail |",
        "|---|---|---|",
    ]
    for check in result.checks:
        lines.append(f"| {check.status} | {check.name} | {_escape(check.detail)} |")
    lines.append("")
    return "\n".join(lines)


def _config_checks(*, strategy_config: dict[str, Any], require_live_config: bool) -> list[ReadinessCheck]:
    trading_config = _dict(strategy_config.get("trading"))
    qmt_config = _dict(trading_config.get("qmt"))
    mode = str(trading_config.get("mode", "paper"))
    checks = [_check("config.trading_mode", "PASS" if mode in {"paper", "live"} else "FAIL", f"mode={mode}")]

    if require_live_config or mode == "live":
        checks.append(_required_text_check("config.qmt.trader_path", qmt_config.get("trader_path")))
        checks.append(_required_text_check("config.qmt.account_id", qmt_config.get("account_id"), detail="configured"))
        has_capital_base = bool(trading_config.get("account_equity") or trading_config.get("order_value_base"))
        checks.append(
            _check(
                "config.capital_base",
                "PASS" if has_capital_base else "FAIL",
                "account_equity or order_value_base configured" if has_capital_base else "missing account_equity/order_value_base",
            )
        )
    return checks


def _smoke_checks(
    data_config: dict[str, Any],
    strategy_config: dict[str, Any],
    db_path: Path,
    parquet_root: Path,
) -> list[ReadinessCheck]:
    result = run_qmt_smoke_test(
        data_config=data_config,
        strategy_config=strategy_config,
        db_path=db_path,
        parquet_root=parquet_root,
        output_path=None,
        connect=False,
    )
    return [
        _check(f"smoke.{item.name}", item.status, item.detail)
        for item in result.checks
        if item.name != "qmt.connect"
    ]


def _run_health_checks(db_path: Path, *, require_recent_run: bool) -> list[ReadinessCheck]:
    result = check_trading_run_health(db_path=db_path, output_path=None)
    checks: list[ReadinessCheck] = []
    for item in result.checks:
        status = item.status
        if item.name == "trading_run.exists" and status == "FAIL" and not require_recent_run:
            status = "WARN"
        checks.append(_check(f"run.{item.name}", status, item.detail))
    return checks


def _artifact_checks() -> list[ReadinessCheck]:
    artifacts = {
        "artifact.qmt_smoke_test": Path("outputs/qmt_smoke_test.md"),
        "artifact.trading_run_monitor": Path("outputs/trading_run_monitor.md"),
        "artifact.trading_run_health": Path("outputs/trading_run_health.md"),
        "artifact.position_reconciliation": Path("outputs/position_reconciliation.md"),
    }
    checks: list[ReadinessCheck] = []
    for name, path in artifacts.items():
        status = "PASS" if path.exists() and path.stat().st_size > 0 else "WARN"
        detail = f"found {path}" if status == "PASS" else f"not generated yet: {path}"
        checks.append(_check(name, status, detail))
    return checks


def _required_text_check(name: str, value: object, *, detail: str | None = None) -> ReadinessCheck:
    text = str(value or "")
    if text:
        return _check(name, "PASS", detail or text)
    return _check(name, "FAIL", "missing")


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _check(name: str, status: str, detail: str) -> ReadinessCheck:
    return ReadinessCheck(name=name, status=status, detail=detail)


def _escape(value: str) -> str:
    return value.replace("|", "\\|")
