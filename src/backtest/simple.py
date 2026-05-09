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
    "entry_blocked",
    "exit_deferred_days",
    "holding_days",
    "position_ratio",
    "score",
    "gross_return",
    "net_return",
    "weighted_return",
    "weighted_net_return",
    "cost_rate",
]

EQUITY_COLUMNS = [
    "date",
    "period_return",
    "equity",
    "drawdown",
    "trade_count",
]

SUMMARY_COLUMNS = [
    "decision_count",
    "trade_count",
    "skipped_count",
    "portfolio_skipped_count",
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
    "compounded_return",
    "final_equity",
    "max_drawdown",
    "best_return",
    "worst_return",
    "best_net_return",
    "worst_net_return",
]


@dataclass(frozen=True)
class BacktestResult:
    trades_path: Path
    summary_path: Path
    equity_path: Path | None
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
    limit_config: dict[str, Any] | None = None,
    portfolio_config: dict[str, Any] | None = None,
    initial_equity: float = 1.0,
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
    limits = _normalize_limit_config(limit_config)
    portfolio = _normalize_portfolio_config(portfolio_config)

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
    portfolio_skipped_count = 0
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
            limit_config=limits,
            pd=pd,
        )
        if trade is None:
            skipped_count += 1
        elif not _portfolio_allows_trade(trade, rows, portfolio):
            skipped_count += 1
            portfolio_skipped_count += 1
        else:
            rows.append(trade)

    trades = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    equity_curve = build_mark_to_market_equity_curve(
        trades,
        storage=storage,
        initial_equity=initial_equity,
        cost_config=costs,
    )
    summary = _summary(
        decision_count=len(open_decisions),
        trades=trades,
        skipped_count=skipped_count,
        portfolio_skipped_count=portfolio_skipped_count,
        equity_curve=equity_curve,
        initial_equity=initial_equity,
    )
    return trades, summary


def build_decision_backtest(
    *,
    decisions_path: str | Path,
    parquet_root: str | Path,
    trades_output_path: str | Path,
    summary_output_path: str | Path,
    equity_output_path: str | Path | None = None,
    report_output_path: str | Path | None = None,
    holding_days: int = 5,
    cost_config: dict[str, Any] | None = None,
    exit_config: dict[str, Any] | None = None,
    limit_config: dict[str, Any] | None = None,
    portfolio_config: dict[str, Any] | None = None,
    initial_equity: float = 1.0,
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
        limit_config=limit_config,
        portfolio_config=portfolio_config,
        initial_equity=initial_equity,
        start_date=start_date,
        end_date=end_date,
    )
    equity_curve = build_mark_to_market_equity_curve(
        trades,
        storage=ParquetStorage(parquet_root),
        initial_equity=initial_equity,
        cost_config=cost_config,
    )

    trades_path = Path(trades_output_path)
    summary_path = Path(summary_output_path)
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(trades_path, index=False)
    pd.DataFrame([summary], columns=SUMMARY_COLUMNS).to_csv(summary_path, index=False, encoding="utf-8")
    equity_path = Path(equity_output_path) if equity_output_path is not None else None
    if equity_path is not None:
        equity_path.parent.mkdir(parents=True, exist_ok=True)
        equity_curve.to_csv(equity_path, index=False, encoding="utf-8")
    report_path = Path(report_output_path) if report_output_path is not None else None
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_backtest_markdown(summary=summary, trades=trades, equity_curve=equity_curve),
            encoding="utf-8",
        )
    return BacktestResult(
        trades_path=trades_path,
        summary_path=summary_path,
        equity_path=equity_path,
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
    limit_config: dict[str, float | bool],
    pd: object,
) -> dict[str, object] | None:
    future = daily_frame.loc[daily_frame["date"] > str(decision["decision_date"])].copy()
    if future.empty:
        return None

    entry_index = future.index[0]
    entry_row = daily_frame.loc[entry_index]
    entry_pos = daily_frame.index.get_loc(entry_index)
    if _is_limit_up(daily_frame=daily_frame, position=entry_pos, limit_config=limit_config, price_field="open"):
        return None

    entry_price = float(entry_row["open"])
    if entry_price <= 0:
        return None

    max_exit_pos = min(entry_pos + holding_days - 1, len(daily_frame) - 1)
    exit_row, exit_price, exit_reason, exit_deferred_days = _resolve_exit(
        daily_frame=daily_frame,
        entry_pos=entry_pos,
        max_exit_pos=max_exit_pos,
        entry_price=entry_price,
        exit_config=exit_config,
        limit_config=limit_config,
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
        "entry_blocked": False,
        "exit_deferred_days": exit_deferred_days,
        "holding_days": int(daily_frame.index.get_loc(exit_row.name) - daily_frame.index.get_loc(entry_index) + 1),
        "position_ratio": float(ratio),
        "score": score,
        "gross_return": gross_return,
        "net_return": net_return,
        "weighted_return": gross_return * float(ratio),
        "weighted_net_return": net_return * float(ratio),
        "cost_rate": cost_rate,
    }


