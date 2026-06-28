"""RUNTIME — the agent loop (drains the task queue).

The beating heart of the always-live agent. It loops forever: claim the next
queued task, run the handler registered for its `kind`, record the outcome to the
Memory layer's observation stream, repeat. When the queue is empty it sleeps for
`poll_interval` and checks again.

This is the **task-level** orchestrator — runtime plumbing that hosts the process,
distinct from Think's **turn-level** control (`think/control.py`). For a real task
the handler will *invoke* Think; the loop itself only dispatches and records.

A **handler** is just `callable(Task) -> result`. The registry maps a task `kind`
to its handler, so adding a new kind of background work (e.g. 'research') later
means registering one function — the loop itself never changes.

Everything the loop does lands in the observation stream under channel='kahnd', so
`kahn log` shows the daemon's life next to chat turns: one timeline for the whole
agent. The loop stops cleanly when `stop` (a threading.Event) is set — the daemon
wires that to SIGTERM/SIGINT.
"""
from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from typing import Any

from openkahn.memory.observations import Observations
from openkahn.runtime.queue import Task, Tasks

Handler = Callable[[Task], Any]

DAEMON_SESSION = "kahnd"
DAEMON_CHANNEL = "kahnd"


def echo_handler(task: Task) -> dict:
    """The trivial first handler: hand back what it was given. Proves the pipe works."""
    return {"echo": task.params.get("text", "")}


DEFAULT_HANDLERS: dict[str, Handler] = {
    "echo": echo_handler,
}


class Worker:
    """Drains the task queue, one task at a time, until asked to stop."""

    def __init__(
        self,
        tasks: Tasks,
        observations: Observations,
        handlers: dict[str, Handler] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self._tasks = tasks
        self._obs = observations
        self._handlers = handlers if handlers is not None else dict(DEFAULT_HANDLERS)
        self._poll = poll_interval

    def _record(self, kind: str, content: str, **meta) -> None:
        self._obs.record(kind=kind, actor="system", content=content,
                         session_id=DAEMON_SESSION, channel=DAEMON_CHANNEL, **meta)

    def run_once(self) -> bool:
        """Claim and run one task. Returns True if a task ran, False if queue empty."""
        task = self._tasks.claim_next()
        if task is None:
            return False

        self._record("task_started", f"task #{task.id} ({task.kind}) started",
                     task_id=task.id, task_kind=task.kind)
        handler = self._handlers.get(task.kind)
        if handler is None:
            self._tasks.mark_failed(task.id, f"no handler for kind '{task.kind}'")
            self._record("task_failed", f"task #{task.id} failed: no handler for '{task.kind}'",
                         task_id=task.id)
            return True

        try:
            result = handler(task)
            self._tasks.mark_done(task.id, result)
            self._record("task_done", f"task #{task.id} ({task.kind}) done",
                         task_id=task.id, task_kind=task.kind)
        except Exception as exc:  # a bad handler must not kill the daemon
            self._tasks.mark_failed(task.id, f"{type(exc).__name__}: {exc}")
            self._record("task_failed", f"task #{task.id} ({task.kind}) failed: {exc}",
                         task_id=task.id, traceback=traceback.format_exc())
        return True

    def run(self, stop: threading.Event) -> None:
        """Loop until `stop` is set: drain the queue, then wait, then check again."""
        self._record("daemon", "kahnd agent loop started")
        try:
            while not stop.is_set():
                # Drain everything queued before sleeping, so a burst runs back-to-back.
                while not stop.is_set() and self.run_once():
                    pass
                stop.wait(self._poll)  # interruptible sleep
        finally:
            self._record("daemon", "kahnd agent loop stopped")
