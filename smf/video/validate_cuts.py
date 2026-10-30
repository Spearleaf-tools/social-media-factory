"""validate_cuts.py - listen to the finished clips and check they contain what they were meant to.

A CHECK THAT READS THE PLAN IS NOT A CHECK. If the cut list's times were wrong, anything that
recomputes "what should be there" from those same times will agree with the mistake and report
success. So nothing here looks at the plan's arithmetic. Every clip file is opened and:

  plays      the whole file decodes. A render that was interrupted can keep a sensible name and
             size while the pictures inside are broken.
  head       the clip opens on the first words the cut list quoted.
  seams      every later segment (the body after a lifted hook) starts on its quoted words, at the
             point in the clip where that segment begins.
  tail       the clip closes on the last words the cut list quoted.
  voices     no stretch that was ACTUALLY cut overlaps someone who is off camera. (This one does
             read labels rather than sound, so it catches assembly mistakes, not mislabelling.)

The listening is done with the small local speech model, on purpose a DIFFERENT tool from the one
that made the transcript: two tools that agree are evidence, one tool agreeing with itself is not.
Matching is loose (a stutter or one misheard word is fine) and leaves numbers out while there are
other words to go on, because no two speech tools write a number the same way.

A COMPARISON WITH NOTHING IN IT IS NOT A PASS. A clip passes only when speech was heard in it and
its opening, its close and every hand-over between parts had real words that were compared and
found. One of those with nothing to compare (no quoted words, or only numbers that were not heard
the way they are written) makes the clip "could not be checked": not failed, because nothing was
heard to be wrong, and never passed, because nothing was heard to be right. A person watches it.

When a clip fails: listen to the video around the failing time, correct that time and its quoted
words in the cut list, run the rough cut again (saved parts make it quick), and validate again.
"""
from __future__ import annotations

import os

from smf.video import gate
from smf.video.common import (Transcript, VideoError, as_brand, decodes_cleanly, lcs, output_dir, read_json,
                              stream_of, tokens_of, write_json_atomic)
from smf.video.rough_cut import speech_model

THRESHOLD = 0.55       # share of the quoted words that must be heard, in order
EDGE_WINDOW = 6.0      # seconds of speech examined at each boundary
SEAM_BEFORE = 1.5
VOICE_TOLERANCE = 0.05

PASSED, FAILED, UNCHECKED = "passed", "failed", "could not be checked"
WATCH_IT = "could not be checked by ear: watch this one yourself"
NO_QUOTE = "there are no quoted words to listen for there"
ONLY_NUMBERS = "the quoted words there are only numbers, and the numbers were not heard the way they are written"


def match_ratio(quote, heard_words):
    """How much of `quote` is heard, in order, in `heard_words` (0..1), or None when there was
    nothing to compare. None is not a score: a comparison that looked at nothing did not happen.

    A quote that is ONLY numbers is compared on its numbers instead of having them stripped.
    Hearing them as written is evidence. Not hearing them proves nothing either way ("3" against
    "three"), so that is None as well, never a low score."""
    toks = tokens_of(quote)
    if toks:
        heard = [t for _i, t in stream_of(heard_words)]
        return lcs(toks, heard) / float(len(toks))
    toks = tokens_of(quote, keep_numbers=True)
    if not toks:
        return None
    heard = [t for _i, t in stream_of(heard_words, keep_numbers=True)]
    ratio = lcs(toks, heard) / float(len(toks))
    return ratio if ratio >= THRESHOLD else None


def judge(clip, heard, total, unchecked=None):
    """The word checks for one clip. `heard` is [(start, end, word)] from listening to the FILE;
    `total` is the file's length. Returns {check name: ratio} for the boundaries that were really
    compared. A boundary that should have been compared and could not be gets no ratio at all: its
    name and the reason go into `unchecked` (a dict the caller hands in), so it can never be read
    as a boundary that was heard to be right.

    What should be compared: where the clip opens, where it closes, and every join where one part
    of the cut list hands over to the next (a lifted hook, then its body). A join INSIDE one part
    is made by taking an off-camera voice out; it carries no quoted words on purpose, and the
    voices check is what covers it."""
    checks, at = {}, 0.0
    unchecked = {} if unchecked is None else unchecked
    segments = clip.get("segments") or []
    boundaries = []
    for i, seg in enumerate(segments):
        quote = seg.get("starts_with")
        if quote or i == 0 or seg.get("role") != segments[i - 1].get("role"):
            window = [w for t0, _t1, w in heard if at - SEAM_BEFORE <= t0 <= at + EDGE_WINDOW]
            boundaries.append(("head" if i == 0 else "seam %d" % i, quote, window))
        at += float(seg.get("duration") or 0.0)
    if not segments:
        boundaries.append(("head", "", []))
    window = [w for t0, _t1, w in heard if t0 >= total - EDGE_WINDOW]
    boundaries.append(("tail", segments[-1].get("ends_with") if segments else "", window))
    for name, quote, window in boundaries:
        ratio = match_ratio(quote, window)
        if ratio is None:
            unchecked[name] = ONLY_NUMBERS if tokens_of(quote, keep_numbers=True) else NO_QUOTE
        else:
            checks[name] = round(ratio, 2)
    return checks


