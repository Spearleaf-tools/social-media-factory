"""journal.py - the owner's thinking journal: their own words, saved word for word and dated.

An owner thinks out loud in the chat. When they say "save this", their words go here exactly as
they said them: nothing tidied, nothing summarised. Planning reads the journal as a source for
topics (`source_ref` "journal:<id>") and the writer may use it for their voice.

Three rules hold everywhere:

  * THEIR WORDS ONLY count as theirs. An entry is either the owner's words or a note from Claude
    (a question it asked, a suggestion it made). Claude's notes are context for planning, never
    the owner's voice and never something to quote as theirs.
  * PRIVATE stays private. A private entry is kept for the owner and is left out of planning, the
    writer's brief and the voice. A draft that repeats one is stopped by the draft check.
  * The file stays readable. It is Brand/journal.md, a page the owner can open and read. Each
    entry starts with one line the tools write:

        ### entry 2026-10-23-1 · owner's words
        ### entry 2026-10-23-2 · owner's words · PRIVATE
        ### entry 2026-10-23-3 · note from Claude

    An answer to a question Claude asked starts with "> Claude asked: <the question>", so the
    question is never mistaken for their words. Anything written by hand outside entries (an
    older, hand-made journal) is kept as "older notes"; a line or a section heading marked
    PRIVATE in it is left out the same way.
"""
from __future__ import annotations

import os
import re
from datetime import date

from smf.studio.files import StudioError, as_brand, read_text
from smf.brands import replace_patiently

JOURNAL_FILE = ("Brand", "journal.md")
KINDS = {"owner": "owner's words", "claude": "note from Claude"}
HEADER = ("# Thinking journal",
          "Your own thinking, saved word for word and dated. Rough is fine; nothing here is tidied.",
          "Planning reads this page for topics and for how you sound. Entries marked PRIVATE stay out of posts.",
          "To add to it, say \"save this\" in the chat.")
ASKED = "> Claude asked: "
PRIVATE_WORD = re.compile(r"\bPRIVATE\b")
RUN_WORDS = 6                    # this many words in a row from a private entry, in a draft, is a leak

_ENTRY = re.compile(r"^### entry (\d{4}-\d{2}-\d{2})-(\d+) · (owner's words|note from Claude)( · PRIVATE)?\s*$")
_DAY = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
_HEADING = re.compile(r"^(#{1,6})\s")
_LOOKS_LIKE_ENTRY = re.compile(r"^#{2,3} (entry )?\d{4}-\d{2}-\d{2}")


class JournalError(StudioError):
    """A journal entry that cannot be saved or changed as asked."""


def journal_path(brand):
    return as_brand(brand).path(*JOURNAL_FILE)


# ----------------------------------------------------------------------------- reading
def _parse(text):
    entries, older, private_older = [], [], []
    current, private_level = None, 0
    for line in text.splitlines():
        m = _ENTRY.match(line.strip())
        if m:
            current = {"id": "%s-%s" % (m.group(1), m.group(2)), "date": m.group(1), "n": int(m.group(2)),
                       "kind": "owner" if m.group(3) == "owner's words" else "claude",
                       "private": bool(m.group(4)), "asked": "", "lines": []}
            entries.append(current)
            continue
        if _DAY.match(line.strip()):
            current, private_level = None, 0
            continue
        if current is not None:
            if not current["lines"] and not current["asked"] and line.startswith(ASKED):
                current["asked"] = line[len(ASKED):].strip()
            else:
                current["lines"].append(line)
            continue
        s = line.strip()                                   # older, hand-written notes
        heading = _HEADING.match(s)
        if heading:
            level = len(heading.group(1))
            if private_level and level <= private_level:
                private_level = 0
            if PRIVATE_WORD.search(s):
                private_level = level
        if not s or s == "---" or s in HEADER:
            continue
        if private_level or PRIVATE_WORD.search(s):
            if not heading:                                # a heading's few words are not a secret to look for
                private_older.append(s)
            continue
        older.append(s)
    for e in entries:
        lines = e.pop("lines")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        e["text"] = "\n".join(lines)
    return {"entries": entries, "older": older, "private_older": private_older}


def load(brand):
    """{"entries": [...], "older": [lines], "private_older": [lines]}. A brand with no journal yet has none.
    `private_older` is for the leak check only; nothing that plans or writes is given it."""
    path = journal_path(brand)
    if not os.path.isfile(path):
        return {"entries": [], "older": [], "private_older": []}
    text, _cut = read_text(path)
    return _parse(text)


