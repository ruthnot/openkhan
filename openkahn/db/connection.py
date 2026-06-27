"""Plumbing — the SQLite connection + schema bootstrap for the Memory layer.

One database file holds every memory tier as it comes online. Today there's a
single table: `observations` (tier 1, the raw memory stream). The schema uses
`IF NOT EXISTS`, so opening an existing DB is a no-op and future tiers just add
their own `CREATE TABLE` lines here.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- stream position = order in time
  ts         TEXT    NOT NULL,                   -- UTC ISO8601 (sortable)
  day        TEXT    NOT NULL,                   -- LOCAL calendar day  YYYY-MM-DD
  hour       INTEGER NOT NULL,                   -- LOCAL hour 0-23
  session_id TEXT    NOT NULL,                   -- one conversation / run
  turn_id    TEXT,                               -- links a user msg to its reply(ies)
  channel    TEXT    NOT NULL,                   -- 'cli' (later 'telegram', ...)
  actor      TEXT    NOT NULL,                   -- 'user' | 'agent' | 'system'
  kind       TEXT    NOT NULL,                   -- 'user_msg'|'agent_msg'|'reflex'|'system'|...
  content    TEXT,                               -- human-readable description
  meta       TEXT                                -- JSON: tier, model, latency_ms, ...
);
CREATE INDEX IF NOT EXISTS idx_obs_ts      ON observations(ts);
CREATE INDEX IF NOT EXISTS idx_obs_day     ON observations(day);
CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the Memory database and ensure the schema exists."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")  # append-friendly: readers don't block the writer
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
