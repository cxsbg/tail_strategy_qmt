from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WindowsTaskCommands:
    cycle_command: str
    health_command: str


def build_windows_task_commands(
    *,
    workspace_path: str | Path,
    env_name: str = "stock",
    task_prefix: str = "TailStrategyQMT",
    strategy_config: str = "config/strategy.live.yaml",
    data_config: str = "config/data_source.yaml",
    cycle_time: str = "14:50",
    health_time: str = "15:05",
    submit: bool = False,
    apply_positions: bool = False,
    sync_attempts: int = 3,
    sync_interval_seconds: int = 20,
    max_age_hours: int = 12,
) -> WindowsTaskCommands:
    workspace = str(Path(workspace_path))
    cycle_args = [
        "python",
        "-m",
        "scripts.run_trading_cycle_scheduled",
        "--data-config",
        data_config,
        "--strategy-config",
        strategy_config,
        "--skip-weekend",
        "--sync-attempts",
        str(sync_attempts),
        "--sync-interval-seconds",
        str(sync_interval_seconds),
    ]
    if not submit:
        cycle_args.append("--no-submit")
    if apply_positions:
        cycle_args.append("--apply-positions")

    health_args = [
        "python",
        "-m",
        "scripts.check_trading_run_health",
        "--data-config",
        data_config,
        "--today",
        "--max-age-hours",
        str(max_age_hours),
        "--fail-on-warn",
    ]
    return WindowsTaskCommands(
        cycle_command=_schtasks_command(
            task_name=f"{task_prefix} Cycle",
            start_time=cycle_time,
            workspace=workspace,
            env_name=env_name,
            args=cycle_args,
        ),
        health_command=_schtasks_command(
            task_name=f"{task_prefix} Health",
            start_time=health_time,
            workspace=workspace,
            env_name=env_name,
            args=health_args,
        ),
    )


def _schtasks_command(
    *,
    task_name: str,
    start_time: str,
    workspace: str,
    env_name: str,
    args: list[str],
) -> str:
    task_action = f'cmd /c "cd /d {workspace} && conda run -n {env_name} {" ".join(args)}"'
    return (
        f'schtasks /Create /F /SC DAILY /ST {start_time} '
        f'/TN "{task_name}" /TR "{task_action}"'
    )
