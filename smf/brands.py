"""brands.py - the brand is explicit, always.

A brand is a folder under Client/ that contains `brand-master.json`. Every tool in the Social Media Factory
takes a Brand (or a brand id) and there is NO default brand and NO fallback brand anywhere: an
unknown or missing brand is an error, because the alternative is one company's words going out
on another company's accounts.

Four kinds of brand data, four owners (only the first is handled here):
  A. stable settings     brand-master.json                 written by onboarding, validated here
  B. evidence + assets   Inputs/, Studio/registry.db, ...   added by the user over time
  C. per-job decisions   each job's own manifest
  D. production state    _state/                            written by the tools

`sync()` derives tool-specific settings files from A. It is atomic, stamps what it writes, and
refuses to overwrite a derived file that someone edited by hand.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_DIR = os.path.join(ROOT, "Client")
MASTER = "brand-master.json"
SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand.schema.json")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand_template")

BUCKETS = [
    "Brand/brand-kit/logos", "Brand/brand-kit/photos", "Brand/brand-kit/fonts",
    "Inputs/Recordings", "Inputs/Research", "Inputs/Questions", "Inputs/Proof", "Inputs/Edited", "Inputs/Footage",
    "Studio/exemplars", "Studio/runs",
    "Output/batches", "Output/visuals", "Output/ready-to-post", "Output/video",
    "Strategy", "_state",
]


class BrandError(Exception):
    """A problem with a brand, worded for the person, not the programmer."""


# ----------------------------------------------------------------------------- validation
def _type_ok(value, expected):
    return {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }.get(expected, True)


def _validate(value, schema, where, out):
    t = schema.get("type")
    if t and not _type_ok(value, t):
        out.append("%s should be %s" % (where or "the file", {"object": "a group of settings", "array": "a list",
                   "string": "text", "boolean": "true or false", "integer": "a whole number"}.get(t, t)))
        return
    if "enum" in schema and value not in schema["enum"]:
        out.append("%s must be one of: %s" % (where, ", ".join(str(e) for e in schema["enum"])))
    if isinstance(value, str):
        if len(value.strip()) < schema.get("minLength", 0):
            out.append("%s is empty or too short" % where)
        if schema.get("pattern") and value and not re.match(schema["pattern"], value):
            out.append("%s has an unexpected format (%s)" % (where, schema.get("about", schema["pattern"])))
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append("%s is below %s" % (where, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            out.append("%s is above %s" % (where, schema["maximum"]))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            out.append("%s needs at least %d" % (where, schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append("%s has more than %d" % (where, schema["maxItems"]))
        for i, item in enumerate(value):
            _validate(item, schema.get("items", {}), "%s[%d]" % (where, i + 1), out)
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value or value[req] in ("", None, [], {}):
                out.append("%s is missing" % ((where + "." if where else "") + req))
        for key, sub in schema.get("properties", {}).items():
            if key in value and value[key] not in (None,):
                _validate(value[key], sub, (where + "." if where else "") + key, out)


def _luminance(hex_colour):
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def mix(a, b, amount):
    """Blend colour a toward colour b by `amount` (0..1)."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("%02X" % int(round(x + (y - x) * amount)) for x, y in zip(pa, pb))


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# The people who inspire the owner (the influences question). Only ever the owner's own answers, so never
# "drafted" or "mixed". A plain name is fine too, for a list written by hand.
INFLUENCE_SOURCES = ("typed", "pasted", "spoken", "drafted-from-website", "quoted")


def _influence_problems(value):
    """The schema can't say "a name, or a name with why", so the influences list is checked here."""
    if value is None:
        return []
    if not isinstance(value, list):
        return ["influences should be a list"]
    out = []
    for i, item in enumerate(value, 1):
        where = "influences[%d]" % i
        if isinstance(item, str):
            if not item.strip():
                out.append("%s is empty" % where)
        elif isinstance(item, dict):
            if not (isinstance(item.get("name"), str) and item["name"].strip()):
                out.append("%s needs a name" % where)
            if "why" in item and not isinstance(item["why"], str):
                out.append("%s.why should be text" % where)
            if "source" in item and item["source"] not in INFLUENCE_SOURCES:
                out.append("%s is only ever the owner's own answer (source %s isn't allowed)" % (where, item["source"]))
        else:
            out.append("%s should be a name, or a name with why" % where)
    return out


def validate(data):
    """Returns (problems, warnings): plain sentences. No problems means the brand is usable."""
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = json.load(f)
    problems, warnings = [], []
    _validate(data, schema, "", problems)
    if problems:
        return problems, warnings

    ids = [i["id"] for i in data.get("identities", [])]
    if len(ids) != len(set(ids)):
        problems.append("two identities share the same id")
    for t in data.get("accounts", {}).get("targets", []):
        if t.get("identity") not in ids:
            problems.append("an account is linked to identity '%s', which this brand does not have" % t.get("identity"))
    for key in data.get("voice", {}).get("by_identity", {}):
        if key not in ids:
            problems.append("voice.by_identity mentions '%s', which is not one of this brand's identities" % key)
    own = {o.lower() for o in data.get("own_brands", [])} | {data.get("name", "").lower()}
    for n in data.get("never_mention", []):
        if n.lower() in own:
            problems.append("'%s' is on both the never-mention list and the own-brands list" % n)
    for text in _all_strings(data):
        if "TODO" in text:
            warnings.append("some answers are still placeholders (look for TODO)")
            break
    for offer in data.get("offers", []):
        if isinstance(offer, dict) and not (offer.get("link") or "").strip():
            warnings.append("the offer '%s' has no link yet, so a post about it has nowhere to send people"
                            % (offer.get("name") or offer.get("id") or "unnamed"))
    problems.extend(_offer_problems(data.get("offers", [])))
    problems.extend(_influence_problems(data.get("influences")))
    problems.extend(_platform_problems(data.get("intended_platforms") or {}, ids))
    colours = data.get("visual", {}).get("colors", {})
    if colours.get("ground") and colours.get("ink"):
        c = contrast(colours["ground"], colours["ink"])
        if c < 4.5:
            warnings.append("headline colour on the background is hard to read (contrast %.1f, aim for 4.5+)" % c)
    if colours.get("ground") and colours.get("accent"):
        if contrast(colours["ground"], colours["accent"]) < 1.6:
            warnings.append("the accent colour almost disappears against the background")
    return problems, warnings


