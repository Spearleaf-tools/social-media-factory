"""video_miner.py - turn ONE video into a folder Claude can read for facts, numbers and lessons.

No key, no paid service, no text-recognition program to install. The steps:

    download     a web link is fetched with yt-dlp; a file on this computer is used where it is
                 (never copied, never moved, never deleted)
    frames       one still every few seconds, using the Factory's own ffmpeg
    de-duplicate a slide held for a minute becomes one still, not thirty
    transcribe   the words, with times, using the small local speech model
    index        every kept still, paired with what was being said around it

THE LAW THIS TOOL SERVES
A number is quoted exactly, with its timestamp, or it does not ship. This tool therefore never
tries to READ the screen. Reading small type off video is unreliable, and an unreliable reading
of a number is worse than none. Instead it hands Claude the stills themselves, in order, each
beside the words spoken at that moment, and Claude reads the pictures. The transcript is a guide
to where things are; a spoken number is marked to be checked against the audio at its timestamp,
because a speech model can hear "fifteen" as "fifty".

HOW DE-DUPLICATION DECIDES (pure Pillow, and why it is more than a picture hash)
A picture hash alone answers "do these two stills look alike overall?". That is the wrong
question for a slide where only "38%" became "83%": overall it looks identical, and a hash would
throw the second still away, number and all. So two measurements are used together:

    look     a 256-bit difference hash of the whole still: is this the same scene?
    change   the still is compared block by block with the last KEPT still: did ANY small area
             change sharply, and how much of the picture changed?

    nothing changed anywhere              -> duplicate, absorbed into the still before it
    same scene, a small area changed      -> kept: that is what a changed number looks like.
                                             It is also what a person moving looks like, so
                                             these are kept at most once every `local_every`
                                             seconds to stop a talking head filling the folder
    a different scene                     -> kept

Each still is compared with the last one KEPT, not with its neighbour, so a slow fade cannot
creep past one small step at a time. Every kept still records how many it absorbed and why, so
nothing disappears silently, and `keep_raw=True` keeps every original still for checking.

The honest limit: a number that flashes up on an unchanged scene for less than `local_every`
seconds can be missed. For a slide-heavy video where numbers matter, set local_every to the same
value as the interval and every change is kept.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import json

from smf.research import store

JOB = "video"
INTERVAL = 2.0              # seconds between stills
LOCAL_EVERY = 6.0           # same-scene changes are kept at most this often
HASH_SIDE = 16              # 16 x 16 = a 256-bit hash
SAME_SCENE_BITS = 26        # of 256: at or under this, the two stills show the same scene
# These three were chosen by measurement, not by feel. On test slides, the SAME slide saved twice
# (once cleanly, once badly compressed with heavy noise added) never moved a block by more than 6.
# Changing one small number in the footnote ("1,204" to "1,240") moved a block by 72. A coarser
# setting (480 x 270, 16-pixel blocks) moved it by only 7 and lost the change in the noise. The
# threshold sits three times above the worst noise and four times below the smallest real change.
COMPARE_SIZE = (960, 540)
BLOCK = 8                   # pixels per block on the comparison image
BLOCK_CHANGED = 18          # mean brightness change (0-255) that counts as a block having changed
THUMB = (160, 88)           # a small copy kept per still, only to spot a slide coming back
PAD_SECS = 4.0              # how much speech either side of a still counts as "around it"
VIDEO_TYPES = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")
_NUMBER_WORD = re.compile(
    r"\d|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"million|billion|percent|half|double|triple|quarter)\b", re.I)


class MinerError(store.ResearchError):
    """A problem mining a video, worded for the person."""


def clock(seconds):
    s = int(max(0, seconds))
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


# ----------------------------------------------------------------------------- de-duplication (pure Pillow)
def look_hash(img):
    """A 256-bit difference hash: each bit says whether a pixel is brighter than its right-hand neighbour."""
    from PIL import Image
    small = img.convert("L").resize((HASH_SIDE + 1, HASH_SIDE), Image.LANCZOS)
    px = small.tobytes()
    bits = 0
    for row in range(HASH_SIDE):
        base = row * (HASH_SIDE + 1)
        for col in range(HASH_SIDE):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def bits_apart(a, b):
    return bin(a ^ b).count("1")


def compare_image(img):
    from PIL import Image
    return img.convert("L").resize(COMPARE_SIZE, Image.BILINEAR)


def change_between(a, b):
    """(share of blocks that changed, the biggest change in any one block), both from comparison images.
    Shrinking the difference picture with a box filter makes each output pixel the MEAN of one block,
    so one resize does the work of a loop over every block."""
    from PIL import Image, ImageChops
    diff = ImageChops.difference(a, b)
    cols, rows = max(1, COMPARE_SIZE[0] // BLOCK), max(1, COMPARE_SIZE[1] // BLOCK)
    means = diff.resize((cols, rows), Image.BOX).tobytes()
    changed = sum(1 for m in means if m >= BLOCK_CHANGED)
    return changed / float(len(means)), max(means) if means else 0


def judge(cur, last, last_cmp, local_every):
    """Compare a still with the last KEPT still. Returns (keep, kind, why)."""
    share, _peak = change_between(cur["cmp"], last_cmp)
    apart = bits_apart(cur["hash"], last["hash"])
    if share == 0:
        return False, "same", "nothing on screen changed"
    if apart <= SAME_SCENE_BITS:
        if cur["t"] - last["t"] >= local_every:
            return True, "changed", "same scene, a part of the picture changed"
        return False, "moved", "same scene, a small change too soon after the last still"
    return True, "scene", "a different scene"


def _seen_before(cur, earlier):
    """Is `cur` a slide that was already kept earlier? Only used to label it, so a small thumbnail is enough."""
    from PIL import Image, ImageChops
    if bits_apart(cur["hash"], earlier["hash"]) > SAME_SCENE_BITS:
        return False
    diff = ImageChops.difference(cur["thumb"], earlier["thumb"])
    return max(diff.resize((THUMB[0] // 8, THUMB[1] // 8), Image.BOX).tobytes()) < BLOCK_CHANGED


def dedupe(stills, local_every=LOCAL_EVERY, interval=INTERVAL):
    """`stills` is a list of (seconds, image path) in time order. Returns the kept ones as dicts.
    Pure apart from opening the images: no clock, no randomness, the same answer every time.

    Memory: only ONE full-size comparison image is held at a time (the last kept still). Every kept
    still also keeps a tiny thumbnail, used only to notice a slide coming back later. An hour of
    video therefore costs a few megabytes, not a few hundred."""
    from PIL import Image
    kept, last_cmp = [], None
    for t, path in stills:
        with Image.open(path) as img:
            img.load()
            cur = {"t": float(t), "path": path, "hash": look_hash(img), "cmp": compare_image(img),
                   "thumb": img.convert("L").resize(THUMB, Image.BILINEAR)}
        if kept:
            keep, kind, why = judge(cur, kept[-1], last_cmp, local_every)
            if not keep:
                kept[-1]["t_end"] = cur["t"] + interval
                kept[-1]["absorbed"] += 1
                kept[-1]["absorbed_as"][kind] = kept[-1]["absorbed_as"].get(kind, 0) + 1
                continue
        else:
            kind, why = "scene", "the first still"
        last_cmp = cur.pop("cmp")
        cur.update({"t_end": cur["t"] + interval, "absorbed": 0, "absorbed_as": {}, "kind": kind, "why": why,
                    "repeat_of": None, "index": len(kept) + 1})
        for earlier in kept[:-1]:                     # a slide that comes BACK later is kept, and says so
            if _seen_before(cur, earlier):
                cur["repeat_of"] = earlier["index"]
                break
        kept.append(cur)
    for k in kept:
        k.pop("thumb", None)
        k.pop("hash", None)
    return kept


# ----------------------------------------------------------------------------- the outside programs
def _run(cmd, cwd=None, timeout=3600):
    """Run a program with its arguments as a LIST. Paths are never pasted into a command string, so a
    folder called "Ava's clips (final)" is just a folder."""
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise MinerError("That took too long and was stopped. Try a shorter video, or a longer gap between stills.")
    except OSError as e:
        raise MinerError("A video program could not be started (%s). Run: python factory.py doctor" % e)


def _ffmpeg():
    from smf import media
    try:
        return media.ensure_ffmpeg()
    except RuntimeError as e:
        raise MinerError(str(e))


def probe(video):
    """What is in this file: how long it is, and whether it has a picture and a sound track.
    Asked up front so that a screen recording with no sound is handled as the ordinary thing it is,
    instead of surfacing as a crash from deep inside the speech model."""
    _ff, prober = _ffmpeg()
    p = _run([prober, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json",
              os.path.abspath(video)], timeout=120)
    try:
        data = json.loads(p.stdout)
        kinds = [s.get("codec_type") for s in data.get("streams") or []]
        return {"seconds": float(data["format"]["duration"]), "has_video": "video" in kinds,
                "has_audio": "audio" in kinds}
    except (ValueError, KeyError, TypeError):
        raise MinerError("That file could not be read as a video.")


def probe_seconds(video):
    return probe(video)["seconds"]


def extract_stills(video, folder, every, first_seconds=None, prefix="f"):
    """One still every `every` seconds into `folder`. ffmpeg runs INSIDE the folder with a bare file
    pattern, so a percent sign anywhere in the path cannot be mistaken for part of the pattern."""
    ff, _probe = _ffmpeg()
    os.makedirs(folder, exist_ok=True)
    cmd = [ff, "-y", "-loglevel", "error", "-i", os.path.abspath(video)]
    if first_seconds:
        cmd += ["-t", "%g" % first_seconds]
    cmd += ["-vf", "fps=1/%g" % every, "-q:v", "3", prefix + "%05d.jpg"]
    p = _run(cmd, cwd=folder)
    names = sorted(n for n in os.listdir(folder) if n.startswith(prefix) and n.endswith(".jpg"))
    if not names:
        raise MinerError("No stills could be taken from that video. %s" % (p.stderr or "").strip()[:200])
    return [(i * float(every), os.path.join(folder, n)) for i, n in enumerate(names)]


def download(url, folder):
    """Fetch a web video with yt-dlp (imported, not shelled out to, so it need not be on the PATH)."""
    try:
        import yt_dlp
    except ImportError:
        raise MinerError("Fetching a video from a link needs the video tools. Run: python factory.py setup --tier "
                         "video. A video file already on this computer works without them being re-installed.")
    ff, _probe = _ffmpeg()
    os.makedirs(folder, exist_ok=True)
    opts = {"format": "bv*[height<=1080]+ba/b[height<=1080]/b", "merge_output_format": "mp4",
            "paths": {"home": folder}, "outtmpl": {"default": "%(id)s.%(ext)s"}, "noplaylist": True,
            "retries": 5, "quiet": True, "no_warnings": True, "noprogress": True,
            "ffmpeg_location": os.path.dirname(ff)}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:                                        # yt-dlp raises many kinds; all mean "could not fetch"
        raise MinerError("That video could not be fetched. It may be private, removed, or not available where you "
                         "are. (%s)" % str(e).splitlines()[-1][:160])
    files = sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(VIDEO_TYPES))
    if not files:
        raise MinerError("The video was fetched but no video file was saved.")
    meta = {k: info.get(k) for k in ("id", "title", "channel", "uploader", "upload_date", "duration", "view_count",
                                     "webpage_url", "language")}
    return files[0], meta


def transcribe(video, model_name="base", language=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise MinerError("Transcribing needs the video tools. Run: python factory.py setup --tier video")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(os.path.abspath(video), language=language, word_timestamps=True,
                                      vad_filter=True, vad_parameters={"min_silence_duration_ms": 300})
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
    return {"made_with": "faster-whisper:%s" % model_name, "language": info.language,
            "seconds": round(info.duration, 2), "segments": [s for s in segs if s["text"]]}


# ----------------------------------------------------------------------------- the index
def said_between(transcript, start, end):
    if not transcript:
        return ""
    return " ".join(s["text"] for s in transcript["segments"] if s["end"] > start and s["start"] < end).strip()


def build_index(kept, transcript, pad=PAD_SECS):
    rows = []
    for k in kept:
        said = said_between(transcript, k["t"] - pad, k["t_end"] + pad)
        rows.append({"index": k["index"], "file": k["file"], "at": clock(k["t"]), "seconds": round(k["t"], 2),
                     "on_screen_for": round(k["t_end"] - k["t"], 2), "kind": k["kind"], "why_kept": k["why"],
                     "absorbed": k["absorbed"], "absorbed_as": k["absorbed_as"], "repeat_of": k["repeat_of"],
                     "said_around_it": said, "a_number_is_spoken_here": bool(_NUMBER_WORD.search(said))})
    return rows


def transcript_blocks(transcript, every=30):
    out, block, started = [], [], None
    for s in (transcript or {}).get("segments", []):
        if started is None:
            started = s["start"]
        if s["start"] - started >= every and block:
            out.append((started, " ".join(block)))
            block, started = [], s["start"]
        block.append(s["text"])
    if block:
        out.append((started, " ".join(block)))
    return out


def render_index(brand, title, rows, stats, transcript):
    lines = ["# Video index: %s" % title, "", "For **%s**." % brand.name, "", store.RULES_OF_USE, "",
             "**%d stills kept of %d taken.** %d absorbed because nothing changed, %d because it was the same scene "
             "with a small change too soon after the last still." % (
                 stats["kept"], stats["taken"], stats["absorbed_same"], stats["absorbed_moved"]), "",
             "## How Claude reads this", "",
             "1. **Open the stills and read them.** The text on screen is not written out anywhere in this folder, "
             "on purpose: a machine reading of small type gets numbers wrong. Read each still yourself.",
             "2. Start with the rows marked **a number is spoken here**, then every **new scene**. Rows marked "
             "*same scene* are usually a person moving; read them when the words beside them mention a figure.",
             "3. **Quote a number exactly as it appears, with its time**, or leave it out. Never round it, never "
             "rebuild it from memory, never combine two numbers into a new one.",
             "4. A number that is only SPOKEN is quoted as transcribed and marked \"heard, check the audio at "
             "[time]\": a speech model can mishear a figure.",
             "5. If the video gives a figure without saying where it comes from, write **source not stated**.", "",
             store.md_table(["#", "Time", "Still", "Kind", "On screen (s)", "Number spoken?", "Said around it"],
                            [[r["index"], r["at"], "frames/" + r["file"],
                              {"scene": "new scene", "changed": "same scene, changed"}.get(r["kind"], r["kind"])
                              + (" (seen before at #%d)" % r["repeat_of"] if r["repeat_of"] else ""),
                              r["on_screen_for"], "yes" if r["a_number_is_spoken_here"] else "",
                              r["said_around_it"][:260]] for r in rows]), ""]
    if not transcript:
        lines += ["There is no transcript for this video, so the last column is empty.", ""]
    return "\n".join(lines)


FACTS = """# Facts and lessons: {title}

