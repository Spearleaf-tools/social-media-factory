"""scripts_cli.py - `factory.py scripts <step> --brand <id> ...`

    new-batch     start an empty batch of scripts for a brand
    pitch         record pitches (one per topic, or one per body of a recording's cut list)
    approve       a person's yes (or no) to pitches; writes a starter file for each yes
    validate      check written scripts against the brand's rules; a pass also makes the teleprompter
    teleprompter  make, or check, the plain-words file read on camera
    index         rebuild the page a person films from
    status        where every script has got to; also marks scripts as filmed
    audit         what the published numbers say, and the one thing to test next

Every step needs --brand. There is no default brand and no "latest batch": a step that is not told
which brand and which batch it is for stops and says so. Nothing here posts, schedules or uploads.
"""
from __future__ import annotations

import argparse
import json
import os

from smf import brands
from smf.scripts import audit as A
from smf.scripts import brief as B
from smf.scripts import index as I
from smf.scripts import manifest as M
from smf.scripts import paths as P
from smf.scripts import teleprompter as T
from smf.scripts import validate as V
from smf.scripts import ScriptsError
from smf.studio import cta as cta_lib
from smf.studio import topics
from smf.studio.files import StudioError, inside

SHORT_VIDEO_PLATFORMS = ("instagram", "tiktok", "youtube", "facebook")


# ----------------------------------------------------------------------------- helpers
def _read_json_input(path, what):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        raise ScriptsError("%s could not be found or opened." % what)
    except ValueError as e:
        raise ScriptsError("%s could not be read as JSON (%s). Nothing was saved." % (what, e))


def _platform_for(brand, speaker):
    where = brand.platforms_for(speaker)
    return next((p for p in where if p in SHORT_VIDEO_PLATFORMS), where[0])


def choose_cta(brand, job, speaker, used):
    """The call to action for one script, chosen by its job from the brand's own library, in the
    words this package uses for endings. `used` is the running tally for the batch, so offers and
    asks rotate instead of one being repeated in every script."""
    chosen = cta_lib.select_cta(brand, job, _platform_for(brand, speaker), used_counts=used)
    out = {"instruction": chosen.get("instruction") or "", "text": chosen.get("text") or "",
           "note": chosen.get("note") or "", "offer": "", "keyword": chosen.get("keyword") or ""}
    if chosen["kind"] in ("offer", "keyword"):
        out["kind"] = chosen["kind"]
        if chosen["kind"] == "offer":
            entry = next((c for c in cta_lib.load_library(brand)["ctas"] if c.get("id") == chosen["cta_id"]), {})
            out["offer"] = str(entry.get("offer_id") or "")
    elif chosen["kind"] == "reach":
        out["kind"] = chosen["cta_id"]                    # save, share or follow
    elif chosen.get("cta_id") == "none":
        out["kind"] = "none"
    else:
        out["kind"] = "question"                          # a soft close, including a leads script with no offer ready
    return out


def _details_from(brief):
    return {"format": (brief.header.get("format") or "").strip(), "hook_pattern": (brief.header.get("hook pattern") or "").strip(),
            "cta_kind": brief.cta.kind, "length": brief.length_seconds, "pillar": (brief.header.get("pillar") or "").strip()}


# ----------------------------------------------------------------------------- the steps
def do_new_batch(brand, a):
    track = a.track
    source = (a.source or "").strip()
    if track == "recording":
        path = inside(brand, source)
        if not path or not os.path.isfile(path):
            raise ScriptsError("A batch made from a recording needs the cut list the clip tools produced, as a file "
                               "inside %s's folder (--source). '%s' is not one." % (brand.name, source))
    M.create_batch(brand, a.name, track=track, source=source, note=a.note or "")
    I.write(brand, a.name)
    print("Started the batch '%s' for %s. It is empty: the next step is a pitch sheet." % (a.name, brand.name))
    return 0


