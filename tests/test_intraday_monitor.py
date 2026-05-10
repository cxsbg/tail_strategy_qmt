from __future__ import annotations

from datetime import datetime

from trading.intraday_monitor import (
    monitor_config_from_strategy,
    render_intraday_monitor_markdown,
    run_intraday_monitor,
)


def test_monitor_config_from_strategy_uses_defaults_and_overrides() -> None:
    config = monitor_config_from_strategy({"monitor": {"tail_poll_seconds": 15, "order_start_time": "14:48"}})

    assert config.sell_poll_seconds == 60
    assert config.tail_poll_seconds == 15
    assert config.order_start_time == "14:48"


def test_intraday_monitor_runs_tail_and_execution_phases(tmp_path) -> None:
    times = iter(
        [
            datetime(2026, 5, 8, 14, 31),
            datetime(2026, 5, 8, 14, 50),
            datetime(2026, 5, 8, 15, 1),
        ]
    )
    sleeps: list[float] = []

    result = run_intraday_monitor(
        db_path=tmp_path / "tail_strategy.db",
        parquet_root=tmp_path / "parquet",
        strategy_config=_strategy_config(),
        trade_date="20260508",
        report_path=tmp_path / "intraday.md",
        now_fn=lambda: next(times),
        sleep_fn=sleeps.append,
        cycle_runner=_fake_cycle_runner,
    )

    assert [event.phase for event in result.events] == ["TAIL", "EXECUTION", "CLOSED"]
    assert result.cycle_count == 1
    assert sleeps == [30, 10]
    assert "Intraday Monitor Report" in result.report_path.read_text(encoding="utf-8")


def test_intraday_monitor_limited_rehearsal_stops_without_sleeping_forever(tmp_path) -> None:
    result = run_intraday_monitor(
        db_path=tmp_path / "tail_strategy.db",
        parquet_root=tmp_path / "parquet",
        strategy_config=_strategy_config(),
        trade_date="20260508",
        report_path=None,
        max_iterations=1,
        now_fn=lambda: datetime(2026, 5, 8, 9, 31),
        sleep_fn=lambda seconds: None,
    )

    assert result.events[-1].message == "max_iterations_reached"


def test_render_intraday_monitor_markdown_handles_empty_result(tmp_path) -> None:
    result = run_intraday_monitor(
        db_path=tmp_path / "tail_strategy.db",
        parquet_root=tmp_path / "parquet",
        strategy_config={"monitor": {"enabled": False}},
        trade_date="20260508",
        report_path=None,
    )

    markdown = render_intraday_monitor_markdown(result)

    assert "monitor_disabled" in markdown


def _strategy_config() -> dict[str, object]:
    return {
        "trading": {"mode": "paper"},
        "monitor": {
            "sell_start_time": "09:30",
            "tail_start_time": "14:30",
            "order_start_time": "14:50",
            "stop_time": "15:01",
            "sell_poll_seconds": 60,
            "tail_poll_seconds": 30,
            "execution_poll_seconds": 10,
        },
    }


def _fake_cycle_runner(**kwargs):
    class _PreTrade:
        draft_count = 1
        submitted_count = 0
        paper_submitted_count = 1
        blocked_count = 0
        rejected_count = 0

    class _Result:
        pre_trade = _PreTrade()
        broker_syncs = ()
        report_path = None
        db_path = kwargs["db_path"]

        @property
        def sync_count(self):
            return 0

        @property
        def total_fill_inserted_count(self):
            return 0

        @property
        def total_position_application_count(self):
            return 0

    return _Result()
