"""teleprompter.py - a script as plain words to read on camera.

The teleprompter file holds ONLY what is said. No labels, no headings, no visual directions, no
markings of any kind: whatever is in the file will be read aloud by someone looking into a lens.

Pacing, so it can be read at a glance from a few feet away:
  * one thought per line, never more than LINE_WORDS words;
  * a long sentence is broken where a speaker would breathe: at a comma first, then before a
    joining word, and only as a last resort in the middle;
  * a blank line between the lines of the script, which is where the picture changes.

There is one file per script, and it is made from the script, never edited by hand. Each time it
is made, a stamp is stored in the batch record: a fingerprint of the spoken words it was made from
and of the file itself. From the stamp alone the tools can say whether a teleprompter is current,
out of date (the spoken words changed), edited by hand, or missing.
"""
from __future__ import annotations

import os
import re
import time

from smf.scripts import brief as B
from smf.scripts import paths as P

LINE_WORDS = 10

_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BRACKETED = re.compile(r"\[[^\]]*\]")                  # [pause], [hold up the loaf]: directions, not speech
_TAG = re.compile(r"<[^>]+>")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`|~~)")
_LEADING_MARK = re.compile(r"^\s*(?:>+|#{1,6}|[-*+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")             # splits on the space only, so no character is ever dropped
_SOFT_BREAK = re.compile(r"(?<=[,;:])\s+")
_JOINERS = {"and", "but", "so", "because", "which", "when", "while", "then", "or", "if", "until", "before", "after"}


def strip_markings(text):
    """The words a person would say, with every mark a writer might have typed taken out."""
    s = _LINK.sub(r"\1", text or "")
    s = _BRACKETED.sub("", s)
    s = _TAG.sub("", s)
    s = _LEADING_MARK.sub("", s)
    s = _EMPHASIS.sub("", s)
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = s.strip().strip('"').strip()
    return re.sub(r"\s+", " ", s)


def _break_long(words):
    """Split a run of words that is still too long: before a joining word nearest the middle,
    otherwise in the middle."""
    if len(words) <= LINE_WORDS:
        return [words]
    middle = len(words) / 2.0
    joins = [i for i in range(2, len(words) - 1) if words[i].lower().strip(",.;:") in _JOINERS]
    cut = min(joins, key=lambda i: abs(i - middle)) if joins else int(round(middle))
    return _break_long(words[:cut]) + _break_long(words[cut:])


def pace(sentence):
    """One sentence as one or more short lines."""
    out = []
    for chunk in _SOFT_BREAK.split(sentence):
        words = chunk.split()
        if not words:
            continue
        if out and len(out[-1]) + len(words) <= LINE_WORDS:
            out[-1] = out[-1] + words                     # two short clauses read better on one line
        else:
            out.extend(_break_long(words))
    return [" ".join(w) for w in out]


def render(brief):
    """The teleprompter text for a script."""
    blocks = []
    for _where, spoken in brief.spoken():
        clean = strip_markings(spoken)
        lines = []
        for sentence in _SENTENCE_END.split(clean):
            if sentence.strip():
                lines += pace(sentence.strip())
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


# ----------------------------------------------------------------------------- one file per script, stamped
def write_for(brand, batch, entry, brief):
    """Write the teleprompter for one script and return its stamp for the batch record."""
    path = P.file_in_batch(brand, batch, entry["teleprompter_file"])
    text = render(brief)
    P.write_text(path, text)
    return {"file": entry["teleprompter_file"], "spoken_sha": B.spoken_sha(brief), "text_sha": B.text_sha(text),
            "made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "lines": len([ln for ln in text.splitlines() if ln.strip()])}


def state(brand, batch, entry, brief):
    """(state, plain explanation). state is one of: current, stale, edited, missing, none."""
    stamp = entry.get("teleprompter") or {}
    name = entry.get("teleprompter_file") or ""
    if not name:
        return "none", "No teleprompter file has been planned for this script."
    path = P.file_in_batch(brand, batch, name)
    if not os.path.isfile(path) or not stamp:
        return "missing", "There is no teleprompter file for this script yet."
    if stamp.get("spoken_sha") != B.spoken_sha(brief):
        return "stale", "The spoken words changed after the teleprompter file was made, so it is out of date."
    if stamp.get("text_sha") != B.text_sha(P.read_text(path, "The teleprompter file")):
        return "edited", ("The teleprompter file was changed by hand. The script is the source: change the script, "
                          "then make the teleprompter again.")
    return "current", "The teleprompter file matches the script."
