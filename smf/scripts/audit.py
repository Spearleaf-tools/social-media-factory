"""audit.py - what a batch's published numbers say, and the ONE thing to test next.

The numbers are the person's own. They are either handed over (a small JSON or CSV file) or read
from the brand's local metrics archive under `_state/metrics/` when one exists. Nothing is ever
estimated or filled in: a script with no numbers is left out and named, and a batch with too few
numbers gets "not enough yet" instead of a pattern.

HOW A SHORT IS JUDGED HERE: FOUR MOMENTS
A viewer makes four decisions, in order, and each one leaves a number behind.

    the stop    do they stop, or swipe past?         still watching at three seconds (held_3s)
    the stay    do they stay for the point?          average share of the video watched (watched)
    the keep    was it worth keeping or passing on?  saves and sends per 1,000 views (kept_per_1000)
    the step    did they take the next step?         leads per 1,000 views (leads_per_1000)

Which number matters most depends on the job the scripts were written for: reach is judged on
views, trust on what people kept, leads on the next step taken.

THE MATHS, which is deliberately simple enough to explain to anyone
  * Typical means the MEDIAN of the batch, because one runaway video drags an average but barely
    moves a median.
  * A script stands out when it did at least `times` (default 3) times the typical number, or no
    more than the typical number divided by `times`.
  * Fewer than MIN_SCRIPTS scripts with numbers is not a pattern, so no outliers are named.

THE SINGLE-VARIABLE RULE
An audit ends in exactly one thing to change, never a list. If two things change at once and the
numbers move, nobody can say which one did it, and the next batch teaches nothing.
  * When one script clearly broke out, the test is to repeat its shape on new subjects: the
    subject is the one variable.
  * Otherwise the scripts are grouped by each thing that was recorded about them (opening
    pattern, format, speaker, length, pillar, ending). The grouping with the widest gap between
    its best and worst typical result becomes the test. Everything else is listed under "hold still".
  * When two things always changed together in this batch, the numbers cannot tell them apart.
    That is said plainly, and the one that acts earlier in the video is tested first.
"""
from __future__ import annotations

import csv
import json
import os
import re
import statistics
import time
from collections import OrderedDict, defaultdict

from smf.scripts import ScriptsError
from smf.scripts import brief as B
from smf.scripts import manifest as M
from smf.scripts import paths as P
from smf.studio.files import as_brand

MIN_SCRIPTS = 4
DEFAULT_TIMES = 3.0
MIN_GAP = 1.5                       # a gap smaller than this is noise in a small batch
METRICS_DIR = ("_state", "metrics")

COUNTS = ("views", "saves", "sends", "comments", "follows", "profile_visits", "leads")
PERCENTS = ("held_3s", "watched")
RAW = COUNTS + PERCENTS
PER_1000 = OrderedDict([("kept_per_1000", ("saves", "sends")), ("leads_per_1000", ("leads",)),
                        ("replies_per_1000", ("comments",)), ("follows_per_1000", ("follows",))])
MEASURE_WORDS = {
    "views": "views", "held_3s": "percent still watching at three seconds", "watched": "average percent watched",
    "saves": "saves", "sends": "sends", "comments": "comments", "follows": "follows",
    "profile_visits": "profile visits", "leads": "leads",
    "kept_per_1000": "saves and sends per 1,000 views", "leads_per_1000": "leads per 1,000 views",
    "replies_per_1000": "comments per 1,000 views", "follows_per_1000": "follows per 1,000 views",
}
# The words people and export files use for the same number.
_ALIASES = {
    "views": "views", "plays": "views", "view": "views", "video_views": "views",
    "held_3s": "held_3s", "held3s": "held_3s", "three_second_hold": "held_3s", "hold_3s": "held_3s",
    "viewed_vs_swiped": "held_3s", "stayed_3s": "held_3s",
    "watched": "watched", "average_watched": "watched", "avg_watched": "watched", "retention": "watched",
    "average_percent_watched": "watched", "average_view_percentage": "watched",
    "saves": "saves", "saved": "saves", "sends": "sends", "shares": "sends", "shared": "sends",
    "comments": "comments", "replies": "comments", "follows": "follows", "followers_gained": "follows",
    "profile_visits": "profile_visits", "profile_views": "profile_visits", "leads": "leads",
    "enquiries": "leads", "inquiries": "leads", "bookings": "leads", "sign_ups": "leads", "signups": "leads",
}
_ID_KEYS = ("script", "script_id", "id")

