"""rough_cut.py - cut list in, stitched rough cuts out. One clip per hook: hook, hard cut, body.

WORDS ARE THE ANCHOR, TIMES ARE APPROXIMATE. A time in a cut list may have been rounded down, read
off a different copy of the video, or typed by hand. The quoted first and last words of a segment
do not drift. So for every cut point the tool listens to the video around the written time, finds
the quoted words, and cuts on them. When that is not possible it falls back, in order:

  1. text    the quoted boundary words were found; cut at that word                 (best)
  2. word    no quote, or not found: the first word that starts (or ends) just after the time
  3. silence no word times available at all: the first real pause just after the time
  4. pad     nothing to go on: a fixed margin either side                            (worst)

The method used for every edge is written into the report, and the mix is itself a warning light:
when most quoted words cannot be found near their times, the times almost certainly belong to a
different video file, and the render stops instead of producing confident nonsense.

WHERE A CUT LANDS. Just before a word's attack, never just after the previous word "ends". The
moment a word starts is something both a speech model and a loudness measurement get right; the
moment a word finishes is not (soft endings trail off into what looks like silence). So head cuts
sit inside the pause before the word, and tail cuts take the later of "the model says the word
ended" and "the sound actually dropped", then add breathing room.

THE SPEAKER GATE IS IN THE CODE, not in the instructions. Off-camera voices are removed from every
segment before anything is cut (gate.publishable_pieces), and each piece carries walls that no
cut point may cross however it was found.

Every distinct stretch is encoded once into parts/ and clips are joined from parts without
re-encoding, so a body shared by three hooks is bit-identical in all three and a re-run is cheap.
The result is ROUGH on purpose: the whole frame, no loudness change, no text. Text, captions and
reframing belong to later steps.
"""
from __future__ import annotations

import os
import re
import tempfile

from smf.video import cutlist, gate
from smf.video.common import (CUT_LIST_FILE, Transcript, VideoError, as_brand, fmt_ts, has_audio, join_parts, locate,
                              merge_report, output_dir, probe_duration, probe_shape, programs, resolve, run,
                              stream_of, tokens_of, usable_part, write_json_atomic)
from smf.video.common import lcs as _lcs
from smf.brands import replace_patiently

CROSSFADE = 0.04       # a 40 ms fade on the sound at each part's edges, so joins never click
STAMP_SLACK = 1.35     # a written time may be rounded down: the real word can begin this much later
SEARCH_BACK = 1.0      # ... or the time may run a little late
SEARCH_EXTRA = 0.75
MAX_LEAD = 0.60        # a cut lands at most this far outside its boundary word
SENTENCE_GAP = 0.25    # a pause this long counts as the start of a sentence
CLUSTER_GAP = 45.0     # cut points closer together than this are listened to in one go
CLUSTER_CTX = 6.0      # extra seconds listened to either side of a cluster
HEAD_MARGIN = 0.20
TAIL_MARGIN = 0.25
SILENCE_DB = -35
SILENCE_MIN = 0.15
FALLBACK_PAD = 1.0
SAME_FILE_TOLERANCE = 2.0
ALARM_MIN_EDGES = 4
ALARM_RATE = 0.5

# The pad that keeps off-camera voices out is only real if it is wider than the distance a cut is
# allowed to travel. This is checked where both numbers can be seen, not left to a comment.
if gate.EXCLUDE_PAD <= MAX_LEAD:
    raise AssertionError("gate.EXCLUDE_PAD must be larger than rough_cut.MAX_LEAD")


class CutListProblems(VideoError):
    """The cut list has errors. Carries the findings so they can be shown one per line."""

    def __init__(self, findings):
        self.findings = findings
        errors = [f for f in findings if f.severity == "ERROR"]
        VideoError.__init__(self, "The cut list has %d problem%s to fix before anything is cut."
                            % (len(errors), "" if len(errors) == 1 else "s"))


# ----------------------------------------------------------------------------- where a cut lands
def head_cut(onset, silences):
    """Just before a word's attack. A measured pause ending near the word is a better guide than
    the model's own onset, which can swallow the pause or run late; stay inside that pause so the
    previous word's tail is not clipped either."""
    near = [s for s in silences if -0.3 <= s[1] - onset <= 0.5]
    if near:
        s_start, s_end = min(near, key=lambda s: abs(s[1] - onset))
        cut = max(s_start + 0.05, s_end - 0.15)
    else:
        cut = onset - 0.15
    return max(0.0, cut, onset - MAX_LEAD)


