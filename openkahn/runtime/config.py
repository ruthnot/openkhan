"""RUNTIME — configuration.

Loads config.yaml if present, otherwise falls back to sane defaults so the project
runs out of the box. Today there is only one section (`think`); more get added as
layers come online.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "think": {
        "model": "qwen3:8b",
        "host": "http://localhost:11434",
        "temperature": 0.7,
    },
    "memory": {
        "db": "data/openkahn.db",
    },
    "control": {
        "poll_interval_seconds": 1.0,   # how often the worker checks the job queue
        "pid_file": "data/kahnd.pid",   # daemon liveness handle (start/stop/restart)
        "log_file": "data/kahnd.log",   # daemon stdout/stderr sink
    },
}


@dataclass
class ThinkConfig:
    model: str
    host: str
    temperature: float


@dataclass
class MemoryConfig:
    db: str


@dataclass
class ControlConfig:
    poll_interval_seconds: float
    pid_file: str
    log_file: str


@dataclass
class Config:
    think: ThinkConfig
    memory: MemoryConfig
    control: ControlConfig


def load(path: str | Path = "config.yaml") -> Config:
    data = copy.deepcopy(DEFAULTS)
    p = Path(path)
    if p.exists():
        user = yaml.safe_load(p.read_text()) or {}
        for section, values in user.items():
            data.setdefault(section, {}).update(values or {})
    t = data["think"]
    m = data["memory"]
    c = data["control"]
    return Config(
        think=ThinkConfig(model=t["model"], host=t["host"], temperature=t["temperature"]),
        memory=MemoryConfig(db=m["db"]),
        control=ControlConfig(
            poll_interval_seconds=c["poll_interval_seconds"],
            pid_file=c["pid_file"],
            log_file=c["log_file"],
        ),
    )