MOMENTS = (
    ("the stop", "Do they stop, or swipe past?", "held_3s"),
    ("the stay", "Do they stay for the point?", "watched"),
    ("the keep", "Was it worth keeping or passing on?", "kept_per_1000"),
    ("the step", "Did they take the next step?", "leads_per_1000"),
)
# What was recorded about each script, in the order it acts on a viewer. Ties go to the earliest.
VARIABLES = OrderedDict([
    ("hook_pattern", "the opening pattern"), ("format", "the format"), ("speaker", "who speaks"),
    ("length_band", "the length"), ("pillar", "the subject area"), ("cta_kind", "the ending"),
])
JOB_MEASURES = {"reach": ("views",), "trust": ("kept_per_1000", "watched", "views"),
                "lead_gen": ("leads_per_1000", "kept_per_1000", "views")}

# What makes a short work, as twelve questions in viewing order. The numbers say WHICH moment to
# look at; these say what to look FOR when reading the best and the weakest scripts side by side.
QUESTIONS = OrderedDict([
    ("the stop", ("Do the words on screen, the first picture and the first spoken line make the same promise?",
                  "Would the person this brand is for know it is for them before the first sentence ends?",
                  "Is something already happening in the first picture?")),
    ("the stay", ("Is there exactly one idea, and does every line serve it?",
                  "Does the viewer get something useful early, not only at the end?",
                  "Does the picture change with each line, and can each line be said in one breath?")),
    ("the keep", ("Could a viewer do something differently today because of it?",
                  "Is every fact one the brand can show, and is it shown rather than claimed?",
                  "Could only this brand have made it (their numbers, their bench, their cases)?")),
    ("the step", ("Does the ending fit the job the script was written for?",
                  "Is there one ask only, and does it follow from the subject?",
                  "If it asks for a next step, is that step really set up and easy to take?")),
])


class AuditError(ScriptsError):
    """The audit cannot run as asked."""