def tail_cut(end, silences):
    """Just after a word really finishes: the later of the model's word end and the measured drop
    in sound, plus breathing room. A sliver of the next word is acceptable in a rough cut; a
    chopped last word is not."""
    near = [s for s, _e in silences if abs(s - end) <= 0.5]
    return min(max([end] + near) + 0.3, end + MAX_LEAD)


def match_text(words, phrase_tokens, lo, hi, anchor_last, prefer):
    """Index of the word that opens (or closes) the quoted phrase, or None.

    The first (or last) quoted token must match exactly inside [lo, hi]; the next few tokens are
    then compared loosely, so a stutter, a contraction or one misheard word does not lose the
    match. At least one neighbour has to agree. Numbers are ignored on both sides. When two places
    score the same (a line said twice), the one nearer the written time wins."""
    tokens = [t for t in phrase_tokens if t]
    if not tokens:
        return None
    if anchor_last:
        tokens = tokens[::-1]
    stream = stream_of([w[2] for w in words])
    best, best_key = None, None
    for si, (i, tok) in enumerate(stream):
        ref = words[i][1] if anchor_last else words[i][0]
        if tok != tokens[0] or not lo <= ref <= hi:
            continue
        if anchor_last:
            neighbours = [t for _i, t in stream[max(0, si - 8):si]][::-1]
        else:
            neighbours = [t for _i, t in stream[si + 1:si + 9]]
        matched = 1 + _lcs(tokens[1:], neighbours)
        if matched < 2:
            continue
        key = (matched, -abs(ref - prefer))
        if best_key is None or key > best_key:
            best, best_key = i, key
    return best


def _window(stamp, wall_lo, wall_hi):
    lo, hi = stamp - SEARCH_BACK, stamp + STAMP_SLACK + SEARCH_EXTRA
    if wall_lo is not None:
        lo = max(lo, wall_lo)
    if wall_hi is not None:
        hi = min(hi, wall_hi)
    return lo, hi


def snap_head(words, silences, stamp, text="", wall_lo=None, wall_hi=None):
    """(cut, method) for the start of a segment, from word times; None when they cannot help."""
    lo, hi = _window(stamp, wall_lo, wall_hi)
    if text:
        i = match_text(words, tokens_of(text)[:6], lo, hi, anchor_last=False, prefer=stamp)
        if i is not None:
            return head_cut(words[i][0], silences), "text"
    near = [(i, w) for i, w in enumerate(words) if max(stamp - 0.02, lo) <= w[0] <= min(stamp + STAMP_SLACK, hi)]
    if not near:
        return None
    chosen = None
    for i, w in near:                                     # a sentence start is the best place to open
        if i > 0 and words[i - 1][2][-1:] in ".?!":
            chosen = w
            break
    if chosen is None:
        for i, w in near:
            if i == 0 or w[0] - words[i - 1][1] >= SENTENCE_GAP:
                chosen = w
                break
    chosen = chosen or near[0][1]
    return head_cut(chosen[0], silences), "word"


def snap_tail(words, silences, stamp, text="", wall_lo=None, wall_hi=None):
    """(cut, method) for the end of a segment, from word times; None when they cannot help."""
    lo, hi = _window(stamp, wall_lo, wall_hi)
    if text:
        i = match_text(words, tokens_of(text)[-6:], lo, hi, anchor_last=True, prefer=stamp)
        if i is not None:
            return tail_cut(words[i][1], silences), "text"
    for w in words:
        if w[1] >= stamp - 0.02:
            if w[1] > stamp + STAMP_SLACK or (wall_hi is not None and w[1] > wall_hi):
                return None                               # the next word to end is implausibly far away
            return tail_cut(w[1], silences), "word"
    return None


def head_from_silences(silences, stamp):
    """No word times at all: the first pause that ENDS just after the time is where speech starts."""
    ends = [e for _s, e in silences if stamp - 0.35 <= e <= stamp + STAMP_SLACK]
    return max(0.0, min(ends) - HEAD_MARGIN) if ends else None


