"""sync.py - line two recordings of one conversation up by their sound: how far apart, and WHICH WAY.

Two cameras are never started at the same instant, and a transcript is often made from a different
file than the one the clips are cut from. Every later step needs one number per pair of files:

    time_in_the_other_file = time_in_the_reference_file + offset

That is the same rule the cut list uses for its `Offset` line (video time = transcript time +
offset), so a number measured here can be written there unchanged, sign and all.

HOW IT IS MEASURED
  coarse   The loudness of each whole recording, a hundred values a second, is compared at every
           possible shift. It is cheap, it never holds a whole recording's sound in memory, and it
           copes with one camera being started minutes after the other.
  fine     Several short stretches, spread from the beginning of the recording to its end, are
           each searched for inside the other file at 16 kHz. Every stretch gives its own answer.
           The answer reported is the MEDIAN: one odd stretch (a slammed door, a passage where
           nobody speaks) cannot pull it, and when two clocks run at very slightly different
           speeds the median sits in the middle of the drift instead of at one end of it.
  refuse   If the stretches do not agree, there is no offset to report, and none is. Stretches
           that contradict each other are what two recordings of DIFFERENT conversations look
           like, and a confident number for those would be worse than no number.

THE SIGN IS HALF THE ANSWER
  An offset with the wrong sign is not a little wrong. It moves every cut twice as far from the
  truth as doing nothing would have. And it hides: a check that converts times back with the same
  number agrees with either sign, so it proves nothing at all. The check here is physical. Shift
  one file by the offset, LISTEN to both again, and require that what is left over is about
  zero. With the sign flipped, what is left over is twice the offset (or no match at all), and the
  measurement is refused. `check_offset` is that check, and it can be pointed at any number,
  including one a person typed.

WITHOUT THE FILE THAT WAS TRANSCRIBED
  `measure_transcript_offset` can work from the transcript alone. The words' own times say when
  somebody was talking; the video's loudness says when there was sound. Those two patterns are
  lined up the same way, coarse then fine then checked. It is less exact than sound against
  sound (tenths of a second, not thousandths), which is plenty for a cut list: the rough cut
  lines every cut up on the words themselves afterwards.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from smf.video.common import VideoError, fmt_ts, has_audio, probe_duration, programs, run

LOUDNESS_RATE = 100          # the coarse pass compares loudness measured this many times a second
MIN_OVERLAP = 6.0            # two recordings that share less than this cannot be lined up
COARSE_TRIES = 3             # how many of the coarse pass's best guesses the fine pass may test
MAX_WINDOWS = 7
CHECK_REACH_MAX = 30.0       # the check looks at most this far either side of where things should be
DRIFT_WORTH_SAYING = 0.04    # seconds across the recording: about one frame
DRIFT_TOO_MUCH = 0.24        # more than this from end to end and no single offset keeps lips in sync

# The two ways of comparing, as data. `window` is (shortest, longest) stretch in seconds;
# `margin` is how far either side of the coarse guess a stretch is searched for; `exclude` is how
# much of the match's own neighbourhood is ignored when asking "does this match stand out".
# `second_look` is the wider search given to a stretch that was not found near the coarse guess:
# a stretch that turns up clearly SOMEWHERE ELSE is a contradiction, not a passage to skip over.
#
# A stretch is CLEAR when its best match stands `clear_z` robust deviations above every other
# position, and the runner-up is no better than `runner_up` of it. How GOOD the match is
# (`clear_score`) is only a floor. Measured on real conversation, the score barely tells a true
# match from a false one, because two microphones, or words against loudness, never match well;
# how far the match STANDS OUT does. There, unrelated speech never stood out by more than about
# 6 (sound) or 5 (words), and the true place never by less than about 100 (sound) or 6.5 (words).
# The words method has the thinner margin, so it also needs more stretches to agree (`need`:
# how many clear stretches, when fewer than five were tried and when five or more were).
BY_SOUND = {"name": "sound", "rate": 16000, "window": (3.0, 30.0), "margin": 0.75, "second_look": 20.0,
            "exclude": 0.015, "clear_score": 0.01, "clear_z": 10.0, "runner_up": 0.90, "need": (2, 3),
            "agree_within": 0.06, "residual_limit": 0.03, "check_window": 8.0, "check_reach": 10.0}
BY_WORDS = {"name": "words", "rate": LOUDNESS_RATE, "window": (30.0, 120.0), "margin": 4.0, "second_look": 30.0,
            "exclude": 1.0, "clear_score": 0.15, "clear_z": 5.5, "runner_up": 0.92, "need": (3, 3),
            "agree_within": 0.25, "residual_limit": 0.25, "check_window": 30.0, "check_reach": 10.0}


class SyncRefused(VideoError):
    """No trustworthy offset exists for these two. The message says why, in plain words."""


def _np():
    import numpy
    return numpy


# ----------------------------------------------------------------------------- something to listen to
class Sound(object):
    """One recording's sound, read a stretch at a time so an hour of it never sits in memory."""

    def __init__(self, name, duration, rate):
        self.name, self.duration, self.rate = name, float(duration), int(rate)

    def read(self, start, seconds):
        """The samples from `start` for `seconds`, as floats. Shorter when the recording ends first."""
        raise NotImplementedError

    def loudness(self):
        """How loud it is, LOUDNESS_RATE times a second, for the whole recording."""
        raise NotImplementedError

    def outline(self):
        """The whole recording as the coarse pass sees it: loudness on a level scale."""
        return _shape(self.loudness())


