"""montage.py - a narrated film cut from many sources.

The clip tools cut ONE recording on its own words. A montage is the other shape of video: a
written narration (a synthesised voice, or the person's own read) laid over shots taken from many
different files. Every rule here came from a mistake that only showed up when a person watched
the finished film:

  * The picture follows the VOICE. Each line of narration is measured, and its shots share that
    time exactly. Every shot is a whole number of frames, counted from the start of the film, so
    fifty shots cannot drift a second out of step with the words.
  * A shot must fit inside its source. One that runs past the end comes out short and pulls every
    later cut early. It is refused before anything is made.
  * A shot must not straddle a scene change inside its source; that shows as a one-frame blip.
    Each shot's window is searched for changes.
  * A slow push across a still picture reads as a frozen frame under a line about motion. It is
    flagged; the person decides.
  * Each line's take is kept under a name made from its SPOKEN words and voice settings, not its
    position. Adding a line never re-voices the others, and a pronunciation fix re-voices only the
    lines that hold that word, so cuts timed to a word stay on it.
  * A number in the narration needs a source, or it is unverified. Footage from outside the
    brand's own folder needs a credit.
  * Nothing is judged from the plan alone. Render writes a contact sheet taken from the FINISHED
    film at the middle of every shot, and measures its picture against its sound.

The plan (Client/<brand>/Output/video/films/<film>/plan.json):

    {
      "title": "Spring bake",
      "size": [1920, 1080], "fps": 30, "gap": 0.34, "background": "#000000", "quality": "final",
      "voice": {"elevenlabs": {"voice_id": "...", "model": "eleven_turbo_v2", "settings": {...}}}
            or {"recording": "voiceover.wav"}          (then every line has "from" and "to" in it)
      "say_as": {"brioche": "bree-osh"},               how a word is spoken (plain respelling, or a
                                                       phoneme tag on the turbo and flash models)
      "sources": {"oven": {"file": "oven.mp4", "crop": "1920:1000:0:40", "fit": "fill",
                           "credit": "Our own footage"}},
      "opening": [{"source": "oven", "at": 2.0, "seconds": 3.0}],     silent, before the first line
      "lines": [{"say": "Fresh bread every morning.",
                 "shots": [{"source": "oven", "at": 12.5}, {"source": "oven", "at": 40.0, "seconds": 1.2}],
                 "hold": 0.0, "fact_source": "", "voice_settings": {}}],
      "end_card": {"image": "card.png", "seconds": 4.5},
      "music": {"file": "bed.m4a", "level_db": -12}  or  {"bed": "drone", "level_db": -12}
            or {"compose": {"prompt": "warm, unhurried acoustic guitar", "instrumental": true,
                            "seconds": 90}, "level_db": -12}     made to order (montage music)
    }

A shot without "seconds" shares what is left of its line equally with the others; one with
"seconds" is pinned (use it to land a cut on a word, or to stay clear of a change in the source).
A shot with "speed" plays slower (0.5 is half speed) or faster; its seconds are screen time, and it
is checked against the stretch of source it really uses. A source that is a still image holds with a
slow "move" (in, out, left, right, up, down, none). A line of {"pause": 8, "shots": [...]} is a silent
passage: pictures and music only, for exactly that long, never voiced. Music with "compose" is made
to order by ElevenLabs Music (`montage music`, which says the cost and sends nothing without
--confirm); the bed it makes is saved in the film's music folder and becomes the plan's "file".
Files are found as written (absolute), in the film's folder, or in the brand's folder.

The footage folder (Client/<brand>/Inputs/Footage) is the one place a brand's footage and pictures
go. `montage footage` lists what is there in footage.json (length, "shows": what is in it,
"credit": whose it is). `montage draft` writes a plan from that list and from words that already
exist: the brand's own onboarding answers (--from-brand) or a finished script (--from-script). A
drafted line has "part" (its place in the arc), "wants" (what to show, in words) and maybe
"suggested" footage ids; its shots stay empty until a person looks at the frames and places them.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time

from smf import keys
from smf.video.common import (VideoError, as_brand, concat_line, fmt_ts, is_number_token, join_parts, probe_duration,
                              programs, read_json, run, safe_name, tokens_of, write_json_atomic, write_text_atomic)
from smf.brands import replace_patiently

PLAN_FILE = "plan.json"
FILM_FILE = "film.mp4"
SHEET_FILE = "shots.jpg"
CREDITS_FILE = "credits.txt"
REPORT_FILE = "report.json"
VOICE_DIR = "voice"
WORK_DIR = ".work"

KEY_NAME = "ELEVENLABS_API_KEY"
TTS_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/%s"
# The ElevenLabs models this copy knows, and what each honours in the text it is sent.
#   tags      audio tags such as [confident] or [whispers] steer the delivery (v3 and v4). On a
#             model without them the tag is READ ALOUD: "open bracket, confident, close bracket".
#   phonemes  SSML phoneme tags in say_as (the first turbo and flash models only). A model without
#             them accepts the tagged word and then leaves it out: silence where the word should be.
#   ipa       v4 understands IPA between forward slashes, /ˈɔːrə/, as a plain respelling would be.
#   settings  the voice settings the model listens to; anything else is not sent.
# Both mistakes are refused by check before a character is sent. An unknown model is a warning.
_ALL = ("stability", "similarity_boost", "style", "use_speaker_boost", "speed")
MODELS = {
    "eleven_v4":              {"tags": True,  "phonemes": False, "ipa": True,  "settings": ("stability",)},
    "eleven_v4_turbo":        {"tags": True,  "phonemes": False, "ipa": True,  "settings": ("stability",)},
    "eleven_v3":              {"tags": True,  "phonemes": False, "ipa": False, "settings": ("stability",)},
    "eleven_multilingual_v2": {"tags": False, "phonemes": False, "ipa": False, "settings": _ALL},
    "eleven_flash_v2":        {"tags": False, "phonemes": True,  "ipa": False, "settings": _ALL},
    "eleven_flash_v2_5":      {"tags": False, "phonemes": False, "ipa": False, "settings": _ALL},
    "eleven_turbo_v2":        {"tags": False, "phonemes": True,  "ipa": False, "settings": _ALL},
    "eleven_turbo_v2_5":      {"tags": False, "phonemes": False, "ipa": False, "settings": _ALL},
}
# v3 and v4 take stability as a word as well as a number
STABILITY_WORDS = {"creative": 0.0, "natural": 0.5, "robust": 1.0}
DEFAULT_MODEL = "eleven_turbo_v2"
DEFAULT_SETTINGS = {"stability": 0.40, "similarity_boost": 0.80, "style": 0.18}
_TAG = re.compile(r"\[[^\]\n]{1,60}\]")
_PHONEME = re.compile(r"<\s*phoneme\b", re.I)


def model_of(plan):
    return (plan.get("voice") or {}).get("elevenlabs", {}).get("model") or DEFAULT_MODEL


def model_knows(plan, what):
    """Whether the plan's model honours `what` (tags, phonemes, ipa). An unknown model is taken at
    its word: nothing is refused, and check says it does not know the model."""
    known = MODELS.get(model_of(plan))
    return True if known is None else bool(known.get(what))

MIN_SHOT = 0.8              # seconds: shorter than this and a shot does not read
MIN_SPEED, MAX_SPEED = 0.25, 4.0    # a shot's "speed": 0.5 is half-speed slow motion
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp")
# a still image holds the screen with a slow, steady move, so it reads as chosen rather than frozen
MOVES = ("in", "out", "left", "right", "up", "down", "none")
MOVE_ZOOM = 0.12                    # how far a move travels over the whole shot
MOVE_OVERSCAN = 1.5                 # stills are framed this much larger than the film, so a move stays sharp
THREADS = 2                         # per encode and decode: enough on any machine, gentle on a busy one


def _is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXT
EDGE = 0.05                 # a change this close to a shot's edge is the cut itself, not a blip
SCENE_THRESHOLD = 0.25      # 0.35 missed real changes in practice; 0.25 found them
STILL_LIMIT = 1.5           # average picture change between frames a quarter-second apart, of 255
WORDS_PER_SECOND = 2.6      # only for estimates, before the voice exists
QUALITY = {"final": ("medium", "18"), "draft": ("ultrafast", "28")}


# ----------------------------------------------------------------------------- where things live
def film_dir(brand, film):
    return as_brand(brand).path("Output", "video", "films", safe_name(film, "film"))


def _find(brand, film, written):
    """A file named in the plan: as written (absolute), in the film's folder, or in the brand's."""
    if not isinstance(written, str) or not written.strip():
        return None
    written = written.strip().strip('"')
    if os.path.isabs(written):
        return written if os.path.isfile(written) else None
    parts = [p for p in re.split(r"[\\/]+", written) if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    for base in (film_dir(brand, film), as_brand(brand).home):
        candidate = os.path.join(base, *parts)
        if os.path.isfile(candidate):
            return candidate
    return None


def _inside(brand, path):
    home = os.path.abspath(as_brand(brand).home)
    return os.path.abspath(path).startswith(home + os.sep)


# ----------------------------------------------------------------------------- the plan
def brand_voice(brand):
    """The brand's own voice from its settings (video.voice): the ElevenLabs voice it speaks with,
    its model, settings, named styles and how its own words are said. None when it has none."""
    voice = ((as_brand(brand).data.get("video") or {}).get("voice") or {})
    eleven = voice.get("elevenlabs") or {}
    if not isinstance(eleven, dict) or not eleven.get("voice_id"):
        return None
    out = {"voice": {"elevenlabs": json.loads(json.dumps(eleven))}}
    if isinstance(voice.get("say_as"), dict):
        out["say_as"] = dict(voice["say_as"])
    return out


def starter_plan(title, brand=None):
    plan = {
        "title": title,
        "size": [1920, 1080], "fps": 30, "gap": 0.34, "background": "#000000", "quality": "final",
        "voice": {"elevenlabs": {"voice_id": "PUT-A-VOICE-ID-HERE", "model": DEFAULT_MODEL}},
        "say_as": {},
        "sources": {"example": {"file": "PUT-A-VIDEO-FILE-HERE.mp4", "fit": "fill",
                                "credit": "Say where this came from and under what licence"}},
        "opening": [],
        "lines": [{"say": "Write the first line of the narration here.",
                   "shots": [{"source": "example", "at": 0.0}]}],
    }
    own = brand_voice(brand) if brand is not None else None
    if own:
        plan["voice"] = own["voice"]
        plan["say_as"] = own.get("say_as", {})
    return plan


def create(brand, film, title=None):
    path = os.path.join(film_dir(brand, film), PLAN_FILE)
    if os.path.exists(path):
        raise VideoError("A film called '%s' already has a plan. Nothing was changed. Open it and edit it, or "
                         "choose another name." % film)
    write_json_atomic(path, starter_plan(title or film, brand))
    return path


def load(brand, film):
    path = os.path.join(film_dir(brand, film), PLAN_FILE)
    if not os.path.isfile(path):
        raise VideoError("There is no plan for a film called '%s' yet. Start one with: factory.py montage new "
                         "--brand <id> --film \"%s\"" % (film, film))
    plan = read_json(path, "The plan for '%s'" % film)
    if not isinstance(plan, dict) or not isinstance(plan.get("lines"), list) or not plan["lines"]:
        raise VideoError("The plan for '%s' has no lines of narration. Each line needs \"say\" and \"shots\"." % film)
    return plan


def _fps(plan):
    return int(plan.get("fps") or 30)


def _size(plan):
    w, h = (plan.get("size") or [1920, 1080])[:2]
    return int(w), int(h)


def _gap(plan):
    return float(plan.get("gap", 0.34))


def _voice_mode(plan):
    voice = plan.get("voice") or {}
    if "recording" in voice:
        return "recording"
    if "elevenlabs" in voice:
        return "elevenlabs"
    return None


# ----------------------------------------------------------------------------- the footage folder
# The protocol for every brand: footage and pictures go in ONE folder, Inputs/Footage, and the
# film is cut from what is there. `scan_footage` keeps a list beside the files (footage.json): each
# file's length, what is in it in the person's words ("shows") and whose it is ("credit"). A draft
# plan takes its sources from that list, so nothing points at a download folder that will vanish.
FOOTAGE_FILE = "footage.json"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".mpg", ".mpeg", ".wmv")
FOOTAGE_ABOUT = ("Every piece of footage this brand may cut from: one entry per file in Inputs/Footage, kept up to "
                 "date by `factory.py montage footage`. Fill in \"shows\" (what is in it, in plain words) and "
                 "\"credit\" (your own, or whose and under what licence). A draft plan lists these as its sources "
                 "and suggests shots by \"shows\". An entry is never removed here: a file that has gone is marked "
                 "missing until it is back.")
# words that say nothing about what a shot shows
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with", "is", "are", "it", "its",
         "this", "that", "we", "our", "you", "your", "i", "my", "as", "by", "from", "be", "so", "not", "was"}


def footage_dir(brand):
    return as_brand(brand).path("Inputs", "Footage")


def footage_file(brand):
    return os.path.join(footage_dir(brand), FOOTAGE_FILE)


def load_footage(brand):
    """The footage list, or an empty one when the folder has never been scanned."""
    path = footage_file(brand)
    if not os.path.isfile(path):
        return {"_about": FOOTAGE_ABOUT, "files": {}}
    data = read_json(path, "The footage list (%s)" % path)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise VideoError("The footage list (%s) is not in the shape the Factory writes. Nothing was changed. "
                         "Ask Claude to look at it before going on." % path)
    return data


def _footage_id(rel, taken):
    stem = os.path.splitext(os.path.basename(rel))[0]
    base = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "file"
    cand, n = base, 2
    while cand in taken:
        cand, n = "%s-%d" % (base, n), n + 1
    return cand


def scan_footage(brand):
    """Look through Inputs/Footage and bring footage.json up to date. A new file is added under a
    name made from its file name, with its length measured. What a person wrote about a file
    ("shows", "credit", "crop", "fit", "move") is kept. A file that has gone is marked missing,
    never dropped: its notes are their work. Returns what changed, by id."""
    brand = as_brand(brand)
    folder = footage_dir(brand)
    os.makedirs(folder, exist_ok=True)
    data = load_footage(brand)
    files = data["files"]
    by_file = {entry.get("file"): fid for fid, entry in files.items() if isinstance(entry, dict)}
    present = {}
    for root, _dirs, names in os.walk(folder):
        for name in sorted(names):
            ext = os.path.splitext(name)[1].lower()
            if name.startswith(".") or name == FOOTAGE_FILE or (ext not in VIDEO_EXT and ext not in IMAGE_EXT):
                continue
            full = os.path.join(root, name)
            present[os.path.relpath(full, brand.home).replace(os.sep, "/")] = full
    added, returned, unnamed = [], [], []
    for rel, full in present.items():
        fid = by_file.get(rel)
        if fid is None:
            fid = _footage_id(rel, files)
            files[fid] = {"file": rel, "kind": "image" if _is_image(full) else "video", "seconds": None,
                          "shows": "", "credit": "", "crop": "", "fit": "fill"}
            added.append(fid)
        entry = files[fid]
        if entry.pop("missing", False):
            returned.append(fid)
        if entry.get("kind") != "image":
            entry["seconds"] = round(float(probe_duration(full)), 2)
        if not str(entry.get("shows") or "").strip():
            unnamed.append(fid)
    missing = []
    for fid, entry in files.items():
        if isinstance(entry, dict) and entry.get("file") not in present:
            entry["missing"] = True
            missing.append(fid)
    data["_about"] = FOOTAGE_ABOUT
    write_json_atomic(footage_file(brand), data)
    return {"path": footage_file(brand), "folder": folder, "files": len(present), "added": added,
            "returned": returned, "missing": missing, "unnamed": unnamed}


def footage_sources(footage):
    """The footage list as a plan's sources: every file that is there, under its id."""
    out = {}
    for fid, entry in footage.get("files", {}).items():
        if not isinstance(entry, dict) or entry.get("missing") or not entry.get("file"):
            continue
        src = {"file": entry["file"], "fit": entry.get("fit") or "fill"}
        for key in ("crop", "credit", "move"):
            if entry.get(key):
                src[key] = entry[key]
        out[fid] = src
    return out


