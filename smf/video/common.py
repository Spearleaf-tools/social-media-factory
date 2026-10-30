"""common.py - the small pieces every clip tool shares.

  * where a recording's files live inside a brand folder
  * reading the one canonical transcript, whatever made it
  * timestamps in and out of text
  * word matching that survives punctuation, stutters and the way numbers get transcribed
  * running the bundled video programs without ever pasting a path into a command string

Times are always seconds as floats. Two clocks exist and they are never mixed silently:
TRANSCRIPT time (what the transcript says) and VIDEO time (the file being cut). They are related
by one number per recording:  video_time = transcript_time + offset.  It is zero when the clips
are cut from the same file that was transcribed, which is the normal case.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unicodedata

from smf.studio.files import as_brand          # noqa: F401  (re-exported: every tool starts with it)
from smf.brands import replace_patiently

TRANSCRIPT_FILE = "transcript.json"
READABLE_FILE = "transcript-timestamped.txt"
ON_CAMERA_FILE = "transcript-on-camera.txt"
PLAIN_FILE = "transcript.txt"
CUT_LIST_FILE = "cut-list.md"

# A pause this long between two words of the same voice starts a new turn.
TURN_GAP = 0.75


class VideoError(Exception):
    """A problem in the clip tools, worded for the person, not the programmer."""


# ----------------------------------------------------------------------------- where things live
def safe_name(name, what="recording"):
    """A folder name that stays inside the brand folder. Spaces, apostrophes and accents are fine;
    slashes, '..' and hidden names are not."""
    if not isinstance(name, str) or not name.strip():
        raise VideoError("No %s was named. Say which %s this is for." % (what, what))
    name = name.strip()
    if name in (".", "..") or name.startswith(".") or re.search(r"[\\/:\0]", name):
        raise VideoError("'%s' cannot be used as a %s name. Use a plain folder name, for example "
                         "'2026-09-12 shop interview'." % (name, what))
    return name


def recording_dir(brand, recording):
    return brand.path("Inputs", "Recordings", safe_name(recording))


def transcriptions_dir(brand, recording):
    return os.path.join(recording_dir(brand, recording), "Transcriptions")


def output_dir(brand, recording, *parts):
    return brand.path("Output", "video", safe_name(recording), *parts)


def list_recordings(brand):
    root = brand.path("Inputs", "Recordings")
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root)
                  if not n.startswith(".") and os.path.isdir(os.path.join(root, n)))


def locate(brand, path):
    """How a file's location is written into a report. Inside the brand folder: relative, with
    forward slashes, so the folder can move. Outside it: the full path, exactly as found.
    (Locations are recorded, never linked: links do not survive a zip file or a Windows checkout.)"""
    full = os.path.abspath(path)
    home = os.path.abspath(brand.home)
    if full == home or full.startswith(home + os.sep):
        return os.path.relpath(full, home).replace(os.sep, "/")
    return full


def resolve(brand, recording, written):
    """Turn a location written in a report or a cut list back into a real file, or None.
    Tried in order: as written (if absolute), inside the recording folder, inside the brand folder."""
    if not isinstance(written, str) or not written.strip():
        return None
    written = written.strip().strip('"').strip("'")
    candidates = []
    if os.path.isabs(written):
        candidates.append(written)
    else:
        parts = [p for p in re.split(r"[\\/]+", written) if p not in ("", ".")]
        if any(p == ".." for p in parts):
            return None
        candidates.append(os.path.join(recording_dir(brand, recording), *parts))
        candidates.append(brand.path(*parts))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def slug(text, limit=48):
    """A file-name-safe version of a title. Accents are folded; anything else odd is dropped."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return s[:limit].strip("-")


