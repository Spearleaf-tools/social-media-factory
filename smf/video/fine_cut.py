"""fine_cut.py - rough cuts in, fine cuts out: fillers gone, dead air tightened, clean heads and tails.

This is the pass an editor would make on a fixed-camera talking shot, done by arithmetic on the
word times the recording already has. It costs nothing per clip and it is repeatable.

SMOOTH, NOT SURGICAL. Every removal is a visible jump on a fixed camera, so the settings are
deliberately gentle:

  * only a pause longer than `gap_max` is touched, and a generous beat is left either side so the
    speaker's rhythm survives;
  * a filler word ("um", "uh") is taken only when it sits in its own pocket of silence. One wedged
    tight between two words leaves nowhere to hide a cut, the removal comes out shorter than
    `min_removal`, and it is skipped. That makes filler removal self-limiting;
  * a kept piece shorter than `min_keep` is absorbed into its neighbour, so there is never a
    stutter of tiny cuts;
  * no real word is ever removed, and no cut ever crosses into a neighbouring word.

BOUNDARIES ARE MEASURED, NOT READ OFF THE TRANSCRIPT. A transcript says WHICH word; the loudness
of the recording says WHERE it stops. A word held for effect is timed at the end of its
recognisable sounds, well before the voice actually dies away, so cutting at "word end plus a bit"
chops the performance. Each boundary is placed on measured quiet and then clamped between the
neighbouring words, which also keeps the tail of whoever spoke just before out of the clip's
first moments.

IT READS WHAT WAS ACTUALLY CUT. The rough cut moves its cut points outward to catch whole words,
so the ranges in its report differ from the ones the cut list asked for. Planning from the
requested times instead would quietly eat first and last words. This reads the report.

It does not remove people, sweeten sound, add text or music. After this step a person watches the
fine cuts and approves them before anything else is made from them.
"""
from __future__ import annotations

import os
import subprocess

from smf.video.common import (Transcript, VideoError, as_brand, fmt_ts, join_parts, locate, merge_report, norm_token,
                              output_dir, probe_duration, programs, read_json, resolve, run, usable_part,
                              write_json_atomic)
from smf.video.rough_cut import encode_part, part_name

FADE = 0.02            # a 20 ms fade on the sound at each piece edge, so joins never click
FILLERS = frozenset("um umm uh uhh uhm er erm ah ahh hmm mm mhm".split())

ENV_HOP = 0.010        # loudness is measured every 10 ms
SIL_HOLD = 0.08        # speech has to stay down this long to count as stopped
HEAD_PAD = 0.25        # room before the first word
TAIL_PAD = 0.40        # room after the last word has died away
CUT_OUT_PAD = 0.20     # room after speech stops, before an internal cut
CUT_IN_PAD = 0.30      # room before the next word, after an internal cut

DEFAULTS = {"gap_max": 1.20, "min_removal": 0.35, "min_keep": 0.50}
SUSPICIOUS_EDGE_LOSS = 0.20


def is_filler(word):
    return norm_token(word) in FILLERS


def frame_snap(t, fps):
    """Cuts on whole frames, so joined pieces do not drift against their sound."""
    return round(t * fps) / fps