# ----------------------------------------------------------------------------- reading numbers
def _number(value):
    """1200, '1,200', '61%', '4.5' -> a number. Anything else -> None. Never guesses."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").rstrip("%").strip()
    if not re.match(r"^-?\d+(\.\d+)?$", text):
        return None
    return float(text)


def _clean_row(row):
    out = {}
    for key, value in row.items():
        name = _ALIASES.get(re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_"))
        number = _number(value)
        if name and number is not None and number >= 0:
            out[name] = number
    return out


def _rows_from(path):
    lower = path.lower()
    if lower.endswith(".csv"):
        with open(path, "r", newline="", encoding="utf-8-sig", errors="replace") as f:
            return [dict(r) for r in csv.DictReader(f)]
    with open(path, "r", encoding="utf-8-sig") as f:
        if lower.endswith(".jsonl"):
            return [json.loads(line) for line in f if line.strip()]
        data = json.load(f)
    if isinstance(data, dict):
        for key in ("rows", "posts", "scripts", "numbers"):
            if isinstance(data.get(key), list):
                return data[key]
        return [dict(v, script=k) for k, v in data.items() if isinstance(v, dict)]
    return data if isinstance(data, list) else []


def read_numbers_file(path):
    """Numbers a person handed over. Returns ({script_id: {measure: number}}, notes)."""
    try:
        rows = _rows_from(path)
    except OSError:
        raise AuditError("The numbers file could not be found or opened.")
    except (ValueError, csv.Error) as e:
        raise AuditError("The numbers file could not be read (%s). It should be a list of rows, each with the "
                         "script's number and its views, saves and so on." % type(e).__name__)
    out, notes = {}, []
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        sid = next((str(row[k]).strip() for k in _ID_KEYS if str(row.get(k) or "").strip()), "")
        if not sid:
            notes.append("Row %d of the numbers file does not say which script it is for, so it was skipped." % i)
            continue
        numbers = _clean_row(row)
        if numbers:
            out.setdefault(M.normalise_id(sid.split("/")[-1]), {}).update(numbers)
    return out, notes


def read_archive(brand, batch, data):
    """Numbers from the brand's local metrics archive, if there is one. A row belongs to a script
    when it names it ("script": "<batch>/<id>") or carries a link or post id recorded on that
    script. Later rows replace earlier ones for the same post, so the newest snapshot wins; counts
    are then added across posts and percentages averaged. An unreadable file is skipped and named."""
    folder = brand.path(*METRICS_DIR)
    if not os.path.isdir(folder):
        return {}, []
    by_link = {}
    for entry in data["scripts"]:
        for link in list(entry.get("published_urls") or []) + list(entry.get("published_ids") or []):
            by_link[str(link).strip()] = entry["id"]
    ids = {e["id"] for e in data["scripts"]}
    latest, notes = defaultdict(dict), []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if name.startswith(".") or not name.lower().endswith((".json", ".jsonl", ".csv")):
                continue
            try:
                rows = _rows_from(os.path.join(root, name))
            except (OSError, ValueError, csv.Error):
                notes.append("The metrics file '%s' could not be read, so it was skipped." % name)
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                named = str(row.get("script") or "").strip()
                sid = None
                if named.startswith(batch + "/") and M.normalise_id(named.split("/")[-1]) in ids:
                    sid = M.normalise_id(named.split("/")[-1])
                link = str(row.get("url") or row.get("post_id") or row.get("provider_post_id") or "").strip()
                if sid is None and link in by_link:
                    sid = by_link[link]
                numbers = _clean_row(row)
                if sid and numbers:
                    latest[sid][link or str(row.get("platform") or "post")] = numbers
    out = {}
    for sid, posts in latest.items():
        total = {}
        for key in COUNTS:
            got = [p[key] for p in posts.values() if key in p]
            if got:
                total[key] = sum(got)
        for key in PERCENTS:
            got = [p[key] for p in posts.values() if key in p]
            if got:
                total[key] = round(sum(got) / len(got), 2)
        out[sid] = total
    return out, notes


def with_rates(numbers):
    """The raw numbers plus the per-1,000-views rates that can honestly be worked out from them."""
    out = dict(numbers)
    views = numbers.get("views")
    if views and views > 0:
        for name, parts in PER_1000.items():
            if all(p in numbers for p in parts):
                out[name] = round(sum(numbers[p] for p in parts) / views * 1000.0, 2)
    return out


# ----------------------------------------------------------------------------- the maths
def typical(values):
    return statistics.median(values)


def outliers(values_by_id, times=DEFAULT_TIMES, minimum=MIN_SCRIPTS):
    """Which scripts stand out from the batch.

    Returns {"typical", "high": [(id, ratio)], "low": [(id, ratio)], "note"}. `ratio` is the
    script's number divided by the typical number."""
    if times <= 1:
        raise AuditError("'times' has to be more than 1: a script stands out when it did several times the typical.")
    n = len(values_by_id)
    if n < minimum:
        return {"typical": None, "high": [], "low": [],
                "note": "Only %d script(s) have this number. It takes at least %d to say what is typical, so "
                        "nothing is called an outlier yet." % (n, minimum)}
    mid = typical(list(values_by_id.values()))
    if mid <= 0:
        return {"typical": mid, "high": [], "low": [],
                "note": "Most of the batch has zero for this number, so there is no typical value to compare "
                        "against. Choose another number to judge by."}
    high = sorted(((sid, round(v / mid, 2)) for sid, v in values_by_id.items() if v >= times * mid),
                  key=lambda t: -t[1])
    low = sorted(((sid, round(v / mid, 2)) for sid, v in values_by_id.items() if v <= mid / times),
                 key=lambda t: t[1])
    return {"typical": mid, "high": high, "low": low, "note": ""}


def length_band(seconds):
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ""
    return "under 30 seconds" if seconds < 30 else ("30 to 45 seconds" if seconds <= 45 else "over 45 seconds")


def _variables_of(entry):
    return {"hook_pattern": (entry.get("hook_pattern") or "").strip().lower(),
            "format": (entry.get("format") or "").strip().lower(),
            "speaker": (entry.get("speaker") or "").strip(),
            "length_band": length_band(entry.get("length")),
            "pillar": (entry.get("pillar") or "").strip(),
            "cta_kind": (entry.get("cta_kind") or "").strip().lower()}


def _moves_with(rows, a, b):
    """True when two variables split these scripts into exactly the same groups, so this batch
    cannot tell their effects apart."""
    pairs = {(r["variables"].get(a), r["variables"].get(b)) for r in rows
             if r["variables"].get(a) and r["variables"].get(b)}
    return bool(pairs) and len({p[0] for p in pairs}) == len(pairs) == len({p[1] for p in pairs}) and len(pairs) > 1


