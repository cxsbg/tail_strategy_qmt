from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        name TEXT,
        entry_date TEXT NOT NULL,
        entry_time TEXT,
        entry_price REAL NOT NULL,
        position_ratio REAL NOT NULL,
        max_position_ratio REAL NOT NULL,
        breakout_price REAL,
        stop_loss_price REAL,
        take_profit_price REAL,
        ma10_at_entry REAL,
        status TEXT NOT NULL,
        holding_days INTEGER DEFAULT 0,
        add_count INTEGER DEFAULT 0,
        reduce_count INTEGER DEFAULT 0,
        last_action TEXT,
        updated_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        trade_time TEXT,
        action TEXT NOT NULL,
        price REAL NOT NULL,
        quantity REAL,
        position_ratio REAL,
        reason TEXT,
        strategy_version TEXT,
        signal_score REAL,
        market_state TEXT,
        created_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        signal_time TEXT,
        score REAL,
        suggested_action TEXT,
        suggested_position_ratio REAL,
        reasons TEXT,
        risks TEXT,
        strategy_version TEXT,
        created_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        decision_date TEXT NOT NULL,
        source_signal_id INTEGER,
        position_id INTEGER,
        action TEXT NOT NULL,
        score REAL,
        suggested_position_ratio REAL,
        reasons TEXT,
        risks TEXT,
        strategy_version TEXT,
        created_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decision_id INTEGER NOT NULL UNIQUE,
        symbol TEXT NOT NULL,
        decision_date TEXT NOT NULL,
        action TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT,
        created_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS data_sync_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        period TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        last_sync_time TEXT,
        source TEXT,
        status TEXT,
        error_message TEXT,
        UNIQUE(symbol, period)
    );
    """,
)


class SQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            for statement in SCHEMA:
                conn.execute(statement)
            conn.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def upsert_sync_status(
        self,
        *,
        symbol: str,
        period: str,
        start_date: str | None,
        end_date: str | None,
        last_sync_time: str,
        source: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        sql = """
        INSERT INTO data_sync_status (
            symbol, period, start_date, end_date, last_sync_time, source, status, error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, period) DO UPDATE SET
            start_date = excluded.start_date,
            end_date = excluded.end_date,
            last_sync_time = excluded.last_sync_time,
            source = excluded.source,
            status = excluded.status,
            error_message = excluded.error_message;
        """
        with self.connect() as conn:
            conn.execute(
                sql,
                (
                    symbol,
                    period,
                    start_date,
                    end_date,
                    last_sync_time,
                    source,
                    status,
                    error_message,
                ),
            )
            conn.commit()
