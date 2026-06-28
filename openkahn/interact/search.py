"""INTERACT layer — search: the agent reading the world (read-only web access).

Search is a **functionality of the Interact layer**, not a layer or a skill: it's
the world-input boundary's read-only mode (the agent pulling from the web, vs
Converse which exchanges chat, vs an Effect which changes the world). It returns
facts; it never acts. A *skill* (procedural memory) later strings this together
with Think and Memory to do research — but the search itself lives here.

The backend is swappable (mirroring `Brain` — an interface, not a hard-wired
model): a backend is just `callable(query, max_results) -> list[SearchResult]`.
The default is DuckDuckGo via `ddgs` — no API key, works out of the box. A keyed
provider (e.g. Tavily) can drop in later by passing a different backend.

Security note: this is the agent's **first external egress**. It is read-only, so
it needs only a `network` capability — no confirmation gate (those are for
side-effecting Effects). The Security plane will enforce that manifest later;
today the egress simply happens.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_MAX_RESULTS = 5


@dataclass
class SearchResult:
    """One hit: a title, the page URL, and a short snippet. No page body (yet)."""

    title: str
    url: str
    snippet: str


# A backend turns a query into results. Swap it to change providers.
Backend = Callable[[str, int], "list[SearchResult]"]


def duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    """Default backend — DuckDuckGo via `ddgs`. No API key required."""
    from ddgs import DDGS  # imported lazily so the package only loads if search is used

    hits = DDGS().text(query, max_results=max_results)
    return [
        SearchResult(
            title=h.get("title", ""),
            url=h.get("href", ""),
            snippet=h.get("body", ""),
        )
        for h in hits
    ]


class Search:
    """Read-only web search. Holds a backend + a default result cap."""

    def __init__(self, backend: Backend = duckduckgo, max_results: int = DEFAULT_MAX_RESULTS) -> None:
        self._backend = backend
        self._max_results = max_results

    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        """Run a query and return ranked results (most-relevant first)."""
        query = (query or "").strip()
        if not query:
            return []
        return self._backend(query, max_results or self._max_results)
