from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from position import PositionRepository
from qmt.trader import QmtTrader
from storage.parquet import ParquetStorage
from storage.sqlite import SQLiteStore
from strategy.decisions import DecisionAction, DecisionRepository, StrategyDecision
from trading.execution import TradeExecutionRepository
from trading.submitter import LiveOrderSubmitter, PaperOrderSubmitter
from utils.exceptions import StorageError


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    PAPER_SUBMITTED = "PAPER_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    ALREADY_SUBMITTED = "ALREADY_SUBMITTED"


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class OrderDraft:
    id: int | None
    decision_id: int
    symbol: str
    trade_date: str
    side: OrderSide
    reference_price: float | None
    position_ratio: float
    status: OrderStatus
    block_reasons: str | None
    strategy_version: str | None
    created_at: str | None
    submitted_at: str | None


@dataclass(frozen=True)
class PreTradeCheck:
    id: int | None
    order_id: int
    decision_id: int
    symbol: str
    check_name: str
    status: CheckStatus
    message: str | None
    created_at: str | None


@dataclass(frozen=True)
class PreTradeResult:
    date: str
    decision_count: int
    draft_count: int
    ready_count: int
    blocked_count: int
    skipped_count: int
    paper_submitted_count: int
    submitted_count: int
    rejected_count: int
    already_submitted_count: int
    report_path: Path | None
    db_path: Path


