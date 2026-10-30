"""multicam_clips.py - the cut list's clips, made from two cameras instead of one.

THE SAME CUT LIST, THE SAME RULES. A two-camera recording uses exactly the cut list a one-camera
recording uses (smf.video.cutlist): bodies, hooks, quoted boundary words, gates. It is proved
against the transcript by the same checker, off-camera voices are taken out by the same code,
and every cut is lined up on the quoted words and the real pauses by the same snapping functions
the rough cut uses. Only the last step differs: each stretch is rendered through the two-camera
switcher, so the picture follows whoever is talking inside the clip.

WHO MAY BE IN A CLIP. Both conditions, always:
  * the brand's own rule allows the voice (a name on the brand's off-camera list stays out, and
    so does a voice nobody has named, unless a person says nobody is off camera in THIS recording);
  * the voice is on one of the two cameras. A voice with no camera has no picture to cut to.
A hook or a body's boundary spoken by anyone else is refused by the cut-list checker, in words.

TIMES. A cut list's times are transcript times. Two cameras have two different offsets from the
transcript, so the cut list's single `Offset` line cannot describe them and is not used: each
file's own measured offset (from `sync`) is. If the cut list's `Cut from` names one of these files
and its `Offset` disagrees with what was measured, that is an error: one of the two numbers has
the wrong size or the wrong sign, and it is better found here than after a batch of renders.

THE REPORT has the shape of `rough-cut-report.json` and lives where that does, so everything that
reads rough cuts (the checker that listens to clips, captions, versions, posting) reads these
with no special case: `pieces` are the stretches that were really cut, in transcript time, with
`offset` 0. What is different is said plainly in the report (`made_with`, `cameras`, `layout`,
and the shots inside every stretch). `source` names no single file, because there is none: a step
that re-cuts from one source file must stop rather than quietly make one-camera clips.

Layout defaults to `solo`: clips are usually cropped to a tall frame later, and a crop must never
land on the gap between two people.
"""
from __future__ import annotations

import hashlib
import json
import os

from smf.studio.lint import Finding
from smf.video import cutlist, gate, multicam, rough_cut
from smf.video.common import (CUT_LIST_FILE, VideoError, fmt_ts, join_parts, locate, merge_report, output_dir,
                              probe_duration, resolve, usable_part, write_json_atomic)

MADE_WITH = "two cameras"
NO_SINGLE_SOURCE = "two cameras (see 'cameras' in this report)"
REPORT_FILE = "rough-cut-report.json"
OFFSETS_AGREE_WITHIN = 0.10


class CameraPolicy(gate.SpeakerPolicy):
    """The brand's speaker rule, plus one more condition: the voice has to be on a camera."""

    def __init__(self, brand, speakers, camera_of, everyone_on_camera=False):
        gate.SpeakerPolicy.__init__(self, brand, speakers, everyone_on_camera)
        self.camera_of = dict(camera_of)
        unseen = [s for s in self.present if not self.camera_of.get(s)]
        if self.everyone_on_camera and unseen:
            # "Nobody is off camera" switches the voice-by-voice removal off altogether, so it can
            # only be accepted when it is true of every voice in the recording.
            raise VideoError("You said nobody is off camera in this recording, but %s on neither camera. Put them on a "
                             "camera (--speaker \"%s=B\"), or leave out --nobody-off-camera so their voice is cut around."
                             % (" and ".join("'%s'" % s for s in unseen) + (" is" if len(unseen) == 1 else " are"), unseen[0]))

    def may_publish(self, name):
        return bool(self.camera_of.get(name or "")) and gate.SpeakerPolicy.may_publish(self, name)


def reference_findings(cl, brand, recording, files):
    """Does the cut list's own Offset contradict what was measured for the file it names?"""
    written = cl.reference.get("cut_from")
    named = resolve(brand, recording, written) if written else None
    if not named:
        return []
    from smf.video.sync import same_file
    for key, label in ((multicam.A, "camera A"), (multicam.B, "camera B"), ("sound", "the sound file")):
        if same_file(named, files[key]["path"]):
            measured = files[key]["offset"]
            if abs(cl.offset - measured) > OFFSETS_AGREE_WITHIN:
                return [Finding("ERROR", "reference", "The cut list says '%s' is %+.3f seconds from the transcript, "
                                "but lining the files up by their sound measured %+.3f for it (%s). One of the two has "
                                "the wrong size or the wrong sign. Run sync again; if it gives the same answer, "
                                "correct the Offset line." % (os.path.basename(named), cl.offset, measured, label))]
            return []
    if abs(cl.offset) > OFFSETS_AGREE_WITHIN:
        return [Finding("WARN", "reference", "The cut list's 'Cut from' and 'Offset' describe a file that is not one of "
                        "the two cameras. Two-camera clips are cut from the cameras with the offsets sync measured, "
                        "so that Offset is not used here.")]
    return []