def compare_groups(rows):
    """For each recorded variable, the gap between its best and worst typical result.
    Only values with at least two scripts count: one script is an anecdote."""
    found = []
    for position, name in enumerate(VARIABLES):
        groups = defaultdict(list)
        for r in rows:
            value = r["variables"].get(name)
            if value:
                groups[value].append(r["value"])
        usable = {k: v for k, v in groups.items() if len(v) >= 2}
        if len(usable) < 2:
            continue
        mids = {k: typical(v) for k, v in usable.items()}
        best = max(sorted(mids), key=lambda k: mids[k])
        worst = min(sorted(mids), key=lambda k: mids[k])
        if mids[best] <= 0:
            continue
        gap = float("inf") if mids[worst] <= 0 else mids[best] / mids[worst]
        found.append({"variable": name, "position": position, "best": best, "worst": worst,
                      "best_typical": mids[best], "worst_typical": mids[worst], "gap": gap,
                      "best_count": len(usable[best]), "worst_count": len(usable[worst])})
    return found


def propose_test(rows, measure, standouts):
    """EXACTLY ONE thing to test next, or None with the reason. Never a list."""
    words = MEASURE_WORDS[measure]
    everything = list(VARIABLES.values())
    if standouts["high"]:
        sid, ratio = standouts["high"][0]
        return {"variable": "subject", "kind": "repeat",
                "change": "Make two or three more scripts in exactly the shape of script %s, on new subjects." % sid,
                "because": "Script %s did %s times the typical %s for this batch." % (sid, _times(ratio), words),
                "hold_still": everything, "judge_by": measure, "moved_together_with": [], "also_noticed": [],
                "success_looks_like": "At least one of the new scripts also does well above typical. If none do, "
                                      "the first one was luck or its subject, not its shape."}, ""
    found = [c for c in compare_groups(rows) if c["gap"] >= MIN_GAP]
    if not found:
        return None, ("Nothing recorded about these scripts separates the better ones from the rest by a clear "
                      "margin. Either the batch is too alike to learn from, or too few scripts share a value. "
                      "Next batch, vary ONE thing on purpose (for example the opening pattern across half the "
                      "scripts) so there is something to compare.")
    found.sort(key=lambda c: (-c["gap"], c["position"]))
    pick = found[0]
    tied = [c for c in found[1:] if _moves_with(rows, pick["variable"], c["variable"])]
    if tied:
        earliest = min([pick] + tied, key=lambda c: c["position"])
        tied = [c for c in [pick] + tied if c is not earliest]
        pick = earliest
    label = VARIABLES[pick["variable"]]
    gap = "many" if pick["gap"] == float("inf") else _times(pick["gap"])
    test = {"variable": pick["variable"], "kind": "change",
            "change": "For the next batch, use '%s' for %s in every script." % (pick["best"], label),
            "because": "Scripts with '%s' had a typical %s of %s (%d scripts), against %s for '%s' (%d scripts). "
                       "That is about %s times." % (pick["best"], words, _fmt(pick["best_typical"]), pick["best_count"],
                                                    _fmt(pick["worst_typical"]), pick["worst"], pick["worst_count"], gap),
            "hold_still": [v for k, v in VARIABLES.items() if k != pick["variable"]],
            "judge_by": measure,
            "moved_together_with": [VARIABLES[c["variable"]] for c in tied],
            "also_noticed": ["%s ('%s' did better than '%s')" % (VARIABLES[c["variable"]], c["best"], c["worst"])
                             for c in found if c is not pick and c not in tied],
            "success_looks_like": "The typical %s of the next batch is clearly above this batch's. If it is not, "
                                  "the difference seen here was chance, and the next thing on the list gets its turn."
                                  % words}
    return test, ""


def _times(ratio):
    return ("%.1f" % ratio).rstrip("0").rstrip(".")


def _fmt(value):
    if value is None:
        return ""
    return ("%d" % value) if float(value).is_integer() else ("%.1f" % value)


