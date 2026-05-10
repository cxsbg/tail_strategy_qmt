from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from web_console.runner import JobManager


class RunRequest(BaseModel):
    confirm_live: bool = False


def create_app(*, project_root: str | Path | None = None) -> FastAPI:
    root = Path(project_root) if project_root is not None else Path.cwd()
    manager = JobManager(cwd=root)
    app = FastAPI(title="Tail Strategy QMT Console")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _HTML

    @app.get("/api/actions")
    def actions() -> list[dict[str, object]]:
        return [
            {
                "id": action.id,
                "label": action.label,
                "description": action.description,
                "dangerous": action.dangerous,
            }
            for action in manager.list_actions()
        ]

    @app.post("/api/actions/{action_id}/run")
    def run_action(action_id: str, request: RunRequest) -> dict[str, object]:
        try:
            job = manager.start(action_id, confirm_live=request.confirm_live)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown action") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return _job_payload(job)

    @app.get("/api/jobs")
    def jobs() -> list[dict[str, object]]:
        return [_job_payload(job) for job in manager.latest()]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, object]:
        item = manager.get(job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return _job_payload(item)

    @app.get("/api/reports/{name}", response_class=PlainTextResponse)
    def report(name: str) -> str:
        if name not in _REPORTS:
            raise HTTPException(status_code=404, detail="unknown report")
        path = root / _REPORTS[name]
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"report not found: {path}")
        return path.read_text(encoding="utf-8")

    return app


def _job_payload(job) -> dict[str, object]:
    return {
        "id": job.id,
        "action_id": job.action_id,
        "label": job.label,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "return_code": job.return_code,
        "output": job.output,
    }


_REPORTS = {
    "qmt_smoke": Path("outputs/qmt_smoke_test.md"),
    "readiness": Path("outputs/readiness_report.md"),
    "readiness_strict": Path("outputs/readiness_report_strict.md"),
    "run_monitor": Path("outputs/trading_run_monitor.md"),
    "health": Path("outputs/trading_run_health.md"),
    "position_reconciliation": Path("outputs/position_reconciliation.md"),
    "trading_cycle": Path("outputs/trading_cycle_report.md"),
    "intraday_monitor": Path("outputs/intraday_monitor_report.md"),
}


_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tail Strategy QMT Console</title>
  <style>
    :root { color-scheme: light; font-family: "Microsoft YaHei", Arial, sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #1d2433; }
    header { background: #16324f; color: white; padding: 18px 28px; }
    h1 { margin: 0; font-size: 22px; font-weight: 650; }
    main { max-width: 1180px; margin: 0 auto; padding: 22px; display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 18px; }
    section { background: white; border: 1px solid #d8dee8; border-radius: 8px; padding: 16px; }
    h2 { margin: 0 0 12px; font-size: 17px; }
    .actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
    .action { border: 1px solid #d8dee8; border-radius: 8px; padding: 12px; background: #fbfcfd; }
    .action strong { display: block; margin-bottom: 6px; }
    .action p { margin: 0 0 10px; color: #5b6677; font-size: 13px; line-height: 1.45; }
    button { border: 0; border-radius: 6px; background: #1c6dd0; color: white; padding: 8px 11px; cursor: pointer; font-weight: 600; }
    button:hover { background: #1559ab; }
    button.danger { background: #b42318; }
    button.danger:hover { background: #8f1d14; }
    .reports button { margin: 0 8px 8px 0; background: #42526b; }
    .job { border-top: 1px solid #e5e9f0; padding: 10px 0; }
    .job:first-child { border-top: 0; }
    .status { font-weight: 700; }
    .SUCCESS { color: #147a3d; }
    .FAILED { color: #b42318; }
    .RUNNING { color: #9a5b00; }
    pre { white-space: pre-wrap; overflow: auto; background: #0f172a; color: #dbeafe; border-radius: 8px; padding: 12px; min-height: 260px; max-height: 560px; }
    .note { color: #5b6677; font-size: 13px; line-height: 1.5; }
    @media (max-width: 860px) { main { grid-template-columns: 1fr; padding: 14px; } }
  </style>
</head>
<body>
  <header>
    <h1>Tail Strategy QMT 控制台</h1>
  </header>
  <main>
    <section>
      <h2>操作</h2>
      <p class="note">默认按钮不会真实下单。红色 Live 按钮需要二次确认。</p>
      <div id="actions" class="actions"></div>
    </section>
    <section>
      <h2>报告</h2>
      <div class="reports">
        <button onclick="loadReport('qmt_smoke')">QMT 检查</button>
        <button onclick="loadReport('readiness')">上线就绪</button>
        <button onclick="loadReport('run_monitor')">运行监控</button>
        <button onclick="loadReport('health')">健康检查</button>
        <button onclick="loadReport('trading_cycle')">交易循环</button>
        <button onclick="loadReport('intraday_monitor')">盘中监控</button>
      </div>
      <pre id="report">选择一个报告查看内容。</pre>
    </section>
    <section>
      <h2>最近任务</h2>
      <div id="jobs"></div>
    </section>
    <section>
      <h2>任务输出</h2>
      <pre id="output">点击任务后显示输出。</pre>
    </section>
  </main>
  <script>
    async function api(path, options) {
      const res = await fetch(path, options);
      if (!res.ok) throw new Error(await res.text());
      return res;
    }
    async function loadActions() {
      const res = await api('/api/actions');
      const actions = await res.json();
      document.getElementById('actions').innerHTML = actions.map(a => `
        <div class="action">
          <strong>${a.label}</strong>
          <p>${a.description}</p>
          <button class="${a.dangerous ? 'danger' : ''}" onclick="runAction('${a.id}', ${a.dangerous})">运行</button>
        </div>`).join('');
    }
    async function runAction(id, dangerous) {
      const confirm_live = dangerous ? confirm('这会执行 live 交易循环。确认已经完成 smoke test 和 no-submit 演练？') : false;
      if (dangerous && !confirm_live) return;
      const res = await api(`/api/actions/${id}/run`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({confirm_live})
      });
      const job = await res.json();
      document.getElementById('output').textContent = `任务已启动：${job.label}\\n${job.id}`;
      refreshJobs();
    }
    async function refreshJobs() {
      const res = await api('/api/jobs');
      const jobs = await res.json();
      document.getElementById('jobs').innerHTML = jobs.map(j => `
        <div class="job" onclick="showJob('${j.id}')">
          <span class="status ${j.status}">${j.status}</span> ${j.label}<br>
          <small>${j.started_at}${j.finished_at ? ' - ' + j.finished_at : ''}</small>
        </div>`).join('') || '<p class="note">还没有任务。</p>';
    }
    async function showJob(id) {
      const res = await api(`/api/jobs/${id}`);
      const job = await res.json();
      document.getElementById('output').textContent = job.output || JSON.stringify(job, null, 2);
    }
    async function loadReport(name) {
      try {
        const res = await api(`/api/reports/${name}`);
        document.getElementById('report').textContent = await res.text();
      } catch (err) {
        document.getElementById('report').textContent = String(err);
      }
    }
    loadActions();
    refreshJobs();
    setInterval(refreshJobs, 3000);
  </script>
</body>
</html>
"""


app = create_app()
