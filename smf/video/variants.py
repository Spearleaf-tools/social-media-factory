"""variants.py - one finished clip in, several versions out that look and sound different.

A brand with more than one account, on more than one app, wants to post the same clip in each
place without every copy being the same file. A version is the same clip, the same words, the
same person, made again with a different frame, pace, colour and sound, and with its on-screen
text, captions and any disclaimer drawn on.

    plan_variants(brand, recording, clip_ids, n)     decide, and write the manifest. Makes no video.
    render_variants(brand, recording, ...)           make the files the manifest describes.

NO MODEL IS IN THE LOOP. Planning is arithmetic on the clip report. Rendering is the bundled
video program plus pictures of text drawn by overlays.py. A hundred versions cost no more to
think about than one, and the same inputs always give the same plan.

RECIPES ARE DATA (`RECIPES` below). A recipe sets these dials, and nothing else changes a clip:

    format    full frame (1080 x 1920) or a square picture in a vertical frame with its caption under it
    speed     a few percent faster at most; speech still sounds natural
    pitch     a percent or two, and eq a decibel or two. Pace alone leaves the voice's tone exactly
              as it was, so these two change the tone. If either can be heard it is set too high
    zoom, grade, vignette       the look
    mirror    OFF unless the brand's settings allow it AND a person has said nothing readable is
              in the picture. Mirrored writing, a logo or a clock reads backwards, and a tool
              cannot be trusted to notice. The text this engine draws is added after the flip
    trim      up to a second off the head or the tail, and only out of silence the clip report
              shows is there. Never a word
    music     a bed from the brand's OWN `video.music_folder`, quietly under the voice. No music
              ships with the Factory

`plan_variants` picks n recipes per clip, in an order fixed by a seed, so that every two versions
of a clip differ on at least three dials AS THEY WILL REALLY BE APPLIED: a dial that is switched
off for this brand or this clip (mirror, music, trim) does not count as a difference.

THE MANIFEST IS WRITTEN BEFORE ANYTHING IS RENDERED, from the clip report, and it is the only thing
the renderer reads. Which clip a file came from, its gate, its disclaimer and its sign-off are
recorded at the moment they are known. They are never worked out afterwards from file names.

TEXT GOES ON LAST. Flip, crop, zoom, colour and pace are applied to the picture first and the
text is laid over the result, so no dial can stretch, flip or tint a word.

A CLIP ON HOLD. It always carries the brand's disclaimer for its whole length; there is no dial
for that and no way to build the overlays without it (overlays.compose). A finished file only
gets its real name after the disclaimer has been found in its pixels. Until the person named in
the brand's settings has signed the clip off, it can only be made as a PREVIEW: stamped, in its
own folder, under a name that is not the delivery name.

Every file is written under a working name and renamed when it is complete and checked. What was
really applied to each file is written to `variant-log.json`. Making the versions again leaves
finished files alone unless asked to make them again.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time

from smf.video import cutlist, gate, overlays
from smf.video.fine_cut import probe_fps
from smf.video.common import (Transcript, VideoError, as_brand, fmt_ts, has_audio, locate, output_dir,
                              probe_duration, probe_shape, programs, read_json, resolve, run, words_in_clip,
                              write_json_atomic)
from smf.brands import replace_patiently

MANIFEST_FILE = "manifest.json"
LOG_FILE = "variant-log.json"
VERSION_MARK = "__"            # the same mark the posting tools read: <clip>__<version>.mp4
MAX_VERSIONS = 6
MIN_AXES_APART = 3
AXES = ("format", "speed", "pitch", "eq", "zoom", "grade", "vignette", "mirror", "trim", "music")

TRIM_MOST = 1.0                # never more than a second
TRIM_KEEP = {"head": 0.15, "tail": 0.25}     # silence left in place around the first and last word
TRIM_LEAST = 0.12              # less than this is not worth doing
SPEED_RANGE = (1.0, 1.08)
PITCH_RANGE = (0.98, 1.02)
ZOOM_RANGE = (1.0, 1.06)
MUSIC_MOST = 0.18
AUDIO_RATE = 48000
AUDIO_FILES = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
ENCODE = {"preset": "veryfast", "crf": "19"}

EQ = {"none": "", "air": "highshelf=f=7000:g=1.5", "presence": "equalizer=f=3000:t=q:w=1.2:g=1.2",
      "warmth": "lowshelf=f=200:g=1.5"}
GRADE = {"none": "", "warm": "colorbalance=rs=0.04:gs=0.01:bs=-0.04,eq=saturation=1.05",
         "cool": "colorbalance=rs=-0.03:bs=0.04,eq=saturation=1.03"}
VIGNETTE = "vignette=angle=PI/5"

RECIPES = [
    {"id": "clean", "format": "fullbleed", "speed": 1.00, "pitch": 1.000, "eq": "none", "zoom": 1.00,
     "grade": "none", "vignette": False, "mirror": False, "trim": "none", "music": 0.0},
    {"id": "framed", "format": "square", "speed": 1.03, "pitch": 0.988, "eq": "presence", "zoom": 1.00,
     "grade": "none", "vignette": False, "mirror": False, "trim": "none", "music": 0.12},
    {"id": "warm", "format": "fullbleed", "speed": 1.05, "pitch": 1.012, "eq": "warmth", "zoom": 1.03,
     "grade": "warm", "vignette": True, "mirror": False, "trim": "tail", "music": 0.0},
    {"id": "cool", "format": "fullbleed", "speed": 1.03, "pitch": 1.020, "eq": "air", "zoom": 1.05,
     "grade": "cool", "vignette": False, "mirror": True, "trim": "head", "music": 0.14},
    {"id": "brisk", "format": "square", "speed": 1.07, "pitch": 1.012, "eq": "air", "zoom": 1.03,
     "grade": "warm", "vignette": False, "mirror": False, "trim": "tail", "music": 0.0},
    {"id": "close", "format": "fullbleed", "speed": 1.07, "pitch": 0.988, "eq": "none", "zoom": 1.05,
     "grade": "none", "vignette": True, "mirror": False, "trim": "head", "music": 0.12},
    {"id": "soft", "format": "square", "speed": 1.05, "pitch": 1.020, "eq": "warmth", "zoom": 1.00,
     "grade": "cool", "vignette": True, "mirror": True, "trim": "none", "music": 0.16},
    {"id": "steady", "format": "square", "speed": 1.00, "pitch": 1.012, "eq": "presence", "zoom": 1.05,
     "grade": "warm", "vignette": True, "mirror": False, "trim": "head", "music": 0.0},
]

# The face finder uses the detector built into the video tier's imaging library. That detector
# needs a small model file, which is not part of this copy of the Factory. When it is absent the
# picture is cropped around its centre and the report says so in plain words.
FACE_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "face_detection_yunet_2023mar.onnx")
FACE_SAMPLES = 9
HEAD_AT = 0.40                 # where the head should sit in a square picture, from the top
NO_FINDER = ("This copy of the Factory cannot look for faces, so the picture was cropped around its centre. "
             "Watch the framing. If the person is off to one side, say where they are and plan again.")
NO_FACE = "No face was found, so the picture was cropped around its centre. Watch the framing."


# ----------------------------------------------------------------------------- where things live
def variants_dir(brand, recording, *parts):
    return output_dir(brand, recording, "variants", *parts)


def manifest_path(brand, recording):
    return variants_dir(brand, recording, MANIFEST_FILE)


def log_path(brand, recording):
    return variants_dir(brand, recording, LOG_FILE)


def load_manifest(brand, recording):
    path = manifest_path(brand, recording)
    if not os.path.isfile(path):
        raise VideoError("No versions have been planned for '%s' yet. Plan them first." % recording)
    data = read_json(path, "The versions plan for '%s'" % recording)
    if data.get("brand") != brand.id:
        raise VideoError("The versions plan in this folder belongs to '%s', not to %s. Nothing was done."
                         % (data.get("brand"), brand.name))
    return data


def load_log(brand, recording):
    path = log_path(brand, recording)
    if not os.path.isfile(path):
        return []
    data = read_json(path, "The record of what was made for '%s'" % recording)
    return data.get("files", []) if isinstance(data, dict) else []


def _save_log(brand, recording, fresh):
    """Fold new entries into the record. Making one clip again must not erase the record of all
    the others, so entries are replaced by (clip, version, preview) and everything else is kept."""
    def key(e):
        return (e.get("clip"), e.get("version"), bool(e.get("preview")))
    touched = {key(e) for e in fresh}
    kept = [e for e in load_log(brand, recording) if key(e) not in touched]
    write_json_atomic(log_path(brand, recording), {"schema": 1, "brand": brand.id, "recording": recording,
                                                   "files": kept + list(fresh)})


def version_file(clip, version, preview=False):
    stem = os.path.splitext(clip["file"])[0]
    return "%s%s%s%s.mp4" % (stem, VERSION_MARK, version, ".preview" if preview else "")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ----------------------------------------------------------------------------- the clip report
def load_report(brand, recording, which="auto"):
    """(report, folder, kind): the fine cuts when there are any, otherwise the rough cuts."""
    for kind in (["fine", "rough"] if which == "auto" else [which]):
        folder = output_dir(brand, recording, kind)
        path = os.path.join(folder, "%s-cut-report.json" % kind)
        if os.path.isfile(path):
            report = read_json(path, "The %s-cut report for '%s'" % (kind, recording))
            if report.get("brand") not in (None, brand.id):
                raise VideoError("The cut report in this folder belongs to '%s', not to %s. Nothing was done."
                                 % (report.get("brand"), brand.name))
            return report, folder, kind
    raise VideoError("There are no finished clips for '%s' yet. Make the rough cuts (and fine cuts) first." % recording)


def current_sign_off(brand, recording, report, clip):
    """Who signed this clip off, read NOW. The clip report only knows what the cut list said on
    the day the clip was cut, and a sign-off is normally written into the cut list afterwards,
    once somebody has watched the clip. So the cut list is read again; the report is the fallback."""
    written = str(clip.get("signed_off") or "").strip()
    path = resolve(brand, recording, report.get("cut_list"))
    if not path:
        return written
    try:
        for body in cutlist.load(path).bodies:
            if body.key == str(clip.get("body") or "").upper() and body.signed_off.strip():
                return body.signed_off.strip()
    except VideoError:
        pass
    return written


def speaker_policy(brand, transcript, report):
    return gate.SpeakerPolicy.for_transcript(brand, transcript, report.get("speaker_check") == gate.ATTESTED)


def clip_words(clip, transcript, offset, policy=None):
    """The clip's words, timed from the clip's start, each marked with the piece it sits in.

    The arithmetic is common.words_in_clip, one piece at a time so the piece is known. `pieces`
    are what was REALLY cut (the fine cut's removals are already out of them). A word from a voice
    that may not appear is left out and counted: it should not be there at all, and the check
    before delivery looks for it, but it must never be printed as a caption meanwhile."""
    out, kept_out, elapsed = [], 0, 0.0
    for index, (start, end) in enumerate(clip.get("pieces") or []):
        for w in words_in_clip([[start, end]], transcript.words, offset):
            if policy is not None and policy.labelled and not policy.may_publish(w.get("speaker")):
                kept_out += 1
                continue
            out.append(dict(w, start=round(w["start"] + elapsed, 3), end=round(w["end"] + elapsed, 3), piece=index))
        elapsed += end - start
    return out, kept_out


def piece_joins(clip):
    joins, elapsed = [], 0.0
    for start, end in (clip.get("pieces") or [])[:-1]:
        elapsed += end - start
        joins.append(round(elapsed, 3))
    return joins


def planned_length(clip):
    return round(sum(end - start for start, end in clip.get("pieces") or []), 3)


# ----------------------------------------------------------------------------- the brand's own settings
def mirror_allowed(brand):
    return (brand.data.get("video") or {}).get("allow_mirror") is True


def music_beds(brand):
    """(files, note). The brand's OWN music folder: inside the brand, or a full path the brand
    wrote down. Never another brand's folder, never anything that ships with the Factory."""
    from smf import brands as B
    raw = str((brand.data.get("video") or {}).get("music_folder") or "").strip()
    if not raw:
        return [], ""
    expanded = os.path.expanduser(raw)
    if os.path.isabs(expanded) or re.match(r"^[A-Za-z]:[\\/]", expanded):
        folder = expanded
    else:
        parts = [p for p in re.split(r"[\\/]+", raw) if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            return [], "The music folder in %s's settings climbs out of the brand folder, so no music was used." % brand.name
        folder = os.path.join(brand.home, *parts)
    real, home, clients = (os.path.normcase(os.path.realpath(p)) for p in (folder, brand.home, B.CLIENT_DIR))
    inside_brand = real == home or real.startswith(home + os.sep)
    if not inside_brand and (real == clients or real.startswith(clients + os.sep)):
        return [], "That music folder belongs to another brand, so no music was used."
    if not os.path.isdir(folder):
        return [], "The music folder in %s's settings could not be found, so the versions have no music." % brand.name
    beds = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        beds += [os.path.join(root, n) for n in sorted(names)
                 if not n.startswith(".") and os.path.splitext(n)[1].lower() in AUDIO_FILES]
    return beds, ("" if beds else "The music folder is empty, so the versions have no music.")


# ----------------------------------------------------------------------------- recipes
def check_recipe(recipe):
    """A recipe somebody edited must still be inside the ranges that keep a clip sounding natural."""
    rid = recipe.get("id", "?")
    if recipe.get("format") not in overlays.FORMATS:
        raise VideoError("The recipe '%s' has a format that does not exist: %s." % (rid, recipe.get("format")))
    for name, (low, high) in (("speed", SPEED_RANGE), ("pitch", PITCH_RANGE), ("zoom", ZOOM_RANGE)):
        if not low <= float(recipe.get(name, 1.0)) <= high:
            raise VideoError("The recipe '%s' sets %s to %s. It has to stay between %s and %s, or people hear and "
                             "see the difference." % (rid, name, recipe.get(name), low, high))
    if recipe.get("eq", "none") not in EQ or recipe.get("grade", "none") not in GRADE:
        raise VideoError("The recipe '%s' names a sound or colour setting that does not exist." % rid)
    if recipe.get("trim", "none") not in ("none", "head", "tail"):
        raise VideoError("The recipe '%s' can trim the 'head', the 'tail' or 'none'." % rid)
    if not 0.0 <= float(recipe.get("music", 0.0)) <= MUSIC_MOST:
        raise VideoError("The recipe '%s' sets music louder than %s, which would fight the voice." % (rid, MUSIC_MOST))
    return recipe


def slack_of(words, length):
    """Seconds of silence before the first word and after the last, as the clip report shows them."""
    if not words:
        return {"head": 0.0, "tail": 0.0}
    return {"head": round(max(0.0, words[0]["start"]), 3), "tail": round(max(0.0, length - words[-1]["end"]), 3)}


def effective(recipe, mirror_ok=False, beds=(), slack=None):
    """The recipe as it will REALLY be applied to one clip. A dial that cannot apply is switched
    off here, in the open, so the plan, the distance between versions and the log all agree."""
    r = dict(check_recipe(recipe))
    r["mirror"] = bool(r.get("mirror")) and bool(mirror_ok)
    where = r.get("trim", "none")
    seconds = 0.0
    if where != "none":
        seconds = min(TRIM_MOST, (slack or {}).get(where, 0.0) - TRIM_KEEP[where])
        if seconds < TRIM_LEAST:
            where, seconds = "none", 0.0
    r["trim"], r["trim_seconds"] = where, round(max(0.0, seconds), 3)
    r["music"] = float(r.get("music", 0.0)) if beds else 0.0
    return r


def axes_apart(a, b):
    return [axis for axis in AXES if (bool(a[axis]) if axis == "music" else a[axis]) !=
            (bool(b[axis]) if axis == "music" else b[axis])]


def choose_recipes(n, seed_text, mirror_ok=False, beds=(), slack=None, library=None):
    """n recipes in an order fixed by `seed_text`, every two of them at least MIN_AXES_APART dials
    apart as they will really be applied. The same seed always gives the same answer."""
    library = list(library or RECIPES)
    if not 1 <= n <= MAX_VERSIONS:
        raise VideoError("Ask for between 1 and %d versions of a clip." % MAX_VERSIONS)

    def order(recipe):
        return hashlib.sha256(("%s|%s" % (seed_text, recipe["id"])).encode("utf-8")).hexdigest()
    chosen = []
    for recipe in sorted(library, key=order):
        candidate = effective(recipe, mirror_ok, beds, slack)
        if all(len(axes_apart(candidate, other)) >= MIN_AXES_APART for other in chosen):
            chosen.append(candidate)
        if len(chosen) == n:
            return chosen
    raise VideoError("Only %d version%s of this clip can be made that differ enough from each other. Ask for %d or fewer."
                     % (len(chosen), "" if len(chosen) == 1 else "s", len(chosen)))


# ----------------------------------------------------------------------------- where the person is
def find_face(path, shape, duration, samples=FACE_SAMPLES):
    """{"found", "x", "y", "h", "seen_in", "looked_at", "by", "note"}: the middle of the largest face, as
    shares of the picture as it is SHOWN, taken as the median over frames spread through the clip.
    One frame can catch a turned head or a hand across the face; the median of several does not
    care. A face seen in fewer than half the frames counts as not found."""
    nothing = {"found": False, "x": 0.5, "y": 0.5, "h": 0.0, "seen_in": 0, "looked_at": 0, "by": "", "note": NO_FINDER}
    if not os.path.isfile(FACE_MODEL) or duration <= 0.5:
        return nothing                                              # and the imaging library is never even loaded
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")              # its start-up chatter is not for the person
    try:
        import cv2
        import numpy as np
    except ImportError:
        return nothing
    if not hasattr(cv2, "FaceDetectorYN"):
        return nothing
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass
    ff, _fp = programs()
    width = 640
    height = int(round(width * shape["height"] / float(shape["width"]) / 2.0)) * 2
    r = run([ff, "-v", "error", "-ss", "%.3f" % (duration * 0.06), "-i", path, "-t", "%.3f" % (duration * 0.88),
             "-vf", "fps=%.5f,scale=%d:%d" % (samples / (duration * 0.88), width, height),
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], "look for a face in '%s'" % os.path.basename(path), binary=True)
    size = width * height * 3
    frames = [np.frombuffer(r.stdout[i:i + size], dtype="uint8").reshape(height, width, 3)
              for i in range(0, len(r.stdout) - size + 1, size)]
    if not frames:
        return dict(nothing, note=NO_FACE)
    xs, ys, hs = [], [], []
    try:
        detector = cv2.FaceDetectorYN.create(FACE_MODEL, "", (width, height), 0.6, 0.3, 5000)
        for frame in frames:
            _n, faces = detector.detect(frame)
            if faces is None or not len(faces):
                continue
            fx, fy, fw, fh = [float(v) for v in max(faces, key=lambda f: f[2] * f[3])[:4]]     # the largest face
            xs.append((fx + fw / 2.0) / width)
            ys.append((fy + fh / 2.0) / height)
            hs.append(fh / height)
    except Exception:                                               # a damaged model file must not stop a plan
        return dict(nothing, looked_at=len(frames))
    found = len(xs) * 2 >= len(frames)
    if not found:
        return dict(nothing, seen_in=len(xs), looked_at=len(frames), note=NO_FACE)
    mid = lambda v: float(sorted(v)[len(v) // 2])                   # noqa: E731
    return {"found": True, "x": round(mid(xs), 4), "y": round(mid(ys), 4), "h": round(mid(hs), 4),
            "seen_in": len(xs), "looked_at": len(frames), "by": "the face finder", "note": ""}


def crop_for(shape, fmt, framing, zoom=1.0):
    """Which part of the source picture a version uses: {"x", "y", "w", "h", "face", "around"}.

    A full-frame version needs a 9:16 upright slice and a square version needs a square one. From a
    horizontal video that is a column, and WHICH column is the whole question: the person is often
    not in the middle. So it is centred on the face when one was found, and on the middle of the
    picture when not. `face` is where the face lands inside the slice (centre and height, as shares
    of the slice's height), for keeping the opening card off it."""
    W, H = int(shape["width"]), int(shape["height"])
    aspect = 9.0 / 16.0 if fmt == "fullbleed" else 1.0
    w = min(W, H * aspect)
    h = w / aspect
    w, h = w / max(1.0, zoom), h / max(1.0, zoom)
    known = bool(framing and framing.get("found"))
    cx = framing["x"] * W if known else W / 2.0
    if known and framing.get("h"):
        top = framing["y"] * H - HEAD_AT * h
    elif fmt == "square" and H > W:
        top = 0.30 * (H - h)                                        # people sit above the middle of an upright frame
    else:
        top = (H - h) / 2.0
    x = min(max(0.0, cx - w / 2.0), W - w)
    y = min(max(0.0, top), H - h)
    w2, h2 = int(w) - int(w) % 2, int(h) - int(h) % 2
    face = None
    if known and framing.get("h"):
        face = (round((framing["y"] * H - y) / h, 4), round(framing["h"] * H / h, 4))
    return {"x": int(x), "y": int(y), "w": w2, "h": h2, "face": face,
            "around": ("the face" if known and framing.get("by") != "a person" else
                       "where a person said they are" if known else "the centre")}


# ----------------------------------------------------------------------------- planning
def _gate_of(clip, rules, brand):
    """(gate, reasons). The report's gate, made stricter when the words that will be drawn on screen
    would themselves be stopped by the brand's rules. Never looser."""
    declared = str(clip.get("gate") or "").upper()
    if declared not in cutlist.GATES:
        return gate.DROP, ["its gate cannot be read from the clip report"]
    status, reasons = declared, []
    for label, text in (("on-screen text", clip.get("on_screen_text")), ("lower-third line", clip.get("lower_third"))):
        verdict = gate.check(text or "", rules)
        if verdict.status == gate.DROP:
            return gate.DROP, ["its %s carries a claim %s never publishes (%s)"
                               % (label, brand.name, "; ".join(verdict.reasons))]
        if verdict.status == gate.HOLD and status == cutlist.SHIP:
            status = gate.HOLD
            reasons.append("its %s needs the disclaimer and a sign-off (%s)" % (label, "; ".join(verdict.reasons)))
    return status, reasons


def plan_variants(brand, recording, clip_ids=None, n=3, seed="", no_text_in_footage=False, centre_on=None,
                  which="auto", face_finder=None, say=None):
    """Decide the versions of each clip and write the manifest. Nothing is rendered.

    no_text_in_footage   a person's statement about THIS recording: nothing readable is in the
                         picture (no sign, label, logo, screen or clock). Mirroring needs this AND
                         the brand's `video.allow_mirror`. It is never worked out by the tool.
    centre_on            {clip id: 0..1}: where the person is, left to right, when a person says so.
    face_finder          replaces the built-in finder: f(path, shape, duration) -> framing dict.
                         Pass False to skip looking.
    """
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    report, folder, kind = load_report(brand, recording, which)
    rules = gate.GateRules.for_brand(brand)
    transcript = Transcript.load(brand, recording)
    policy = speaker_policy(brand, transcript, report)
    offset = float(report.get("offset") or 0.0)
    shape = report.get("shape") or {}
    if not shape.get("width") or not shape.get("height"):
        raise VideoError("The clip report does not say what size the video is, so versions cannot be planned. "
                         "Make the rough cuts again.")
    beds, music_note = music_beds(brand)
    mirror_ok = mirror_allowed(brand) and bool(no_text_in_footage)
    centre_on = {str(k).upper(): float(v) for k, v in (centre_on or {}).items()}
    for cid, where in centre_on.items():
        if not 0.0 <= where <= 1.0:
            raise VideoError("Say where the person in %s is as a number from 0 (far left) to 1 (far right)." % cid)

    wanted = {c.upper() for c in clip_ids} if clip_ids else None
    known = {str(c.get("id", "")).upper() for c in report.get("clips", [])}
    if wanted is not None and wanted - known:
        raise VideoError("There is no clip called %s in the %s cuts. The clips are: %s."
                         % (", ".join(sorted(wanted - known)), kind, ", ".join(sorted(known)) or "none"))

    look = overlays.look_for(brand)                                 # a brand with no colours stops here, in plain words
    clips, refused = [], []
    for clip in report.get("clips", []):
        cid = str(clip.get("id", ""))
        if wanted is not None and cid.upper() not in wanted:
            continue
        source = os.path.join(folder, clip.get("file") or "")
        if clip.get("status") != "ok" or not clip.get("file") or not os.path.isfile(source):
            refused.append({"id": cid, "why": "it has no finished %s cut to work from" % kind})
            continue
        status, gate_reasons = _gate_of(clip, rules, brand)
        if status == gate.DROP:
            refused.append({"id": cid, "why": "; ".join(gate_reasons) or "it is marked DROP: this brand never publishes it"})
            continue
        disclaimer = (clip.get("disclaimer") or "").strip() or (rules.disclaimer if status == gate.HOLD else "")
        sign_off_by = (clip.get("sign_off_by") or "").strip() or (rules.sign_off_by if status == gate.HOLD else "")
        if status == gate.HOLD and not disclaimer:
            refused.append({"id": cid, "why": "it is on HOLD and %s has no disclaimer written, so it cannot be shown. "
                                              "Add the disclaimer in the brand's settings" % brand.name})
            continue
        if status == gate.HOLD:
            try:
                overlays.disclaimer_band(look, disclaimer)          # too long to read on a phone: say so now, not mid-render
            except ImportError:
                pass                                                # nothing to draw with yet; the same check runs at render

        length = planned_length(clip)
        if length <= 0:
            refused.append({"id": cid, "why": "the clip report does not say which stretches it was cut from"})
            continue
        words, kept_out = clip_words(clip, transcript, offset, policy)
        printed, left_out, caption_note = overlays.printable_words(words)
        notes = list(gate_reasons)
        if not transcript.word_level:
            notes.append("This recording's transcript has sentence times only, so the versions have no captions and "
                         "nothing is trimmed.")
        if kept_out:
            notes.append("%d word(s) inside this clip belong to someone who stays off camera. They are not captioned. "
                         "The check before delivery will look at this clip closely." % kept_out)
        if caption_note:
            notes.append(caption_note)
        text_note = overlays.check_words(clip.get("on_screen_text"))
        if text_note:
            notes.append(text_note)

        if cid.upper() in centre_on:
            framing = {"found": True, "x": centre_on[cid.upper()], "y": 0.0, "h": 0.0, "seen_in": 0, "looked_at": 0,
                       "by": "a person", "note": ""}
        elif face_finder is False:
            framing = {"found": False, "x": 0.5, "y": 0.5, "h": 0.0, "seen_in": 0, "looked_at": 0, "by": "",
                       "note": "Nobody looked for a face, so the picture is cropped around its centre."}
        else:
            framing = (face_finder or find_face)(source, shape, float(clip.get("actual_duration") or length))
        if not framing.get("found") and shape.get("orientation") != "vertical":
            notes.append(framing.get("note") or NO_FACE)

        signed = current_sign_off(brand, recording, report, clip)
        recipes = choose_recipes(n, "%s|%s|%s|%s" % (brand.id, recording, cid, seed), mirror_ok, beds,
                                 slack_of(words, length))
        entry = {"id": cid, "source": {"file": locate(brand, source), "cut": kind,
                                       "duration": float(clip.get("actual_duration") or length), "shape": shape},
                 "report_entry": clip, "gate": status, "needs_disclaimer": status == gate.HOLD,
                 "disclaimer": disclaimer if status == gate.HOLD else "", "sign_off_by": sign_off_by,
                 "signed_off": signed, "may_be_delivered": status != gate.HOLD or bool(signed),
                 "on_screen_text": "" if text_note else " ".join(str(clip.get("on_screen_text") or "").split()),
                 "lower_third": " ".join(str(clip.get("lower_third") or "").split()),
                 "framing": framing, "captions": {"words": len(printed), "left_out": left_out},
                 "notes": notes, "versions": []}
        hashed = int(hashlib.sha256(cid.encode("utf-8")).hexdigest(), 16)
        for index, recipe in enumerate(recipes):
            version = "v%d" % (index + 1)
            recipe = dict(recipe, music_bed=(locate(brand, beds[(hashed + index) % len(beds)])
                                             if recipe["music"] and beds else ""))
            body = {"recipe": recipe, "source": entry["source"], "gate": status, "disclaimer": entry["disclaimer"],
                    "on_screen_text": entry["on_screen_text"], "lower_third": entry["lower_third"],
                    "framing": {k: framing.get(k) for k in ("found", "x", "y", "h")}, "pieces": clip.get("pieces")}
            sealed = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
            entry["versions"].append({
                "version": version, "recipe": recipe, "fingerprint": hashlib.sha256(sealed).hexdigest()[:16],
                "output": locate(brand, variants_dir(brand, recording, version_file(clip, version))),
                "preview_output": locate(brand, variants_dir(brand, recording, "previews",
                                                             version_file(clip, version, True)))})
        clips.append(entry)
        chosen = ", ".join("%s=%s" % (v["version"], v["recipe"]["id"]) for v in entry["versions"])
        say("%s  %s  %s%s" % (cid, status, chosen, "" if entry["may_be_delivered"] else
                              "  (waiting for sign-off by %s)" % (sign_off_by or "a named person")))
    if not clips:
        why = "; ".join("%s: %s" % (r["id"], r["why"]) for r in refused) or "there are no clips in the report"
        raise VideoError("No versions could be planned (%s)." % why)

    manifest = {"schema": 1, "kind": "variants", "brand": brand.id, "recording": recording, "made_from": kind,
                "report": locate(brand, os.path.join(folder, "%s-cut-report.json" % kind)),
                "cut_list": report.get("cut_list"), "offset": offset, "speaker_check": report.get("speaker_check"),
                "planned_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seed": seed, "versions_per_clip": n,
                "frame": {"width": overlays.CANVAS_W, "height": overlays.CANVAS_H},
                "clear_area": {"box": list(overlays.design_box()), "as_of": overlays.SAFE_MARGINS_AS_OF},
                "mirror": {"brand_allows": mirror_allowed(brand),
                           "a_person_said_no_text_in_picture": bool(no_text_in_footage), "used": mirror_ok},
                "music": {"beds": [os.path.basename(b) for b in beds], "note": music_note},
                "clips": clips, "refused": refused}
    path = manifest_path(brand, recording)
    saved = manifest
    if clip_ids and os.path.isfile(path):                           # planning one clip again keeps the others' plans
        try:
            old = read_json(path, "The earlier plan")
            fresh = {c["id"]: c for c in clips}
            if old.get("brand") == brand.id and old.get("made_from") == kind:
                saved = dict(manifest, clips=[fresh.pop(c["id"], c) for c in old.get("clips", [])] + list(fresh.values()))
        except VideoError:
            pass
    write_json_atomic(path, saved)
    return manifest                                                 # what THIS run planned; the file holds everything


# ----------------------------------------------------------------------------- building the render
def retimed(words, head, speed, length_out):
    """The clip's words on the VERSION's clock: a trimmed head moves everything earlier, a faster
    pace squeezes it. Captions are timed on this clock, so they need no correction afterwards."""
    out = []
    for w in words:
        start, end = (w["start"] - head) / speed, (w["end"] - head) / speed
        if end <= 0 or start >= length_out:
            continue
        out.append(dict(w, start=round(max(0.0, start), 3), end=round(min(length_out, end), 3)))
    return out


def build_command(ff, source, working, job):
    """The video program's arguments for ONE version, as a list (paths are never pasted into a
    string). `job` holds everything already decided: the slice, the dials, the overlays.

    Two rules are enforced here as well as where the overlays are made, because this is the last
    place a mistake could slip in: a clip that needs its disclaimer gets no command without one,
    and the disclaimer is laid on after every other piece of text so nothing can sit on top of it."""
    recipe, crop, ov, fps = job["recipe"], job["crop"], job["overlays"], job["fps"]
    kinds = [layer.kind for layer in ov.layers]
    if job["need_disclaimer"]:
        if "disclaimer" not in kinds:
            raise VideoError("This clip may only be shown with its disclaimer, and the disclaimer is missing from "
                             "the version being made. Nothing was made.")
        if [k for k in kinds if k != "preview"][-1] != "disclaimer":
            raise VideoError("The disclaimer has to be the last thing laid over the picture. Nothing was made.")
    if job["preview"] and "preview" not in kinds:
        raise VideoError("A preview has to carry the PREVIEW stamp. Nothing was made.")

    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    if job["head"] > 0 or job["tail"] > 0:
        cmd += ["-ss", "%.3f" % job["head"], "-t", "%.3f" % job["kept"]]
    cmd += ["-i", source]
    vx, vy, vw, vh = ov.video_rect
    chain = ["crop=%d:%d:%d:%d" % (crop["w"], crop["h"], crop["x"], crop["y"])]
    if recipe["mirror"]:
        chain.append("hflip")
    chain += ["scale=%d:%d:flags=lanczos" % (vw, vh), "setsar=1"]
    if GRADE[recipe["grade"]]:
        chain.append(GRADE[recipe["grade"]])
    if recipe["vignette"]:
        chain.append(VIGNETTE)
    if (vw, vh) != (overlays.CANVAS_W, overlays.CANVAS_H):
        chain.append("pad=%d:%d:%d:%d:color=0x%s" % (overlays.CANVAS_W, overlays.CANVAS_H, vx, vy,
                                                     ov.canvas_colour.lstrip("#")))
    if abs(recipe["speed"] - 1.0) > 1e-6:
        chain.append("setpts=PTS/%.4f" % recipe["speed"])
    chain.append("fps=%.5f" % fps)
    graph, label, index = ["[0:v]%s[v0]" % ",".join(chain)], "[v0]", 1
    for layer in ov.layers:
        if layer.kind == "captions":
            cmd += ["-f", "concat", "-safe", "0", "-i", layer.path]
            how = "overlay=%d:%d" % (layer.x, layer.y)
            feed = "[%d:v]" % index
        elif layer.end is not None:
            # A picture shown for a while and then faded out. It is looped for just long enough, so
            # it is never an endless input that something later has to remember to stop.
            cmd += ["-f", "image2", "-pattern_type", "none", "-loop", "1", "-framerate", "%.5f" % fps,
                    "-t", "%.3f" % (layer.end + 0.25), "-i", layer.path]
            graph.append("[%d:v]format=rgba,fade=t=out:st=%.3f:d=%.3f:alpha=1[f%d]"
                         % (index, max(0.0, layer.end - layer.fade), layer.fade, index))
            how = "overlay=%d:%d:eof_action=pass:enable='lt(t,%.3f)'" % (layer.x, layer.y, layer.end)
            feed = "[f%d]" % index
        else:
            cmd += ["-f", "image2", "-pattern_type", "none", "-i", layer.path]     # one frame, held to the end
            how = "overlay=%d:%d" % (layer.x, layer.y)
            feed = "[%d:v]" % index
        graph.append("%s%s%s[v%d]" % (label, feed, how, index))
        label, index = "[v%d]" % index, index + 1

    voice = ["aresample=%d" % AUDIO_RATE]
    if abs(recipe["pitch"] - 1.0) > 1e-6:
        # Changing the rate moves pitch and pace together; the pace is then put back, so only the
        # pitch has changed. The resample FIRST is what makes the amount right for any source.
        voice += ["asetrate=%d" % int(round(AUDIO_RATE * recipe["pitch"])), "aresample=%d" % AUDIO_RATE,
                  "atempo=%.6f" % (1.0 / recipe["pitch"])]
    if abs(recipe["speed"] - 1.0) > 1e-6:
        voice.append("atempo=%.4f" % recipe["speed"])
    if EQ[recipe["eq"]]:
        voice.append(EQ[recipe["eq"]])
    graph.append("[0:a]%s[voice]" % ",".join(voice))
    sound = "[voice]"
    if job.get("bed"):
        cmd += ["-stream_loop", "-1", "-i", job["bed"]]
        graph.append("[%d:a]aresample=%d,volume=%.3f[bed]" % (index, AUDIO_RATE, recipe["music"]))
        graph.append("[voice][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]")
        sound = "[mix]"
    cmd += ["-filter_complex", ";".join(graph), "-map", label, "-map", sound, "-map_metadata", "-1",
            "-c:v", "libx264", "-preset", ENCODE["preset"], "-crf", ENCODE["crf"], "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", str(AUDIO_RATE), "-movflags", "+faststart",
            "-t", "%.3f" % (job["length_out"] + 0.04), working]     # a hard stop, whatever the inputs do
    return cmd


def grab_frame(path, at, shape=None):
    """One frame of a video as an image, without writing anything to disk."""
    from PIL import Image
    shape = shape or probe_shape(path)
    ff, _fp = programs()
    r = run([ff, "-v", "error", "-ss", "%.3f" % max(0.0, at), "-i", path, "-frames:v", "1", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-"], "look at a frame of '%s'" % os.path.basename(path), binary=True)
    need = shape["width"] * shape["height"] * 3
    if len(r.stdout) < need:
        return None
    return Image.frombytes("RGB", (shape["width"], shape["height"]), r.stdout[:need])


def disclaimer_in_pixels(path, facts, length, shape=None):
    """(frames looked at, problems). The start, the middle and the end of a finished file."""
    looked, problems = 0, []
    for at in sorted({round(min(0.2, length / 4.0), 2), round(length / 2.0, 2), round(max(0.0, length - 0.35), 2)}):
        frame = grab_frame(path, at, shape)
        if frame is None:
            continue
        looked += 1
        ok, why = overlays.band_present(frame, facts)
        if not ok:
            problems.append("at %s %s" % (fmt_ts(at), why))
    return looked, problems


def _may_render(clip, signed, preview):
    """("deliver" | "preview" | "wait", why). The one place that decides what a HOLD clip may become."""
    if clip["gate"] != gate.HOLD or signed:
        return "deliver", ""
    who = clip.get("sign_off_by") or "the person named in the brand's settings"
    if preview:
        return "preview", "waiting for sign-off by %s" % who
    return "wait", ("%s is on HOLD and %s has not signed it off, so it cannot be made for posting. Make a preview "
                    "for them to watch, then write their sign-off into the cut list." % (clip["id"], who))


def render_variants(brand, recording, clip_ids=None, versions=None, preview=False, again=False, say=None,
                    keep_scratch=False):
    """Make the files the manifest describes. Returns {"made", "already", "waiting", "failed"}.

    preview   also make stamped previews, in their own folder, of clips still waiting for sign-off.
              Without it those clips are listed under "waiting" and nothing is made of them.
    again     make finished files again. Without it a finished file that still matches the plan
              is left exactly as it is.
    """
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    manifest = load_manifest(brand, recording)
    report, _folder, _kind = load_report(brand, recording, manifest.get("made_from") or "auto")
    transcript = Transcript.load(brand, recording)
    policy = speaker_policy(brand, transcript, report)
    look = overlays.look_for(brand)
    ff, _fp = programs()
    wanted = {c.upper() for c in clip_ids} if clip_ids else None
    known = {c["id"].upper() for c in manifest["clips"]}
    if wanted is not None and wanted - known:
        raise VideoError("The plan has no clip called %s. It has: %s." % (", ".join(sorted(wanted - known)),
                                                                        ", ".join(sorted(known))))
    only_versions = {v.lower() for v in versions} if versions else None
    logged = {(e.get("clip"), e.get("version"), bool(e.get("preview"))): e for e in load_log(brand, recording)}
    result = {"made": [], "already": [], "waiting": [], "failed": []}

    for clip in manifest["clips"]:
        if wanted is not None and clip["id"].upper() not in wanted:
            continue
        signed = current_sign_off(brand, recording, report, clip["report_entry"])
        what, why = _may_render(clip, signed, preview)
        if what == "wait":
            result["waiting"].append({"clip": clip["id"], "why": why})
            say(why)
            continue
        as_preview = what == "preview"
        source = resolve(brand, recording, clip["source"]["file"])
        if not source:
            result["failed"].append({"clip": clip["id"], "version": "",
                                     "why": "the clip it is made from cannot be found any more"})
            continue
        shape = probe_shape(source)
        if not has_audio(source):
            result["failed"].append({"clip": clip["id"], "version": "", "why": "the clip has no sound"})
            continue
        length = probe_duration(source)
        fps = probe_fps(source)
        words, _kept_out = clip_words(clip["report_entry"], transcript, float(manifest.get("offset") or 0.0), policy)
        printed, left_out, _note = overlays.printable_words(words)

        for v in clip["versions"]:
            if only_versions is not None and v["version"].lower() not in only_versions:
                continue
            final = brand.path(*(v["preview_output"] if as_preview else v["output"]).split("/"))
            key = (clip["id"], v["version"], as_preview)
            before = logged.get(key)
            if (not again and before and before.get("status") == "ok" and before.get("fingerprint") == v["fingerprint"]
                    and os.path.isfile(final)):
                result["already"].append(locate(brand, final))
                say("%s %s  already made" % (clip["id"], v["version"]))
                continue
            entry = _render_one(brand, ff, clip, v, source, shape, length, fps, printed, left_out, look, final,
                                as_preview, signed, keep_scratch)
            _save_log(brand, recording, [entry])
            if entry["status"] == "ok":
                result["made"].append(entry["file"])
                say("%s %s  %s  %s%s" % (clip["id"], v["version"], v["recipe"]["id"], fmt_ts(entry["duration"]),
                                         "  PREVIEW" if as_preview else ""))
            else:
                result["failed"].append({"clip": clip["id"], "version": v["version"], "why": entry["why"]})
                say("%s %s  could not be made: %s" % (clip["id"], v["version"], entry["why"]))
    if not (result["made"] or result["already"] or result["waiting"] or result["failed"]):
        raise VideoError("Nothing matched what was asked for, so nothing was made.")
    return result


def _render_one(brand, ff, clip, v, source, shape, length, fps, printed, left_out, look, final, as_preview, signed,
                keep_scratch):
    recipe = v["recipe"]
    head = recipe["trim_seconds"] if recipe["trim"] == "head" else 0.0
    tail = recipe["trim_seconds"] if recipe["trim"] == "tail" else 0.0
    kept = max(0.5, length - head - tail)
    length_out = kept / recipe["speed"]
    entry = {"clip": clip["id"], "version": v["version"], "preview": as_preview, "file": locate(brand, final),
             "status": "failed", "made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "fingerprint": v["fingerprint"],
             "source": clip["source"]["file"], "recipe": recipe, "gate": clip["gate"], "signed_off": signed,
             "disclaimer": {"required": bool(clip["needs_disclaimer"]), "present": False, "text": clip["disclaimer"]}}
    scratch = tempfile.mkdtemp(prefix="smf-version-")
    working = os.path.splitext(final)[0] + ".working.mp4"
    try:
        words = retimed(printed, head, recipe["speed"], length_out)
        lines = overlays.caption_lines(words, fits=overlays.caption_fits(look)) if words else []
        joins = [round((j - head) / recipe["speed"], 3) for j in piece_joins(clip["report_entry"])
                 if head < j < length - tail]
        crop = crop_for(shape, recipe["format"], clip["framing"], recipe["zoom"])
        ov = overlays.compose(look, recipe["format"], scratch, on_screen_text=clip["on_screen_text"],
                              lower_third=clip["lower_third"], disclaimer=clip["disclaimer"],
                              need_disclaimer=bool(clip["needs_disclaimer"]),
                              preview_for=(clip.get("sign_off_by") or "") if as_preview else None,
                              lines=lines, duration=length_out, joins=joins, face=crop["face"])
        bed = resolve_bed(brand, recipe)
        job = {"recipe": recipe, "crop": crop, "overlays": ov, "fps": fps, "head": head, "tail": tail, "kept": kept,
               "length_out": length_out, "need_disclaimer": bool(clip["needs_disclaimer"]), "preview": as_preview,
               "bed": bed}
        os.makedirs(os.path.dirname(final), exist_ok=True)
        run(build_command(ff, source, working, job), "make %s of clip %s" % (v["version"], clip["id"]))

        made = probe_shape(working)
        actual = probe_duration(working)
        if (made["width"], made["height"]) != (overlays.CANVAS_W, overlays.CANVAS_H) or not has_audio(working):
            raise VideoError("the finished file is not an upright video with sound")
        if abs(actual - length_out) > 0.5:
            raise VideoError("the finished file is %s long and should be %s" % (fmt_ts(actual), fmt_ts(length_out)))
        if clip["needs_disclaimer"]:
            looked, problems = disclaimer_in_pixels(working, ov.disclaimer, actual, made)
            entry["disclaimer"].update(ov.disclaimer, frames_checked=looked)
            if not looked:
                raise VideoError("the finished file could not be looked at, so the disclaimer could not be confirmed")
            if problems:
                raise VideoError("the disclaimer could not be seen in the finished picture (%s)" % "; ".join(problems))
            entry["disclaimer"]["present"] = True
        replace_patiently(working, final)                                  # only a complete, checked file gets the real name
        hook = ov.layer("hook")
        entry.update({
            "status": "ok", "duration": round(actual, 2), "expected_duration": round(length_out, 2),
            "frame": [made["width"], made["height"]], "bytes": os.path.getsize(final), "sha256": sha256_of(final),
            "applied": {"slice_of_source": {k: crop[k] for k in ("x", "y", "w", "h")}, "framed_around": crop["around"],
                        "picture_on_frame": list(ov.video_rect), "mirror": recipe["mirror"], "speed": recipe["speed"],
                        "pitch": recipe["pitch"], "eq": recipe["eq"], "zoom": recipe["zoom"], "grade": recipe["grade"],
                        "vignette": recipe["vignette"], "trim": {"where": recipe["trim"], "seconds": recipe["trim_seconds"]},
                        "music": {"bed": os.path.basename(bed), "level": recipe["music"]} if bed else None},
            "on_screen": {"text": clip["on_screen_text"],
                          "shown_for": hook.end if hook else (round(actual, 2) if ov.layer("under") else 0.0),
                          "lower_third": clip["lower_third"],
                          "captions": {"lines": ov.caption_lines, "words": len(words), "left_out": left_out,
                                       "spoken_word_colour": look.accent_on_plate},
                          "preview_stamp": as_preview},
            "notes": list(ov.notes)})
    except VideoError as e:
        entry["why"] = str(e)
    finally:
        if os.path.exists(working):
            os.remove(working)
        if not keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    return entry


def resolve_bed(brand, recipe):
    """The music file for a version, or "". It has to be where the plan said, inside the brand's
    own music folder; a plan that points anywhere else is ignored rather than followed."""
    if not recipe.get("music") or not recipe.get("music_bed"):
        return ""
    beds, _note = music_beds(brand)
    for bed in beds:
        if locate(brand, bed) == recipe["music_bed"]:
            return bed
    return ""


# ----------------------------------------------------------------------------- where things stand
def status(brand, recording):
    """One row per clip: what is planned, made, waiting, checked and delivered."""
    brand = as_brand(brand)
    manifest = load_manifest(brand, recording)
    report, _folder, _kind = load_report(brand, recording, manifest.get("made_from") or "auto")
    finished = [e for e in load_log(brand, recording) if e.get("status") == "ok"]
    made = {(e["clip"], e["version"]): e for e in finished if not e.get("preview")}
    previews = {(e["clip"], e["version"]) for e in finished if e.get("preview")}
    rows = []
    for clip in manifest["clips"]:
        signed = current_sign_off(brand, recording, report, clip["report_entry"])
        names = [v["version"] for v in clip["versions"]]
        rows.append({"clip": clip["id"], "gate": clip["gate"], "signed_off": signed,
                     "sign_off_by": clip.get("sign_off_by", ""),
                     "may_be_delivered": clip["gate"] != gate.HOLD or bool(signed), "planned": names,
                     "made": [n for n in names if (clip["id"], n) in made
                              and os.path.isfile(brand.path(*made[(clip["id"], n)]["file"].split("/")))],
                     "previews": [n for n in names if (clip["id"], n) in previews], "notes": clip.get("notes", [])})
    return rows
