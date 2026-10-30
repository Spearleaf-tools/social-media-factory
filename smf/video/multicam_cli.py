"""multicam_cli.py - the two-camera verbs. Every one of them needs --brand and --recording.

    sync       line recordings up by their sound: how far apart, and which way
               two cameras:  --camera-a FILE --camera-b FILE   (saved with the recording)
               one camera:   --video FILE                      (the cut list's Offset, size and sign)
    multicam   plan     say who is on which camera, and read the list of shots before rendering
               render   make the two-camera video (--dry-run shows the shots and makes nothing)
               clips    make the cut list's clips from the two cameras
               verify   open what was made and check pictures, sound and length (--clips for the clips)

Each returns 0 when it did its job and 1 when it could not, with a plain sentence saying why.
"""
from __future__ import annotations

import argparse
import os

from smf import brands
from smf.video.common import VideoError, fmt_ts

ACTIONS = ("plan", "render", "clips", "verify")


def _parser(verb, about):
    ap = argparse.ArgumentParser(prog="factory.py %s" % verb, description=about)
    ap.add_argument("--brand", required=True, help="which brand this is for (there is no default)")
    ap.add_argument("--recording", required=True, help="the recording's folder name inside Inputs/Recordings")
    return ap


def _guard(fn):
    """Run one verb; turn the tools' own errors into a sentence and exit code 1."""
    def wrapped(args):
        try:
            return fn(args)
        except (brands.BrandError, VideoError) as e:
            print(str(e))
            for f in getattr(e, "findings", None) or []:
                print("  - %s" % f)
            return 1
        except OSError as e:
            print("A file could not be read or written (%s). Nothing else was changed. Check that the disk has "
                  "room and that the brand's folder is not open in another program." % (e.strerror or "unknown reason"))
            return 1
    wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
    return wrapped


def _pairs(items, what, example):
    """['Ava Lindqvist=A', ...] -> {'Ava Lindqvist': 'A'}"""
    out = {}
    for item in items or []:
        name, sep, value = item.rpartition("=")
        if not sep or not name.strip() or not value.strip():
            raise VideoError("Write each %s like %s." % (what, example))
        out[name.strip().strip('"')] = value.strip().strip('"')
    return out


def _numbers(pairs, what):
    out = {}
    for key, value in pairs.items():
        try:
            out[key] = float(value)
        except ValueError:
            raise VideoError("'%s' is not a number of seconds (%s)." % (value, what))
    return out


def _evidence(found):
    """One line on how far a measured offset can be trusted."""
    if found["method"] == "same-file":
        return "it is the file the transcript was made from%s" % (
            ", and the words do land on its speech" if found["checked"] else "")
    if found["method"] == "given":
        return ("a person gave this number, and listening confirms it" if found["checked"]
                else "a person gave this number; it could not be checked")
    clear = [w for w in found["windows"] if w.get("clear")]
    return ("%d of %d places agree to within %.0f ms, confidence %s; after shifting by it, what is left over is %.0f ms"
            % (len(clear), len(found["windows"]), found["spread"] * 1000, found["confidence_word"],
               abs(found["residual"] or 0.0) * 1000))


