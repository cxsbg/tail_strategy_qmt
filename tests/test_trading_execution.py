from __future__ import annotations

from trading.execution import (
    BrokerFill,
    BrokerOrder,
    BrokerOrderApplication,
    BrokerOrderStatus,
    TradeExecutionRepository,
)


def test_trade_execution_repository_upserts_and_updates_orders(tmp_path) -> None:
    repository = TradeExecutionRepository(tmp_path / "tail_strategy.db")
    order = BrokerOrder(
        id=None,
        order_draft_id=1,
        decision_id=2,
        broker_order_id="10001",
        symbol="000001.SZ",
        trade_date="20260508",
        side="BUY",
        quantity=100.0,
        price=10.5,
        order_type="LIMIT",
        status=BrokerOrderStatus.SUBMITTED,
        raw_status="submitted",
        message=None,
        strategy_version="test-rule",
        created_at="now",
        updated_at="now",
    )

    first_id = repository.upsert_order(order)
    second_id = repository.upsert_order(
        BrokerOrder(
            **{
                **order.__dict__,
                "id": None,
                "status": BrokerOrderStatus.PARTIAL_FILLED,
                "raw_status": "partial",
                "message": "partial fill",
            }
        )
    )
    repository.update_order_status(
        broker_order_id="10001",
        status=BrokerOrderStatus.FILLED,
        raw_status="filled",
        message="done",
    )

    orders = repository.list_orders(trade_date="20260508")
    assert first_id == second_id
    assert len(orders) == 1
    assert orders[0].status == BrokerOrderStatus.FILLED
    assert orders[0].message == "done"


def test_trade_execution_repository_records_fills(tmp_path) -> None:
    repository = TradeExecutionRepository(tmp_path / "tail_strategy.db")
    fill_id = repository.insert_fill(
        BrokerFill(
            id=None,
            broker_order_id="10001",
            symbol="000001.SZ",
            side="BUY",
            fill_date="20260508",
            fill_time="14:56:00",
            quantity=100.0,
            price=10.5,
            amount=1050.0,
            fee=1.0,
            created_at="now",
        )
    )

    fills = repository.list_fills(broker_order_id="10001")
    assert fill_id == 1
    assert len(fills) == 1
    assert fills[0].symbol == "000001.SZ"
    assert fills[0].amount == 1050.0


def test_trade_execution_repository_deduplicates_fills_and_records_applications(tmp_path) -> None:
    repository = TradeExecutionRepository(tmp_path / "tail_strategy.db")
    fill = BrokerFill(
        id=None,
        broker_order_id="10001",
        symbol="000001.SZ",
        side="BUY",
        fill_date="20260508",
        fill_time="14:56:00",
        quantity=100.0,
        price=10.5,
        amount=1050.0,
        fee=1.0,
        created_at="now",
    )

    first_id, first_inserted = repository.upsert_fill(fill)
    second_id, second_inserted = repository.upsert_fill(fill)
    application_id = repository.insert_order_application(
        BrokerOrderApplication(
            id=None,
            broker_order_id="10001",
            symbol="000001.SZ",
            side="BUY",
            status="APPLIED",
            message="opened_position",
            created_at="now",
        )
    )

    assert first_inserted is True
    assert second_inserted is False
    assert first_id == second_id
    assert len(repository.list_fills(broker_order_id="10001")) == 1
    assert application_id == 1
    assert repository.get_order_application("10001").status == "APPLIED"
