"""multicam.py - two cameras on one conversation -> one video that shows whoever is talking.

WHAT IT NEEDS
  * two camera files of the same conversation, already lined up (`sync` measures how far apart
    they are and saves it with the recording);
  * the recording's transcript, with its voices labelled;
  * a person saying which voice is on which camera. That is never worked out from a file name or
    from the order people speak in. Get it backwards and every cut lands on the LISTENER, and the
    result still renders and still looks like a finished edit, so nothing downstream would notice.

HOW THE PICTURE IS CHOSEN
  The transcript says who speaks when. The rules below (they are data: RULES) turn that into a
  list of shots, each one camera A, camera B, or both side by side. Defaults are what makes it feel
  edited rather than switched:

    shortest_shot         no shot is shorter than this, so fast exchanges do not flicker
    interjection_*        a quick "yeah" or "right" does not steal the shot from the speaker
    cut_ahead             the cut lands a moment BEFORE the new speaker's first word; a cut that
                          lands exactly on the word looks late
    both_talking_*        when two people talk over each other, neither camera is right: show both
    back_and_forth_*      the same when the conversation changes hands several times in seconds
    wide_every            after a long stretch on one face, a short look at both, placed on the
                          widest pause nearby (0 turns it off)
    open_wide/close_wide  begin and end on both people, so the viewer knows who is in the room

  Layouts: `hybrid` uses all of that, `solo` only ever shows one person (use it for anything that
  will be cropped to a tall frame: a crop must never land between two people), `side-by-side`
  shows both throughout.

HOW IT IS RENDERED
  One pass of the video program. Three pictures are prepared for the whole length (camera A,
  camera B, both side by side), one selector chooses between them, and a small script of timed
  commands tells the selector when to switch. There is no cutting into pieces and joining, so the
  sound, which is copied through from ONE continuous source, cannot slip against the picture
  however many cuts there are. Each camera is read from its own place in its own file (that is
  what the measured offsets are for); the sound is read separately, so nudging a camera's picture
  never moves the sound.

  The list of shots is written as JSON next to the video. `dry_run` makes the list and renders
  nothing: it is far cheaper to disagree with an edit as text than to watch an hour of render.

All times are TRANSCRIPT time. A file's own time is transcript time plus that file's offset.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile

from smf.video.common import (Transcript, VideoError, as_brand, fmt_ts, locate, output_dir, probe_duration,
                              probe_shape, programs, read_json, resolve, run, safe_name, tokens_of, write_json_atomic)
from smf.brands import replace_patiently

A, B, BOTH = "A", "B", "both"
CAMERAS = (A, B)
HYBRID, SOLO, SIDE_BY_SIDE = "hybrid", "solo", "side-by-side"
LAYOUTS = (HYBRID, SOLO, SIDE_BY_SIDE)

SETUP_FILE = "setup.json"
EDIT_NAME = "two-camera-edit"
MAX_HEIGHT = 1080              # a larger master is scaled down unless a height is asked for

# The editorial rules. Seconds unless the name says otherwise. Change them per recording with
# `rules={...}`; an unknown name is an error rather than a setting that silently does nothing.
RULES = {
    "shortest_shot": 2.5,
    "shortest_turn": 0.6,               # talk shorter than this never takes the shot, whatever was said
    "interjection_longest": 1.4,        # talk this short...
    "interjection_most_words": 4,       # ...of this few words, all of them acknowledgements, is held through
    "cut_ahead": 0.15,
    "both_talking_shortest": 0.8,       # two cameras' voices overlapping for this long -> both
    "back_and_forth_changes": 5,        # this many changes of camera...
    "back_and_forth_window": 6.0,       # ...inside this long -> both
    "wide_tail": 1.0,                   # a wide shot outlasts what caused it by this much
    "wide_every": 45.0,                 # 0 = never cut away from a long stretch on one face
    "wide_length": 2.5,
    "wide_search": 8.0,                 # how far either side to look for a pause to cut away on
    "open_wide": 6.0,
    "close_wide": 6.0,
}

# Words that acknowledge without taking the floor. English; in another language the length rules
# (shortest_turn, shortest_shot) still stop the flicker, only less gracefully.
ACKNOWLEDGEMENTS = frozenset("""yes yeah yep yup no nope nah ok okay right sure true exactly absolutely
definitely totally really wow nice cool great good fine mm mmm mhm hmm hm uh huh oh ah aha got it gotcha
i see indeed agreed fair""".split())

WHY_SPEAKING = "speaking"
WHY_BOTH_TALKING = "both talking"
WHY_BACK_AND_FORTH = "quick back-and-forth"
WHY_LONG_STRETCH = "a look at both after a long stretch"
WHY_OPENING, WHY_CLOSING, WHY_LAYOUT = "opening", "closing", "the layout shows both throughout"

# Encoders, as data. The software one is on every computer and is the default. A hardware one is
# used only when this computer's video program lists it, a short trial encode really works, and
# the person has not asked for software.
SOFTWARE = "libx264"
ENCODERS = {
    "libx264": {"kind": "software", "args": ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]},
    "h264_videotoolbox": {"kind": "hardware", "platform": "darwin", "args": ["-c:v", "h264_videotoolbox"],
                          "kbps_at_1080p30": 6000},
}
COMMON_RATES = (("24000/1001", 23.976), ("24", 24.0), ("25", 25.0), ("30000/1001", 29.97), ("30", 30.0),
                ("50", 50.0), ("60000/1001", 59.94), ("60", 60.0))


# ----------------------------------------------------------------------------- the rules
def merge_rules(overrides=None):
    rules = dict(RULES)
    for key, value in (overrides or {}).items():
        if key not in RULES:
            raise VideoError("There is no editing rule called '%s'. The rules are: %s." % (key, ", ".join(sorted(RULES))))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise VideoError("The rule '%s' needs a number that is zero or more." % key)
        rules[key] = type(RULES[key])(value)
    return rules


def is_interjection(turn, rules):
    """Talk that must not take the shot: too short to be worth a cut, or a few words that only
    acknowledge what the other person is saying."""
    length = turn["end"] - turn["start"]
    if length < rules["shortest_turn"]:
        return True
    if length > rules["interjection_longest"]:
        return False
    words = tokens_of(turn.get("text", ""), keep_numbers=True)
    return len(words) <= rules["interjection_most_words"] and all(w in ACKNOWLEDGEMENTS for w in words)


# ----------------------------------------------------------------------------- who is on which camera
def _plain(name):
    return " ".join((name or "").split()).casefold()


def who_is_where(brand, transcript, speakers, off_camera=()):
    """{voice: "A" | "B" | None} for EVERY voice in the transcript. None means never shown.

    `speakers` is what a person said: {"Ava Lindqvist": "A", ...}. Every voice has to be accounted
    for. A voice the brand lists as off camera is accounted for already. Any other voice that
    nobody has placed is an error, never a guess: a wrong guess puts the listener on screen for
    the whole video and nothing afterwards can tell."""
    from smf.video import gate
    brand = as_brand(brand)
    voices = list(transcript.speakers)
    if not voices:
        raise VideoError("This transcript does not say who is speaking, so the picture cannot follow the speaker. "
                         "Transcribe the recording so each voice is labelled. (The side-by-side layout needs no "
                         "labels and still works.)")
    known = {_plain(v): v for v in voices}
    listing = ", ".join("'%s'" % v for v in voices)
    out = {}
    for name, camera in (speakers or {}).items():
        camera = str(camera or "").strip().upper()
        if camera not in CAMERAS:
            raise VideoError("'%s' was put on camera '%s', but the cameras are called A and B." % (name, camera))
        if _plain(name) not in known:
            raise VideoError("There is no voice called '%s' in this transcript. Its voices are: %s. Copy the name "
                             "exactly as the transcript has it." % (name, listing))
        out[known[_plain(name)]] = camera
    for name in off_camera or ():
        if _plain(name) not in known:
            raise VideoError("There is no voice called '%s' in this transcript. Its voices are: %s." % (name, listing))
        if known[_plain(name)] in out:
            raise VideoError("'%s' was said to be on camera %s and also off camera. Which is it?"
                             % (name, out[known[_plain(name)]]))
        out[known[_plain(name)]] = None
    policy = gate.SpeakerPolicy(brand, voices)
    unplaced = []
    for v in voices:
        if v in out:
            continue
        if policy.is_host(v):
            out[v] = None                         # the brand already says this person stays off camera
        else:
            unplaced.append(v)
    if unplaced:
        raise VideoError("Nobody has said which camera %s on. Say it for each voice, for example "
                         "--speaker \"%s=A\", or --off-camera \"%s\" for a voice that is on neither camera. This is "
                         "never worked out from a name or a file name: a wrong guess would show the listener "
                         "instead of the speaker for the whole video."
                         % (" and ".join("'%s'" % v for v in unplaced) + (" is" if len(unplaced) == 1 else " are"),
                            unplaced[0], unplaced[0]))
    if not any(out.values()):
        raise VideoError("Every voice in this recording is off camera, so there is nobody to cut to.")
    out[""] = None                                # words nobody's voice was matched to never take the shot
    return out


# ----------------------------------------------------------------------------- the list of shots
def _shot(start, end, show, why):
    return {"start": start, "end": end, "show": show, "why": why}


def _settle(shots, shortest, start, end, fps):
    """Tidy a list of shots: on whole frames, no gaps, neighbours showing the same thing joined,
    and nothing shorter than `shortest`. A short shot is taken over by the one before it; when it
    is the very first shot, by the one after."""
    def snap(t):
        return round(round(t * fps) / fps, 4)

    def join(items):
        out = []
        for s in items:
            if out and out[-1]["show"] == s["show"]:
                out[-1]["end"] = s["end"]
            else:
                out.append(dict(s))
        return out

    kept = []
    for s in sorted(shots, key=lambda s: (s["start"], s["end"])):
        a, z = snap(min(max(s["start"], start), end)), snap(min(max(s["end"], start), end))
        if z > a:
            kept.append(_shot(a, z, s["show"], s["why"]))
    if not kept:
        return []
    kept = join(kept)
    for i in range(len(kept) - 1):
        kept[i]["end"] = kept[i + 1]["start"]                  # a shot runs until the next one begins
    kept[0]["start"], kept[-1]["end"] = snap(start), snap(end)
    kept = join([s for s in kept if s["end"] > s["start"]])
    floor = shortest - 0.5 / fps
    while len(kept) > 1:
        short = next((i for i, s in enumerate(kept) if s["end"] - s["start"] < floor), None)
        if short is None:
            break
        if short == 0:
            kept[1]["start"] = kept[0]["start"]
            del kept[0]
        else:
            kept[short - 1]["end"] = kept[short]["end"]
            del kept[short]
        kept = join(kept)
    return kept


def _intervals(turns):
    out = []
    for t in sorted(turns, key=lambda t: t["start"]):
        if out and t["start"] <= out[-1][1]:
            out[-1][1] = max(out[-1][1], t["end"])
        else:
            out.append([t["start"], t["end"]])
    return out


def _widest_pause(turns, near, reach):
    """The middle of the longest silence between turns within `reach` of `near`: a natural place
    to cut away. None when there is no pause in reach."""
    best, best_gap = None, 0.0
    for before, after in zip(turns, turns[1:]):
        gap = after["start"] - before["end"]
        middle = (before["end"] + after["start"]) / 2.0
        if gap > best_gap and abs(middle - near) <= reach:
            best, best_gap = middle, gap
    return best


def _wide_moments(seen, taking, shots, camera_of, rules, start, end):
    """[(from, to, why)]: the stretches a hybrid edit shows both people for."""
    wides = []
    # two people talking over each other
    by_camera = {c: _intervals([t for t in taking if camera_of[t["speaker"]] == c]) for c in CAMERAS}
    for a0, a1 in by_camera[A]:
        for b0, b1 in by_camera[B]:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi - lo >= rules["both_talking_shortest"]:
                wides.append((lo - rules["cut_ahead"], hi + rules["wide_tail"], WHY_BOTH_TALKING))
    # the conversation changing hands quickly
    changes = [t["start"] for prev, t in zip(seen, seen[1:])
               if camera_of[prev["speaker"]] != camera_of[t["speaker"]]]
    i = 0
    while i < len(changes) and rules["back_and_forth_changes"] > 0:
        j = i
        while j < len(changes) and changes[j] - changes[i] <= rules["back_and_forth_window"]:
            j += 1
        if j - i >= rules["back_and_forth_changes"]:
            wides.append((changes[i] - rules["cut_ahead"], changes[j - 1] + rules["wide_tail"], WHY_BACK_AND_FORTH))
            i = j
        else:
            i += 1
    # a look at both after a long stretch on one face
    if rules["wide_every"] > 0 and rules["wide_length"] > 0:
        for s in shots:
            mark = s["start"] + rules["wide_every"]
            while s["end"] - mark >= 2 * rules["wide_length"]:
                at = _widest_pause(seen, mark, rules["wide_search"])
                at = mark if at is None else at
                wides.append((at, at + rules["wide_length"], WHY_LONG_STRETCH))
                mark += rules["wide_every"]
    # begin and end on both people, when the video is long enough for that not to be most of it
    if end - start >= 2 * (rules["open_wide"] + rules["close_wide"]) + rules["shortest_shot"]:
        if rules["open_wide"] > 0:
            wides.append((start, start + rules["open_wide"], WHY_OPENING))
        if rules["close_wide"] > 0:
            wides.append((end - rules["close_wide"], end, WHY_CLOSING))
    out = []
    for lo, hi, why in wides:
        lo, hi = max(start, lo), min(end, hi)
        if hi - lo < rules["shortest_shot"]:                       # long enough to read as a shot
            hi = min(end, lo + rules["shortest_shot"])
            lo = max(start, hi - rules["shortest_shot"])
        if hi > lo:
            out.append((lo, hi, why))
    return sorted(out)


def _punch(shots, wides):
    """Lay the wide stretches over the one-person timeline."""
    for lo, hi, why in wides:
        cut = []
        for s in shots:
            if s["end"] <= lo or s["start"] >= hi:
                cut.append(s)
                continue
            if s["start"] < lo:
                cut.append(dict(s, end=lo))
            if s["end"] > hi:
                cut.append(dict(s, start=hi))
        cut.append(_shot(lo, hi, BOTH, why))
        shots = sorted(cut, key=lambda s: (s["start"], s["end"]))
    return shots


def _when_nobody_takes_the_shot(seen, turns, camera_of, start, end, layout):
    """The range holds no talk long enough to cut to (a one-word hook, a silence). Hold on whoever
    talks most inside it; failing that, whoever spoke nearest to it."""
    totals = {}
    for t in seen:
        cam = camera_of[t["speaker"]]
        totals[cam] = totals.get(cam, 0.0) + min(t["end"], end) - max(t["start"], start)
    if totals:
        return max(sorted(totals), key=lambda c: totals[c])
    nearby = [t for t in turns if camera_of.get(t["speaker"]) in CAMERAS]
    if nearby:
        nearest = min(nearby, key=lambda t: (max(t["start"] - end, start - t["end"], 0.0), t["start"]))
        return camera_of[nearest["speaker"]]
    if layout == SOLO:
        raise VideoError("Nobody who is on a camera speaks in this recording, so there is no one to show.")
    return BOTH


def build_decisions(turns, camera_of, layout=HYBRID, start=0.0, end=None, rules=None, fps=30.0):
    """The list of shots for [start, end]: [{"start", "end", "show": "A"|"B"|"both", "why"}].

    Nothing here touches a file, and the same input always gives the same list. `camera_of` must
    hold every voice in `turns` (None = never shown); a voice it has never heard of is an error."""
    rules = merge_rules(rules)
    if layout not in LAYOUTS:
        raise VideoError("'%s' is not a layout. The layouts are: %s." % (layout, ", ".join(LAYOUTS)))
    turns = sorted(turns, key=lambda t: (t["start"], t["end"], t.get("speaker") or ""))
    if end is None:
        end = max([t["end"] for t in turns] or [start])
    # The edges of the range go on whole frames by moving INWARD. Rounding to the nearest frame can
    # put the start a hundredth of a second before the first moment both cameras cover.
    start = math.ceil(start * fps - 1e-6) / fps
    end = math.floor(end * fps + 1e-6) / fps
    if end - start < 1.0 / fps:
        raise VideoError("There is nothing to show between %s and %s." % (fmt_ts(start), fmt_ts(end)))
    if layout == SIDE_BY_SIDE:
        return _settle([_shot(start, end, BOTH, WHY_LAYOUT)], 0.0, start, end, fps)
    strangers = sorted({t.get("speaker") or "" for t in turns} - set(camera_of))
    if strangers:
        raise VideoError("Nobody has said which camera '%s' is on, so the picture cannot be chosen. Nothing is "
                         "guessed from a name." % "', '".join(strangers))
    seen = [t for t in turns if camera_of[t.get("speaker") or ""] in CAMERAS and t["end"] > start and t["start"] < end]
    taking = [t for t in seen if not is_interjection(t, rules)]
    shots = [_shot(max(start, t["start"] - rules["cut_ahead"]), end, camera_of[t["speaker"]], WHY_SPEAKING)
             for t in taking]
    if not shots:
        shots = [_shot(start, end, _when_nobody_takes_the_shot(seen, turns, camera_of, start, end, layout),
                       WHY_SPEAKING)]
    shots = _settle(shots, rules["shortest_shot"], start, end, fps)
    if layout == HYBRID:
        wides = _wide_moments(seen, taking, shots, camera_of, rules, start, end)
        shots = _settle(_punch(shots, wides), rules["shortest_shot"], start, end, fps)
    return shots


def summarise(shots):
    """Numbers a person can judge an edit by without watching it."""
    if not shots:
        return {"shots": 0}
    total = shots[-1]["end"] - shots[0]["start"]
    lengths = sorted(s["end"] - s["start"] for s in shots)
    on_screen, reasons = {}, {}
    for s in shots:
        on_screen[s["show"]] = on_screen.get(s["show"], 0.0) + s["end"] - s["start"]
        if s["show"] == BOTH:
            reasons[s["why"]] = reasons.get(s["why"], 0) + 1
    return {"shots": len(shots), "seconds": round(total, 2),
            "cuts_per_minute": round((len(shots) - 1) / (total / 60.0), 1) if total > 0 else 0.0,
            "typical_shot": round(lengths[len(lengths) // 2], 1), "shortest_shot": round(lengths[0], 2),
            "share_of_screen": {k: round(v / total, 3) for k, v in sorted(on_screen.items())},
            "why_both": dict(sorted(reasons.items()))}


def describe(decisions, limit=40):
    """The decisions as lines of text, for a person to read before anything is rendered."""
    shots, s = decisions["shots"], decisions["summary"]
    names = {A: "camera A", B: "camera B", BOTH: "both"}
    lines = ["%d shots over %s: about %.1f cuts a minute, a typical shot is %.1f seconds."
             % (s["shots"], fmt_ts(s["seconds"], 0), s["cuts_per_minute"], s["typical_shot"])]
    for show, share in s["share_of_screen"].items():
        lines.append("  %-9s on screen %2.0f%% of the time" % (names[show], share * 100))
    if s["why_both"]:
        lines.append("  both people are shown for: " + ", ".join("%s (%d)" % kv for kv in s["why_both"].items()))
    lines.append("")
    for shot in shots[:limit]:
        lines.append("  %s - %s  %-9s %s" % (fmt_ts(shot["start"]), fmt_ts(shot["end"]), names[shot["show"]], shot["why"]))
    if len(shots) > limit:
        lines.append("  ... and %d more shots (all of them are in the saved list)" % (len(shots) - limit))
    return lines


# ----------------------------------------------------------------------------- the saved setup
def multicam_dir(brand, recording, *parts):
    return output_dir(brand, recording, "multicam", *parts)


def load_setup(brand, recording):
    brand = as_brand(brand)
    path = multicam_dir(brand, recording, SETUP_FILE)
    if not os.path.isfile(path):
        raise VideoError("The two cameras for '%s' have not been lined up yet. Run sync first, naming the two "
                         "camera files; it measures how far apart they were started." % recording)
    setup = read_json(path, "The two-camera setup for '%s'" % recording)
    if setup.get("brand") != brand.id or setup.get("recording") != recording:
        raise VideoError("The saved two-camera setup belongs to a different brand or recording (%s, '%s'). Run sync "
                         "again for this one." % (setup.get("brand"), setup.get("recording")))
    return setup


def save_setup(brand, recording, setup):
    brand = as_brand(brand)
    setup = dict(setup, schema=1, kind="two-camera setup", brand=brand.id, recording=safe_name(recording))
    write_json_atomic(multicam_dir(brand, recording, SETUP_FILE), setup)
    return setup


def files_of(brand, recording, setup):
    """{"A": {"path", "offset", "nudge"}, "B": {...}, "sound": {"path", "offset"}} with real paths."""
    brand = as_brand(brand)
    out = {}
    for cam in CAMERAS:
        entry = (setup.get("cameras") or {}).get(cam) or {}
        path = resolve(brand, recording, entry.get("file"))
        if not path:
            raise VideoError("Camera %s's file ('%s') cannot be found any more. Put it back in the recording's "
                             "folder, or run sync again with the file's new name." % (cam, entry.get("file") or "none"))
        out[cam] = {"path": path, "offset": float(entry.get("offset") or 0.0), "nudge": float(entry.get("nudge") or 0.0)}
    sound = setup.get("sound") or {"from": A}
    if sound.get("from") in CAMERAS:
        out["sound"] = {"path": out[sound["from"]]["path"], "offset": out[sound["from"]]["offset"]}
    else:
        path = resolve(brand, recording, sound.get("file"))
        if not path:
            raise VideoError("The sound file ('%s') cannot be found any more. Put it back, or run sync again."
                             % (sound.get("file") or "none"))
        out["sound"] = {"path": path, "offset": float(sound.get("offset") or 0.0)}
    return out


def shared_span(files):
    """The stretch of TRANSCRIPT time during which both cameras and the sound were all running."""
    lo, hi = 0.0, None
    for key, f in files.items():
        shift = f["offset"] - f.get("nudge", 0.0)
        lo = max(lo, -shift)
        top = probe_duration(f["path"]) - shift
        hi = top if hi is None else min(hi, top)
    if hi is None or hi - lo < 1.0:
        raise VideoError("The two cameras and the sound never all run at the same time, going by the saved offsets. "
                         "Run sync again; if it gives the same answer, these files are not the same conversation.")
    return lo, hi


# ----------------------------------------------------------------------------- lining the files up
def line_up(brand, recording, camera_a, camera_b, sound=A, given=None, nudge=None, say=None):
    """Measure where each file sits against the transcript's clock, and save it as the setup.

    sound   "A" or "B" (use that camera's own sound in the finished video), or a separate sound
            file recorded at the same time. Whichever it is becomes the anchor: it is lined up
            against the transcript first, and each camera is then lined up against IT, sound
            against sound.
    given   {"A": seconds, "B": seconds}: how far that camera is from the anchor, when a person
            already knows (camera_time = anchor_time + seconds). A number somebody typed is still
            checked by listening whenever that camera has any sound at all.
    nudge   {"A": seconds, "B": seconds}: delay that camera's PICTURE only, for a camera whose
            lips run a little early. The sound is never moved."""
    from smf.video import sync
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    transcript = Transcript.load(brand, recording)
    given, nudge = dict(given or {}), dict(nudge or {})
    paths = {}
    for cam, written in ((A, camera_a), (B, camera_b)):
        path = resolve(brand, recording, written)
        if not path:
            raise VideoError("Camera %s's file ('%s') cannot be found. Put it in the recording's folder, or give its "
                             "full location." % (cam, written or "none named"))
        if probe_shape(path)["orientation"] == "unknown":
            raise VideoError("'%s' has no picture in it, so it cannot be camera %s." % (os.path.basename(path), cam))
        paths[cam] = path
    if sync.same_file(paths[A], paths[B]):
        raise VideoError("Camera A and camera B are the same file. Name the two different camera files.")
    sound_key = str(sound or A).strip()
    if sound_key.upper() in CAMERAS:
        sound_key = sound_key.upper()
        anchor = paths[sound_key]
    else:
        anchor = resolve(brand, recording, sound_key)
        if not anchor:
            raise VideoError("The sound file ('%s') cannot be found. Put it in the recording's folder, or give its "
                             "full location." % sound_key)
        sound_key = "file"

    transcribed = resolve(brand, recording, (transcript.source or {}).get("media"))
    say("Lining '%s' up with the transcript..." % os.path.basename(anchor))
    base = sync.measure_transcript_offset(anchor, transcript, transcribed, say)
    setup = {"cameras": {}, "sound": {"from": sound_key}}
    if sound_key == "file":
        setup["sound"].update({"file": locate(brand, anchor), "offset": base.seconds, "how": base.as_dict()})
    for cam in CAMERAS:
        if paths[cam] == anchor:
            found = sync.Offset(seconds=0.0, confidence=1.0, method="same-file", checked=True)
        elif cam in given:
            found = sync.Offset(seconds=round(float(given[cam]), 3), method="given")
            try:
                check = sync.check_offset(anchor, paths[cam], found.seconds)
            except sync.SyncRefused:
                check = None                                   # that camera has no sound to check against
            if check is None:
                found.notes.append("This number was typed by a person and could not be checked, because the "
                                   "camera has no sound.")
            elif not check["ok"]:
                raise sync.SyncRefused("Camera %s was said to be %+.3f seconds from the sound, but that does not "
                                       "hold up: %s. Nothing was saved." % (cam, found.seconds, check["why"]))
            else:
                found.checked, found.residual, found.confidence = True, check["residual"], 1.0
        else:
            say("Lining camera %s up with '%s' by sound..." % (cam, os.path.basename(anchor)))
            found = sync.measure_offset(anchor, paths[cam], say)
        setup["cameras"][cam] = {"file": locate(brand, paths[cam]), "offset": round(base.seconds + found.seconds, 3),
                                 "from_the_sound": found.seconds, "nudge": round(float(nudge.get(cam) or 0.0), 3),
                                 "how": found.as_dict()}
    setup["transcript"] = {"offset_of_the_sound": base.seconds, "how": base.as_dict()}
    try:
        before = load_setup(brand, recording)
    except VideoError:
        before = {}
    same_cameras = all(((before.get("cameras") or {}).get(c) or {}).get("file") == setup["cameras"][c]["file"]
                       for c in CAMERAS)
    if same_cameras:                        # who sits where only survives when the camera files are the same ones
        for key in ("speakers", "off_camera", "layout", "rules", "look_at", "left"):
            if before.get(key):
                setup[key] = before[key]
    return save_setup(brand, recording, setup)


# ----------------------------------------------------------------------------- picture size, speed, encoder
def frame_rate(path):
    """(text for the video program, frames a second). Rates a camera really uses are kept exact;
    an odd average (a phone that drops frames) is rounded to the nearest real one."""
    _ff, fp = programs()
    r = run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", path], "read the frame rate of '%s'" % os.path.basename(path))
    num, _, den = r.stdout.strip().partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    if not 5.0 <= fps <= 240.0:
        return "30", 30.0
    text, value = min(COMMON_RATES, key=lambda c: abs(c[1] - fps))
    if abs(value - fps) / value <= 0.015:
        return text, value
    whole = int(min(60, max(10, round(fps))))
    return str(whole), float(whole)


def picture_size(path, height=0):
    """(width, height) of the finished video, from camera A as it is SHOWN. Both are multiples of
    four, so each half of a side-by-side picture is still an even number of pixels."""
    shape = probe_shape(path)
    if shape["orientation"] == "unknown":
        raise VideoError("'%s' has no picture in it, so it cannot be one of the cameras." % os.path.basename(path))
    h = int(height) if height else min(shape["height"], MAX_HEIGHT)
    w = shape["width"] * h / float(shape["height"])
    return max(16, int(round(w / 4.0)) * 4), max(16, int(round(h / 4.0)) * 4)


_listed = {}
_proven = {}


def _listed_encoders():
    if "text" not in _listed:
        ff, _fp = programs()
        _listed["text"] = run([ff, "-hide_banner", "-encoders"], "ask the video program what it can encode").stdout
    return _listed["text"]


def _really_works(name):
    """Being listed is not the same as working: a build can list an encoder for hardware this
    computer does not have. So a quarter of a second of nothing is actually encoded with it."""
    if name not in _proven:
        ff, _fp = programs()
        try:
            r = subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=0.25"]
                               + ENCODERS[name]["args"] + ["-b:v", "800k", "-pix_fmt", "yuv420p", "-f", "null", "-"],
                               capture_output=True)
            _proven[name] = r.returncode == 0
        except OSError:
            _proven[name] = False
    return _proven[name]


def pick_encoder(asked="auto", listed=None, works=None, platform=None):
    """Which encoder to use. `asked` is auto, software or hardware.

    auto      the software encoder, unless a hardware one is listed by the video program, passes a
              trial, and belongs to this kind of computer
    software  always the software encoder
    hardware  a hardware encoder, or a plain refusal"""
    asked = (asked or "auto").strip().lower()
    if asked not in ("auto", "software", "hardware"):
        raise VideoError("The encoder can be auto, software or hardware, not '%s'." % asked)
    if asked == "software":
        return SOFTWARE
    listed = _listed_encoders() if listed is None else listed
    works = works or _really_works
    platform = platform or sys.platform
    for name, info in ENCODERS.items():
        if info["kind"] != "hardware" or not platform.startswith(info["platform"]):
            continue
        if any(line.split()[1:2] == [name] for line in listed.splitlines()) and works(name):
            return name
    if asked == "hardware":
        raise VideoError("This computer has no hardware video encoder the Factory can use. Leave the encoder on "
                         "auto: the software one works everywhere, it is only slower.")
    return SOFTWARE


def encoder_args(name, size, fps):
    info = ENCODERS[name]
    args = list(info["args"])
    if info["kind"] == "hardware":
        kbps = info["kbps_at_1080p30"] * (size[0] * size[1]) / (1920.0 * 1080.0) * (fps / 30.0)
        args += ["-b:v", "%dk" % max(800, int(kbps))]
    return args + ["-pix_fmt", "yuv420p"]


# ----------------------------------------------------------------------------- rendering
def _fit(size):
    """Fill the frame without stretching anybody: scale until it covers, then trim the overhang."""
    return "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1" % (size[0], size[1], size[0], size[1])


def _half(size, look_at):
    """The crop that gives one person their half of a side-by-side picture. `look_at` is where
    they sit across their own frame (0 = one edge, 0.5 = the middle, 1 = the other edge)."""
    w, h = size
    look_at = min(1.0, max(0.0, float(look_at)))
    if w >= h:
        half = w // 2
        x = int(min(max(look_at * w - half / 2.0, 0), w - half)) // 2 * 2
        return "crop=%d:%d:%d:0" % (half, h, x)
    half = h // 2
    y = int(min(max(look_at * h - half / 2.0, 0), h - half)) // 2 * 2
    return "crop=%d:%d:0:%d" % (w, half, y)


def three_pictures(size, fps_text, look_at=None, left=A):
    """The part of the filter graph that prepares camera A, camera B and both-side-by-side from
    inputs 0 and 1, as [pa], [pb] and [pboth]. The checker builds its comparison pictures with this
    same function, so what it compares against is what the renderer would have drawn."""
    look_at = look_at or {}
    first, second = (A, B) if left != B else (B, A)
    tag = {A: "a2", B: "b2"}
    stack = "hstack" if size[0] >= size[1] else "vstack"
    return (
        "[0:v]fps=%s:start_time=0,%s,format=yuv420p,split=2[pa][a2];"
        "[1:v]fps=%s:start_time=0,%s,format=yuv420p,split=2[pb][b2];"
        "[a2]%s[ha];[b2]%s[hb];[h%s][h%s]%s=inputs=2,setsar=1[pboth]"
        % (fps_text, _fit(size), fps_text, _fit(size), _half(size, look_at.get(A, 0.5)), _half(size, look_at.get(B, 0.5)),
           tag[first][0], tag[second][0], stack))


def seek_of(entry, t):
    """Where transcript time `t` is inside one file. A nudge delays that camera's PICTURE only."""
    return t + entry["offset"] - entry.get("nudge", 0.0)


def _watch(cmd, total, say, cwd, what):
    """Run a long render, saying how far along it is every tenth of the way."""
    with tempfile.TemporaryFile() as complaints:
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=complaints, text=True,
                                    encoding="utf-8", errors="replace")
        except OSError as e:
            raise VideoError("Could not %s: the video program would not start (%s)." % (what, e))
        said = 0
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit() and total > 0:
                tenth = int(10 * (int(value) / 1e6) / total)
                if 0 < tenth < 10 and tenth > said:
                    said = tenth
                    say("  %d%% rendered" % (tenth * 10))
        proc.stdout.close()
        if proc.wait() != 0:
            complaints.seek(0)
            last = [ln for ln in complaints.read().decode("utf-8", "replace").strip().splitlines() if ln.strip()][-2:]
            raise VideoError("Could not %s. The video program said: %s" % (what, " / ".join(last) or "nothing"))