# ----------------------------------------------------------------------------- the audit
def run(brand, batch, supplied=None, measure=None, job=None, times=DEFAULT_TIMES):
    """Audit one batch. `supplied` is {script_id: {measure: number}} from a person; the brand's
    metrics archive is read as well when it exists, and supplied numbers win.

    Returns a plain dict (see `report_text` for the page made from it)."""
    brand = as_brand(brand)
    data = M.load(brand, batch)
    notes = []
    archive, archive_notes = read_archive(brand, batch, data)
    notes += archive_notes
    if supplied:
        unknown = sorted(set(supplied) - {e["id"] for e in data["scripts"]})
        if unknown:
            raise AuditError("The numbers name script(s) this batch does not have: %s. Nothing was saved."
                             % ", ".join(unknown))
        M.record_numbers(brand, batch, supplied)
        data = M.load(brand, batch)

    scripts = []
    for entry in data["scripts"]:
        if entry["status"] == M.CUT:
            continue
        numbers = dict(archive.get(entry["id"], {}))
        numbers.update(entry.get("numbers") or {})
        scripts.append({"id": entry["id"], "title": entry.get("title", ""), "job": entry.get("job", ""),
                        "numbers": with_rates(numbers), "variables": _variables_of(entry)})
    have = [s for s in scripts if s["numbers"]]
    missing = [s for s in scripts if not s["numbers"]]

    wanted_job = B.normalise_job(job) if job else None
    if job and wanted_job is None:
        raise AuditError("A job is one of: reach, leads, trust.")
    by_job = defaultdict(list)
    for s in have:
        by_job[s["job"]].append(s)
    if wanted_job is None and by_job:
        wanted_job = max(sorted(by_job), key=lambda j: len(by_job[j]))
        if len(by_job) > 1:
            others = ", ".join("%d %s" % (len(v), B.JOB_NAMES.get(j, j)) for j, v in sorted(by_job.items()) if j != wanted_job)
            notes.append("This batch mixes jobs. Scripts written for different jobs are judged by different "
                         "numbers, so only the %d %s script(s) are compared here. Run the audit again for the "
                         "others (%s)." % (len(by_job[wanted_job]), B.JOB_NAMES.get(wanted_job, wanted_job), others))
    pool = by_job.get(wanted_job, [])

    if measure is not None and measure not in MEASURE_WORDS:
        raise AuditError("'%s' is not a number this audit knows. Choose one of: %s." % (measure, ", ".join(MEASURE_WORDS)))
    if measure is None:
        for candidate in JOB_MEASURES.get(wanted_job, ("views",)):
            if sum(1 for s in pool if candidate in s["numbers"]) >= MIN_SCRIPTS:
                measure = candidate
                break
        measure = measure or JOB_MEASURES.get(wanted_job, ("views",))[0]

    rows = [{"id": s["id"], "title": s["title"], "value": s["numbers"][measure], "variables": s["variables"],
             "numbers": s["numbers"]} for s in pool if measure in s["numbers"]]
    rows.sort(key=lambda r: (-r["value"], r["id"]))
    standouts = outliers({r["id"]: r["value"] for r in rows}, times=times)

    test, why_not = (None, standouts["note"])
    if standouts["typical"] is not None and standouts["typical"] > 0:
        test, why_not = propose_test(rows, measure, standouts)

    moments = []
    for name, question, m in MOMENTS:
        vals = {s["id"]: s["numbers"][m] for s in pool if m in s["numbers"]}
        moments.append({"moment": name, "question": question, "measure": m, "scripts": len(vals),
                        "typical": typical(list(vals.values())) if vals else None,
                        "best": max(sorted(vals), key=lambda k: vals[k]) if vals else "",
                        "weakest": min(sorted(vals), key=lambda k: vals[k]) if vals else ""})

    return {"brand": brand.id, "brand_name": brand.name, "batch": batch, "job": wanted_job, "measure": measure,
            "times": times, "ranking": rows, "typical": standouts["typical"], "high": standouts["high"],
            "low": standouts["low"], "test": test, "no_test_because": why_not, "moments": moments,
            "without_numbers": [(s["id"], s["title"]) for s in missing], "notes": notes,
            "recommendation": _recommend(rows, standouts, test, why_not, measure, missing)}


def _recommend(rows, standouts, test, why_not, measure, missing):
    if not rows:
        return ("There are no numbers for this batch yet. Once the videos have been out for about a week, give "
                "Claude each one's views, saves, sends and (if you have them) how many were still watching at "
                "three seconds and how much of the video people watched on average.")
    if standouts["typical"] is None:
        return ("Keep publishing. %d script(s) have numbers, and it takes %d before a pattern means anything. "
                "Change nothing on the strength of one or two videos." % (len(rows), MIN_SCRIPTS))
    if test is None:
        return "Keep going as you are. %s" % why_not
    if test["kind"] == "repeat":
        return ("You have a clear winner. %s %s Change only the subject, so that if the new ones also do well you "
                "know the shape is what works." % (test["because"], test["change"]))
    return ("Change one thing, and only one. %s %s Keep everything else the way it was, publish the batch, and "
            "compare the same number." % (test["because"], test["change"]))


