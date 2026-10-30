"""state.py - the small per-brand files the posting tools remember things in.

Two kinds of file live under Client/<brand>/_state/ besides the posting ledger:

  * a JSON state file (what the shorts planner has booked, where each clip is in the
    test-and-promote loop). It is read STRICTLY: a file that cannot be read is an error, never an
    empty file, because "nothing is booked" is exactly the belief that causes a double booking.
    Every change happens inside one lock, on a copy read fresh inside that lock, and is written
    whole in one step. A lock around the read AND the write is the point: writing to a temporary
    file only protects a reader from half a file, it does nothing for two writers who both read
    the old version and then each save their own.
  * a JSON-lines log that only ever grows (what was sent, results over time, decisions made).
    New lines are added by building the longer file beside the old one and swapping it in, so a
    crash leaves either the old log or the new one and never a torn line. Lines already written
    are copied byte for byte and never parsed and rewritten.

Every file names the brand it belongs to, and a file that names another brand is refused.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager

from smf.posting.ledger import _Lock
from smf.brands import replace_patiently


class StateError(Exception):
    """Worded for the person. Raised instead of guessing what a damaged file used to say."""


def _write_atomic(path, payload_bytes):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload_bytes)
            f.flush()
            os.fsync(f.fileno())
        replace_patiently(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class StateFile(object):
    """One JSON state file for one brand. `what` names it in plain words for error messages."""

    def __init__(self, brand, filename, what, fresh=None):
        self.brand_id = brand.id
        self.dir = brand.state_dir
        self.path = os.path.join(self.dir, filename)
        self.lock_path = os.path.join(self.dir, os.path.splitext(filename)[0] + ".lock")
        self.what = what
        self._fresh = dict(fresh or {})

    def read(self):
        """The current contents. Safe for looking; never save a copy made outside `edit()`."""
        if not os.path.exists(self.path):
            data = json.loads(json.dumps(self._fresh))
            data["brand"] = self.brand_id
            return data
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise StateError("The record of %s for this brand is damaged and cannot be read (%s). Nothing was "
                             "changed, and nothing new will be planned until it is repaired, so nothing gets "
                             "booked twice. Ask Claude to repair it." % (self.what, type(e).__name__))
        if not isinstance(data, dict):
            raise StateError("The record of %s for this brand is not in the expected shape. Nothing was changed."
                             % self.what)
        if data.get("brand") != self.brand_id:
            raise StateError("This record of %s belongs to '%s', not '%s'. Nothing was changed."
                             % (self.what, data.get("brand"), self.brand_id))
        for key, value in self._fresh.items():
            if not isinstance(data.get(key), type(value)):
                raise StateError("The record of %s for this brand is missing its '%s' section. Nothing was "
                                 "changed. Ask Claude to repair it." % (self.what, key))
        return data

    @contextmanager
    def edit(self):
        """Read, change and save as one step that no other run can interleave with.
        If the block raises, the file is left exactly as it was."""
        os.makedirs(self.dir, exist_ok=True)
        with _Lock(self.lock_path):
            data = self.read()
            yield data
            _write_atomic(self.path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


# ----------------------------------------------------------------------------- logs that only grow
def read_lines(path):
    """(rows, unreadable): every line of a JSON-lines log that parses, and how many did not.
    One bad line never hides the rest of the log, and it is counted so it can be reported."""
    rows, bad = [], 0
    if not os.path.isfile(path):
        return rows, bad
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                bad += 1
    return rows, bad


def append_lines(path, rows, lock_path=None):
    """Add rows to the end of a log. What is already there is kept byte for byte."""
    if not rows:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock_path = lock_path or (path + ".lock")
    with _Lock(lock_path):
        old = b""
        if os.path.isfile(path):
            with open(path, "rb") as f:
                old = f.read()
        if old and not old.endswith(b"\n"):
            old += b"\n"
        new = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")
        _write_atomic(path, old + new)
    return len(rows)
