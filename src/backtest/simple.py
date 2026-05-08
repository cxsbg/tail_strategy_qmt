from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    "exit_reason",
    "holding_days",
    "position_ratio",
    "score",
    "gross_return",
    "net_return",
    "weighted_return",
    "weighted_net_return",
    "cost_rate",
]

SUMMARY_COLUMNS = [
    "decision_count",
    "trade_count",
    "skipped_count",
    "stop_loss_count",
    "take_profit_count",
    "time_exit_count",
    "win_rate",
    "avg_return",
    "avg_net_return",
    "median_return",
    "median_net_return",
    "total_weighted_return",
    "total_weighted_net_return",
    "best_return",
    "worst_return",
    "best_net_return",
    "worst_net_return",
]


@dataclass(frozen=True)
class BacktestResult:
    trades_path: Path
    summary_path: Path
    report_path: Path | None
    decision_count: int
    trade_count: int
    skipped_count: int


def run_decision_backtest(
    decisions: object,
    *,
    storage: ParquetStorage,
    holding_days: int = 5,
    cost_config: dict[str, Any] | None = None,
    exit_config: dict[str, Any] | None = None,
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
    costs = _normalize_cost_config(cost_config)
    exits = _normalize_exit_config(exit_config)

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
            cost_config=costs,
            exit_config=exits,
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
    report_output_path: str | Path | None = None,
    holding_days: int = 5,
    cost_config: dict[str, Any] | None = None,
    exit_config: dict[str, Any] | None = None,
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
        cost_config=cost_config,
        exit_config=exit_config,
        start_date=start_date,
        end_date=end_date,
    )

    trades_path = Path(trades_output_path)
    summary_path = Path(summary_output_path)
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(trades_path, index=False)
    pd.DataFrame([summary], columns=SUMMARY_COLUMNS).to_csv(summary_path, index=False, encoding="utf-8")
    report_path = Path(report_output_path) if report_output_path is not None else None
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_backtest_markdown(summary=summary, trades=trades),
            encoding="utf-8",
        )
    return BacktestResult(
        trades_path=trades_path,
        summary_path=summary_path,
        report_path=report_path,
        decision_count=int(summary["decision_count"]),
        trade_count=int(summary["trade_count"]),
        skipped_count=int(summary["skipped_count"]),
    )


def _simulate_one_decision(
    decision: object,
    *,
    daily_frame: object,
    holding_days: int,
    cost_config: dict[str, float],
    exit_config: dict[str, float],
    pd: object,
) -> dict[str, object] | None:
    future = daily_frame.loc[daily_frame["date"] > str(decision["decision_date"])].copy()
    if future.empty:
        return None

    entry_index = future.index[0]
    entry_row = daily_frame.loc[entry_index]
    entry_price = float(entry_row["open"])
    if entry_price <= 0:
        return None

    entry_pos = daily_frame.index.get_loc(entry_index)
    max_exit_pos = min(entry_pos + holding_days - 1, len(daily_frame) - 1)
    exit_row, exit_price, exit_reason = _resolve_exit(
        daily_frame=daily_frame,
        entry_pos=entry_pos,
        max_exit_pos=max_exit_pos,
        entry_price=entry_price,
        exit_config=exit_config,
    )

    gross_return = exit_price / entry_price - 1.0
    entry_cost_rate = cost_config["slippage_rate"] + cost_config["commission_rate"]
    exit_cost_rate = cost_config["slippage_rate"] + cost_config["commission_rate"] + cost_config["stamp_tax_rate"]
    cost_rate = entry_cost_rate + exit_cost_rate
    net_return = (exit_price * (1.0 - exit_cost_rate)) / (entry_price * (1.0 + entry_cost_rate)) - 1.0
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
        "exit_reason": exit_reason,
        "holding_days": int(daily_frame.index.get_loc(exit_row.name) - daily_frame.index.get_loc(entry_index) + 1),
        "position_ratio": float(ratio),
        "score": score,
        "gross_return": gross_return,
        "net_return": net_return,
        "weighted_return": gross_return * float(ratio),
        "weighted_net_return": net_return * float(ratio),
        "cost_rate": cost_rate,
    }


def _summary(*, decision_count: int, trades: object, skipped_count: int) -> dict[str, object]:
    if trades.empty:
        return {
            "decision_count": decision_count,
            "trade_count": 0,
            "skipped_count": skipped_count,
            "stop_loss_count": 0,
            "take_profit_count": 0,
            "time_exit_count": 0,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "avg_net_return": 0.0,
            "median_return": 0.0,
            "median_net_return": 0.0,
            "total_weighted_return": 0.0,
            "total_weighted_net_return": 0.0,
            "best_return": 0.0,
            "worst_return": 0.0,
            "best_net_return": 0.0,
            "worst_net_return": 0.0,
        }
    returns = trades["gross_return"]
    net_returns = trades["net_return"]
    exit_counts = trades["exit_reason"].value_counts()
    return {
        "decision_count": decision_count,
        "trade_count": len(trades),
        "skipped_count": skipped_count,
        "stop_loss_count": int(exit_counts.get("stop_loss", 0)),
        "take_profit_count": int(exit_counts.get("take_profit", 0)),
        "time_exit_count": int(exit_counts.get("time_exit", 0)),
        "win_rate": float((net_returns > 0).mean()),
        "avg_return": float(returns.mean()),
        "avg_net_return": float(net_returns.mean()),
        "median_return": float(returns.median()),
        "median_net_return": float(net_returns.median()),
        "total_weighted_return": float(trades["weighted_return"].sum()),
        "total_weighted_net_return": float(trades["weighted_net_return"].sum()),
        "best_return": float(returns.max()),
        "worst_return": float(returns.min()),
        "best_net_return": float(net_returns.max()),
        "worst_net_return": float(net_returns.min()),
    }


