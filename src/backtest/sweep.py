from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Iterable

from backtest.simple import run_decision_backtest
from storage.parquet import ParquetStorage
from utils.exceptions import StorageError


SWEEP_COLUMNS = [
    "holding_days",
    "stop_loss_pct",
    "take_profit_pct",
    "max_gross_exposure",
    "decision_count",
    "trade_count",
    "skipped_count",
    "portfolio_skipped_count",
    "win_rate",
    "avg_net_return",
    "total_weighted_net_return",
    "compounded_return",
    "final_equity",
    "max_drawdown",
    "score",
]


@dataclass(frozen=True)
class BacktestSweepResult:
    output_path: Path
    run_count: int
    best_score: float | None


def run_backtest_sweep(
    decisions: object,
    *,
    storage: ParquetStorage,
    base_config: dict[str, Any],
    holding_days_values: Iterable[int],
    stop_loss_values: Iterable[float],
    take_profit_values: Iterable[float],
    max_gross_exposure_values: Iterable[float],
    start_date: str | None = None,
    end_date: str | None = None,
) -> object:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to run backtest sweeps.") from exc

    if not isinstance(decisions, pd.DataFrame):
        raise StorageError("run_backtest_sweep expects decisions to be a pandas DataFrame.")

    rows: list[dict[str, object]] = []
    for holding_days, stop_loss, take_profit, max_exposure in product(
        holding_days_values,
        stop_loss_values,
        take_profit_values,
        max_gross_exposure_values,
    ):
        summary = _run_one(
            decisions,
            storage=storage,
            base_config=base_config,
            holding_days=int(holding_days),
            stop_loss_pct=float(stop_loss),
            take_profit_pct=float(take_profit),
            max_gross_exposure=float(max_exposure),
            start_date=start_date,
            end_date=end_date,
        )
        rows.append(
            {
                "holding_days": int(holding_days),
                "stop_loss_pct": float(stop_loss),
                "take_profit_pct": float(take_profit),
                "max_gross_exposure": float(max_exposure),
                **summary,
                "score": _score_summary(summary),
            }
        )

    if not rows:
        return pd.DataFrame(columns=SWEEP_COLUMNS)
    return (
        pd.DataFrame(rows, columns=SWEEP_COLUMNS)
        .sort_values(["score", "compounded_return", "max_drawdown", "win_rate"], ascending=[False, False, False, False])
        .reset_index(drop=True)
    )


def build_backtest_sweep(
    *,
    decisions_path: str | Path,
    parquet_root: str | Path,
    output_path: str | Path,
    base_config: dict[str, Any],
    holding_days_values: Iterable[int],
    stop_loss_values: Iterable[float],
    take_profit_values: Iterable[float],
    max_gross_exposure_values: Iterable[float],
    start_date: str | None = None,
    end_date: str | None = None,
) -> BacktestSweepResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build backtest sweeps.") from exc

    decisions = pd.read_parquet(decisions_path)
    result = run_backtest_sweep(
        decisions,
        storage=ParquetStorage(parquet_root),
        base_config=base_config,
        holding_days_values=holding_days_values,
        stop_loss_values=stop_loss_values,
        take_profit_values=take_profit_values,
        max_gross_exposure_values=max_gross_exposure_values,
        start_date=start_date,
        end_date=end_date,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(path, index=False, encoding="utf-8")
    best_score = None if result.empty else float(result.iloc[0]["score"])
    return BacktestSweepResult(output_path=path, run_count=len(result), best_score=best_score)


def _run_one(
    decisions: object,
    *,
    storage: ParquetStorage,
    base_config: dict[str, Any],
    holding_days: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_gross_exposure: float,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, object]:
    exit_config = dict(base_config.get("exit", {}))
    exit_config["stop_loss_pct"] = stop_loss_pct
    exit_config["take_profit_pct"] = take_profit_pct

    portfolio_config = dict(base_config.get("portfolio", {}))
    portfolio_config["max_gross_exposure"] = max_gross_exposure

    _, summary = run_decision_backtest(
        decisions,
        storage=storage,
        holding_days=holding_days,
        cost_config=base_config.get("cost", {}),
        exit_config=exit_config,
        limit_config=base_config.get("limit", {}),
        portfolio_config=portfolio_config,
        initial_equity=float(base_config.get("initial_equity", 1.0)),
        start_date=start_date,
        end_date=end_date,
    )
    return {column: summary[column] for column in SWEEP_COLUMNS if column in summary}


def _score_summary(summary: dict[str, object]) -> float:
    compounded = float(summary.get("compounded_return", 0.0))
    drawdown = abs(float(summary.get("max_drawdown", 0.0)))
    win_rate = float(summary.get("win_rate", 0.0))
    trade_count = int(summary.get("trade_count", 0))
    if trade_count == 0:
        return -999.0
    return round(compounded - drawdown * 0.5 + win_rate * 0.05, 6)