def tail_from_silences(silences, stamp):
    starts = [(s, e) for s, e in silences if s >= stamp - 0.15 and s <= stamp + STAMP_SLACK + 0.6]
    if not starts:
        return None
    s, e = min(starts)
    return min(e - 0.02, s + TAIL_MARGIN)


def clamp(cut, wall_lo, wall_hi, duration):
    """The last word on where a cut may sit: inside the video, and never past a wall."""
    if wall_lo is not None:
        cut = max(cut, wall_lo)
    if wall_hi is not None:
        cut = min(cut, wall_hi)
    return min(max(0.0, cut), duration)


# ----------------------------------------------------------------------------- listening
def find_silences(source, win_start, win_end):
    """Pauses in the sound between two times: [(start, end)] in the video's own clock."""
    ff, _fp = programs()
    win_start = max(0.0, win_start)
    if win_end - win_start <= 0:
        return []
    r = run([ff, "-hide_banner", "-nostats", "-ss", "%.3f" % win_start, "-t", "%.3f" % (win_end - win_start),
             "-i", source, "-vn", "-af", "silencedetect=noise=%ddB:d=%s" % (SILENCE_DB, SILENCE_MIN),
             "-f", "null", "-"], "listen for pauses")
    out, cur = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            cur = max(0.0, float(m.group(1))) + win_start
            continue
        m = re.search(r"silence_end:\s*(-?[\d.]+)", line)
        if m and cur is not None:
            out.append((cur, float(m.group(1)) + win_start))
            cur = None
    if cur is not None:                                   # the pause runs past the end of the window
        out.append((cur, win_end))
    return out


_model = {}


def speech_model():
    """The small local speech model, loaded once. It is used to CHECK and to LINE UP, never as the
    transcript of record. Returns None when it cannot be loaded; callers decide what that means."""
    if "m" not in _model:
        os.environ.setdefault("HF_HUB_VERBOSITY", "error")            # it needs no account; do not nag for one
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        try:
            from faster_whisper import WhisperModel
            try:
                _model["m"] = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
            except Exception:
                _model["m"] = WhisperModel("base", device="cpu", compute_type="int8")     # first use: fetch it once
        except Exception:
            _model["m"] = None
    return _model["m"]


def listen_with_model(source):
    """A listener that transcribes a window of the REAL video with the local model. This is
    independent evidence: if the times belong to some other file, the quoted words will not be
    there, and that is exactly what should be found out before rendering."""
    model = speech_model()
    if model is None:
        return None
    ff, _fp = programs()

    def listen(win_start, win_end):
        with tempfile.TemporaryDirectory(prefix="smf-listen-") as scratch:
            wav = os.path.join(scratch, "window.wav")
            run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", "%.3f" % win_start,
                 "-t", "%.3f" % (win_end - win_start), "-i", source, "-vn", "-ac", "1", "-ar", "16000", wav],
                "pull a stretch of sound out of the video")
            segments, _info = model.transcribe(wav, word_timestamps=True)
            return [(win_start + w.start, win_start + w.end, w.word.strip())
                    for seg in segments for w in (seg.words or []) if w.word.strip()]
    return listen


def listen_from_transcript(transcript, offset):
    """A listener that simply reads the transcript's own word times. Fast and needs no model, but
    it is the transcript agreeing with itself: it cannot notice a wrong video file."""
    words = [(w["start"] + offset, w["end"] + offset, w["word"]) for w in transcript.words]

    def listen(win_start, win_end):
        return [w for w in words if win_start <= w[0] <= win_end]
    return listen


class Snapper(object):
    """Word times and pauses around every cut point. Cut points that sit close together are
    listened to in ONE window: a model's word times wobble a little between separate runs, but
    inside a single run the spacing of words and gaps is dependable."""

    def __init__(self, listen, silences, duration):
        self.listen, self.silences, self.duration = listen, silences, duration
        self.windows = []

    def prepare(self, stamps, say=None):
        stamps = sorted(set(stamps))
        if not stamps:
            return
        groups, group = [], [stamps[0]]
        for s in stamps[1:]:
            if s - group[-1] <= CLUSTER_GAP:
                group.append(s)
            else:
                groups.append(group)
                group = [s]
        groups.append(group)
        for g in groups:
            a = max(0.0, g[0] - CLUSTER_CTX)
            b = min(self.duration, g[-1] + STAMP_SLACK + CLUSTER_CTX)
            if say:
                say("  listening to %s - %s (%d cut point%s)" % (fmt_ts(a), fmt_ts(b), len(g), "" if len(g) == 1 else "s"))
            self.windows.append((a, b, self.listen(a, b), self.silences(a, b)))

    def near(self, stamp):
        for a, b, words, silences in self.windows:
            if a <= stamp <= b:
                return words, silences
        return [], []