# Card F4: one offer per rung of the ladder, and a "comment WORD" keyword is one word, at most 10
# capitals, and not a word people type anyway.
COMMON_WORDS = {"FREE", "YES", "NO", "OK", "INFO", "LINK", "DM", "HI", "HELLO", "THE", "AND", "NOW", "HERE",
                "ME", "YOU", "GO", "WANT", "SEND", "MORE", "PLEASE", "THANKS", "LOVE", "WOW", "NICE", "GREAT",
                "COOL", "IN", "ON"}
# An offer's call_to_action becomes a ready call to action in the writing tools (studio/cta.py), so it
# may never ask people to comment, message or reply with a word: that promise belongs to `keyword`,
# which is only used once `keyword_ready` is true.
# A keyword ask is a verb people do to a word: "Comment STARTER", "comment starter below", "DM me
# GUIDE", "message us GUIDE", "Reply X", "Send STARTER for the guide", "type the word STARTER". Ordinary
# next steps ("Book a Saturday class", "Message our UK office", "Comment below", "Send us an email",
# "Reply to this post") are not: the word after the verb must be followed by nothing, punctuation, or
# a small joining word, and it may not be one of the ordinary words below.
_ASK_VERB = r"(?:comment|reply|dm|text|send|type|message)"
_ASK_WORD = r"[\"'“‘]?([A-Za-z0-9]{1,15})[\"'”’]?"
KEYWORD_ASK = re.compile(r"(?i)\b%s\b(?:\s+(?:me|us|the\s+word|with))?\s+%s(?=\s*(?:$|[.!?,:;)]|\s+(?:and|for|to|"
                         r"below|here|now|in|on)\b))" % (_ASK_VERB, _ASK_WORD))
NOT_A_KEYWORD = {"below", "here", "now", "your", "a", "an", "the", "us", "me", "to", "this", "that", "it", "back",
                 "away", "today", "with", "on", "in", "for", "and", "or", "email", "message", "our", "my"}
PLATFORMS = ("linkedin", "instagram", "facebook", "tiktok", "youtube", "twitter")


def asks_for_keyword(text):
    """True when the text asks people to comment, message or reply with a word."""
    for m in KEYWORD_ASK.finditer(text or ""):
        if m.group(1).lower() not in NOT_A_KEYWORD:
            return True
    return False


def _offer_problems(offers):
    out, rungs = [], {}
    for offer in offers if isinstance(offers, list) else []:
        if not isinstance(offer, dict):
            continue
        name = offer.get("name") or offer.get("id") or "unnamed"
        rung = offer.get("rung")
        if isinstance(rung, str) and rung:
            if rung in rungs:
                out.append("two offers ('%s' and '%s') are both on the %s rung of the ladder; one offer per rung"
                           % (rungs[rung], name, rung))
            rungs[rung] = name
        keyword = offer.get("keyword")
        if isinstance(keyword, str) and keyword in COMMON_WORDS:
            out.append("the keyword '%s' for '%s' is a word people type anyway; pick one that's yours" % (keyword, name))
        cta = offer.get("call_to_action")
        if isinstance(cta, str) and asks_for_keyword(cta):
            out.append("the call to action for '%s' asks people to comment or message a keyword. Say the next step "
                       "instead (for example 'book on our website'); the keyword goes in its own field and is only "
                       "used once the reply is really set up" % name)
    return out


def _platform_problems(intended, ids):
    out = []
    by_speaker = intended.get("by_speaker") if isinstance(intended, dict) else None
    if not isinstance(by_speaker, dict):
        return out
    for speaker, platforms in by_speaker.items():
        if speaker not in ids:
            out.append("intended_platforms mentions '%s', which is not one of this brand's speakers" % speaker)
        if not isinstance(platforms, list):
            out.append("intended_platforms for %s should be a list of platforms" % speaker)
            continue
        for p in platforms:
            if p not in PLATFORMS:
                out.append("intended_platforms has '%s' for %s; the choices are %s (anything else goes under "
                           "'other')" % (p, speaker, ", ".join(PLATFORMS)))
    return out


# Card F8: what the brand stands for. Empty answers are named once, as a note; a brand is ready without them.
STRATEGY_PARTS = (
    ("known_for", "what people should think of first"), ("core_belief", "a core belief"),
    ("for", "what you're for"), ("against", "what you're against"),
    ("differentiation", "what you do differently"), ("non_negotiables", "non-negotiables"),
    ("story", "your story"), ("home_medium", "where you're most at home"), ("stage", "your audience size"),
)


def _answered(value):
    if isinstance(value, dict):
        return any(_answered(v) for k, v in value.items() if k not in ("id", "source"))
    if isinstance(value, list):
        return any(_answered(v) for v in value)
    return bool(str(value or "").strip())


def strategy_notes(data):
    """Plain notes about what the brand stands for and its goal: never problems."""
    notes = []
    positioning = data.get("positioning") or {}
    missing = [label for key, label in STRATEGY_PARTS if not _answered(positioning.get(key))]
    if missing:
        notes.append("what the brand stands for isn't complete yet (%s). The brand works without it; posts get more "
                     "distinctive with it" % ", ".join(missing))
    if not data.get("goal"):
        notes.append("what a win looks like isn't chosen yet: more people seeing it, more enquiries, or being the "
                     "trusted name")
    return notes


