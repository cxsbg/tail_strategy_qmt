from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from storage.parquet import ParquetStorage
from utils.exceptions import StorageError
from utils.logging import get_logger


logger = get_logger(__name__)


TAIL_COLUMNS = [
    "symbol",
    "date",
    "tail_start_time",
    "tail_confirm_time",
    "close_tail_start",
    "close_tail_confirm",
    "close_end",
    "tail_return_1430_1500",
    "tail_return_1445_1500",
    "tail_volume",
    "confirm_tail_volume",
    "day_volume",
    "tail_volume_ratio",
    "confirm_tail_volume_ratio",
    "tail_confirmed",
    "failed_reasons",
]


@dataclass(frozen=True)
class TailConfirmationBuildResult:
    output_path: Path
    symbol_count: int
    row_count: int
    skipped_symbols: tuple[str, ...]


def compute_tail_confirmation(
    minute_frame: object,
    *,
    intraday_config: dict[str, object],
    trade_date: str | None = None,
) -> object:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas is required to compute intraday tail confirmation.") from exc

    if not isinstance(minute_frame, pd.DataFrame):
        raise StorageError("compute_tail_confirmation expects a pandas DataFrame.")
    _validate_minute_frame(minute_frame)

    frame = minute_frame.copy()
    frame["datetime"] = frame["datetime"].map(_format_minute_datetime)
    frame["date"] = frame["datetime"].str.slice(0, 8)
    frame["time"] = frame["datetime"].str.slice(8, 12)
    if trade_date is not None:
        frame = frame.loc[frame["date"] == trade_date].copy()
    if frame.empty:
        return _empty_tail_confirmation(pd)

    tail_start = _time_text(intraday_config.get("tail_start_time", "14:30"))
    tail_confirm = _time_text(intraday_config.get("tail_confirm_time", "14:45"))
    max_return_1430 = float(intraday_config.get("max_tail_return_1430_1500", 0.03))
    max_return_1445 = float(intraday_config.get("max_tail_return_1445_1500", 0.02))
    max_volume_ratio = float(intraday_config.get("max_tail_volume_ratio", 0.35))

    rows = []
    for (symbol, date), group in frame.sort_values("datetime").groupby(["symbol", "date"]):
        rows.append(
            _compute_one_day(
                symbol=symbol,
                date=date,
                group=group,
                tail_start=tail_start,
                tail_confirm=tail_confirm,
                max_return_1430=max_return_1430,
                max_return_1445=max_return_1445,
                max_volume_ratio=max_volume_ratio,
            )
        )
    return pd.DataFrame(rows, columns=TAIL_COLUMNS)


def build_tail_confirmations(
    *,
    symbols: Iterable[str],
    storage: ParquetStorage,
    output_path: str | Path,
    intraday_config: dict[str, object],
    trade_date: str | None = None,
) -> TailConfirmationBuildResult:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise StorageError("pandas and pyarrow are required to build tail confirmations.") from exc

    confirmation_frames = []
    skipped_symbols: list[str] = []
    for symbol in symbols:
        try:
            minute_frame = storage.read_frame("minute", symbol)
        except StorageError:
            logger.warning("Skip %s because minute parquet cache is missing.", symbol)
            skipped_symbols.append(symbol)
            continue
        confirmation_frames.append(
            compute_tail_confirmation(
                minute_frame,
                intraday_config=intraday_config,
                trade_date=trade_date,
            )
        )

    if confirmation_frames:
        result_frame = pd.concat(confirmation_frames, ignore_index=True)
        result_frame = result_frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    else:
        result_frame = pd.DataFrame(columns=TAIL_COLUMNS)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    result_frame.to_parquet(path, index=False)
    return TailConfirmationBuildResult(
        output_path=path,
        symbol_count=len(confirmation_frames),
        row_count=len(result_frame),
        skipped_symbols=tuple(skipped_symbols),
    )