# ----------------------------------------------------------------------------- planning
def plan_clips(cl, transcript, policy, only=None):
    """The cut list as concrete work, in VIDEO time, with off-camera voices already taken out.
    Returns (clips, skipped). Nothing here touches a video file."""
    offset = cl.offset
    turns = transcript.turns()
    gated = policy.labelled and not policy.everyone_on_camera
    clips, skipped = [], []
    wanted = {o.upper() for o in only} if only else None
    for clip in cl.clips():
        if wanted is not None and clip.id.upper() not in wanted:
            continue
        if clip.gate == gate.DROP:
            skipped.append({"id": clip.id, "status": "skipped-drop",
                            "why": "marked DROP: this brand's rules say it must never publish"})
            continue
        segments = []
        for seg in clip.segments:
            if gated:
                pieces = gate.publishable_pieces(seg, turns, policy)
            else:
                pieces = [dict(seg, wall_lo=None, wall_hi=None)]
            for p in pieces:
                segments.append({
                    "role": seg["role"], "start": p["start"] + offset, "end": p["end"] + offset,
                    "starts_with": p.get("starts_with", ""), "ends_with": p.get("ends_with", ""),
                    "wall_lo": None if p["wall_lo"] is None else p["wall_lo"] + offset,
                    "wall_hi": None if p["wall_hi"] is None else p["wall_hi"] + offset})
        if not segments:
            skipped.append({"id": clip.id, "status": "nothing-left",
                            "why": "once the off-camera voice was taken out, nothing was left to cut"})
            continue
        clips.append({"clip": clip, "segments": segments})
    if wanted is not None:
        known = {c.id.upper() for c in cl.clips()}
        missing = sorted(wanted - known)
        if missing:
            raise VideoError("The cut list has no clip called %s. Its clips are: %s."
                             % (", ".join(missing), ", ".join(sorted(known)) or "none"))
    return clips, skipped


def resolve_cuts(planned, snapper, source, duration):
    """Turn every requested start and end into a real cut point, once each. Two clips that share
    a body ask for the same points, get the same answers, and so share the same encoded part."""
    heads, tails = {}, {}

    def head(seg):
        stamp, text, lo, hi = seg["start"], seg["starts_with"], seg["wall_lo"], seg["wall_hi"]
        found = None
        if snapper is not None:
            words, silences = snapper.near(stamp)
            found = snap_head(words, silences, stamp, text, lo, hi)
        if found is None:
            cut = head_from_silences(find_silences(source, stamp - 1.2, stamp + STAMP_SLACK + 0.4), stamp)
            found = (cut, "silence") if cut is not None else (stamp - FALLBACK_PAD, "pad")
        return clamp(found[0], lo, hi, duration), found[1]

    def tail(seg):
        stamp, text, lo, hi = seg["end"], seg["ends_with"], seg["wall_lo"], seg["wall_hi"]
        found = None
        if snapper is not None:
            words, silences = snapper.near(stamp)
            found = snap_tail(words, silences, stamp, text, lo, hi)
        if found is None:
            cut = tail_from_silences(find_silences(source, stamp - 0.6, stamp + STAMP_SLACK + 0.6), stamp)
            found = (cut, "silence") if cut is not None else (stamp + FALLBACK_PAD, "pad")
        return clamp(found[0], lo, hi, duration), found[1]

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
                raise VideoError("Clip %s: after lining up on the words, one of its pieces came out empty "
                                 "(%s to %s). Check that piece's times and quoted words in the cut list."
                                 % (item["clip"].id, fmt_ts(a), fmt_ts(b)))
            seg["cut"], seg["snap"] = [round(a, 3), round(b, 3)], [how_a, how_b]
    return planned


