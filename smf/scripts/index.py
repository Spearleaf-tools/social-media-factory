"""index.py - the page a person films from.

A person coming back to a batch after a fortnight should not have to work out what they are
looking at. INDEX.md answers it on one page: which scripts can be filmed today, which file goes on
the teleprompter, and what needs to be within reach. It is rebuilt from the batch record
(manifest.json) every time a script moves, so the record stays the truth and this stays readable.

`survey` is the shared look at a batch: for every script, where it has got to, whether its file
changed since it last passed the checks, and whether its teleprompter still matches it.
"""
from __future__ import annotations

import os
import time

from smf.scripts import brief as B
from smf.scripts import manifest as M
from smf.scripts import paths as P
from smf.scripts import teleprompter as T
from smf.studio.files import as_brand

_STATUS_WORDS = {
    "pitched": "waiting for a yes", "approved": "approved, not written yet", "draft": "written, needs fixes",
    "validated": "ready to film", "recorded": "filmed", "cut": "cut",
}
_TELEPROMPTER_WORDS = {"current": "ready", "stale": "OUT OF DATE", "edited": "EDITED BY HAND", "missing": "not made yet",
                       "none": "not made yet"}


def survey(brand, batch):
    """One row per script: the record's entry plus what is true on disk right now.

    Scripts that changed since they last passed are moved back to draft here, so nothing that
    reads the survey can mistake an edited script for a checked one."""
    brand = as_brand(brand)
    data = M.load(brand, batch)
    texts, shas = {}, {}
    for entry in data["scripts"]:
        name = entry.get("script_file") or ""
        path = P.file_in_batch(brand, batch, name) if name else ""
        if path and os.path.isfile(path):
            texts[entry["id"]] = P.read_text(path, "The script file for script %s" % entry["id"])
            shas[entry["id"]] = B.text_sha(texts[entry["id"]])
    if any(e["status"] == "validated" and shas.get(e["id"]) not in (None, e.get("checked_sha")) for e in data["scripts"]):
        M.demote_changed(brand, batch, shas)
        data = M.load(brand, batch)

    rows = []
    for entry in data["scripts"]:
        text = texts.get(entry["id"])
        brief = B.parse(text) if text is not None else None
        written = brief is not None and not brief.unwritten
        if brief is not None and entry["status"] != "cut":
            tele_state, tele_note = T.state(brand, batch, entry, brief)
        else:
            tele_state, tele_note = "none", ""
        rows.append({"entry": entry, "brief": brief, "written": written,
                     "teleprompter": tele_state, "teleprompter_note": tele_note})
    return data, rows


def _cell(text):
    return " ".join(str(text or "").replace("|", "/").split())


def open_items(rows):
    """What still stands between this batch and a camera, in plain sentences."""
    out = []
    for r in rows:
        e, sid = r["entry"], r["entry"]["id"]
        label = "Script %s (%s)" % (sid, e.get("title", ""))
        if e["status"] == "pitched":
            out.append("%s is a pitch waiting for a yes or a no." % label)
        elif e["status"] == "approved":
            out.append("%s is approved and still has to be written." % label)
        elif e["status"] == "draft":
            n = e.get("open_findings") or 0
            out.append("%s needs %s before it is ready to film. Run the check to see them."
                       % (label, "%d fix(es)" % n if n else "checking again"))
        if e["status"] in ("validated", "recorded"):
            if r["teleprompter"] in ("stale", "edited", "missing"):
                out.append("%s: %s" % (label, r["teleprompter_note"]))
            if e.get("needs_sign_off"):
                out.append("%s needs the brand's disclaimer and a named person's sign-off before it is published." % label)
            if e.get("sourcing") == "unverified":
                out.append("%s states something that cannot be traced to the brand's files yet (unverified)." % label)
    return out