def report_text(result, rows_to_read=3):
    """audit.md: the numbers, the one test, the recommendation, and the reading sheet."""
    words = MEASURE_WORDS[result["measure"]]
    out = ["# Script audit: %s" % result["batch"], "",
           "Brand: %s. Made on %s from the brand's own published numbers. Nothing here is estimated."
           % (result["brand_name"], time.strftime("%Y-%m-%d")), "",
           "Judged as %s scripts, by %s." % (B.JOB_NAMES.get(result["job"], result["job"] or "unsorted"), words), ""]
    out += ["- %s" % n for n in result["notes"]]
    if result["without_numbers"]:
        out.append("- No numbers yet, so left out: %s." % ", ".join("%s (%s)" % t for t in result["without_numbers"]))
    out.append("")

    out += ["## The ranking", "", "| Script | Title | %s | Against typical |" % (words[0].upper() + words[1:]), "|---|---|---|---|"]
    mid = result["typical"]
    for r in result["ranking"]:
        against = ("%s times" % _times(r["value"] / mid)) if mid else ""
        out.append("| %s | %s | %s | %s |" % (r["id"], " ".join(r["title"].replace("|", "/").split()), _fmt(r["value"]), against))
    out.append("")

    out += ["## What is typical, and what stands out", ""]
    if mid is None or mid <= 0:
        out += [result["no_test_because"], ""]
    else:
        out.append("Typical for this batch (the middle value): %s %s." % (_fmt(mid), words))
        out.append("Stands out means at least %s times typical, or no more than typical divided by %s."
                   % (_times(result["times"]), _times(result["times"])))
        out += ["- Well above: script %s, at %s times typical." % (sid, _times(ratio)) for sid, ratio in result["high"]]
        out += ["- Well below: script %s, at %s times typical." % (sid, _times(ratio)) for sid, ratio in result["low"]]
        if not result["high"] and not result["low"]:
            out.append("Nothing stands out. The batch performed evenly.")
        out.append("")

    out += ["## The four moments", "",
            "| Moment | The question | The number | Scripts with it | Typical | Best | Weakest |", "|---|---|---|---|---|---|---|"]
    for m in result["moments"]:
        out.append("| %s | %s | %s | %d | %s | %s | %s |" % (m["moment"], m["question"], MEASURE_WORDS[m["measure"]],
                                                             m["scripts"], _fmt(m["typical"]), m["best"], m["weakest"]))
    out.append("")

    out += ["## The one thing to test next", ""]
    test = result["test"]
    if test is None:
        out += ["No test is proposed from this batch. %s" % result["no_test_because"], ""]
    else:
        out += [test["change"], "", "Why: %s" % test["because"], "",
                "Hold still: %s." % ", ".join(test["hold_still"]),
                "Judge it by: %s." % MEASURE_WORDS[test["judge_by"]],
                "It worked if: %s" % test["success_looks_like"], ""]
        if test["moved_together_with"]:
            out += ["In this batch, %s always changed together with %s, so the numbers cannot tell them apart. "
                    "Testing the earlier one first, with the other held still, will." %
                    (VARIABLES.get(test["variable"], test["variable"]), " and ".join(test["moved_together_with"])), ""]
        if test["also_noticed"]:
            out += ["Also noticed, and deliberately left for a later batch: %s." % "; ".join(test["also_noticed"]), ""]

    out += ["## What to do", "", result["recommendation"], ""]

    ranking = result["ranking"]
    if len(ranking) >= 2:
        top = [r["id"] for r in ranking[:rows_to_read]]
        bottom = [r["id"] for r in ranking[-rows_to_read:] if r["id"] not in top]
        out += ["## Reading the scripts", "",
                "The numbers say where to look. Read the best scripts (%s) beside the weakest (%s) and answer each "
                "question with yes, partly or no, quoting the line that shows it. Look for what the best share "
                "and the weakest lack." % (", ".join(top), ", ".join(bottom) or "none"), ""]
        for moment, questions in QUESTIONS.items():
            out += ["### %s" % (moment[0].upper() + moment[1:]), "",
                    "| Question | %s |" % " | ".join(top + bottom), "|---|%s" % ("---|" * len(top + bottom))]
            out += ["| %s |%s" % (q, " |" * len(top + bottom)) for q in questions]
            out.append("")
    return "\n".join(out)


def write(brand, batch, result):
    brand = as_brand(brand)
    path = os.path.join(P.batch_dir(brand, batch), P.AUDIT_NAME)
    P.write_text(path, report_text(result))
    return path
