from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from trading.execution import TradeExecutionRepository
from trading.pre_trade import OrderDraftRepository

if TYPE_CHECKING:
    from trading.cycle import TradingCycleResult


@dataclass(frozen=True)
class TradingCycleReportResult:
    markdown_path: Path
    report_date: str
    order_count: int
    fill_count: int


def build_trading_cycle_report(
    *,
    result: "TradingCycleResult",
    markdown_path: str | Path,
) -> TradingCycleReportResult:
    draft_repository = OrderDraftRepository(result.db_path)
    execution_repository = TradeExecutionRepository(result.db_path)
    drafts = draft_repository.list_drafts(trade_date=result.date)
    checks = draft_repository.list_checks(trade_date=result.date)
    orders = execution_repository.list_orders(trade_date=result.date)
    fills = execution_repository.list_fills()
    fills = [fill for fill in fills if fill.fill_date in {None, result.date} or not fill.fill_date]

    output = Path(markdown_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_trading_cycle_markdown(
            result=result,
            drafts=drafts,
            checks=checks,
            orders=orders,
            fills=fills,
        ),
        encoding="utf-8",
    )
    return TradingCycleReportResult(
        markdown_path=output,
        report_date=result.date,
        order_count=len(orders),
        fill_count=len(fills),
    )


def render_trading_cycle_markdown(
    *,
    result: "TradingCycleResult",
    drafts: object,
    checks: object,
    orders: object,
    fills: object,
) -> str:
    lines = [
        f"# Trading Cycle Report - {result.date}",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Decisions: {result.pre_trade.decision_count}",
        f"- Drafts: {result.pre_trade.draft_count}",
        f"- Blocked: {result.pre_trade.blocked_count}",
        f"- Paper submitted: {result.pre_trade.paper_submitted_count}",
        f"- Submitted: {result.pre_trade.submitted_count}",
        f"- Rejected: {result.pre_trade.rejected_count}",
        f"- Broker sync attempts: {result.sync_count}",
        f"- Inserted fills: {result.total_fill_inserted_count}",
        f"- Position applications: {result.total_position_application_count}",
        "",
        "## Order Drafts",
        "",
        "| Status | Symbol | Side | Ref Price | Position Ratio | Reasons |",
        "|---|---|---:|---:|---:|---|",
    ]
    if not drafts:
        lines.append("| - | - | - | - | - | no_order_drafts |")
    for draft in drafts:
        lines.append(
            "| {status} | {symbol} | {side} | {price} | {ratio} | {reasons} |".format(
                status=draft.status.value,
                symbol=draft.symbol,
                side=draft.side.value,
                price=_fmt_float(draft.reference_price),
                ratio=_fmt_pct(draft.position_ratio),
                reasons=draft.block_reasons or "",
            )
        )

    lines.extend(
        [
            "",
            "## Broker Orders",
            "",
            "| Status | Broker Order | Symbol | Side | Quantity | Price | Message |",
            "|---|---|---|---:|---:|---:|---|",
        ]
    )
    if not orders:
        lines.append("| - | - | - | - | - | - | no_broker_orders |")
    for order in orders:
        lines.append(
            "| {status} | {broker_order_id} | {symbol} | {side} | {quantity} | {price} | {message} |".format(
                status=order.status.value,
                broker_order_id=order.broker_order_id or "",
                symbol=order.symbol,
                side=order.side,
                quantity=_fmt_float(order.quantity),
                price=_fmt_float(order.price),
                message=_escape(order.message or ""),
            )
        )

    lines.extend(
        [
            "",
            "## Fills",
            "",
            "| Broker Order | Symbol | Side | Time | Quantity | Price | Amount |",
            "|---|---|---:|---|---:|---:|---:|",
        ]
    )
    if not fills:
        lines.append("| - | - | - | - | - | - | no_fills |")
    for fill in fills:
        lines.append(
            "| {broker_order_id} | {symbol} | {side} | {time} | {quantity} | {price} | {amount} |".format(
                broker_order_id=fill.broker_order_id or "",
                symbol=fill.symbol,
                side=fill.side,
                time=fill.fill_time or "",
                quantity=_fmt_float(fill.quantity),
                price=_fmt_float(fill.price),
                amount=_fmt_float(fill.amount),
            )
        )

    lines.extend(["", "## Risk Checks", "", "| Status | Symbol | Check | Message |", "|---|---|---|---|"])
    if not checks:
        lines.append("| - | - | - | no_checks |")
    for check in checks:
        lines.append(
            f"| {check.status.value} | {check.symbol} | {check.check_name} | {_escape(check.message or '')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _fmt_float(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _fmt_pct(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value) * 100:.2f}%"


def _escape(value: str) -> str:
    return value.replace("|", "\\|")