# The words people leave where an answer should be. Each is matched as a marker, not as ordinary
# prose: "Link to add" or "(to add)", never "ideas to add value"; "Not collected", never "have not
# collected their loaf".
PLACEHOLDER_MARKERS = (
    ("TODO", re.compile(r"\bTODO\b")),
    ("Link to add", re.compile(r"\blinks? to add\b", re.I)),
    ("to add", re.compile(r"\(\s*to add\s*\)|(?:^[\s>*|-]*|[:–—-]\s*)to add\s*[.)]?\s*$", re.I | re.M)),
    ("Not collected", re.compile(r"(?:^[\s>*|-]*|\(|:\s*)not collected\b", re.I | re.M)),
    ("placeholder", re.compile(r"\bplaceholder\b", re.I)),
)


def _markers_in(text):
    found = [label for label, pattern in PLACEHOLDER_MARKERS if pattern.search(text)]
    if "Link to add" in found and "to add" in found:
        found.remove("to add")                          # one placeholder, named once
    return found


def placeholder_notes(brand):
    """Plain notes naming every placeholder still left in a brand: in its settings (by setting) and
    in its brand files (by file, with line numbers). Notes only, never problems: a brand that works
    today keeps working. Reads files; never changes one."""
    notes = []
    for path, text in _strings_with_paths(brand.data, ""):
        found = _markers_in(text)
        if found:
            notes.append("the setting %s still says \"%s\"" % (path, found[0]))
    folder = brand.path("Brand")
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            full = os.path.join(folder, name)
            if not (name.endswith(".md") and os.path.isfile(full)):
                continue
            with open(full, "r", encoding="utf-8-sig", errors="replace") as f:
                lines = f.read().splitlines()
            hits = [(n, _markers_in(line)) for n, line in enumerate(lines, 1)]
            hits = [(n, found) for n, found in hits if found]
            if hits:
                words = sorted({w for _n, found in hits for w in found}, key=lambda w: [m[0] for m in PLACEHOLDER_MARKERS].index(w))
                where = ", ".join(str(n) for n, _found in hits[:6]) + (" and more" if len(hits) > 6 else "")
                notes.append("Brand/%s still has %d placeholder%s (\"%s\"; line%s %s)"
                             % (name, len(hits), "" if len(hits) == 1 else "s", "\", \"".join(words),
                                "" if len(hits) == 1 else "s", where))
    return notes


def _strings_with_paths(node, where):
    if isinstance(node, str):
        yield where, node
    elif isinstance(node, dict):
        for k, v in node.items():
            for item in _strings_with_paths(v, (where + "." if where else "") + str(k)):
                yield item
    elif isinstance(node, list):
        for i, v in enumerate(node, 1):
            for item in _strings_with_paths(v, "%s[%d]" % (where, i)):
                yield item


def _all_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            for s in _all_strings(v):
                yield s
    elif isinstance(node, list):
        for v in node:
            for s in _all_strings(v):
                yield s


# ----------------------------------------------------------------------------- the Brand object
class Brand(object):
    def __init__(self, brand_id, home, data):
        self.id = brand_id
        self.home = home
        self.data = data

    # paths -------------------------------------------------------------------------------
    def path(self, *parts):
        return os.path.join(self.home, *parts)

    @property
    def kit_dir(self):
        return self.path("Brand", "brand-kit")

    @property
    def state_dir(self):
        return self.path("_state")

    # settings ----------------------------------------------------------------------------
    @property
    def name(self):
        return self.data["name"]

    @property
    def identities(self):
        return [i["id"] for i in self.data["identities"]]

    def identity(self, identity_id):
        for i in self.data["identities"]:
            if i["id"] == identity_id:
                return i
        raise BrandError("%s has no identity called '%s' (it has: %s)"
                         % (self.name, identity_id, ", ".join(self.identities)))

    def targets(self, identity_id=None, connected_only=False):
        out = []
        for t in self.data.get("accounts", {}).get("targets", []):
            if identity_id and t["identity"] != identity_id:
                continue
            if connected_only and not t.get("connected"):
                continue
            out.append(t)
        return out

    def platforms_for(self, identity_id):
        """Platforms this identity posts on, in a stable order. Drives the drip rotation.
        With no accounts linked yet, a sensible default set so planning and writing still work."""
        self.identity(identity_id)
        seen = []
        for t in self.targets(identity_id):
            if t["platform"] not in seen:
                seen.append(t["platform"])
        return seen or ["linkedin", "instagram", "facebook"]

    def target(self, identity_id, platform):
        """Exact (identity, platform) account, or a BrandError. Never guesses, never falls back."""
        for t in self.targets(identity_id):
            if t["platform"] == platform:
                return t
        raise BrandError("%s has no %s account linked for '%s'. Link it in onboarding before posting there."
                         % (self.name, platform, identity_id))

    @property
    def timezone(self):
        return self.data.get("accounts", {}).get("timezone") or "America/New_York"

    @property
    def posting_windows(self):
        return self.data.get("accounts", {}).get("posting_windows") or ["06:30", "10:00", "12:00", "17:00", "18:00"]

    @property
    def style(self):
        s = {"no_em_dashes": True, "max_sentence_words": 22, "max_paragraph_words": 50,
             "max_paragraph_sentences": 3, "no_tags_on": ["facebook", "linkedin"],
             "banned_words": [], "banned_phrases": [], "plain_language_pack": True,
             "strict_craft_checks": False}
        s.update(self.data.get("style", {}))
        return s

    @property
    def colours(self):
        """All eight colour slots. A brand only has to choose three (background, headline,
        accent); the rest are mixed from those so the palette always belongs together."""
        c = dict(self.data["visual"]["colors"])
        c.setdefault("surface", mix(c["ground"], c["ink"], 0.05))
        c.setdefault("text", c["ink"])
        c.setdefault("muted", mix(c["ink"], c["ground"], 0.42))
        c.setdefault("rule", mix(c["ink"], c["ground"], 0.86))
        c.setdefault("accent2", c["accent"])
        return c