def render_shots(files, shots, out_path, size, fps_text, fps, encoder=SOFTWARE, look_at=None, left=A,
                 soften_sound=0.0, say=None):
    """Render one continuous stretch, switching pictures as `shots` says. One pass, one encode.

    The timed commands go in a small file of their own. It is handed to the video program by its
    bare name, from a throwaway folder the program is started in, so no folder name (however many
    spaces, apostrophes or accents it has) is ever written inside the filter description."""
    say = say or (lambda _t: None)
    ff, _fp = programs()
    start, end = shots[0]["start"], shots[-1]["end"]
    length = end - start
    order = {A: 0, B: 1, BOTH: 2}
    graph = three_pictures(size, fps_text, look_at, left)
    switches = ["%.4f streamselect map %d;" % (s["start"] - start, order[s["show"]]) for s in shots[1:]]
    # Time zero is where the file was asked to start, NOT wherever its first sample happens to be.
    # A sound track often begins a few hundredths of a second (sometimes far more) after the
    # file does. Resetting its clock to its own first sample would slide all of the sound early by
    # that gap; padding the gap with silence keeps it where the measured offsets say it is. The
    # pictures are pinned to zero the same way (start_time=0, in three_pictures).
    sound = "[2:a]aresample=48000:async=1:first_pts=0"
    if soften_sound > 0:
        sound += ",afade=t=in:st=0:d=%s,afade=t=out:st=%.3f:d=%s" % (soften_sound, max(0.0, length - soften_sound),
                                                                     soften_sound)
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    working = os.path.splitext(out_path)[0] + ".working" + os.path.splitext(out_path)[1]
    with tempfile.TemporaryDirectory(prefix="smf-switch-") as scratch:
        if switches:
            with open(os.path.join(scratch, "cuts.txt"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(switches) + "\n")
            # The commands ride on the side-by-side picture, on purpose. That picture is built FROM
            # the other two, so for any moment it is the last of the three to reach the selector.
            # A command carried by a picture that arrives early would flip the selector while
            # frames for earlier moments were still queued behind it, and the cut would land early.
            graph += ";[pboth]sendcmd=f=cuts.txt[pboth_timed];[pa][pb][pboth_timed]"
        else:
            graph += ";[pa][pb][pboth]"
        graph += "streamselect=inputs=3:map=%d[v];%s[s]" % (order[shots[0]["show"]], sound)
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]
        for key in (A, B, "sound"):
            seek = seek_of(files[key], start)
            if seek < -0.001:
                # Quietly starting that file at its beginning instead would put it out of step with
                # the other two for the whole render, and nothing afterwards would say so.
                raise VideoError("This stretch begins %s into the conversation, which is before %s was recording. "
                                 "Begin it %.1f seconds later." % (fmt_ts(start), "the sound" if key == "sound"
                                                                   else "camera " + key, -seek))
            cmd += ["-ss", "%.4f" % max(0.0, seek), "-t", "%.4f" % length, "-i", os.path.abspath(files[key]["path"])]
        cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[s]"] + encoder_args(encoder, size, fps)
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-t", "%.4f" % length, "-movflags", "+faststart", working]
        try:
            _watch(cmd, length, say, scratch, "render the two-camera video")
            replace_patiently(working, out_path)                       # only a finished file ever gets the real name
        finally:
            if os.path.exists(working):
                os.remove(working)
    return out_path


