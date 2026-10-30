"""verify.py - before anything is delivered: open every finished version and check what is IN it.

A render that reports success has only said that a file was written. Whether the file holds the
right words, only the right people and the disclaimer it needs is a different question, and the
log of the render cannot answer it: the log describes the plan. So every check below looks at the
finished file, and says how much it looked at.

    plays        the whole file decodes, is 1080 x 1920 with sound, and is the length it should be
    words        the version is listened to with the small local speech model and compared with
                 the words the clip should hold. This is a DIFFERENT tool from the one that made
                 the transcript, on purpose: two tools that agree are evidence, one tool agreeing
                 with itself is not. It catches a version made from the wrong clip, a cut that
                 lost its first or last words, and talk about the take itself ("say that again")
    voices       by the transcript's speaker labels, no stretch that was really cut overlaps
                 someone who stays off camera. This one reads labels, not sound, so it proves the
                 assembly and cannot see a mislabelled voice. That is why `words` also listens for
                 anything the off-camera voice said nearby
    disclaimer   on a HOLD clip, frames are pulled from the file and the band is looked for in
                 their pixels, from the first second to the last

A CHECK THAT EXAMINED NOTHING HAS FAILED. No files found, a speech model that would not load, no
frames that could be read, a transcript that cannot say who spoke while the brand keeps someone
off camera: each of those is reported as a failure with its reason. None of them is ever a pass.

The result is written beside the versions, with each file's fingerprint, so delivery can tell
that the file it is about to copy is the file that was checked.
"""
from __future__ import annotations

import os
import re
import time

from smf.video import gate, overlays
from smf.video import validate_cuts as VC
from smf.video import variants as V
from smf.video.common import (Transcript, VideoError, as_brand, decodes_cleanly, fmt_ts, has_audio, lcs, locate,
                              probe_duration, probe_shape, read_json, stream_of, tokens_of, write_json_atomic)

REPORT_FILE = "verify-report.json"
WORDS_NEEDED = 0.55            # share of the expected words that must be heard, in order
EDGE_WORDS = 5                 # how many words are checked at each end
EDGE_NEEDED = 0.5
EDGE_SECONDS = 4.0
EXTRA_ALLOWED = 1.6            # heard words may outnumber expected words by this much and no more
NEARBY_SECONDS = 20.0
LEAK_HEARD, LEAK_EXPECTED = 0.75, 0.5
LENGTH_TOLERANCE = 0.5
FRAME_TIMES = (0.04, 0.27, 0.5, 0.73, 0.96)

# Things people say about the take, not in it. Deliberately few and exact: a loose list flags
# clean clips, and a report that is usually wrong stops being read.
TAKE_TALK = [(re.compile(rx, re.IGNORECASE), why) for rx, why in (
    (r"\b(?:say|do|try) (?:it|that|this) (?:again|once more)\b", "asking for the line again"),
    (r"\bone more time\b", "asking for the line again"),
    (r"\bfrom the top\b", "starting the take again"),
    (r"\b(?:let me|can i|i'?ll) start (?:over|again)\b", "starting the take again"),
    (r"\btake (?:two|three|four|five)\b", "naming the take"),
    (r"\bare we (?:rolling|recording|live)\b", "checking the camera"),
    (r"\bis (?:it|this|that) recording\b", "checking the camera"),
    (r"\b(?:how was that|was that (?:ok|okay|good|all right|alright))\b", "asking how the take went"),
    (r"\b(?:cut there|keep rolling|that'?s a wrap)\b", "directing the take"),
)]


def _ratio(expected, heard):
    return lcs(expected, heard) / float(len(expected)) if expected else 1.0


