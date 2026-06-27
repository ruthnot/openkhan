"""THINK layer — control / orchestrator (the router).

Decides *how* to answer each turn, then produces the answer as a stream of chunks.
Today it knows two tiers:

  System 0 (reflex)  faster.reflex()  — instant canned reply, no LLM
  System 1 (fast)    brain.think()    — one single-pass model call

Pacing / "felt latency": an instant reply feels robotic. So every *substantive*
reply is held to a minimum felt-latency floor (~0.5-1s), measured from the moment
the message arrived. This pads an instant reflex up to a human beat — but it NEVER
slows a reply that already took longer (the model's own latency sails past the
floor), so real turns lose nothing. That's the trick: we only pad where no real
work is happening, so the delay is never additive to the slow path.

Acknowledgements (fillers) stay instant on purpose — a quick "I heard you" is good
responsiveness; it's the answer that should feel composed.

Control *yields* chunks instead of returning a string so the Interact layer can
render each piece the moment it's ready, staying a dumb renderer with no routing
logic of its own. (This is also where token-streaming slots in later.)
"""
from __future__ import annotations

import random
import time
from collections.abc import Iterator

from openkahn.think import faster
from openkahn.think.brain import Brain

# Minimum felt latency for a substantive reply, randomized so it isn't metronomic.
FELT_FLOOR_SECONDS = (0.5, 1.0)


def _pace(since: float) -> None:
    """Sleep so the reply never lands faster than a human-feeling floor.

    No-op when more than the floor has already elapsed since `since` — so slow
    (model) turns are never delayed; only instant ones get padded up.
    """
    floor = random.uniform(*FELT_FLOOR_SECONDS)
    elapsed = time.monotonic() - since
    if elapsed < floor:
        time.sleep(floor - elapsed)


class Control:
    def __init__(self, brain: Brain) -> None:
        self._brain = brain

    def respond(self, message: str) -> Iterator[str]:
        arrived = time.monotonic()

        canned = faster.reflex(message)
        if canned is not None:
            _pace(arrived)                     # pad the instant reflex up to the floor
            yield canned                       # System 0 — model never touched
            return

        yield faster.filler()                          # instant ack (varied each turn)
        answer = self._brain.think(message, mode="fast")  # System 1 — /no_think, single pass
        _pace(arrived)                         # no-op when the model was slow; pads if fast
        yield answer
