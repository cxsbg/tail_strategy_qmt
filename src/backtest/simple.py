from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.parquet import ParquetStorage
from utils.exceptions import StorageError


TRADE_COLUMNS = [
    "symbol",
    "decision_date",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "holding_days",
    "position_ratio",
    "score",
    "gross_return",
    "weighted_return",
]

SUMMARY_COLUMNS = [
    "decision_count",
    "trade_count",
    "skipped_count",
    "win_rate",
    "avg_return",
    "median_return",
    "total_weighted_return",
    "best_return",
    "worst_return",
]


@dataclass(frozen=True)
class BacktestResult:
    trades_path: Path
    summary_path: Path
    decision_count: int
    trade_count: int
    skipped_count: int


def run_decision_backtest(
    decisions: object,
    *,
    storage: ParquetStorage,
    holding_days: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[object, dict[str, object]]:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to run decision backtests.") from exc

    if not isinstance(decisions, pd.DataFrame):
        raise StorageError("run_decision_backtest expects decisions to be a pandas DataFrame.")
    _validate_decisions(decisions)
    if holding_days <= 0:
        raise StorageError("holding_days must be positive.")

    frame = decisions.copy()
    if start_date is not None:
        frame = frame.loc[frame["decision_date"] >= start_date].copy()
    if end_date is not None:
        frame = frame.loc[frame["decision_date"] <= end_date].copy()

    open_decisions = frame.loc[frame["action"] == "OPEN_POSITION"].sort_values(
        ["decision_date", "score", "symbol"],
        ascending=[True, False, True],
    )

    rows: list[dict[str, object]] = []
    skipped_count = 0
    daily_cache: dict[str, object] = {}
    for _, decision in open_decisions.iterrows():
        symbol = str(decision["symbol"])
        try:
            daily_frame = daily_cache.setdefault(symbol, _load_daily_frame(storage, symbol, pd))
        except StorageError:
            skipped_count += 1
            continue

        trade = _simulate_one_decision(
            decision,
            daily_frame=daily_frame,
            holding_days=holding_days,
            pd=pd,
        )
        if trade is None:
            skipped_count += 1
        else:
            rows.append(trade)

    trades = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    summary = _summary(decision_count=len(open_decisions), trades=trades, skipped_count=skipped_count)
    return trades, summary


def build_decision_backtest(
    *,
    decisions_path: str | Path,
    parquet_root: str | Path,
    trades_output_path: str | Path,
    summary_output_path: str | Path,
    holding_days: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
) -> BacktestResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build decision backtests.") from exc

    decisions = pd.read_parquet(decisions_path)
    trades, summary = run_decision_backtest(
        decisions,
        storage=ParquetStorage(parquet_root),
        holding_days=holding_days,
        start_date=start_date,
        end_date=end_date,
    )

    trades_path = Path(trades_output_path)
    summary_path = Path(summary_output_path)
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(trades_path, index=False)
    pd.DataFrame([summary], columns=SUMMARY_COLUMNS).to_csv(summary_path, index=False, encoding="utf-8")
    return BacktestResult(
        trades_path=trades_path,
        summary_path=summary_path,
        decision_count=int(summary["decision_count"]),
        trade_count=int(summary["trade_count"]),
        skipped_count=int(summary["skipped_count"]),
    )


def _simulate_one_decision(
    decision: object,
    *,
    daily_frame: object,
    holding_days: int,
    pd: object,
) -> dict[str, object] | None:
    future = daily_frame.loc[daily_frame["date"] > str(decision["decision_date"])].copy()
    if future.empty:
        return None

    entry_index = future.index[0]
    entry_row = daily_frame.loc[entry_index]
    exit_pos = min(daily_frame.index.get_loc(entry_index) + holding_days - 1, len(daily_frame) - 1)
    exit_row = daily_frame.iloc[exit_pos]
    entry_price = float(entry_row["open"])
    exit_price = float(exit_row["close"])
    if entry_price <= 0:
        return None

    gross_return = exit_price / entry_price - 1.0
    ratio = decision.get("suggested_position_ratio", 1.0)
    if pd.isna(ratio):
        ratio = 1.0
    score = decision.get("score")
    if pd.isna(score):
        score = None
    return {
        "symbol": decision["symbol"],
        "decision_date": decision["decision_date"],
        "entry_date": entry_row["date"],
        "exit_date": exit_row["date"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "holding_days": int(daily_frame.index.get_loc(exit_row.name) - daily_frame.index.get_loc(entry_index) + 1),
        "position_ratio": float(ratio),
        "score": score,
        "gross_return": gross_return,
        "weighted_return": gross_return * float(ratio),
    }


def _summary(*, decision_count: int, trades: object, skipped_count: int) -> dict[str, object]:
    if trades.empty:
        return {
            "decision_count": decision_count,
            "trade_count": 0,
            "skipped_count": skipped_count,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "median_return": 0.0,
            "total_weighted_return": 0.0,
            "best_return": 0.0,
            "worst_return": 0.0,
        }
    returns = trades["gross_return"]
    return {
        "decision_count": decision_count,
        "trade_count": len(trades),
        "skipped_count": skipped_count,
        "win_rate": float((returns > 0).mean()),
        "avg_return": float(returns.mean()),
        "median_return": float(returns.median()),
        "total_weighted_return": float(trades["weighted_return"].sum()),
        "best_return": float(returns.max()),
        "worst_return": float(returns.min()),
    }


def _load_daily_frame(storage: ParquetStorage, symbol: str, pd: object) -> object:
    frame = storage.read_frame("daily", symbol)
    if not isinstance(frame, pd.DataFrame):
        raise StorageError("Daily cache must be a pandas DataFrame.")
    missing = {"symbol", "date", "open", "close"} - set(frame.columns)
    if missing:
        raise StorageError(f"Daily frame missing required columns: {', '.join(sorted(missing))}")
    return frame.sort_values("date").reset_index(drop=True)


def _validate_decisions(decisions: object) -> None:
    required = {"symbol", "decision_date", "action", "score", "suggested_position_ratio"}
    missing = required - set(decisions.columns)
    if missing:
        raise StorageError(f"Decision frame missing required columns: {', '.join(sorted(missing))}")