def _read_master(home):
    path = os.path.join(home, MASTER)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        raise BrandError("this folder has no brand settings file")
    except ValueError as e:
        raise BrandError("the brand settings file is damaged and cannot be read (%s). "
                         "Nothing was changed. Ask Claude to repair it." % e)


def list_brands():
    out = []
    if not os.path.isdir(CLIENT_DIR):
        return out
    for name in sorted(os.listdir(CLIENT_DIR)):
        if name.startswith("."):
            continue
        if os.path.isfile(os.path.join(CLIENT_DIR, name, MASTER)):
            out.append(name)
    return out


def load(brand_id, allow_invalid=False):
    """Load one brand by id. No default. Unknown id = BrandError listing what exists."""
    if not brand_id or not isinstance(brand_id, str):
        raise BrandError("no brand was named. Say which brand this is for. Brands here: %s"
                         % (", ".join(list_brands()) or "none yet"))
    home = os.path.join(CLIENT_DIR, brand_id)
    if not os.path.isfile(os.path.join(home, MASTER)):
        raise BrandError("there is no brand called '%s'. Brands here: %s"
                         % (brand_id, ", ".join(list_brands()) or "none yet"))
    data = _read_master(home)
    if data.get("id") != brand_id:
        raise BrandError("the folder is called '%s' but its settings say the brand id is '%s'. "
                         "They must match, so one brand can never be mistaken for another."
                         % (brand_id, data.get("id")))
    if not allow_invalid:
        problems, _ = validate(data)
        if problems:
            raise BrandError("%s is not ready to use yet:\n  - %s" % (brand_id, "\n  - ".join(problems)))
    return Brand(brand_id, home, data)


# ----------------------------------------------------------------------------- new brand
def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "brand"


# Windows refuses to swap a file in while another program has it open for a moment (antivirus
# scanning the new file, OneDrive or the search indexer reading the old one). It lets go within a
# second or two, so a refused swap is tried again after a short wait, about 3 seconds in all.
# Windows reports that as a permission error, so every permission error from the swap is retried;
# a place that truly can't be written to simply fails the same way after those 3 seconds.
SAVE_WAITS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.5)


def replace_patiently(src, dst):
    """Swap the finished file `src` onto `dst`, trying again after each of SAVE_WAITS while Windows
    refuses with a permission error. Every save in every area that swaps a finished temporary file
    onto its real name uses this. Still refused after about 3 seconds: that last error is raised."""
    for wait in SAVE_WAITS + (None,):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if wait is None:
                raise
            time.sleep(wait)


def _remove_quietly(tmp):
    """Remove a leftover temporary file. True if it is gone. Never raises: a failed cleanup must
    not hide the real problem from the person."""
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        return True
    except OSError:
        return False


def write_text_atomic(path, text, newline=None):
    """Save `text` so the file is always either the old version or the new one, never half of each.
    `newline` is passed to open(): None writes the computer's own line endings, "\\n" always \\n."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    told = False
    try:
        try:
            f = os.fdopen(fd, "w", encoding="utf-8", newline=newline)
        except BaseException:
            os.close(fd)                                # or Windows keeps the file open and can't remove it
            raise
        with f:
            f.write(text)
        if os.path.exists(path):
            # Keeps the old file's basic permission settings (on Windows only "read-only"; who may
            # read the file is not copied).
            shutil.copymode(path, tmp)
        try:
            replace_patiently(tmp, path)
        except PermissionError as e:
            told = not _remove_quietly(tmp)
            left = (" A temporary file (%s) was left beside it and can be deleted."
                    % os.path.basename(tmp)) if told else ""
            raise PermissionError(e.errno, "Could not save %s: another program on this computer "
                                  "(often antivirus, OneDrive or the search indexer) kept it locked, "
                                  "or this folder can't be written to. The old version is untouched. "
                                  "Wait a moment and try again.%s"
                                  % (os.path.basename(path), left), path) from e
    finally:
        # Whatever went wrong still reaches the person as it was; a leftover file is only mentioned.
        if not _remove_quietly(tmp) and not told:
            try:
                sys.stderr.write("Note: a temporary file (%s) was left beside %s and can be deleted.\n"
                                 % (os.path.basename(tmp), os.path.basename(path)))
            except Exception:
                pass                                    # the note is a courtesy; it must never replace the real error


def _write_json_atomic(path, data):
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def blank_master(brand_id, name):
    return {
        "schema_version": 1, "id": brand_id, "name": name,
        "business": {"what_we_do": "TODO: one or two sentences on what the business does and for whom",
                     "industry": "TODO", "location": "", "website": "", "regulated": "none"},
        "audience": {"who": "TODO: who you are trying to reach, in a sentence",
                     "problems": [], "questions_they_ask": [], "by_platform": {}},
        "pillars": [], "offers": [],
        "identities": [{"id": "company", "kind": "company", "display_name": name}],
        "voice": {"register": "TODO: how the brand sounds, in a sentence or two",
                  "do": [], "dont": [], "signature_phrases": [], "sources": ["Brand/voice-samples.md"],
                  "by_identity": {}},
        "style": {},
        "never_mention": [], "own_brands": [name],
        "compliance": {"pack": "generic", "drop_terms": [], "hold_terms": [], "disclaimer": "", "sign_off_by": ""},
        "visual": {"colors": {"ground": "#FFFFFF", "surface": "#F3F4F6", "ink": "#111827", "text": "#1F2937",
                              "muted": "#6B7280", "rule": "#E5E7EB", "accent": "#2563EB", "accent2": "#0F766E"},
                   "fonts": {"display": "Inter", "body": "Inter", "mono": "Geist Mono"},
                   "wordmark": name, "handle": "", "logo": "", "formats_enabled": []},
        "accounts": {"provider": "none", "timezone": "America/New_York",
                     "posting_windows": ["06:30", "10:00", "12:00", "17:00", "18:00"], "targets": []},
        "video": {"inbox_folder": "Inputs/Edited", "music_folder": "", "host_names": [], "allow_mirror": False},
        "wants": [],
    }


REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS proof (
    proof_id     TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,              -- result | testimonial | screenshot | photo | fact
    title        TEXT NOT NULL,
    detail       TEXT DEFAULT '',
    source       TEXT DEFAULT '',            -- where it came from: a file, a link, a date
    file_path    TEXT DEFAULT '',            -- relative to the brand folder
    may_publish  TEXT NOT NULL DEFAULT 'no', -- no | anonymised | yes
    names_third_party INTEGER NOT NULL DEFAULT 0,
    added_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts_written (
    post_id    TEXT PRIMARY KEY,
    topic_id   TEXT DEFAULT '',
    shape      TEXT DEFAULT '',
    platform   TEXT NOT NULL,
    identity   TEXT NOT NULL,
    text       TEXT NOT NULL,
    proof_ids  TEXT DEFAULT '[]',
    written_at TEXT NOT NULL,
    used_at    TEXT DEFAULT ''
);
"""