@_guard
def cli_sync(args):
    from smf.video import multicam, sync
    ap = _parser("sync", "Line recordings up by their sound: how far apart they are, and which way.")
    ap.add_argument("--camera-a", help="two cameras: the first camera's file")
    ap.add_argument("--camera-b", help="two cameras: the second camera's file")
    ap.add_argument("--sound", default="A", help="whose sound the finished video uses: A, B, or a separate sound file")
    ap.add_argument("--a-offset", type=float, help="you already know how far camera A is from the sound, in seconds")
    ap.add_argument("--b-offset", type=float, help="you already know how far camera B is from the sound, in seconds")
    ap.add_argument("--nudge", action="append", default=[], metavar="B=0.08",
                    help="delay one camera's PICTURE by this many seconds (its lips run early); the sound never moves")
    ap.add_argument("--video", help="one camera: the video the cut list is cut from, to measure its Offset")
    ap.add_argument("--save", action="store_true", help="one camera: write the measured Offset into the cut list")
    a = ap.parse_args(args)
    brand = brands.load(a.brand)

    if a.camera_a or a.camera_b:
        if not (a.camera_a and a.camera_b):
            raise VideoError("Two cameras means two files: give both --camera-a and --camera-b.")
        given = {k: v for k, v in (("A", a.a_offset), ("B", a.b_offset)) if v is not None}
        nudge = _numbers(_pairs(a.nudge, "nudge", "B=0.08"), "a nudge")
        setup = multicam.line_up(brand, a.recording, a.camera_a, a.camera_b, sound=a.sound, given=given,
                                 nudge={k.upper(): v for k, v in nudge.items()}, say=print)
        print("")
        a_off, b_off = (setup["cameras"][c]["offset"] for c in ("A", "B"))
        print(sync.in_words(b_off - a_off, "camera A", "camera B"))
        for cam in ("A", "B"):
            print("  camera %s: %s." % (cam, _evidence(setup["cameras"][cam]["how"])))
            for note in setup["cameras"][cam]["how"].get("notes") or []:
                print("    " + note)
        base = setup["transcript"]["how"]
        print("  the transcript: %s." % _evidence(base))
        for note in base.get("notes") or []:
            print("    " + note)
        print("Saved with the recording. Next: multicam plan, saying who is on which camera "
              "(--speaker \"Their Name=A\").")
        return 0

    out = sync.offset_for_cut_list(brand, a.recording, video=a.video, save=a.save, say=print)
    found = out["offset"]
    name = os.path.basename(out["video"])
    print("")
    print(sync.in_words(found, "the transcript", "'%s'" % name, both_recordings=False))
    print("  %s." % _evidence(found.as_dict()))
    for note in found.notes:
        print("  " + note)
    text = sync.offset_text(found.seconds)
    if out["was"] is not None and abs(out["was"] - found.seconds) > 0.1:
        print("The cut list says %s at the moment. That does not match what was measured." % sync.offset_text(out["was"]))
        if abs(out["was"] + found.seconds) <= 0.1:
            print("It is the right size with the sign back to front, which puts every cut twice as far out as "
                  "no offset at all.")
    if out["saved"]:
        print("The cut list's Offset line now reads: %s" % text)
    else:
        print("The cut list's Offset line should read: %s   (add --save to write it for you)" % text)
    return 0


def _choices(ap):
    ap.add_argument("--speaker", action="append", default=[], metavar='"Their Name=A"',
                    help="which camera a voice is on; repeat for each voice. Never worked out from a name.")
    ap.add_argument("--off-camera", action="append", default=[], metavar='"Their Name"',
                    help="a voice that is on neither camera and is never cut to")
    ap.add_argument("--rule", action="append", default=[], metavar="shortest_shot=3",
                    help="change one editing rule for this recording; repeat for more")
    ap.add_argument("--look-at", action="append", default=[], metavar="A=0.4",
                    help="where the person sits across their camera's frame (0 to 1), for side-by-side shots")
    ap.add_argument("--left", choices=("A", "B"), help="which camera is on the left in side-by-side shots")
    ap.add_argument("--height", type=int, default=0, help="make the video this many pixels tall")


def _chosen(a):
    return {"speakers": _pairs(a.speaker, "speaker", '"Their Name=A"'), "off_camera": a.off_camera,
            "rules": _numbers(_pairs(a.rule, "rule", "shortest_shot=3"), "a rule"),
            "look_at": {k.upper(): v for k, v in _numbers(_pairs(a.look_at, "place", "A=0.4"), "a place").items()},
            "left": a.left, "height": a.height}


def _time(value):
    from smf.video.common import parse_ts
    return None if value is None else parse_ts(value)


