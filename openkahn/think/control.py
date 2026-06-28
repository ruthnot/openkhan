"""THINK layer — control / orchestrator (the router).

Decides *how* to answer each turn (tier) and produces the answer as a stream of
chunks. Tiers today:

  faster (System 0)  faster.reflex()  — DEPRECATED: canned table reply, no LLM.
                     Kept in faster.py but no longer routed; fast mode (now terse
                     by persona) handles trivial turns too.
  fast   (System 1)  brain.think()    — one /no_think single pass (the default)
  slow   (System 2)  brain.think()    — thinking on; implemented, not routed yet

Pacing: every reply is held to a minimum felt-latency floor (~1-1.5s), measured
from message arrival. It never delays a reply that already took longer (the model's
own latency sails past the floor), so real turns lose nothing — it only keeps the
occasional very-fast reply from snapping back unnaturally.

Control yields **Chunk** objects (text + kind + meta) rather than bare strings, so
the Interact layer can both render them and record them as observations with the
right kind/metadata.

(The filler ack and the System-0 reflex are both deprecated — see faster.py — so a
turn now yields exactly one `agent_msg` chunk.)
"""
from __future__ import annotations

import random
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from openkahn.think.brain import Brain

# Minimum felt latency for a substantive reply, randomized so it isn't metronomic.
FELT_FLOOR_SECONDS = (1.0, 1.5)


@dataclass
class Chunk:
    """One renderable piece of a reply, tagged for rendering AND for the log."""

    text: str
    kind: str                                   # 'agent_msg' (reflex/filler deprecated)
    meta: dict = field(default_factory=dict)
    record: bool = True                         # set False for ephemeral, non-logged UX


def _pace(since: float) -> None:
    """Sleep so the reply never lands faster than a human-feeling floor (no-op if slow)."""
    floor = random.uniform(*FELT_FLOOR_SECONDS)
    elapsed = time.monotonic() - since
    if elapsed < floor:
        time.sleep(floor - elapsed)


class Control:
    def __init__(self, brain: Brain) -> None:
        self._brain = brain

    def respond(self, history: list[dict]) -> Iterator[Chunk]:
        """Answer the latest turn. `history` is the full conversation (chat-shape
        dicts); the last entry is the current user message.

        One pass, one chunk: fast mode (System 1). The System-0 reflex and the
        filler ack are both deprecated (faster.py), so there's no pre-answer noise.
        """
        arrived = time.monotonic()
        answer = self._brain.think(history, mode="fast")      # System 1 — /no_think
        latency_ms = int((time.monotonic() - arrived) * 1000)
        _pace(arrived)                                         # no-op when the model was slow
        yield Chunk(answer, "agent_msg", {
            "tier": "fast",
            "mode": "fast",
            "model": getattr(self._brain, "model", None),
            "latency_ms": latency_ms,
        })
