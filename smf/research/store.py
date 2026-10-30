"""store.py - where research is kept, and the rule that it is kept per brand.

Every research run gets its own dated folder inside ONE brand:

    Client/<brand>/Inputs/Research/<job>/<date>-<slug>/
        run.json       what was asked, what it cost (estimated), what came back, any warnings
        summary.md     the readable version, laid out for Claude to study with the person
        *.json         the tidy data

Two promises are kept here rather than in each job, so no job can forget them:

  * Research is written only inside the named brand's folder. The folder name is built from
    text a person typed (a handle, a keyword), so it is reduced to safe characters AND the final
    location is checked to really sit inside that brand before anything is written.
  * Research is read back only by the brand that made it. A run's record names its brand; a
    record naming a different brand is refused, because a demand report built for one company
    from another company's listening is exactly the mix-up the Factory exists to prevent.

Earlier research is never overwritten: a second run on the same day gets "-2", "-3", and so on.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date

from smf import brands
from smf.brands import replace_patiently

RESEARCH = ("Inputs", "Research")
RECORD = "run.json"
_JOB_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")


class ResearchError(Exception):
    """A problem in the research tools, worded for the person, not the programmer."""


def as_brand(brand):
    """Every research job starts here. A Brand or a brand id comes back as a Brand; nothing, or
    anything else, is an error. There is no default brand to fall back on."""
    if isinstance(brand, brands.Brand):
        return brand
    if isinstance(brand, str) and brand.strip():
        return brands.load(brand.strip())
    raise brands.BrandError("no brand was named. Say which brand this research is for. Brands here: %s"
                            % (", ".join(brands.list_brands()) or "none yet"))


def slugify(text, limit=48):
    """Text a person typed -> a short folder-safe name. Only a-z, 0-9 and dashes survive, so
    slashes, dots, spaces, quotes and accents cannot shape the path."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:limit].strip("-") or "research"


def _inside(child, parent):
    """True when `child` really is within `parent` once links and '..' are resolved."""
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    try:
        return os.path.commonpath([child, parent]) == parent and child != parent
    except ValueError:                      # different drives on Windows
        return False


def research_root(brand, job=None):
    brand = as_brand(brand)
    if job is None:
        return brand.path(*RESEARCH)
    if not _JOB_NAME.match(job or ""):
        raise ResearchError("'%s' is not a research job name." % job)
    return brand.path(*(RESEARCH + (job,)))


def new_run_dir(brand, job, label, today=None):
    """Create and return a fresh folder for one run. Never reuses an existing folder."""
    brand = as_brand(brand)
    root = research_root(brand, job)
    day = (today or date.today()).isoformat()
    base = "%s-%s" % (day, slugify(label))
    for n in range(1, 500):
        name = base if n == 1 else "%s-%d" % (base, n)
        target = os.path.join(root, name)
        if not _inside(target, brand.home):
            raise ResearchError("That name would put the research outside %s's folder, so nothing was saved."
                                % brand.name)
        try:
            os.makedirs(target, exist_ok=False)
            return target
        except FileExistsError:
            continue
    raise ResearchError("There are already too many runs with that name today. Use a different label.")


def rel(brand, path):
    """A path as the person would find it: relative to their brand folder, forward slashes."""
    return os.path.relpath(path, as_brand(brand).home).replace(os.sep, "/")


# ----------------------------------------------------------------------------- writing
def _atomic(path, text):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        replace_patiently(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_json(brand, path, data):
    _guard(brand, path)
    _atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def write_text(brand, path, text):
    _guard(brand, path)
    _atomic(path, text if text.endswith("\n") else text + "\n")


def _guard(brand, path):
    brand = as_brand(brand)
    if not _inside(path, research_root(brand)):
        raise ResearchError("Research for %s can only be saved inside its own research folder. Nothing was written."
                            % brand.name)


def write_record(brand, run_dir, job, asked, result=None, extra=None):
    """The run's record. Written last, so a folder with a record is a finished run."""
    brand = as_brand(brand)
    rec = {"brand": brand.id, "job": job, "made_on": date.today().isoformat(), "asked": asked}
    if result is not None:
        rec["cost"] = {"estimated_usd": result.get("estimated_usd"), "ceiling_usd": result.get("ceiling_usd"),
                       "note": "An estimate, not a bill. The Apify console shows what was really charged."}
        rec["returned"] = result.get("count", 0)
        rec["partial"] = bool(result.get("partial"))
        rec["warnings"] = list(result.get("warnings") or [])
        rec["actor"] = result.get("actor")
        rec["their_fields_seen"] = list(result.get("their_fields_seen") or [])
    rec.update(extra or {})
    write_json(brand, os.path.join(run_dir, RECORD), rec)
    return rec


# ----------------------------------------------------------------------------- reading back
def read_run(brand, run_dir, job=None):
    """Open an earlier run FOR THIS BRAND. Refuses a folder outside the brand, a folder with no
    finished record, and a record that names a different brand."""
    brand = as_brand(brand)
    run_dir = run_dir if os.path.isabs(run_dir) else brand.path(*str(run_dir).replace("\\", "/").split("/"))
    if not _inside(run_dir, research_root(brand)):
        raise ResearchError("That folder is not part of %s's research, so it was not opened." % brand.name)
    path = os.path.join(run_dir, RECORD)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            rec = json.load(f)
    except OSError:
        raise ResearchError("That folder has no finished research run in it.")
    except ValueError:
        raise ResearchError("That run's record is damaged and cannot be read. Nothing was changed.")
    if rec.get("brand") != brand.id:
        raise ResearchError("That research was made for a different brand (%s), so it cannot be used for %s."
                            % (rec.get("brand") or "unknown", brand.name))
    if job and rec.get("job") != job:
        raise ResearchError("That folder holds a '%s' run, not a '%s' run." % (rec.get("job"), job))
    return rec


def read_json(brand, run_dir, name):
    brand = as_brand(brand)
    path = os.path.join(run_dir, name)
    if not _inside(path, research_root(brand)):
        raise ResearchError("That file is not part of %s's research, so it was not opened." % brand.name)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        raise ResearchError("The run is missing its '%s' file." % name)
    except ValueError:
        raise ResearchError("The run's '%s' file is damaged and cannot be read." % name)


def list_runs(brand, job):
    """Finished runs of one job for this brand, newest first."""
    brand = as_brand(brand)
    root = research_root(brand, job)
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        folder = os.path.join(root, name)
        if os.path.isfile(os.path.join(folder, RECORD)):
            out.append(folder)
    return out


# ----------------------------------------------------------------------------- markdown helpers
def md_cell(text, limit=160):
    """One table cell: single line, pipes escaped, trimmed. Never raises on odd input."""
    one = re.sub(r"\s+", " ", str(text if text is not None else "")).strip().replace("|", "\\|")
    if len(one) > limit:
        one = one[:limit - 1].rstrip() + "…"
    return one or "-"


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(md_cell(c) for c in row) + " |")
    return "\n".join(out)


def fmt_int(n):
    try:
        return "{:,}".format(int(round(float(n))))
    except (TypeError, ValueError):
        return "-"


RULES_OF_USE = (
    "> **How to use this.** This is research, not copy. Learn the STRUCTURE and the DEMAND: what "
    "people ask, how a strong video is built, which topics are alive. Never reuse someone else's "
    "words, lines, jokes, stories or numbers as your own. Anything quoted here is quoted so it can "
    "be understood, and it keeps its link. You are responsible for how you use material collected "
    "from other people's public posts, including the rules of the site it came from and the law "
    "where you live."
)
