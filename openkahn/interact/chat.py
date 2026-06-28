"""INTERACT layer — chat: a stateful conversation (the agent talking with you).

Chat is a functionality of the Interact layer, parallel to `search`: search is
read-only world *input*; chat is the bidirectional *conversation*. The job chat
has that search doesn't is **context** — an LLM is stateless, so to stay coherent
across turns ("what is Apple?" → "who is its CEO?") every request must carry the
*entire* prior conversation, not just the latest line. Chat owns that running
history and feeds all of it to Think each turn; without it, "who is the ceo" lands
with no idea you meant Apple.

A channel (the CLI now, Telegram later) is just transport: it drives one Chat per
session and renders/records the chunks. The conversation state lives here so it's
identical regardless of channel.

History is the standard chat-completion shape — a list of {"role", "content"}
dicts (role 'user' | 'assistant') — which is exactly what the Brain feeds the
model (it prepends the per-mode system persona).
"""
from __future__ import annotations

from collections.abc import Iterator

from openkahn.think.control import Chunk, Control


class Chat:
    """A single conversation: keeps history and feeds full context to Think."""

    def __init__(self, control: Control) -> None:
        self._control = control
        self._history: list[dict[str, str]] = []

    @property
    def history(self) -> list[dict[str, str]]:
        return self._history

    def respond(self, message: str) -> Iterator[Chunk]:
        """Append the user turn, stream Think's reply chunks, then record the reply
        back into history so the *next* turn has context."""
        self._history.append({"role": "user", "content": message})
        reply: list[str] = []
        for chunk in self._control.respond(self._history):
            if chunk.kind in ("agent_msg", "reflex"):  # the substantive reply (not filler)
                reply.append(chunk.text)
            yield chunk
        if reply:
            self._history.append({"role": "assistant", "content": "\n".join(reply)})
