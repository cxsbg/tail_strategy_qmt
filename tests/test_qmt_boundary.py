from __future__ import annotations

from pathlib import Path

from qmt import (
    QmtOrderRequest,
    QmtOrderSide,
    QmtOrderStatus,
    QmtPriceType,
    QmtSubmittedOrder,
)


def test_xtquant_is_only_referenced_inside_qmt_package() -> None:
    root = Path("src")
    offenders: list[Path] = []

    for path in root.rglob("*.py"):
        if "qmt" in path.parts:
            continue
        if "xtquant" in path.read_text(encoding="utf-8"):
            offenders.append(path)

    assert offenders == []


def test_qmt_trader_models_are_importable_without_xtquant() -> None:
    request = QmtOrderRequest(
        symbol="000001.SZ",
        side=QmtOrderSide.BUY,
        quantity=100,
        price=10.5,
        price_type=QmtPriceType.LIMIT,
    )
    submitted = QmtSubmittedOrder(
        broker_order_id="10001",
        symbol=request.symbol,
        side=request.side,
        status=QmtOrderStatus.SUBMITTED,
    )

    assert request.symbol == "000001.SZ"
    assert submitted.status == QmtOrderStatus.SUBMITTED