def do_pitch(brand, a):
    data = M.load(brand, a.batch)
    raw = _read_json_input(a.from_file, "The pitches file")
    pitches = raw.get("pitches") if isinstance(raw, dict) else raw
    if not isinstance(pitches, list) or not pitches:
        raise ScriptsError("The pitches file should hold a list of pitches. Nothing was saved.")
    approved = {}
    if a.run:
        approved = {t["topic_id"]: t for t in topics.approved_topics(brand, a.run)}
    prepared = []
    for p in pitches:
        if not isinstance(p, dict):
            raise ScriptsError("Every pitch is a group of fields (title, job, speaker and so on). Nothing was saved.")
        p = dict(p)
        if a.run:
            topic = approved.get(str(p.get("topic_id") or ""))
            if topic is None:
                raise ScriptsError("The pitch '%s' is for the topic '%s', which is not an approved topic in the run "
                                   "'%s'. Only approved topics are written. Nothing was saved."
                                   % (p.get("title", ""), p.get("topic_id", ""), a.run))
            p.setdefault("title", topic.get("title", ""))
            p.setdefault("pillar", topic.get("pillar", ""))
            p.setdefault("source_ref", topic.get("source_ref", ""))
        if data.get("track") == "recording":
            p.setdefault("source_ref", data.get("source", ""))
        prepared.append(p)
    added, skipped = M.add_pitches(brand, a.batch, prepared, allow_repeat=a.allow_repeat)
    I.pitch_sheet(brand, a.batch)
    I.write(brand, a.batch)
    print("Recorded %d pitch(es) for %s, batch '%s'. Nothing is written until a person says yes to them."
          % (len(added), brand.name, a.batch))
    for e in added:
        print("  %s  %s  [%s]" % (e["id"], e["title"], B.JOB_NAMES[e["job"]]))
    for title, why in skipped:
        print("  left out: '%s' (%s)" % (title, why))
    notes = [e for e in added if not e["source_is_checkable"]]
    if notes:
        print("  %d pitch(es) give a note rather than a file or a recorded fact as their source. Any fact in those "
              "scripts will be labelled unverified until it is recorded." % len(notes))
    return 0


def do_approve(brand, a):
    data = M.load(brand, a.batch)
    yes = [s["id"] for s in data["scripts"] if s["status"] == "pitched"] if a.all else [M.normalise_id(s) for s in a.scripts or []]
    no = [M.normalise_id(s) for s in a.cut or []]
    if not yes and not no:
        raise ScriptsError("Say which pitches were approved (--scripts 01 02, or --all) or cut (--cut 03).")
    if no:
        M.set_status(brand, a.batch, no, "cut")
    approved = M.set_status(brand, a.batch, yes, "approved") if yes else []
    used, notes = {}, []
    for e in approved:
        path = P.file_in_batch(brand, a.batch, e["script_file"])
        cta = choose_cta(brand, e["job"], e["speaker"], used)
        if cta["note"]:
            notes.append(cta["note"])
        if not os.path.exists(path):
            P.write_text(path, B.starter(e["title"], brand.id, a.batch, e["id"], e["speaker"], e["job"],
                                         pillar=e.get("pillar", ""), comes_from=e.get("source_ref", ""),
                                         hook=e.get("hook", ""), angle=e.get("angle", ""), length=e.get("length") or 45,
                                         cta=cta))
    I.pitch_sheet(brand, a.batch)
    I.write(brand, a.batch)
    print("Approved %d, cut %d. Each approved script now has a starter file with its header and its call to "
          "action already chosen for its job." % (len(approved), len(no)))
    for e in approved:
        print("  %s  %s" % (e["id"], e["title"]))
    for n in sorted(set(notes)):
        print("  note: %s" % n)
    return 0


def _targets(brand, batch, script):
    data = M.load(brand, batch)
    if script:
        return data, [M.find(data, script)]
    return data, [e for e in data["scripts"] if e["status"] not in ("pitched", "cut")]


def _read_brief(brand, batch, entry):
    path = P.file_in_batch(brand, batch, entry["script_file"])
    if not os.path.isfile(path):
        return None, None
    text = P.read_text(path, "The script file for script %s" % entry["id"])
    return text, B.parse(text)


