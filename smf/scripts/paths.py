"""paths.py - where a batch of scripts lives, and the names that are allowed to become folders.

A batch name and a script's slug both end up as names on disk, on Windows as well as Mac and
Linux. A name typed by a person (or copied from a file that someone edited) is therefore checked
before it is ever joined to a path: it may not climb out of the brand's folder, may not be a name
Windows reserves, and may not contain a character some computer would refuse.

Writes of anything that counts as state go through `write_text`, which is atomic: the old file
stays whole until the new one is complete.
"""
from __future__ import annotations

import os
import re
import tempfile
import unicodedata

from smf.scripts import ScriptsError
from smf.brands import replace_patiently

SCRIPTS_DIR = ("Studio", "scripts")
MANIFEST_NAME = "manifest.json"
INDEX_NAME = "INDEX.md"
PITCHES_NAME = "pitches.md"
AUDIT_NAME = "audit.md"
TELEPROMPTER_SUFFIX = ".teleprompter.txt"

_BATCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,60}$")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)}


def check_batch_name(name):
    """Return the name if it is safe to use as a folder. Otherwise explain, in plain words."""
    ok = (isinstance(name, str) and _BATCH_NAME.match(name) and ".." not in name
          and not name.endswith((".", " ")) and name.split(".")[0].lower() not in _WINDOWS_RESERVED)
    if not ok:
        raise ScriptsError("A batch name is short and simple, like 'october-week-1': letters, numbers, spaces, "
                           "dots and dashes, starting with a letter or a number. '%s' cannot be used."
                           % (name if isinstance(name, str) else ""))
    return name


def slugify(text, fallback="script"):
    """A few plain words, safe as part of a file name on any computer."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return s[:40].strip("-") or fallback


def scripts_home(brand):
    return brand.path(*SCRIPTS_DIR)


def batch_dir(brand, batch):
    return os.path.join(scripts_home(brand), check_batch_name(batch))


def manifest_path(brand, batch):
    return os.path.join(batch_dir(brand, batch), MANIFEST_NAME)


def list_batches(brand):
    """Every batch this brand has, in name order. A folder without a manifest is not a batch."""
    home = scripts_home(brand)
    if not os.path.isdir(home):
        return []
    return sorted(n for n in os.listdir(home)
                  if not n.startswith(".") and os.path.isfile(os.path.join(home, n, MANIFEST_NAME)))


def file_in_batch(brand, batch, name):
    """A file that belongs to a batch, named in the manifest. The manifest can be edited by hand,
    so the name is treated as untrusted: it must be a plain file name inside the batch folder."""
    folder = batch_dir(brand, batch)
    if (not isinstance(name, str) or not name.strip() or name != os.path.basename(name)
            or name in (".", "..") or "/" in name or "\\" in name or ":" in name):
        raise ScriptsError("The batch '%s' names a file that is not inside its own folder ('%s'). "
                           "Nothing was read or written. Ask Claude to repair the batch record." % (batch, name))
    full = os.path.join(folder, name)
    home = os.path.realpath(folder)
    if os.path.dirname(os.path.realpath(full)) != home:
        raise ScriptsError("The batch '%s' names a file that leads outside its own folder ('%s'). "
                           "Nothing was read or written." % (batch, name))
    return full


def write_text(path, text):
    """Atomic write of a text file, always UTF-8, always ending in a newline."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        replace_patiently(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def read_text(path, what):
    """Read a file a person or a writer made. `what` names it in plain words for the error."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        raise ScriptsError("%s could not be found or opened." % what)
