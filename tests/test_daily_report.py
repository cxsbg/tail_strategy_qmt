from __future__ import annotations

import sqlite3

import pytest

from reports.daily import build_daily_report, render_daily_markdown


def test_render_daily_markdown_handles_empty_candidates() -> None:
    pd = pytest.importorskip("pandas")
    candidates = pd.DataFrame()
    diagnostics = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "20260508",
                "passed": False,
                "failed_reasons": "min_return_today",
            }
        ]
    )
    summary = pd.DataFrame([{"reason": "min_return_today", "count": 1}])

    markdown = render_daily_markdown(
        report_date="20260508",
        candidates=candidates,
        diagnostics=diagnostics,
        reason_summary=summary,
        sync_summary=[],
    )

    assert "No candidates for this report date." in markdown
    assert "| min_return_today | 1 |" in markdown
    assert "Failed diagnostics: 1" in markdown


def test_render_daily_markdown_includes_candidates() -> None:
    pd = pytest.importorskip("pandas")
    candidates = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "score": 82.5,
                "candidate_level": "normal",
                "close": 10.25,
                "pct_chg": 0.035,
                "volume_ratio_5d": 1.5,
                "reasons": "price_above_ma20",
            }
        ]
    )
    diagnostics = pd.DataFrame([{"passed": True}])
    summary = pd.DataFrame()

    markdown = render_daily_markdown(
        report_date="20260508",
        candidates=candidates,
        diagnostics=diagnostics,
        reason_summary=summary,
        sync_summary=[
            {
                "symbol": "000001.SZ",
                "period": "1d",
                "end_date": "20260508",
                "status": "success",
                "last_sync_time": "2026-05-08T15:10:00",
            }
        ],
    )

    assert "| 000001.SZ | 82.50 | normal |" in markdown
    assert "| 000001.SZ | 1d | 20260508 | success | 2026-05-08T15:10:00 |" in markdown


def test_build_daily_report_writes_markdown_and_csv(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pd = pytest.importorskip("pandas")
    candidates_path = tmp_path / "candidates.parquet"
    diagnostics_path = tmp_path / "diagnostics.parquet"
    reason_path = tmp_path / "reasons.csv"
    sqlite_path = tmp_path / "sync.db"
    markdown_path = tmp_path / "report.md"
    csv_path = tmp_path / "report.csv"

    pd.DataFrame().to_parquet(candidates_path, index=False)
    pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "20260508",
                "passed": False,
                "failed_reason_count": 1,
                "failed_reasons": "min_return_today",
                "close": 10.0,
                "pct_chg": 0.01,
                "volume_ratio_5d": 0.8,
                "close_position_20d": 0.6,
            }
        ]
    ).to_parquet(diagnostics_path, index=False)
    pd.DataFrame([{"reason": "min_return_today", "count": 1}]).to_csv(reason_path, index=False)
    _create_sync_db(sqlite_path)

    result = build_daily_report(
        candidates_path=candidates_path,
        diagnostics_path=diagnostics_path,
        reason_summary_path=reason_path,
        sqlite_path=sqlite_path,
        markdown_path=markdown_path,
        csv_path=csv_path,
    )

    assert result.report_date == "20260508"
    assert result.candidate_count == 0
    assert result.diagnostics_count == 1
    assert "Tail Strategy Daily Report" in markdown_path.read_text(encoding="utf-8")
    assert "000001.SZ" in csv_path.read_text(encoding="utf-8-sig")


def _create_sync_db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE data_sync_status (
                symbol TEXT,
                period TEXT,
                start_date TEXT,
                end_date TEXT,
                last_sync_time TEXT,
                source TEXT,
                status TEXT,
                error_message TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO data_sync_status
            VALUES ('000001.SZ', '1d', '20240101', '20260508', '2026-05-08T15:10:00', 'qmt', 'success', NULL)
            """
        )