# ----------------------------------------------------------------------------- the whole job
def prepare(brand, recording, speakers=None, off_camera=None, layout=None, rules=None, look_at=None, left=None,
            height=0, use_saved_layout=True):
    """Everything an edit of this recording needs, checked: the transcript, the saved setup with
    what the person just said laid over it, the real files, who is on which camera, the picture's
    size and speed, and the stretch of the conversation that both cameras and the sound cover."""
    brand = as_brand(brand)
    transcript = Transcript.load(brand, recording)
    setup = load_setup(brand, recording)
    chosen = {"speakers": speakers, "off_camera": off_camera, "rules": rules, "look_at": look_at, "left": left}
    for key, value in chosen.items():
        if value:
            setup[key] = value
    # The full edit remembers its layout. Clips choose their own each time and never change it.
    layout = layout or (setup.get("layout") if use_saved_layout else None) or HYBRID
    if layout not in LAYOUTS:
        raise VideoError("'%s' is not a layout. The layouts are: %s." % (layout, ", ".join(LAYOUTS)))
    if (setup.get("left") or A) not in CAMERAS:
        raise VideoError("The left-hand side can be camera A or camera B, not '%s'." % setup.get("left"))
    rules_now = merge_rules(setup.get("rules"))
    files = files_of(brand, recording, setup)
    camera_of = {}
    if layout != SIDE_BY_SIDE or setup.get("speakers"):
        if not setup.get("speakers"):
            raise VideoError("Nobody has said who is on which camera yet. Say it once for this recording, for "
                             "example --speaker \"%s=A\". Its voices are: %s."
                             % ((transcript.speakers or ["Their Name"])[0], ", ".join(transcript.speakers) or "not labelled"))
        camera_of = who_is_where(brand, transcript, setup["speakers"], setup.get("off_camera") or ())
    fps_text, fps = frame_rate(files[A]["path"])
    return {"brand": brand, "recording": recording, "transcript": transcript, "setup": setup, "layout": layout,
            "rules": rules_now, "files": files, "camera_of": camera_of, "span": shared_span(files),
            "size": picture_size(files[A]["path"], height), "fps_text": fps_text, "fps": fps,
            "look_at": setup.get("look_at") or {}, "left": setup.get("left") or A}