def suggest_shots(text, footage, limit=2):
    """Footage ids whose notes share words with what a line wants to show. A suggestion, never a
    shot: someone still looks at the frames and chooses the moment."""
    want = set(tokens_of(text)) - _STOP
    if not want:
        return []
    scored = []
    for fid, entry in footage.get("files", {}).items():
        if not isinstance(entry, dict) or entry.get("missing"):
            continue
        have = set(tokens_of("%s %s" % (fid.replace("-", " "), entry.get("shows") or ""))) - _STOP
        hit = len(want & have)
        if hit:
            scored.append((-hit, fid))
    return [fid for _hit, fid in sorted(scored)[:limit]]


# ----------------------------------------------------------------------------- a draft plan
# A draft is a plan whose lines are already written and whose shots are not: the words come from
# the brand's own onboarding answers, or from a script the writer finished, never from here. Each
# line carries "part" (its place in the arc), "wants" (what it should show, in words) and, when the
# footage list has notes, "suggested" footage ids. check reports every line without shots, so a
# draft cannot be rendered by accident.
def _own_words(value):
    text = value.strip() if isinstance(value, str) else ""
    return "" if not text or text.upper().startswith("TODO") else text


def _value(item):
    return item.get("value") if isinstance(item, dict) else item


def brand_lines(brand):
    """Lines of narration in the brand's OWN words, from its settings, in a story arc: why they
    started, what changed in the world, the problems, the truth they hold, its proof, what they do
    and how that differs, the myth and the mistake they correct, the steps, the offer. Every line
    names where it came from. Returns (lines, missing): what the brand has not said yet."""
    data = as_brand(brand).data
    lines, missing = [], []

    def add(part, text, where, wants):
        text = _own_words(text)
        if text:
            lines.append({"part": part, "say": text, "shots": [], "fact_source": where, "wants": wants})
        return bool(text)

    positioning = data.get("positioning") or {}
    story = positioning.get("story") or {}
    if not add("why", (data.get("person") or {}).get("why_started"), "brand-master.json: person.why_started",
               "the person who started it, or where it began"):
        missing.append("why they started (onboarding: Speakers)")
    if not add("catalyst", _value(story.get("catalyst")), "brand-master.json: positioning.story.catalyst",
               "the world the brand works in, before the product appears"):
        missing.append("what changed in the world (onboarding: What you stand for, the story)")
    for k, problem in enumerate(((data.get("audience") or {}).get("problems") or [])):
        add("problem", problem, "brand-master.json: audience.problems[%d]" % k, "that problem, out in the world")
    if not add("core_truth", _value(story.get("core_truth")), "brand-master.json: positioning.story.core_truth",
               "the idea, shown rather than said: the place or the people it is about"):
        missing.append("the truth the brand holds (onboarding: What you stand for, the story)")
    proofs = [p for p in (story.get("proof") or []) if _own_words(_value(p))]
    for k, proof in enumerate(proofs):
        add("story_proof", _value(proof), "brand-master.json: positioning.story.proof[%d]" % k,
            "evidence of that change, out in the world")
    if not proofs:
        missing.append("what shows the story is true (onboarding: What you stand for, the story)")
    if not add("what_we_do", (data.get("business") or {}).get("what_we_do"), "brand-master.json: business.what_we_do",
               "the product in use"):
        missing.append("what the brand does (onboarding: Basics)")
    for k, diff in enumerate(positioning.get("differentiation") or []):
        if isinstance(diff, dict):
            add("others", diff.get("others"), "brand-master.json: positioning.differentiation[%d].others" % k,
                "how it is usually done")
            add("us", diff.get("us"), "brand-master.json: positioning.differentiation[%d].us" % k,
                "how the brand does it instead")
    for part, key, wants in (("myth", "myths", "the belief people hold, then what is really true"),
                             ("mistake", "mistakes", "the mistake as it happens"),
                             ("step", "steps_to_result", "that step being done")):
        for k, item in enumerate(data.get(key) or []):
            add(part, _value(item), "brand-master.json: %s[%d]" % (key, k), wants)
    offers = [o for o in (data.get("offers") or []) if isinstance(o, dict)]
    offer = next((o for o in offers if o.get("rung") == "main"), None) or next((o for o in offers if o.get("link")), None)
    if offer:
        said = ". ".join(_own_words(offer.get(key)) for key in ("name", "what", "price") if _own_words(offer.get(key)))
        line = {"part": "offer", "say": said + ".", "shots": [], "fact_source": "offer:%s" % offer.get("id", ""),
                "wants": "the product, and where to get it"}
        if offer.get("link"):
            line["link"] = offer["link"]
        lines.append(line)
        if not offer.get("link"):
            missing.append("a link for the offer '%s', so the film can send people somewhere" % offer.get("name", ""))
    else:
        missing.append("an offer to end on (onboarding: Your offers)")
    return lines, missing


def script_lines(path):
    """Lines of narration from a finished short-form script: its opening, every written line and
    the call to action, in order. "Say" becomes the line, "Show" what it wants, "Source" its fact
    source, words on screen stay on the line. A placeholder nobody filled in is not a line.
    Returns (lines, problems)."""
    from smf.scripts import brief
    with open(path, "r", encoding="utf-8-sig") as f:
        parsed = brief.parse(f.read())
    lines = []

    def add(part, say, show, source, on_screen):
        if not brief.is_filled(say):
            return
        line = {"part": part, "say": say.strip(), "shots": [],
                "fact_source": (source or "").strip() if brief.is_filled(source) else "",
                "wants": (show or "").strip() if brief.is_filled(show) else ""}
        if brief.is_filled(on_screen):
            line["on_screen"] = on_screen.strip()
        lines.append(line)

    o = parsed.opening
    add("opening", o.say, o.show, o.source, o.on_screen)
    for ln in parsed.lines:
        add("line %d" % ln.number, ln.say, ln.show, ln.source, ln.on_screen)
    c = parsed.cta
    add("call to action", c.say, c.show, c.source, c.on_screen)
    return lines, list(parsed.problems)