def judge_words(expected_words, heard, length, off_camera_turns=()):
    """(problems, looks, facts) for one version. `expected_words` are the clip's on-camera words on
    the version's clock; `heard` is [(start, end, word)] from listening to the FILE.

    Numbers are left out on both sides: no two speech tools write them the same way."""
    problems, looks = [], []
    expected = [t for _i, t in stream_of([w["word"] for w in expected_words])]
    heard_tokens = [t for _i, t in stream_of([w for _s, _e, w in heard])]
    facts = {"expected_words": len(expected), "heard_words": len(heard_tokens)}
    if not expected:
        return ["there are no expected words to compare with, so the words were not checked"], looks, facts
    if not heard_tokens:
        return ["no words were heard in it at all"], looks, facts

    facts["overall"] = round(_ratio(expected, heard_tokens), 2)
    if facts["overall"] < WORDS_NEEDED:
        problems.append("only %d%% of the words it should hold were heard. It may have been made from the wrong clip"
                        % round(facts["overall"] * 100))
    head_heard = [t for _i, t in stream_of([w for s, _e, w in heard if s <= EDGE_SECONDS])]
    tail_heard = [t for _i, t in stream_of([w for s, _e, w in heard if s >= length - EDGE_SECONDS])]
    facts["head"] = round(_ratio(expected[:EDGE_WORDS], head_heard), 2)
    facts["tail"] = round(_ratio(expected[-EDGE_WORDS:], tail_heard), 2)
    if facts["head"] < EDGE_NEEDED:
        problems.append("it does not open on the words it should (\"%s\"). The cut may have lost its first words"
                        % " ".join(expected[:EDGE_WORDS]))
    if facts["tail"] < EDGE_NEEDED:
        problems.append("it does not close on the words it should (\"%s\")" % " ".join(expected[-EDGE_WORDS:]))
    if len(heard_tokens) > EXTRA_ALLOWED * len(expected) + 4:
        problems.append("much more was heard in it (%d words) than it should hold (%d)" % (len(heard_tokens), len(expected)))

    heard_text = " ".join(w for _s, _e, w in heard)
    expected_text = " ".join(w["word"] for w in expected_words)
    for pattern, why in TAKE_TALK:
        m = pattern.search(heard_text)
        if not m:
            continue
        if pattern.search(expected_text):
            looks.append("\"%s\" is in the clip on purpose, and it sounds like %s. Listen to it once." % (m.group(0), why))
        else:
            problems.append("talk about the take was heard in it (\"%s\": %s)" % (m.group(0), why))
    for turn in off_camera_turns:
        said = tokens_of(turn.get("text", ""))
        if len(said) < 3:
            continue
        if _ratio(said, heard_tokens) >= LEAK_HEARD and _ratio(said, expected) < LEAK_EXPECTED:
            problems.append("words that %s said off camera were heard in it (\"%s\")"
                            % (turn.get("speaker") or "someone", turn.get("text", "")[:60]))
    return problems, looks, facts


def judge_voices(clip_entry, turns, policy, offset, brand_has_hosts):
    """(problems, facts) from the transcript's speaker labels and the stretches that were really cut."""
    pieces = clip_entry.get("pieces") or []
    if not pieces:
        return ["the clip report does not say which stretches it was cut from, so who is in it was not checked"], \
               {"pieces": 0}
    if policy.everyone_on_camera:
        return [], {"pieces": len(pieces), "off_camera_seconds": 0.0, "basis": gate.ATTESTED}
    if not policy.labelled:
        if brand_has_hosts:
            return ["the transcript does not say who is speaking, and this brand keeps someone off camera, so who "
                    "is in it could not be checked"], {"pieces": len(pieces)}
        return [], {"pieces": len(pieces), "off_camera_seconds": 0.0,
                    "basis": "this brand keeps nobody off camera, so there was nobody to keep out"}
    leaked = VC.off_camera_inside(clip_entry, turns, policy, offset)
    facts = {"pieces": len(pieces), "off_camera_seconds": leaked, "basis": "speaker labels"}
    if leaked > VC.VOICE_TOLERANCE:
        return ["%.1f seconds of someone who stays off camera is inside it" % leaked], facts
    return [], facts


def judge_frames(path, facts, length, shape):
    """(problems, frames looked at) for the disclaimer band, across the whole length of the file."""
    looked, problems = 0, []
    for share in FRAME_TIMES:
        frame = V.grab_frame(path, min(max(0.0, length * share), max(0.0, length - 0.1)), shape)
        if frame is None:
            continue
        looked += 1
        ok, why = overlays.band_present(frame, facts)
        if not ok:
            problems.append("at %s %s" % (fmt_ts(length * share), why))
    if not looked:
        return ["no frame of it could be read, so the disclaimer was not confirmed"], 0
    return (["the disclaimer is not on screen all the way through: " + "; ".join(problems)] if problems else []), looked