class OrderDraftRepository:
    def __init__(self, store: SQLiteStore | str | Path) -> None:
        self.store = store if isinstance(store, SQLiteStore) else SQLiteStore(store)
        self.store.initialize()

    def get_by_decision_id(self, decision_id: int) -> OrderDraft | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM order_drafts WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        return _row_to_draft(row) if row else None

    def get_draft(self, order_id: int) -> OrderDraft | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM order_drafts WHERE id = ?", (order_id,)).fetchone()
        return _row_to_draft(row) if row else None

    def upsert_draft(self, draft: OrderDraft) -> int:
        sql = """
        INSERT INTO order_drafts (
            decision_id, symbol, trade_date, side, reference_price, position_ratio,
            status, block_reasons, strategy_version, created_at, submitted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(decision_id) DO UPDATE SET
            symbol = excluded.symbol,
            trade_date = excluded.trade_date,
            side = excluded.side,
            reference_price = excluded.reference_price,
            position_ratio = excluded.position_ratio,
            status = excluded.status,
            block_reasons = excluded.block_reasons,
            strategy_version = excluded.strategy_version,
            created_at = excluded.created_at,
            submitted_at = excluded.submitted_at
        """
        with self.store.connect() as conn:
            conn.execute(sql, _draft_values(draft))
            conn.commit()
            row = conn.execute(
                "SELECT id FROM order_drafts WHERE decision_id = ?",
                (draft.decision_id,),
            ).fetchone()
            return int(row["id"])

    def update_status(
        self,
        order_id: int,
        *,
        status: OrderStatus,
        submitted_at: str | None,
    ) -> None:
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE order_drafts SET status = ?, submitted_at = ? WHERE id = ?",
                (status.value, submitted_at, order_id),
            )
            conn.commit()

    def replace_checks(self, order_id: int, checks: Iterable[PreTradeCheck]) -> None:
        with self.store.connect() as conn:
            conn.execute("DELETE FROM pre_trade_checks WHERE order_id = ?", (order_id,))
            conn.executemany(
                """
                INSERT INTO pre_trade_checks (
                    order_id, decision_id, symbol, check_name, status, message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [_check_values(check) for check in checks],
            )
            conn.commit()

    def list_drafts(self, *, trade_date: str | None = None) -> list[OrderDraft]:
        if trade_date is None:
            sql = "SELECT * FROM order_drafts ORDER BY id"
            params: tuple[object, ...] = ()
        else:
            sql = "SELECT * FROM order_drafts WHERE trade_date = ? ORDER BY id"
            params = (trade_date,)
        with self.store.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_draft(row) for row in rows]

    def list_checks(self, *, trade_date: str | None = None) -> list[PreTradeCheck]:
        sql = """
        SELECT pre_trade_checks.*
        FROM pre_trade_checks
        JOIN order_drafts ON order_drafts.id = pre_trade_checks.order_id
        """
        params: tuple[object, ...] = ()
        if trade_date is not None:
            sql += " WHERE order_drafts.trade_date = ?"
            params = (trade_date,)
        sql += " ORDER BY pre_trade_checks.id"
        with self.store.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_check(row) for row in rows]


def run_pre_trade(
    *,
    db_path: str | Path,
    parquet_root: str | Path,
    strategy_config: dict[str, Any],
    trade_date: str,
    strategy_version: str = "rule-v0",
    report_path: str | Path | None = "outputs/pre_trade_report.md",
    submit: bool = True,
    trader: QmtTrader | None = None,
) -> PreTradeResult:
    decision_repository = DecisionRepository(db_path)
    draft_repository = OrderDraftRepository(db_path)
    execution_repository = TradeExecutionRepository(db_path)
    position_repository = PositionRepository(db_path)
    storage = ParquetStorage(parquet_root)
    trading_config = _trading_config(strategy_config)

    decisions = decision_repository.list_decisions(
        decision_date=trade_date,
        strategy_version=strategy_version,
    )
    skipped_count = 0
    already_submitted_count = 0

    for decision in decisions:
        side = _decision_side(decision)
        if side is None:
            skipped_count += 1
            continue
        if decision.id is None:
            skipped_count += 1
            continue

        existing = draft_repository.get_by_decision_id(decision.id)
        if existing is not None and existing.status in {OrderStatus.PAPER_SUBMITTED, OrderStatus.SUBMITTED}:
            already_submitted_count += 1
            continue

        draft, checks = _build_order_draft(
            decision=decision,
            side=side,
            position_repository=position_repository,
            storage=storage,
            strategy_config=strategy_config,
            trading_config=trading_config,
        )
        order_id = draft_repository.upsert_draft(draft)
        saved_draft = OrderDraft(
            id=order_id,
            decision_id=draft.decision_id,
            symbol=draft.symbol,
            trade_date=draft.trade_date,
            side=draft.side,
            reference_price=draft.reference_price,
            position_ratio=draft.position_ratio,
            status=draft.status,
            block_reasons=draft.block_reasons,
            strategy_version=draft.strategy_version,
            created_at=draft.created_at,
            submitted_at=draft.submitted_at,
        )
        draft_repository.replace_checks(
            order_id,
            [
                PreTradeCheck(
                    id=None,
                    order_id=order_id,
                    decision_id=check.decision_id,
                    symbol=check.symbol,
                    check_name=check.check_name,
                    status=check.status,
                    message=check.message,
                    created_at=check.created_at,
                )
                for check in checks
            ],
        )
        if submit and saved_draft.status == OrderStatus.READY:
            submit_result = _submitter(
                mode=str(trading_config["mode"]),
                execution_repository=execution_repository,
                trading_config=trading_config,
                trader=trader,
            ).submit(saved_draft)
            draft_repository.update_status(
                saved_draft.id,
                status=OrderStatus(submit_result.status),
                submitted_at=_now(),
            )

    drafts = draft_repository.list_drafts(trade_date=trade_date)
    markdown_path = Path(report_path) if report_path is not None else None
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render_pre_trade_markdown(
                trade_date=trade_date,
                drafts=drafts,
                checks=draft_repository.list_checks(trade_date=trade_date),
                trading_config=trading_config,
            ),
            encoding="utf-8",
        )

    return PreTradeResult(
        date=trade_date,
        decision_count=len(decisions),
        draft_count=len(drafts),
        ready_count=_count_status(drafts, OrderStatus.READY),
        blocked_count=_count_status(drafts, OrderStatus.BLOCKED),
        skipped_count=skipped_count,
        paper_submitted_count=_count_status(drafts, OrderStatus.PAPER_SUBMITTED),
        submitted_count=_count_status(drafts, OrderStatus.SUBMITTED),
        rejected_count=_count_status(drafts, OrderStatus.REJECTED),
        already_submitted_count=already_submitted_count,
        report_path=markdown_path,
        db_path=Path(db_path),
    )


def render_pre_trade_markdown(
    *,
    trade_date: str,
    drafts: Iterable[OrderDraft],
    checks: Iterable[PreTradeCheck],
    trading_config: dict[str, Any],
) -> str:
    draft_list = list(drafts)
    check_list = list(checks)
    lines = [
        f"# Pre Trade Risk Gate - {trade_date}",
        "",
        "## Summary",
        "",
        f"- Mode: {trading_config['mode']}",
        f"- Drafts: {len(draft_list)}",
        f"- Ready: {_count_status(draft_list, OrderStatus.READY)}",
        f"- Blocked: {_count_status(draft_list, OrderStatus.BLOCKED)}",
        f"- Paper submitted: {_count_status(draft_list, OrderStatus.PAPER_SUBMITTED)}",
        f"- Submitted: {_count_status(draft_list, OrderStatus.SUBMITTED)}",
        f"- Rejected: {_count_status(draft_list, OrderStatus.REJECTED)}",
        "",
        "## Orders",
        "",
        "| Status | Symbol | Side | Ref Price | Position Ratio | Reasons |",
        "|---|---|---:|---:|---:|---|",
    ]
    if not draft_list:
        lines.append("| - | - | - | - | - | no_order_drafts |")
    for draft in draft_list:
        lines.append(
            "| {status} | {symbol} | {side} | {price} | {ratio} | {reasons} |".format(
                status=draft.status.value,
                symbol=draft.symbol,
                side=draft.side.value,
                price=_fmt_price(draft.reference_price),
                ratio=_fmt_pct(draft.position_ratio),
                reasons=draft.block_reasons or "",
            )
        )
    lines.extend(["", "## Checks", "", "| Status | Symbol | Check | Message |", "|---|---|---|---|"])
    if not check_list:
        lines.append("| - | - | - | no_checks |")
    for check in check_list:
        lines.append(
            f"| {check.status.value} | {check.symbol} | {check.check_name} | {_escape_table(check.message or '')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _build_order_draft(
    *,
    decision: StrategyDecision,
    side: OrderSide,
    position_repository: PositionRepository,
    storage: ParquetStorage,
    strategy_config: dict[str, Any],
    trading_config: dict[str, Any],
) -> tuple[OrderDraft, list[PreTradeCheck]]:
    now = _now()
    checks: list[PreTradeCheck] = []
    reference_price, previous_close = _reference_prices(storage, decision.symbol, decision.decision_date, checks, decision)
    open_positions = position_repository.list_open_positions()
    open_position = position_repository.get_open_position_by_symbol(decision.symbol)
    ratio = _draft_ratio(decision, side, open_position, strategy_config)

    checks.extend(
        _position_checks(
            decision=decision,
            side=side,
            ratio=ratio,
            open_position=open_position,
            open_position_count=len(open_positions),
            current_exposure=sum(float(position.position_ratio) for position in open_positions),
            strategy_config=strategy_config,
            trading_config=trading_config,
        )
    )
    checks.extend(
        _price_limit_checks(
            decision=decision,
            side=side,
            reference_price=reference_price,
            previous_close=previous_close,
            trading_config=trading_config,
        )
    )
    status = _draft_status(checks, trading_config)
    block_reasons = ",".join(
        check.check_name
        for check in checks
        if check.status == CheckStatus.BLOCK or (check.status == CheckStatus.WARN and trading_config["warn_policy"] == "block")
    ) or None
    draft = OrderDraft(
        id=None,
        decision_id=int(decision.id or 0),
        symbol=decision.symbol,
        trade_date=decision.decision_date,
        side=side,
        reference_price=reference_price,
        position_ratio=ratio,
        status=status,
        block_reasons=block_reasons,
        strategy_version=decision.strategy_version,
        created_at=now,
        submitted_at=None,
    )
    return draft, checks


def _position_checks(
    *,
    decision: StrategyDecision,
    side: OrderSide,
    ratio: float,
    open_position: object,
    open_position_count: int,
    current_exposure: float,
    strategy_config: dict[str, Any],
    trading_config: dict[str, Any],
) -> list[PreTradeCheck]:
    checks: list[PreTradeCheck] = []
    if side == OrderSide.BUY:
        checks.append(
            _check(
                decision,
                "duplicate_position",
                CheckStatus.BLOCK if open_position is not None else CheckStatus.PASS,
                "open_position_exists" if open_position is not None else "no_open_position",
            )
        )
        max_order_ratio = float(trading_config["max_order_position_ratio"])
        checks.append(
            _check(
                decision,
                "max_order_position_ratio",
                CheckStatus.BLOCK if ratio > max_order_ratio else CheckStatus.PASS,
                f"ratio={ratio:.4f}; max={max_order_ratio:.4f}",
            )
        )
        max_total_ratio = float(trading_config["max_total_position_ratio"])
        projected_exposure = current_exposure + ratio
        checks.append(
            _check(
                decision,
                "max_total_position_ratio",
                CheckStatus.BLOCK if projected_exposure > max_total_ratio else CheckStatus.PASS,
                f"projected={projected_exposure:.4f}; max={max_total_ratio:.4f}",
            )
        )
        max_positions = int(trading_config.get("max_open_positions") or strategy_config.get("position", {}).get("max_total_positions", 999999))
        checks.append(
            _check(
                decision,
                "max_open_positions",
                CheckStatus.BLOCK if open_position_count + 1 > max_positions else CheckStatus.PASS,
                f"projected={open_position_count + 1}; max={max_positions}",
            )
        )
    else:
        checks.append(
            _check(
                decision,
                "sell_position_exists",
                CheckStatus.PASS if open_position is not None else CheckStatus.BLOCK,
                "open_position_found" if open_position is not None else "open_position_not_found",
            )
        )
    return checks


def _price_limit_checks(
    *,
    decision: StrategyDecision,
    side: OrderSide,
    reference_price: float | None,
    previous_close: float | None,
    trading_config: dict[str, Any],
) -> list[PreTradeCheck]:
    if not trading_config["block_if_price_limit"]:
        return [_check(decision, "price_limit", CheckStatus.PASS, "disabled")]
    if reference_price is None:
        return [_check(decision, "price_limit", CheckStatus.BLOCK, "reference_price_missing")]
    if previous_close is None:
        return [_check(decision, "price_limit", CheckStatus.WARN, "previous_close_missing")]

    if side == OrderSide.BUY:
        limit_price = previous_close * (1.0 + float(trading_config["limit_up_pct"]))
        status = CheckStatus.BLOCK if reference_price >= limit_price else CheckStatus.PASS
        return [_check(decision, "limit_up_buy", status, f"price={reference_price:.4f}; limit={limit_price:.4f}")]

    limit_price = previous_close * (1.0 - float(trading_config["limit_down_pct"]))
    status = CheckStatus.BLOCK if reference_price <= limit_price else CheckStatus.PASS
    return [_check(decision, "limit_down_sell", status, f"price={reference_price:.4f}; limit={limit_price:.4f}")]


def _reference_prices(
    storage: ParquetStorage,
    symbol: str,
    trade_date: str,
    checks: list[PreTradeCheck],
    decision: StrategyDecision,
) -> tuple[float | None, float | None]:
    try:
        frame = storage.read_frame("daily", symbol)
    except StorageError as exc:
        checks.append(_check(decision, "market_data", CheckStatus.BLOCK, str(exc)))
        return None, None

    if "date" not in frame.columns or "close" not in frame.columns:
        checks.append(_check(decision, "market_data", CheckStatus.BLOCK, "missing date or close column"))
        return None, None

    ordered = frame.sort_values("date").reset_index(drop=True)
    rows = ordered.loc[ordered["date"].astype(str) == str(trade_date)]
    if rows.empty:
        checks.append(_check(decision, "market_data", CheckStatus.BLOCK, f"missing close for {trade_date}"))
        return None, None

    index = int(rows.index[-1])
    reference_price = float(ordered.loc[index, "close"])
    previous_close = float(ordered.loc[index - 1, "close"]) if index > 0 else None
    checks.append(_check(decision, "market_data", CheckStatus.PASS, f"reference_price={reference_price:.4f}"))
    return reference_price, previous_close


def _draft_ratio(
    decision: StrategyDecision,
    side: OrderSide,
    open_position: object,
    strategy_config: dict[str, Any],
) -> float:
    if side == OrderSide.SELL and open_position is not None:
        return float(open_position.position_ratio)
    position_config = strategy_config.get("position", {})
    max_ratio = float(position_config.get("max_single_stock_ratio", 1.0))
    fallback_ratio = float(position_config.get("initial_position_ratio", max_ratio))
    raw_ratio = decision.suggested_position_ratio
    ratio = float(raw_ratio if raw_ratio is not None and raw_ratio > 0 else fallback_ratio)
    return max(0.0, ratio)


def _draft_status(checks: list[PreTradeCheck], trading_config: dict[str, Any]) -> OrderStatus:
    if any(check.status == CheckStatus.BLOCK for check in checks):
        return OrderStatus.BLOCKED
    if trading_config["warn_policy"] == "block" and any(check.status == CheckStatus.WARN for check in checks):
        return OrderStatus.BLOCKED
    return OrderStatus.READY


def _decision_side(decision: StrategyDecision) -> OrderSide | None:
    if decision.action == DecisionAction.OPEN_POSITION:
        return OrderSide.BUY
    if decision.action == DecisionAction.REDUCE_POSITION:
        return OrderSide.SELL
    return None


def _trading_config(strategy_config: dict[str, Any]) -> dict[str, Any]:
    position_config = strategy_config.get("position", {})
    trading_config = strategy_config.get("trading", {})
    return {
        "mode": str(trading_config.get("mode", "paper")),
        "warn_policy": str(trading_config.get("warn_policy", "block")),
        "max_order_position_ratio": float(
            trading_config.get("max_order_position_ratio", position_config.get("max_single_stock_ratio", 1.0))
        ),
        "max_total_position_ratio": float(trading_config.get("max_total_position_ratio", 1.0)),
        "max_open_positions": int(trading_config.get("max_open_positions", position_config.get("max_total_positions", 999999))),
        "block_if_price_limit": bool(trading_config.get("block_if_price_limit", True)),
        "limit_up_pct": float(trading_config.get("limit_up_pct", 0.098)),
        "limit_down_pct": float(trading_config.get("limit_down_pct", 0.098)),
        "order_value_base": trading_config.get("order_value_base"),
        "account_equity": trading_config.get("account_equity"),
        "order_lot_size": int(trading_config.get("order_lot_size", 100)),
        "strategy_name": str(trading_config.get("strategy_name", "tail_strategy_qmt")),
    }


def _submitter(
    *,
    mode: str,
    execution_repository: TradeExecutionRepository,
    trading_config: dict[str, Any],
    trader: QmtTrader | None,
) -> PaperOrderSubmitter | LiveOrderSubmitter:
    if mode == "paper":
        return PaperOrderSubmitter(
            execution_repository=execution_repository,
        )
    if mode == "live":
        if trader is None:
            raise ValueError("A QmtTrader is required when trading.mode is live.")
        return LiveOrderSubmitter(
            trader=trader,
            execution_repository=execution_repository,
            trading_config=trading_config,
        )
    raise ValueError(f"Unsupported trading.mode: {mode}")


def _check(
    decision: StrategyDecision,
    name: str,
    status: CheckStatus,
    message: str,
) -> PreTradeCheck:
    return PreTradeCheck(
        id=None,
        order_id=0,
        decision_id=int(decision.id or 0),
        symbol=decision.symbol,
        check_name=name,
        status=status,
        message=message,
        created_at=_now(),
    )


def _draft_values(draft: OrderDraft) -> tuple[object, ...]:
    return (
        draft.decision_id,
        draft.symbol,
        draft.trade_date,
        draft.side.value,
        draft.reference_price,
        draft.position_ratio,
        draft.status.value,
        draft.block_reasons,
        draft.strategy_version,
        draft.created_at,
        draft.submitted_at,
    )


def _check_values(check: PreTradeCheck) -> tuple[object, ...]:
    return (
        check.order_id,
        check.decision_id,
        check.symbol,
        check.check_name,
        check.status.value,
        check.message,
        check.created_at,
    )


def _row_to_draft(row: object) -> OrderDraft:
    return OrderDraft(
        id=row["id"],
        decision_id=row["decision_id"],
        symbol=row["symbol"],
        trade_date=row["trade_date"],
        side=OrderSide(row["side"]),
        reference_price=row["reference_price"],
        position_ratio=row["position_ratio"],
        status=OrderStatus(row["status"]),
        block_reasons=row["block_reasons"],
        strategy_version=row["strategy_version"],
        created_at=row["created_at"],
        submitted_at=row["submitted_at"],
    )


def _row_to_check(row: object) -> PreTradeCheck:
    return PreTradeCheck(
        id=row["id"],
        order_id=row["order_id"],
        decision_id=row["decision_id"],
        symbol=row["symbol"],
        check_name=row["check_name"],
        status=CheckStatus(row["status"]),
        message=row["message"],
        created_at=row["created_at"],
    )


def _count_status(drafts: Iterable[OrderDraft], status: OrderStatus) -> int:
    return sum(1 for draft in drafts if draft.status == status)


def _fmt_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
