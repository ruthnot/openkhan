"""Plumbing — the SQLite connection + schema bootstrap.

One database file holds every layer's tables as they come online:
  - `observations` — Memory tier 1, the raw append-only memory stream.
  - `jobs`         — Control plane, the work queue the kahnd daemon drains.

The schema uses `IF NOT EXISTS`, so opening an existing DB is a no-op and future
tiers just add their own `CREATE TABLE` lines here. The DB has two writers (the
`kahn chat` session and the `kahnd` daemon, separate processes), so we run in WAL
mode with a busy_timeout — readers never block the writer, and a writer that finds
the file briefly locked waits instead of erroring.
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

CREATE TABLE IF NOT EXISTS jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,  -- queue position = order enqueued
  kind        TEXT    NOT NULL,                   -- 'echo' (later 'research', ...)
  params      TEXT,                               -- JSON: kind-specific inputs
  requester   TEXT,                               -- JSON: {channel, peer} — where to deliver
  state       TEXT    NOT NULL,                   -- 'queued'|'running'|'done'|'failed'
  result      TEXT,                               -- JSON: handler output (when done)
  error       TEXT,                               -- failure message (when failed)
  created_at  TEXT    NOT NULL,                   -- UTC ISO8601 enqueued
  started_at  TEXT,                               -- UTC ISO8601 claimed by worker
  finished_at TEXT                                -- UTC ISO8601 done/failed
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the database and ensure the schema exists."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")    # readers don't block the writer
    conn.execute("PRAGMA busy_timeout=5000;")   # two writers (chat + daemon): wait, don't error
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