@_guard
def cli_multicam(args):
    from smf.video import multicam
    if not args or args[0] not in ACTIONS:
        print("Say what to do: multicam %s. For example: multicam plan --brand ... --recording ..." % " | ".join(ACTIONS))
        return 1
    action, rest = args[0], args[1:]

    if action in ("plan", "render"):
        ap = _parser("multicam %s" % action, "The two-camera edit: one video that shows whoever is talking.")
        _choices(ap)
        ap.add_argument("--layout", choices=multicam.LAYOUTS)
        ap.add_argument("--from", dest="start", help="begin here, in the transcript's time (for example 01:30)")
        ap.add_argument("--to", dest="end", help="end here")
        if action == "render":
            ap.add_argument("--dry-run", action="store_true", help="show the list of shots; render nothing")
            ap.add_argument("--encoder", choices=("auto", "software", "hardware"), default="auto")
        a = ap.parse_args(rest)
        brand = brands.load(a.brand)
        choices = dict(_chosen(a), layout=a.layout, start=_time(a.start), end=_time(a.end))
        if action == "plan":
            decisions, _files = multicam.plan(brand, a.recording, remember=True, **choices)
        else:
            decisions = multicam.render(brand, a.recording, dry_run=a.dry_run, encoder=a.encoder, say=print, **choices)
        print("\n".join(multicam.describe(decisions)))
        for note in decisions["notes"]:
            print("Note: " + note)
        if action == "plan" or decisions.get("dry_run"):
            print("\nThat is the plan. Nothing was rendered. If a cut looks wrong, change a rule (--rule) or check who "
                  "is on which camera, then look again. When it reads right: multicam render.")
        else:
            print("\nMade %s (%s). The list of shots is saved beside it. Next: multicam verify."
                  % (decisions["output"], fmt_ts(decisions["actual_duration"], 0)))
        return 0

    if action == "clips":
        from smf.video import multicam_clips
        ap = _parser("multicam clips", "The cut list's clips, made from the two cameras.")
        _choices(ap)
        ap.add_argument("--layout", choices=multicam.LAYOUTS, help="solo unless you say otherwise: clips usually get "
                        "cropped tall later, and a crop must not land between two people")
        ap.add_argument("--cut-list", help="the cut list file, if it is not in the usual place")
        ap.add_argument("--only", action="append", help="just this clip (for example A1); repeat for more")
        ap.add_argument("--dry-run", action="store_true", help="show where every cut would land; make nothing")
        ap.add_argument("--listen", choices=("auto", "model", "transcript", "none"), default="auto")
        ap.add_argument("--encoder", choices=("software", "hardware"), default="software")
        ap.add_argument("--nobody-off-camera", action="store_true",
                        help="you are saying that everyone heard in THIS recording is on one of the cameras")
        ap.add_argument("--anyway", action="store_true", help="render even though the quoted words were mostly not found")
        a = ap.parse_args(rest)
        report = multicam_clips.make_clips(brands.load(a.brand), a.recording, cut_list_path=a.cut_list, only=a.only,
                                           dry_run=a.dry_run, listen=a.listen, everyone_on_camera=a.nobody_off_camera,
                                           anyway=a.anyway, layout=a.layout, encoder=a.encoder, say=print, **_chosen(a))
        made = [c for c in report["clips"] if c.get("status") == "ok"]
        bad = [c for c in report["clips"] if c.get("status") == "duration-mismatch"]
        skipped = [c for c in report["clips"] if str(c.get("status", "")).startswith(("skipped", "nothing"))]
        if a.dry_run:
            print("\nThat is the plan for %d clip(s). Nothing was made."
                  % len([c for c in report["clips"] if c.get("segments")]))
        else:
            print("\n%d two-camera clip(s) made%s." % (len(made), (", %d left out" % len(skipped)) if skipped else ""))
        if report["kept_out"]:
            print("Kept out of every clip: %s." % ", ".join(report["kept_out"]))
        if report["alarm"]:
            print("WARNING: " + report["alarm"])
        if report["by_ear"]:
            print("These edges could not be lined up on words, so check them by ear: %s." % ", ".join(report["by_ear"]))
        holds = [c["id"] for c in report["clips"] if c.get("gate") == "HOLD" and not c.get("signed_off")]
        if holds:
            print("On HOLD, waiting for sign-off, not to be posted yet: %s." % ", ".join(holds))
        if bad:
            print("These came out the wrong length and should not be used: %s." % ", ".join(c["id"] for c in bad))
            return 1
        if not a.dry_run:
            print("Next: multicam verify --clips (are the right pictures on screen), then validate-cuts (are the "
                  "right words in them). These clips were made from two cameras, so skip fine-cut: it re-cuts from "
                  "one source file and there is not one.")
        return 0

    from smf.video import multicam_verify
    ap = _parser("multicam verify", "Open what was made and check pictures, sound and length.")
    ap.add_argument("--clips", action="store_true", help="check the two-camera clips instead of the full edit")
    ap.add_argument("--only", action="append", help="with --clips: just this clip")
    ap.add_argument("--samples", type=int, help="how many cuts to look at (they are spread evenly)")
    a = ap.parse_args(rest)
    brand = brands.load(a.brand)
    if a.clips:
        out = multicam_verify.verify_clips(brand, a.recording, only=a.only, samples=a.samples or 12, say=print)
        print("\n%d clip(s) checked, %d failed." % (out["checked"], len(out["failed"])))
        return 1 if out["failed"] else 0
    out = multicam_verify.verify_edit(brand, a.recording, samples=a.samples or multicam_verify.DEFAULT_SAMPLES, say=print)
    print("Pictures: %d frame(s) beside the cuts compared with the cameras, %d wrong%s."
          % (out["pictures"]["checked"], out["pictures"]["wrong"],
             (", %d too alike to tell" % out["pictures"]["could_not_tell"]) if out["pictures"]["could_not_tell"] else ""))
    print("Sound: found where it belongs at %d place(s)." % out["sound"]["checked"])
    print("Length: %s, planned %s." % (fmt_ts(out["length"]["actual"], 2), fmt_ts(out["length"]["planned"], 2)))
    if out["pass"]:
        print("The video is what the list of shots says it is.")
        return 0
    print("Do not use this video yet:")
    for p in out["problems"]:
        print("  - " + p)
    return 1
