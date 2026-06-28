"""RUNTIME — wires the layers together and dispatches a subcommand.

The only place that knows how to *construct* things. It loads config and opens the
database, then dispatches:

  Daemon (the always-live agent):
    kahn start              → start the kahnd daemon (drains the task queue)
    kahn stop               → stop the daemon
    kahn restart            → restart the daemon
    kahn status             → is the daemon up? how many tasks queued?

  Sessions & inspection (these run in-process; the daemon need not be up):
    kahn chat               → interactive chat REPL (builds Think + Interact)
    kahn chat --once MSG    → one-shot chat
    kahn submit [--text T]  → enqueue a task for the daemon to run (echo, for now)
    kahn log                → Observability log viewer (read-only; no model)

  Internal:
    kahn _daemon            → the daemon body itself (spawned by `kahn start`)

The reframe behind the command split: the agent is an always-live daemon (`start`);
a chat is just one session that connects, and you can exit it while kahnd keeps
running. Only `stop` ends the agent.
"""
from __future__ import annotations

import argparse

from openkahn.db.connection import connect
from openkahn.interact.cli import CLI
from openkahn.memory.observations import Observations
from openkahn.observability import logview
from openkahn.runtime import daemon
from openkahn.runtime.config import load
from openkahn.runtime.queue import Tasks
from openkahn.think.brain import OllamaBrain
from openkahn.think.control import Control


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kahn", description="openkahn — local agent")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")

    sub = parser.add_subparsers(dest="command")

    # Daemon lifecycle.
    sub.add_parser("start", help="start the kahnd daemon (the always-live agent)")
    sub.add_parser("stop", help="stop the kahnd daemon")
    sub.add_parser("restart", help="restart the kahnd daemon")
    sub.add_parser("status", help="show daemon status and queued task count")

    # Sessions & inspection.
    chat_p = sub.add_parser("chat", help="open an interactive chat session (REPL)")
    chat_p.add_argument("--once", metavar="MSG", help="send one message, print the reply, exit")

    submit_p = sub.add_parser("submit", help="enqueue a task for the daemon to run")
    submit_p.add_argument("--kind", default="echo", help="task kind (default: echo)")
    submit_p.add_argument("--text", default="", help="text payload for the task")

    log_p = sub.add_parser("log", help="show the recent observation stream (read-only)")
    log_p.add_argument("--limit", type=int, default=30, help="max observations to show (default 30)")

    # Internal: the daemon body, spawned detached by `start`.
    sub.add_parser("_daemon", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    cfg = load(args.config)

    # Daemon lifecycle — no DB/model construction needed here.
    if args.command == "start":
        daemon.start(cfg, args.config)
        return
    if args.command == "stop":
        daemon.stop(cfg)
        return
    if args.command == "restart":
        daemon.restart(cfg, args.config)
        return
    if args.command == "status":
        daemon.status(cfg)
        return
    if args.command == "_daemon":
        daemon.run(cfg)
        return

    # Everything below touches the database.
    conn = connect(cfg.memory.db)
    observations = Observations(conn)

    # Observability: just read the stream, no model needed.
    if args.command == "log":
        logview.show(observations, args.limit)
        return

    # Enqueue a task for the daemon's agent loop to pick up.
    if args.command == "submit":
        task = Tasks(conn).enqueue(args.kind, params={"text": args.text})
        print(f"queued task #{task.id} ({task.kind})")
        return

    # Chat: build Think + Interact (in-process; daemon need not be running).
    if args.command == "chat":
        brain = OllamaBrain(
            model=cfg.think.model,
            host=cfg.think.host,
            temperature=cfg.think.temperature,
        )
        cli = CLI(Control(brain), observations)
        if args.once:
            print(cli.run_once(args.once))
        else:
            cli.repl()
        return

    # No subcommand → show help.
    parser.print_help()


if __name__ == "__main__":
    main()
