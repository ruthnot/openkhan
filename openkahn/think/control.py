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

Tool use (search): before answering, a quick fast-mode **router** call decides
whether the turn needs a live web search and, if so, extracts a query. If yes,
Control calls the injected Search capability (Interact) and feeds the results back
into fast mode to synthesise the answer. The search capability is *injected*, so
Think doesn't hard-depend on Interact (it just needs something with `.search`).

Streaming: the answer is streamed as text deltas (`kind="delta"`, render-only),
followed by one final `kind="agent_msg"` chunk carrying the full text — that final
one is what gets recorded and stored in the conversation history.

Control yields **Chunk** objects (text + kind + meta + render/record flags) rather
than bare strings, so the Interact layer can render them live and log them with the
right kind/metadata. (The System-0 reflex and filler ack are deprecated — faster.py.)
"""
from __future__ import annotations

import random
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from openkahn.think.brain import Brain

# Minimum felt latency for a substantive reply, randomized so it isn't metronomic.
FELT_FLOOR_SECONDS = (1.0, 1.5)

# The router: a tiny fast-mode decision on whether this turn needs a web search.
# Plain-text verdict (easier for a small model than JSON): "SEARCH: <query>" or "NO".
ROUTER_SYSTEM = (
    "You are a router. Decide if answering the user's message needs a LIVE web "
    "search — current events, news, prices, schedules, recent releases, or a "
    "specific fact you are not confident about. General knowledge, chit-chat, math, "
    "or opinions do NOT need search.\n"
    "If a search is needed, reply EXACTLY: SEARCH: <a concise web query>\n"
    "Otherwise reply EXACTLY: NO\n"
    "Keep the query close to the user's wording; do NOT add a year unless the user "
    "mentioned one (today's date is given above if you need it).\n"
    "Reply with nothing else."
)


class Searcher(Protocol):
    """What Control needs from a search capability (Interact provides it). Results
    are duck-typed: each has `.title`, `.url`, `.snippet`."""

    def search(self, query: str, max_results: int | None = None) -> list: ...


@dataclass
class Chunk:
    """One renderable piece of a reply, tagged for rendering AND for the log."""

    text: str
    kind: str                                   # 'delta' | 'agent_msg' | 'search'
    meta: dict = field(default_factory=dict)
    record: bool = True                         # log to the observation stream?
    render: bool = True                         # show to the user? (final agent_msg: False)


def _pace(since: float) -> None:
    """Sleep so the reply never lands faster than a human-feeling floor (no-op if slow)."""
    floor = random.uniform(*FELT_FLOOR_SECONDS)
    elapsed = time.monotonic() - since
    if elapsed < floor:
        time.sleep(floor - elapsed)


class Control:
    def __init__(self, brain: Brain, search: Searcher | None = None) -> None:
        self._brain = brain
        self._search = search

    def respond(self, history: list[dict]) -> Iterator[Chunk]:
        """Answer the latest turn, streaming the reply. `history` is the full
        conversation (chat-shape dicts); the last entry is the current user message.

        Flow: route (does this need a web search?) → optionally search → stream the
        fast-mode answer (grounded on results if we searched). Both the routing and
        the synthesis use fast mode (System 1).
        """
        arrived = time.monotonic()

        query = self._route_search(history)
        if query is not None:
            yield Chunk(f"🔍 searching the web: {query}", "search", {"query": query})
            results = self._search.search(query)
            messages = [*history, {"role": "user", "content": self._results_context(query, results)}]
            meta = {"tier": "fast", "mode": "fast", "tool": "search",
                    "query": query, "results": len(results)}
        else:
            messages = history
            meta = {"tier": "fast", "mode": "fast"}

        parts: list[str] = []
        first = True
        for delta in self._brain.stream(messages, mode="fast"):
            if first:
                _pace(arrived)        # hold the *first* token to the felt-latency floor
                first = False
            parts.append(delta)
            yield Chunk(delta, "delta", record=False)         # render-only, per-token

        meta["model"] = getattr(self._brain, "model", None)
        meta["latency_ms"] = int((time.monotonic() - arrived) * 1000)
        # final chunk: the full text — recorded + stored in history, but not re-rendered
        yield Chunk("".join(parts), "agent_msg", meta, render=False)

    # --- tool routing --------------------------------------------------------

    def _route_search(self, history: list[dict]) -> str | None:
        """Ask fast mode whether the latest turn needs a web search. Returns the
        query to run, or None (no search capability, or not needed)."""
        if self._search is None:
            return None
        last = history[-1]["content"]
        verdict = self._brain.complete(ROUTER_SYSTEM, last, max_tokens=40)
        marker = "SEARCH:"
        idx = verdict.upper().find(marker)
        if idx == -1:
            return None
        query = verdict[idx + len(marker):].splitlines()[0].strip().strip('"').strip()
        return query or None

    @staticmethod
    def _results_context(query: str, results: list) -> str:
        """Fold search results into a message the model can answer from."""
        if not results:
            return (f'A web search for "{query}" returned no results. Tell the user '
                    "you couldn't find anything and answer from what you know.")
        lines = [f'Web search results for "{query}":', ""]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.title}\n   {r.url}\n   {r.snippet}")
        lines += ["", "Using these results, answer my previous question concisely "
                  "and name the most relevant source."]
        return "\n".join(lines)
