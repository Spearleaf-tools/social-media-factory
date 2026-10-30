"""video_cli.py - the clip verbs. Every one of them needs --brand; there is no default brand.

    transcribe       what a recording will cost to transcribe; with --confirm, send it
                     (also: --srt to bring in an editor's subtitles, --name to name the voices)
    find-clips       flag compliance problems, list stretches worth reading, start a cut list
    check-cut-list   prove the cut list against the transcript, without cutting anything
    rough-cut        cut list -> stitched rough cuts (--dry-run shows the plan only)
    fine-cut         rough cuts -> fine cuts (fillers and dead air out)
    validate-cuts    listen to the finished clips and check they hold what they should

Each returns 0 when it did its job and 1 when it could not, with a plain sentence saying why.
"""
from __future__ import annotations

import argparse

from smf import brands
from smf.video.common import Transcript, VideoError, list_recordings, output_dir, CUT_LIST_FILE


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
            findings = getattr(e, "findings", None)
            print(str(e))
            for f in findings or []:
                print("  - %s" % f)
            return 1
        except OSError as e:
            print("A file could not be read or written (%s). Nothing else was changed. Check that the disk has "
                  "room and that the brand's folder is not open in another program." % (e.strerror or "unknown reason"))
            return 1
    wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
    return wrapped


def _show(findings):
    for f in findings:
        print("  - %s" % f)


@_guard
def cli_transcribe(args):
    from smf.video import transcribe as T
    ap = _parser("transcribe", "Transcribe a recording (costs money: nothing is sent without --confirm).")
    ap.add_argument("--media", help="the video or audio file to transcribe")
    ap.add_argument("--srt", help="instead of transcribing: a subtitle file an editor made for the video")
    ap.add_argument("--speakers", type=int, help="how many people speak, if you know")
    ap.add_argument("--name", action="append", default=[], metavar='speaker_0="Their Name"',
                    help="name a voice in a transcript that already exists (free; repeat for each voice)")
    ap.add_argument("--confirm", action="store_true", help="really send it, and spend the money")
    ap.add_argument("--again", action="store_true", help="send it even though a transcript already exists")
    a = ap.parse_args(args)
    brand = brands.load(a.brand)

    if a.name:
        mapping = {}
        for pair in a.name:
            label, sep, name = pair.partition("=")
            if not sep:
                raise VideoError("Write each name like speaker_0=\"Ava Lindqvist\".")
            mapping[label.strip()] = name.strip().strip('"')
        _transcript, policy = T.rename_speakers(brand, a.recording, mapping)
        print("The voices are named. %s" % policy.describe())
        return 0

    if a.srt:
        transcript, _policy = T.ingest_srt(brand, a.recording, a.srt, a.media)
        print("Filed %d subtitle lines as the transcript for '%s'. It has sentence times only and does not say "
              "who is speaking, so the speaker check will be unverified." % (len(transcript.segments), a.recording))
        return 0

    if not a.media:
        raise VideoError("Say which file to transcribe with --media (or bring in subtitles with --srt).")
    result = T.transcribe(brand, a.recording, a.media, confirm=a.confirm, speakers=a.speakers, again=a.again, say=print)
    if not result["sent"]:
        print(T.plan_words(result["plan"]))
        return 0
    transcript, policy = result["transcript"], result["policy"]
    print("Done: %d words, %d voice(s): %s." % (len(transcript.words), len(transcript.speakers),
                                                ", ".join(transcript.speakers) or "none labelled"))
    if len(transcript.speakers) > 1 and not policy.on_camera():
        print("Next: read the first lines of the transcript, work out which voice is which, and name them "
              "(--name speaker_0=\"...\" --name speaker_1=\"...\"). Until then no clip can be cut.")
    else:
        print(policy.describe())
    return 0