def verify(brand, recording, only=None, hear=None, say=None):
    """Check every finished (not preview) version. Returns the report, also written beside them.
    `hear(path)` -> [(start, end, word)] replaces the speech model so the judging can be tested."""
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    manifest = V.load_manifest(brand, recording)
    report, _folder, _kind = V.load_report(brand, recording, manifest.get("made_from") or "auto")
    transcript = Transcript.load(brand, recording)
    policy = V.speaker_policy(brand, transcript, report)
    turns = transcript.turns()
    offset = float(manifest.get("offset") or 0.0)
    hosts = bool(policy.hosts)
    logged = {(e["clip"], e["version"]): e for e in V.load_log(brand, recording)
              if not e.get("preview") and e.get("status") == "ok"}
    wanted = {c.upper() for c in only} if only else None

    if hear is None:
        if VC.speech_model() is None:
            raise VideoError("The small speech model could not be loaded, so the versions cannot be listened to and "
                             "nothing was verified. That is not a pass. Run: python factory.py doctor --deep")
        hear = VC.hear_with_model

    results = []
    for clip in manifest["clips"]:
        if wanted is not None and clip["id"].upper() not in wanted:
            continue
        entry = clip["report_entry"]
        words, _kept_out = V.clip_words(entry, transcript, offset, policy)
        pieces = entry.get("pieces") or []
        lo = (min(p[0] for p in pieces) - offset - NEARBY_SECONDS) if pieces else 0.0
        hi = (max(p[1] for p in pieces) - offset + NEARBY_SECONDS) if pieces else 0.0
        off_turns = [t for t in gate.off_camera_turns(turns, policy) if lo <= t["start"] <= hi] \
            if policy.labelled and not policy.everyone_on_camera else []
        for v in clip["versions"]:
            made = logged.get((clip["id"], v["version"]))
            if not made:
                continue
            path = brand.path(*made["file"].split("/"))
            row = {"clip": clip["id"], "version": v["version"], "file": made["file"], "problems": [], "looks": [],
                   "checks": {}}
            results.append(row)
            if not os.path.isfile(path):
                row["problems"].append("the file is not where the record says it is")
                continue
            row["sha256"] = V.sha256_of(path)
            if row["sha256"] != made.get("sha256"):
                row["problems"].append("the file has changed since it was made, so the record of what is in it no "
                                       "longer holds. Make it again")
                continue
            if not decodes_cleanly(path):
                row["problems"].append("it does not play all the way through")
                continue
            shape, length = probe_shape(path), probe_duration(path)
            row["checks"]["plays"] = {"width": shape["width"], "height": shape["height"], "seconds": round(length, 2)}
            if (shape["width"], shape["height"]) != (overlays.CANVAS_W, overlays.CANVAS_H) or not has_audio(path):
                row["problems"].append("it is not an upright %d x %d video with sound"
                                       % (overlays.CANVAS_W, overlays.CANVAS_H))
            if abs(length - float(made.get("expected_duration") or 0.0)) > LENGTH_TOLERANCE:
                row["problems"].append("it is %s long and should be %s"
                                       % (fmt_ts(length), fmt_ts(made.get("expected_duration") or 0)))

            recipe = made["recipe"]
            head = recipe["trim_seconds"] if recipe["trim"] == "head" else 0.0
            expected = V.retimed(words, head, recipe["speed"], length)
            problems, looks, facts = judge_words(expected, hear(path), length, off_turns)
            row["checks"]["words"] = facts
            row["problems"] += problems
            row["looks"] += looks

            problems, facts = judge_voices(entry, turns, policy, offset, hosts)
            row["checks"]["voices"] = facts
            row["problems"] += problems

            if clip["needs_disclaimer"]:
                band = made.get("disclaimer") or {}
                if not band.get("rect"):
                    row["problems"].append("this clip needs its disclaimer and the record of how it was made has none")
                else:
                    problems, looked = judge_frames(path, band, length, shape)
                    row["checks"]["disclaimer"] = {"frames": looked}
                    row["problems"] += problems
            row["pass"] = not row["problems"]
            say("%s  %s %s%s" % ("ok  " if row["pass"] else "FAIL", clip["id"], v["version"],
                                 "" if row["pass"] else "  " + "; ".join(row["problems"])))
    for row in results:
        row.setdefault("pass", False)
    if not results:
        raise VideoError("No finished versions were found to check, so nothing was verified. That is not a pass. "
                         "Make the versions first (previews are not checked: they are never delivered).")
    out = {"schema": 1, "brand": brand.id, "recording": recording, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "checked": len(results), "failed": ["%s %s" % (r["clip"], r["version"]) for r in results if not r["pass"]],
           "versions": results}
    path = V.variants_dir(brand, recording, REPORT_FILE)
    merged = out
    if only and os.path.isfile(path):                               # checking one clip again keeps the others' results
        try:
            old = read_json(path, "The earlier check")
            fresh = {(r["clip"], r["version"]) for r in results}
            kept = [r for r in old.get("versions", []) if (r.get("clip"), r.get("version")) not in fresh]
            merged = dict(out, versions=kept + results)
        except VideoError:
            pass
    write_json_atomic(path, merged)
    return out


def passed(brand, recording):
    """{(clip, version): sha256} for every version whose last check passed."""
    brand = as_brand(brand)
    path = V.variants_dir(brand, recording, REPORT_FILE)
    if not os.path.isfile(path):
        return {}
    data = read_json(path, "The record of the last check")
    if data.get("brand") != brand.id:
        return {}
    return {(r["clip"], r["version"]): r.get("sha256") for r in data.get("versions", [])
            if r.get("pass") and r.get("sha256")}


def where(brand, recording):
    return locate(as_brand(brand), V.variants_dir(brand, recording, REPORT_FILE))