def snap_alarm(planned, listened_with):
    """The mix of methods is evidence. A right video finds nearly all its quoted words; a wrong
    one (or a wrong offset) finds almost none, because the tool is listening to places where
    those words are not. Only meaningful when the real video was listened to."""
    if listened_with != "speech-model":
        return ""
    anchored = text = 0
    for item in planned:
        for seg in item["segments"]:
            for quote, how in ((seg["starts_with"], seg["snap"][0]), (seg["ends_with"], seg["snap"][1])):
                if quote:
                    anchored += 1
                    text += 1 if how == "text" else 0
    if anchored >= ALARM_MIN_EDGES and text / float(anchored) < ALARM_RATE:
        return ("Only %d of %d quoted boundary words could be heard near their times in this video. That "
                "usually means the cut list's times belong to a different video file, or the Offset is wrong "
                "(size or direction)." % (text, anchored))
    return ""


# ----------------------------------------------------------------------------- encoding
def encode_part(source, start, end, out_path, height=0, fade=CROSSFADE):
    """One stretch of the source, re-encoded with the software encoder every computer has. `height`
    optionally makes a smaller working copy of a very large master; cut points are unaffected."""
    ff, _fp = programs()
    dur = end - start
    vf = "setpts=PTS-STARTPTS"
    if height:
        vf += ",scale=-2:%d:flags=lanczos" % int(height)
    graph = ("[0:v]%s[v];[0:a]asetpts=PTS-STARTPTS,afade=t=in:st=0:d=%s,afade=t=out:st=%.3f:d=%s[a]"
             % (vf, fade, max(0.0, dur - fade), fade))
    # Written under a working name and renamed only when complete, so a run that is stopped half
    # way never leaves a broken file sitting under a finished file's name.
    working = out_path[:-4] + ".working.mp4"
    try:
        run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", "%.3f" % start, "-t", "%.3f" % dur, "-i", source,
             "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", working], "encode %s - %s" % (fmt_ts(start), fmt_ts(end)))
        replace_patiently(working, out_path)
    finally:
        if os.path.exists(working):
            os.remove(working)


def part_name(start, end, height=0):
    # The height is part of the name because it is part of the result: without it, a saved
    # small-size part would be silently reused for a full-size rebuild.
    return "part-%010.3f-%010.3f%s.mp4" % (start, end, ("-h%d" % height) if height else "")