@_guard
def cli_find_clips(args):
    from smf.video import find_clips as F
    ap = _parser("find-clips", "Flag compliance problems and list stretches worth reading. It does not rank.")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--nobody-off-camera", action="store_true",
                    help="you are saying that everyone heard in THIS recording is on camera")
    a = ap.parse_args(args)
    result = F.run(brands.load(a.brand), a.recording, top=a.top, everyone_on_camera=a.nobody_off_camera)
    print("%d stretch(es) worth reading first, %d flagged by the brand's rules."
          % (len(result["pass"]), len(result["quarantine"])))
    for e in result["quarantine"]:
        print("  - %s at %s: %s" % (e["gate"], _clock(e["start"]), "; ".join(e["reasons"])))
    print("They are in the recording's folder under Output/video, in 'candidates'. These are places to look, "
          "not a ranking: a person picks the clips.")
    if result["started_cut_list"]:
        print("A cut list was started there too, with its reference block filled in.")
    return 0


@_guard
def cli_check_cut_list(args):
    from smf.video import cutlist, gate
    ap = _parser("check-cut-list", "Prove the cut list against the transcript. Cuts nothing.")
    ap.add_argument("--cut-list", help="the cut list file, if it is not in the usual place")
    ap.add_argument("--nobody-off-camera", action="store_true")
    a = ap.parse_args(args)
    brand = brands.load(a.brand)
    transcript = Transcript.load(brand, a.recording)
    policy = gate.SpeakerPolicy.for_transcript(brand, transcript, a.nobody_off_camera)
    policy.require_checkable()
    cl = cutlist.load(a.cut_list or output_dir(brand, a.recording, CUT_LIST_FILE))
    findings = cutlist.validate(cl, transcript, brand, recording=a.recording, policy=policy)
    clips = cl.clips()
    if cutlist.is_valid(findings):
        print("The cut list holds up: %d clip(s) from %d bod%s. %s"
              % (len(clips), len(cl.bodies), "y" if len(cl.bodies) == 1 else "ies", policy.describe()))
    else:
        print("The cut list has problems to fix before anything is cut:")
    _show(findings)
    return 0 if cutlist.is_valid(findings) else 1


@_guard
def cli_rough_cut(args):
    from smf.video import rough_cut as R
    ap = _parser("rough-cut", "Cut list -> stitched rough cuts.")
    ap.add_argument("--cut-list", help="the cut list file, if it is not in the usual place")
    ap.add_argument("--only", action="append", help="just this clip (for example A1); repeat for more")
    ap.add_argument("--dry-run", action="store_true", help="show where every cut would land; make nothing")
    ap.add_argument("--listen", choices=("auto", "model", "transcript", "none"), default="auto")
    ap.add_argument("--height", type=int, default=0, help="make smaller working copies, this many pixels tall")
    ap.add_argument("--nobody-off-camera", action="store_true",
                    help="you are saying that everyone heard in THIS recording is on camera")
    ap.add_argument("--anyway", action="store_true", help="render even though the quoted words were mostly not found")
    a = ap.parse_args(args)
    report = R.rough_cut(brands.load(a.brand), a.recording, cut_list_path=a.cut_list, only=a.only,
                         dry_run=a.dry_run, listen=a.listen, everyone_on_camera=a.nobody_off_camera,
                         anyway=a.anyway, height=a.height, say=print)
    made = [c for c in report["clips"] if c.get("status") == "ok"]
    bad = [c for c in report["clips"] if c.get("status") == "duration-mismatch"]
    skipped = [c for c in report["clips"] if str(c.get("status", "")).startswith(("skipped", "nothing"))]
    if a.dry_run:
        print("\nThat is the plan for %d clip(s). Nothing was made." % len([c for c in report["clips"] if c.get("segments")]))
    else:
        print("\n%d rough cut(s) made%s." % (len(made), (", %d left out" % len(skipped)) if skipped else ""))
    if report["alarm"]:
        print("WARNING: " + report["alarm"])
    if report["by_ear"]:
        print("These edges could not be lined up on words, so check them by ear: %s." % ", ".join(report["by_ear"]))
    holds = [c["id"] for c in report["clips"] if c.get("gate") == "HOLD" and not c.get("signed_off")]
    if holds:
        print("On HOLD, waiting for sign-off, not to be posted yet: %s." % ", ".join(holds))
    if report["shape"]["orientation"] == "horizontal":
        print("Note: this video is horizontal. Short-form platforms want vertical, so a later step has to reframe it.")
    if bad:
        print("These came out the wrong length and should not be used: %s." % ", ".join(c["id"] for c in bad))
        return 1
    if not a.dry_run:
        print("Next: validate-cuts, which listens to the files and checks they hold the right words.")
    return 0