def build(brand, batch):
    """The text of INDEX.md for a batch."""
    brand = as_brand(brand)
    data, rows = survey(brand, batch)
    live = [r for r in rows if r["entry"]["status"] != "cut"]
    ready = [r for r in live if r["entry"]["status"] == "validated" and r["teleprompter"] == "current"]
    filmed = [r for r in live if r["entry"]["status"] == "recorded"]

    out = ["# Script batch: %s" % data["batch"], "",
           "Brand: %s. Started %s. Made from %s%s." % (
               brand.name, data.get("created", ""),
               "a recording's cut list" if data.get("track") == "recording" else "the brand's topics",
               (" (%s)" % data["source"]) if data.get("source") else ""),
           "This page was rebuilt on %s. The batch record beside it is the source of truth." % time.strftime("%Y-%m-%d"),
           ""]
    if data.get("note"):
        out += [data["note"], ""]
    out += ["%d script(s): %d ready to film, %d filmed, %d still in progress."
            % (len(live), len(ready), len(filmed), len(live) - len(ready) - len(filmed)), ""]

    out += ["## The scripts", "",
            "| # | Title | Words on screen at the start | Who speaks | Job | Seconds | Where it is up to | Teleprompter |",
            "|---|---|---|---|---|---|---|---|"]
    for r in live:
        e, b = r["entry"], r["brief"]
        on_screen = (b.opening.on_screen if b and r["written"] else "") or e.get("hook", "")
        seconds = (b.length_seconds if b else None) or e.get("length", "")
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            e["id"], _cell(e.get("title")), _cell(on_screen), _cell(e.get("speaker")),
            B.JOB_NAMES.get(e.get("job"), e.get("job", "")), seconds, _STATUS_WORDS[e["status"]],
            _TELEPROMPTER_WORDS[r["teleprompter"]] if e["status"] in ("validated", "recorded") else ""))
    out.append("")

    out += ["## To have to hand when filming", ""]
    any_notes = False
    for r in live:
        notes = [n for n in (r["brief"].shoot_notes if r["brief"] else []) if "TODO" not in n]
        if notes:
            any_notes = True
            out.append("Script %s, %s:" % (r["entry"]["id"], r["entry"].get("title", "")))
            out += ["- %s" % n for n in notes]
            out.append("")
    if not any_notes:
        out += ["Nothing listed yet. Each script's own 'To shoot this' section fills this in.", ""]

    out += ["## Files for each script", "",
            "- The script (what is said, what is shown, where each fact comes from): the file ending in `.md`",
            "- The teleprompter (read this on camera, it holds only the spoken words): the file ending in `%s`"
            % P.TELEPROMPTER_SUFFIX, ""]
    for r in live:
        e = r["entry"]
        if e["status"] in ("validated", "recorded"):
            out.append("- Script %s: `%s` and `%s`" % (e["id"], e.get("script_file"), e.get("teleprompter_file")))
    out.append("")

    out += ["## Before you film", "",
            "- [ ] Say every teleprompter file aloud once before the camera is on. A line that feels wrong in your "
            "mouth is changed in the script, and the script is checked again.",
            "- [ ] Gather everything listed above.",
            "- [ ] Film only scripts marked ready to film, with a teleprompter marked ready.",
            "- [ ] When a script is filmed, tell Claude, so it is marked as filmed here.", ""]

    still = open_items(rows)
    out += ["## Still open", ""]
    out += ["- %s" % s for s in still] or ["Nothing. Every script in this batch is ready or filmed."]
    out.append("")

    cut = [r["entry"] for r in rows if r["entry"]["status"] == "cut"]
    if cut:
        out += ["## Cut from this batch", ""] + ["- %s %s" % (e["id"], e.get("title", "")) for e in cut] + [""]
    return "\n".join(out)


def write(brand, batch):
    brand = as_brand(brand)
    path = os.path.join(P.batch_dir(brand, batch), P.INDEX_NAME)
    P.write_text(path, build(brand, batch))
    return path


def pitch_sheet(brand, batch):
    """pitches.md: one row per pitch, for a person to say yes or no to."""
    brand = as_brand(brand)
    data = M.load(brand, batch)
    out = ["# Pitch sheet: %s" % data["batch"], "",
           "Brand: %s. One row per idea. Nothing is written until a row gets a yes." % brand.name, "",
           "| # | Subject | Words on screen at the start | The angle | Job | Who speaks | Where it comes from | Decision |",
           "|---|---|---|---|---|---|---|---|"]
    decision = {"pitched": "waiting", "cut": "no"}
    for e in data["scripts"]:
        source = e.get("source_ref", "") + ("" if e.get("source_is_checkable") else " (a note, not a file)")
        if e.get("body"):
            source = "body %s of %s" % (e["body"], e.get("source_ref", ""))
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            e["id"], _cell(e.get("title")), _cell(e.get("hook")), _cell(e.get("angle")),
            B.JOB_NAMES.get(e.get("job"), ""), _cell(e.get("speaker")), _cell(source),
            decision.get(e["status"], "yes")))
    out += ["", "Jobs: reach means new people see you. Leads means the right people take a next step. "
                "Trust means the people already watching believe you a little more.", ""]
    path = os.path.join(P.batch_dir(brand, batch), P.PITCHES_NAME)
    P.write_text(path, "\n".join(out))
    return path