def build_equity_curve(trades: object, *, initial_equity: float = 1.0) -> object:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to build backtest equity curves.") from exc

    if not isinstance(trades, pd.DataFrame):
        raise StorageError("build_equity_curve expects trades to be a pandas DataFrame.")
    if initial_equity <= 0:
        raise StorageError("initial_equity must be positive.")
    if trades.empty:
        return pd.DataFrame(columns=EQUITY_COLUMNS)
    missing = {"exit_date", "weighted_net_return"} - set(trades.columns)
    if missing:
        raise StorageError(f"Trade frame missing required columns: {', '.join(sorted(missing))}")

    grouped = (
        trades.groupby("exit_date", as_index=False)
        .agg(period_return=("weighted_net_return", "sum"), trade_count=("symbol", "count"))
        .rename(columns={"exit_date": "date"})
        .sort_values("date")
        .reset_index(drop=True)
    )
    grouped["equity"] = initial_equity * (1.0 + grouped["period_return"]).cumprod()
    grouped["drawdown"] = grouped["equity"] / grouped["equity"].cummax() - 1.0
    return grouped[EQUITY_COLUMNS]


def build_mark_to_market_equity_curve(
    trades: object,
    *,
    storage: ParquetStorage,
    initial_equity: float = 1.0,
    cost_config: dict[str, Any] | None = None,
) -> object:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to build mark-to-market equity curves.") from exc

    if not isinstance(trades, pd.DataFrame):
        raise StorageError("build_mark_to_market_equity_curve expects trades to be a pandas DataFrame.")
    if initial_equity <= 0:
        raise StorageError("initial_equity must be positive.")
    if trades.empty:
        return pd.DataFrame(columns=EQUITY_COLUMNS)
    required = {"symbol", "entry_date", "exit_date", "entry_price", "position_ratio", "weighted_net_return"}
    missing = required - set(trades.columns)
    if missing:
        raise StorageError(f"Trade frame missing required columns: {', '.join(sorted(missing))}")

    costs = _normalize_cost_config(cost_config)
    daily_by_symbol: dict[str, object] = {}
    all_dates: set[str] = set()
    min_date = str(trades["entry_date"].min())
    max_date = str(trades["exit_date"].max())
    for symbol in sorted(set(trades["symbol"])):
        frame = _load_daily_frame(storage, str(symbol), pd)
        frame = frame.loc[(frame["date"] >= min_date) & (frame["date"] <= max_date)].copy()
        if frame.empty:
            continue
        daily_by_symbol[str(symbol)] = frame
        all_dates.update(str(date) for date in frame["date"])

    if not all_dates:
        return pd.DataFrame(columns=EQUITY_COLUMNS)

    rows: list[dict[str, object]] = []
    equity_values: list[float] = []
    for date in sorted(all_dates):
        contribution = 0.0
        active_count = 0
        for _, trade in trades.iterrows():
            symbol = str(trade["symbol"])
            if date < str(trade["entry_date"]):
                continue
            if date >= str(trade["exit_date"]):
                contribution += float(trade["weighted_net_return"])
                continue

            daily_frame = daily_by_symbol.get(symbol)
            if daily_frame is None:
                continue
            mark = daily_frame.loc[(daily_frame["date"] >= str(trade["entry_date"])) & (daily_frame["date"] <= date)]
            if mark.empty:
                continue
            active_count += 1
            mark_price = float(mark.iloc[-1]["close"])
            entry_price = float(trade["entry_price"])
            position_ratio = float(trade["position_ratio"])
            entry_cost_rate = costs["slippage_rate"] + costs["commission_rate"]
            unrealized_return = mark_price / (entry_price * (1.0 + entry_cost_rate)) - 1.0
            contribution += unrealized_return * position_ratio

        equity = initial_equity * (1.0 + contribution)
        equity_values.append(equity)
        previous_equity = equity_values[-2] if len(equity_values) > 1 else initial_equity
        period_return = equity / previous_equity - 1.0 if previous_equity else 0.0
        rows.append(
            {
                "date": date,
                "period_return": period_return,
                "equity": equity,
                "drawdown": 0.0,
                "trade_count": active_count,
            }
        )

    curve = pd.DataFrame(rows, columns=EQUITY_COLUMNS)
    curve["drawdown"] = curve["equity"] / curve["equity"].cummax() - 1.0
    return curve