def _has_real_lines(plan):
    starter = starter_plan("")["lines"][0]["say"]
    return isinstance(plan, dict) and any(isinstance(ln, dict) and _own_words(ln.get("say")) not in ("", starter)
                                          for ln in plan.get("lines") or [])


def draft(brand, film, from_brand=False, script=None, title=None):
    """Write a draft plan for a film: lines from the brand's own words (from_brand) or from a
    finished script, sources from the footage folder, shots left for a person to place. Never
    overwrites a plan that already has lines. Returns what was made and what is still missing."""
    brand = as_brand(brand)
    if bool(from_brand) == bool(script):
        raise VideoError("Say where the words come from: --from-brand (the brand's own onboarding answers) or "
                         "--from-script <file> (a finished script). One or the other.")
    path = os.path.join(film_dir(brand, film), PLAN_FILE)
    if os.path.isfile(path) and _has_real_lines(read_json(path, "The plan for '%s'" % film)):
        raise VideoError("'%s' already has a plan with lines in it. Nothing was changed. Draft under another "
                         "film name, or edit that plan." % film)
    scan = scan_footage(brand)
    footage = load_footage(brand)
    sources = footage_sources(footage)
    if from_brand:
        lines, missing = brand_lines(brand)
        came_from = "the brand's own words (brand-master.json)"
    else:
        script_path = _find(brand, film, script)
        if not script_path:
            raise VideoError("The script '%s' is not there. Give its path inside the brand's folder, or the "
                             "whole path." % script)
        lines, missing = script_lines(script_path)
        came_from = "the script %s" % os.path.relpath(script_path, brand.home).replace(os.sep, "/") \
            if _inside(brand, script_path) else "the script %s" % script_path
        if not lines:
            raise VideoError("The script '%s' has no spoken lines yet (every Say is still a placeholder), so there "
                             "is nothing to draft from.%s" % (script, (" " + " ".join(missing)) if missing else ""))
    if not lines:
        raise VideoError("The brand has not said enough yet to draft from: %s." % "; ".join(missing))
    suggested = 0
    for line in lines:
        ids = suggest_shots("%s %s" % (line.get("wants", ""), line["say"]), footage)
        if ids:
            line["suggested"] = ids
            suggested += 1
    plan = starter_plan(title or film, brand)
    try:
        plan["background"] = brand.colours.get("ground") or plan["background"]
    except (KeyError, AttributeError):
        pass
    plan["sources"] = sources or plan["sources"]
    plan["lines"] = lines
    plan["drafted_from"] = came_from
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json_atomic(path, plan)
    own = [n for n in (brand.data.get("own_brands") or []) if isinstance(n, str)]
    voiced = brand_voice(brand) is not None
    return {"path": path, "lines": len(lines), "sources": len(sources), "suggested": suggested,
            "missing": missing, "footage": scan, "no_footage": not sources, "words_to_check": own,
            "from": came_from, "own_voice": voiced, "model": model_of(plan)}


# ----------------------------------------------------------------------------- the voice
def style_tag(plan, i, strict=True):
    """The delivery a line asks for, as the audio tag that goes in front of its words. A style is a
    name from the voice's "styles" ({"confident": "[confident]", "warm": "[warm, unhurried]"}),
    chosen per line with "style" or for the whole film with the voice's "style". A line may also
    give the tag itself. Returns "" when nothing is asked for. A style nobody defined is an error
    when strict; otherwise it is returned as written, so a take's name still tells it apart."""
    eleven = (plan.get("voice") or {}).get("elevenlabs") or {}
    styles = eleven.get("styles") or {}
    asked = plan["lines"][i].get("style")
    if asked is None:
        asked = eleven.get("style")
    if not asked:
        return ""
    tag = styles.get(asked, asked if _TAG.fullmatch(str(asked).strip()) else None)
    if tag is None:
        if not strict:
            return str(asked).strip()
        raise VideoError("Line %d asks for the style '%s', which the voice does not define. Add it under "
                         "\"styles\" as an audio tag, for example {\"%s\": \"[%s]\"}." % (i + 1, asked, asked, asked))
    return str(tag).strip()


def spoken(plan, i):
    """The words as sent to the voice: each `say_as` word swapped for how it is said, with the
    line's style tag in front when it has one."""
    text = str(plan["lines"][i].get("say") or "")
    for word, say in (plan.get("say_as") or {}).items():
        text = re.sub(r"(?<![\w-])%s(?![\w-])" % re.escape(word), lambda _m: say, text)
    tag = style_tag(plan, i, strict=False)
    return ("%s %s" % (tag, text)).strip() if tag else text


def _stability(value):
    if isinstance(value, str) and value.strip().lower() in STABILITY_WORDS:
        return STABILITY_WORDS[value.strip().lower()]
    return value


def _voice_identity(plan, i):
    line = plan["lines"][i]
    if _voice_mode(plan) == "recording":
        return ["recording", plan["voice"]["recording"], line.get("from"), line.get("to")]
    eleven = plan["voice"]["elevenlabs"]
    model = eleven.get("model") or DEFAULT_MODEL
    settings = dict(DEFAULT_SETTINGS)
    settings.update(eleven.get("settings") or {})
    settings.update(line.get("voice_settings") or {})
    if "stability" in settings:
        settings["stability"] = _stability(settings["stability"])
    heard = MODELS.get(model, {}).get("settings") or _ALL
    settings = {k: v for k, v in settings.items() if k in heard}
    return ["elevenlabs", spoken(plan, i), eleven.get("voice_id"), model, sorted(settings.items())]


def voice_problems(plan):
    """What would go wrong at ElevenLabs before anything is sent: a tag a model would read aloud,
    a phoneme tag a model would drop, a style that is not defined, a model this copy does not
    know. Returns (errors, warnings)."""
    errors, warnings = [], []
    if _voice_mode(plan) != "elevenlabs":
        return errors, warnings
    model = model_of(plan)
    if model not in MODELS:
        warnings.append("The voice model '%s' is not one this copy knows (%s). Tags and phoneme tags are sent as "
                        "written; listen to the first take before making the rest." % (model, ", ".join(MODELS)))
    if not model_knows(plan, "phonemes"):
        tagged = [w for w, say in (plan.get("say_as") or {}).items() if _PHONEME.search(str(say))]
        if tagged:
            errors.append("say_as uses a phoneme tag for %s, and %s leaves a phoneme-tagged word out entirely: "
                          "silence where the word should be. Use a plain respelling%s, or the model %s."
                          % (", ".join(tagged), model, " (on v4, IPA between slashes works too)"
                             if model_knows(plan, "ipa") else "",
                             " or ".join(m for m, k in MODELS.items() if k["phonemes"])))
    for i, line in enumerate(plan["lines"]):
        if _is_pause(line):
            continue
        try:
            tag = style_tag(plan, i)
        except VideoError as e:
            errors.append(str(e))
            continue
        tags = ([tag] if tag else []) + _TAG.findall(str(line.get("say") or ""))
        if tags and not model_knows(plan, "tags"):
            errors.append("Line %d carries the tag %s, and %s would read it aloud, word for word. Use a model that "
                          "takes audio tags (%s), or take the tag out."
                          % (i + 1, tags[0], model, ", ".join(m for m, k in MODELS.items() if k["tags"])))
    return errors, warnings


def voice_key(plan, i):
    """A take's name, made from what is said and how, never from where the line sits."""
    return hashlib.sha1(json.dumps(_voice_identity(plan, i)).encode("utf-8")).hexdigest()[:12]


def _is_pause(line):
    """A silent passage: pictures and music only, for exactly "pause" seconds. Never voiced."""
    return "pause" in line and not line.get("say")


def _take(brand, film, plan, i):
    return os.path.join(film_dir(brand, film), VOICE_DIR, voice_key(plan, i) + ".mp3")


def _settings(plan, i):
    return dict(_voice_identity(plan, i)[4])


def make_voice(brand, film, confirm=False):
    """Make the takes that do not exist yet. Without `confirm` it says how much text would be sent,
    and sends nothing."""
    plan = load(brand, film)
    if _voice_mode(plan) == "recording":
        return {"mode": "recording", "to_make": [], "characters": 0, "sent": False}
    if _voice_mode(plan) != "elevenlabs":
        raise VideoError("The plan does not say where the voice comes from. Give \"voice\" either "
                         "{\"elevenlabs\": {\"voice_id\": ...}} or {\"recording\": \"your-read.wav\"}.")
    wrong, _warned = voice_problems(plan)
    if wrong:
        raise VideoError("The voice would come out wrong, so nothing was sent: " + " ".join(wrong))
    to_make = [i + 1 for i in range(len(plan["lines"]))
               if not _is_pause(plan["lines"][i]) and not os.path.isfile(_take(brand, film, plan, i))]
    characters = sum(len(spoken(plan, n - 1)) for n in to_make)
    out = {"mode": "elevenlabs", "to_make": to_make, "characters": characters, "sent": False, "made": 0}
    if not confirm or not to_make:
        return out
    keys.load()
    api_key = os.environ.get(KEY_NAME) or ""
    if not api_key:
        raise VideoError("Making the voice needs an ElevenLabs key, and %s is missing from the keys file. Add it, "
                         "or record the narration yourself and use {\"recording\": ...} instead." % KEY_NAME)
    broken = keys.damaged(api_key, KEY_NAME)
    if broken:
        raise VideoError(broken + " Nothing was sent.")
    import requests
    eleven = plan["voice"]["elevenlabs"]
    for n in to_make:
        i = n - 1
        try:
            r = requests.post(TTS_ENDPOINT % eleven.get("voice_id"),
                              headers={"xi-api-key": api_key, "accept": "audio/mpeg"},
                              json={"text": spoken(plan, i), "model_id": eleven.get("model") or DEFAULT_MODEL,
                                    "voice_settings": _settings(plan, i)}, timeout=240)
        except requests.RequestException:
            raise VideoError("Could not reach ElevenLabs. %d of %d takes were made; the rest can be made by running "
                             "the same command again." % (out["made"], len(to_make)))
        if r.status_code in (401, 403):
            raise VideoError("ElevenLabs refused the key for making speech. Check that %s is complete and that it is "
                             "allowed to use text to speech." % KEY_NAME)
        if r.status_code != 200:
            raise VideoError("ElevenLabs could not voice line %d (it answered %d: %s)."
                             % (n, r.status_code, keys.redact(getattr(r, "text", ""))[:300]))
        path = _take(brand, film, plan, i)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        replace_patiently(tmp, path)
        out["made"] += 1
    out["sent"] = True
    return out


