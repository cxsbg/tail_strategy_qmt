from __future__ import annotations

import pytest

from reports.decisions import build_decision_report, render_decision_markdown


def test_render_decision_markdown_includes_summary_and_actions() -> None:
    pd = pytest.importorskip("pandas")
    decisions = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "action": "OPEN_POSITION",
                "score": 88.0,
                "suggested_position_ratio": 0.15,
                "reasons": "tail_confirmed",
                "risks": None,
            },
            {
                "symbol": "600000.SH",
                "action": "WATCH_SIGNAL",
                "score": 75.0,
                "suggested_position_ratio": 0.0,
                "reasons": "watch_signal",
                "risks": "new_position_quota_used",
            },
        ]
    )

    markdown = render_decision_markdown(report_date="20260508", decisions=decisions)

    assert "- Decisions: 2" in markdown
    assert "- OPEN_POSITION: 1" in markdown
    assert "| 000001.SZ | OPEN_POSITION | 88 | 0.15 | tail_confirmed |  |" in markdown
    assert "new_position_quota_used" in markdown


def test_build_decision_report_writes_markdown_and_csv(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    decisions_path = tmp_path / "decisions.parquet"
    markdown_path = tmp_path / "decision_report.md"
    csv_path = tmp_path / "decision_report.csv"
    pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "decision_date": "20260508",
                "source_signal_id": 1,
                "position_id": None,
                "action": "OPEN_POSITION",
                "score": 88.0,
                "suggested_position_ratio": 0.15,
                "reasons": "tail_confirmed",
                "risks": None,
                "strategy_version": "test-rule",
                "created_at": "2026-05-08T15:00:00",
            }
        ]
    ).to_parquet(decisions_path, index=False)

    result = build_decision_report(
        decisions_path=decisions_path,
        markdown_path=markdown_path,
        csv_path=csv_path,
        report_date="20260508",
    )

    assert result.report_date == "20260508"
    assert result.decision_count == 1
    assert "Tail Strategy Decision Report" in markdown_path.read_text(encoding="utf-8")
    assert "000001.SZ" in csv_path.read_text(encoding="utf-8-sig")