# ----------------------------------------------------------------------------- files
def write_text_atomic(path, text):
    """The old file stays whole until the new one is complete."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    replace_patiently(tmp, path)


def write_json_atomic(path, data, compact=False):
    if compact:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    write_text_atomic(path, text + "\n")


def read_json(path, what):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        raise VideoError("%s could not be found." % what)
    except ValueError:
        raise VideoError("%s is damaged and cannot be read. Nothing was changed. "
                         "Ask Claude to look at it before going on." % what)


# ----------------------------------------------------------------------------- timestamps
def parse_ts(value):
    """'MM:SS', 'MM:SS.s', 'H:MM:SS.s' or plain seconds -> float seconds."""
    if isinstance(value, bool):
        raise VideoError("'%s' is not a time." % value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    parts = text.split(":")
    if not text or not 1 <= len(parts) <= 3:
        raise VideoError("'%s' is not a time. Write it like 02:14 or 1:02:14.5." % value)
    total = 0.0
    try:
        for p in parts:
            total = total * 60 + float(p)
    except ValueError:
        raise VideoError("'%s' is not a time. Write it like 02:14 or 1:02:14.5." % value)
    return total


def fmt_ts(seconds, decimals=1):
    seconds = max(0.0, float(seconds))
    scale = 10 ** decimals
    whole = int(round(seconds * scale))
    secs_total, frac = divmod(whole, scale)
    h, rem = divmod(secs_total, 3600)
    m, s = divmod(rem, 60)
    tail = (".%0*d" % (decimals, frac)) if decimals else ""
    if h:
        return "%d:%02d:%02d%s" % (h, m, s, tail)
    return "%02d:%02d%s" % (m, s, tail)


def minutes_words(seconds):
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return "%d seconds" % round(seconds)
    if seconds < 3600:
        return "%d minutes" % round(seconds / 60.0)
    h, rem = divmod(int(round(seconds / 60.0)), 60)
    return "%d hour%s %d minutes" % (h, "" if h == 1 else "s", rem)


# ----------------------------------------------------------------------------- word matching
_NUMBER_WORDS = frozenset("""zero one two three four five six seven eight nine ten eleven twelve thirteen
fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety
hundred thousand million billion half quarter dozen""".split())


def norm_token(token):
    """Lowercase, letters, digits and apostrophes only; a possessive 's is dropped so
    "baker's" and "bakers" still line up. Curly apostrophes are straightened first."""
    t = (token or "").lower().replace("\u2019", "'")
    t = "".join(c for c in unicodedata.normalize("NFKC", t) if c.isalnum() or c == "'")
    t = t.strip("'")
    return t[:-2] if t.endswith("'s") else t


def is_number_token(token):
    """Spoken numbers come back from a speech model in unpredictable shapes ('twenty grams',
    '20g', '20 grams'), so they are never used to decide whether two passages match."""
    return token in _NUMBER_WORDS or any(c.isdigit() for c in token)


def tokens_of(text, keep_numbers=False):
    """Normalised tokens of a phrase. [Bracketed corrections] are the editor's notes, not speech."""
    text = re.sub(r"\[[^\]]*\]", " ", text or "")
    out = []
    for raw in re.split(r"[\s\u2014\u2013-]+", text):
        t = norm_token(raw)
        if t and (keep_numbers or not is_number_token(t)):
            out.append(t)
    return out


def stream_of(texts, keep_numbers=False):
    """[(index, token), ...] for a list of written words. One written word can hold several
    tokens ("gluten-free"), and a quoted phrase is split by the same rule, so the two line up."""
    out = []
    for i, text in enumerate(texts):
        for tok in tokens_of(text, keep_numbers=keep_numbers):
            out.append((i, tok))
    return out


def lcs(a, b):
    """Length of the longest common subsequence: tolerant of a dropped or extra word either side."""
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(max(prev[j] + 1 if x == y else 0, prev[j + 1], cur[-1]))
        prev = cur
    return prev[-1]


