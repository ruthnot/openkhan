"""OBSERVABILITY plane — the log viewer.

A read-only window onto the Memory layer's observation stream. It calls the
Observations read API and pretty-prints the most recent slice (capped). It only
ever *reads* — that's what makes Observability a plane, not a layer.
"""
from __future__ import annotations

from datetime import datetime

from openkahn.memory.observations import Observation, Observations

# how each kind shows in the left gutter
_LABELS = {
    "user_msg": "you →",
    "agent_msg": "kahn ←",
    "reflex": "kahn ←",
    "filler": "kahn ⋯",
    "system": "  ·",
}
_CONTENT_WIDTH = 64


def _local_time(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone().strftime("%H:%M:%S")


def _meta_tag(ob: Observation) -> str:
    tier = (ob.meta or {}).get("tier")
    if not tier:
        return ""
    if "latency_ms" in ob.meta:
        return f"  [{tier} {ob.meta['latency_ms']}ms {ob.meta.get('model', '')}]".rstrip()
    return f"  [{tier}]"


def _line(ob: Observation) -> str:
    label = _LABELS.get(ob.kind, ob.kind)
    content = (ob.content or "").replace("\n", " ")
    if len(content) > _CONTENT_WIDTH:
        content = content[: _CONTENT_WIDTH - 1] + "…"
    return f" {_local_time(ob.ts)}  {label:7} {content}{_meta_tag(ob)}"


def show(observations: Observations, limit: int) -> None:
    obs = observations.recent(limit)
    if not obs:
        print("(no observations yet — talk to kahn first)")
        return
    print(f"openkahn log — last {len(obs)} observation(s), oldest first\n")
    current_day = None
    for ob in obs:
        if ob.day != current_day:
            current_day = ob.day
            print(current_day)
        print(_line(ob))