# ----------------------------------------------------------------------------- where each cut lands
def _listeners(transcript, sound, listen, listener, say):
    """(listen(a, b), silences(a, b), what it is called), all in TRANSCRIPT time. The sound file
    runs on its own clock, so every question is shifted onto that clock and every answer back."""
    shift = sound["offset"]

    def silences(a, b):
        return [(s - shift, e - shift) for s, e in rough_cut.find_silences(sound["path"], a + shift, b + shift)]

    if listener is not None:
        return listener, silences, "a supplied listener"
    if listen in ("auto", "model"):
        heard = rough_cut.listen_with_model(sound["path"])
        if heard is not None:
            return (lambda a, b: [(t0 - shift, t1 - shift, w) for t0, t1, w in heard(a + shift, b + shift)],
                    silences, "speech-model")
        if listen == "model":
            raise VideoError("The small speech model could not be loaded. Run: python factory.py doctor --deep")
    if listen in ("auto", "transcript") and transcript.word_level:
        say("Lining cuts up with the transcript's own word times (the sound itself is not being listened to).")
        return rough_cut.listen_from_transcript(transcript, 0.0), silences, "transcript"
    return None, silences, "pauses only"


def resolve_cuts(planned, snapper, silences, lo, hi):
    """Every requested start and end becomes a real cut point, once each, by the rough cut's own
    rules: the quoted words, else the nearest word, else a real pause, else a fixed margin. Cuts
    stay inside [lo, hi], the stretch both cameras and the sound cover."""
    heads, tails = {}, {}

    def head(seg):
        stamp = seg["start"]
        found = None
        if snapper is not None:
            words, pauses = snapper.near(stamp)
            found = rough_cut.snap_head(words, pauses, stamp, seg["starts_with"], seg["wall_lo"], seg["wall_hi"])
        if found is None:
            cut = rough_cut.head_from_silences(silences(stamp - 1.2, stamp + rough_cut.STAMP_SLACK + 0.4), stamp)
            found = (cut, "silence") if cut is not None else (stamp - rough_cut.FALLBACK_PAD, "pad")
        return max(lo, rough_cut.clamp(found[0], seg["wall_lo"], seg["wall_hi"], hi)), found[1]

    def tail(seg):
        stamp = seg["end"]
        found = None
        if snapper is not None:
            words, pauses = snapper.near(stamp)
            found = rough_cut.snap_tail(words, pauses, stamp, seg["ends_with"], seg["wall_lo"], seg["wall_hi"])
        if found is None:
            cut = rough_cut.tail_from_silences(silences(stamp - 0.6, stamp + rough_cut.STAMP_SLACK + 0.6), stamp)
            found = (cut, "silence") if cut is not None else (stamp + rough_cut.FALLBACK_PAD, "pad")
        return max(lo, rough_cut.clamp(found[0], seg["wall_lo"], seg["wall_hi"], hi)), found[1]

    for item in planned:
        for seg in item["segments"]:
            hk = (round(seg["start"], 3), seg["starts_with"], seg["wall_lo"])
            tk = (round(seg["end"], 3), seg["ends_with"], seg["wall_hi"])
            if hk not in heads:
                heads[hk] = head(seg)
            if tk not in tails:
                tails[tk] = tail(seg)
            (a, how_a), (b, how_b) = heads[hk], tails[tk]
            if b - a < 0.2:
                raise VideoError("Clip %s: one of its pieces came out empty (%s to %s). Either its times and quoted "
                                 "words need checking in the cut list, or it falls outside %s - %s, the only stretch "
                                 "both cameras were recording." % (item["clip"].id, fmt_ts(a), fmt_ts(b), fmt_ts(lo), fmt_ts(hi)))
            seg["cut"], seg["snap"] = [round(a, 3), round(b, 3)], [how_a, how_b]
    return planned