# ----------------------------------------------------------------------------- the transcript
class Transcript(object):
    """The one canonical transcript of a recording.

    words     [{"word", "start", "end", "speaker"}]   empty when the transcript came from subtitles
    segments  [{"start", "end", "text", "speaker"}]   sentence-sized, always present
    """

    def __init__(self, data, path=""):
        if not isinstance(data, dict):
            raise VideoError("The transcript file does not look like a transcript.")
        self.path = path
        self.source = data.get("source") if isinstance(data.get("source"), dict) else {}
        self.language = data.get("language") or ""
        self.words = []
        for w in data.get("words") or []:
            try:
                word = {"word": str(w["word"]).strip(), "start": float(w["start"]), "end": float(w["end"]),
                        "speaker": (w.get("speaker") or "")}
            except (KeyError, TypeError, ValueError):
                continue                      # one malformed entry is skipped, not fatal
            if word["word"]:
                self.words.append(word)
        self.words.sort(key=lambda w: w["start"])
        self.segments = []
        for s in data.get("segments") or []:
            try:
                seg = {"start": float(s["start"]), "end": float(s["end"]),
                       "text": str(s.get("text", "")).strip(), "speaker": (s.get("speaker") or "")}
            except (KeyError, TypeError, ValueError):
                continue
            if seg["text"]:
                self.segments.append(seg)
        if not self.segments and not self.words:
            raise VideoError("The transcript is empty: no words and no sentences were found in it.")
        if not self.segments:
            self.segments = sentences_from_words(self.words)
        last = max([w["end"] for w in self.words] + [s["end"] for s in self.segments])
        self.duration = float(data.get("duration") or last)

    @property
    def word_level(self):
        return bool(self.words)

    @property
    def speakers(self):
        pool = self.words if self.words else self.segments
        return sorted({x["speaker"] for x in pool if x["speaker"]})

    @property
    def labelled(self):
        return bool(self.speakers)

    def turns(self):
        """Stretches of one voice. From words when there are words, otherwise from the sentences."""
        if not self.words:
            return [dict(s) for s in self.segments]
        return turns_from_words(self.words)

    @classmethod
    def load(cls, brand, recording):
        path = os.path.join(transcriptions_dir(brand, recording), TRANSCRIPT_FILE)
        if not os.path.isfile(path):
            raise VideoError("'%s' has no transcript yet. Transcribe the recording first "
                             "(it needs an ElevenLabs key), or bring in a subtitle file the editor made."
                             % recording)
        return cls(read_json(path, "The transcript for '%s'" % recording), path)


def turns_from_words(words, max_gap=TURN_GAP):
    turns = []
    for w in words:
        if turns and w["speaker"] == turns[-1]["speaker"] and w["start"] - turns[-1]["end"] <= max_gap:
            turns[-1]["end"] = w["end"]
            turns[-1]["_toks"].append(w["word"])
        else:
            turns.append({"start": w["start"], "end": w["end"], "speaker": w["speaker"], "_toks": [w["word"]]})
    for t in turns:
        t["text"] = " ".join(t.pop("_toks"))
    return turns


def sentences_from_words(words, max_gap=TURN_GAP, max_words=60):
    """Sentence-sized pieces: a new one starts when the voice changes, after a real pause, after
    sentence punctuation, or when a run-on has gone on long enough."""
    out, cur = [], None
    for w in words:
        new = (cur is None or w["speaker"] != cur["speaker"] or w["start"] - cur["end"] > max_gap
               or cur["_closed"] or len(cur["_toks"]) >= max_words)
        if new:
            if cur:
                out.append(cur)
            cur = {"start": w["start"], "end": w["end"], "speaker": w["speaker"], "_toks": [], "_closed": False}
        cur["end"] = w["end"]
        cur["_toks"].append(w["word"])
        cur["_closed"] = w["word"][-1:] in ".?!"
    if cur:
        out.append(cur)
    for s in out:
        s["text"] = " ".join(s.pop("_toks"))
        s.pop("_closed")
    return out


def words_in_clip(pieces, words, offset=0.0):
    """The transcript's words as they fall inside a finished clip, timed from the clip's start.

    `pieces` are the [start, end] ranges (VIDEO time) that were joined to make the clip, in order.
    This is how a later step (captions, for one) gets clip-accurate word times without listening
    to the clip again: the recording was transcribed once, by the good transcriber, and everything
    after that is arithmetic. A word counts when its middle falls inside a piece."""
    out, elapsed = [], 0.0
    for start, end in pieces:
        for w in words:
            mid = (w["start"] + w["end"]) / 2.0 + offset
            if start <= mid < end:
                out.append({"word": w["word"], "speaker": w.get("speaker", ""),
                            "start": round(max(w["start"] + offset, start) - start + elapsed, 3),
                            "end": round(min(w["end"] + offset, end) - start + elapsed, 3)})
        elapsed += end - start
    return out


# ----------------------------------------------------------------------------- the video programs
_programs = {}


def programs():
    """(ffmpeg, ffprobe) from the Factory's own copies. A plain message if they are not installed."""
    if not _programs:
        from smf import media
        try:
            ff, fp = media.ensure_ffmpeg()
        except RuntimeError as e:
            raise VideoError(str(e))
        _programs["ffmpeg"], _programs["ffprobe"] = ff, fp
    return _programs["ffmpeg"], _programs["ffprobe"]