def do_validate(brand, a):
    _data, entries = _targets(brand, a.batch, a.script)
    if not entries:
        print("There is nothing to check yet in '%s': no pitch has been approved." % a.batch)
        return 0
    results, failed = [], 0
    for entry in entries:
        if entry["status"] in ("pitched", "cut"):
            raise M.ManifestError("Script %s is %s. A person has to approve the pitch before it is written or "
                                  "checked." % (entry["id"], "only a pitch" if entry["status"] == "pitched" else "cut"))
        text, brief = _read_brief(brand, a.batch, entry)
        if brief is None or brief.unwritten:
            print("Script %s (%s) has not been written yet. Its starter file is waiting to be filled in."
                  % (entry["id"], entry["title"]))
            failed += 1
            continue
        report = V.check_brief(brief, brand, batch=a.batch, script_id=entry["id"])
        M.record_check(brand, a.batch, entry["id"], report, B.text_sha(text))
        if report["ok"]:
            M.record_details(brand, a.batch, entry["id"], _details_from(brief))
            M.record_teleprompter(brand, a.batch, entry["id"], T.write_for(brand, a.batch, entry, brief))
        else:
            failed += 1
        results.append({"id": entry["id"], "title": entry["title"], "ok": report["ok"], "sourcing": report["sourcing"],
                        "errors": report["errors"], "warnings": report["warnings"],
                        "needs_sign_off": report["needs_sign_off"], "spoken_words": report["spoken_words"]})
        if not a.json:
            print(V.explain(report, "%s %s" % (entry["id"], entry["title"])))
    I.write(brand, a.batch)
    if a.json:
        print(json.dumps({"brand": brand.id, "batch": a.batch, "scripts": results}, indent=2, ensure_ascii=False))
    else:
        passed = len([r for r in results if r["ok"]])
        print("%d of %d script(s) pass. Each one that passes has a fresh teleprompter file beside it."
              % (passed, len(entries)))
    return 1 if failed else 0


def do_teleprompter(brand, a):
    _data, entries = _targets(brand, a.batch, a.script)
    trouble = 0
    for entry in entries:
        _text, brief = _read_brief(brand, a.batch, entry)
        if brief is None or not brief.spoken():
            print("Script %s (%s) has no spoken lines yet, so there is nothing to put on a teleprompter."
                  % (entry["id"], entry["title"]))
            trouble += 1
            continue
        if a.check:
            state, note = T.state(brand, a.batch, entry, brief)
            print("Script %s: %s" % (entry["id"], note))
            trouble += 0 if state == "current" else 1
            continue
        stamp = T.write_for(brand, a.batch, entry, brief)
        M.record_teleprompter(brand, a.batch, entry["id"], stamp)
        extra = "" if entry["status"] in ("validated", "recorded") else " (this script has not passed its checks yet)"
        print("Script %s: teleprompter made, %d lines%s." % (entry["id"], stamp["lines"], extra))
    if not a.check:
        I.write(brand, a.batch)
    return 1 if trouble else 0


def do_index(brand, a):
    I.write(brand, a.batch)
    _data, rows = I.survey(brand, a.batch)
    still = I.open_items(rows)
    print("The index for '%s' is rebuilt. It is the INDEX file inside the batch's folder, under Studio, scripts."
          % a.batch)
    for s in still:
        print("  still open: %s" % s)
    if not still:
        print("  Nothing is open: every script is ready to film or filmed.")
    return 0


def do_status(brand, a):
    if a.recorded:
        if not a.batch:
            raise ScriptsError("Say which batch the filmed scripts belong to (--batch).")
        _data, rows = I.survey(brand, a.batch)                         # an edited script is a draft again first
        moved = M.set_status(brand, a.batch, [M.normalise_id(s) for s in a.recorded], "recorded")
        I.write(brand, a.batch)
        print("Marked as filmed: %s." % ", ".join(e["id"] for e in moved))
        return 0
    if not a.batch:
        names = P.list_batches(brand)
        summary = []
        for name in names:
            data = M.load(brand, name)
            counts = {s: len([e for e in data["scripts"] if e["status"] == s]) for s in M.STATUSES}
            summary.append({"batch": name, "created": data.get("created", ""), "counts": counts})
        if a.json:
            print(json.dumps({"brand": brand.id, "batches": summary}, indent=2, ensure_ascii=False))
        elif not summary:
            print("%s has no script batches yet." % brand.name)
        else:
            for s in summary:
                parts = ["%d %s" % (n, k) for k, n in s["counts"].items() if n]
                print("%s (started %s): %s" % (s["batch"], s["created"], ", ".join(parts) or "empty"))
        return 0
    data, rows = I.survey(brand, a.batch)
    if a.json:
        print(json.dumps({"brand": brand.id, "batch": a.batch, "track": data.get("track"), "source": data.get("source"),
                          "scripts": [{"id": r["entry"]["id"], "title": r["entry"].get("title"),
                                       "status": r["entry"]["status"], "job": r["entry"].get("job"),
                                       "speaker": r["entry"].get("speaker"), "sourcing": r["entry"].get("sourcing"),
                                       "script_file": r["entry"].get("script_file"), "written": r["written"],
                                       "teleprompter": r["teleprompter"],
                                       "needs_sign_off": r["entry"].get("needs_sign_off", False)} for r in rows],
                          "open": I.open_items(rows)}, indent=2, ensure_ascii=False))
        return 0
    print("%s, batch '%s':" % (brand.name, a.batch))
    for r in rows:
        e = r["entry"]
        print("  %s  %-10s %s" % (e["id"], e["status"], e.get("title", "")))
    for s in I.open_items(rows):
        print("  still open: %s" % s)
    return 0


