from __future__ import annotations

from position import PositionAction, PositionRepository, PositionService, PositionStatus
from qmt import (
    QmtFillSnapshot,
    QmtOrderSide,
    QmtOrderSnapshot,
    QmtOrderStatus,
    QmtPositionSnapshot,
    QmtSubmittedOrder,
)
from storage.parquet import ParquetStorage
from strategy.decisions import DecisionAction, DecisionRepository, StrategyDecision
from trading.execution import BrokerOrderStatus, TradeExecutionRepository
from trading.pre_trade import run_pre_trade
from trading.sync import sync_broker_executions


def test_sync_broker_executions_updates_orders_fills_and_opens_position(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))
    submit_trader = _FakeTrader()
    run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(mode="live") | {
            "trading": _strategy_config(mode="live")["trading"] | {"account_equity": 100000.0}
        },
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        trader=submit_trader,
    )

    sync_trader = _FakeTrader(
        orders=[
            QmtOrderSnapshot(
                broker_order_id="live-1",
                symbol="000001.SZ",
                side=QmtOrderSide.BUY,
                status=QmtOrderStatus.FILLED,
                quantity=1400.0,
                traded_quantity=1400.0,
                price=10.5,
                raw_status="filled",
            )
        ],
        fills=[
            QmtFillSnapshot(
                broker_order_id="live-1",
                symbol="000001.SZ",
                side=QmtOrderSide.BUY,
                quantity=1400.0,
                price=10.5,
                fill_date="20260508",
                fill_time="14:56:00",
                amount=14700.0,
                fee=1.0,
            )
        ],
    )

    result = sync_broker_executions(
        db_path=db_path,
        trader=sync_trader,
        trade_date="20260508",
        apply_positions=True,
        strategy_version="test-rule",
    )

    execution_repository = TradeExecutionRepository(db_path)
    broker_order = execution_repository.list_orders(trade_date="20260508")[0]
    position = PositionRepository(db_path).get_open_position_by_symbol("000001.SZ")
    assert result.order_upsert_count == 1
    assert result.fill_inserted_count == 1
    assert result.position_application_count == 1
    assert broker_order.status == BrokerOrderStatus.FILLED
    assert len(execution_repository.list_fills(broker_order_id="live-1")) == 1
    assert execution_repository.get_order_application("live-1").status == "APPLIED"
    assert position is not None
    assert position.entry_price == 10.5
    assert position.position_ratio == 0.15


def test_sync_broker_executions_is_idempotent_for_fills_and_position_application(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))
    run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(mode="live") | {
            "trading": _strategy_config(mode="live")["trading"] | {"account_equity": 100000.0}
        },
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        trader=_FakeTrader(),
    )
    sync_trader = _FakeTrader(
        orders=[
            QmtOrderSnapshot(
                broker_order_id="live-1",
                symbol="000001.SZ",
                side=QmtOrderSide.BUY,
                status=QmtOrderStatus.FILLED,
                quantity=1400.0,
                traded_quantity=1400.0,
                price=10.5,
            )
        ],
        fills=[
            QmtFillSnapshot(
                broker_order_id="live-1",
                symbol="000001.SZ",
                side=QmtOrderSide.BUY,
                quantity=1400.0,
                price=10.5,
                fill_date="20260508",
                fill_time="14:56:00",
            )
        ],
    )

    first = sync_broker_executions(
        db_path=db_path,
        trader=sync_trader,
        trade_date="20260508",
        apply_positions=True,
        strategy_version="test-rule",
    )
    second = sync_broker_executions(
        db_path=db_path,
        trader=sync_trader,
        trade_date="20260508",
        apply_positions=True,
        strategy_version="test-rule",
    )

    repository = PositionRepository(db_path)
    assert first.fill_inserted_count == 1
    assert second.fill_inserted_count == 0
    assert second.position_application_count == 0
    assert len(repository.list_trades("000001.SZ")) == 1


