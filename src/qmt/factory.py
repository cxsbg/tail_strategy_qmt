from __future__ import annotations

from qmt.trader import QmtTrader
from qmt.xtquant_trader_adapter import XtQuantTraderAdapter


def build_xt_trader(
    *,
    trader_path: str,
    account_id: str,
    session_id: int = 1,
    strategy_name: str = "tail_strategy_qmt",
) -> QmtTrader:
    return XtQuantTraderAdapter(
        trader_path=trader_path,
        account_id=account_id,
        session_id=session_id,
        strategy_name=strategy_name,
    )
