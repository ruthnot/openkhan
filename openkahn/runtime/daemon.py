"""RUNTIME — the kahnd daemon lifecycle.

This is the "always-live agent" made real. `kahn start` launches kahnd as a
detached background process that drains the jobs queue; it keeps running after you
close your chat session and only stops on `kahn stop`. The model:

    kahn start    → spawn a detached child running `_run()`, write its PID
    kahn stop     → SIGTERM the PID, wait for it to exit, clear the PID file
    kahn restart  → stop, then start
    kahn status   → is it alive? how many jobs are queued?

We keep it deliberately simple: one detached child process (not a double-fork
init-style daemon), a PID file for liveness, and the child's stdout/stderr sent to
a log file. The child installs SIGTERM/SIGINT handlers that set a stop Event, so
the worker finishes its current job and exits cleanly.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from openkahn.control.jobs import Jobs
from openkahn.control.worker import Worker
from openkahn.db.connection import connect
from openkahn.memory.observations import Observations
from openkahn.runtime.config import Config


# --- PID file helpers --------------------------------------------------------

def _read_pid(pid_file: str) -> int | None:
    p = Path(pid_file)
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def _alive(pid: int) -> bool:
    """Is a process with this PID running? (signal 0 = existence check, no-op.)"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def status_pid(pid_file: str) -> int | None:
    """Return the PID if kahnd is alive, else None (clearing a stale PID file)."""
    pid = _read_pid(pid_file)
    if pid is None:
        return None
    if _alive(pid):
        return pid
    Path(pid_file).unlink(missing_ok=True)  # stale: process gone, file lingered
    return None


# --- lifecycle (called from the foreground `kahn` invocation) -----------------

def start(cfg: Config, config_path: str) -> None:
    """Spawn the detached kahnd child and record its PID."""
    running = status_pid(cfg.control.pid_file)
    if running is not None:
        print(f"kahnd already running (pid {running})")
        return

    Path(cfg.control.pid_file).parent.mkdir(parents=True, exist_ok=True)
    log = open(cfg.control.log_file, "a")  # noqa: SIM115 — handed to the child, stays open
    child = subprocess.Popen(
        [sys.executable, "-m", "openkahn", "--config", config_path, "_daemon"],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,  # detach: survives this shell / chat session
    )
    Path(cfg.control.pid_file).write_text(str(child.pid))
    print(f"kahnd started (pid {child.pid}) — logs: {cfg.control.log_file}")


def stop(cfg: Config) -> None:
    """Signal kahnd to stop and wait for it to exit."""
    pid = status_pid(cfg.control.pid_file)
    if pid is None:
        print("kahnd is not running")
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):  # up to ~5s for a graceful exit
        if not _alive(pid):
            break
        time.sleep(0.1)
    else:
        print(f"kahnd (pid {pid}) did not stop within 5s — leaving it")
        return
    Path(cfg.control.pid_file).unlink(missing_ok=True)
    print(f"kahnd stopped (pid {pid})")


def restart(cfg: Config, config_path: str) -> None:
    stop(cfg)
    start(cfg, config_path)


def status(cfg: Config) -> None:
    pid = status_pid(cfg.control.pid_file)
    conn = connect(cfg.memory.db)
    queued = Jobs(conn).pending()
    if pid is None:
        print(f"kahnd: stopped  ·  {queued} job(s) queued")
    else:
        print(f"kahnd: running (pid {pid})  ·  {queued} job(s) queued")


# --- the daemon body (runs inside the detached child) ------------------------

def run(cfg: Config) -> None:
    """The foreground loop of the detached child: build the worker and drain jobs."""
    conn = connect(cfg.memory.db)
    worker = Worker(
        jobs=Jobs(conn),
        observations=Observations(conn),
        poll_interval=cfg.control.poll_interval_seconds,
    )

    stop_event = threading.Event()

    def _handle(signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    worker.run(stop_event)
    Path(cfg.control.pid_file).unlink(missing_ok=True)  # clean exit clears its own PID file
