from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from web_console.app import create_app


def test_web_console_serves_index_and_actions(tmp_path) -> None:
    client = TestClient(create_app(project_root=tmp_path))

    index = client.get("/")
    actions = client.get("/api/actions")

    assert index.status_code == 200
    assert "Tail Strategy QMT" in index.text
    assert actions.status_code == 200
    assert any(item["id"] == "qmt_smoke" for item in actions.json())
    assert any(item["id"] == "intraday_monitor" for item in actions.json())


def test_web_console_blocks_live_action_without_confirmation(tmp_path) -> None:
    client = TestClient(create_app(project_root=tmp_path))

    response = client.post("/api/actions/live_cycle/run", json={"confirm_live": False})

    assert response.status_code == 403


def test_web_console_reads_known_report(tmp_path) -> None:
    report = tmp_path / "outputs" / "readiness_report.md"
    report.parent.mkdir(parents=True)
    report.write_text("# ready", encoding="utf-8")
    client = TestClient(create_app(project_root=tmp_path))

    response = client.get("/api/reports/readiness")

    assert response.status_code == 200
    assert response.text == "# ready"


def test_web_console_reads_intraday_monitor_report(tmp_path) -> None:
    report = tmp_path / "outputs" / "intraday_monitor_report.md"
    report.parent.mkdir(parents=True)
    report.write_text("# intraday", encoding="utf-8")
    client = TestClient(create_app(project_root=tmp_path))

    response = client.get("/api/reports/intraday_monitor")

    assert response.status_code == 200
    assert response.text == "# intraday"


def test_web_console_runs_quick_job() -> None:
    client = TestClient(create_app(project_root=Path.cwd()))

    response = client.post("/api/actions/windows_tasks/run", json={})
    assert response.status_code == 200
    job_id = response.json()["id"]

    final = None
    for _ in range(30):
        final = client.get(f"/api/jobs/{job_id}").json()
        if final["status"] != "RUNNING":
            break
        time.sleep(0.1)

    assert final is not None
    assert final["status"] == "SUCCESS"
    assert "schtasks /Create" in final["output"]
