"""CONTROL plane — the worker loop.

The beating heart of the always-live agent. It loops forever: claim the next
queued job, run the handler registered for its `kind`, record the outcome to the
Memory layer's observation stream, repeat. When the queue is empty it sleeps for
`poll_interval` and checks again.

A **handler** is just `callable(Job) -> result`. The registry maps a job `kind`
to its handler, so adding a new kind of background work (e.g. 'research') later
means registering one function — the loop itself never changes.

Everything the worker does lands in the observation stream under channel='kahnd',
so `kahn log` shows the daemon's life next to chat turns: one timeline for the
whole agent. The worker stops cleanly when `stop` (a threading.Event) is set —
the daemon wires that to SIGTERM/SIGINT.
"""
from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from typing import Any

from openkahn.control.jobs import Job, Jobs
from openkahn.memory.observations import Observations

Handler = Callable[[Job], Any]

DAEMON_SESSION = "kahnd"
DAEMON_CHANNEL = "kahnd"


def echo_handler(job: Job) -> dict:
    """The trivial first handler: hand back what it was given. Proves the pipe works."""
    return {"echo": job.params.get("text", "")}


DEFAULT_HANDLERS: dict[str, Handler] = {
    "echo": echo_handler,
}


class Worker:
    """Drains the jobs queue, one job at a time, until asked to stop."""

    def __init__(
        self,
        jobs: Jobs,
        observations: Observations,
        handlers: dict[str, Handler] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self._jobs = jobs
        self._obs = observations
        self._handlers = handlers if handlers is not None else dict(DEFAULT_HANDLERS)
        self._poll = poll_interval

    def _record(self, kind: str, content: str, **meta) -> None:
        self._obs.record(kind=kind, actor="system", content=content,
                         session_id=DAEMON_SESSION, channel=DAEMON_CHANNEL, **meta)

    def run_once(self) -> bool:
        """Claim and run one job. Returns True if a job ran, False if queue empty."""
        job = self._jobs.claim_next()
        if job is None:
            return False

        self._record("job_started", f"job #{job.id} ({job.kind}) started", job_id=job.id, job_kind=job.kind)
        handler = self._handlers.get(job.kind)
        if handler is None:
            self._jobs.mark_failed(job.id, f"no handler for kind '{job.kind}'")
            self._record("job_failed", f"job #{job.id} failed: no handler for '{job.kind}'", job_id=job.id)
            return True

        try:
            result = handler(job)
            self._jobs.mark_done(job.id, result)
            self._record("job_done", f"job #{job.id} ({job.kind}) done", job_id=job.id, job_kind=job.kind)
        except Exception as exc:  # a bad handler must not kill the daemon
            self._jobs.mark_failed(job.id, f"{type(exc).__name__}: {exc}")
            self._record("job_failed", f"job #{job.id} ({job.kind}) failed: {exc}",
                         job_id=job.id, traceback=traceback.format_exc())
        return True

    def run(self, stop: threading.Event) -> None:
        """Loop until `stop` is set: drain the queue, then wait, then check again."""
        self._record("daemon", "kahnd worker started")
        try:
            while not stop.is_set():
                # Drain everything queued before sleeping, so a burst runs back-to-back.
                while not stop.is_set() and self.run_once():
                    pass
                stop.wait(self._poll)  # interruptible sleep
        finally:
            self._record("daemon", "kahnd worker stopped")
