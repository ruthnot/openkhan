"""RUNTIME — the task queue (the DB-backed work queue the agent loop drains).

The always-live agent's unit of background work is a **task**: a row that says
*what to do* (`kind` + `params`) and *where to deliver the result* (`requester`).
Anyone — a chat turn, a future scheduler, a Telegram message — enqueues a task;
the kahnd daemon's agent loop (`worker.py`) drains them one at a time.

This is queue *plumbing*, not a layer or plane — it lives in `runtime/` next to the
loop and daemon that host the process. It mirrors how `Observations` wraps its
table; it does NOT run tasks (that's the loop's job). Lifecycle:

    enqueue() → queued → claim_next() → running → mark_done()  → done
                                                 ↘ mark_failed() → failed

`claim_next()` is the only state-changing read: it atomically picks the oldest
queued row and flips it to running, so a task is never handed out twice.
`reclaim_stale()` is the stage-1 watchdog (see its docstring).
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
class Task:
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


class Tasks:
    """Access to the `tasks` table — enqueue, claim, complete, reclaim, read."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- write ---------------------------------------------------------------

    def enqueue(
        self,
        kind: str,
        params: dict | None = None,
        requester: dict | None = None,
    ) -> Task:
        """Append a new task in the `queued` state."""
        created = _now()
        cur = self._conn.execute(
            "INSERT INTO tasks (kind, params, requester, state, created_at) "
            "VALUES (?, ?, ?, 'queued', ?)",
            (kind, json.dumps(params or {}), json.dumps(requester) if requester else None, created),
        )
        self._conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def claim_next(self) -> Task | None:
        """Atomically take the oldest queued task and mark it running. None if empty.

        A single UPDATE...RETURNING flips exactly one row, so even if several
        callers raced, each would claim a distinct task (only the loop claims
        today, but this keeps the queue safe regardless).
        """
        row = self._conn.execute(
            "UPDATE tasks SET state='running', started_at=? "
            "WHERE id = (SELECT id FROM tasks WHERE state='queued' ORDER BY id LIMIT 1) "
            "RETURNING *",
            (_now(),),
        ).fetchone()
        self._conn.commit()
        return self._row(row) if row else None

    def mark_done(self, task_id: int, result: Any = None) -> None:
        self._conn.execute(
            "UPDATE tasks SET state='done', result=?, finished_at=? WHERE id=?",
            (json.dumps(result), _now(), task_id),
        )
        self._conn.commit()

    def mark_failed(self, task_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE tasks SET state='failed', error=?, finished_at=? WHERE id=?",
            (error, _now(), task_id),
        )
        self._conn.commit()

    def reclaim_stale(self) -> int:
        """Stage-1 watchdog: requeue tasks left `running` by a crashed worker.

        Safe to call at daemon startup: with a single worker, nothing can
        legitimately be `running` before the loop begins, so every `running` row
        is an orphan from a previous crash. Returns the number reclaimed.

        (Stage 2 — detecting a *live* hang while the daemon is still up — needs
        per-task `heartbeat_ts` + a timeout and is deferred to Phase 6.)
        """
        cur = self._conn.execute(
            "UPDATE tasks SET state='queued', started_at=NULL WHERE state='running'"
        )
        self._conn.commit()
        return cur.rowcount

    # --- read ----------------------------------------------------------------

    def get(self, task_id: int) -> Task:
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._row(row)

    def recent(self, limit: int = 20) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(r) for r in reversed(rows)]

    def pending(self) -> int:
        """How many tasks are still queued (not yet claimed)."""
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE state='queued'"
        ).fetchone()["n"]

    @staticmethod
    def _row(r: sqlite3.Row) -> Task:
        return Task(
            id=r["id"], kind=r["kind"],
            params=json.loads(r["params"]) if r["params"] else {},
            requester=json.loads(r["requester"]) if r["requester"] else None,
            state=r["state"],
            result=json.loads(r["result"]) if r["result"] else None,
            error=r["error"], created_at=r["created_at"],
            started_at=r["started_at"], finished_at=r["finished_at"],
        )