class ArraySound(Sound):
    """Sound that is already in memory. Used by the tests, and for the words-against-loudness
    comparison, where both sides are small."""

    def __init__(self, samples, rate, name="sound"):
        np = _np()
        self.samples = np.asarray(samples, dtype="float64")
        Sound.__init__(self, name, len(self.samples) / float(rate), rate)

    def read(self, start, seconds):
        a = max(0, int(round(start * self.rate)))
        return self.samples[a:a + int(round(seconds * self.rate))]

    def loudness(self):
        np = _np()
        if self.rate == LOUDNESS_RATE:
            return self.samples
        hop = self.rate // LOUDNESS_RATE
        usable = len(self.samples) - len(self.samples) % hop
        if usable <= 0:
            return np.zeros(0)
        return np.sqrt((self.samples[:usable].reshape(-1, hop) ** 2).mean(axis=1) + 1e-12)

    def outline(self):
        # A track that is already a pattern over time (talking / not talking, or loudness that
        # has been levelled once) is only centred; levelling it twice would mangle it.
        return _standard(self.samples) if self.rate == LOUDNESS_RATE else Sound.outline(self)


class FileSound(Sound):
    """The sound inside a video or audio file, read with the Factory's own video program."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        if not os.path.isfile(self.path):
            raise VideoError("'%s' cannot be found." % os.path.basename(path))
        if not has_audio(self.path):
            raise SyncRefused("'%s' has no sound in it, so it cannot be lined up by sound. If you know how far "
                              "apart the recordings are, you can say so instead." % os.path.basename(path))
        Sound.__init__(self, os.path.basename(path), probe_duration(self.path), BY_SOUND["rate"])
        self._loud = None

    def read(self, start, seconds):
        np = _np()
        ff, _fp = programs()
        # The resampler is told where time zero is, so a sound track that begins a little after
        # its picture comes back padded with silence rather than quietly shifted.
        r = run([ff, "-v", "error", "-ss", "%.6f" % max(0.0, start), "-t", "%.6f" % max(0.0, seconds),
                 "-i", self.path, "-vn", "-ac", "1", "-ar", str(self.rate),
                 "-af", "aresample=async=1:first_pts=0", "-f", "s16le", "-"],
                "listen to '%s'" % self.name, binary=True)
        return np.frombuffer(r.stdout, dtype="<i2").astype("float64") / 32768.0

    def loudness(self):
        if self._loud is None:
            from smf.video.fine_cut import Envelope
            self._loud = Envelope.measure(self.path).e
        return self._loud


def as_sound(thing):
    if isinstance(thing, Sound):
        return thing
    if isinstance(thing, (str, os.PathLike)) and str(thing).strip():
        return FileSound(str(thing))
    raise VideoError("No recording was named to line up.")


def same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


# ----------------------------------------------------------------------------- the result
@dataclass
class Offset:
    """other_time = reference_time + seconds. Everything else is the evidence for that number."""
    seconds: float
    spread: float = 0.0              # the furthest any clear stretch's answer sat from the median
    confidence: float = 0.0          # share of the stretches tried that were clear AND agreed (0 to 1)
    method: str = ""                 # sound | words | same-file | given
    windows: list = field(default_factory=list)
    drift_per_hour: float = 0.0
    residual: float = None           # what was left over after shifting by the offset and listening again
    checked: bool = False
    notes: list = field(default_factory=list)

    @property
    def confidence_word(self):
        return "high" if self.confidence >= 0.8 else "medium" if self.confidence >= 0.5 else "low"

    def as_dict(self):
        return {"seconds": self.seconds, "spread": self.spread, "confidence": self.confidence,
                "confidence_word": self.confidence_word, "method": self.method, "checked": self.checked,
                "residual": self.residual, "drift_per_hour": self.drift_per_hour, "windows": self.windows,
                "notes": self.notes}


def in_words(offset, reference="the first file", other="the second file", at=60.0, both_recordings=True):
    """The offset as a sentence nobody can read backwards: one concrete moment, in both clocks.
    `both_recordings=False` is for a transcript against a video, where only one side was 'started'."""
    seconds = offset.seconds if isinstance(offset, Offset) else float(offset)
    if abs(seconds) < 0.0005:
        return "%s and %s share one clock: the same moment has the same time in both." % (
            reference[:1].upper() + reference[1:], other)
    at = max(at, abs(seconds) + 1.0)
    example = "A moment at %s in %s is at %s in %s." % (fmt_ts(at, 2), reference, fmt_ts(at + seconds, 2), other)
    if not both_recordings:
        return example
    rolling_first, rolling_second = (other, reference) if seconds > 0 else (reference, other)
    return "%s was already recording %.3f seconds before %s started. %s" % (
        rolling_first[:1].upper() + rolling_first[1:], abs(seconds), rolling_second, example)


# ----------------------------------------------------------------------------- finding one thing in another
def locate_inside(needle, haystack, exclude=0):
    """Where `needle` sits inside `haystack` (same rate; the haystack is the longer one).

    Returns None when there is nothing to compare, otherwise
    {"index", "score", "z", "runner_up"}: the best position, how good the match is there on a scale
    where 1.0 is identical, how far it stands above every position outside its own neighbourhood
    (in robust deviations), and the best score outside that neighbourhood. A repeating sound (a
    hum, a pure tone) matches in many places equally well; the runner-up is how that shows."""
    np = _np()
    needle = np.asarray(needle, dtype="float64")
    haystack = np.asarray(haystack, dtype="float64")
    n, m = len(needle), len(haystack)
    if n < 16 or m < n:
        return None
    centred = needle - needle.mean()
    energy = float(np.dot(centred, centred))
    if energy <= 1e-12:
        return None
    size = 1 << int(np.ceil(np.log2(m + n)))
    raw = np.fft.irfft(np.fft.rfft(haystack, size) * np.conj(np.fft.rfft(centred, size)), size)[:m - n + 1]
    total = np.concatenate(([0.0], np.cumsum(haystack)))
    squares = np.concatenate(([0.0], np.cumsum(haystack * haystack)))
    local = (squares[n:] - squares[:-n]) - (total[n:] - total[:-n]) ** 2 / n      # energy under the needle
    score = np.zeros(len(raw))
    alive = local > 1e-9 * max(1.0, float(local.max()))
    score[alive] = raw[alive] / np.sqrt(energy * local[alive])
    k = int(np.argmax(score))
    rest = np.concatenate((score[:max(0, k - exclude)], score[k + exclude + 1:]))
    if len(rest) < 8:
        return {"index": k, "score": float(score[k]), "z": 0.0, "runner_up": float(score[k])}
    middle = float(np.median(rest))
    sigma = 1.4826 * float(np.median(np.abs(rest - middle)))
    return {"index": k, "score": float(score[k]), "z": (float(score[k]) - middle) / max(sigma, 1e-9),
            "runner_up": float(rest.max())}


def is_clear(found, how):
    return (found is not None and found["score"] >= how["clear_score"] and found["z"] >= how["clear_z"]
            and found["runner_up"] <= how["runner_up"] * found["score"])


def _standard(values):
    np = _np()
    v = np.asarray(values, dtype="float64")
    if not len(v):
        return v
    spread = v.std()
    return (v - v.mean()) / spread if spread > 1e-9 else v * 0.0


def _shape(loudness):
    """Loudness on a scale where a quiet recording and a loud one of the same talk look alike."""
    np = _np()
    e = np.asarray(loudness, dtype="float64")
    if not len(e):
        return e
    return _standard(np.log(e + 0.001 * float(np.percentile(e, 95)) + 1e-9))


def best_shifts(reference, other, rate, keep=COARSE_TRIES):
    """The shifts most worth testing, best first, in seconds: other_time = reference_time + shift.
    Every possible shift is scored at once; only those leaving a real overlap are considered."""
    np = _np()
    n, m = len(reference), len(other)
    need = int(MIN_OVERLAP * rate)
    if n < need or m < need:
        return []
    size = 1 << int(np.ceil(np.log2(n + m)))
    corr = np.fft.irfft(np.conj(np.fft.rfft(reference, size)) * np.fft.rfft(other, size), size)
    # corr[k] adds up reference[i] * other[i + k]: a positive k says the other file reaches each
    # moment k samples LATER in its own clock than the reference does.
    lags = np.concatenate((np.arange(0, m), np.arange(-(n - 1), 0)))
    values = np.concatenate((corr[:m], corr[size - (n - 1):]))
    overlap = np.minimum(n, m - lags) - np.maximum(0, -lags)
    values = np.where(overlap >= need, values, -np.inf)
    out = []
    for _ in range(keep):
        k = int(np.argmax(values))
        if not np.isfinite(values[k]):
            break
        out.append(float(lags[k]) / float(rate))
        values[np.abs(lags - lags[k]) <= 2 * rate] = -np.inf          # the next guess must be a different place
    return out


# ----------------------------------------------------------------------------- measuring
def _shared(a, b, shift):
    """The stretch of the reference's clock during which BOTH recordings were running."""
    return max(0.0, -shift), min(a.duration, b.duration - shift)