def part_name(cut, shots, ready, encoder):
    """A part is only reused when EVERYTHING that shaped it is the same: the stretch, the shots
    inside it, the files and their offsets, the picture's size and the encoder. Anything less and
    changing who is on which camera would quietly keep serving yesterday's pictures."""
    recipe = json.dumps([shots, multicam.files_record(ready["brand"], ready["files"]), ready["size"], ready["fps_text"],
                         ready["look_at"], ready["left"], encoder], sort_keys=True, ensure_ascii=True)
    return "two-camera-%010.3f-%010.3f-%s.mp4" % (cut[0], cut[1], hashlib.sha1(recipe.encode("utf-8")).hexdigest()[:10])


# ----------------------------------------------------------------------------- the whole job
def make_clips(brand, recording, cut_list_path=None, only=None, dry_run=False, listen="auto", everyone_on_camera=False,
               anyway=False, layout=None, encoder="software", say=None, listener=None, **choices):
    """Make the cut list's clips from the two cameras. Returns the report (also written beside the
    clips, where the rough cut's report goes). `choices` are the same as for the full edit: who is
    on which camera, changed rules, picture height."""
    say = say or (lambda _t: None)
    ready = multicam.prepare(brand, recording, layout=layout or multicam.SOLO, use_saved_layout=False, **choices)
    brand, transcript, files = ready["brand"], ready["transcript"], ready["files"]
    if not ready["camera_of"]:
        raise VideoError("Nobody has said who is on which camera yet, so nobody can be cleared to appear in a clip.")
    policy = CameraPolicy(brand, transcript.speakers, ready["camera_of"], everyone_on_camera)
    policy.require_checkable()
    path = cut_list_path or output_dir(brand, recording, CUT_LIST_FILE)
    cl = cutlist.load(path)
    findings = cutlist.validate(cl, transcript, brand, recording=recording, policy=policy, check_files=False)
    findings += reference_findings(cl, brand, recording, files)
    if not cutlist.is_valid(findings):
        raise rough_cut.CutListProblems(findings)
    rules = gate.GateRules.for_brand(brand)

    # The cut list's times are transcript times, and so is everything below: each file's own
    # offset is applied at the last moment, by the renderer, never folded into the plan.
    in_transcript_time = cutlist.CutList(cl.title, dict(cl.reference, offset="0"), cl.bodies, cl.problems)
    planned, skipped = rough_cut.plan_clips(in_transcript_time, transcript, policy, only)
    lo, hi = ready["span"]
    listen_fn, silences, listened_with = _listeners(transcript, files["sound"], listen, listener, say)
    snapper = None
    stamps = [seg[k] for item in planned for seg in item["segments"] for k in ("start", "end")]
    if listen_fn is not None and stamps:
        snapper = rough_cut.Snapper(listen_fn, silences, hi)
        say("Finding the quoted words around %d cut points..." % len(stamps))
        snapper.prepare(stamps, say)
    resolve_cuts(planned, snapper, silences, lo, hi)
    alarm = rough_cut.snap_alarm(planned, listened_with)
    if alarm and not dry_run and not anyway:
        raise VideoError(alarm + " Nothing was rendered. With two cameras that points at the offsets: run sync "
                         "again. If you are sure they are right, run again with --anyway.")

    clip_rules = dict(ready["rules"], open_wide=0.0, close_wide=0.0)      # a clip has no opening and closing
    chosen = multicam.pick_encoder(encoder)
    out_dir = output_dir(brand, recording, "rough")
    if not dry_run:
        os.makedirs(os.path.join(out_dir, "parts"), exist_ok=True)
    width, height = ready["size"]
    report = {"schema": 1, "kind": "rough", "made_with": MADE_WITH, "brand": brand.id, "recording": recording,
              "source": NO_SINGLE_SOURCE, "source_duration": round(hi, 3),
              "shape": {"orientation": "vertical" if height > width else "horizontal" if width > height else "square",
                        "width": width, "height": height},
              "cut_list": locate(brand, path), "offset": 0.0, "speaker_check": policy.status,
              "on_camera": policy.on_camera(), "kept_out": policy.off_camera(), "listened_with": listened_with,
              "dry_run": bool(dry_run), "alarm": alarm, "layout": ready["layout"], "fps": ready["fps_text"],
              "look_at": ready["look_at"], "left": ready["left"], "encoder": chosen, "clips": []}
    report.update(multicam.files_record(brand, files))
    turns = transcript.turns()

    for item in planned:
        clip, segments = item["clip"], item["segments"]
        entry = {"id": clip.id, "file": clip.file_stem + ".mp4", "body": clip.body.key, "hook": clip.hook.number,
                 "title": clip.body.title, "hook_text": clip.hook.text, "on_screen_text": clip.body.on_screen_text,
                 "lower_third": clip.body.lower_third, "gate": clip.gate,
                 "disclaimer": rules.disclaimer if clip.gate == gate.HOLD else "",
                 "sign_off_by": rules.sign_off_by if clip.gate == gate.HOLD else "",
                 "signed_off": clip.body.signed_off, "segments": [], "pieces": []}
        say("%s  %s" % (clip.id, clip.body.title))
        already = 0.0
        for s in segments:
            shots = multicam.build_decisions(turns, ready["camera_of"], ready["layout"], s["cut"][0], s["cut"][1],
                                             clip_rules, ready["fps"])
            # What is reported is what was really cut: the stretch lands on whole frames, a hair
            # inside what was asked for, and later steps work out word times from these numbers.
            cut = [shots[0]["start"], shots[-1]["end"]]
            entry["segments"].append({
                "role": s["role"], "requested": [round(s["start"], 3), round(s["end"], 3)], "cut": cut,
                "duration": round(cut[1] - cut[0], 3), "walls": [s["wall_lo"], s["wall_hi"]],
                "snap": s["snap"], "starts_with": s["starts_with"], "ends_with": s["ends_with"],
                "part": "parts/" + part_name(cut, shots, ready, chosen), "shots": multicam.timeline(shots, already)})
            entry["pieces"].append(cut)
            already += cut[1] - cut[0]
            say("  %-4s %s - %s  ->  %s - %s   (start: %s, end: %s)   %s"
                % (s["role"], fmt_ts(s["start"]), fmt_ts(s["end"]), fmt_ts(cut[0], 2), fmt_ts(cut[1], 2),
                   s["snap"][0], s["snap"][1], " > ".join(x["show"] for x in shots)))
        expected = already
        entry["expected_duration"] = round(expected, 2)
        entry["shows"] = sorted({x["show"] for seg in entry["segments"] for x in seg["shots"]})
        if len(entry["shows"]) > 1 and entry["lower_third"]:
            # One line of text cannot sit under two faces. Shown under the wrong one, it is a
            # published statement about a real person that is false.
            entry["lower_third_left_off"] = entry["lower_third"]
            entry["lower_third"] = ""
            say("  The lower-third is left off: more than one picture appears in this clip and the line names one person.")
        if dry_run:
            entry["status"] = "planned"
        else:
            parts = []
            for seg in entry["segments"]:
                p = os.path.join(out_dir, *seg["part"].split("/"))
                if not usable_part(p, seg["shots"][-1]["out_end"] - seg["shots"][0]["out_start"]):
                    multicam.render_shots(files, seg["shots"], p, ready["size"], ready["fps_text"], ready["fps"], chosen,
                                          ready["look_at"], ready["left"], soften_sound=rough_cut.CROSSFADE)
                parts.append(p)
            final = os.path.join(out_dir, entry["file"])
            join_parts(parts, final, "join clip %s" % clip.id)
            actual = probe_duration(final)
            entry["actual_duration"] = round(actual, 2)
            entry["status"] = "ok" if abs(actual - expected) < 0.35 else "duration-mismatch"
            say("  -> %s (%.1fs)" % (entry["file"], actual))
        report["clips"].append(entry)
    for s in skipped:
        report["clips"].append(dict(s, file=""))
        say("%s  skipped: %s" % (s["id"], s["why"]))

    report["by_ear"] = ["%s (%s)" % (c["id"], seg["role"]) for c in report["clips"] for seg in c.get("segments", [])
                        if set(seg["snap"]) & {"silence", "pad"}]
    if not dry_run:
        report_path = os.path.join(out_dir, REPORT_FILE)
        write_json_atomic(report_path, merge_report(report_path, report, partial=bool(only)))
    return report