def line_words(brand, film, number, confirm=False):
    """Word times inside one line's take, so a cut can land on a word. Transcribing costs a little:
    without `confirm` it says how much and sends nothing."""
    from smf.video import transcribe
    plan = load(brand, film)
    if not 1 <= number <= len(plan["lines"]):
        raise VideoError("There is no line %d; the plan has %d." % (number, len(plan["lines"])))
    take = _take(brand, film, plan, number - 1)
    if _voice_mode(plan) == "recording":
        raise VideoError("With your own recording, transcribe the recording itself with factory.py transcribe; "
                         "the word times are in it.")
    if not os.path.isfile(take):
        raise VideoError("Line %d has no voice yet. Make it first: factory.py montage voice --confirm." % number)
    saved = take[:-4] + ".words.json"
    if os.path.isfile(saved):
        return {"line": number, "words": read_json(saved, "The word times for line %d" % number), "sent": False}
    seconds = probe_duration(take)
    cost = transcribe.cost_words(transcribe.estimate_cost(seconds))
    if not confirm:
        return {"line": number, "words": None, "sent": False, "cost_words": cost}
    keys.load()
    words = transcribe.words_from_response(transcribe.send_to_elevenlabs(take, os.environ.get(KEY_NAME) or ""))
    write_json_atomic(saved, words)
    return {"line": number, "words": words, "sent": True, "cost_words": cost}


def _durations(brand, film, plan):
    """Seconds of speech per line, and whether any of them is only an estimate."""
    out, estimated = [], False
    for i, line in enumerate(plan["lines"]):
        if _is_pause(line):
            out.append(max(0.0, float(line["pause"])))
            continue
        if _voice_mode(plan) == "recording":
            try:
                out.append(max(0.0, float(line["to"]) - float(line["from"])))
            except (KeyError, TypeError, ValueError):
                out.append(0.0)
            continue
        take = _take(brand, film, plan, i) if _voice_mode(plan) == "elevenlabs" else ""
        if take and os.path.isfile(take):
            out.append(probe_duration(take))
        else:
            out.append(max(1.0, len(str(line.get("say") or "").split()) / WORDS_PER_SECOND))
            estimated = True
    return out, estimated


# ----------------------------------------------------------------------------- music made to order
# A music bed can be composed for the film by ElevenLabs Music, from a few words about how it should
# sound. The plan says so with {"music": {"compose": {"prompt": "...", "instrumental": true,
# "seconds": 90}, "level_db": -12}}. Nothing is sent without `confirm`; the bed is saved under a
# name made from exactly what was sent, so the same bed is never paid for twice; and the plan's
# "file" is then pointed at it, so render mixes it exactly as it mixes a licensed track.
# The music is instrumental unless the person asks for words, and sung words must be the brand's
# own ("words", with "words_source" saying where they came from): a music model left to itself
# would make lyrics up, and nothing invented goes into a brand's film.
# The prompt itself is the brand's too. Left out, it is drafted from the brand's own settings (how
# its voice sounds, its industry, the looks it likes and dislikes), written into the plan for the
# person to read and change, and never sent on the run that drafted it. A brand whose settings say
# nothing usable gets no made-up mood: the person is asked for three words, used exactly.
MUSIC_DIR = "music"
MUSIC_ENDPOINT = "https://api.elevenlabs.io/v1/music"
MUSIC_MODEL = "music_v2_5"
MUSIC_MIN_SECONDS, MUSIC_MAX_SECONDS = 3, 600      # what the music model will make in one piece
MUSIC_TAIL = 4.0            # seconds past the film's end when the length is not pinned, so the fade has room


def _compose(plan):
    """The plan's "compose" settings, or None when the music is not made to order."""
    music = plan.get("music") or {}
    if "compose" not in music:
        return None
    compose = music["compose"]
    if isinstance(compose, str):
        compose = {"prompt": compose}
    if not isinstance(compose, dict):
        raise VideoError("The plan's \"compose\" should be the words for the music, like {\"prompt\": \"warm, "
                         "unhurried acoustic guitar\"}.")
    return compose


MUSIC_WORDS = (("business", "industry"), ("voice", "register"), ("visual", "likes"), ("visual", "dislikes"))


def brand_music_words(brand):
    """A prompt for the brand's music in the brand's OWN words, and where each piece came from.
    Only the joining words are the Factory's ("music under a narrated film for a ... brand"); every
    word about sound, look or feel is the brand's. Returns ("", []) when its settings say nothing
    usable, and then the person is asked for three words instead. The places are brand-master.json
    fields, "voice.register" and so on."""
    data = as_brand(brand).data
    found = {}
    for section, field in MUSIC_WORDS:
        value = (data.get(section) or {}).get(field)
        if isinstance(value, list):
            value = "; ".join(w for w in (_own_words(_value(v)) for v in value) if w)
        text = _own_words(_value(value))
        if text:
            found[field] = text.rstrip(".")
    if not found.get("register") and not found.get("likes"):
        return "", []                   # an industry alone says nothing about how music should feel
    parts = ["Music to sit quietly under a narrated film for a %s brand." % found["industry"]
             if found.get("industry") else "Music to sit quietly under a narrated film for a brand."]
    if found.get("register"):
        parts.append("The brand sounds like this: %s." % found["register"])
    if found.get("likes"):
        parts.append("Looks it likes: %s." % found["likes"])
    if found.get("dislikes"):
        parts.append("Looks it dislikes: %s." % found["dislikes"])
    where = ["%s.%s" % (s, f) for s, f in MUSIC_WORDS if f in found]
    return " ".join(parts), where


