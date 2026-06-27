"""RUNTIME — wires the layers together and starts a channel.

This is the only place that knows how to *construct* things. It loads config, opens
the Memory database, builds the brain (Think), wraps it in the router (Control), and
injects both the router and the observation store into the CLI (Interact). Those
dependency-injection seams let us later swap the CLI for Chainlit/Telegram, the
brain for a bigger model, or the store's backing without touching the other layers.
"""
from __future__ import annotations

import argparse

from openkahn.db.connection import connect
from openkahn.interact.cli import CLI
from openkahn.memory.observations import Observations
from openkahn.runtime.config import load
from openkahn.think.brain import OllamaBrain
from openkahn.think.control import Control


def main() -> None:
    parser = argparse.ArgumentParser(prog="kahn", description="openkahn — local agent (skeleton)")
    parser.add_argument("--once", metavar="MSG", help="send one message, print the reply, exit")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    args = parser.parse_args()

    cfg = load(args.config)

    conn = connect(cfg.memory.db)
    observations = Observations(conn)

    brain = OllamaBrain(
        model=cfg.think.model,
        host=cfg.think.host,
        temperature=cfg.think.temperature,
    )
    control = Control(brain)
    cli = CLI(control, observations)

    if args.once:
        print(cli.run_once(args.once))
    else:
        cli.repl()


if __name__ == "__main__":
    main()