def create(brand_id, name, answers=None):
    """Create a complete, EMPTY brand: every folder, the settings file, and an empty proof
    library with its tables. A brand with no wins, no photos and no past posts is a normal brand."""
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,40}$", brand_id or ""):
        raise BrandError("a brand id is short and lowercase: letters, numbers and dashes (for example %s)"
                         % slugify(name or "my brand"))
    home = os.path.join(CLIENT_DIR, brand_id)
    if os.path.exists(os.path.join(home, MASTER)):
        raise BrandError("a brand called '%s' already exists. Nothing was changed." % brand_id)

    data = blank_master(brand_id, name)
    if answers:
        given = (answers.get("visual") or {}).get("colors")
        if given:
            # A brand that chose its own colours gets a palette mixed from THOSE, not the
            # placeholder greys, so three chosen colours are enough to look coherent.
            data["visual"]["colors"] = {}
        _deep_update(data, answers)
        data["id"], data["schema_version"] = brand_id, 1

    for bucket in BUCKETS:
        os.makedirs(os.path.join(home, *bucket.split("/")), exist_ok=True)
    if os.path.isdir(TEMPLATE_DIR):
        for root, _dirs, files in os.walk(TEMPLATE_DIR):
            rel = os.path.relpath(root, TEMPLATE_DIR)
            for fn in files:
                dst = os.path.join(home, "" if rel == "." else rel, fn)
                if not os.path.exists(dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(os.path.join(root, fn), "r", encoding="utf-8") as src:
                        text = src.read().replace("{{BRAND_NAME}}", name)
                    with open(dst, "w", encoding="utf-8") as out:
                        out.write(text)
    _write_json_atomic(os.path.join(home, MASTER), data)

    db = os.path.join(home, "Studio", "registry.db")
    con = sqlite3.connect(db)
    con.executescript(REGISTRY_SCHEMA)
    con.commit()
    con.close()
    return Brand(brand_id, home, data)


# Lists whose items have ids (onboarding v2, "Updates, removal and retry"). An update merges these by id:
# an item it names is edited in place (its id and place kept), a new id is added, and an item it leaves
# out stays. An item is removed only when the update says {"id": ..., "remove": true}: the person removed
# it and confirmed. Every other list is replaced, as before.
BY_ID_LISTS = {("identities",), ("offers",), ("audience", "objections"), ("positioning", "contrarian"), ("positioning", "for"),
               ("positioning", "against"), ("positioning", "differentiation"), ("positioning", "non_negotiables"),
               ("positioning", "story", "proof"), ("person", "stories"), ("proof_summary",), ("myths",),
               ("mistakes",), ("steps_to_result",), ("vocabulary",)}
NEVER_REMOVED_BY_UPDATE = {("identities",): "speaker", ("offers",): "offer"}


def _merge_by_id(old, new, path):
    out = copy.deepcopy(old) if isinstance(old, list) else []
    for item in new:
        if not isinstance(item, dict) or not item.get("id"):
            out.append(copy.deepcopy(item))                 # the brand check names an item with no id
            continue
        at = next((i for i, o in enumerate(out) if isinstance(o, dict) and o.get("id") == item["id"]), None)
        if item.get("remove") is True:
            if path in NEVER_REMOVED_BY_UPDATE:
                raise BrandError("That change was not saved: a %s is never removed by an update. Remove '%s' in "
                                 "the chat, where everything that uses it can be checked first."
                                 % (NEVER_REMOVED_BY_UPDATE[path], item["id"]))
            if at is not None:
                del out[at]
            continue
        fields = {k: v for k, v in item.items() if k != "remove"}
        if at is None:
            out.append({k: copy.deepcopy(v) for k, v in fields.items() if v is not None})
            continue
        for k, v in fields.items():
            if v is None:
                out[at].pop(k, None)                        # None clears that one field (a rung taken away)
            else:
                out[at][k] = copy.deepcopy(v)
    return out


def _deep_update(base, extra, by_id=False, path=()):
    """Merge `extra` into `base`. Values are COPIED, so the caller's answers and the brand's
    settings never share a list by accident. With `by_id`, the lists in BY_ID_LISTS merge by id."""
    for k, v in extra.items():
        here = path + (k,)
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v, by_id, here)
        elif by_id and here in BY_ID_LISTS and isinstance(v, list):
            base[k] = _merge_by_id(base.get(k), v, here)
        elif by_id and isinstance(v, dict) and base.get(k) is None:
            base[k] = {}
            _deep_update(base[k], v, by_id, here)           # a new group still drops "remove" items and None
        else:
            base[k] = copy.deepcopy(v)