def files_record(brand, files):
    """The files and offsets an edit was made with, as they are written into its report."""
    return {"cameras": {c: {"file": locate(brand, files[c]["path"]), "offset": files[c]["offset"],
                            "nudge": files[c]["nudge"]} for c in CAMERAS},
            "sound": {"file": locate(brand, files["sound"]["path"]), "offset": files["sound"]["offset"]}}


def files_from_record(brand, recording, record):
    """The reverse: real paths from a report, so a check uses what the render used, not whatever
    the setup says today."""
    out = {}
    for key, entry in list((record.get("cameras") or {}).items()) + [("sound", record.get("sound") or {})]:
        path = resolve(brand, recording, entry.get("file"))
        if not path:
            raise VideoError("'%s', which this video was made from, cannot be found any more, so the video cannot "
                             "be checked against it." % (entry.get("file") or "a camera file"))
        out[key] = {"path": path, "offset": float(entry.get("offset") or 0.0), "nudge": float(entry.get("nudge") or 0.0)}
    if set(out) != {A, B, "sound"}:
        raise VideoError("The report does not say which two cameras and which sound this video was made from.")
    return out


def plan(brand, recording, start=None, end=None, remember=False, **choices):
    """Work out the edit for one recording. Returns (decisions, files). Renders nothing.

    What a person says here (who is on which camera, the layout, changed rules) replaces what was
    saved before; what they leave out is taken from the saved setup. `remember=True` saves it."""
    ready = prepare(brand, recording, **choices)
    brand, files, layout, camera_of = ready["brand"], ready["files"], ready["layout"], ready["camera_of"]
    lo, hi = ready["span"]
    first = lo if start is None else max(lo, float(start))
    last = hi if end is None else min(hi, float(end))
    if last - first < 1.0:
        raise VideoError("Between %s and %s there is less than a second that both cameras and the sound all cover."
                         % (fmt_ts(first), fmt_ts(last)))
    shots = build_decisions(ready["transcript"].turns(), camera_of, layout, first, last, ready["rules"], ready["fps"])
    notes = []
    if start is None and lo > 0.5:
        notes.append("The edit begins %s into the conversation: that is the first moment both cameras and the sound "
                     "were all recording." % fmt_ts(lo))
    other = probe_shape(files[B]["path"])
    if other["orientation"] not in ("unknown", probe_shape(files[A]["path"])["orientation"]):
        notes.append("Camera B is %s and camera A is not, so camera B's picture is trimmed to fit camera A's shape."
                     % other["orientation"])
    if layout != SIDE_BY_SIDE and len({c for c in camera_of.values() if c}) == 1:
        notes.append("Everyone who speaks is on the same camera, so the other camera is only seen in the shots "
                     "that show both.")
    decisions = {
        "schema": 1, "kind": "two-camera edit", "brand": brand.id, "recording": recording, "layout": layout,
        "range": [shots[0]["start"], shots[-1]["end"]], "duration": round(shots[-1]["end"] - shots[0]["start"], 4),
        "size": list(ready["size"]), "fps": ready["fps_text"]}
    decisions.update(files_record(brand, files))
    decisions.update({
        "speakers": {k: v for k, v in sorted(camera_of.items()) if k and v},
        "off_camera": sorted(k for k, v in camera_of.items() if k and not v),
        "rules": ready["rules"], "look_at": ready["look_at"], "left": ready["left"],
        "shots": timeline(shots), "summary": summarise(shots), "notes": notes})
    if remember:
        save_setup(brand, recording, dict(ready["setup"], layout=layout))
    return decisions, files