@_guard
def cli_fine_cut(args):
    from smf.video import fine_cut as F
    ap = _parser("fine-cut", "Rough cuts -> fine cuts: fillers and dead air out, gently.")
    ap.add_argument("--only", action="append")
    ap.add_argument("--dry-run", action="store_true", help="show what would be removed; make nothing")
    ap.add_argument("--gap-max", type=float, help="only pauses longer than this many seconds are tightened")
    a = ap.parse_args(args)
    settings = {"gap_max": a.gap_max} if a.gap_max else None
    report = F.fine_cut(brands.load(a.brand), a.recording, only=a.only, dry_run=a.dry_run, settings=settings, say=print)
    rough = sum(c["rough_duration"] for c in report["clips"])
    fine = sum(c["fine_duration"] for c in report["clips"])
    print("\n%d clip(s): %s -> %s (%.0f seconds taken out)." % (len(report["clips"]), _clock(rough), _clock(fine), rough - fine))
    flagged = [c["id"] for c in report["clips"] if c.get("check")]
    if flagged:
        print("Look at these before trusting them: %s." % ", ".join(flagged))
    if not a.dry_run:
        print("Next: validate-cuts. Then a person watches the fine cuts and says yes before anything else is made "
              "from them.")
    return 0


@_guard
def cli_validate_cuts(args):
    from smf.video import validate_cuts as V
    ap = _parser("validate-cuts", "Listen to the finished clips and check they hold the right words.")
    ap.add_argument("--which", choices=("auto", "rough", "fine"), default="auto")
    ap.add_argument("--only", action="append")
    a = ap.parse_args(args)
    out = V.validate(brands.load(a.brand), a.recording, which=a.which, only=a.only, say=print)
    # A clip nobody could check is not the same as one heard to be wrong, and the advice differs.
    wrong = [c for c in out["failed"] if c not in out["could_not_check"]]
    print("\n%d %s cut(s) checked, %d heard to be wrong, %d could not be checked."
          % (out["checked"], out["kind"], len(wrong), len(out["could_not_check"])))
    if wrong:
        print("For each one that is wrong: listen to the video around that spot, correct the time and the quoted "
              "words in the cut list, make the cuts again, and check again.")
    return 1 if out["failed"] else 0


def cli_recordings(args):
    """Small helper for skills: which recordings does a brand have, and which have a transcript."""
    ap = argparse.ArgumentParser(prog="factory.py recordings")
    ap.add_argument("--brand", required=True)
    a = ap.parse_args(args)
    try:
        brand = brands.load(a.brand)
    except brands.BrandError as e:
        print(str(e))
        return 1
    names = list_recordings(brand)
    if not names:
        print("No recordings yet. Put each one in its own folder inside the brand's Inputs/Recordings folder.")
        return 0
    for n in names:
        try:
            t = Transcript.load(brand, n)
            state = "transcribed (%s)" % (", ".join(t.speakers) or "no voice labels")
        except VideoError:
            state = "not transcribed yet"
        print("%s: %s" % (n, state))
    return 0


def _clock(seconds):
    from smf.video.common import fmt_ts
    return fmt_ts(seconds, 0)
