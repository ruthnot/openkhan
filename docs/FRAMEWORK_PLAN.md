# openkahn — A Personal Agent Framework (openclaw × Hermes), built to learn

> Named for Daniel **Kahn**eman (fast/slow thinking), keeping the `open*` convention.
> Package/repo: `openkahn` · CLI: `kahn`

## Context

You run **openclaw** on a 16GB Mac mini and like its connection layer (talk to the agent
from Telegram). But it hangs, you can't see what it's doing, it has a documented security
record (9 CVEs in 4 days, ~12% malware in its ClawHub skill marketplace), you don't
understand how/whether it learns, and metered API is expensive.

You want to **build your own framework** that combines:
- **openclaw's** strength — a messaging connection layer + gateway, and
- **Hermes Agent's** strength (Nous Research) — a **self-improving loop** that distills
  successful workflows into reusable skills and refines them over time,

while you **learn how each piece works as you build it**. It must run on the 16GB Mac mini
doing basic tasks first (news brief, library-room booking — you already have working
booking scripts in the openclaw workspace), then **migrate to a 64GB Mac mini** for heavier
work (e.g. day-trade research) as a *config change, not a rewrite*.

Goal of this doc: a phased build where every phase ships something working **and** teaches
one concept. Greenfield, Python, fully local v1.

---

## How openclaw and Hermes do it (so we can borrow deliberately)

| Concern | openclaw | Hermes | What we take |
|---|---|---|---|
| Transport | Pluggable channels behind a WebSocket gateway (port 18789), tightly coupled to its agent loop | Similar multi-channel gateway | **Our own thin Telegram transport** (~200 lines, no coupling) |
| Memory | SQLite + FTS5 + `sqlite-vec` (3072-dim) RAG over markdown files | Persistent cross-session memory | SQLite + FTS5 + `sqlite-vec`, but **DB-first** (episodes/facts/skills as rows, not just .md) |
| Learning | **Manual** — agent rewrites `MEMORY.md` on heartbeat. No real loop. | **Self-improving loop**: solve → distill into reusable skill → refine | **Hermes-style loop**, made *outcome-grounded* for a small model |
| Skills | Markdown `SKILL.md` + optional scripts; marketplace had malware | Auto-created from your workflows | Same `SKILL.md` shape, **no marketplace**, sandboxed, promotion-gated |
| Observability | Has a real dashboard + `status --deep` (you under-used it) | — | Our own dashboard focused on **"what is it doing right now"** |
| Robustness | Session queue, but turns can hang with no watchdog | — | **Per-turn watchdog + timeouts + circuit breakers** |

---

## Architecture model — four layers + two planes

The **generic** framework (any agent, not just this one): four layers + two cross-cutting
planes. **Skills are not a layer — they are procedural memory.**

```
        ┌── Observability ──┐              ┌── Security ──┐
        │   (watch, r/o)    │              │  (gate, enforce) │
        ▼                   │              ▼              │
  ┌─────────────────────────────────────────────────────────┐
  │  INTERACT   world boundary: converse · sense · effect    │  ◄─ online (awake)
  ├─────────────────────────────────────────────────────────┤
  │  THINK      control/orchestrator + fast/slow reasoning   │  ◄─ online (awake)
  ├─────────────────────────────────────────────────────────┤
  │  MEMORY     working · episodic · semantic · procedural   │  ◄─ shared substrate
  ├─────────────────────────────────────────────────────────┤
  │  REFLECT    review past → distill + promote → Memory     │  ◄─ offline (asleep)
  └─────────────────────────────────────────────────────────┘
```

**Layers**
- **Interact** — the world I/O boundary, bidirectional. Sub-modes (built later): **Converse**
  (chat I/O — Telegram now, email later), **Sense** (read-only pulls — web/API/RSS),
  **Effect** (side-effecting actions — book/send/pay; confirmation-gated). *Converse is one
  way to act, not the whole layer.*
- **Think** — control/orchestrator **and** fast/slow reasoning about the **current** turn.
  Online, latency-bound. Houses System-1/System-2 routing (the router is a control decision).
- **Memory** — the shared substrate the stack rests on: **working** (live turn), **episodic**
  (what happened), **semantic** (facts), **procedural** (= **Skills**).
- **Reflect** — offline consolidation. Same brain as Think, pointed at the **past** instead of
  now, writing to **Memory** instead of replying. Reviews episodes → distills candidates
  (`reflect`) → gates candidate→trusted (`promote`). **Its only customer is Memory**;
  improvement reaches Think/Interact only because Memory got richer. **Outcome-grounded, not
  introspective** — keys on real results (booking succeeded? user corrected me?), because
  self-critique is unreliable on a 7B.

