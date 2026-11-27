import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_DIR = Path(os.environ.get("JMON_HOME", Path.home() / ".juniper_monitor"))
DB_FILE = DB_DIR / "juniper_monitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS switches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL,
    password_enc TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL,
    error_message TEXT,
    summary_json TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    metric_name TEXT NOT NULL,
    metric_value REAL
);

CREATE INDEX IF NOT EXISTS idx_metrics_switch_name ON metrics(switch_id, metric_name, collected_at);
CREATE INDEX IF NOT EXISTS idx_collections_switch ON collections(switch_id, collected_at);
"""


def init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_switch(name: str, host: str, port: int, username: str, password_enc: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO switches (name, host, port, username, password_enc) VALUES (?, ?, ?, ?, ?)",
            (name, host, port, username, password_enc),
        )
        return cur.lastrowid


def get_switches():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM switches ORDER BY name")]


def get_switch(switch_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM switches WHERE id = ?", (switch_id,)).fetchone()
        return dict(row) if row else None


def get_switch_by_name(name: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM switches WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None


def delete_switch(switch_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM switches WHERE id = ?", (switch_id,))


def save_collection(switch_id: int, status: str, summary: dict, raw: dict, error_message: str = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO collections (switch_id, status, error_message, summary_json, raw_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (switch_id, status, error_message, json.dumps(summary), json.dumps(raw)),
        )


def save_metrics(switch_id: int, metrics: dict):
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO metrics (switch_id, metric_name, metric_value) VALUES (?, ?, ?)",
            [(switch_id, k, v) for k, v in metrics.items() if v is not None],
        )


def get_latest_collection(switch_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM collections WHERE switch_id = ? ORDER BY collected_at DESC LIMIT 1",
            (switch_id,),
        ).fetchone()
        return dict(row) if row else None


def get_metric_history(switch_id: int, metric_name: str, limit: int = 200):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT collected_at, metric_value FROM metrics "
            "WHERE switch_id = ? AND metric_name = ? ORDER BY collected_at DESC LIMIT ?",
            (switch_id, metric_name, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_collection_history(switch_id: int, limit: int = 30):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, collected_at, status, error_message FROM collections "
            "WHERE switch_id = ? ORDER BY collected_at DESC LIMIT ?",
            (switch_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
