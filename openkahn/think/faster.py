"""THINK layer — System 0, the "faster" reflex tier.

DEPRECATED (kept, not deleted): `reflex()` is no longer routed by control.py. Fast
mode (System 1) is now terse by persona, so it handles greetings/acks itself with
acceptable latency, and one consistent voice beats a canned table. This module
stays because `filler()` is still used (the latency-masking ack before a fast turn),
and the reflex table is a useful fallback to re-enable if we ever want sub-second,
LLM-free trivial replies.

The cheapest tier: no LLM, no ML, just string matching. If the *whole* message is
a recognized trivial turn, we return a canned reply in microseconds. Everything
else returns None and falls through to real fast-think (System 1).

To avoid sounding like a broken record, each trigger maps to a *category*, and
each category has many interchangeable replies — we pick one at random per turn.
So "hi" three times in a row gives three different greetings. This is variety, not
coverage: we are NOT trying to enumerate conversation (that's the model's job).

Deliberately rules-only — no model. A reflex must be instant, and a second tiny
model on a 16GB box would cost a multi-second swap, defeating the point.
"""
from __future__ import annotations

import random
import re

# --- Response banks: one category -> many interchangeable replies -------------

GREETING = [
    "hey 👋", "hi there!", "hey, what's up?", "hello!", "yo 👋", "hey hey",
    "hi! how can I help?", "hey — what can I do for you?", "hello! what's on your mind?",
    "good to see you 👋", "hey there 👋", "morning ☀️",
]
THANKS = [
    "anytime.", "no problem.", "you got it.", "sure thing.", "happy to help.",
    "of course!", "no worries.", "glad to help.", "anytime 🙂", "my pleasure.",
    "all good!", "you bet.",
]
FAREWELL = [
    "see you 👋", "later!", "take care.", "bye!", "catch you later.",
    "see you around.", "talk soon.", "cya 👋",
]
NIGHT = [
    "night 🌙", "sleep well 🌙", "good night!", "rest up.", "night night 🌙",
]
AFFIRM = [
    "👍", "got it.", "cool.", "sounds good.", "alright!", "great 👍",
    "perfect.", "noted.", "👌", "right on.", "okay!", "gotcha.",
]

# Backchannel fillers — emitted before a real (non-reflex) turn to mask the
# multi-second model latency. Varied so the wait never feels scripted.
FILLERS = [
    "sure — one sec…", "let me think…", "give me a moment…", "just a sec…",
    "on it…", "one moment…", "let me check…", "hmm, let me see…", "working on it…",
    "sure thing, a sec…", "let me look into that…", "thinking…",
    "right, give me a second…", "okay, let me work that out…", "let me figure that out…",
    "good question — one sec…", "let me pull that together…", "on it, just a moment…",
    "let me chew on that…", "sec, thinking it through…",
]

# --- Trigger -> category (matched against the WHOLE normalized message) --------

_BY_CATEGORY: dict[tuple[str, ...], list[str]] = {
    ("hi", "hello", "hey", "yo", "gm", "heya", "hiya", "hi there", "hey there",
     "morning", "good morning", "good afternoon", "good evening",
     "sup", "what's up", "whats up", "wassup"): GREETING,
    ("thanks", "thank you", "thx", "ty", "thanks a lot", "thank you so much",
     "cheers", "appreciate it", "much appreciated"): THANKS,
    ("bye", "goodbye", "see ya", "see you", "later", "catch you later", "cya",
     "talk soon"): FAREWELL,
    ("gn", "good night", "goodnight", "night night"): NIGHT,
    ("ok", "okay", "k", "kk", "cool", "got it", "sounds good", "nice", "great",
     "perfect", "awesome", "alright", "all good", "gotcha", "sweet", "word"): AFFIRM,
}

# flatten to phrase -> bank for O(1) lookup
TRIGGERS: dict[str, list[str]] = {
    phrase: bank for phrases, bank in _BY_CATEGORY.items() for phrase in phrases
}

_TRAILING_PUNCT = re.compile(r"[!.?,…]+$")
_INNER_SPACES = re.compile(r"\s+")


def _normalize(message: str) -> str:
    """lowercase, collapse whitespace, drop trailing punctuation."""
    m = message.strip().lower()
    m = _TRAILING_PUNCT.sub("", m)   # "thanks!!!" -> "thanks"
    m = _INNER_SPACES.sub(" ", m)    # "good   morning" -> "good morning"
    return m.strip()


def reflex(message: str) -> str | None:
    """A varied canned reply if the whole message is a trivial turn, else None."""
    bank = TRIGGERS.get(_normalize(message))
    return random.choice(bank) if bank else None


def filler() -> str:
    """A varied 'give me a sec' backchannel for real turns."""
    return random.choice(FILLERS)