class Envelope(object):
    """How loud the recording is, every 10 ms, and from that: where speech really starts and stops."""

    def __init__(self, values):
        import numpy as np
        self.e = np.asarray(values, dtype="float64")
        if not len(self.e):
            raise VideoError("The recording's sound could not be measured.")
        # The line between "speaking" and "not": well above the room's hum, well below talking level.
        quiet, loud = np.percentile(self.e, 20), np.percentile(self.e, 90)
        self.threshold = max(quiet * 3.0, loud * 0.04)
        self.hold = max(1, int(round(SIL_HOLD / ENV_HOP)))

    @classmethod
    def measure(cls, source, rate=16000):
        """Decode the sound once and keep only its loudness. The sound is read in pieces as it is
        decoded, so an hour-long recording does not have to fit in memory."""
        import numpy as np
        ff, _fp = programs()
        hop = int(ENV_HOP * rate)
        hop_bytes = hop * 4
        try:
            proc = subprocess.Popen([ff, "-v", "error", "-i", source, "-vn", "-ac", "1", "-ar", str(rate),
                                     "-f", "f32le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as e:
            raise VideoError("Could not measure the recording's sound: the video program would not start (%s)." % e)
        chunks, carry = [], b""
        while True:
            buf = proc.stdout.read(hop_bytes * 4096)
            if not buf:
                break
            buf = carry + buf
            usable = len(buf) - len(buf) % hop_bytes
            carry = buf[usable:]
            if usable:
                x = np.frombuffer(buf[:usable], dtype=np.float32).astype(np.float64).reshape(-1, hop)
                chunks.append(np.sqrt((x ** 2).mean(axis=1) + 1e-12))
        proc.stdout.close()
        if proc.wait() != 0 or not chunks:
            raise VideoError("The recording's sound could not be measured. Is there sound in the file?")
        return cls(np.concatenate(chunks))

    def _i(self, t):
        return max(0, min(len(self.e) - 1, int(t / ENV_HOP)))

    def speech_ends_after(self, t):
        """The first moment at or after t where it has been quiet for SIL_HOLD."""
        i, quiet = self._i(t), 0
        while i < len(self.e):
            if self.e[i] < self.threshold:
                quiet += 1
                if quiet >= self.hold:
                    return (i - quiet + 1) * ENV_HOP
            else:
                quiet = 0
            i += 1
        return len(self.e) * ENV_HOP

    def speech_starts_before(self, t):
        """The latest moment at or before t where speech begins after a quiet stretch."""
        i, quiet = self._i(t), 0
        while i > 0:
            if self.e[i] < self.threshold:
                quiet += 1
                if quiet >= self.hold:
                    return (i + quiet - 1) * ENV_HOP
            else:
                quiet = 0
            i -= 1
        return 0.0


def anchor_index(inside, quote, last):
    """Which word in `inside` is the one the cut list quoted as the segment's first (or last) word.

    A rough cut opens just before a word's attack and may therefore include a scrap of the word
    before it. Anchoring on the quoted words means the fine cut opens on the word that was MEANT,
    and the scrap, which is sometimes the end of someone else's sentence, is dropped. Two quoted
    words are matched when there are two, so a common opener like "the" does not latch on to the
    wrong place."""
    toks = [t for t in (norm_token(w) for w in (quote or "").replace("-", " ").split()) if t]
    default = len(inside) - 1 if last else 0
    if not toks or not inside:
        return default
    heard = [norm_token(w["word"]) for w in inside]
    order = range(len(inside) - 1, -1, -1) if last else range(len(inside))
    want, beside = (toks[-1], toks[-2] if len(toks) > 1 else None) if last else (toks[0], toks[1] if len(toks) > 1 else None)
    step = -1 if last else 1
    single = None
    for i in order:
        if heard[i] != want:
            continue
        j = i + step
        if beside is None or (0 <= j < len(heard) and heard[j] == beside):
            return i
        if single is None:
            single = i
    return single if single is not None else default


def plan_segment(seg_start, seg_end, words, settings=None, envelope=None, starts_with="", ends_with="",
                 walls=(None, None)):
    """(keeps, removals) for one segment of a rough cut, all in VIDEO time.

    keeps      [(start, end)]            the ranges to keep, in order
    removals   [(start, end, reason)]    what was taken out between them, and why
    `words` are the recording's words in VIDEO time. `envelope` is optional: without it the word
    times are used as they are, which is how this is tested without any media. `walls` are the
    rough cut's limits either side of an off-camera voice; the head and tail are allowed to reach
    a little outside the rough cut to let a held word finish, but never past a wall."""
    cfg = dict(DEFAULTS, **(settings or {}))
    # OVERLAP, not containment. The segment opens just before a word's attack and can close a hair
    # before its last word is timed to end. Asking for words wholly inside would drop those two
    # words, and the anchors would then settle on a LATER (or earlier) use of the same word,
    # throwing away a large part of the clip while reporting only a handful of removals.
    inside = [w for w in words if w["end"] > seg_start and w["start"] < seg_end]
    if not inside:
        return [(seg_start, seg_end)], []
    i0 = anchor_index(inside, starts_with, last=False)
    i1 = anchor_index(inside, ends_with, last=True)
    if i1 < i0:
        i0, i1 = 0, len(inside) - 1
    span = inside[i0:i1 + 1]
    kept = [w for w in span if not is_filler(w["word"])]
    if not kept:
        return [(seg_start, seg_end)], []

    position = {id(w): k for k, w in enumerate(words)}

    def neighbour(w, step):
        k = position.get(id(w))
        if k is None or not 0 <= k + step < len(words):
            return None
        return words[k + step]

    def stops(w):
        """Where this word's sound really ends; never later than the next word begins."""
        t = envelope.speech_ends_after(w["end"] - 0.05) if envelope is not None else w["end"]
        nxt = neighbour(w, 1)
        if nxt is not None:
            t = min(t, nxt["start"])
        return max(t, w["end"])

    def starts(w):
        """Where this word's sound really begins; never earlier than the previous word ends."""
        t = envelope.speech_starts_before(w["start"] + 0.05) if envelope is not None else w["start"]
        prv = neighbour(w, -1)
        if prv is not None:
            t = max(t, prv["end"])
        return min(t, w["start"])

    # Head: open a little before the first kept word, never inside the word before it. When that
    # word runs straight into ours there is no room for a pad, so open exactly on the attack.
    onset = starts(kept[0])
    head = onset - HEAD_PAD
    before = neighbour(kept[0], -1)
    if before is not None:
        head = max(head, stops(before) + 0.05)
    head = max(0.0, min(head, onset))

    # Tail: close after the last word has really died away, and before anyone else starts.
    decay = stops(kept[-1])
    tail = decay + TAIL_PAD
    after = neighbour(kept[-1], 1)
    if after is not None:
        tail = min(tail, after["start"])
    tail = max(tail, decay)
    if walls[0] is not None:
        head = max(head, walls[0])
    if walls[1] is not None:
        tail = min(tail, walls[1])
    if tail <= head:
        return [(seg_start, seg_end)], []

    removals = []
    for left, right in zip(kept, kept[1:]):
        a, b = stops(left), starts(right)
        fillers = [w for w in span if is_filler(w["word"])
                   and w["start"] >= left["end"] - 0.01 and w["end"] <= right["start"] + 0.01]
        if (b - a) <= cfg["gap_max"] and not fillers:
            continue
        cut_a, cut_b = a + CUT_OUT_PAD, b - CUT_IN_PAD
        if cut_b - cut_a < cfg["min_removal"]:
            continue                                        # not worth a visible jump
        why = ("filler '%s'" % " ".join(w["word"].strip() for w in fillers)) if fillers else "pause of %.2fs" % (b - a)
        removals.append((cut_a, cut_b, why))

    keeps, cursor = [], head
    for a, b, _why in removals:
        a, b = max(a, head), min(b, tail)
        if b <= cursor:
            continue
        if a > cursor:
            keeps.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < tail:
        keeps.append((cursor, tail))

    merged = []
    for a, b in keeps:
        if merged and (a - merged[-1][1] < 0.02 or b - a < cfg["min_keep"]):
            merged[-1] = (merged[-1][0], b)                 # absorb a sliver rather than stutter
        else:
            merged.append((a, b))
    return merged, removals


def edge_loss(rough_len, keeps, removals):
    """The share of a clip's length that went missing WITHOUT a removal to explain it, which means
    it was lost at the head or the tail. A big number here is not a loose clip being tightened:
    the quoted first or last words matched the wrong place."""
    if not rough_len:
        return 0.0
    fine_len = sum(y - x for x, y in keeps)
    taken = sum(b - a for a, b, _why in removals)
    return (rough_len - fine_len - taken) / rough_len


def probe_fps(path):
    _ff, fp = programs()
    r = run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", path], "read the frame rate")
    num, _, den = r.stdout.strip().partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return fps if 1.0 <= fps <= 240.0 else 30.0


def fine_cut(brand, recording, only=None, dry_run=False, settings=None, say=None, measure=True):
    """Make the fine cuts for one recording from its rough-cut report. Returns the fine-cut report."""
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    rough_dir = output_dir(brand, recording, "rough")
    rough = read_json(os.path.join(rough_dir, "rough-cut-report.json"),
                      "The rough-cut report for '%s' (make the rough cuts first)" % recording)
    transcript = Transcript.load(brand, recording)
    if not transcript.word_level:
        raise VideoError("A fine cut needs the time of every word, and this recording's transcript came from a "
                         "subtitle file, which only has sentence times. Transcribe the recording to get word times, "
                         "or hand the rough cuts to an editor.")
    if rough.get("made_with") == "two cameras":
        # These clips were assembled from two camera files. Tightening them here would re-cut from
        # ONE file and quietly turn them back into single-camera clips.
        raise VideoError("These clips were cut from a two-camera edit, so they cannot be tightened with this step: "
                         "it works from one video file. They are ready for captions and versions as they are.")
    source = resolve(brand, recording, rough.get("source"))
    if not source:
        raise VideoError("The video the rough cuts were made from cannot be found any more. Put it back where it "
                         "was and try again.")
    offset = float(rough.get("offset") or 0.0)
    words = [{"word": w["word"], "start": w["start"] + offset, "end": w["end"] + offset} for w in transcript.words]
    cfg = dict(DEFAULTS, **(settings or {}))
    duration = probe_duration(source)
    fps = probe_fps(source)
    envelope = None
    if measure:
        say("Measuring how loud the recording is, so cuts land on real silence...")
        envelope = Envelope.measure(source)

    out_dir = output_dir(brand, recording, "fine")
    wanted = {o.upper() for o in only} if only else None
    todo = [c for c in rough.get("clips", []) if c.get("status") == "ok"
            and (wanted is None or c["id"].upper() in wanted)]
    if not todo:
        raise VideoError("There are no finished rough cuts to work from%s."
                         % (" with that name" if wanted else ". Make the rough cuts first"))
    if not dry_run:
        os.makedirs(os.path.join(out_dir, "parts"), exist_ok=True)

    report = {"schema": 1, "kind": "fine", "brand": brand.id, "recording": recording, "source": locate(brand, source),
              "offset": offset, "settings": cfg, "dry_run": bool(dry_run), "clips": []}
    for carried in ("source_duration", "shape", "cut_list", "speaker_check", "on_camera", "kept_out"):
        report[carried] = rough.get(carried)
    broken = []
    for clip in todo:
        pieces, removals, segments, rough_len = [], [], [], 0.0
        for seg in clip["segments"]:
            a, b = float(seg["cut"][0]), float(seg["cut"][1])
            rough_len += b - a
            keeps, cuts = plan_segment(a, b, words, cfg, envelope, seg.get("starts_with", ""), seg.get("ends_with", ""),
                                       tuple(seg.get("walls") or (None, None)))
            keeps = [(frame_snap(x, fps), frame_snap(y, fps)) for x, y in keeps]
            keeps = [(x, min(y, duration)) for x, y in keeps if min(y, duration) - x > 0.02]
            pieces += keeps
            removals += cuts
            segments.append({"role": seg.get("role", ""), "starts_with": seg.get("starts_with", ""),
                             "ends_with": seg.get("ends_with", ""),
                             "duration": round(sum(y - x for x, y in keeps), 3)})
        fine_len = sum(y - x for x, y in pieces)
        lost_at_edges = edge_loss(rough_len, pieces, removals)
        entry = {k: clip.get(k, "") for k in ("id", "file", "body", "hook", "title", "hook_text", "on_screen_text",
                                              "lower_third", "gate", "disclaimer", "sign_off_by", "signed_off")}
        entry.update({"rough_duration": round(rough_len, 2), "fine_duration": round(fine_len, 2),
                      "pieces": [[round(x, 3), round(y, 3)] for x, y in pieces], "segments": segments,
                      "removals": [{"from": round(a, 3), "to": round(b, 3), "seconds": round(b - a, 2), "reason": why}
                                   for a, b, why in removals]})
        if lost_at_edges >= SUSPICIOUS_EDGE_LOSS:
            entry["check"] = ("It lost %d%% of its length from its start or end, not from pauses or fillers. That is "
                              "not a loose clip being tightened; its first or last quoted words probably matched the "
                              "wrong place. Check them in the cut list." % round(lost_at_edges * 100))
        fillers = sum(1 for r in removals if r[2].startswith("filler"))
        say("%s  %s -> %s  (%d filler, %d pause%s)" % (clip["id"], fmt_ts(rough_len), fmt_ts(fine_len), fillers,
                                                       len(removals) - fillers, "" if len(removals) - fillers == 1 else "s"))
        if entry.get("check"):
            say("  CHECK: " + entry["check"])
        if dry_run:
            entry["status"] = "planned"
            report["clips"].append(entry)
            continue

        parts = []
        for a, b in pieces:
            p = os.path.join(out_dir, "parts", part_name(a, b))
            if not usable_part(p, b - a):
                encode_part(source, a, b, p, fade=FADE)
            parts.append(p)
        final = os.path.join(out_dir, entry["file"])
        join_parts(parts, final, "join clip %s" % clip["id"])
        actual = probe_duration(final)
        entry["actual_duration"] = round(actual, 2)
        # Everything above reports the PLANNED length. Only measuring the finished file shows a
        # join that silently lost a piece.
        entry["status"] = "ok" if abs(actual - fine_len) <= 1.0 else "duration-mismatch"
        if entry["status"] != "ok":
            broken.append("%s (made %.1fs, planned %.1fs)" % (clip["id"], actual, fine_len))
        report["clips"].append(entry)

    if not dry_run:
        report_path = os.path.join(out_dir, "fine-cut-report.json")
        write_json_atomic(report_path, merge_report(report_path, report, partial=bool(only)))
    if broken:
        raise VideoError("These fine cuts did not come out the length they were planned to be, so do not use them: "
                         "%s. It usually means a saved part was damaged. Delete the 'parts' folder inside the fine "
                         "cuts folder and run it again." % "; ".join(broken))
    return report