def music_spec(plan, film_seconds):
    """Exactly what would be sent to make the plan's bed, and the name it is saved under. None when
    the music is not made to order. `film_seconds` is the film's length from the timeline; it is
    used only when the person has not pinned the length with "seconds"."""
    compose = _compose(plan)
    if compose is None:
        return None
    prompt = " ".join(str(compose.get("prompt") or "").split())
    if not prompt:
        raise VideoError("Say what the music should sound like, in \"compose\": {\"prompt\": \"...\"}, or leave the "
                         "prompt out and factory.py montage music drafts it from the brand's own settings for the "
                         "person to approve. Nothing was sent.")
    instrumental = compose.get("instrumental", True) is not False
    if not instrumental:
        words = " ".join(str(compose.get("words") or "").split())
        if not words or not str(compose.get("words_source") or "").strip():
            raise VideoError("Sung words have to be the brand's own. Put them in \"compose\" as \"words\", with "
                             "\"words_source\" saying which of the brand's files they come from, or leave "
                             "\"instrumental\" on and the music has no words. Nothing was sent.")
        prompt = "%s Sing exactly these words and no others: %s" % (prompt, words)
    pinned = compose.get("seconds") is not None
    try:
        seconds = int(math.ceil(float(compose["seconds"]))) if pinned else int(math.ceil(film_seconds + MUSIC_TAIL))
    except (TypeError, ValueError):
        raise VideoError("The music's \"seconds\" should be a number of seconds, or left out to match the film.")
    if not MUSIC_MIN_SECONDS <= seconds <= MUSIC_MAX_SECONDS:
        raise VideoError("A made-to-order bed can be %d seconds to %d minutes long, and this one would be %s. %s"
                         % (MUSIC_MIN_SECONDS, MUSIC_MAX_SECONDS // 60, fmt_ts(seconds),
                            "Pin a length inside that with \"seconds\"." if pinned
                            else "The film is longer than one bed can be: pin \"seconds\" and the bed will loop, "
                                 "or use a licensed track with {\"file\": ...}."))
    model = str(compose.get("model") or MUSIC_MODEL)
    body = {"prompt": prompt, "music_length_ms": seconds * 1000, "force_instrumental": instrumental,
            "model_id": model}
    key = hashlib.sha1(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return {"body": body, "prompt": prompt, "seconds": seconds, "pinned": pinned, "instrumental": instrumental,
            "model": model, "key": key, "file": "%s/%s.mp3" % (MUSIC_DIR, key), "film_seconds": film_seconds}


def bed_on_file(brand, film, plan, spec):
    """The saved bed that already serves `spec`, as the plan would name it, or None. The exact one;
    or, when the length is not pinned, the bed made earlier from the same words and model, if it is
    at least as long as the film is now. The film's estimated length moves as the voice is made,
    and that alone should never cost a second bed."""
    if os.path.isfile(os.path.join(film_dir(brand, film), MUSIC_DIR, spec["key"] + ".mp3")):
        return spec["file"]
    music = plan.get("music") or {}
    made = music.get("made") or {}
    same = (made.get("prompt") == spec["prompt"] and made.get("model") == spec["model"]
            and bool(made.get("instrumental", True)) == spec["instrumental"])
    try:
        long_enough = float(made.get("seconds")) >= spec["film_seconds"]
    except (TypeError, ValueError):
        long_enough = False
    if not spec["pinned"] and same and long_enough and _find(brand, film, music.get("file")):
        return music["file"]
    return None


def make_music(brand, film, confirm=False):
    """Make the plan's made-to-order bed if it does not exist yet. Without `confirm` it says what
    would be sent, and sends nothing. The plan's music "file" is pointed at the bed either way."""
    brand = as_brand(brand)
    plan = load(brand, film)
    music = plan.get("music") or {}
    if _compose(plan) is None:
        if music.get("file"):
            return {"mode": "file", "sent": False, "made": False}
        if music.get("bed"):
            return {"mode": "bed", "sent": False, "made": False}
        raise VideoError("The plan has no music. Give \"music\" one of: {\"file\": ...} for a track the brand has the "
                         "rights to, {\"bed\": \"drone\"} for the built-in quiet bed, or {\"compose\": {\"prompt\": "
                         "...}} to have one made with ElevenLabs Music.")
    durations, estimated = _durations(brand, film, plan)
    tl, _placing = timeline(plan, durations)
    compose = _compose(plan)
    if not " ".join(str(compose.get("prompt") or "").split()):
        # no words yet: draft them from the brand's own settings, write them into the plan for the
        # person to read, and send nothing on this run however it was called
        words, where = brand_music_words(brand)
        if not words:
            raise VideoError("The brand's settings say nothing about how it sounds or what it likes to look like, so "
                             "there are no words of its own to make music from. Ask the person for three words that "
                             "describe the music they want, and put exactly those in \"compose\": {\"prompt\": ...}. "
                             "Nothing was sent.")
        compose["prompt"], compose["prompt_source"] = words, "brand-master.json: " + ", ".join(where)
        music["compose"] = compose
        plan["music"] = music
        write_json_atomic(os.path.join(film_dir(brand, film), PLAN_FILE), plan)
        spec = music_spec(plan, tl["seconds"])
        return dict(spec, mode="compose", sent=False, made=False, reused=False, drafted=True, drafted_from=where,
                    estimated=bool(estimated) and not spec["pinned"])
    spec = music_spec(plan, tl["seconds"])
    out = dict(spec, mode="compose", sent=False, made=False, reused=False, drafted=False,
               estimated=bool(estimated) and not spec["pinned"])
    have = bed_on_file(brand, film, plan, spec)
    if have:
        if music.get("file") != have:
            music["file"] = have
            write_json_atomic(os.path.join(film_dir(brand, film), PLAN_FILE), plan)
        out.update(file=have, reused=True)
        return out
    if not confirm:
        return out
    keys.load()
    api_key = os.environ.get(KEY_NAME) or ""
    if not api_key:
        raise VideoError("Making the music needs an ElevenLabs key, and %s is missing from the keys file. Add it, or "
                         "use a track the brand has the rights to with {\"file\": ...}, or the built-in bed with "
                         "{\"bed\": \"drone\"}." % KEY_NAME)
    broken = keys.damaged(api_key, KEY_NAME)
    if broken:
        raise VideoError(broken + " Nothing was sent.")
    import requests
    try:
        r = requests.post(MUSIC_ENDPOINT, headers={"xi-api-key": api_key, "accept": "audio/mpeg"},
                          json=spec["body"], timeout=600)
    except requests.RequestException:
        raise VideoError("Could not reach ElevenLabs. No music was made; run the same command again.")
    if r.status_code in (401, 403):
        raise VideoError("ElevenLabs refused the key for making music. Check that %s is complete and that it is "
                         "allowed to use music." % KEY_NAME)
    if r.status_code != 200:
        raise VideoError("ElevenLabs could not make the music (it answered %d: %s)."
                         % (r.status_code, keys.redact(getattr(r, "text", ""))[:300]))
    if not r.content:
        raise VideoError("ElevenLabs answered with no sound at all. Nothing was saved; try again in a minute.")
    path = os.path.join(film_dir(brand, film), MUSIC_DIR, spec["key"] + ".mp3")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    with os.fdopen(fd, "wb") as f:
        f.write(r.content)
    replace_patiently(tmp, path)
    music["file"] = spec["file"]
    music["made"] = {"prompt": spec["prompt"], "seconds": spec["seconds"], "model": spec["model"],
                     "instrumental": spec["instrumental"]}
    plan["music"] = music
    write_json_atomic(os.path.join(film_dir(brand, film), PLAN_FILE), plan)
    out.update(sent=True, made=True)
    return out


# ----------------------------------------------------------------------------- the timeline
def timeline(plan, durations, card_seconds=0.0):
    """Every shot as a whole number of frames, counted from the start of the film, so the picture
    cannot drift from the voice however many shots there are. Returns (timeline, errors)."""
    fps, gap, errors = _fps(plan), _gap(plan), []
    shots, lines, clock = [], [], 0.0

    def place(entry, line_no, seconds):
        start = clock
        a, b = round(start * fps), round((start + seconds) * fps)
        shots.append({"line": line_no, "source": entry.get("source"), "at": float(entry.get("at") or 0.0),
                      "crop": entry.get("crop"), "pinned": "seconds" in entry, "start_frame": a, "frames": b - a,
                      "seconds": (b - a) / float(fps), "speed": entry.get("speed", 1.0), "move": entry.get("move")})
        return start + seconds

    for entry in plan.get("opening") or []:
        if "seconds" not in entry:
            errors.append("Every opening shot needs \"seconds\": the opening has no voice to take its length from.")
            continue
        clock = place(entry, 0, float(entry["seconds"]))

    for i, line in enumerate(plan["lines"]):
        n = i + 1
        span = durations[i] if _is_pause(line) else durations[i] + gap + float(line.get("hold") or 0.0)
        lines.append({"number": n, "say": line.get("say") or "", "start": clock, "span": span, "speech": durations[i]})
        given = line.get("shots") or []
        if not given:
            errors.append("Line %d has no shots." % n)
            clock += span
            continue
        pinned = sum(float(s["seconds"]) for s in given if "seconds" in s)
        free = [s for s in given if "seconds" not in s]
        if not free:
            errors.append("Line %d pins every shot, so the picture cannot stretch to fit the voice and everything "
                          "after it would drift. Leave at least one shot without \"seconds\"." % n)
            share = 0.0
        else:
            share = (span - pinned) / len(free)
            if share < MIN_SHOT:
                errors.append("Line %d lasts %.2fs; its pinned shots take %.2fs, which leaves %.2fs for each of the "
                              "other %d. Shorten a pinned shot or move one to another line."
                              % (n, span, pinned, max(0.0, share), len(free)))
        line_end = clock + span
        for s in given:
            seconds = float(s["seconds"]) if "seconds" in s else max(share, 0.0)
            clock = place(s, n, seconds)
        clock = line_end

    card = plan.get("end_card") or {}
    if card:
        seconds = float(card.get("seconds") or card_seconds or 4.0)
        a, b = round(clock * fps), round((clock + seconds) * fps)
        shots.append({"line": None, "card": card.get("image"), "start_frame": a, "frames": b - a,
                      "seconds": (b - a) / float(fps), "pinned": True})
        clock += seconds
    total = round(clock * fps)
    if shots:                     # the last shot ends exactly on the last frame
        shots[-1]["frames"] = total - shots[-1]["start_frame"]
    return {"fps": fps, "frames": total, "seconds": total / float(fps), "lines": lines, "shots": shots}, errors


# ----------------------------------------------------------------------------- looking at footage
def scene_cuts(path, start, seconds, threshold=SCENE_THRESHOLD):
    """Times (in the source) of scene changes strictly inside [start, start + seconds]."""
    ff, _fp = programs()
    r = run([ff, "-hide_banner", "-ss", "%.3f" % start, "-t", "%.3f" % seconds, "-i", path, "-an",
             "-vf", "scale=320:-2,select='gt(scene,%.2f)',metadata=print:file=-" % threshold, "-f", "null", "-"],
            "look for scene changes in '%s'" % os.path.basename(path))
    found = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", (r.stdout or "") + (r.stderr or ""))]
    return sorted({round(start + t, 2) for t in found if EDGE < t < seconds - EDGE})


def is_still(path, start, seconds):
    """True when almost nothing changes between frames a quarter of a second apart."""
    import numpy as np
    ff, _fp = programs()
    w, h = 64, 36
    r = run([ff, "-v", "error", "-ss", "%.3f" % start, "-t", "%.3f" % seconds, "-i", path, "-an",
             "-vf", "fps=4,scale=%d:%d,format=gray" % (w, h), "-f", "rawvideo", "-"],
            "look at the picture in '%s'" % os.path.basename(path), binary=True)
    n = len(r.stdout) // (w * h)
    if n < 2:
        return False
    frames = np.frombuffer(r.stdout[:n * w * h], np.uint8).reshape(n, w * h).astype(np.int16)
    return float(np.abs(np.diff(frames, axis=0)).mean()) < STILL_LIMIT


# ----------------------------------------------------------------------------- the check
_CROP = re.compile(r"^\d+:\d+:\d+:\d+$")


def _numbers_in(text):
    """The numbers a line states, as written. 'one' and 'half' are left out: they are ordinary words
    far more often than they are figures ("the one thing", "half the city")."""
    return [t for t in tokens_of(text, keep_numbers=True) if is_number_token(t) and t not in ("one", "half")]


def check(brand, film):
    """Everything that can be known before rendering. Errors stop a render; warnings are for the
    person to decide on. Free: nothing is sent anywhere."""
    brand = as_brand(brand)
    plan = load(brand, film)
    errors, warnings = voice_problems(plan)
    mode = _voice_mode(plan)
    if mode is None:
        errors.append("The plan does not say where the voice comes from: {\"elevenlabs\": {...}} or "
                      "{\"recording\": \"your-read.wav\"}.")
    if mode == "recording":
        rec = _find(brand, film, plan["voice"]["recording"])
        if not rec:
            errors.append("The voice recording '%s' is not there." % plan["voice"]["recording"])
        else:
            length = probe_duration(rec)
            for i, line in enumerate(plan["lines"]):
                if _is_pause(line):
                    continue
                try:
                    a, b = float(line["from"]), float(line["to"])
                except (KeyError, TypeError, ValueError):
                    errors.append("Line %d needs \"from\" and \"to\": where it is in your recording." % (i + 1))
                    continue
                if not 0 <= a < b <= length + 0.01:
                    errors.append("Line %d is set from %s to %s, but the recording runs 00:00.0 to %s."
                                  % (i + 1, fmt_ts(a), fmt_ts(b), fmt_ts(length)))

    sources = {}
    for alias, src in (plan.get("sources") or {}).items():
        path = _find(brand, film, (src or {}).get("file"))
        if not path:
            errors.append("The source '%s' points at a file that is not there: %s" % (alias, (src or {}).get("file")))
            continue
        crop = src.get("crop")
        if crop and not _CROP.match(str(crop)):
            errors.append("The source '%s' has a crop of '%s'. Write it as width:height:x:y in pixels." % (alias, crop))
        if not _inside(brand, path) and not src.get("credit"):
            warnings.append("'%s' comes from outside the brand's folder and has no credit. Say where it came from and "
                            "under what licence (your own, public domain, licensed) before this is published." % alias)
        if src.get("move") and src["move"] not in MOVES:
            errors.append("The source '%s' has a move of '%s'. Use one of: %s." % (alias, src["move"], ", ".join(MOVES)))
        if _is_image(path):
            sources[alias] = {"path": path, "length": None, "image": True}
        else:
            sources[alias] = {"path": path, "length": probe_duration(path)}

    for i, line in enumerate(plan["lines"]):
        nums = _numbers_in(str(line.get("say") or ""))
        if nums and not line.get("fact_source"):
            warnings.append("Line %d says \"%s\" but names no source for it, so it is unverified. Add \"fact_source\": "
                            "where the number comes from." % (i + 1, ", ".join(nums)))

    card = plan.get("end_card") or {}
    if card and not _find(brand, film, card.get("image")):
        errors.append("The end card image '%s' is not there." % card.get("image"))

    durations, estimated = _durations(brand, film, plan)
    tl, placing = timeline(plan, durations)
    errors.extend(placing)
    fps = tl["fps"]
    for k, shot in enumerate(tl["shots"], 1):
        if shot.get("card"):
            continue
        where = "Opening shot %d" % k if shot["line"] == 0 else "Shot %d (line %d)" % (k, shot["line"])
        alias = shot["source"]
        if alias not in sources:
            if alias not in (plan.get("sources") or {}):
                errors.append("%s uses '%s', which is not one of the plan's sources." % (where, alias))
            continue
        if shot.get("crop") and not _CROP.match(str(shot["crop"])):
            errors.append("%s has a crop of '%s'. Write it as width:height:x:y in pixels." % (where, shot["crop"]))
        if shot.get("move") and shot["move"] not in MOVES:
            errors.append("%s has a move of '%s'. Use one of: %s." % (where, shot["move"], ", ".join(MOVES)))
        if sources[alias].get("image"):
            continue                    # a still has no end to run past, no scene change, and moves by design
        try:
            speed = float(shot.get("speed", 1.0))
        except (TypeError, ValueError):
            speed = 0.0
        if not MIN_SPEED <= speed <= MAX_SPEED:
            errors.append("%s has a speed of %s. Use %.2g (a quarter speed) up to %.2g (four times as fast); 1 is "
                          "normal, 0.5 is half-speed slow motion." % (where, shot.get("speed"), MIN_SPEED, MAX_SPEED))
            continue
        # a slowed shot uses less of its source than it fills on screen: check what it really uses
        start, seconds = shot["at"], shot["seconds"] * speed
        end, length = start + seconds, sources[alias]["length"]
        span = "takes '%s' from %s to %s" % (alias, fmt_ts(start), fmt_ts(end))
        if start < 0 or end > length + 1.0 / fps:
            errors.append("%s %s, but '%s' ends at %s. It would come out short and every cut after it would "
                          "land early." % (where, span, alias, fmt_ts(length)))
            continue
        path = sources[alias]["path"]
        for cut in scene_cuts(path, start, seconds):
            errors.append("%s %s, across a scene change at %s in the source: it will show as a blip. Move it to "
                          "one side of the change." % (where, span, fmt_ts(cut)))
        if is_still(path, start, seconds):
            warnings.append("%s %s, and it looks like a still: almost nothing moves in it. Fine for a title; under a "
                            "line about motion it reads as a frozen frame." % (where, span))
    try:
        spec = music_spec(plan, tl["seconds"])
    except VideoError as e:
        spec = None
        errors.append(str(e))
    if spec and not bed_on_file(brand, film, plan, spec):
        errors.append("The plan asks for a music bed made to order, and none has been made for these words and "
                      "this length yet. Make it first: factory.py montage music --confirm.")
    if estimated:
        warnings.append("The voice has not been made yet, so every length here is an estimate. Check again after "
                        "factory.py montage voice.")
    return {"errors": errors, "warnings": warnings, "timeline": tl, "estimated": estimated, "plan": plan,
            "sources": sources}


# ----------------------------------------------------------------------------- titles (HyperFrames)
# A motion title is an ordinary SOURCE for the plan, not a layer the renderer knows about: one small
# HTML page per piece of on-screen text, rendered frame by frame by HyperFrames (Apache 2.0,
# https://github.com/heygen-com/hyperframes) into an mp4 of the plan's size and frame rate. The
# video tier installs HyperFrames and a portable Node inside the Factory's folder (bootstrap), and
# only those copies are ever run. The text is only ever words that already exist: the plan's title
# (an opening title), a line's "on_screen" words, and the brand's wordmark and handle (an end card).
# Every title is unmistakably the brand's: its colours exactly as the card renderer mixes them
# (kit.palette), its fonts with the card renderer's fall-backs, its wordmark, handle and logo from
# the brand kit, and one simple entrance and exit, nothing else. Each clip is added to the plan as a
# source named title-<n> and SUGGESTED on its line; a person places the shot.
TITLES_DIR = "titles"                   # under the film's .work
TITLE_FILE = "title.json"               # what one title folder holds: its words, kind, size, frame rate, seconds
TITLE_CREDIT = "Made by the Factory"
TITLE_SECONDS = 6.0                     # an opening title or an end card
TITLE_MIN, TITLE_MARGIN = 5.0, 2.0      # words on screen: at least this, or the line's length plus this
TITLE_RISE = 0.7                        # seconds the words take to settle (the one entrance)
TITLE_EXIT = 0.5                        # seconds they take to fade at the very end (the one exit)
# which of the card renderer's grounds each kind of title sits on, unless the brand's settings say
# otherwise (visual.titles: {"opening": ..., "words": ..., "end_card": ...}, each one of kit.GROUNDS)
TITLE_GROUNDS = {"opening": "bold", "words": "main", "end_card": "bold"}


def _title_programs():
    """(node, hyperframes) from the Factory's own folder, or a VideoError saying how to install them."""
    from smf import media
    try:
        return media.node_programs()
    except RuntimeError as e:
        raise VideoError("%s. Nothing was changed." % str(e).rstrip("."))


def titles_available():
    """(ok, why): whether titles can be rendered on this computer. For tests and for status."""
    from smf import media
    try:
        media.node_programs()
    except RuntimeError as e:
        return False, str(e)
    return True, ""


def _hyperframes_render(project_dir, out_path, fps, quality):
    """Render one HyperFrames project (its index.html) to out_path with the Factory's own Node,
    HyperFrames and ffmpeg. Replaced by a stand-in in tests."""
    from smf import bootstrap
    node, hyperframes = _title_programs()
    ff, fp = programs()
    env = dict(os.environ, **bootstrap.HYPERFRAMES_ENV)
    env.update({"HYPERFRAMES_FFMPEG_PATH": ff, "HYPERFRAMES_FFPROBE_PATH": fp,
                "PATH": os.path.dirname(node) + os.pathsep + os.environ.get("PATH", "")})
    cmd = [node, hyperframes, "render", project_dir, "-o", out_path, "--fps", str(int(fps)), "--quiet"]
    if quality == "draft":
        cmd += ["--quality", "draft"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                           cwd=project_dir, timeout=1800)
    except OSError as e:
        raise VideoError("Could not start HyperFrames to render a title (%s). Nothing was added to the plan." % e)
    except subprocess.TimeoutExpired:
        raise VideoError("HyperFrames took more than half an hour on one title and was stopped. Nothing was added "
                         "to the plan.")
    if r.returncode != 0 or not os.path.isfile(out_path):
        said = [ln.strip() for ln in (r.stderr + "\n" + r.stdout).splitlines()
                if ln.strip() and "error" in ln.lower()][-2:]
        raise VideoError("HyperFrames could not render the title in %s. It said: %s. Nothing was added to the plan."
                         % (os.path.basename(project_dir), " / ".join(said) or "nothing"))


def _probe_size(path):
    """(width, height) of a video file, from the Factory's ffprobe."""
    _ff, fp = programs()
    r = run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
             path], "measure '%s'" % os.path.basename(path))
    try:
        w, h = r.stdout.strip().splitlines()[0].split(",")[:2]
        return int(w), int(h)
    except (ValueError, IndexError):
        raise VideoError("'%s' does not look like a video file." % os.path.basename(path))