def update(brand_id, answers):
    """Merge new answers into an existing brand's settings. Lists with ids merge by id (BY_ID_LISTS).
    Validates BEFORE writing: a change that would break the brand is refused and nothing on disk changes."""
    brand = load(brand_id, allow_invalid=True)
    data = copy.deepcopy(brand.data)
    given = (answers.get("visual") or {}).get("colors")
    if given and set(given) >= {"ground", "ink", "accent"}:
        data["visual"]["colors"] = {}
    _deep_update(data, answers, by_id=True)
    data["id"], data["schema_version"] = brand_id, 1
    problems, _warnings = validate(data)
    if problems:
        raise BrandError("That change was not saved because it would leave the brand unusable:\n  - "
                         + "\n  - ".join(problems))
    _write_json_atomic(os.path.join(brand.home, MASTER), data)
    return Brand(brand_id, brand.home, data)


# ----------------------------------------------------------------------------- sync (derive)
def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _ours(path):
    """(the file's settings, why not) for a file sync wants to replace.

    A file is the Social Media Factory's to replace ONLY when it can be read, holds a group of settings, and
    carries a stamp that still matches what is in it. Everything else is somebody's work: a file
    that will not parse cannot show a stamp, so it cannot clear that bar, and the old habit of
    reading a parse failure as "nothing there" is what let a mistyped hand edit be thrown away."""
    try:
        # Saving a file on Windows can put an invisible mark at the front. That is not damage.
        with open(path, "r", encoding="utf-8-sig") as f:
            old = json.load(f)
    except OSError:
        return None, "it could not be opened"
    except ValueError:
        return None, "it is not valid JSON any more, so something in it has been mistyped"
    if not isinstance(old, dict):
        return None, "it no longer holds a group of settings"
    stamp = old.pop("_derived", None)
    if not stamp or not isinstance(stamp, dict):
        return None, "the Social Media Factory did not write it, or its stamp has been removed"
    if stamp.get("content") != _sha(old):
        return None, "it has been edited by hand since the Social Media Factory wrote it"
    return old, ""


def _keep_a_copy(path):
    """Put the file that is about to be replaced beside itself, under a dated name. Returns that
    name. Nothing a person wrote is thrown away on their behalf, even when they asked for --force."""
    stem, ext = os.path.splitext(os.path.basename(path))
    name = "%s.before-sync-%s%s" % (stem, time.strftime("%Y-%m-%d-%H%M%S"), ext)
    beside = os.path.join(os.path.dirname(path), name)
    n = 2
    while os.path.exists(beside):                                  # two syncs in the same second
        beside = os.path.join(os.path.dirname(path), "%s.before-sync-%s-%d%s"
                              % (stem, time.strftime("%Y-%m-%d-%H%M%S"), n, ext))
        n += 1
    shutil.copyfile(path, beside)
    return os.path.basename(beside)


def _write_derived(path, payload, master_sha, force, report):
    """Write a derived JSON file with a stamp. Never replace a file the Social Media Factory cannot prove it
    wrote and nobody has touched since; with --force, keep what was there first."""
    try:
        rel = os.path.relpath(path, ROOT)
    except ValueError:                       # Windows: the brand folder is on a different drive
        rel = path
    if os.path.isfile(path):
        old, why = _ours(path)
        if why and not force:
            report["refused"].append(rel)
            report["notes"].append("%s was left as it is (%s): move what you want to keep into %s, or run sync "
                                   "again with --force to replace it." % (rel, why, MASTER))
            return
        if why:
            kept = _keep_a_copy(path)
            report["kept"].append(kept)
            report["notes"].append("%s was replaced; what was there before is kept beside it as %s." % (rel, kept))
        elif not force and _sha(old) == _sha(payload):
            report["unchanged"].append(rel)         # same content; leave the file (and its date) alone
            return
    out = dict(payload)
    out["_derived"] = {"from": MASTER, "master": master_sha, "content": _sha(payload),
                       "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "note": "Made by `factory.py sync-brand`. Edit brand-master.json instead; "
                               "a hand edit here blocks the next sync until you say which one wins."}
    _write_json_atomic(path, out)
    report["written"].append(rel)


# ----------------------------------------------------------------------------- the strategy file (F8)
# Brand/brand-strategy.md is made from `positioning` like the JSON files above, with the same rule: the
# Social Media Factory replaces it only while it can prove it wrote it and nobody has edited it since. Markdown has
# no room for a stamp field, so the stamp is the file's last line, an HTML comment people don't see.
TEXT_STAMP = re.compile(r"\n<!-- smf-derived (\{.*\}) -->\n?\Z")


