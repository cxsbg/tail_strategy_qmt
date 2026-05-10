from __future__ import annotations

from qmt.trader import (
    QmtFillSnapshot,
    QmtOrderRequest,
    QmtOrderSide,
    QmtOrderSnapshot,
    QmtOrderStatus,
    QmtPositionSnapshot,
    QmtPriceType,
    QmtSubmittedOrder,
)
from utils.exceptions import QmtUnavailableError


class XtQuantTraderAdapter:
    """Thin xtquant trader adapter with lazy imports.

    This adapter is intentionally isolated in `src/qmt/` so strategy and
    trading workflow code can be tested without a QMT installation.
    """

    def __init__(
        self,
        *,
        trader_path: str,
        account_id: str,
        session_id: int = 1,
        strategy_name: str = "tail_strategy_qmt",
        auto_connect: bool = True,
    ) -> None:
        try:
            from xtquant import xtconstant, xttrader, xttype
        except ModuleNotFoundError as exc:
            raise QmtUnavailableError(
                "xtquant is not available. Install QMT/xtquant before using QMT trading access."
            ) from exc

        self._xtconstant = xtconstant
        self._trader = xttrader.XtQuantTrader(trader_path, session_id)
        self._account = xttype.StockAccount(account_id)
        self._strategy_name = strategy_name
        if auto_connect:
            self.connect()

    def connect(self) -> None:
        result = self._trader.connect()
        if result not in {0, None}:
            raise QmtUnavailableError(f"QMT trader connect failed: {result}")
        subscribe_result = self._trader.subscribe(self._account)
        if subscribe_result not in {0, None}:
            raise QmtUnavailableError(f"QMT account subscribe failed: {subscribe_result}")

    def submit_order(self, request: QmtOrderRequest) -> QmtSubmittedOrder:
        order_type = _side_constant(self._xtconstant, request.side)
        price_type = _price_type_constant(self._xtconstant, request.price_type)
        broker_order_id = self._trader.order_stock(
            self._account,
            request.symbol,
            order_type,
            int(request.quantity),
            price_type,
            float(request.price or 0.0),
            request.strategy_name or self._strategy_name,
            request.order_remark or "",
        )
        status = QmtOrderStatus.SUBMITTED if int(broker_order_id) >= 0 else QmtOrderStatus.REJECTED
        message = None if status == QmtOrderStatus.SUBMITTED else f"order_stock returned {broker_order_id}"
        return QmtSubmittedOrder(
            broker_order_id=str(broker_order_id),
            symbol=request.symbol,
            side=request.side,
            status=status,
            raw_status=None,
            message=message,
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        result = self._trader.cancel_order_stock(self._account, int(broker_order_id))
        return result in {0, None}

    def query_orders(self) -> list[QmtOrderSnapshot]:
        orders = self._trader.query_stock_orders(self._account) or []
        return [_order_snapshot(order) for order in orders]

    def query_fills(self) -> list[QmtFillSnapshot]:
        trades = self._trader.query_stock_trades(self._account) or []
        return [_fill_snapshot(trade) for trade in trades]

    def query_positions(self) -> list[QmtPositionSnapshot]:
        positions = self._trader.query_stock_positions(self._account) or []
        return [_position_snapshot(position) for position in positions]


def _side_constant(xtconstant: object, side: QmtOrderSide) -> object:
    if side == QmtOrderSide.BUY:
        return getattr(xtconstant, "STOCK_BUY")
    return getattr(xtconstant, "STOCK_SELL")


def _price_type_constant(xtconstant: object, price_type: QmtPriceType) -> object:
    if price_type == QmtPriceType.MARKET:
        return getattr(xtconstant, "LATEST_PRICE", getattr(xtconstant, "MARKET_PRICE", 0))
    return getattr(xtconstant, "FIX_PRICE", 11)


def _order_snapshot(order: object) -> QmtOrderSnapshot:
    side = _side_from_raw(_first_attr(order, "order_type", "entrust_bs", "offset_flag"))
    raw_status = _first_attr(order, "order_status", "status", "entrust_status")
    return QmtOrderSnapshot(
        broker_order_id=str(_first_attr(order, "order_id", "order_sysid", "entrust_no") or ""),
        symbol=str(_first_attr(order, "stock_code", "symbol", "instrument_id") or ""),
        side=side,
        status=_status_from_raw(raw_status),
        quantity=_float_or_none(_first_attr(order, "order_volume", "volume", "entrust_amount")),
        traded_quantity=_float_or_none(_first_attr(order, "traded_volume", "traded_amount", "business_amount")),
        price=_float_or_none(_first_attr(order, "price", "entrust_price")),
        raw_status=str(raw_status) if raw_status is not None else None,
        message=_string_or_none(_first_attr(order, "status_msg", "msg", "error_msg")),
    )


def _fill_snapshot(trade: object) -> QmtFillSnapshot:
    side = _side_from_raw(_first_attr(trade, "order_type", "entrust_bs", "offset_flag"))
    price = _float_or_none(_first_attr(trade, "traded_price", "price", "business_price")) or 0.0
    quantity = _float_or_none(_first_attr(trade, "traded_volume", "volume", "business_amount")) or 0.0
    return QmtFillSnapshot(
        broker_order_id=_string_or_none(_first_attr(trade, "order_id", "order_sysid", "entrust_no")),
        symbol=str(_first_attr(trade, "stock_code", "symbol", "instrument_id") or ""),
        side=side,
        quantity=quantity,
        price=price,
        fill_date=_string_or_none(_first_attr(trade, "traded_date", "trade_date", "business_date")),
        fill_time=_string_or_none(_first_attr(trade, "traded_time", "trade_time", "business_time")),
        amount=price * quantity,
        fee=_float_or_none(_first_attr(trade, "fee", "commission")),
    )


def _position_snapshot(position: object) -> QmtPositionSnapshot:
    return QmtPositionSnapshot(
        symbol=str(_first_attr(position, "stock_code", "symbol", "instrument_id") or ""),
        quantity=_float_or_none(_first_attr(position, "volume", "total_volume", "current_amount")) or 0.0,
        available_quantity=_float_or_none(_first_attr(position, "can_use_volume", "available_volume", "enable_amount")),
        market_value=_float_or_none(_first_attr(position, "market_value", "mkt_value")),
        cost_price=_float_or_none(_first_attr(position, "open_price", "cost_price")),
    )


def _status_from_raw(raw_status: object) -> QmtOrderStatus:
    text = str(raw_status or "").lower()
    if any(token in text for token in ["filled", "all_traded", "已成", "全部成交"]):
        return QmtOrderStatus.FILLED
    if any(token in text for token in ["partial", "part", "部成", "部分成交"]):
        return QmtOrderStatus.PARTIAL_FILLED
    if any(token in text for token in ["cancel", "撤", "废单"]):
        return QmtOrderStatus.CANCELED
    if any(token in text for token in ["reject", "error", "fail", "失败", "拒绝"]):
        return QmtOrderStatus.REJECTED
    if text:
        return QmtOrderStatus.SUBMITTED
    return QmtOrderStatus.UNKNOWN


def _side_from_raw(raw_side: object) -> QmtOrderSide:
    text = str(raw_side or "").lower()
    if "sell" in text or "卖" in text or text in {"24", "49"}:
        return QmtOrderSide.SELL
    return QmtOrderSide.BUY


def _first_attr(item: object, *names: str) -> object:
    for name in names:
        if hasattr(item, name):
            return getattr(item, name)
    return None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