# ----------------------------------------------------------------------------- the whole job
def rough_cut(brand, recording, cut_list_path=None, only=None, dry_run=False, listen="auto",
              everyone_on_camera=False, anyway=False, height=0, say=None, listener=None):
    """Make the rough cuts for one recording. Returns the report (also written beside the clips).

    listen   "auto"        the local speech model if it is available, else the transcript's word times
             "model"       the local speech model, or stop
             "transcript"  the transcript's own word times (fast; cannot notice a wrong video file)
             "none"        pauses and pads only
    `listener` replaces all of that with a function (win_start, win_end) -> [(onset, end, text)].
    """
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    transcript = Transcript.load(brand, recording)
    policy = gate.SpeakerPolicy.for_transcript(brand, transcript, everyone_on_camera)
    policy.require_checkable()
    out_dir = output_dir(brand, recording, "rough")
    path = cut_list_path or output_dir(brand, recording, CUT_LIST_FILE)
    cl = cutlist.load(path)
    findings = cutlist.validate(cl, transcript, brand, recording=recording, policy=policy)
    if not cutlist.is_valid(findings):
        raise CutListProblems(findings)
    rules = gate.GateRules.for_brand(brand)

    source = resolve(brand, recording, cl.reference.get("cut_from"))
    if not has_audio(source):
        raise VideoError("'%s' has no sound in it, so clips cannot be lined up on words." % os.path.basename(source))
    duration = probe_duration(source)
    made_from = (transcript.source or {}).get("duration")
    if made_from and cl.offset == 0 and abs(float(made_from) - duration) > SAME_FILE_TOLERANCE:
        raise VideoError("'%s' is %s long, but the transcript was made from a file %s long. They are not the same "
                         "video, so the times will not line up. Cut from the file that was transcribed, or "
                         "transcribe this one." % (os.path.basename(source), fmt_ts(duration), fmt_ts(float(made_from))))
    shape = probe_shape(source)
    if shape["orientation"] == "unknown":
        raise VideoError("'%s' has sound but no picture. Clips are cut from a video, so name the video file under "
                         "'Cut from' in the cut list." % os.path.basename(source))

    planned, skipped = plan_clips(cl, transcript, policy, only)
    stamps = [seg[k] for item in planned for seg in item["segments"] for k in ("start", "end")]

    listened_with = "pauses only"
    if listener is not None:
        listened_with = "a supplied listener"
    elif listen in ("auto", "model"):
        listener = listen_with_model(source)
        if listener is not None:
            listened_with = "speech-model"
        elif listen == "model":
            raise VideoError("The small speech model could not be loaded. Run: python factory.py doctor --deep")
    if listener is None and listen in ("auto", "transcript") and transcript.word_level:
        listener, listened_with = listen_from_transcript(transcript, cl.offset), "transcript"
        say("Lining cuts up with the transcript's own word times (the video itself is not being listened to).")
    snapper = None
    if listener is not None and stamps:
        snapper = Snapper(listener, lambda a, b: find_silences(source, a, b), duration)
        say("Finding the quoted words around %d cut points..." % len(stamps))
        snapper.prepare(stamps, say)

    resolve_cuts(planned, snapper, source, duration)
    alarm = snap_alarm(planned, listened_with)
    if alarm and not dry_run and not anyway:
        raise VideoError(alarm + " Nothing was rendered. Check 'Cut from' and 'Offset' in the cut list. "
                         "If you are sure they are right, run again with --anyway.")

    parts_dir = os.path.join(out_dir, "parts")
    if not dry_run:
        os.makedirs(parts_dir, exist_ok=True)
    report = {"schema": 1, "kind": "rough", "brand": brand.id, "recording": recording,
              "source": locate(brand, source), "source_duration": round(duration, 3), "shape": shape,
              "cut_list": locate(brand, path), "offset": cl.offset, "speaker_check": policy.status,
              "on_camera": policy.on_camera(), "kept_out": policy.off_camera(), "listened_with": listened_with,
              "dry_run": bool(dry_run), "alarm": alarm, "clips": []}

    for item in planned:
        clip, segments = item["clip"], item["segments"]
        expected = sum(s["cut"][1] - s["cut"][0] for s in segments)
        entry = {"id": clip.id, "file": clip.file_stem + ".mp4", "body": clip.body.key, "hook": clip.hook.number,
                 "title": clip.body.title, "hook_text": clip.hook.text, "on_screen_text": clip.body.on_screen_text,
                 "lower_third": clip.body.lower_third, "gate": clip.gate,
                 "disclaimer": rules.disclaimer if clip.gate == gate.HOLD else "",
                 "sign_off_by": rules.sign_off_by if clip.gate == gate.HOLD else "",
                 "signed_off": clip.body.signed_off,
                 "segments": [{"role": s["role"], "requested": [round(s["start"], 3), round(s["end"], 3)],
                               "cut": s["cut"], "duration": round(s["cut"][1] - s["cut"][0], 3),
                               "walls": [s["wall_lo"], s["wall_hi"]],
                               "snap": s["snap"], "starts_with": s["starts_with"],
                               "ends_with": s["ends_with"], "part": "parts/" + part_name(s["cut"][0], s["cut"][1], height)}
                              for s in segments],
                 "pieces": [s["cut"] for s in segments], "expected_duration": round(expected, 2)}
        say("%s  %s" % (clip.id, clip.body.title))
        for s in entry["segments"]:
            say("  %-4s %s - %s  ->  %s - %s   (start: %s, end: %s)"
                % (s["role"], fmt_ts(s["requested"][0]), fmt_ts(s["requested"][1]), fmt_ts(s["cut"][0], 2),
                   fmt_ts(s["cut"][1], 2), s["snap"][0], s["snap"][1]))
        if dry_run:
            entry["status"] = "planned"
        else:
            parts = []
            for s in entry["segments"]:
                p = os.path.join(out_dir, *s["part"].split("/"))
                want = min(s["cut"][1], duration) - s["cut"][0]
                if not usable_part(p, want):
                    encode_part(source, s["cut"][0], s["cut"][1], p, height)
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
        report_path = os.path.join(out_dir, "rough-cut-report.json")
        write_json_atomic(report_path, merge_report(report_path, report, partial=bool(only)))
    return report
