"""THINK layer — reasoning.

The Brain is an *interface*, not a model — backends are swappable by config. It
runs in one of two modes, and the mode shapes *three* things, not just one:

  fast (System 1)  — thinking OFF + a terse persona + a short output cap: a quick,
                     intuitive, 1-3 sentence reflex. Brevity is the point — a short
                     answer is also a *fast* answer (fewer tokens = less latency).
  slow (System 2)  — thinking ON + a thorough persona + no cap: it reasons first,
                     then gives a full structured answer.

Each mode carries its own **system prompt** (the persona) and **options**
(`num_predict` cap), so the fast/slow split is real in behaviour, not just a
`think=` toggle. The router (control.py) currently only asks for `fast`; `slow`
works here but isn't routed yet — the full System 2 scaffolding (decompose /
self-consistency / tool-verify) comes later.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Literal, Protocol

import ollama

Mode = Literal["fast", "slow", "search"]


def _today() -> str:
    """Current local date, computed fresh per call (the daemon is long-running)."""
    return datetime.now().strftime("%A, %d %B %Y")


def _dated(system: str) -> str:
    """Prepend today's date so the model isn't stuck at its training cutoff —
    fixes wrong-year answers and stale years in search queries."""
    return f"Today's date is {_today()}.\n\n{system}"

# Shared capability note so the model knows what it can actually do. Search is run
# FOR the model by the system (Control's router), not called by the model — but from
# the user's view kahn can look things up, so it must never deny having web access.
CAN_SEARCH = (
    "You can search the web: when a question needs current or specific facts, the "
    "system runs a search automatically and gives you results to answer from. So "
    "never say you can't look things up. If asked to search but not told what, ask "
    "what to look up."
)
# System-1: fast, intuitive, brief. Lead with the answer; no ceremony.
FAST_SYSTEM = (
    "You are kahn, replying on reflex (System 1): fast, intuitive, and brief. "
    "Answer in 1-3 short sentences. Lead with the answer — no preamble, no lists, "
    "no headings. " + CAN_SEARCH + " If the question truly needs depth, give the "
    "gist in one line and offer to expand."
)
# System-2: deliberate, thorough, structured.
SLOW_SYSTEM = (
    "You are kahn, thinking carefully (System 2). Reason the problem through, then "
    "give a thorough, well-structured answer. " + CAN_SEARCH
)
# Search synthesis: still fast (thinking off, low latency) but NOT terse — it must
# actually use the results. Allows lists and a fuller answer, unlike the chat persona.
SEARCH_SYSTEM = (
    "You are kahn, answering with the help of fresh web search results provided to "
    "you. Give a complete, accurate answer grounded in those results — a few "
    "sentences, or a short bulleted list when the user asks for a list or multiple "
    "items. Name the most relevant source(s). If the results don't cover it, say so."
)
# Backstop output cap for fast replies: keeps System-1 brief even if it ignores the
# persona, and bounds worst-case latency. Generous enough not to clip 1-3 sentences.
FAST_NUM_PREDICT = 160
# Search answers need room for a list + citations — much higher cap than chat.
SEARCH_NUM_PREDICT = 600


class Brain(Protocol):
    """The Think layer's contract: a conversation + mode in, a reply out.

    `history` is the running conversation in chat-completion shape — a list of
    {"role": "user"|"assistant", "content": ...} dicts, oldest first, the last
    entry being the current user turn. The model is stateless, so the *whole*
    history is sent every call; the Brain prepends the per-mode system persona.
    """

    def think(self, history: list[dict], mode: Mode = "fast") -> str: ...

    def stream(self, history: list[dict], mode: Mode = "fast") -> Iterator[str]:
        """Same as think, but yields the reply in text deltas as they arrive."""
        ...

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str:
        """A one-shot completion with a caller-supplied system prompt (no persona,
        thinking off). For quick control decisions like routing, not chat replies."""
        ...


class OllamaBrain:
    """Local ollama backend. `mode` sets thinking, persona, and output cap together."""

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        temperature: float = 0.7,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self._client = ollama.Client(host=host)

    # --- shared request shaping ---------------------------------------------

    @staticmethod
    def _system(mode: Mode) -> str:
        persona = {"fast": FAST_SYSTEM, "slow": SLOW_SYSTEM, "search": SEARCH_SYSTEM}[mode]
        return _dated(persona)

    def _options(self, mode: Mode) -> dict:
        options = {"temperature": self.temperature}
        caps = {"fast": FAST_NUM_PREDICT, "search": SEARCH_NUM_PREDICT}  # slow = uncapped
        if mode in caps:
            options["num_predict"] = caps[mode]
        return options

    def _messages(self, mode: Mode, history: list[dict]) -> list[dict]:
        # persona first, then the full conversation so far (the model is stateless)
        return [{"role": "system", "content": self._system(mode)}, *history]

    # --- generation ----------------------------------------------------------

    def think(self, history: list[dict], mode: Mode = "fast") -> str:
        resp = self._client.chat(
            model=self.model,
            messages=self._messages(mode, history),
            think=(mode == "slow"),  # fast = thinking off (System 1); slow = on (System 2)
            options=self._options(mode),
        )
        return resp.message.content

    def stream(self, history: list[dict], mode: Mode = "fast") -> Iterator[str]:
        for part in self._client.chat(
            model=self.model,
            messages=self._messages(mode, history),
            think=(mode == "slow"),
            options=self._options(mode),
            stream=True,
        ):
            text = part.message.content
            if text:
                yield text

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str:
        options = {"temperature": self.temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        resp = self._client.chat(
            model=self.model,
            messages=[{"role": "system", "content": _dated(system)}, {"role": "user", "content": user}],
            think=False,
            options=options,
        )
        return resp.message.content
