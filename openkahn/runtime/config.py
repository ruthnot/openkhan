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
    }
}


@dataclass
class ThinkConfig:
    model: str
    host: str
    temperature: float


@dataclass
class Config:
    think: ThinkConfig


def load(path: str | Path = "config.yaml") -> Config:
    data = copy.deepcopy(DEFAULTS)
    p = Path(path)
    if p.exists():
        user = yaml.safe_load(p.read_text()) or {}
        for section, values in user.items():
            data.setdefault(section, {}).update(values or {})
    t = data["think"]
    return Config(think=ThinkConfig(model=t["model"], host=t["host"], temperature=t["temperature"]))
