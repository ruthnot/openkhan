"""INTERACT layer — CLI channel.

Reads what you type, hands it to Think's router, renders the reply chunks, AND
records everything to the Memory layer's observation stream.

Interact owns the conversation boundary: it mints the session id (one per run) and
the turn ids, and it writes the diary. Think just produces tagged chunks; Memory
just stores. So the recording lives here, at the I/O edge, where every message in
and every reply out is visible.
"""
from __future__ import annotations

import itertools
from datetime import datetime

from openkahn.memory.observations import Observations
from openkahn.think.control import Control

USER_PROMPT = "you › "
AGENT_PREFIX = "kahn › "


class CLI:
    def __init__(self, control: Control, observations: Observations) -> None:
        self._control = control
        self._obs = observations

    @staticmethod
    def _new_session() -> str:
        return "cli-" + datetime.now().strftime("%Y%m%d-%H%M%S")

    def _start(self, session_id: str) -> None:
        self._obs.record(kind="system", actor="system", content="session started",
                         session_id=session_id, channel="cli")

    def _end(self, session_id: str) -> None:
        self._obs.record(kind="system", actor="system", content="session ended",
                         session_id=session_id, channel="cli")

    def _turn(self, session_id: str, turn_id: str, message: str, render) -> None:
        """Record the user msg, then stream + record each reply chunk."""
        self._obs.record(kind="user_msg", actor="user", content=message,
                         session_id=session_id, channel="cli", turn_id=turn_id)
        for chunk in self._control.respond(message):
            render(chunk.text)
            if chunk.record:
                self._obs.record(kind=chunk.kind, actor="agent", content=chunk.text,
                                 session_id=session_id, channel="cli", turn_id=turn_id,
                                 **chunk.meta)

    def run_once(self, message: str) -> str:
        """One message in, all reply chunks out — handy for smoke tests and scripts."""
        session_id = self._new_session()
        self._start(session_id)
        lines: list[str] = []
        self._turn(session_id, f"{session_id}-t1", message, lines.append)
        self._end(session_id)
        return "\n".join(f"{AGENT_PREFIX}{line}" for line in lines)

    def repl(self) -> None:
        """Interactive read-eval-print loop. Ctrl-D or 'exit' to quit."""
        session_id = self._new_session()
        self._start(session_id)
        print("openkahn — reflex + fast-think, logging observations (v0). Ctrl-D or 'exit' to quit.\n")
        turns = itertools.count(1)
        while True:
            try:
                message = input(USER_PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                self._end(session_id)
                print("\nbye.")
                return
            if not message:
                continue
            if message in {"exit", "quit"}:
                self._end(session_id)
                print("bye.")
                return
            turn_id = f"{session_id}-t{next(turns)}"
            self._turn(session_id, turn_id, message, lambda t: print(f"{AGENT_PREFIX}{t}"))
            print()
