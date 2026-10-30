"""Long-form YouTube: from a topic to a packaged video, one folder per video, one brand at a time.

Everything a video needs sits together inside the brand that owns it:

    Client/<brand>/Output/youtube/<date>-<slug>/
        brief.json          the record: topic, where it comes from, title options, the chosen title,
                            thumbnail concepts, the opening, the structure, the ask, the description
        brief.md            the same thing as a page a person can read
        script.md           the person's own words, refined for speaking (written with Claude)
        teleprompter.txt    only what is said, in short lines
        thumbnails/         drawn thumbnails, plus how each one reads at small size
        deck/               slides as pictures, one PDF, and a sheet showing every slide at once

and the question engine keeps its work in the brand's strategy folder:

    Client/<brand>/Strategy/youtube-questions/
        questions.json      every keyword the brand supplied, grouped into videos and tiered
        review.html         the sheet a person opens to approve, park or split them
        slate.md            the readable summary

The modules:

    video       the per-video folder, its record, and the check that reads it in plain words
    titles      title patterns as data, the keep-the-keyword rule, and scoring signals you can see
    describe    the description and its chapters
    script      the long-form script file and its teleprompter cut
    thumbnail   thumbnails at 1280x720, and the small-size legibility check
    deck        a support deck at 1920x1080, with density limits
    questions   keyword exports -> groups of phrases, one per video, tiered and ruled on by a person

Three promises hold across all of them. The brand is always named: there is no default. Nothing
is invented: a number has to trace to the brand's own facts, and a photo has to be one the brand
supplied. Nothing here talks to a network: pictures are drawn offline, and research that costs
money lives in `smf.research`, behind its own confirmation step.

The method behind the tools is written down in `playbooks/youtube-packaging.md` and
`playbooks/slide-decks.md`.
"""
from __future__ import annotations

import os
import re
import tempfile
import unicodedata

from smf.studio.files import StudioError, as_brand
from smf.brands import replace_patiently

__all__ = ["YouTubeError", "as_brand", "slugify", "write_text", "read_text", "inside_folder"]

_WINDOWS_RESERVED = ({"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)}
                     | {"lpt%d" % i for i in range(1, 10)})


class YouTubeError(StudioError):
    """A problem with a video, a title, a thumbnail, a deck or the question slate, worded for the
    person using the Factory rather than for a programmer."""


def slugify(text, fallback="video", limit=48):
    """A few plain words that are safe as a folder name on any computer. Accents are flattened,
    and only a-z, 0-9 and dashes survive, so text a person typed can never shape a path."""
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:limit].strip("-")
    if not s or s in _WINDOWS_RESERVED:
        return fallback
    return s


def inside_folder(path, folder):
    """True when `path` really sits within `folder` once links and '..' are resolved."""
    child, parent = os.path.realpath(path), os.path.realpath(folder)
    try:
        return os.path.commonpath([child, parent]) == parent and child != parent
    except ValueError:                       # different drives on Windows
        return False


def write_text(path, text):
    """Atomic write of a text file: UTF-8, Unix line ends, a final newline. The old file stays
    whole until the new one is complete."""
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
    """Read a file a person made. `what` names it in plain words for the message."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        raise YouTubeError("%s could not be found or opened." % what)
