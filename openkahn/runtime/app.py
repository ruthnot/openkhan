"""RUNTIME — wires the layers together and starts a channel.

This is the only place that knows how to *construct* things. Interact and Think do
not build each other; the runtime loads config, builds the brain (Think), injects
it into the CLI (Interact), and runs it. That dependency-injection seam is what
lets us later swap the CLI for Chainlit/Telegram, or the brain for a bigger model,
without touching the other layer.
"""
from __future__ import annotations

import argparse

from openkahn.interact.cli import CLI
from openkahn.runtime.config import load
from openkahn.think.brain import OllamaBrain
from openkahn.think.control import Control


def main() -> None:
    parser = argparse.ArgumentParser(prog="kahn", description="openkahn — local agent (skeleton)")
    parser.add_argument("--once", metavar="MSG", help="send one message, print the reply, exit")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    args = parser.parse_args()

    cfg = load(args.config)
    brain = OllamaBrain(
        model=cfg.think.model,
        host=cfg.think.host,
        temperature=cfg.think.temperature,
    )
    control = Control(brain)
    cli = CLI(control)

    if args.once:
        print(cli.run_once(args.once))
    else:
        cli.repl()


if __name__ == "__main__":
    main()