def titles_dir(brand, film):
    return os.path.join(film_dir(brand, film), WORK_DIR, TITLES_DIR)


def wanted_titles(brand, plan, durations):
    """Every title this plan can carry, from words that already exist and nowhere else: the plan's
    title as an opening title, each line's "on_screen" words, and the brand's wordmark and handle
    as an end card. Each knows the line it belongs with and how long it should run."""
    visual = as_brand(brand).data.get("visual") or {}
    out = []
    title = str(plan.get("title") or "").strip()
    if title:
        out.append({"kind": "opening", "text": [title], "line": 1, "seconds": TITLE_SECONDS})
    for i, line in enumerate(plan["lines"]):
        words = line.get("on_screen") if isinstance(line, dict) else None
        if not isinstance(words, str) or not words.strip():
            continue
        span = durations[i] + (0.0 if _is_pause(line) else _gap(plan) + float(line.get("hold") or 0.0))
        seconds = round(max(TITLE_MIN, span + TITLE_MARGIN), 1)
        out.append({"kind": "words", "text": [ln.strip() for ln in words.strip().splitlines() if ln.strip()],
                    "line": i + 1, "seconds": seconds})
    wordmark = str(visual.get("wordmark") or "").strip()
    if wordmark:
        text = [wordmark] + ([str(visual["handle"]).strip()] if str(visual.get("handle") or "").strip() else [])
        out.append({"kind": "end_card", "text": text, "line": len(plan["lines"]), "seconds": TITLE_SECONDS})
    return out


def _title_key(title, size, fps, look):
    """Everything a rendered title depends on. A clip is reused only while all of it is the same, so
    a brand that changes a colour, a font or its logo gets its titles drawn again."""
    return {"kind": title["kind"], "text": list(title["text"]), "size": [int(size[0]), int(size[1])],
            "fps": int(fps), "seconds": float(title["seconds"]), "look": look}


def _title_look(kit, brand, kind, fonts, logo):
    pal = kit.palette(title_ground(brand, kind))
    return {"ground": title_ground(brand, kind), "colours": [pal["bg"], pal["head"], pal["accent"], pal["accent_small"]],
            "fonts": sorted(fonts), "logo": logo or ""}


def title_ground(brand, kind):
    """Which of the card renderer's grounds this kind of title sits on: the brand's own choice from
    its settings (visual.titles) when it made one, otherwise the Factory's default for that kind."""
    from smf.studio.render import kit as brand_kit
    chosen = ((as_brand(brand).data.get("visual") or {}).get("titles") or {})
    ground = chosen.get(kind) if isinstance(chosen, dict) else None
    return ground if ground in brand_kit.GROUNDS else TITLE_GROUNDS[kind]


def title_html(kit, title, size, fps, fonts, ground="main", logo=None):
    """One HyperFrames composition: a full-frame page on one of the brand's grounds, with the
    colours the card renderer would use on that ground (kit.palette), the words in the brand's
    display font, its accent as a short rule, its logo on the end card, one entrance (a short rise)
    and one exit (a fade over the last moments). `fonts` maps each face's file name to the name it
    was copied to beside the page; `logo` is the file name of the brand's logo copied beside it.
    Nothing moves between the entrance and the exit, so any moment in between can sit under any
    moment of the line."""
    import html as H
    w, h = int(size[0]), int(size[1])
    pal = kit.palette(ground)
    faces = "\n".join('@font-face{font-family:"%s";src:url("fonts/%s") format("%s");font-weight:%s;font-style:%s;'
                      'font-display:block;}' % (f.css_family, fonts[f.path.name],
                                                {".ttf": "truetype", ".otf": "opentype", ".woff2": "woff2",
                                                 ".woff": "woff"}[f.path.suffix.lower()], f.weight, f.style)
                      for f in kit.faces if f.path.name in fonts)
    short = min(w, h)
    big = {"opening": 0.085, "words": 0.075, "end_card": 0.095}[title["kind"]] * short
    small = 0.034 * short
    lines = title["text"]
    body = ""
    if title["kind"] == "end_card":
        if logo:
            body += '<img class="logo" src="%s" alt="">' % H.escape(logo, quote=True)
        body += '<div class="rule"></div><h1 class="words">%s</h1>' % H.escape(lines[0])
        if len(lines) > 1:
            body += '<p class="handle">%s</p>' % H.escape(lines[1])
    else:
        body = '<div class="rule"></div><h1 class="words">%s</h1>' % "<br>".join(H.escape(ln) for ln in lines)
    seconds = float(title["seconds"])
    exit_at = max(0.0, seconds - TITLE_EXIT)
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=%(w)d, height=%(h)d" />
<style>
%(faces)s
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:%(w)dpx;height:%(h)dpx;overflow:hidden;background:%(bg)s}
#root{width:100%%;height:100%%;position:relative;background:%(bg)s}
.scene{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
  text-align:center;padding:0 %(pad)dpx;gap:%(gap)dpx;animation:leave %(exit).2fs ease-in %(exit_at).3fs both}