def _compute_one_day(
    *,
    symbol: str,
    date: str,
    group: object,
    tail_start: str,
    tail_confirm: str,
    max_return_1430: float,
    max_return_1445: float,
    max_volume_ratio: float,
) -> dict[str, object]:
    tail_start_rows = group.loc[group["time"] >= tail_start]
    tail_confirm_rows = group.loc[group["time"] >= tail_confirm]
    day_volume = float(group["volume"].sum())
    reasons: list[str] = []

    if tail_start_rows.empty:
        return _failed_row(symbol, date, tail_start, tail_confirm, "missing_tail_start")
    if tail_confirm_rows.empty:
        return _failed_row(symbol, date, tail_start, tail_confirm, "missing_tail_confirm")

    start_close = float(tail_start_rows.iloc[0]["close"])
    confirm_close = float(tail_confirm_rows.iloc[0]["close"])
    end_close = float(group.iloc[-1]["close"])
    tail_return_1430 = _safe_return(end_close, start_close)
    tail_return_1445 = _safe_return(end_close, confirm_close)
    tail_volume = float(tail_start_rows["volume"].sum())
    confirm_tail_volume = float(tail_confirm_rows["volume"].sum())
    tail_volume_ratio = _safe_ratio(tail_volume, day_volume)
    confirm_tail_volume_ratio = _safe_ratio(confirm_tail_volume, day_volume)

    _require(reasons, tail_return_1430 <= max_return_1430, "tail_return_1430_1500")
    _require(reasons, tail_return_1445 <= max_return_1445, "tail_return_1445_1500")
    _require(reasons, tail_volume_ratio <= max_volume_ratio, "tail_volume_ratio")
    return {
        "symbol": symbol,
        "date": date,
        "tail_start_time": _colon_time(tail_start),
        "tail_confirm_time": _colon_time(tail_confirm),
        "close_tail_start": start_close,
        "close_tail_confirm": confirm_close,
        "close_end": end_close,
        "tail_return_1430_1500": tail_return_1430,
        "tail_return_1445_1500": tail_return_1445,
        "tail_volume": tail_volume,
        "confirm_tail_volume": confirm_tail_volume,
        "day_volume": day_volume,
        "tail_volume_ratio": tail_volume_ratio,
        "confirm_tail_volume_ratio": confirm_tail_volume_ratio,
        "tail_confirmed": len(reasons) == 0,
        "failed_reasons": ",".join(reasons),
    }


def _failed_row(symbol: str, date: str, tail_start: str, tail_confirm: str, reason: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": date,
        "tail_start_time": _colon_time(tail_start),
        "tail_confirm_time": _colon_time(tail_confirm),
        "close_tail_start": None,
        "close_tail_confirm": None,
        "close_end": None,
        "tail_return_1430_1500": None,
        "tail_return_1445_1500": None,
        "tail_volume": None,
        "confirm_tail_volume": None,
        "day_volume": None,
        "tail_volume_ratio": None,
        "confirm_tail_volume_ratio": None,
        "tail_confirmed": False,
        "failed_reasons": reason,
    }


def _validate_minute_frame(frame: object) -> None:
    required = {"symbol", "datetime", "open", "high", "low", "close", "volume", "amount"}
    missing = required - set(frame.columns)
    if missing:
        raise StorageError(f"Minute frame missing required columns: {', '.join(sorted(missing))}")


def _format_minute_datetime(value: object) -> str:
    import pandas as pd

    text = str(value)
    if text.isdigit() and len(text) == 14:
        return text
    if text.isdigit() and len(text) == 12:
        return f"{text}00"
    if text.isdigit() and len(text) == 13:
        return pd.to_datetime(int(text), unit="ms").strftime("%Y%m%d%H%M%S")
    return pd.to_datetime(value).strftime("%Y%m%d%H%M%S")


def _time_text(value: object) -> str:
    return str(value).replace(":", "")[:4]


def _colon_time(value: str) -> str:
    return f"{value[:2]}:{value[2:4]}"


def _safe_return(end_value: float, start_value: float) -> float:
    if start_value == 0:
        return 0.0
    return end_value / start_value - 1


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _require(reasons: list[str], condition: bool, reason: str) -> None:
    if not condition:
        reasons.append(reason)


def _empty_tail_confirmation(pd: object) -> object:
    return pd.DataFrame(columns=TAIL_COLUMNS)