def _liveliest(sound, lo, hi, length, target):
    """A start time near `target` where the stretch has the most going on. Stretches are spread
    evenly first and then nudged, a little, toward sound: a stretch of silence can only ever come
    back 'unclear', which says nothing either way."""
    np = _np()
    loud = sound.loudness()
    slack = min(0.1 * (hi - lo), 2.0 * length)
    first, last = max(lo, target - slack), min(hi - length, target + slack)
    if not len(loud) or last <= first:
        return float(min(max(target, lo), max(lo, hi - length)))
    level = np.log(np.asarray(loud, dtype="float64") + 0.001 * float(np.percentile(loud, 95)) + 1e-9)
    total = np.concatenate(([0.0], np.cumsum(level)))
    n = max(1, int(length * LOUDNESS_RATE))
    best, best_mean = target, None
    for start in np.arange(first, last + 1e-9, 0.5):
        i = int(start * LOUDNESS_RATE)
        if i + n >= len(total):
            break
        mean = (total[i + n] - total[i]) / n
        if best_mean is None or mean > best_mean + 1e-12:
            best, best_mean = float(start), mean
    return float(min(max(best, lo), max(lo, hi - length)))


def _window_starts(sound, lo, hi, length):
    room = hi - lo - length
    if room < 0:
        return []
    count = int(min(MAX_WINDOWS, max(3, (hi - lo) // length)))
    if count == 1 or room == 0:
        return [float(lo)]
    starts = [_liveliest(sound, lo, hi, length, lo + room * i / float(count - 1)) for i in range(count)]
    return sorted(set(round(x, 3) for x in starts))


def _fine_pass(a, b, shift, how):
    """One answer per stretch, spread through the part both recordings cover."""
    lo, hi = _shared(a, b, shift)
    if hi - lo < MIN_OVERLAP:
        return []
    length = min(max((hi - lo) / 4.0, how["window"][0]), how["window"][1], hi - lo)
    windows = []
    for t in _window_starts(a, lo, hi, length):
        needle = a.read(t, length)
        entry = {"at": round(float(t), 3), "clear": False}
        for margin in (how["margin"], how["second_look"]):
            wide_from = max(0.0, t + shift - margin)
            found = locate_inside(needle, b.read(wide_from, length + 2 * margin), int(how["exclude"] * a.rate))
            if found is None:
                continue
            entry.update({"offset": round(float(wide_from + found["index"] / float(a.rate) - t), 4),
                          "score": round(found["score"], 3), "stands_out": round(found["z"], 1),
                          "clear": is_clear(found, how), "looked_wider": margin != how["margin"]})
            if entry["clear"]:
                break
        windows.append(entry)
    return windows


def _median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _slope(points):
    """Seconds of offset gained per second of recording, by least squares; 0 with too few points."""
    if len(points) < 3:
        return 0.0
    mx = sum(p[0] for p in points) / len(points)
    my = sum(p[1] for p in points) / len(points)
    den = sum((p[0] - mx) ** 2 for p in points)
    return sum((p[0] - mx) * (p[1] - my) for p in points) / den if den > 0 else 0.0


def _judge(windows, how, span):
    """(offset or None, the clear stretches, why not). The rule for 'the stretches agree'.

    A stretch that could not be found is left out: silence and noise do that, and they say nothing
    either way. A stretch that WAS found, clearly, somewhere the others do not put it is different.
    That is a contradiction, and one is enough, with a single exception: two clocks running at
    very slightly different speeds put the answers on a gentle slope, and a slope that stays
    inside what lips can hide is accepted (and reported) rather than refused."""
    clear = [w for w in windows if w["clear"]]
    need = how["need"][1] if len(windows) >= 5 else how["need"][0]
    if len(clear) < need:
        return None, clear, "unclear"
    middle = _median([w["offset"] for w in clear])
    if all(abs(w["offset"] - middle) <= how["agree_within"] for w in clear):
        return middle, clear, ""
    slope = _slope([(w["at"], w["offset"]) for w in clear])
    base = _median([w["offset"] - slope * w["at"] for w in clear])
    if all(abs(w["offset"] - slope * w["at"] - base) <= how["agree_within"] for w in clear):
        if abs(slope) * span <= DRIFT_TOO_MUCH:
            return middle, clear, ""
        return None, clear, "drift"
    return None, clear, "disagree"


def _measure(a, b, how, say=None):
    say = say or (lambda _t: None)
    if a.rate != b.rate:
        raise ValueError("both recordings must be read at the same rate")
    say("Comparing how loud the two recordings are, from start to end...")
    guesses = best_shifts(a.outline(), b.outline(), LOUDNESS_RATE)
    if not guesses:
        raise SyncRefused("'%s' and '%s' are too short to line up: they need at least %d seconds in common."
                          % (a.name, b.name, MIN_OVERLAP))
    worst = None
    rank = {"unclear": 0, "drift": 1, "disagree": 2}
    for shift in guesses:
        say("Looking for stretches of one inside the other, around %+.2f seconds..." % shift)
        windows = _fine_pass(a, b, shift, how)
        lo, hi = _shared(a, b, shift)
        middle, agreeing, why_not = _judge(windows, how, hi - lo)
        if middle is not None:
            spread = max(abs(w["offset"] - middle) for w in agreeing)
            slope = _slope([(w["at"], w["offset"]) for w in agreeing])
            result = Offset(seconds=round(float(middle), 3), spread=round(float(spread), 4), method=how["name"],
                            windows=windows, confidence=round(len(agreeing) / float(len(windows)), 2),
                            drift_per_hour=round(float(slope) * 3600.0, 3))
            if abs(slope) * (hi - lo) > DRIFT_WORTH_SAYING:
                result.notes.append("The two clocks drift apart by about %.2f seconds an hour. The offset is right "
                                    "for the middle of the recording; the two ends will each be a little out."
                                    % abs(result.drift_per_hour))
            return result
        if worst is None or rank[why_not] > rank[worst[0]]:
            worst = (why_not, agreeing)
    why_not, clear = worst
    if why_not == "drift":
        slope = _slope([(w["at"], w["offset"]) for w in clear])
        raise SyncRefused("'%s' and '%s' run at different speeds: they drift apart by about %.1f seconds an hour, so "
                          "no single offset lines them up. One of them was probably re-timed when it was exported. "
                          "Export both again at their original speed." % (a.name, b.name, abs(slope * 3600.0)))
    if why_not == "disagree":
        found = sorted(w["offset"] for w in clear)
        raise SyncRefused("'%s' and '%s' do not line up: different parts of them give different answers (from %+.2f "
                          "to %+.2f seconds). They may not be recordings of the same conversation, or one of them "
                          "was paused and restarted part way through." % (a.name, b.name, found[0], found[-1]))
    raise SyncRefused("No stretch of '%s' could be found in '%s'. They may not be recordings of the same "
                      "conversation." % (a.name, b.name))


def check_offset(reference, other, offset, how=None):
    """Shift by `offset`, listen again at the start, the middle and the end, and say what is left.

    Returns {"ok", "residual", "points", "why"}. `ok` needs a CLEAR match at two places or more (one,
    when the recordings are very short), every clear match within the limit of zero, and no
    place where the match was clear but somewhere else. A sign that is back to front leaves
    twice the offset behind, or no match at all; either way it does not pass."""
    how = how or BY_SOUND
    a, b = as_sound(reference), as_sound(other)
    offset = float(offset)
    lo, hi = _shared(a, b, offset)
    if hi - lo < min(MIN_OVERLAP, how["check_window"]):
        return {"ok": False, "residual": None, "points": [],
                "why": "with that offset the two recordings hardly overlap at all"}
    length = min(how["check_window"], (hi - lo) / 3.0)
    reach = min(CHECK_REACH_MAX, max(how["check_reach"], 2.2 * abs(offset)))
    points = []
    for target in (lo, (lo + hi - length) / 2.0, hi - length):
        t = _liveliest(a, lo, hi, length, target)
        wide_from = max(0.0, t + offset - reach)
        found = locate_inside(a.read(t, length), b.read(wide_from, length + 2 * reach), int(how["exclude"] * a.rate))
        entry = {"at": round(float(t), 3), "clear": is_clear(found, how)}
        if found is not None:
            entry["residual"] = round(float(wide_from + found["index"] / float(a.rate) - (t + offset)), 4)
        points.append(entry)
    clear = [p for p in points if p["clear"]]
    if not clear:
        return {"ok": False, "residual": None, "points": points,
                "why": "after shifting by that offset, nothing in one recording could be found in the other"}
    residual = float(_median([p["residual"] for p in clear]))
    out = {"ok": False, "residual": round(residual, 4), "points": points, "why": ""}
    furthest = max(clear, key=lambda p: abs(p["residual"]))
    if abs(furthest["residual"]) > how["residual_limit"]:
        if abs(offset) > how["residual_limit"] and abs(residual + 2 * offset) <= 2 * how["residual_limit"]:
            out["why"] = ("after shifting by that offset the recordings are still %.3f seconds apart, which is twice "
                          "the offset. That is what an offset with its sign back to front looks like"
                          % abs(residual))
        else:
            out["why"] = ("after shifting by that offset the recordings are still %.3f seconds apart around %s"
                          % (abs(furthest["residual"]), fmt_ts(furthest["at"], 0)))
        return out
    if len(clear) < min(2, len(points)):
        out["why"] = "after shifting, only one place could be checked, which is not enough to be sure"
        return out
    out["ok"] = True
    return out


def measure_offset(file_a, file_b, say=None):
    """How far apart two recordings of the same conversation are, by their sound.

    Returns an Offset where  time_in_b = time_in_a + seconds.  Raises SyncRefused, with the reason
    in plain words, when the stretches disagree or the measured number does not survive being
    applied and listened to again."""
    a, b = as_sound(file_a), as_sound(file_b)
    result = _measure(a, b, BY_SOUND, say)
    return _prove(a, b, result, BY_SOUND)


def _prove(a, b, result, how):
    check = check_offset(a, b, result.seconds, how)
    result.residual = check["residual"]
    if not check["ok"]:
        raise SyncRefused("An offset of %+.3f seconds was measured between '%s' and '%s', but it did not survive being "
                          "checked: %s. Nothing was saved." % (result.seconds, a.name, b.name, check["why"]))
    result.checked = True
    return result


# ----------------------------------------------------------------------------- a transcript against a video
def activity(transcript):
    """When somebody was talking, according to the transcript's own word times: a Sound whose
    samples are 1 during a word and 0 between words."""
    np = _np()
    track = np.zeros(int(transcript.duration * LOUDNESS_RATE) + 2)
    for w in transcript.words:
        track[max(0, int(w["start"] * LOUDNESS_RATE)):int(w["end"] * LOUDNESS_RATE) + 1] = 1.0
    return ArraySound(track, LOUDNESS_RATE, "the transcript")


def measure_transcript_offset(video_file, transcript, transcribed_file=None, say=None):
    """The cut list's Offset for one video:  video_time = transcript_time + seconds.

    `transcribed_file` is the file the transcript was made from, when it is still around.
      * It IS the video: the offset is zero by construction, and the words are still checked
        against the video's sound, because a file can be replaced under the same name.
      * It is a different file: the two are lined up sound against sound, the exact way.
      * It is gone: the transcript's word times are lined up against the video's loudness."""
    video = as_sound(video_file)
    by_words = bool(getattr(transcript, "word_level", False))
    if transcribed_file and os.path.isfile(transcribed_file):
        if not (isinstance(video, FileSound) and same_file(transcribed_file, video.path)):
            return measure_offset(transcribed_file, video, say)
        result = Offset(seconds=0.0, confidence=1.0, method="same-file")
        if by_words:
            check = check_offset(activity(transcript), _loudness_of(video), 0.0, BY_WORDS)
            result.residual = check["residual"]
            if check["ok"]:
                result.checked = True
            elif check["residual"] is not None:
                raise SyncRefused("The transcript says it was made from '%s', but its words do not land on the "
                                  "speech in that file: they are about %.1f seconds out. The file may have been "
                                  "replaced since it was transcribed. Transcribe it again, or name the file the "
                                  "transcript really came from." % (video.name, abs(check["residual"])))
            else:
                result.notes.append("The words could not be double-checked against the sound (music or a noisy "
                                    "room can do that).")
        return result
    if not by_words:
        raise SyncRefused("This transcript has sentence times only and the file it was made from is not here, so "
                          "there is nothing exact enough to line up against '%s'. Put the transcribed file back in "
                          "the recording's folder, or transcribe this video." % video.name)
    words, loud = activity(transcript), _loudness_of(video)
    try:
        result = _prove(words, loud, _measure(words, loud, BY_WORDS, say), BY_WORDS)
    except SyncRefused as e:
        # This is the fallback, and it needs a minute or two of talk with pauses in it. Say what
        # the exact way would need, because that is nearly always the quicker fix.
        raise SyncRefused("%s (This was judged from the transcript's word times alone, because the file that was "
                          "transcribed is not in the recording's folder. Put it back and the two files can be "
                          "compared sound against sound, which is exact. Or transcribe this video itself.)" % e)
    result.seconds = round(result.seconds, 2)                  # this method is good to tenths, not thousandths
    return result


def _loudness_of(sound):
    return ArraySound(_shape(sound.loudness()), LOUDNESS_RATE, sound.name)


# ----------------------------------------------------------------------------- for a cut list (one camera)
def offset_text(seconds):
    """The number as it is written on a cut list's Offset line: signed, and never '-0'."""
    if abs(seconds) < 0.0005:
        return "0"
    return ("%+.3f" % seconds).rstrip("0").rstrip(".")


def offset_for_cut_list(brand, recording, video=None, cut_list_path=None, save=False, say=None):
    """Measure the `Offset` a cut list needs for the video it is cut from, size and sign.

    `video` defaults to the file the cut list names under 'Cut from'. With `save`, the Offset line
    of the cut list is rewritten (that one line and nothing else), so the sign never passes
    through anybody's fingers. Returns {"offset": Offset, "video", "cut_list", "was", "saved"}."""
    import re
    from smf.video import cutlist
    from smf.video.common import (CUT_LIST_FILE, Transcript, as_brand, output_dir, resolve, write_text_atomic)
    brand = as_brand(brand)
    transcript = Transcript.load(brand, recording)
    path = cut_list_path or output_dir(brand, recording, CUT_LIST_FILE)
    cl = cutlist.load(path) if os.path.isfile(path) else None
    written = video or (cl.reference.get("cut_from") if cl else None)
    if not written:
        raise VideoError("Say which video to measure with --video. (There is no cut list for '%s' yet to take the "
                         "file name from.)" % recording)
    video_path = resolve(brand, recording, written)
    if not video_path:
        raise VideoError("'%s' cannot be found. Put the video in the recording's folder, or give its full location."
                         % written)
    transcribed = resolve(brand, recording, (transcript.source or {}).get("media"))
    result = measure_transcript_offset(video_path, transcript, transcribed, say)
    named = resolve(brand, recording, cl.reference.get("cut_from")) if cl else None
    names_this_video = bool(named) and same_file(named, video_path)
    # What the cut list says now is only comparable when it is talking about this very file.
    out = {"offset": result, "video": video_path, "cut_list": path if cl else None,
           "was": cl.offset if names_this_video else None, "saved": False}
    if not save:
        return out
    if cl is None:
        raise VideoError("There is no cut list for '%s' yet, so there is nowhere to save the offset. It is %s."
                         % (recording, offset_text(result.seconds)))
    if not names_this_video:
        raise VideoError("The cut list is cut from '%s', but the video measured was '%s'. An offset belongs to one "
                         "particular file, so nothing was saved. Change the cut list's 'Cut from' line first, or "
                         "measure the file it names." % (cl.reference.get("cut_from") or "nothing", os.path.basename(video_path)))
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    line = re.compile(r"^(>\s*\*{0,2}\s*Offset\s*:\*{0,2}[ \t]*).*$", re.IGNORECASE | re.MULTILINE)
    if not line.search(text):
        raise VideoError("The cut list has no 'Offset' line to update. Add this line to the block at its top: "
                         "> **Offset:** %s" % offset_text(result.seconds))
    write_text_atomic(path, line.sub(lambda m: m.group(1) + offset_text(result.seconds), text, count=1))
    out["saved"] = True
    return out
