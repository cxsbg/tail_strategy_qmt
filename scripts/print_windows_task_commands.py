from __future__ import annotations

import argparse
from pathlib import Path

from scripts._bootstrap import ensure_src_path

ensure_src_path()

from trading.deploy import build_windows_task_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print Windows Task Scheduler commands for trading automation.")
    parser.add_argument("--workspace", default=str(Path.cwd()))
    parser.add_argument("--env-name", default="stock")
    parser.add_argument("--task-prefix", default="TailStrategyQMT")
    parser.add_argument("--data-config", default="config/data_source.yaml")
    parser.add_argument("--strategy-config", default="config/strategy.live.yaml")
    parser.add_argument("--cycle-time", default="14:50")
    parser.add_argument("--health-time", default="15:05")
    parser.add_argument("--submit", action="store_true", help="Generate live-submit cycle command.")
    parser.add_argument("--apply-positions", action="store_true")
    parser.add_argument("--sync-attempts", type=int, default=3)
    parser.add_argument("--sync-interval-seconds", type=int, default=20)
    parser.add_argument("--max-age-hours", type=int, default=12)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    commands = build_windows_task_commands(
        workspace_path=args.workspace,
        env_name=args.env_name,
        task_prefix=args.task_prefix,
        data_config=args.data_config,
        strategy_config=args.strategy_config,
        cycle_time=args.cycle_time,
        health_time=args.health_time,
        submit=args.submit,
        apply_positions=args.apply_positions,
        sync_attempts=args.sync_attempts,
        sync_interval_seconds=args.sync_interval_seconds,
        max_age_hours=args.max_age_hours,
    )
    print("# Cycle task")
    print(commands.cycle_command)
    print()
    print("# Health task")
    print(commands.health_command)


if __name__ == "__main__":
    main()
