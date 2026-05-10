from __future__ import annotations

from position import PositionRepository, PositionService
from qmt import QmtPositionSnapshot
from trading.reconcile import reconcile_positions, render_position_reconciliation_markdown


def test_reconcile_positions_reports_matches_and_mismatches(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    PositionService(PositionRepository(db_path), strategy_version="test-rule").open_position(
        symbol="000001.SZ",
        entry_date="20260508",
        entry_price=10.0,
        position_ratio=0.15,
        max_position_ratio=0.15,
    )
    PositionService(PositionRepository(db_path), strategy_version="test-rule").open_position(
        symbol="000002.SZ",
        entry_date="20260508",
        entry_price=20.0,
        position_ratio=0.10,
        max_position_ratio=0.10,
    )

    result = reconcile_positions(
        db_path=db_path,
        trader=_FakeTrader(
            positions=[
                QmtPositionSnapshot(symbol="000001.SZ", quantity=1000.0, market_value=10000.0),
                QmtPositionSnapshot(symbol="000003.SZ", quantity=500.0, market_value=15000.0),
            ]
        ),
        output_path=tmp_path / "position_reconciliation.md",
    )
    statuses = {item.symbol: item.status for item in result.items}

    assert statuses == {
        "000001.SZ": "MATCH",
        "000002.SZ": "MISSING_BROKER",
        "000003.SZ": "MISSING_LOCAL",
    }
    assert result.matched_count == 1
    assert result.mismatch_count == 2
    assert result.markdown_path.read_text(encoding="utf-8").startswith("# Position Reconciliation")


def test_render_position_reconciliation_markdown_handles_empty_result(tmp_path) -> None:
    result = reconcile_positions(
        db_path=tmp_path / "tail_strategy.db",
        trader=_FakeTrader(),
        output_path=None,
    )

    markdown = render_position_reconciliation_markdown(result)

    assert "- MATCH: 0" in markdown
    assert "| Status | Symbol |" in markdown


class _FakeTrader:
    def __init__(self, *, positions: list[QmtPositionSnapshot] | None = None) -> None:
        self.positions = positions or []

    def connect(self) -> None:
        return None

    def submit_order(self, request):
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> bool:
        return True

    def query_orders(self):
        return []

    def query_fills(self):
        return []

    def query_positions(self):
        return self.positions
