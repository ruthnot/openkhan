"""Enables `python -m openkahn ...` — used to spawn the detached kahnd daemon.

Delegates to the same entry point as the `kahn` console script, so the daemon
child runs identical code regardless of how it was launched.
"""
from openkahn.runtime.app import main

if __name__ == "__main__":
    main()
