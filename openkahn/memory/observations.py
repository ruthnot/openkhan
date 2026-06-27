"""MEMORY layer — tier 1: the observation stream.

A Generative-Agents "memory stream", stored MemGPT-recall style in SQLite: an
append-only, time-ordered diary of everything that happens (you said X, the agent
replied Y, the system started). It is the raw ground truth that the higher memory
tiers (working summary, semantic facts, procedural skills) will later derive from.

This tier only ever does two things:
  - record(...)  append one observation        (never UPDATE, never DELETE)
  - read it back chronologically                (recent / by session / by day)

Ranked retrieval, importance scoring, embeddings/search, and reading-into-context
are deliberately NOT here — they belong to layers that sit on top of this stream.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Observation:
    id: int
    ts: str
    day: str
    hour: int
    session_id: str
    turn_id: str | None
    channel: str
    actor: str
    kind: str
    content: str | None
    meta: dict


class Observations:
    """Append-only access to the `observations` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- write (append-only) -------------------------------------------------

    def record(
        self,
        *,
        kind: str,
        actor: str,
        session_id: str,
        channel: str,
        content: str | None = None,
        turn_id: str | None = None,
        **meta,
    ) -> Observation:
        """Append one observation. Timestamp is now; day/hour are LOCAL buckets."""
        now_utc = datetime.now(timezone.utc)
        local = now_utc.astimezone()  # system local timezone
        ts = now_utc.isoformat(timespec="milliseconds")
        day = local.strftime("%Y-%m-%d")
        hour = local.hour
        cur = self._conn.execute(
            "INSERT INTO observations "
            "(ts, day, hour, session_id, turn_id, channel, actor, kind, content, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, day, hour, session_id, turn_id, channel, actor, kind, content,
             json.dumps(meta) if meta else None),
        )
        self._conn.commit()
        return Observation(cur.lastrowid, ts, day, hour, session_id, turn_id,
                           channel, actor, kind, content, meta)

    # --- read (chronological views) -----------------------------------------

    def recent(self, limit: int = 50) -> list[Observation]:
        """The last `limit` observations, oldest-first."""
        rows = self._conn.execute(
            "SELECT * FROM observations ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(r) for r in reversed(rows)]

    def session(self, session_id: str) -> list[Observation]:
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def day(self, day: str) -> list[Observation]:
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE day = ? ORDER BY id", (day,)
        ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r: sqlite3.Row) -> Observation:
        return Observation(
            id=r["id"], ts=r["ts"], day=r["day"], hour=r["hour"],
            session_id=r["session_id"], turn_id=r["turn_id"], channel=r["channel"],
            actor=r["actor"], kind=r["kind"], content=r["content"],
            meta=json.loads(r["meta"]) if r["meta"] else {},
        )
