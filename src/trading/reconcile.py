from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from position import Position, PositionRepository
from qmt.trader import QmtPositionSnapshot, QmtTrader


@dataclass(frozen=True)
class PositionReconciliationItem:
    symbol: str
    status: str
    local_position_id: int | None
    local_position_ratio: float | None
    broker_quantity: float
    broker_available_quantity: float | None
    broker_market_value: float | None
    message: str


@dataclass(frozen=True)
class PositionReconciliationResult:
    items: tuple[PositionReconciliationItem, ...]
    markdown_path: Path | None

    @property
    def mismatch_count(self) -> int:
        return sum(item.status != "MATCH" for item in self.items)

    @property
    def matched_count(self) -> int:
        return sum(item.status == "MATCH" for item in self.items)


def reconcile_positions(
    *,
    db_path: str | Path,
    trader: QmtTrader,
    output_path: str | Path | None = None,
) -> PositionReconciliationResult:
    repository = PositionRepository(db_path)
    local_positions = {position.symbol: position for position in repository.list_open_positions()}
    broker_positions = _active_broker_positions(trader.query_positions())
    symbols = sorted(set(local_positions) | set(broker_positions))

    items: list[PositionReconciliationItem] = []
    for symbol in symbols:
        local_position = local_positions.get(symbol)
        broker_position = broker_positions.get(symbol)
        items.append(
            _compare_position(
                symbol=symbol,
                local_position=local_position,
                broker_position=broker_position,
            )
        )

    markdown_path = Path(output_path) if output_path is not None else None
    result = PositionReconciliationResult(items=tuple(items), markdown_path=markdown_path)
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_position_reconciliation_markdown(result), encoding="utf-8")
    return result


def render_position_reconciliation_markdown(result: PositionReconciliationResult) -> str:
    lines = [
        "# Position Reconciliation",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- MATCH: {result.matched_count}",
        f"- MISMATCH: {result.mismatch_count}",
        "",
        "## Items",
        "",
        "| Status | Symbol | Local Position ID | Local Ratio | Broker Quantity | Broker Market Value | Message |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in result.items:
        lines.append(
            "| {status} | {symbol} | {position_id} | {ratio} | {quantity:.2f} | {market_value} | {message} |".format(
                status=item.status,
                symbol=item.symbol,
                position_id=item.local_position_id or "",
                ratio="" if item.local_position_ratio is None else f"{item.local_position_ratio:.4f}",
                quantity=float(item.broker_quantity),
                market_value="" if item.broker_market_value is None else f"{float(item.broker_market_value):.2f}",
                message=item.message.replace("|", "\\|"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _active_broker_positions(positions: list[QmtPositionSnapshot]) -> dict[str, QmtPositionSnapshot]:
    return {position.symbol: position for position in positions if float(position.quantity) > 0}


def _compare_position(
    *,
    symbol: str,
    local_position: Position | None,
    broker_position: QmtPositionSnapshot | None,
) -> PositionReconciliationItem:
    if local_position is not None and broker_position is not None:
        return PositionReconciliationItem(
            symbol=symbol,
            status="MATCH",
            local_position_id=local_position.id,
            local_position_ratio=local_position.position_ratio,
            broker_quantity=broker_position.quantity,
            broker_available_quantity=broker_position.available_quantity,
            broker_market_value=broker_position.market_value,
            message="local_and_broker_position_found",
        )
    if local_position is not None:
        return PositionReconciliationItem(
            symbol=symbol,
            status="MISSING_BROKER",
            local_position_id=local_position.id,
            local_position_ratio=local_position.position_ratio,
            broker_quantity=0.0,
            broker_available_quantity=None,
            broker_market_value=None,
            message="local_position_without_broker_position",
        )
    if broker_position is not None:
        return PositionReconciliationItem(
            symbol=symbol,
            status="MISSING_LOCAL",
            local_position_id=None,
            local_position_ratio=None,
            broker_quantity=broker_position.quantity,
            broker_available_quantity=broker_position.available_quantity,
            broker_market_value=broker_position.market_value,
            message="broker_position_without_local_position",
        )
    raise ValueError(f"Position comparison has no local or broker position: {symbol}")