.words{font-family:"smf-display",sans-serif;font-weight:700;font-size:%(big)dpx;line-height:1.08;
  letter-spacing:-0.015em;color:%(head)s;animation:rise %(rise).2fs cubic-bezier(.2,.7,.2,1) both;
  overflow-wrap:anywhere}
.handle{font-family:"smf-body",sans-serif;font-weight:500;font-size:%(small)dpx;color:%(accent_small)s;
  animation:rise %(rise).2fs cubic-bezier(.2,.7,.2,1) 0.25s both}
.rule{width:%(rule)dpx;height:%(thick)dpx;background:%(accent)s;transform-origin:left center;
  animation:grow %(rise).2fs cubic-bezier(.2,.7,.2,1) both}
.logo{height:%(logo)dpx;max-width:%(logo_w)dpx;object-fit:contain;animation:rise %(rise).2fs cubic-bezier(.2,.7,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(%(lift)dpx)}to{opacity:1;transform:none}}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes leave{from{opacity:1}to{opacity:0}}
</style>
</head>
<body>
<div id="root" data-composition-id="title" data-start="0" data-duration="%(seconds)s" data-width="%(w)d"
     data-height="%(h)d" data-no-timeline>
  <div class="scene" data-start="0" data-duration="%(seconds)s">
    %(body)s
  </div>
</div>
</body>
</html>
""" % {"w": w, "h": h, "faces": faces, "bg": pal["bg"], "head": pal["head"], "accent": pal["accent"],
       "accent_small": pal["accent_small"], "pad": int(0.08 * w), "gap": int(0.045 * short), "big": int(big),
       "small": int(small), "rise": TITLE_RISE, "exit": TITLE_EXIT, "exit_at": exit_at,
       "rule": int(0.09 * short), "thick": max(4, int(0.006 * short)), "lift": int(0.03 * short),
       "logo": int(0.14 * short), "logo_w": int(0.4 * w),
       "seconds": ("%.3f" % seconds).rstrip("0").rstrip("."), "body": body}


def _title_folders(folder):
    """{number: what that folder holds} for every title folder that has its words and its clip."""
    out = {}
    if not os.path.isdir(folder):
        return out
    for name in os.listdir(folder):
        if not name.isdigit():
            continue
        n = int(name)
        meta = os.path.join(folder, name, TITLE_FILE)
        clip = os.path.join(folder, name, "title-%d.mp4" % n)
        if os.path.isfile(meta) and os.path.isfile(clip):
            try:
                out[n] = read_json(meta, "The title %d" % n)
            except VideoError:
                continue
    return out


def _is_factory_title(src):
    return isinstance(src, dict) and src.get("credit") == TITLE_CREDIT


def titles(brand, film, say=print):
    """Make a motion-title clip for every piece of on-screen text the plan already carries, in the
    brand's colours and fonts, and add each to the plan as a source (title-<n>, credited to the
    Factory) suggested on its line. Never places a shot, never changes a line, never touches a
    source the Factory did not make. A title already made for the same words, size and frame rate
    is reused, not rendered again."""
    from smf.studio.render import kit as brand_kit
    brand = as_brand(brand)
    plan = load(brand, film)
    kit = brand_kit.resolve(brand)              # the brand's colours, wordmark, handle and fonts, or a plain refusal
    size, fps = _size(plan), _fps(plan)
    durations, _estimated = _durations(brand, film, plan)
    wanted = wanted_titles(brand, plan, durations)
    without = [i + 1 for i, ln in enumerate(plan["lines"])
               if isinstance(ln, dict) and not _is_pause(ln) and not str(ln.get("on_screen") or "").strip()]
    folder = titles_dir(brand, film)
    have = _title_folders(folder)
    sources = plan.setdefault("sources", {})
    if not isinstance(sources, dict):
        raise VideoError("The plan's \"sources\" is not a table of sources, so nothing can be added to it.")

    # what goes beside every page: the display and body faces, and the logo on the end card
    font_files = {}
    for face in kit.faces:
        if face.role in ("display", "body") and face.path.name not in font_files:
            font_files[face.path.name] = face.path
    logo_name = ("logo" + kit.logo.suffix.lower()) if kit.logo is not None else None

    plan_of = []                                # (title, number, reused)
    taken = set(have)
    for title in wanted:
        title["look"] = _title_look(kit, brand, title["kind"], font_files,
                                    logo_name if title["kind"] == "end_card" else None)
        key = _title_key(title, size, fps, title["look"])
        number = next((n for n, meta in sorted(have.items()) if meta == key and n not in {p[1] for p in plan_of}),
                      None)
        if number is None:
            number = 1
            while number in taken or (("title-%d" % number) in sources and not _is_factory_title(sources["title-%d" % number])):
                number += 1
            taken.add(number)
        plan_of.append((title, number, number in have))

    to_make = [(t, n) for t, n, reused in plan_of if not reused]
    if to_make:
        _title_programs()                   # the Factory's own Node and HyperFrames, or one sentence, before anything is written
    made, timings = [], {}
    quality = plan.get("quality") or "final"
    for title, n in to_make:
        project = os.path.join(folder, str(n))
        shutil.rmtree(project, ignore_errors=True)
        os.makedirs(os.path.join(project, "fonts"))
        fonts = {}
        for name, path in font_files.items():
            shutil.copyfile(str(path), os.path.join(project, "fonts", name))
            fonts[name] = name
        logo = title["look"]["logo"] or None
        if logo:
            shutil.copyfile(str(kit.logo), os.path.join(project, logo))
        write_text_atomic(os.path.join(project, "index.html"),
                          title_html(kit, title, size, fps, fonts, ground=title["look"]["ground"], logo=logo))
        clip = os.path.join(project, "title-%d.mp4" % n)
        say("Rendering title-%d (%s, %.1fs)..." % (n, _title_what(title), title["seconds"]))
        started = time.monotonic()
        _hyperframes_render(project, clip, fps, quality)
        timings[n] = round(time.monotonic() - started, 1)
        got = _probe_size(clip)
        length = probe_duration(clip)
        if tuple(got) != tuple(size) or abs(length - title["seconds"]) > 1.0 / fps + 0.05:
            os.remove(clip)
            raise VideoError("The title clip title-%d came out %dx%d and %.2fs, not the %dx%d and %.2fs the plan "
                             "needs, so it was not kept and nothing was added to the plan."
                             % (n, got[0], got[1], length, size[0], size[1], title["seconds"]))
        write_json_atomic(os.path.join(project, TITLE_FILE), _title_key(title, size, fps, title["look"]))
        made.append(n)

    # only now, with every clip there, is the plan touched: sources added, suggestions added, nothing else
    for title, n, _reused in plan_of:
        name = "title-%d" % n
        sources[name] = {"file": "/".join([WORK_DIR, TITLES_DIR, str(n), "%s.mp4" % name]), "fit": "fill",
                         "credit": TITLE_CREDIT, "shows": _title_what(title), "text": " / ".join(title["text"])}
        line = plan["lines"][title["line"] - 1]
        if isinstance(line, dict):
            suggested = line.get("suggested")
            if not isinstance(suggested, list):
                suggested = line["suggested"] = []
            if name not in suggested:
                suggested.append(name)
    write_json_atomic(os.path.join(film_dir(brand, film), PLAN_FILE), plan)
    return {"titles": [{"name": "title-%d" % n, "kind": t["kind"], "line": t["line"], "seconds": t["seconds"],
                        "text": t["text"], "reused": reused, "took": timings.get(n)} for t, n, reused in plan_of],
            "made": made, "without": without, "notes": list(kit.notes), "folder": folder}


def _title_what(title):
    return {"opening": "the opening title", "words": "the words on screen for line %d" % title["line"],
            "end_card": "the end card: the brand's wordmark and handle"}[title["kind"]]


# ----------------------------------------------------------------------------- rendering
def _colour(plan):
    c = str(plan.get("background") or "#000000").lstrip("#")
    return "0x" + (c if re.fullmatch(r"[0-9a-fA-F]{6}", c) else "000000")


def _picture_filter(plan, src, crop, speed=1.0):
    w, h = _size(plan)
    parts = ["crop=%s" % crop] if crop else []
    if (src.get("fit") or "fill") == "pad":
        parts.append("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:-1:-1:color=%s"
                     % (w, h, w, h, _colour(plan)))
    else:
        parts.append("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (w, h, w, h))
    if float(speed) != 1.0:
        parts.append("setpts=PTS/%.4f" % float(speed))      # frames are repeated, never invented
    parts.append("fps=%d,setsar=1,format=yuv420p" % _fps(plan))
    return ",".join(parts)


def _still_filter(plan, src, crop, move, frames):
    """A still image, framed like footage, then moved slowly: in, out, or a pan. It is framed larger
    than the film first so the move stays sharp, and zoompan makes exactly one frame per input frame
    (d=1): any other value multiplies the shot's length."""
    w, h = _size(plan)
    parts = ["crop=%s" % crop] if crop else []
    big_w, big_h = int(MOVE_OVERSCAN * w) // 2 * 2, int(MOVE_OVERSCAN * h) // 2 * 2
    if (src.get("fit") or "fill") == "pad":
        parts.append("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:-1:-1:color=%s"
                     % (big_w, big_h, big_w, big_h, _colour(plan)))
    else:
        parts.append("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (big_w, big_h, big_w, big_h))
    n = max(1, frames - 1)
    t = "(on/%d)" % n
    zin, zout, zhold = "1+%.3f*%s" % (MOVE_ZOOM, t), "%.3f-%.3f*%s" % (1 + MOVE_ZOOM, MOVE_ZOOM, t), "%.3f" % (1 + MOVE_ZOOM)
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    z, x, y = {"in": (zin, cx, cy), "out": (zout, cx, cy), "none": ("1", "0", "0"),
               "left": (zhold, "(iw-iw/zoom)*(1-%s)" % t, cy), "right": (zhold, "(iw-iw/zoom)*%s" % t, cy),
               "up": (zhold, cx, "(ih-ih/zoom)*(1-%s)" % t), "down": (zhold, cx, "(ih-ih/zoom)*%s" % t)}[move]
    parts.append("zoompan=z='%s':x='%s':y='%s':d=1:s=%dx%d:fps=%d" % (z, x, y, w, h, _fps(plan)))
    parts.append("setsar=1,format=yuv420p")
    return ",".join(parts)


def _encode_args(plan):
    preset, crf = QUALITY.get(plan.get("quality") or "final", QUALITY["final"])
    # capped threads: one x264 thread per core on a big machine, fed from 4K sources, can run a busy
    # computer out of memory, and the encoder then fails with nothing but "generic error"
    # a short lookahead keeps x264's buffered frames (and memory) small; quality at CRF 18 barely moves
    return ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-threads", str(THREADS),
            "-x264-params", "rc-lookahead=10", "-r", str(_fps(plan)), "-video_track_timescale", str(_fps(plan) * 1000)]