def _summary(
    *,
    decision_count: int,
    trades: object,
    skipped_count: int,
    portfolio_skipped_count: int,
    equity_curve: object,
    initial_equity: float,
) -> dict[str, object]:
    if trades.empty:
        return {
            "decision_count": decision_count,
            "trade_count": 0,
            "skipped_count": skipped_count,
            "portfolio_skipped_count": portfolio_skipped_count,
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
            "compounded_return": 0.0,
            "final_equity": initial_equity,
            "max_drawdown": 0.0,
            "best_return": 0.0,
            "worst_return": 0.0,
            "best_net_return": 0.0,
            "worst_net_return": 0.0,
        }
    returns = trades["gross_return"]
    net_returns = trades["net_return"]
    final_equity = float(equity_curve.iloc[-1]["equity"]) if not equity_curve.empty else initial_equity
    compounded_return = final_equity / initial_equity - 1.0
    max_drawdown = float(equity_curve["drawdown"].min()) if not equity_curve.empty else 0.0
    return {
        "decision_count": decision_count,
        "trade_count": len(trades),
        "skipped_count": skipped_count,
        "portfolio_skipped_count": portfolio_skipped_count,
        "stop_loss_count": _reason_count(trades, "stop_loss"),
        "take_profit_count": _reason_count(trades, "take_profit"),
        "time_exit_count": _reason_count(trades, "time_exit"),
        "win_rate": float((net_returns > 0).mean()),
        "avg_return": float(returns.mean()),
        "avg_net_return": float(net_returns.mean()),
        "median_return": float(returns.median()),
        "median_net_return": float(net_returns.median()),
        "total_weighted_return": float(trades["weighted_return"].sum()),
        "total_weighted_net_return": float(trades["weighted_net_return"].sum()),
        "compounded_return": compounded_return,
        "final_equity": final_equity,
        "max_drawdown": max_drawdown,
        "best_return": float(returns.max()),
        "worst_return": float(returns.min()),
        "best_net_return": float(net_returns.max()),
        "worst_net_return": float(net_returns.min()),
    }


def render_backtest_markdown(*, summary: dict[str, object], trades: object, equity_curve: object | None = None) -> str:
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
        f"- Portfolio skipped: {int(summary['portfolio_skipped_count'])}",
        f"- Stop loss exits: {int(summary['stop_loss_count'])}",
        f"- Take profit exits: {int(summary['take_profit_count'])}",
        f"- Time exits: {int(summary['time_exit_count'])}",
        f"- Win rate: {_format_pct(summary['win_rate'])}",
        f"- Avg gross return: {_format_pct(summary['avg_return'])}",
        f"- Avg net return: {_format_pct(summary['avg_net_return'])}",
        f"- Total weighted net return: {_format_pct(summary['total_weighted_net_return'])}",
        f"- Compounded return: {_format_pct(summary['compounded_return'])}",
        f"- Final equity: {_format_number(summary['final_equity'])}",
        f"- Max drawdown: {_format_pct(summary['max_drawdown'])}",
        f"- Best net return: {_format_pct(summary['best_net_return'])}",
        f"- Worst net return: {_format_pct(summary['worst_net_return'])}",
        "",
        "## Equity Curve",
        "",
    ]
    lines.extend(_equity_lines(equity_curve))
    lines.extend(
        [
            "",
            "## Trades",
            "",
        ]
    )
    lines.extend(_trade_lines(trades))
    lines.append("")
    return "\n".join(lines)


def _equity_lines(equity_curve: object | None) -> list[str]:
    if equity_curve is None or equity_curve.empty:
        return ["No equity curve records."]
    lines = ["| Date | Period Return | Equity | Drawdown | Trades |"]
    lines.append("|---|---:|---:|---:|---:|")
    for _, row in equity_curve.tail(20).iterrows():
        lines.append(
            "| {date} | {period_return} | {equity} | {drawdown} | {trade_count} |".format(
                date=row["date"],
                period_return=_format_pct(row["period_return"]),
                equity=_format_number(row["equity"]),
                drawdown=_format_pct(row["drawdown"]),
                trade_count=int(row["trade_count"]),
            )
        )
    return lines


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


def _normalize_limit_config(limit_config: dict[str, Any] | None) -> dict[str, float | bool]:
    config = limit_config or {}
    return {
        "enabled": bool(config.get("enabled", True)),
        "limit_up_pct": max(0.0, float(config.get("limit_up_pct", 0.098))),
        "limit_down_pct": max(0.0, float(config.get("limit_down_pct", 0.098))),
    }


def _normalize_portfolio_config(portfolio_config: dict[str, Any] | None) -> dict[str, float | int | bool]:
    config = portfolio_config or {}
    return {
        "enabled": bool(config.get("enabled", True)),
        "max_gross_exposure": max(0.0, float(config.get("max_gross_exposure", 1.0))),
        "max_concurrent_positions": max(0, int(config.get("max_concurrent_positions", 999999))),
    }