def render_backtest_markdown(*, summary: dict[str, object], trades: object) -> str:
    lines: list[str] = [
        "# Tail Strategy Backtest Report",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Decisions: {int(summary['decision_count'])}",
        f"- Trades: {int(summary['trade_count'])}",
        f"- Skipped: {int(summary['skipped_count'])}",
        f"- Stop loss exits: {int(summary['stop_loss_count'])}",
        f"- Take profit exits: {int(summary['take_profit_count'])}",
        f"- Time exits: {int(summary['time_exit_count'])}",
        f"- Win rate: {_format_pct(summary['win_rate'])}",
        f"- Avg gross return: {_format_pct(summary['avg_return'])}",
        f"- Avg net return: {_format_pct(summary['avg_net_return'])}",
        f"- Total weighted net return: {_format_pct(summary['total_weighted_net_return'])}",
        f"- Best net return: {_format_pct(summary['best_net_return'])}",
        f"- Worst net return: {_format_pct(summary['worst_net_return'])}",
        "",
        "## Trades",
        "",
    ]
    lines.extend(_trade_lines(trades))
    lines.append("")
    return "\n".join(lines)


def _trade_lines(trades: object) -> list[str]:
    if trades.empty:
        return ["No simulated trades."]
    lines = ["| Symbol | Decision | Entry | Exit | Reason | Gross | Net | Weight | Score |"]
    lines.append("|---|---|---|---|---|---:|---:|---:|---:|")
    for _, row in trades.head(50).iterrows():
        lines.append(
            "| {symbol} | {decision_date} | {entry_date} @ {entry_price:.3f} | {exit_date} @ {exit_price:.3f} | {reason} | {gross} | {net} | {weight:.4f} | {score} |".format(
                symbol=row["symbol"],
                decision_date=row["decision_date"],
                entry_date=row["entry_date"],
                entry_price=float(row["entry_price"]),
                exit_date=row["exit_date"],
                exit_price=float(row["exit_price"]),
                reason=row.get("exit_reason", ""),
                gross=_format_pct(row["gross_return"]),
                net=_format_pct(row["net_return"]),
                weight=float(row["position_ratio"]),
                score=_format_number(row.get("score")),
            )
        )
    return lines


def _normalize_cost_config(cost_config: dict[str, Any] | None) -> dict[str, float]:
    config = cost_config or {}
    return {
        "slippage_rate": max(0.0, float(config.get("slippage_rate", 0.0))),
        "commission_rate": max(0.0, float(config.get("commission_rate", 0.0))),
        "stamp_tax_rate": max(0.0, float(config.get("stamp_tax_rate", 0.0))),
    }


def _normalize_exit_config(exit_config: dict[str, Any] | None) -> dict[str, float]:
    config = exit_config or {}
    return {
        "stop_loss_pct": max(0.0, float(config.get("stop_loss_pct", 0.0))),
        "take_profit_pct": max(0.0, float(config.get("take_profit_pct", 0.0))),
    }


def _resolve_exit(
    *,
    daily_frame: object,
    entry_pos: int,
    max_exit_pos: int,
    entry_price: float,
    exit_config: dict[str, float],
) -> tuple[object, float, str]:
    stop_loss_pct = exit_config["stop_loss_pct"]
    take_profit_pct = exit_config["take_profit_pct"]
    stop_price = entry_price * (1.0 - stop_loss_pct) if stop_loss_pct > 0 else None
    take_profit_price = entry_price * (1.0 + take_profit_pct) if take_profit_pct > 0 else None

    for position in range(entry_pos, max_exit_pos + 1):
        row = daily_frame.iloc[position]
        if stop_price is not None and float(row["low"]) <= stop_price:
            return row, stop_price, "stop_loss"
        if take_profit_price is not None and float(row["high"]) >= take_profit_price:
            return row, take_profit_price, "take_profit"

    exit_row = daily_frame.iloc[max_exit_pos]
    return exit_row, float(exit_row["close"]), "time_exit"


def _format_pct(value: object) -> str:
    return f"{float(value):.2%}"


def _format_number(value: object) -> str:
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except ModuleNotFoundError:
        if value is None:
            return ""
    if value is None:
        return ""
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _load_daily_frame(storage: ParquetStorage, symbol: str, pd: object) -> object:
    frame = storage.read_frame("daily", symbol)
    if not isinstance(frame, pd.DataFrame):
        raise StorageError("Daily cache must be a pandas DataFrame.")
    missing = {"symbol", "date", "open", "high", "low", "close"} - set(frame.columns)
    if missing:
        raise StorageError(f"Daily frame missing required columns: {', '.join(sorted(missing))}")
    return frame.sort_values("date").reset_index(drop=True)


def _validate_decisions(decisions: object) -> None:
    required = {"symbol", "decision_date", "action", "score", "suggested_position_ratio"}
    missing = required - set(decisions.columns)
    if missing:
        raise StorageError(f"Decision frame missing required columns: {', '.join(sorted(missing))}")
