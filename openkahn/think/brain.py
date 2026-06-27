"""THINK layer — reasoning.

The Brain is an *interface*, not a model — backends are swappable by config. It
runs in one of two modes:

  fast (System 1)  — qwen3 with thinking OFF: one quick single pass.
  slow (System 2)  — qwen3 with thinking ON: it reasons before answering.

The router (control.py) currently only ever asks for `fast`. `slow` works here but
nothing routes to it yet — the full System 2 scaffolding (decompose / self-
consistency / tool-verify) comes later; this is just qwen3's native thinking toggle.
"""
from __future__ import annotations

from typing import Literal, Protocol

import ollama

Mode = Literal["fast", "slow"]


class Brain(Protocol):
    """The Think layer's contract: a message + mode in, a reply out."""

    def think(self, message: str, mode: Mode = "fast") -> str: ...


class OllamaBrain:
    """Local ollama backend. `mode` toggles qwen3's thinking on/off."""

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        temperature: float = 0.7,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self._client = ollama.Client(host=host)

    def think(self, message: str, mode: Mode = "fast") -> str:
        resp = self._client.chat(
            model=self.model,
            messages=[{"role": "user", "content": message}],
            think=(mode == "slow"),  # fast = thinking off (System 1); slow = on (System 2)
            options={"temperature": self.temperature},
        )
        return resp.message.content
