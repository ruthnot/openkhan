# openkahn

A personal, self-improving agent framework that runs **fully local** on a Mac mini.

Named for Daniel **Kahn**eman — its core idea is a **fast/slow brain**: a fixed small local
model (`qwen2.5:7b`) answers easy turns in one pass (System 1) and escalates hard ones to the
*same* model wrapped in reasoning scaffolding (System 2). It gets smarter over time through
**memory + distilled skills**, not a bigger model.

It combines:
- **openclaw's** strength — a messaging connection layer (talk to it from Telegram), without the coupling, opacity, or security record.
- **Hermes Agent's** strength — a self-improving loop that distills successful workflows into reusable skills.

> Status: pre–Phase 0 (scaffold only). See [`docs/FRAMEWORK_PLAN.md`](docs/FRAMEWORK_PLAN.md)
> for the architecture, data model, phased roadmap, and security model.

## Layout

```
openkahn/
  config.yaml          # model tiers, allowlists, telegram token, budgets
  openkahn/            # the package (transport, gateway, queue, brain, memory, skills, learning, security, dashboard, db)
  tests/
  docs/FRAMEWORK_PLAN.md
```

## Stack

Python 3.12 · `uv` · FastAPI · SQLite + `sqlite-vec` + FTS5 · ollama (`qwen2.5:7b`, `nomic-embed-text`) · HTMX

## Getting started

Phase 0 is not built yet. Once it is:

```sh
uv sync
cp config.example.yaml config.yaml   # add your Telegram token
uv run kahn
```
