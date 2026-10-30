#!/bin/sh
# first-run.sh - for a Mac or Linux computer that has NO Python at all.
#
#     sh install/first-run.sh
#
# It downloads one small installer program (uv) INTO this folder, then lets it fetch a private
# Python and run the normal setup. No admin password. Nothing is added to your shell profile or
# PATH. Delete this folder and everything it installed here is gone.
#
# If the computer already has Python 3.8+, you do not need this: run  python3 factory.py setup
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HERE/.factory/bin"
mkdir -p "$BIN"

if [ ! -x "$BIN/uv" ]; then
  echo "Downloading the installer program into this folder..."
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | UV_UNMANAGED_INSTALL="$BIN" sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | UV_UNMANAGED_INSTALL="$BIN" sh
  else
    echo "This computer has neither curl nor wget, so nothing can be downloaded from here."
    echo "Install Python 3.12 from https://www.python.org/downloads/ and then run: python3 factory.py setup"
    exit 1
  fi
fi

cd "$HERE"
exec "$BIN/uv" run --no-project --python 3.12 factory.py setup "$@"