def timeline(shots, already=0.0):
    """The shots with their place in the FINISHED video added (out_start, out_end), given that
    `already` seconds of finished video come before them."""
    first = shots[0]["start"]
    return [dict(s, out_start=round(already + s["start"] - first, 4), out_end=round(already + s["end"] - first, 4))
            for s in shots]


def render(brand, recording, dry_run=False, encoder="auto", name=EDIT_NAME, say=None, **choices):
    """Make the two-camera edit. Returns the decisions, which are also saved next to the video.
    A dry run returns the same decisions and writes nothing at all."""
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    decisions, files = plan(brand, recording, remember=not dry_run, **choices)
    decisions["dry_run"] = bool(dry_run)
    if dry_run:
        return decisions
    name = safe_name(name, "video")
    out_path = multicam_dir(brand, recording, name + ".mp4")
    chosen = pick_encoder(encoder)
    say("Rendering %s of video with the %s encoder. On most computers this takes about as long as the video "
        "itself; a hardware encoder is several times quicker." % (fmt_ts(decisions["duration"], 0), ENCODERS[chosen]["kind"]))
    fps = dict(COMMON_RATES).get(decisions["fps"]) or float(decisions["fps"])
    render_shots(files, decisions["shots"], out_path, tuple(decisions["size"]), decisions["fps"], fps, chosen,
                 decisions["look_at"], decisions["left"], say=say)
    actual = probe_duration(out_path)
    decisions.update({"encoder": chosen, "output": locate(brand, out_path), "actual_duration": round(actual, 3),
                      "status": "ok" if abs(actual - decisions["duration"]) <= 0.5 else "duration-mismatch"})
    write_json_atomic(decisions_path(out_path), decisions)
    if decisions["status"] != "ok":
        raise VideoError("The video came out %s long but the plan was %s, so do not use it. Run it again; if it "
                         "happens twice, run the doctor." % (fmt_ts(actual), fmt_ts(decisions["duration"])))
    return decisions


def decisions_path(video_path):
    return os.path.splitext(video_path)[0] + ".edit-decisions.json"
