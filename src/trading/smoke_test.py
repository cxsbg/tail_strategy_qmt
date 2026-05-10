from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from qmt.trader import QmtTrader
from storage.sqlite import SQLiteStore


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class QmtSmokeTestResult:
    checks: tuple[SmokeCheck, ...]
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


def run_qmt_smoke_test(
    *,
    data_config: dict[str, Any],
    strategy_config: dict[str, Any],
    db_path: str | Path | None = None,
    parquet_root: str | Path | None = None,
    output_path: str | Path | None = "outputs/qmt_smoke_test.md",
    connect: bool = False,
    trader: QmtTrader | None = None,
) -> QmtSmokeTestResult:
    checks: list[SmokeCheck] = []
    storage_config = _dict(data_config.get("storage"))
    trading_config = _dict(strategy_config.get("trading"))
    qmt_config = _dict(trading_config.get("qmt"))
    resolved_db_path = Path(db_path or storage_config.get("sqlite_path", "data/database/tail_strategy.db"))
    resolved_parquet_root = Path(parquet_root or storage_config.get("parquet_root", "data/parquet"))

    checks.append(_sqlite_check(resolved_db_path))
    checks.append(_parquet_root_check(resolved_parquet_root))
    checks.extend(_trading_config_checks(trading_config=trading_config, qmt_config=qmt_config, connect=connect))

    if connect:
        checks.extend(_qmt_connection_checks(trading_config=trading_config, qmt_config=qmt_config, trader=trader))
    else:
        checks.append(_check("qmt.connect", "WARN", "Skipped QMT connection checks. Use --connect on the QMT machine."))

    markdown_path = Path(output_path) if output_path is not None else None
    result = QmtSmokeTestResult(checks=tuple(checks), markdown_path=markdown_path)
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_qmt_smoke_markdown(result), encoding="utf-8")
    return result


def render_qmt_smoke_markdown(result: QmtSmokeTestResult) -> str:
    lines = [
        "# QMT Smoke Test",
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


def _sqlite_check(db_path: Path) -> SmokeCheck:
    try:
        SQLiteStore(db_path).initialize()
    except Exception as exc:
        return _check("sqlite.database", "FAIL", str(exc))
    return _check("sqlite.database", "PASS", f"Initialized database: {db_path}")


def _parquet_root_check(parquet_root: Path) -> SmokeCheck:
    if parquet_root.exists():
        return _check("parquet.root", "PASS", f"Found parquet root: {parquet_root}")
    return _check("parquet.root", "WARN", f"Parquet root not found yet: {parquet_root}")


def _trading_config_checks(
    *,
    trading_config: dict[str, Any],
    qmt_config: dict[str, Any],
    connect: bool,
) -> list[SmokeCheck]:
    mode = str(trading_config.get("mode", "paper"))
    checks = [_check("trading.mode", "PASS" if mode in {"paper", "live"} else "WARN", f"mode={mode}")]

    trader_path = str(qmt_config.get("trader_path") or "")
    account_id = str(qmt_config.get("account_id") or "")
    required_status = "FAIL" if connect or mode == "live" else "WARN"
    checks.append(
        _check(
            "qmt.trader_path",
            "PASS" if trader_path else required_status,
            trader_path or "trading.qmt.trader_path is empty",
        )
    )
    checks.append(
        _check(
            "qmt.account_id",
            "PASS" if account_id else required_status,
            "configured" if account_id else "trading.qmt.account_id is empty",
        )
    )

    if mode == "live":
        account_equity = trading_config.get("account_equity")
        order_value_base = trading_config.get("order_value_base")
        if account_equity or order_value_base:
            checks.append(_check("trading.capital_base", "PASS", "account_equity or order_value_base configured"))
        else:
            checks.append(_check("trading.capital_base", "FAIL", "Set account_equity or order_value_base for live mode."))
    return checks


def _qmt_connection_checks(
    *,
    trading_config: dict[str, Any],
    qmt_config: dict[str, Any],
    trader: QmtTrader | None,
) -> list[SmokeCheck]:
    checks: list[SmokeCheck] = []
    active_trader = trader
    try:
        if active_trader is None:
            from qmt import build_xt_trader

            active_trader = build_xt_trader(
                trader_path=str(qmt_config.get("trader_path") or ""),
                account_id=str(qmt_config.get("account_id") or ""),
                session_id=int(qmt_config.get("session_id", 1)),
                strategy_name=str(trading_config.get("strategy_name", "tail_strategy_qmt")),
            )
        else:
            active_trader.connect()
        checks.append(_check("qmt.connect", "PASS", "Connected and subscribed account."))
    except Exception as exc:
        return [_check("qmt.connect", "FAIL", str(exc))]

    checks.append(_query_check("qmt.positions", active_trader.query_positions))
    checks.append(_query_check("qmt.orders", active_trader.query_orders))
    checks.append(_query_check("qmt.fills", active_trader.query_fills))
    return checks


def _query_check(name: str, query) -> SmokeCheck:
    try:
        rows = query()
    except Exception as exc:
        return _check(name, "FAIL", str(exc))
    return _check(name, "PASS", f"rows={len(rows)}")


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _check(name: str, status: str, detail: str) -> SmokeCheck:
    return SmokeCheck(name=name, status=status, detail=detail)


def _escape(value: str) -> str:
    return value.replace("|", "\\|")
