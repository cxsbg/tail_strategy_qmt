from __future__ import annotations

from trading.deploy import build_windows_task_commands


def test_build_windows_task_commands_defaults_to_no_submit() -> None:
    commands = build_windows_task_commands(
        workspace_path="C:/Users/lxj42/Documents/Codex/SSQMT",
        env_name="stock",
        cycle_time="14:50",
        health_time="15:05",
    )

    assert "schtasks /Create" in commands.cycle_command
    assert "/TN \"TailStrategyQMT Cycle\"" in commands.cycle_command
    assert "--no-submit" in commands.cycle_command
    assert "--strategy-config config/strategy.live.yaml" in commands.cycle_command
    assert "conda run -n stock" in commands.cycle_command
    assert "/ST 15:05" in commands.health_command
    assert "--fail-on-warn" in commands.health_command


def test_build_windows_task_commands_can_enable_live_submit_and_position_apply() -> None:
    commands = build_windows_task_commands(
        workspace_path="D:/SSQMT",
        submit=True,
        apply_positions=True,
        sync_attempts=5,
        sync_interval_seconds=10,
    )

    assert "--no-submit" not in commands.cycle_command
    assert "--apply-positions" in commands.cycle_command
    assert "--sync-attempts 5" in commands.cycle_command
    assert "--sync-interval-seconds 10" in commands.cycle_command
