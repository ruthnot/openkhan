"""CONTROL plane — the jobs queue.

The always-live agent's unit of background work is a **job**: a row that says
*what to do* (`kind` + `params`) and *where to deliver the result* (`requester`).
Anyone — a chat turn, a future scheduler, a Telegram message — enqueues a job;
the kahnd daemon's worker drains them one at a time.

This module is pure data access over the `jobs` table (mirrors how `Observations`
wraps its table). It does NOT run jobs — that's the worker's job (worker.py). The
lifecycle a row moves through:

    enqueue() → queued → claim_next() → running → mark_done()  → done
                                                 ↘ mark_failed() → failed

`claim_next()` is the only state-changing read: it atomically picks the oldest
queued row and flips it to running, so a job is never handed out twice.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Job:
    id: int
    kind: str
    params: dict
    requester: dict | None
    state: str
    result: Any
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class Jobs:
    """Access to the `jobs` table — enqueue, claim, complete, read."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- write ---------------------------------------------------------------

    def enqueue(
        self,
        kind: str,
        params: dict | None = None,
        requester: dict | None = None,
    ) -> Job:
        """Append a new job in the `queued` state."""
        created = _now()
        cur = self._conn.execute(
            "INSERT INTO jobs (kind, params, requester, state, created_at) "
            "VALUES (?, ?, ?, 'queued', ?)",
            (kind, json.dumps(params or {}), json.dumps(requester) if requester else None, created),
        )
        self._conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def claim_next(self) -> Job | None:
        """Atomically take the oldest queued job and mark it running. None if empty.

        A single UPDATE...RETURNING flips exactly one row, so even if several
        callers raced, each would claim a distinct job (only the worker claims
        today, but this keeps the queue safe regardless).
        """
        row = self._conn.execute(
            "UPDATE jobs SET state='running', started_at=? "
            "WHERE id = (SELECT id FROM jobs WHERE state='queued' ORDER BY id LIMIT 1) "
            "RETURNING *",
            (_now(),),
        ).fetchone()
        self._conn.commit()
        return self._row(row) if row else None

    def mark_done(self, job_id: int, result: Any = None) -> None:
        self._conn.execute(
            "UPDATE jobs SET state='done', result=?, finished_at=? WHERE id=?",
            (json.dumps(result), _now(), job_id),
        )
        self._conn.commit()

    def mark_failed(self, job_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET state='failed', error=?, finished_at=? WHERE id=?",
            (error, _now(), job_id),
        )
        self._conn.commit()

    # --- read ----------------------------------------------------------------

    def get(self, job_id: int) -> Job:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row)

    def recent(self, limit: int = 20) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(r) for r in reversed(rows)]

    def pending(self) -> int:
        """How many jobs are still queued (not yet claimed)."""
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE state='queued'"
        ).fetchone()["n"]

    @staticmethod
    def _row(r: sqlite3.Row) -> Job:
        return Job(
            id=r["id"], kind=r["kind"],
            params=json.loads(r["params"]) if r["params"] else {},
            requester=json.loads(r["requester"]) if r["requester"] else None,
            state=r["state"],
            result=json.loads(r["result"]) if r["result"] else None,
            error=r["error"], created_at=r["created_at"],
            started_at=r["started_at"], finished_at=r["finished_at"],
        )