def off_camera_inside(clip, turns, policy, offset):
    """Seconds of off-camera talking inside the ranges that were really cut. The ranges come from
    the report (what was rendered), and are put back on the transcript's clock first."""
    if not policy.labelled or policy.everyone_on_camera:
        return 0.0
    return round(sum(gate.off_camera_seconds(a - offset, b - offset, turns, policy)
                     for a, b in clip.get("pieces") or []), 2)


def hear_with_model(path):
    model = speech_model()
    if model is None:
        raise VideoError("The small speech model could not be loaded, so the clips cannot be listened to. "
                         "Run: python factory.py doctor --deep")
    segments, _info = model.transcribe(path, word_timestamps=True)
    return [(w.start, w.end, w.word.strip()) for s in segments for w in (s.words or []) if w.word.strip()]


def validate(brand, recording, which="auto", only=None, say=None, hear=None):
    """Check the fine cuts if there are any, otherwise the rough cuts. Returns the validation report
    (also written beside the clips). `hear(path)` is injectable so the judging can be tested."""
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    kinds = ["fine", "rough"] if which == "auto" else [which]
    folder = report_path = None
    for kind in kinds:
        candidate = os.path.join(output_dir(brand, recording, kind), "%s-cut-report.json" % kind)
        if os.path.isfile(candidate):
            folder, report_path = output_dir(brand, recording, kind), candidate
            break
    if report_path is None:
        raise VideoError("There are no cuts to check yet for '%s'. Make the rough cuts first." % recording)
    report = read_json(report_path, "The cut report")
    transcript = Transcript.load(brand, recording)
    policy = gate.SpeakerPolicy.for_transcript(brand, transcript, report.get("speaker_check") == gate.ATTESTED)
    turns = transcript.turns()
    offset = float(report.get("offset") or 0.0)
    hear = hear or hear_with_model

    wanted = {o.upper() for o in only} if only else None
    results = []
    for clip in report.get("clips", []):
        if not clip.get("file") or (wanted is not None and clip["id"].upper() not in wanted):
            continue
        entry = {"id": clip["id"], "file": clip["file"], "checks": {}, "problems": [], "unchecked": {}}
        path = os.path.join(folder, clip["file"])
        if clip.get("status") != "ok" or not os.path.isfile(path):
            entry["problems"].append("it was not made properly (status: %s)" % clip.get("status", "missing"))
        elif not decodes_cleanly(path):
            entry["problems"].append("the file does not play all the way through; it was probably interrupted "
                                     "while being made")
        else:
            heard = hear(path)
            total = float(clip.get("actual_duration") or 0.0)
            entry["checks"] = judge(clip, heard, total, entry["unchecked"])
            if not heard:
                entry["problems"].append("no speech was heard in it at all")
            for name, ratio in entry["checks"].items():
                if ratio < THRESHOLD:
                    entry["problems"].append("%s: the quoted words were not heard there (%.0f%% matched)"
                                             % (name, ratio * 100))
            leaked = off_camera_inside(clip, turns, policy, offset)
            entry["checks"]["off-camera seconds"] = leaked
            if leaked > VOICE_TOLERANCE:
                entry["problems"].append("%.1f seconds of someone off camera is inside it" % leaked)
        # Heard to be wrong outranks not heard at all; only a clip with neither has passed.
        entry["state"] = FAILED if entry["problems"] else (UNCHECKED if entry["unchecked"] else PASSED)
        entry["pass"] = entry["state"] == PASSED
        results.append(entry)
        gaps = "; ".join("%s: %s" % (name, why) for name, why in entry["unchecked"].items())
        if entry["state"] == UNCHECKED:
            say("LOOK  %s  %s (%s)" % (clip["id"], WATCH_IT, gaps))
        else:
            say("%s  %s%s" % ("ok  " if entry["pass"] else "FAIL", clip["id"],
                              "" if entry["pass"] else "  " + "; ".join(entry["problems"] + ([gaps] if gaps else []))))

    # A check that examined nothing must never come back green: that is how a moved folder or a
    # mistyped name turns into "all clear".
    if not results:
        raise VideoError("No clips were found to check, so nothing was verified. That is not a pass.")
    unheard = [r["id"] for r in results if r["state"] == UNCHECKED]
    if unheard:
        say("%d clip(s) could not be checked by ear, so they are counted as not passed: %s. Watch each one "
            "yourself. To have one checked next time, give it quoted first and last words in the cut list (words, "
            "not only numbers), and make sure it does not open or close on someone who is off camera."
            % (len(unheard), ", ".join(unheard)))
    # `failed` is every clip that did not pass. `could_not_check` names the ones among them where
    # nothing was heard to be wrong, only nothing could be compared.
    out = {"schema": 1, "kind": report.get("kind"), "brand": brand.id, "recording": recording,
           "checked": len(results), "failed": [r["id"] for r in results if not r["pass"]],
           "could_not_check": unheard, "clips": results}
    write_json_atomic(os.path.join(folder, "validation-report.json"), out)
    return out