def _text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _ours_text(path):
    """(the file's text without its stamp, why not): the text version of _ours()."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return None, "it could not be opened"
    m = TEXT_STAMP.search(text)
    if not m:
        return None, "the Social Media Factory did not write it, or its stamp has been removed"
    body = text[:m.start()]
    try:
        stamp = json.loads(m.group(1))
    except ValueError:
        return None, "its stamp has been changed"
    if not isinstance(stamp, dict):
        return None, "its stamp has been changed"
    if stamp.get("content") != _text_sha(body):
        return None, "it has been edited by hand since the Social Media Factory wrote it"
    return body, ""


def _write_derived_text(path, body, master_sha, force, report):
    try:
        rel = os.path.relpath(path, ROOT)
    except ValueError:
        rel = path
    if os.path.isfile(path):
        old, why = _ours_text(path)
        if why and not force:
            report["refused"].append(rel)
            report["notes"].append("%s was left as it is (%s): move what you want to keep into your brand's answers, "
                                   "or run sync again with --force to replace it." % (rel, why))
            return
        if why:
            kept = _keep_a_copy(path)
            report["kept"].append(kept)
            report["notes"].append("%s was replaced; what was there before is kept beside it as %s." % (rel, kept))
        elif not force and old == body:
            report["unchanged"].append(rel)
            return
    stamp = {"from": MASTER, "master": master_sha, "content": _text_sha(body),
             "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text_atomic(path, body + "\n<!-- smf-derived %s -->\n" % json.dumps(stamp, sort_keys=True), newline="\n")
    report["written"].append(rel)


def _val(item):
    if isinstance(item, dict):
        return (item.get("value") or item.get("text") or "").strip()
    return str(item or "").strip()


def strategy_markdown(name, positioning):
    """The readable brand-strategy file, made only from the brand's own confirmed answers."""
    p = positioning or {}
    out = ["# What %s stands for" % name, "",
           "_Made by `factory.py sync-brand` from your brand's answers. To change it, update your brand "
           "(\"update my brand\" in the chat), not this file._", ""]

    def section(title, lines):
        lines = [l for l in lines if l]
        if lines:
            out.extend(["## " + title, ""] + lines + [""])

    def bullets(items, with_experience=False):
        lines = []
        for it in items or []:
            text = _val(it)
            if not text:
                continue
            exp = (it.get("experience") or "").strip() if with_experience and isinstance(it, dict) else ""
            lines.append("- %s%s" % (text, " (from experience: %s)" % exp if exp else ""))
        return lines

    section("Known for", [_val(p.get("known_for"))])
    belief, why = _val(p.get("core_belief")), (p.get("core_belief") or {}).get("experience") if isinstance(
        p.get("core_belief"), dict) else ""
    section("Core belief", [belief, ("_From experience:_ " + why.strip()) if belief and (why or "").strip() else ""])
    section("Also believes, against the grain", bullets(p.get("contrarian"), True))
    section("Known as being for", bullets(p.get("for"), True))
    section("Known as being against", bullets(p.get("against"), True))
    rows = [r for r in p.get("differentiation") or [] if isinstance(r, dict) and (r.get("others") or r.get("us"))]
    if rows:
        section("What others do, and what we do instead",
                ["| Others in our space | What we do instead |", "|---|---|"]
                + ["| %s | %s |" % (r.get("others", "").replace("|", "/"), r.get("us", "").replace("|", "/"))
                   for r in rows])
    section("Every piece of content must show", bullets(p.get("non_negotiables")))
    story = p.get("story") or {}
    section("Our story", [("**What we saw that others didn't:** " + _val(story.get("catalyst"))) if _val(story.get("catalyst")) else "",
                          ("**What we believe:** " + _val(story.get("core_truth"))) if _val(story.get("core_truth")) else ""]
            + (["**How we've proved it:**"] + bullets(story.get("proof")) if bullets(story.get("proof")) else []))
    stage = {"under_100k": "under 100k followers", "100k_1m": "100k to 1 million", "1m_10m": "1 to 10 million",
             "10m_plus": "over 10 million"}.get(p.get("stage") or "", "")
    section("Where we're at home", [("Medium: " + p["home_medium"]) if p.get("home_medium") else "",
                                    ("Audience size: " + stage) if stage else ""])
    journey = p.get("journey") or {}
    section("The brand journey", ["- **%s** %s" % (label, journey[key].strip()) for key, label in
                                  (("want", "What we want to happen:"), ("known_for", "What we must be known for:"),
                                   ("do", "What we must do:"), ("learn", "What we must learn:"))
                                  if (journey.get(key) or "").strip()])
    formats = p.get("formats") or {}
    section("Signature formats", ["- Repeatable: %s" % f for f in formats.get("repeatable") or [] if f]
            + (["- One we enjoy: %s" % formats["enjoyable"]] if formats.get("enjoyable") else []))
    section("Topics next to ours", ["- %s" % t for t in p.get("adjacent_topics") or [] if t])
    section("What people compliment us on", ["- %s" % t for t in p.get("compliments") or [] if t])
    world = p.get("world") or {}
    section("Our world", ["- %s: %s" % (label, ", ".join(world.get(key) or [])) for key, label in
                          (("people", "People who keep coming up"), ("places", "Places"), ("interests", "Interests"))
                          if world.get(key)] + (["- The enemy: %s" % world["enemy"]] if world.get("enemy") else []))
    return "\n".join(out).rstrip() + "\n"


def sync(brand, force=False):
    """Derive tool-specific SETTINGS files from brand-master.json. Evidence, per-job decisions
    and state are never touched. Returns {"written", "unchanged", "refused", "kept", "notes"}:
    `refused` and `kept` are file names, `notes` the sentences to show the person."""
    report = {"written": [], "unchanged": [], "refused": [], "kept": [], "notes": []}
    master_sha = _sha(brand.data)
    c = brand.colours
    visual = brand.data["visual"]

    # brand kit: colours under their neutral names, plus the legacy slot names the renderers
    # grew up with, so old and new code read the same file.
    tokens = dict(c)
    tokens.update({"paper": c["ground"], "sand": c["surface"], "espresso": c["ink"], "ink_body": c["text"],
                   "marigold": c["accent"], "cobalt": c["accent2"]})
    _write_derived(os.path.join(brand.kit_dir, "tokens.json"), tokens, master_sha, force, report)
    _write_derived(os.path.join(brand.kit_dir, "brand.json"),
                   {"wordmark": visual["wordmark"], "handle": visual.get("handle", ""),
                    "fonts": visual.get("fonts", {}), "logo": visual.get("logo", "")},
                   master_sha, force, report)

    # writing + lint rules
    _write_derived(brand.path("Studio", "rules.json"),
                   {"style": brand.style, "never_mention": brand.data.get("never_mention", []),
                    "own_brands": brand.data.get("own_brands", []),
                    "compliance": brand.data.get("compliance", {})},
                   master_sha, force, report)

    # who speaks where
    _write_derived(brand.path("Studio", "accounts.json"),
                   {"provider": brand.data.get("accounts", {}).get("provider", "none"),
                    "timezone": brand.timezone, "posting_windows": brand.posting_windows,
                    "identities": brand.data["identities"],
                    "targets": brand.targets()},
                   master_sha, force, report)

    # what the brand stands for (F8): only when there is something to show
    strategy = brand.path("Brand", "brand-strategy.md")
    if _answered(brand.data.get("positioning")):
        _write_derived_text(strategy, strategy_markdown(brand.name, brand.data["positioning"]), master_sha, force, report)
    elif os.path.isfile(strategy):
        _remove_derived_text(strategy, force, report)
    return report


