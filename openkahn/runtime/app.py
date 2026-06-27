"""RUNTIME — wires the layers together and starts a channel (or a viewer).

The only place that knows how to *construct* things. It loads config and opens the
Memory database, then dispatches a subcommand:
  - `kahn start`            → interactive chat REPL (builds Think + Interact)
  - `kahn start --once MSG` → one-shot chat
  - `kahn log`              → Observability log viewer (read-only; never touches the model)
  - `kahn`                  → help
"""
from __future__ import annotations

import argparse

from openkahn.db.connection import connect
from openkahn.interact.cli import CLI
from openkahn.memory.observations import Observations
from openkahn.observability import logview
from openkahn.runtime.config import load
from openkahn.think.brain import OllamaBrain
from openkahn.think.control import Control


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kahn", description="openkahn — local agent (skeleton)")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")

    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="start an interactive chat session (REPL)")
    start_p.add_argument("--once", metavar="MSG", help="send one message, print the reply, exit")

    log_p = sub.add_parser("log", help="show the recent observation stream (read-only)")
    log_p.add_argument("--limit", type=int, default=30, help="max observations to show (default 30)")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    cfg = load(args.config)

    conn = connect(cfg.memory.db)
    observations = Observations(conn)

    # Observability: just read the stream, no model needed.
    if args.command == "log":
        logview.show(observations, args.limit)
        return

    # Chat: build Think + Interact.
    if args.command == "start":
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
