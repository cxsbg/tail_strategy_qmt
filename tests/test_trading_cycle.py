from __future__ import annotations

from position import PositionRepository
from qmt import QmtFillSnapshot, QmtOrderSide, QmtOrderSnapshot, QmtOrderStatus, QmtPositionSnapshot, QmtSubmittedOrder
from storage.parquet import ParquetStorage
from strategy.decisions import DecisionAction, DecisionRepository, StrategyDecision
from trading.execution import TradeExecutionRepository
from trading.pre_trade import OrderDraftRepository, OrderStatus
from trading.cycle import run_trading_cycle


def test_run_trading_cycle_paper_submits_without_broker_sync(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = run_trading_cycle(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(mode="paper"),
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        cycle_report_path=tmp_path / "cycle.md",
    )

    draft = OrderDraftRepository(db_path).list_drafts(trade_date="20260508")[0]
    assert result.pre_trade.paper_submitted_count == 1
    assert result.sync_count == 0
    assert result.report_path.exists()
    assert "Trading Cycle Report" in result.report_path.read_text(encoding="utf-8")
    assert draft.status == OrderStatus.PAPER_SUBMITTED
    assert len(TradeExecutionRepository(db_path).list_orders(trade_date="20260508")) == 1


def test_run_trading_cycle_live_submits_syncs_and_applies_position(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    trader = _CycleTrader()
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = run_trading_cycle(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(mode="live") | {
            "trading": _strategy_config(mode="live")["trading"] | {"account_equity": 100000.0}
        },
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        cycle_report_path=tmp_path / "cycle_live.md",
        apply_positions=True,
        trader=trader,
    )

    position = PositionRepository(db_path).get_open_position_by_symbol("000001.SZ")
    broker_order = TradeExecutionRepository(db_path).list_orders(trade_date="20260508")[0]
    assert result.pre_trade.submitted_count == 1
    assert result.sync_count == 1
    assert result.total_fill_inserted_count == 1
    assert result.total_position_application_count == 1
    assert broker_order.status.value == "FILLED"
    markdown = result.report_path.read_text(encoding="utf-8")
    assert "Broker Orders" in markdown
    assert "live-1" in markdown
    assert position is not None
    assert position.entry_price == 10.5


def test_run_trading_cycle_live_can_skip_sync(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    parquet_root = tmp_path / "parquet"
    _write_daily(parquet_root, "000001.SZ", closes=[10.0, 10.5])
    _store_decision(db_path, _decision("000001.SZ", DecisionAction.OPEN_POSITION, ratio=0.15))

    result = run_trading_cycle(
        db_path=db_path,
        parquet_root=parquet_root,
        strategy_config=_strategy_config(mode="live") | {
            "trading": _strategy_config(mode="live")["trading"] | {"account_equity": 100000.0}
        },
        trade_date="20260508",
        strategy_version="test-rule",
        report_path=None,
        cycle_report_path=None,
        sync_broker=False,
        trader=_CycleTrader(),
    )

    assert result.pre_trade.submitted_count == 1
    assert result.sync_count == 0
    assert result.report_path is None
    assert PositionRepository(db_path).list_open_positions() == []


def _strategy_config(*, mode: str) -> dict[str, object]:
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


class _CycleTrader:
    def __init__(self) -> None:
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
        return [
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
        ]

    def query_fills(self):
        return [
            QmtFillSnapshot(
                broker_order_id="live-1",
                symbol="000001.SZ",
                side=QmtOrderSide.BUY,
                quantity=1400.0,
                price=10.5,
                fill_date="20260508",
                fill_time="14:56:00",
            )
        ]

    def query_positions(self):
        return [
            QmtPositionSnapshot(
                symbol="000001.SZ",
                quantity=1400.0,
                available_quantity=1400.0,
            )
        ]