def run(cmd, what, binary=False):
    """Run one of the video programs. `cmd` is always a list: paths are handed over as separate
    arguments and never pasted into a string, so spaces, apostrophes and accents need no quoting."""
    kwargs = {"capture_output": True}
    if not binary:
        kwargs.update({"text": True, "encoding": "utf-8", "errors": "replace"})
    try:
        r = subprocess.run(cmd, **kwargs)
    except OSError as e:
        raise VideoError("Could not %s: the video program would not start (%s)." % (what, e))
    if r.returncode != 0:
        err = r.stderr if isinstance(r.stderr, str) else r.stderr.decode("utf-8", "replace")
        last = [ln for ln in err.strip().splitlines() if ln.strip()][-2:]
        raise VideoError("Could not %s. The video program said: %s" % (what, " / ".join(last) or "nothing"))
    return r


def probe_duration(path):
    _ff, fp = programs()
    r = run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             path], "measure '%s'" % os.path.basename(path))
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise VideoError("'%s' does not look like a video or audio file." % os.path.basename(path))


def has_audio(path):
    _ff, fp = programs()
    r = run([fp, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
            "look inside '%s'" % os.path.basename(path))
    return bool(r.stdout.strip())


def probe_shape(path):
    """{"orientation": vertical|horizontal|square|unknown, "width", "height"} as the video is SHOWN.

    Phones very often store a sideways frame plus a 'rotate me' flag. Comparing the stored width
    and height would call every upright phone video horizontal, so the flag is applied first."""
    _ff, fp = programs()
    r = run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:stream_side_data=rotation", "-of", "default=noprint_wrappers=1", path],
            "look inside '%s'" % os.path.basename(path))
    w = h = rot = 0
    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        try:
            if k == "width":
                w = int(v)
            elif k == "height":
                h = int(v)
            elif k == "rotation":
                rot = int(float(v))
        except ValueError:
            pass
    if abs(rot) % 180 == 90:
        w, h = h, w
    if not w or not h:
        return {"orientation": "unknown", "width": w, "height": h}
    return {"orientation": "vertical" if h > w else "horizontal" if w > h else "square", "width": w, "height": h}


def decodes_cleanly(path):
    """Play the whole file to nowhere. A render that was interrupted can keep its name, a sensible
    size and a readable header while the pictures inside are broken; only a full decode shows it."""
    ff, _fp = programs()
    try:
        r = subprocess.run([ff, "-v", "error", "-i", path, "-f", "null", "-"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except OSError:
        return False
    return r.returncode == 0 and not r.stderr.strip()


def concat_line(path):
    """One line of a join list. The list format wraps the path in single quotes, so an apostrophe
    inside the path has to close the quote, add an escaped apostrophe, and open it again."""
    return "file '%s'\n" % os.path.abspath(path).replace(os.sep, "/").replace("'", "'\\''")


def join_parts(parts, out_path, what):
    """Join identically-encoded parts without re-encoding them."""
    ff, _fp = programs()
    fd, listing = tempfile.mkstemp(prefix=".join-", suffix=".txt", dir=os.path.dirname(out_path))
    working = os.path.splitext(out_path)[0] + ".working" + os.path.splitext(out_path)[1]
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for p in parts:
                f.write(concat_line(p))
        run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing,
             "-c", "copy", "-movflags", "+faststart", working], what)
        replace_patiently(working, out_path)                       # only a finished file ever gets the real name
    finally:
        for leftover in (listing, working):
            try:
                os.remove(leftover)
            except OSError:
                pass


def merge_report(path, report, partial):
    """When only some clips were re-made (`partial`), the clips that were left alone keep their
    entries from the last full report. Otherwise re-cutting one clip would make every other
    finished clip invisible to the steps that read this report."""
    if not partial or not os.path.isfile(path):
        return report
    try:
        old = read_json(path, "The earlier report")
    except VideoError:
        return report
    if old.get("source") != report.get("source") or old.get("offset") != report.get("offset"):
        return report
    fresh = {c["id"]: c for c in report["clips"]}
    kept = [fresh.pop(c["id"], c) for c in old.get("clips", [])]
    return dict(report, clips=kept + list(fresh.values()))       # a new dict: the run's own report is untouched


def usable_part(path, want_seconds, tolerance=0.30):
    """Is this saved part complete? A run that was stopped half way leaves a short but perfectly
    well-formed file behind, and a cache that only asks 'does the file exist' would adopt it and
    quietly lose footage. So a saved part is trusted only if it is as long as it was meant to be."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return False
        return abs(probe_duration(path) - want_seconds) <= tolerance
    except VideoError:
        return False

