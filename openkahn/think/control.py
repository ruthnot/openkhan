"""THINK layer — control / orchestrator (the router).

Decides *how* to answer each turn (tier) and produces the answer as a stream of
chunks. Tiers today:

  faster (System 0)  faster.reflex()  — instant canned reply, no LLM
  fast   (System 1)  brain.think()    — one /no_think single pass
  slow   (System 2)  brain.think()    — thinking on; implemented, not routed yet

Pacing: every *substantive* reply is held to a minimum felt-latency floor (~1-1.5s),
measured from message arrival. This pads instant reflexes up to a human beat but
never delays a reply that already took longer (the model's own latency sails past
the floor), so real turns lose nothing. The filler ack stays instant on purpose.

Control yields **Chunk** objects (text + kind + meta) rather than bare strings, so
the Interact layer can both render them and record them as observations with the
right kind/metadata. Everything is recorded — including the filler ack (kind
'filler') — so the stream is complete; later tiers can ignore fillers by kind.
"""
from __future__ import annotations

import random
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from openkahn.think import faster
from openkahn.think.brain import Brain

# Minimum felt latency for a substantive reply, randomized so it isn't metronomic.
FELT_FLOOR_SECONDS = (1.0, 1.5)


@dataclass
class Chunk:
    """One renderable piece of a reply, tagged for rendering AND for the log."""

    text: str
    kind: str                                   # 'reflex' | 'agent_msg' | 'filler'
    meta: dict = field(default_factory=dict)
    record: bool = True                         # filler is ephemeral UX, not recorded


def _pace(since: float) -> None:
    """Sleep so the reply never lands faster than a human-feeling floor (no-op if slow)."""
    floor = random.uniform(*FELT_FLOOR_SECONDS)
    elapsed = time.monotonic() - since
    if elapsed < floor:
        time.sleep(floor - elapsed)


class Control:
    def __init__(self, brain: Brain) -> None:
        self._brain = brain

    def respond(self, message: str) -> Iterator[Chunk]:
        arrived = time.monotonic()

        canned = faster.reflex(message)
        if canned is not None:
            _pace(arrived)                              # pad instant reflex up to the floor
            yield Chunk(canned, "reflex", {"tier": "faster"})
            return

        yield Chunk(faster.filler(), "filler")            # instant ack — now recorded too
        started = time.monotonic()
        answer = self._brain.think(message, mode="fast")      # System 1 — /no_think
        latency_ms = int((time.monotonic() - started) * 1000)
        _pace(arrived)                                         # no-op when the model was slow
        yield Chunk(answer, "agent_msg", {
            "tier": "fast",
            "mode": "fast",
            "model": getattr(self._brain, "model", None),
            "latency_ms": latency_ms,
        })