**Two planes (not layers — they wrap all four)**
- **Observability** — *watches* the stack (read-only): "what is it doing right now."
- **Security** — *gates* the stack (enforces): peer allowlist on Interact, sandbox + capability
  manifest on Skills, confirmation gates on `Effect`. One reads, one enforces.

**Wake / sleep.** Think and Interact run **awake** (online, fast — System 1 mostly). Reflect
runs **asleep** (offline, on the heartbeat, when you're not talking) — slow thinking is free
there because nothing is waiting. Idle time hosts two distinct activities off the same
heartbeat: **proactive Act** (scheduled work — the morning news brief) and **Reflect**
(consolidation, no external output). The learning **signal originates at the Interact
boundary** (succeeded / corrected) → episode log → Reflect picks it up later.

---

## Architecture spine (runtime data-flow)

```
Telegram ──► Transport ──► Task Queue (DB-backed, state machine)
                               │
                               ▼
                          Agent Loop ──► Brain (fast/slow) ──► System 1: qwen2.5:7b single-pass
                               │              (pluggable)  └─► System 2: SAME 7B + scaffolding
                               │                                  └─► [later slot] claude -p / codex exec / 64GB-local
                               ├──► Memory (short-term summary + long-term DB, FTS+vec)
                               ├──► Skills (retrieved, sandboxed, allowlisted)
                               └──► Episode log ──► Reflection loop ──► candidate skills/facts
                               
   Everything observable via FastAPI dashboard (localhost, reachable over Tailscale)
```

**Two levels of control (one idea — Think's "orchestrator" — at two scopes).** "Control" is
Think's word; it is *not* a separate layer or plane. It shows up twice:
- **Turn-level** — `think/control.py` routes a *single live turn* (reflex / fast / slow).
  Online, latency-bound. *The router is a control decision* → this is **Think**.
- **Task-level** — the **Agent Loop** (`runtime/worker.py`) drains the DB-backed **task queue**
  and dispatches each unit of background work, *invoking* Think per task. This is **runtime
  plumbing that hosts the process** — not a layer, not a plane (planes only *watch* or *gate*).
  The always-live `kahnd` daemon **is** this loop; a chat session just connects to it.

**Design principles**
- **Brain = an interface, not a model.** `Brain.think(task, mode, context) -> {answer, confidence, trace}`. Backends are swappable by config (`system1`, `system2`, `embeddings` tiers).
- **System 2 = invocation strategy, not a bigger model.** Same 7B, more test-time compute (decompose → ground → self-consistency vote → tool-verify → confidence). Speed-not-a-problem is what makes this viable.
- **Get smarter via skills + memory, not model size.** A fixed 7B improves because procedural memory accumulates and context is grounded.
- **Outcome-grounded learning.** Reflection keys on real outcomes (booking succeeded? user corrected me?), not self-critique — critical for a 7B.
- **Security in code, not just in the prompt.** Capability manifests, allowlists, confirmation gates enforced by the runtime.
- **Portable & config-driven.** 16→64 migration = copy dir + DB file, edit which model each tier points to.

---

## Tech stack

- **Python 3.12**, `uv` for env/deps
- **FastAPI + Uvicorn** — gateway webhook, dashboard API/UI
- **SQLite** + `sqlite-vec` + FTS5 (via `apsw`), schema modeled with **SQLModel** (Postgres-ready later)
- **ollama** Python client for local models; `httpx` for transport/CLI escalation
- **Embeddings**: `nomic-embed-text` via ollama (small RAM) — keeps 16GB headroom
- **Scheduler**: APScheduler (cron + heartbeat)
- **Telegram**: raw Bot API long-poll via `httpx` (thin, no heavy SDK)
- **Skill sandbox**: `subprocess` with restricted env, timeouts, declared-capabilities only
- **pydantic** everywhere for structured LLM output + validation (catches 7B malformed output)
- Dashboard UI: server-rendered + **HTMX** (no build step; trivial on a mini)

---

## Repo layout

```
openkahn/
  pyproject.toml             # uv project, deps, `kahn` entrypoint
  config.example.yaml        # copy to config.yaml to override defaults
  openkahn/
    interact/                # LAYER 1 — world I/O boundary
      cli.py                 #   [v0] dev CLI channel (a converse sub-mode)
      converse/              #   (later) Telegram long-poll, email
      sense/                 #   (later) read-only web/API/RSS pulls
      effect/                #   (later) side-effecting actions (gated)
    think/                   # LAYER 2 — control + reasoning
      brain.py               #   [v0] Brain interface + OllamaBrain (fast-think)
      backends/              #   (later) cli / 64GB backends, scaffold.py (System 2)
    memory/                  # LAYER 3 — substrate (working/episodic/semantic/procedural)
      skills/builtin/        #   (later) procedural memory: news_brief, library_booking
    reflect/                 # LAYER 4 — offline consolidation (reflect + promote) (later)
    observability/           # plane — watch (dashboard) (later)
    security/                # plane — gate (manifests, sandbox, confirmation) (later)
    runtime/                 # plumbing — wires layers, hosts the process + the agent loop
      app.py                 #   `kahn` entrypoint: dispatch subcommands
      config.py              #   config loader (defaults + config.yaml)
      daemon.py              #   kahnd lifecycle: start/stop/restart/status (detached process)
      queue.py               #   task-queue access (the DB-backed work queue) + watchdog
      worker.py              #   the agent loop: drain tasks, dispatch by kind, record outcomes
    db/                      #   schema bootstrap (observations, tasks)
    __main__.py              #   `python -m openkahn` → re-enters app.main (spawns the daemon)
  tests/
```

## Data model (SQLite)

- `episodes` — one per task: goal, channel/peer, plan, tool_calls(json), outcome, user_feedback, confidence, tokens, timing
- `messages` — raw transcript rows (long-term raw memory)
- `facts` — durable atomic memories (text, embedding, source episode, confidence)
- `skills` — name, description, body(md), script_path, capabilities(json), status(candidate|trusted), success/fail counts, embedding
- `tasks` — work queue drained by the kahnd agent loop: kind, params(json), requester(json: channel/peer), state(queued|running|done|failed|timeout), result/error, created/started/finished. *(planned: heartbeat_ts + attempts for the stage-2 watchdog)*
- `summaries` — short-term rolling summaries per session
- vec/FTS virtual tables over `facts`, `messages`, `skills`

---

## Build status (incremental — one layer at a time, to learn each piece)

Building slowly, smallest working slice first, adding one layer/plane at a time.

- **[done] v0 — Interact(CLI) → Think(control → faster / fast).** A `kahn` CLI types into the
  Think router (`control.py`), which picks a tier:
  - **faster** (System 0, `faster.py`) — table lookup, no LLM. Greetings/acks → a varied
    canned reply (category banks + `random.choice`, ~80 phrases). Paced to a ~0.5–1s
    felt-latency floor so it doesn't feel robotic.
  - **fast** (System 1, `brain.think(mode="fast")`) — `qwen3:8b` with thinking **off**
    (`/no_think`), single pass (~1–3s warm). Preceded by an instant varied filler.
  - **slow** (System 2, `brain.think(mode="slow")`) — thinking **on**. Implemented at the
    Brain, **not routed yet**; full scaffolding (decompose / self-consistency / verify) later.

  Control yields chunks; the CLI just renders them. The felt-latency floor pads instant
  replies but never delays slow ones (measured from message arrival). No memory yet.
  Run: `uv run kahn` or `uv run kahn --once "…"`.
- **[done] Memory tier 1 — observations (the stream).** Append-only SQLite diary
  (`memory/observations.py` + `db/connection.py`): each turn records `user_msg`,
  `reflex`/`agent_msg` (meta: tier/model/latency_ms), and `system` start/end —
  timestamped, bucketed by local day/hour. Interact owns recording (session/turn ids);
  Think yields tagged `Chunk`s; the filler isn't recorded. Read API: `recent/session/day`.
  Generative-Agents memory-stream shape, MemGPT-recall style. **Records, doesn't yet
  *remember*** — reading-into-context is the next tier. DB at `data/openkahn.db`.

- **[done] Observability (plane) — `kahn log`.** Read-only viewer (`observability/logview.py`)
  over the observation stream: `kahn log` shows the latest N (default `--limit 30`),
  oldest-first, with day headers, local time, you→/kahn← gutter, and tier/latency tags.
  Never touches the model — first piece of the "what is it doing" answer.

- **[done] Always-live daemon — `kahnd` + the task queue.** The agent now runs as a background
  daemon draining a DB-backed task queue, so *the agent is always live and a chat is just one
  session that connects*: `kahn start` (daemon) · `kahn chat` (session — exit anytime, daemon
  stays up) · `kahn stop` (the only thing that ends the agent) · `restart`/`status` ·
  `kahn submit` (enqueue). Runtime plumbing, **not a layer/plane**: `runtime/queue.py` (the
  `tasks` table, queued→running→done/failed), `runtime/worker.py` (the agent loop — claim,
  dispatch by `kind`, record outcomes to the observation stream under channel `kahnd`),
  `runtime/daemon.py` (detached process + PID file, graceful SIGTERM stop). An `echo` handler
  proves the queue→loop→memory pipe. **Watchdog (stage 1): reclaim-on-startup** — kahnd
  requeues any task left `running` by a crashed worker (safe: single worker, so a `running` row
  at boot is always an orphan). chat + daemon are separate processes sharing one SQLite DB
  (WAL + busy_timeout). *Stage-2 watchdog (heartbeat + per-task timeout for live hangs) is
  Phase 6.*

- **[next] Interact: Chainlit channel** over localhost + Tailscale, so the same Think layer
  is reachable from the laptop browser. (CLI stays as the dev channel.)
- then: Memory → Think System 2 (scaffold) + router → Skills + Security → Reflect → robustness.

---

## Phased roadmap (each phase = working increment + one concept)

**Phase 0 — Skeleton.** Repo, `config.yaml`, DB schema, Telegram echo bot, FastAPI dashboard
showing "hello + task queue (empty)". *Learn: the message→queue→reply loop and transport.*

**Phase 1 — Single-brain agent.** `qwen2.5:7b` answers messages with structured tool-calling;
every turn logged as an `episode`; dashboard shows the **live current step**. *Learn: agent
loop + observability (kills the "can't see what it's doing" pain immediately).*

**Phase 2 — Memory.** SQLite FTS+vec; ingest messages/facts; short-term rolling summary +
long-term hybrid retrieval; per-turn context assembly. *Learn: RAG, short vs long term.*

**Phase 3 — Fast/slow brain.** `Brain` interface; System 1 router decides "is this hard?";
System 2 = same 7B with `scaffold.py` (decompose → ground → self-consistency vote →
tool-verify → confidence score). *Learn: test-time compute; why scaffolding > raw model.*

**Phase 4 — Skills + security.** `SKILL.md` format, embedding retrieval, subprocess sandbox,
capability manifests + allowlist + confirmation gates. Port your existing **library booking**
(`sjpl-*.js`) and **news brief** as the first two skills. *Learn: procedural memory + a real
security model (the openclaw CVE lesson).*

**Phase 5 — Learning loop (the Hermes piece).** Outcome-grounded `reflect.py`: review episodes
where outcome=success or user-corrected → propose candidate skills/facts → `promote.py` gate
(N successful uses or your approval before "trusted"). Runs on heartbeat. *Learn: how an agent
actually evolves — and why it's safe.*

**Phase 6 — Robustness + escalation.** Per-turn watchdog (timeout → kill, log, notify, don't
block queue), retries, circuit breakers; confidence-gated **escalation slot** wired to a
subscription CLI (`claude -p` / `codex exec`) or held for the 64GB box. *Learn: reliability +
graceful degradation (kills the "stuck forever" pain).*

**Phase 7 — 64GB migration.** Copy project dir + DB; edit `config.yaml` to point `system2` at
a local 32–70B Q4 model; add heavier skills (day-trade research). *Learn: migration as config.*

---

## Security model (explicit, because of openclaw's record)

- **No skill marketplace.** Skills are local, authored or self-distilled, and start as `candidate`.
- **Capability manifest** per skill (declares tools/network/files). Anything undeclared is blocked at runtime.
- **Subprocess sandbox**: restricted env vars, no network unless declared, hard timeout.
- **Confirmation gates** for external/irreversible actions (send email, confirm booking) — enforced in `security/policy.py`, not just asked for in a prompt.
- **Telegram peer allowlist** (pairing), loopback-bound gateway, Tailscale for remote dashboard access (no public exposure).

---

## Verification (per phase, end-to-end)

- **P0**: send Telegram msg → see echo; open `http://<tailscale>/` → dashboard loads, queue visible.
- **P1**: ask a question → reply arrives; dashboard shows the live step; `select * from episodes` has a row.
- **P2**: tell it a fact, ask later in a new session → it recalls via retrieval; inspect `facts`/vec query.
- **P3**: give a multi-step task → dashboard shows decomposition + self-consistency samples + a confidence score.
- **P4**: run news-brief and a library-booking dry-run; attempt an undeclared action → blocked; external action → asks to confirm.
- **P5**: complete a novel workflow twice → a `candidate` skill appears; approve it → becomes `trusted` and is reused.
- **P6**: force a hang (sleep in a skill) → watchdog kills it, logs timeout, notifies you, queue keeps moving.
- **P7**: on 64GB, flip `system2` to a local big model → same tasks pass with higher confidence; no code change.

---

## Open knobs (decide as we go, not blocking)

- Exact System-1 vs System-2 routing threshold (start simple: keyword/length heuristic + a System-1 "is this hard?" classifier).
- Self-consistency sample count (start 3).
- Heartbeat cadence for reflection (start hourly, active-hours only).
- When to introduce the subscription CLI escalation (Phase 6, only if 7B confidence is too often low).
