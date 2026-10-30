#!/usr/bin/env python3
"""factory.py - the one entry point for Social Media Factory.

    python factory.py setup            install everything this computer needs
    python factory.py status           what is ready, what is not, and what to do next
    python factory.py doctor           prove the installed pieces really work
    python factory.py <verb> ...       everything else (runs inside the Social Media Factory's own Python)

Every skill, command and doc in this repo calls tools through this file and nothing else.
It uses no shell syntax, so it behaves the same in zsh, Git Bash, PowerShell and the desktop app.

This file and smf/bootstrap.py use only the standard library and old-Python-safe syntax, because
on first run they may be started by whatever Python happens to be on the computer.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Verbs that must work before the Social Media Factory's own Python environment exists.
PRE_ENV_VERBS = {"setup", "status", "doctor", "where", "help", "-h", "--help"}
# Foundation verbs whose help needs nothing installed, so `<verb> --help` works before setup too.
HELP_BEFORE_SETUP = {"guide", "sync-brand", "check-brand"}


def main(argv):
    from smf import bootstrap

    # Before anything is printed: a brand name or a post can be in any language, and the console
    # this is being read through may not be able to spell it.
    bootstrap.utf8_output()
    verb = argv[0] if argv else "help"

    if sys.version_info < (3, 8):
        print("This computer's Python is too old to start the Social Media Factory (needs 3.8 or newer just to "
              "begin; the Social Media Factory then installs its own). Ask Claude to run the setup skill.")
        return 2

    env_python = bootstrap.env_python()
    inside = bootstrap.running_inside_env()

    asks_help = "--help" in argv[1:] or "-h" in argv[1:]
    if verb not in PRE_ENV_VERBS and not inside and not (asks_help and verb in HELP_BEFORE_SETUP and not env_python):
        if not env_python:
            print("The Social Media Factory is not set up on this computer yet.\n"
                  "Next step: python factory.py setup")
            return 3
        # Re-run this same command inside the Social Media Factory's own Python. subprocess (not exec) because
        # exec does not hand the exit code back reliably on Windows. The second Python is asked for
        # UTF-8 too, or it reads the console's code page again and cannot print every language.
        return subprocess.call([env_python, os.path.join(ROOT, "factory.py")] + list(argv),
                               env=bootstrap.child_surroundings())

    if verb in ("help", "-h", "--help"):
        print(__doc__.strip())
        return 0
    if verb == "where":
        _opts, _words, rc = bootstrap.read_options(
            argv[1:], "where", "python factory.py where    print the path of the Social Media Factory's own Python (empty if not set up)")
        if rc is not None:
            return rc
        print(env_python or "")
        return 0 if env_python else 3
    if verb == "setup":
        return bootstrap.setup(argv[1:])

    # status and doctor prefer the Social Media Factory's Python when it exists (they can then test imports).
    if verb in ("status", "doctor") and env_python and not inside:
        return subprocess.call([env_python, os.path.join(ROOT, "factory.py")] + list(argv),
                               env=bootstrap.child_surroundings())

    from smf import cli
    return cli.main(argv)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\nStopped. Nothing is broken; run the same command again to continue.")
        sys.exit(130)
