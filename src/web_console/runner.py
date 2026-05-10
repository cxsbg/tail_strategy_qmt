from __future__ import annotations

import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ConsoleAction:
    id: str
    label: str
    description: str
    command: tuple[str, ...]
    dangerous: bool = False


@dataclass
class ConsoleJob:
    id: str
    action_id: str
    label: str
    status: str
    started_at: str
    finished_at: str | None = None
    return_code: int | None = None
    output: str = ""


def default_actions() -> dict[str, ConsoleAction]:
    return {
        "qmt_smoke": ConsoleAction(
            id="qmt_smoke",
            label="QMT 配置检查",
            description="不连接 QMT，只检查配置、SQLite 和本地目录。",
            command=("scripts.qmt_smoke_test",),
        ),
        "readiness": ConsoleAction(
            id="readiness",
            label="上线就绪报告",
            description="汇总配置、运行记录和关键报告产物。",
            command=("scripts.build_readiness_report",),
        ),
        "run_monitor": ConsoleAction(
            id="run_monitor",
            label="运行监控报告",
            description="生成最近交易循环运行记录报告。",
            command=("scripts.build_trading_run_report",),
        ),
        "health": ConsoleAction(
            id="health",
            label="运行健康检查",
            description="检查最近一次交易循环是否成功。",
            command=("scripts.check_trading_run_health",),
        ),
        "cycle_dry_run": ConsoleAction(
            id="cycle_dry_run",
            label="交易循环演练",
            description="执行交易循环但不提交订单。",
            command=("scripts.run_trading_cycle_scheduled", "--no-submit"),
        ),
        "windows_tasks": ConsoleAction(
            id="windows_tasks",
            label="生成任务计划命令",
            description="输出 Windows 任务计划程序命令，默认不下单。",
            command=("scripts.print_windows_task_commands",),
        ),
        "live_cycle": ConsoleAction(
            id="live_cycle",
            label="Live 交易循环",
            description="真实提交订单，必须显式确认后才能执行。",
            command=("scripts.run_trading_cycle_scheduled", "--apply-positions"),
            dangerous=True,
        ),
    }


class JobManager:
    def __init__(self, *, cwd: str | Path, actions: dict[str, ConsoleAction] | None = None) -> None:
        self.cwd = Path(cwd)
        self.actions = actions or default_actions()
        self.jobs: dict[str, ConsoleJob] = {}
        self._lock = threading.Lock()

    def list_actions(self) -> list[ConsoleAction]:
        return list(self.actions.values())

    def start(self, action_id: str, *, confirm_live: bool = False) -> ConsoleJob:
        if action_id not in self.actions:
            raise KeyError(action_id)
        action = self.actions[action_id]
        if action.dangerous and not confirm_live:
            raise PermissionError("live action requires confirm_live=true")

        job = ConsoleJob(
            id=str(uuid.uuid4()),
            action_id=action.id,
            label=action.label,
            status="RUNNING",
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        with self._lock:
            self.jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job.id, action), daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> ConsoleJob | None:
        with self._lock:
            return self.jobs.get(job_id)

    def latest(self, limit: int = 20) -> list[ConsoleJob]:
        with self._lock:
            return list(self.jobs.values())[-limit:][::-1]

    def _run(self, job_id: str, action: ConsoleAction) -> None:
        command = [sys.executable, "-m", *action.command]
        try:
            completed = subprocess.run(
                command,
                cwd=self.cwd,
                text=True,
                capture_output=True,
                timeout=600,
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            status = "SUCCESS" if completed.returncode == 0 else "FAILED"
            self._finish(job_id, status=status, return_code=completed.returncode, output=output)
        except Exception as exc:
            self._finish(job_id, status="FAILED", return_code=None, output=str(exc))

    def _finish(self, job_id: str, *, status: str, return_code: int | None, output: str) -> None:
        with self._lock:
            job = self.jobs[job_id]
            job.status = status
            job.return_code = return_code
            job.output = output[-12000:]
            job.finished_at = datetime.now().isoformat(timespec="seconds")
