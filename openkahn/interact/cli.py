"""INTERACT layer — CLI channel.

A development "converse" sub-mode: read what you type, hand it to the Think layer's
control/router, and render the reply chunks as they arrive. That's the whole
boundary for v0.

The CLI knows nothing about tiers, reflexes, or models — it just renders whatever
chunks `control.respond()` yields, in order. All routing lives in Think. The
runtime wires the real control in, so Interact and Think stay decoupled.
"""
from __future__ import annotations

from openkahn.think.control import Control

USER_PROMPT = "you › "
AGENT_PREFIX = "kahn › "


class CLI:
    def __init__(self, control: Control) -> None:
        self._control = control

    def run_once(self, message: str) -> str:
        """One message in, all reply chunks out — handy for smoke tests and scripts."""
        return "\n".join(f"{AGENT_PREFIX}{chunk}" for chunk in self._control.respond(message))

    def repl(self) -> None:
        """Interactive read-eval-print loop. Ctrl-D or 'exit' to quit."""
        print("openkahn — reflex + fast-think (v0). Ctrl-D or 'exit' to quit.\n")
        while True:
            try:
                message = input(USER_PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye.")
                return
            if not message:
                continue
            if message in {"exit", "quit"}:
                print("bye.")
                return
            # Render each chunk the moment it's ready: the filler prints instantly,
            # then a pause while the model thinks, then the real answer.
            for chunk in self._control.respond(message):
                print(f"{AGENT_PREFIX}{chunk}")
            print()
