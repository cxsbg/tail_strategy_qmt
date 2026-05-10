from __future__ import annotations

from storage.sqlite import SQLiteStore


def test_initialize_creates_expected_tables(tmp_path) -> None:
    db_path = tmp_path / "tail_strategy.db"
    store = SQLiteStore(db_path)

    store.initialize()

    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

    table_names = {row["name"] for row in rows}
    assert {
        "positions",
        "trades",
        "signals",
        "decisions",
        "decision_applications",
        "order_drafts",
        "pre_trade_checks",
        "data_sync_status",
    }.issubset(table_names)


def test_upsert_sync_status(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "tail_strategy.db")
    store.initialize()

    store.upsert_sync_status(
        symbol="000001.SZ",
        period="1d",
        start_date="20240101",
        end_date="20240501",
        last_sync_time="2024-05-01T15:30:00",
        source="qmt",
        status="success",
    )
    store.upsert_sync_status(
        symbol="000001.SZ",
        period="1d",
        start_date="20240101",
        end_date="20240502",
        last_sync_time="2024-05-02T15:30:00",
        source="qmt",
        status="success",
    )

    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM data_sync_status").fetchall()

    assert len(rows) == 1
    assert rows[0]["end_date"] == "20240502"