def test_sync_broker_executions_closes_position_on_filled_sell(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 9.8])
    position = PositionService(PositionRepository(db_path), strategy_version="test-rule").open_position(
        symbol="000001.SZ",
        entry_date="20260507",
        entry_price=10.0,
        position_ratio=0.15,
        max_position_ratio=0.15,
    )
    _store_decision(
        db_path,
        _decision("000001.SZ", DecisionAction.REDUCE_POSITION, ratio=0.0, position_id=position.id),
    )
    run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(mode="live"),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        trader=_FakeTrader(
            positions=[
                QmtPositionSnapshot(
                    symbol="000001.SZ",
                    quantity=700.0,
                    available_quantity=700.0,
                )
            ]
        ),
    )

    result = sync_broker_executions(
        db_path=db_path,
        trader=_FakeTrader(
            orders=[
                QmtOrderSnapshot(
                    broker_order_id="live-1",
                    symbol="000001.SZ",
                    side=QmtOrderSide.SELL,
                    status=QmtOrderStatus.FILLED,
                    quantity=700.0,
                    traded_quantity=700.0,
                    price=9.8,
                )
            ],
            fills=[
                QmtFillSnapshot(
                    broker_order_id="live-1",
                    symbol="000001.SZ",
                    side=QmtOrderSide.SELL,
                    quantity=700.0,
                    price=9.8,
                    fill_date="20260508",
                    fill_time="14:57:00",
                )
            ],
        ),
        trade_date="20260508",
        apply_positions=True,
        strategy_version="test-rule",
    )

    repository = PositionRepository(db_path)
    updated = repository.get_position(position.id)
    assert result.position_application_count == 1
    assert updated.status == PositionStatus.CLOSED
    assert repository.list_trades("000001.SZ")[-1].action == PositionAction.REDUCE


def _strategy_config(*, mode: str = "paper") -> dict[str, object]:
    return {
        "position": {
            "initial_position_ratio": 0.30,
            "max_single_stock_ratio": 0.15,
            "max_total_positions": 5,
        },
        "trading": {
            "mode": mode,
            "strategy_name": "tail_strategy_qmt",
            "warn_policy": "block",
            "max_order_position_ratio": 0.15,
            "max_total_position_ratio": 0.80,
            "max_open_positions": 5,
            "block_if_price_limit": True,
            "limit_up_pct": 0.098,
            "limit_down_pct": 0.098,
            "order_lot_size": 100,
        },
    }


def _store_decision(db_path, decision: StrategyDecision) -> None:
    DecisionRepository(db_path).replace_decisions(
        [decision],
        decision_date=decision.decision_date,
        strategy_version=decision.strategy_version,
    )


def _decision(
    symbol: str,
    action: DecisionAction,
    *,
    ratio: float | None,
    position_id: int | None = None,
) -> StrategyDecision:
    return StrategyDecision(
        id=None,
        symbol=symbol,
        decision_date="20260508",
        source_signal_id=None,
        position_id=position_id,
        action=action,
        score=80.0,
        suggested_position_ratio=ratio,
        reasons="tail_confirmed",
        risks=None,
        strategy_version="test-rule",
        created_at="2026-05-08T15:00:00",
    )


def _write_daily(parquet_root, symbol: str, *, closes: list[float]) -> None:
    import pandas as pd

    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "symbol": symbol,
                "date": f"202605{7 + index:02d}",
                "open": close - 0.1,
                "high": close + 0.2,
                "low": close - 0.3,
                "close": close,
                "volume": 1000000,
                "amount": 12340000,
            }
        )
    ParquetStorage(parquet_root).write_frame("daily", symbol, pd.DataFrame(rows))


class _FakeTrader:
    def __init__(
        self,
        *,
        orders: list[QmtOrderSnapshot] | None = None,
        fills: list[QmtFillSnapshot] | None = None,
        positions: list[QmtPositionSnapshot] | None = None,
    ) -> None:
        self.orders = orders or []
        self.fills = fills or []
        self.positions = positions or []
        self.requests = []

    def connect(self) -> None:
        return None

    def submit_order(self, request):
        self.requests.append(request)
        return QmtSubmittedOrder(
            broker_order_id=f"live-{len(self.requests)}",
            symbol=request.symbol,
            side=request.side,
            status=QmtOrderStatus.SUBMITTED,
            raw_status="submitted",
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        return True

    def query_orders(self):
        return self.orders

    def query_fills(self):
        return self.fills

    def query_positions(self):
        return self.positions