def do_audit(brand, a):
    supplied, notes = ({}, [])
    if a.numbers:
        supplied, notes = A.read_numbers_file(a.numbers)
    result = A.run(brand, a.batch, supplied=supplied, measure=a.measure, job=a.job, times=a.times)
    result["notes"] = notes + result["notes"]
    A.write(brand, a.batch, result)
    if a.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0
    print(result["recommendation"])
    if result["test"]:
        print("The one thing to test next: %s" % result["test"]["change"])
        print("Hold still: %s." % ", ".join(result["test"]["hold_still"]))
    for n in result["notes"]:
        print("  note: %s" % n)
    print("The full audit is the audit file inside the batch's folder.")
    return 0


# ----------------------------------------------------------------------------- the verb
def cli_scripts(args):
    ap = argparse.ArgumentParser(prog="factory.py scripts", description="Short-form video scripts for one brand.")
    sub = ap.add_subparsers(dest="step", required=True)

    def step(name, about, batch=True):
        p = sub.add_parser(name, help=about)
        p.add_argument("--brand", required=True, help="the brand's id. There is no default brand")
        if batch:
            p.add_argument("--batch", required=True, help="the batch's name")
        return p

    p = step("new-batch", "start an empty batch", batch=False)
    p.add_argument("--name", required=True)
    p.add_argument("--track", choices=M.TRACKS, default="topics")
    p.add_argument("--source", default="", help="topics: where they came from. recording: the cut list file, inside the brand's folder")
    p.add_argument("--note", default="")

    p = step("pitch", "record pitches from a JSON file")
    p.add_argument("--from", dest="from_file", required=True)
    p.add_argument("--run", default="", help="only pitch topics approved in this planning run")
    p.add_argument("--allow-repeat", action="store_true", help="allow a subject an earlier batch already covered")

    p = step("approve", "record a person's yes or no to pitches")
    p.add_argument("--scripts", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--cut", nargs="*")

    p = step("validate", "check scripts against the brand's rules")
    p.add_argument("--script", default="")
    p.add_argument("--json", action="store_true")

    p = step("teleprompter", "make or check teleprompter files")
    p.add_argument("--script", default="")
    p.add_argument("--check", action="store_true")

    step("index", "rebuild the page a person films from")

    p = step("status", "where every script has got to", batch=False)
    p.add_argument("--batch", default="")
    p.add_argument("--recorded", nargs="*", help="mark these scripts as filmed")
    p.add_argument("--json", action="store_true")

    p = step("audit", "what the published numbers say")
    p.add_argument("--numbers", default="", help="a JSON or CSV file of the person's own numbers")
    p.add_argument("--measure", default=None)
    p.add_argument("--job", default=None)
    p.add_argument("--times", type=float, default=A.DEFAULT_TIMES)
    p.add_argument("--json", action="store_true")

    a = ap.parse_args(args)
    run = {"new-batch": do_new_batch, "pitch": do_pitch, "approve": do_approve, "validate": do_validate,
           "teleprompter": do_teleprompter, "index": do_index, "status": do_status, "audit": do_audit}[a.step]
    try:
        return run(brands.load(a.brand), a)
    except (brands.BrandError, StudioError) as e:
        print(str(e))
        return 1
