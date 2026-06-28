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
from typing import Literal, Protocol

import ollama

Mode = Literal["fast", "slow"]

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
# Backstop output cap for fast replies: keeps System-1 brief even if it ignores the
# persona, and bounds worst-case latency. Generous enough not to clip 1-3 sentences.
FAST_NUM_PREDICT = 160


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
        return FAST_SYSTEM if mode == "fast" else SLOW_SYSTEM

    def _options(self, mode: Mode) -> dict:
        options = {"temperature": self.temperature}
        if mode == "fast":
            options["num_predict"] = FAST_NUM_PREDICT  # brevity backstop (also caps latency)
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
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            think=False,
            options=options,
        )
        return resp.message.content
