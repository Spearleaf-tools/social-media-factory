"""files.py - small, careful file helpers shared by the writing tools.

Three jobs, all about reading a brand's folder safely:

  * JSON in and out. Reads tolerate the byte-order mark that Windows editors add; a damaged file
    becomes a sentence a person can act on. Writes are atomic (they go through the same helper the
    brand settings use), because topic decisions and libraries are state.
  * Paths that come from a settings file stay INSIDE the brand folder. A settings file can be
    edited by hand or copied from somewhere else, so "../../somewhere" is refused, not followed.
  * Telling a person's own words apart from the blank template. A new brand's files are full of
    headings and guidance that ship with the Factory. Those lines are not the brand's voice and
    are not planning material, so they are filtered out before anything is handed to a writer.
"""
from __future__ import annotations

import json
import os
import re

from smf import brands

TEXT_EXTENSIONS = (".md", ".txt", ".csv")
_TABLE_RULE = re.compile(r"^\|?[\s:|-]+\|?$")


class StudioError(Exception):
    """A problem in the writing tools, worded for the person, not the programmer."""


def as_brand(brand):
    """Every writing tool starts here. Accepts a Brand or a brand id and returns a Brand.
    Nothing, or anything else, is an error: there is no default brand to fall back on."""
    if isinstance(brand, brands.Brand):
        return brand
    if isinstance(brand, str) and brand.strip():
        return brands.load(brand.strip())
    raise brands.BrandError("no brand was named. Say which brand this is for. Brands here: %s"
                            % (", ".join(brands.list_brands()) or "none yet"))


# ----------------------------------------------------------------------------- JSON
def read_json(path, what):
    """Load a JSON file. `what` names the file in plain words for the error message."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        raise StudioError("%s could not be found or opened." % what)
    except ValueError as e:
        raise StudioError("%s is damaged and cannot be read (%s). Nothing was changed. "
                          "Ask Claude to repair it." % (what, e))


def write_json(path, data):
    """Atomic write: the old file stays whole until the new one is complete."""
    brands._write_json_atomic(path, data)


def read_text(path, limit=None):
    """Read a text file a person made. Odd bytes are replaced rather than crashing the run."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    if limit is not None and len(text) > limit:
        return text[:limit], True
    return text, False


# ----------------------------------------------------------------------------- safe paths
def inside(brand, rel):
    """Turn a path written in a brand's settings into a real path INSIDE that brand's folder.
    Returns None when the path is absolute, climbs out with '..', or escapes through a link."""
    if not isinstance(rel, str) or not rel.strip():
        return None
    rel = rel.strip()
    if os.path.isabs(rel) or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel):
        return None
    parts = [p for p in re.split(r"[\\/]+", rel) if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    full = os.path.join(brand.home, *parts)
    home = os.path.realpath(brand.home)
    real = os.path.realpath(full)
    if real != home and not real.startswith(home + os.sep):
        return None
    return full


def relative(brand, path):
    """A path as the person would say it: relative to the brand folder, with forward slashes."""
    return os.path.relpath(path, brand.home).replace(os.sep, "/")


def text_files(folder, extensions=TEXT_EXTENSIONS):
    """Every readable text file under a folder, in a stable order. Hidden files are skipped."""
    out = []
    if not os.path.isdir(folder):
        return out
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if name.startswith(".") or not name.lower().endswith(tuple(extensions)):
                continue
            out.append(os.path.join(root, name))
    return out


# ----------------------------------------------------------------------------- their words, not ours
def _template_lines(brand, rel):
    path = os.path.join(brands.TEMPLATE_DIR, *rel.split("/"))
    if not os.path.isfile(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().replace("{{BRAND_NAME}}", brand.name)
    return {line.strip() for line in text.splitlines() if line.strip()}


def own_lines(brand, rel, text):
    """The lines of a brand file that the person actually wrote: not headings, not table rules,
    and not the guidance that ships in the blank template. An untouched template returns []."""
    shipped = _template_lines(brand, rel)
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s == "---" or _TABLE_RULE.match(s) or s in shipped:
            continue
        out.append(s)
    return out