def _run_twice(cmd, what):
    """A shot that fails to encode is tried once more before the render stops: the usual cause is the
    computer running short of memory for a moment, not the shot."""
    try:
        return run(cmd, what)
    except VideoError:
        return run(cmd, what)


def _stream_seconds(path, kind):
    _ff, fp = programs()
    r = run([fp, "-v", "error", "-select_streams", kind, "-show_entries", "stream=duration", "-of", "csv=p=0", path],
            "measure the finished film")
    try:
        return float(r.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return probe_duration(path)


DRONE = ("0.30*sin(2*PI*55*t)+0.22*sin(2*PI*82.41*t)+0.14*sin(2*PI*110*t)"
         "+0.07*sin(2*PI*164.81*t)+0.045*sin(2*PI*220*t)+0.03*sin(2*PI*329.63*t)")


def render(brand, film, dry_run=False, say=print):
    """Check, then make the film, its contact sheet, its credits and a report. A plan with errors
    makes nothing."""
    brand = as_brand(brand)
    found = check(brand, film)
    if found["errors"]:
        e = VideoError("The plan has %d problem%s to fix before anything is made. Nothing was made."
                       % (len(found["errors"]), "" if len(found["errors"]) == 1 else "s"))
        e.findings = found["errors"]
        raise e
    plan, tl, sources = found["plan"], found["timeline"], found["sources"]
    if found["estimated"]:
        missing = [str(i + 1) for i in range(len(plan["lines"]))
                   if not _is_pause(plan["lines"][i]) and not os.path.isfile(_take(brand, film, plan, i))]
        raise VideoError("Line%s %s ha%s no voice yet. Make it first: factory.py montage voice --confirm."
                         % ("s" if len(missing) > 1 else "", ", ".join(missing), "ve" if len(missing) > 1 else "s"))
    fps = tl["fps"]
    for line in tl["lines"]:
        say("line %2d  %s  %s" % (line["number"], fmt_ts(line["start"]), line["say"][:70]))
    for k, s in enumerate(tl["shots"], 1):
        what = "end card" if s.get("card") else "%s @ %s" % (s["source"], fmt_ts(s["at"]))
        say("  shot %2d  %5.2fs  %s" % (k, s["frames"] / float(fps), what))
    if dry_run:
        return {"dry_run": True, "timeline": tl, "warnings": found["warnings"]}

    home = film_dir(brand, film)
    # render's own scratch, under .work: wiped before and after, but only this folder, because the
    # title clips (montage titles) live beside it and a render must never take them away
    work = os.path.join(home, WORK_DIR, "render")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    ff, _fp = programs()
    try:
        # ---- picture: one part per shot, each exactly its frames
        parts = []
        for k, s in enumerate(tl["shots"], 1):
            out = os.path.join(work, "v%03d.mp4" % k)
            if s.get("card"):
                w, h = _size(plan)
                cmd = [ff, "-y", "-v", "error", "-loop", "1", "-framerate", str(fps), "-i",
                       _find(brand, film, s["card"]), "-frames:v", str(s["frames"]), "-an", "-vf",
                       "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:-1:-1:color=%s,fps=%d,setsar=1,"
                       "format=yuv420p" % (w, h, w, h, _colour(plan), fps)]
            elif sources[s["source"]].get("image"):
                src = (plan.get("sources") or {})[s["source"]]
                cmd = [ff, "-y", "-v", "error", "-threads", str(THREADS), "-loop", "1", "-framerate", str(fps), "-i",
                       sources[s["source"]]["path"], "-frames:v", str(s["frames"]), "-an", "-vf",
                       _still_filter(plan, src, s.get("crop") or src.get("crop"), s.get("move") or src.get("move") or "in",
                                     s["frames"])]
            else:
                src = (plan.get("sources") or {})[s["source"]]
                cmd = [ff, "-y", "-v", "error", "-threads", str(THREADS), "-ss", "%.3f" % s["at"], "-i", sources[s["source"]]["path"],
                       "-frames:v", str(s["frames"]), "-an", "-vf",
                       _picture_filter(plan, src, s.get("crop") or src.get("crop"), s.get("speed", 1.0))]
            _run_twice(cmd + _encode_args(plan) + [out], "make shot %d" % k)
            got = probe_duration(out)
            if abs(got - s["frames"] / float(fps)) > 1.5 / fps:
                raise VideoError("Shot %d came out %.2fs long instead of %.2fs. Its source may end early or be damaged; "
                                 "nothing after it would line up, so the film was not finished."
                                 % (k, got, s["frames"] / float(fps)))
            parts.append(out)
        picture = os.path.join(work, "picture.mp4")
        join_parts(parts, picture, "join the shots")

        # ---- sound: silence, each line padded to exactly its frames, silence
        line_frames = {}
        for s in tl["shots"]:
            line_frames[s["line"]] = line_frames.get(s["line"], 0) + s["frames"]
        pieces = []

        def silence(seconds, name):
            p = os.path.join(work, name)
            run([ff, "-y", "-v", "error", "-f", "lavfi", "-t", "%.4f" % seconds, "-i",
                 "anullsrc=channel_layout=stereo:sample_rate=48000", "-c:a", "pcm_s16le", p], "make silence")
            return p

        if line_frames.get(0):
            pieces.append(silence(line_frames[0] / float(fps), "a000.wav"))
        for i, line in enumerate(plan["lines"]):
            seconds = line_frames.get(i + 1, 0) / float(fps)
            p = os.path.join(work, "a%03d.wav" % (i + 1))
            if _is_pause(line):
                pieces.append(silence(seconds, "a%03d.wav" % (i + 1)))
                continue
            if _voice_mode(plan) == "recording":
                rec = _find(brand, film, plan["voice"]["recording"])
                head = ["-ss", "%.3f" % float(line["from"]), "-t", "%.3f" % (float(line["to"]) - float(line["from"])),
                        "-i", rec]
            else:
                head = ["-i", _take(brand, film, plan, i)]
            run([ff, "-y", "-v", "error"] + head + ["-vn", "-af", "apad,atrim=0:%.4f" % seconds, "-ac", "2",
                                                   "-ar", "48000", "-c:a", "pcm_s16le", p], "prepare line %d" % (i + 1))
            pieces.append(p)
        if line_frames.get(None):
            pieces.append(silence(line_frames[None] / float(fps), "a999.wav"))
        voice = os.path.join(work, "voice.wav")
        listing = os.path.join(work, "voice.txt")
        with open(listing, "w", encoding="utf-8", newline="\n") as f:
            for p in pieces:
                f.write(concat_line(p))
        run([ff, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", voice], "join the voice")

        # ---- music under the voice, ducked while it speaks
        total = tl["frames"] / float(fps)
        music = plan.get("music") or {}
        level = str(music.get("level_db", -12)) + "dB"
        bed = None
        if music.get("file") or music.get("bed"):
            bed = os.path.join(work, "music.wav")
            fades = "afade=t=in:st=0:d=3,afade=t=out:st=%.3f:d=4,volume=%s" % (max(0.0, total - 4), level)
            if music.get("file"):
                track = _find(brand, film, music["file"])
                if not track:
                    raise VideoError("The music file '%s' is not there." % music["file"])
                cmd = [ff, "-y", "-v", "error", "-stream_loop", "-1", "-i", track, "-t", "%.3f" % total, "-af", fades]
            else:
                cmd = [ff, "-y", "-v", "error", "-f", "lavfi", "-i", "aevalsrc=%s:s=48000:d=%.3f" % (DRONE, total),
                       "-af", "lowpass=f=460,aecho=0.8:0.85:550|1150:0.32|0.20,tremolo=f=0.10:d=0.30," + fades]
            run(cmd + ["-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", bed], "make the music bed")

        film_path = os.path.join(home, FILM_FILE)
        working = os.path.join(home, "film.working.mp4")
        if bed:
            mix = ["-i", voice, "-i", bed, "-filter_complex",
                   "[2:a][1:a]sidechaincompress=threshold=0.05:ratio=5:attack=20:release=500[duck];"
                   "[1:a][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                   "alimiter=limit=0.95,loudnorm=I=-15:TP=-1.5:LRA=11[a]", "-map", "0:v", "-map", "[a]"]
        else:
            mix = ["-i", voice, "-filter_complex", "[1:a]alimiter=limit=0.95,loudnorm=I=-15:TP=-1.5:LRA=11[a]",
                   "-map", "0:v", "-map", "[a]"]
        run([ff, "-y", "-v", "error", "-i", picture] + mix +
            ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", "%.4f" % total,
             "-movflags", "+faststart", working], "put the picture and the sound together")
        replace_patiently(working, film_path)

        picture_seconds, sound_seconds = _stream_seconds(film_path, "v:0"), _stream_seconds(film_path, "a:0")
        if abs(picture_seconds - sound_seconds) > 2.0 / fps + 0.03:
            raise VideoError("The finished film's picture runs %.2fs and its sound %.2fs. They should match; the film "
                             "is saved but should not be used until this is found." % (picture_seconds, sound_seconds))

        # ---- look at the FINISHED film: one frame from the middle of every shot
        thumbs = []
        for k, s in enumerate(tl["shots"], 1):
            t = (s["start_frame"] + s["frames"] / 2.0) / fps
            p = os.path.join(work, "t%03d.png" % k)
            run([ff, "-y", "-v", "error", "-ss", "%.3f" % t, "-i", film_path, "-frames:v", "1", "-vf", "scale=320:-2", p],
                "take a frame for the contact sheet")
            thumbs.append(p)
        columns = min(6, len(thumbs))
        rows = (len(thumbs) + columns - 1) // columns
        run([ff, "-y", "-v", "error", "-framerate", "1", "-i", os.path.join(work, "t%03d.png"), "-vf",
             "tile=%dx%d:padding=4:color=white" % (columns, rows), "-frames:v", "1", "-q:v", "3",
             os.path.join(home, SHEET_FILE)], "make the contact sheet")

        # ---- credits and report
        used = []
        for s in tl["shots"]:
            if s.get("source") and s["source"] not in used:
                used.append(s["source"])
        lines = ["Credits for %s" % (plan.get("title") or film), ""]
        for alias in used:
            src = plan["sources"][alias]
            lines.append("%s: %s" % (alias, src.get("credit") or "(no credit given)"))
        write_text_atomic(os.path.join(home, CREDITS_FILE), "\n".join(lines) + "\n")
        report = {"film": FILM_FILE, "title": plan.get("title"), "timeline": tl, "warnings": found["warnings"],
                  "picture_seconds": round(picture_seconds, 3), "sound_seconds": round(sound_seconds, 3),
                  "dry_run": False}
        write_json_atomic(os.path.join(home, REPORT_FILE), report)
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            os.remove(os.path.join(home, "film.working.mp4"))       # only a finished film keeps the real name
        except OSError:
            pass