Source: {source}
Length: {length}. Stills kept: {kept}. Transcript: {made_with}.

**Not filled in yet.** Claude fills this in with you by reading `index.md`, the stills in `frames/` and
`transcript.md`.

## The rules for this page

1. **Exact or absent.** Every number is written exactly as it is shown or said. No rounding, no rewording,
   no working a new number out from two others.
2. **Every line carries a time**, like [12:04], so anyone can check it in seconds.
3. **Say where it was**: `screen`, `spoken` or `both`. A number that was only spoken is marked
   "heard, check the audio".
4. **Say whose number it is.** If the video names a source for a figure, record it. If it does not, write
   `source not stated`. A figure with no source is a claim by the person in the video, not a fact, and
   it is labelled `unverified` until someone finds the original.
5. **Collect everything first, tidy second.**
6. **This is for learning, not for lifting.** Their examples, stories and phrasing stay theirs.

## 1. Numbers and facts

| # | Time | Exactly as shown or said | Where | Whose number | Checked? |
|---|------|--------------------------|-------|--------------|----------|
| 1 |      |                          |       |              | unverified |

## 2. Lessons (what is being argued, and the reasoning)

## 3. What {brand} could do with this (each one traced to a lesson above)

## 4. Still to check

Numbers with no stated source, anything that sounded wrong, any still that was hard to read.
Nothing from this section is used until it has been checked.
"""


# ----------------------------------------------------------------------------- the job
def mine(brand, source, every=INTERVAL, local_every=LOCAL_EVERY, opening_seconds=0, model="base", language=None,
         transcript=True, keep_raw=False, keep_video=False, label=None, today=None):
    """Mine one video into the brand's research folder. `source` is a web link or a video file."""
    brand = store.as_brand(brand)
    source = str(source or "").strip()
    if every < 0.5 or every > 60:
        raise MinerError("The gap between stills must be between half a second and a minute.")
    local = os.path.isfile(source)
    if not local and not re.match(r"^https?://", source, re.I):
        raise MinerError("That is neither a video file on this computer nor a web link.")
    if local and not source.lower().endswith(VIDEO_TYPES):
        raise MinerError("That file is not a kind of video this can read (%s)." % ", ".join(VIDEO_TYPES))

    name = label or (os.path.splitext(os.path.basename(source))[0] if local else source.rstrip("/").split("/")[-1])
    run_dir = store.new_run_dir(brand, JOB, name, today)
    meta, fetched = {}, None
    if local:
        video = source
    else:
        video, meta = download(source, os.path.join(run_dir, "_video"))
        fetched = video
    facts = probe(video)
    seconds, warnings = facts["seconds"], []
    if not facts["has_video"]:
        raise MinerError("That file has sound but no picture, so there are no stills to take.")
    title = meta.get("title") or os.path.basename(source)

    raw_dir = os.path.join(run_dir, "frames", "_raw")
    stills = extract_stills(video, raw_dir, every)
    kept = dedupe(stills, local_every=max(local_every, every), interval=every)
    frames_dir = os.path.join(run_dir, "frames")
    for k in kept:
        k["file"] = "f%04d_%06ds.jpg" % (k["index"], int(k["t"]))
        shutil.copyfile(k["path"], os.path.join(frames_dir, k["file"]))
    if not keep_raw:
        shutil.rmtree(raw_dir, ignore_errors=True)
    opening = []
    if opening_seconds:
        opening = extract_stills(video, os.path.join(run_dir, "opening"), 1.0,
                                 first_seconds=min(float(opening_seconds), 30.0), prefix="o")

    spoken = None
    if transcript and not facts["has_audio"]:
        warnings.append("This video has no sound, so there is no transcript. The stills are indexed as usual.")
    elif transcript:
        spoken = transcribe(video, model, language)
        if not spoken["segments"]:
            warnings.append("No speech was found in this video, so the transcript is empty.")
    rows = build_index(kept, spoken)
    stats = {"taken": len(stills), "kept": len(kept),
             "absorbed_same": sum(k["absorbed_as"].get("same", 0) for k in kept),
             "absorbed_moved": sum(k["absorbed_as"].get("moved", 0) for k in kept)}

    if spoken:
        store.write_json(brand, os.path.join(run_dir, "transcript.json"), spoken)
        store.write_text(brand, os.path.join(run_dir, "transcript.md"),
                         "# Transcript, in half-minute blocks\n\nMade with %s. A guide to where things are said; "
                         "check any number against the audio.\n\n%s" % (
                             spoken["made_with"],
                             "\n\n".join("**[%s]** %s" % (clock(t), text) for t, text in transcript_blocks(spoken))))
    store.write_json(brand, os.path.join(run_dir, "index.json"), {"title": title, "stats": stats, "stills": rows})
    store.write_text(brand, os.path.join(run_dir, "index.md"), render_index(brand, title, rows, stats, spoken))
    store.write_text(brand, os.path.join(run_dir, "FACTS.md"), FACTS.format(
        title=title, source=meta.get("webpage_url") or ("a video file on this computer: " + os.path.basename(source)),
        length=clock(seconds), kept=len(kept), made_with=(spoken or {}).get("made_with", "none"), brand=brand.name))
    if fetched and not keep_video:
        shutil.rmtree(os.path.dirname(fetched), ignore_errors=True)       # only ever the copy this tool fetched
    store.write_record(brand, run_dir, JOB,
                       {"source": meta.get("webpage_url") or os.path.basename(source), "from": "file" if local else "link",
                        "every_seconds": every, "local_every_seconds": max(local_every, every),
                        "opening_seconds": opening_seconds, "model": model if transcript else None},
                       extra={"video": dict(meta, seconds=round(seconds, 2)), "stills": stats,
                              "opening_stills": len(opening), "returned": len(kept), "warnings": warnings,
                              "cost": {"estimated_usd": 0, "note": "No cost: everything ran on this computer."}})
    return {"ran": True, "folder": store.rel(brand, run_dir), "count": len(kept), "stats": stats,
            "seconds": seconds, "transcribed": bool(spoken and spoken["segments"]), "warnings": warnings}
