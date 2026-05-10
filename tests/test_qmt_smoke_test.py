from __future__ import annotations

from qmt import QmtFillSnapshot, QmtOrderSide, QmtOrderSnapshot, QmtOrderStatus, QmtPositionSnapshot
from trading.smoke_test import render_qmt_smoke_markdown, run_qmt_smoke_test


def test_qmt_smoke_test_checks_config_without_connecting(tmp_path) -> None:
    result = run_qmt_smoke_test(
        data_config=_data_config(tmp_path),
        strategy_config=_strategy_config(mode="paper", trader_path="", account_id=""),
        output_path=tmp_path / "qmt_smoke_test.md",
        connect=False,
    )
    statuses = {check.name: check.status for check in result.checks}

    assert result.failed_count == 0
    assert statuses["sqlite.database"] == "PASS"
    assert statuses["qmt.connect"] == "WARN"
    assert result.markdown_path.read_text(encoding="utf-8").startswith("# QMT Smoke Test")


def test_qmt_smoke_test_connects_and_queries_trader(tmp_path) -> None:
    trader = _SmokeTrader()
    result = run_qmt_smoke_test(
        data_config=_data_config(tmp_path),
        strategy_config=_strategy_config(mode="live", trader_path="C:/qmt/userdata", account_id="test-account"),
        output_path=None,
        connect=True,
        trader=trader,
    )
    statuses = {check.name: check.status for check in result.checks}

    assert trader.connected is True
    assert result.failed_count == 0
    assert statuses["qmt.connect"] == "PASS"
    assert statuses["qmt.positions"] == "PASS"
    assert statuses["qmt.orders"] == "PASS"
    assert statuses["qmt.fills"] == "PASS"


def test_qmt_smoke_test_reports_query_failure(tmp_path) -> None:
    result = run_qmt_smoke_test(
        data_config=_data_config(tmp_path),
        strategy_config=_strategy_config(mode="live", trader_path="C:/qmt/userdata", account_id="test-account"),
        output_path=None,
        connect=True,
        trader=_SmokeTrader(fail_orders=True),
    )
    checks = {check.name: check for check in result.checks}

    assert result.failed_count == 1
    assert checks["qmt.orders"].status == "FAIL"
    assert "orders failed" in checks["qmt.orders"].detail


def test_render_qmt_smoke_markdown_escapes_pipes() -> None:
    result = run_qmt_smoke_test(
        data_config={"storage": {"sqlite_path": ":memory:", "parquet_root": "missing"}},
        strategy_config=_strategy_config(mode="paper", trader_path="", account_id=""),
        output_path=None,
        connect=False,
    )

    markdown = render_qmt_smoke_markdown(result)

    assert "| Status | Check | Detail |" in markdown


def _data_config(tmp_path) -> dict[str, object]:
    return {
        "storage": {
            "sqlite_path": str(tmp_path / "tail_strategy.db"),
            "parquet_root": str(tmp_path / "parquet"),
        }
    }


def _strategy_config(*, mode: str, trader_path: str, account_id: str) -> dict[str, object]:
    return {
        "trading": {
            "mode": mode,
            "strategy_name": "tail_strategy_qmt",
            "account_equity": 100000.0 if mode == "live" else None,
            "qmt": {
                "trader_path": trader_path,
                "account_id": account_id,
                "session_id": 1,
            },
        }
    }


class _SmokeTrader:
    def __init__(self, *, fail_orders: bool = False) -> None:
        self.connected = False
        self.fail_orders = fail_orders

    def connect(self) -> None:
        self.connected = True

    def submit_order(self, request):
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> bool:
        return True

    def query_orders(self):
        if self.fail_orders:
            raise RuntimeError("orders failed")
        return [
            QmtOrderSnapshot(
                broker_order_id="1",
                symbol="000001.SZ",
                side=QmtOrderSide.BUY,
                status=QmtOrderStatus.SUBMITTED,
            )
        ]

    def query_fills(self):
        return [
            QmtFillSnapshot(
                broker_order_id="1",
                symbol="000001.SZ",
                side=QmtOrderSide.BUY,
                quantity=100.0,
                price=10.0,
            )
        ]

    def query_positions(self):
        return [QmtPositionSnapshot(symbol="000001.SZ", quantity=100.0)]
