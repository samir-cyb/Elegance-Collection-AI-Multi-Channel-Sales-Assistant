"""Shared SQLite setup — used by orders AND by the pixel/event tracker for
the admin analytics dashboard."""

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "app.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def setup_database():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            product TEXT NOT NULL,
            color TEXT,
            quantity INTEGER DEFAULT 1,
            total_price REAL,
            platform TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """
    )
    # Pixel / on-site event log — powers the admin analytics dashboard.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            page TEXT,
            product_id TEXT,
            meta TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