def _portfolio_allows_trade(
    trade: dict[str, object],
    accepted_trades: list[dict[str, object]],
    portfolio_config: dict[str, float | int | bool],
) -> bool:
    if not bool(portfolio_config["enabled"]):
        return True

    entry_date = str(trade["entry_date"])
    active_trades = [
        item
        for item in accepted_trades
        if str(item["entry_date"]) <= entry_date <= str(item["exit_date"])
    ]
    next_exposure = sum(float(item["position_ratio"]) for item in active_trades) + float(trade["position_ratio"])
    next_positions = len(active_trades) + 1
    if next_exposure > float(portfolio_config["max_gross_exposure"]) + 1e-12:
        return False
    return next_positions <= int(portfolio_config["max_concurrent_positions"])


def _reason_count(trades: object, prefix: str) -> int:
    return int(trades["exit_reason"].fillna("").map(lambda reason: str(reason).startswith(prefix)).sum())


def _resolve_exit(
    *,
    daily_frame: object,
    entry_pos: int,
    max_exit_pos: int,
    entry_price: float,
    exit_config: dict[str, float],
    limit_config: dict[str, float | bool],
) -> tuple[object, float, str, int]:
    stop_loss_pct = exit_config["stop_loss_pct"]
    take_profit_pct = exit_config["take_profit_pct"]
    stop_price = entry_price * (1.0 - stop_loss_pct) if stop_loss_pct > 0 else None
    take_profit_price = entry_price * (1.0 + take_profit_pct) if take_profit_pct > 0 else None

    for position in range(entry_pos, max_exit_pos + 1):
        row = daily_frame.iloc[position]
        if stop_price is not None and float(row["low"]) <= stop_price:
            return _defer_exit_if_limit_down(
                daily_frame=daily_frame,
                trigger_pos=position,
                trigger_price=stop_price,
                trigger_reason="stop_loss",
                limit_config=limit_config,
            )
        if take_profit_price is not None and float(row["high"]) >= take_profit_price:
            return row, take_profit_price, "take_profit", 0

    return _defer_exit_if_limit_down(
        daily_frame=daily_frame,
        trigger_pos=max_exit_pos,
        trigger_price=float(daily_frame.iloc[max_exit_pos]["close"]),
        trigger_reason="time_exit",
        limit_config=limit_config,
    )


def _defer_exit_if_limit_down(
    *,
    daily_frame: object,
    trigger_pos: int,
    trigger_price: float,
    trigger_reason: str,
    limit_config: dict[str, float | bool],
) -> tuple[object, float, str, int]:
    for position in range(trigger_pos, len(daily_frame)):
        row = daily_frame.iloc[position]
        if not _is_limit_down(daily_frame=daily_frame, position=position, limit_config=limit_config):
            deferred_days = position - trigger_pos
            reason = trigger_reason if deferred_days == 0 else f"{trigger_reason}_deferred"
            price = trigger_price if deferred_days == 0 else float(row["close"])
            return row, price, reason, deferred_days

    row = daily_frame.iloc[-1]
    return row, float(row["close"]), f"{trigger_reason}_deferred", len(daily_frame) - 1 - trigger_pos


def _is_limit_up(
    *,
    daily_frame: object,
    position: int,
    limit_config: dict[str, float | bool],
    price_field: str = "close",
) -> bool:
    if not bool(limit_config["enabled"]):
        return False
    previous_close = _previous_close(daily_frame, position)
    if previous_close is None or previous_close <= 0:
        return False
    return float(daily_frame.iloc[position][price_field]) >= previous_close * (1.0 + float(limit_config["limit_up_pct"]))


def _is_limit_down(
    *,
    daily_frame: object,
    position: int,
    limit_config: dict[str, float | bool],
) -> bool:
    if not bool(limit_config["enabled"]):
        return False
    previous_close = _previous_close(daily_frame, position)
    if previous_close is None or previous_close <= 0:
        return False
    row = daily_frame.iloc[position]
    threshold = previous_close * (1.0 - float(limit_config["limit_down_pct"]))
    return float(row["close"]) <= threshold or float(row["open"]) <= threshold


def _previous_close(daily_frame: object, position: int) -> float | None:
    row = daily_frame.iloc[position]
    if "pre_close" in daily_frame.columns:
        try:
            import pandas as pd

            value = row["pre_close"]
            if not pd.isna(value):
                return float(value)
        except ModuleNotFoundError:
            value = row["pre_close"]
            if value is not None:
                return float(value)
    if position <= 0:
        return None
    return float(daily_frame.iloc[position - 1]["close"])



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
