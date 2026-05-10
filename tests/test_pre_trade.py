from __future__ import annotations

from position import PositionRepository, PositionService
from qmt import QmtOrderStatus, QmtPositionSnapshot, QmtSubmittedOrder
from storage.parquet import ParquetStorage
from strategy.decisions import DecisionAction, DecisionRepository, StrategyDecision
from trading.execution import BrokerOrderStatus, TradeExecutionRepository
from trading.pre_trade import CheckStatus, OrderDraftRepository, OrderSide, OrderStatus, run_pre_trade


def test_run_pre_trade_paper_submits_ready_buy_order(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=tmp_path / "pre_trade.md",
    )

    repository = OrderDraftRepository(db_path)
    drafts = repository.list_drafts(trade_date="20260508")
    checks = repository.list_checks(trade_date="20260508")

    assert result.paper_submitted_count == 1
    assert result.blocked_count == 0
    assert result.report_path.exists()
    assert drafts[0].side == OrderSide.BUY
    assert drafts[0].status == OrderStatus.PAPER_SUBMITTED
    assert drafts[0].reference_price == 10.5
    assert {check.status for check in checks} == {CheckStatus.PASS}


def test_run_pre_trade_is_idempotent_after_paper_submit(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
    )
    second = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
    )

    drafts = OrderDraftRepository(db_path).list_drafts(trade_date="20260508")
    assert second.already_submitted_count == 1
    assert len(drafts) == 1
    assert drafts[0].status == OrderStatus.PAPER_SUBMITTED


def test_run_pre_trade_blocks_duplicate_buy_position(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    PositionService(PositionRepository(db_path), strategy_version="test-rule").open_position(
        symbol="000001.SZ",
        entry_date="20260507",
        entry_price=10.0,
        position_ratio=0.15,
        max_position_ratio=0.15,
    )
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
    )

    drafts = OrderDraftRepository(db_path).list_drafts(trade_date="20260508")
    assert result.blocked_count == 1
    assert result.paper_submitted_count == 0
    assert drafts[0].status == OrderStatus.BLOCKED
    assert "duplicate_position" in drafts[0].block_reasons


def test_run_pre_trade_blocks_total_exposure_limit(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    service = PositionService(PositionRepository(db_path), strategy_version="test-rule")
    service.open_position(
        symbol="600000.SH",
        entry_date="20260507",
        entry_price=10.0,
        position_ratio=0.75,
        max_position_ratio=0.75,
    )
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
    )

    draft = OrderDraftRepository(db_path).list_drafts(trade_date="20260508")[0]
    assert result.blocked_count == 1
    assert "max_total_position_ratio" in draft.block_reasons


def test_run_pre_trade_builds_sell_order_for_reduce_decision(tmp_path) -> None:
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

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
    )

    draft = OrderDraftRepository(db_path).list_drafts(trade_date="20260508")[0]
    assert result.paper_submitted_count == 1
    assert draft.side == OrderSide.SELL
    assert draft.status == OrderStatus.PAPER_SUBMITTED
    assert draft.position_ratio == 0.15


def test_run_pre_trade_blocks_limit_up_buy(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 11.0])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
    )

    draft = OrderDraftRepository(db_path).list_drafts(trade_date="20260508")[0]
    assert result.blocked_count == 1
    assert "limit_up_buy" in draft.block_reasons


def test_run_pre_trade_live_submits_ready_buy_order_and_records_broker_order(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    trader = _FakeTrader()
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    config = _strategy_config(mode="live") | {"trading": _strategy_config(mode="live")["trading"] | {"account_equity": 100000.0}}
    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=config,
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        trader=trader,
    )

    draft = OrderDraftRepository(db_path).list_drafts(trade_date="20260508")[0]
    broker_order = TradeExecutionRepository(db_path).list_orders(trade_date="20260508")[0]
    assert result.submitted_count == 1
    assert draft.status == OrderStatus.SUBMITTED
    assert broker_order.broker_order_id == "live-1"
    assert broker_order.status == BrokerOrderStatus.SUBMITTED
    assert broker_order.quantity == 1400.0
    assert trader.requests[0].symbol == "000001.SZ"
    assert trader.requests[0].quantity == 1400.0


def test_run_pre_trade_live_rejects_buy_when_order_value_base_missing(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(mode="live"),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        trader=_FakeTrader(),
    )

    draft = OrderDraftRepository(db_path).list_drafts(trade_date="20260508")[0]
    broker_order = TradeExecutionRepository(db_path).list_orders(trade_date="20260508")[0]
    assert result.rejected_count == 1
    assert draft.status == OrderStatus.REJECTED
    assert broker_order.status == BrokerOrderStatus.REJECTED
    assert "order_value_base" in broker_order.message


def test_run_pre_trade_live_sell_uses_broker_available_quantity(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    trader = _FakeTrader(
        positions=[
            QmtPositionSnapshot(
                symbol="000001.SZ",
                quantity=800.0,
                available_quantity=700.0,
            )
        ]
    )
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

    result = run_pre_trade(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(mode="live"),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        trader=trader,
    )

    assert result.submitted_count == 1
    assert trader.requests[0].quantity == 700.0


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


class _FakeTrader:
    def __init__(self, *, positions: list[QmtPositionSnapshot] | None = None) -> None:
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
        return []

    def query_fills(self):
        return []

    def query_positions(self):
        return self.positions


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