def _remove_derived_text(path, force, report):
    """Every strategy answer was cleared: remove the file the Social Media Factory made, so old beliefs don't linger.
    A hand-edited file stays (or, with --force, is kept beside itself first)."""
    try:
        rel = os.path.relpath(path, ROOT)
    except ValueError:
        rel = path
    _old, why = _ours_text(path)
    if why and not force:
        report["refused"].append(rel)
        report["notes"].append("%s was left as it is (%s), although every answer it was made from has been cleared. "
                               "Delete it yourself, or run sync again with --force." % (rel, why))
        return
    if why:
        kept = _keep_a_copy(path)
        report["kept"].append(kept)
        report["notes"].append("%s was removed; what was there is kept beside it as %s." % (rel, kept))
    os.remove(path)
    report["written"].append(rel)


# ----------------------------------------------------------------------------- verbs
def cli_new(args):
    import argparse
    ap = argparse.ArgumentParser(prog="factory.py new-brand")
    ap.add_argument("--name", required=True)
    ap.add_argument("--id")
    ap.add_argument("--answers", help="a JSON file of answers collected during onboarding")
    a = ap.parse_args(args)
    answers = None
    if a.answers:
        with open(a.answers, "r", encoding="utf-8-sig") as f:
            answers = json.load(f)
    try:
        brand = create(a.id or slugify(a.name), a.name, answers)
    except BrandError as e:
        print(str(e))
        return 1
    problems, warnings = validate(brand.data)
    sync(brand)
    print("Created the brand '%s' (id: %s)." % (brand.name, brand.id))
    for w in problems + warnings:
        print("  still needed: " + w)
    return 0


def cli_update(args):
    import argparse
    ap = argparse.ArgumentParser(prog="factory.py update-brand")
    ap.add_argument("--brand", required=True)
    ap.add_argument("--answers", required=True, help="a JSON file holding only the settings that changed")
    a = ap.parse_args(args)
    try:
        with open(a.answers, "r", encoding="utf-8-sig") as f:
            answers = json.load(f)
        brand = update(a.brand, answers)
    except (BrandError, OSError, ValueError) as e:
        print(str(e))
        return 1
    rep = sync(brand)
    _problems, warnings = validate(brand.data)
    print("Saved. %d settings file(s) refreshed." % len(rep["written"]))
    for note in rep["notes"]:
        print("  " + note)
    for w in warnings:
        print("  still needed: " + w)
    return 0


CHECK_USAGE = """
python factory.py check-brand <id>       is this brand's settings file complete and sane
python factory.py check-brand <id> <id>  several brands
python factory.py check-brand            every brand on this computer (it only reads)
"""


def cli_check(args):
    from smf import bootstrap
    _opts, words, rc = bootstrap.read_options(args, "check-brand", CHECK_USAGE, words=True)
    if rc is not None:
        return rc
    ids = words or list_brands()
    if not ids:
        print("No brands yet. Ask Claude to onboard one.")
        return 0
    bad = 0
    for bid in ids:
        try:
            b = load(bid, allow_invalid=True)
        except BrandError as e:
            print("%s: %s" % (bid, e))
            bad += 1
            continue
        problems, warnings = validate(b.data)
        notes = warnings + placeholder_notes(b) + strategy_notes(b.data)
        state = "not ready" if problems else ("ready, with %d thing%s still to fill in" % (
            len(notes), "" if len(notes) == 1 else "s") if notes else "ready")
        print("%s (%s): %s" % (b.name, b.id, state))
        for p in problems:
            print("  - " + p)
        for w in notes:
            print("  - note: " + w)
        bad += 1 if problems else 0
    return 1 if bad else 0


SYNC_USAGE = """
python factory.py sync-brand <id>          remake this brand's tool settings from its brand-master.json
python factory.py sync-brand --brand <id>  the same
python factory.py sync-brand <id> <id>     several brands
python factory.py sync-brand --all         every brand on this computer
  --force   replace a settings file even if it was edited by hand (a copy of the old one is kept)
A brand must be named, or --all given: nothing is updated by default.
"""


def cli_sync(args):
    from smf import bootstrap
    opts, ids, rc = bootstrap.read_options(args, "sync-brand", SYNC_USAGE, flags=("--force", "--all"),
                                           values=("--brand",), words=True)
    if rc is not None:
        return rc
    if opts.get("--brand"):
        other = [b for b in ids if b != opts["--brand"]]
        if other:
            print("Two different brands were named (%s and %s). Name one, or list several without --brand."
                  % (other[0], opts["--brand"]))
            return 2
        ids = [opts["--brand"]]
    if opts.get("--all"):
        if ids:
            print("Name brands or use --all, not both.")
            return 2
        ids = list_brands()
        if not ids:
            print("No brands yet. Ask Claude to onboard one.")
            return 0
    elif not ids:
        found = list_brands()
        print("Which brand? Name it, for example: python factory.py sync-brand %s" % (found[0] if found else "<id>"))
        if found:
            print("Brands on this computer: %s. Or use --all for every brand." % ", ".join(found))
        return 2
    ids = list(dict.fromkeys(ids))
    force = bool(opts.get("--force"))
    rc = 0
    for bid in ids:
        try:
            rep = sync(load(bid), force=force)
        except BrandError as e:
            print(str(e))
            rc = 1
            continue
        print("%s: %d updated, %d already current" % (bid, len(rep["written"]), len(rep["unchanged"])))
        for note in rep["notes"]:
            print("  " + note)
        rc = 1 if rep["refused"] else rc          # nothing was lost, but the sync is not finished
    return rc
