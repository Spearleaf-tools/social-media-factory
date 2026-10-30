#!/bin/bash
# mac_blank_computer.sh - CI (and local): install the Social Media Factory the way a real Mac person would.
#
#     bash tests/ci/mac_blank_computer.sh            # from the repo root
#
# Simulates: a ZIP download, unzipped into a folder with a space, an apostrophe, an ampersand and
# an accented letter, on a computer with NO Python and an EMPTY home folder (so every download is
# cold and nothing already on this machine can help). Leaves the real home folder untouched.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="${RUNNER_TEMP:-$(mktemp -d)}/factory-blank-mac"
KIT="$WORK/O'Neil & Søn kit"
HOME_DIR="$WORK/home"
rm -rf "$WORK"; mkdir -p "$KIT" "$HOME_DIR"

step() { printf '\n=== %s\n' "$1"; }
blank() { /usr/bin/env -i HOME="$HOME_DIR" PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=en_US.UTF-8 "$@"; }

step "Make the ZIP a person would download, unzip it somewhere awkward"
if git -C "$SRC" rev-parse HEAD >/dev/null 2>&1; then
  git -C "$SRC" archive --format=tar HEAD | tar -xf - -C "$KIT"
else
  (cd "$SRC" && tar --exclude=.git --exclude=.factory --exclude=.venv -cf - .) | tar -xf - -C "$KIT"
fi
echo "kit: $KIT"

step "First run, core tier (started from a different folder on purpose)"
cd "$WORK"
T0=$(date +%s)
blank /bin/sh "$KIT/install/first-run.sh"
echo "core install: $(( $(date +%s) - T0 ))s"

PY="$KIT/.venv/bin/python"
[ -x "$PY" ] || { echo "the Social Media Factory's Python was not created"; exit 1; }

step "Second run must skip everything"
T0=$(date +%s); blank "$PY" "$KIT/factory.py" setup; S=$(( $(date +%s) - T0 ))
echo "second run: ${S}s"; [ "$S" -le 60 ] || { echo "a repeated setup should be near-instant"; exit 1; }

step "Status, doctor, unit tests"
blank "$PY" "$KIT/factory.py" status
blank "$PY" "$KIT/factory.py" doctor
(cd "$KIT" && blank "$PY" -m unittest discover -s tests -t .)

step "A brand name in another language, read through a pipe"
# The output goes through a pipe and the child is told to write the old Western code page, which
# holds no Chinese and no emoji. The brand must still be created AND reported. Written as octal
# UTF-8 bytes because the bash macOS ships cannot spell \u escapes.
BAKERY=$(printf '\346\236\253\345\217\266 \360\237\215\236')
if ! SAID=$(blank PYTHONIOENCODING=cp1252 "$PY" "$KIT/factory.py" new-brand --name "$BAKERY" --id unicode-check 2>&1); then
  echo "$SAID"; echo "a brand named in Chinese with an emoji could not be created"; exit 1
fi
case "$SAID" in *Traceback*) echo "$SAID"; echo "creating it printed a traceback"; exit 1;; esac
echo "  created and reported without a crash"

step "Video tier, then the deep doctor (video program, codecs, speech model)"
T0=$(date +%s)
blank "$PY" "$KIT/factory.py" setup --tier video
blank "$PY" "$KIT/factory.py" doctor --deep
echo "video install + deep doctor: $(( $(date +%s) - T0 ))s"

step "What it cost"
du -sh "$KIT/.venv" "$KIT/.factory" "$HOME_DIR/Library/Caches/ms-playwright" "$HOME_DIR/.cache/huggingface" 2>/dev/null || true

printf '\nMAC BLANK-COMPUTER TEST PASSED\n'