def get(brand, entry_id):
    for e in load(brand)["entries"]:
        if e["id"] == str(entry_id).strip():
            return e
    return None


def public_entries(brand):
    return [e for e in load(brand)["entries"] if not e["private"]]


def owner_words(brand):
    """The owner's own public words, for their voice. Claude's notes and private entries are not in it."""
    return "\n\n".join(e["text"] for e in public_entries(brand) if e["kind"] == "owner")


def is_journal(brand, path):
    return os.path.realpath(path) == os.path.realpath(journal_path(brand))


# ----------------------------------------------------------------------------- writing
def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".saving"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    replace_patiently(tmp, path)


def add(brand, text, kind="owner", private=False, asked="", when=None):
    """Save one entry, word for word. `kind` is "owner" for their words, "claude" for a note from
    Claude. Returns the entry. Nothing is changed in the words except blank lines at either end."""
    brand = as_brand(brand)
    if kind not in KINDS:
        raise JournalError("A journal entry is either the owner's words (owner) or a note from Claude (claude).")
    body = str(text or "").strip("\r\n")
    if not body.strip():
        raise JournalError("There is nothing to save: the entry is empty.")
    if any(_LOOKS_LIKE_ENTRY.match(line.strip()) for line in body.splitlines()):
        raise JournalError("One line of this looks like a journal date heading, which would split the entry in two. "
                           "Save it in two parts, or change that line first (only if the owner says so).")
    asked = " ".join(str(asked or "").split())
    day = (when or date.today()).strftime("%Y-%m-%d")

    path = journal_path(brand)
    existing = read_text(path)[0] if os.path.isfile(path) else "%s\n\n%s\n" % (HEADER[0], "\n".join(HEADER[1:]))
    parsed = _parse(existing)
    n = 1 + max([e["n"] for e in parsed["entries"] if e["date"] == day] or [0])
    entry_id = "%s-%d" % (day, n)
    days = [m.group(1) for m in (_DAY.match(line.strip()) for line in existing.splitlines()) if m]
    heading = "### entry %s · %s%s" % (entry_id, KINDS[kind], " · PRIVATE" if private else "")
    block = "" if days and days[-1] == day else "\n## %s\n" % day
    block += "\n%s\n%s%s\n" % (heading, (ASKED + asked + "\n") if asked else "", body)
    _write(path, existing.rstrip("\n") + "\n" + block)
    return get(brand, entry_id)


def set_private(brand, entry_id, private=True):
    """Mark one entry private, or public again. Only its heading line changes; the words do not."""
    brand = as_brand(brand)
    path = journal_path(brand)
    entry = get(brand, entry_id) if os.path.isfile(path) else None
    if entry is None:
        known = [e["id"] for e in load(brand)["entries"]]
        raise JournalError("%s's journal has no entry '%s'. It has: %s."
                           % (brand.name, entry_id, ", ".join(known) or "none yet"))
    text, _cut = read_text(path)
    out = []
    for line in text.split("\n"):
        m = _ENTRY.match(line.strip())
        if m and "%s-%s" % (m.group(1), m.group(2)) == entry["id"]:
            line = "### entry %s · %s%s" % (entry["id"], KINDS[entry["kind"]], " · PRIVATE" if private else "")
        out.append(line)
    _write(path, "\n".join(out))
    return get(brand, entry["id"])


# ----------------------------------------------------------------------------- the leak check
def _words(text):
    return re.findall(r"[a-z0-9']+", str(text or "").lower().replace("’", "'"))


def private_overlap(brand, text):
    """The private entries (by id, or "an older private note") whose words appear in `text`:
    RUN_WORDS words in a row, or the whole of anything shorter."""
    said = " %s " % " ".join(_words(text))
    book = load(brand)
    private = [(e["id"], e["text"]) for e in book["entries"] if e["private"]]
    private += [("an older private note", line) for line in book["private_older"]]
    hits = []
    for label, words in private:
        words = _words(words)
        if not words or label in hits:
            continue
        runs = [words[i:i + RUN_WORDS] for i in range(max(1, len(words) - RUN_WORDS + 1))]
        if any(" %s " % " ".join(r) in said for r in runs):
            hits.append(label)
    return hits
