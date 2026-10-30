"""describe.py - the words that go UNDER a video: a contract to write from, and a check afterwards.

"Description" here always means the text a platform shows beneath the video. The text drawn ON
the video (on-screen text, captions, the disclaimer) belongs to overlays.py.

CODE NEVER WRITES PROSE. `build_contract` gathers, for ONE clip, everything a writer may use:

    what is said       the clip's own words, word for word, from the recording's transcript
                       retimed to the clip (the finished clip is never listened to again)
    who says it        the person on camera, and the brand's voice in its own words
    each version       every version of the clip needs words of its own, per platform
    the platform       its mechanics from the playbooks, and the short-video guidance
    the ending         the brand's own offers and calls to action; never an invented one
    the facts          the brand's verified facts and research, plus the numbers said on camera
    the rules          the brand's style rules, its never-mention list, its regulated terms, and
                       the disclaimer a HOLD clip's words must carry

Claude writes from that page and saves the words in ONE file, the store
(`variants/descriptions.json`). `check_descriptions` then reads the store and gives every entry
the same verdict a written post gets (smf/studio/contract.py):

    passed       nothing to fix and nothing unconfirmed
    unverified   nothing provably wrong, but a sentence makes a claim whose key words are neither
                 in the clip nor in the brand's own files. A person decides
    blocked      must be fixed: a rule broken, a number from nowhere, words only the off-camera
                 voice said, a service the brand does not offer, a claim the brand never publishes,
                 a HOLD clip's words without the disclaimer, or words shared with another version

WHY EACH CHECK EXISTS
  numbers     a number under a video is a claim a viewer can check. It must trace to the brand's
              evidence, or be one the on-camera person says in this very clip.
  claims      finding each WORD somewhere proves nothing: any common word is somewhere. What is
              asked is whether a sentence's distinctive words are in the clip or the brand's files.
  speaker     an interviewer's question is not the guest's opinion. Words that only the off-camera
              voice said must not be put under the on-camera person's face.
  services    a description that offers something sends people to ask for it. It has to be
              something the brand really offers, in its settings.
  own words   the same words under two versions of a clip undo the point of making versions, and
              make them impossible to tell apart when results come in. Checked across the whole
              store at once, because two clips cut from the same passage attract the same words.

The text files beside each delivered video are written from the store at delivery time
(deliver.py). Nobody edits those; the store is the one place the words live.
"""
from __future__ import annotations

import json
import os
import re
import time

from smf import brands as B
from smf.studio import contract as post_contract
from smf.studio import cta as cta_mod
from smf.studio import dedup, grounding, platforms
from smf.studio.files import StudioError
from smf.studio.lint import PLATFORM_CHAR_LIMITS, Rules, lint_caption
from smf.video import gate
from smf.video import variants as V
from smf.video.common import (Transcript, VideoError, as_brand, locate, norm_token, read_json, write_json_atomic,
                              write_text_atomic)

STORE_FILE = "descriptions.json"
CHECK_FILE = "descriptions-check.json"
VIDEO_PLATFORMS = ("tiktok", "instagram", "facebook", "youtube", "linkedin")
ANY_PLATFORM = ""                      # words with no platform are used wherever nothing more exact exists
YOUTUBE_TITLE_LIMIT = 100
NEARBY_SECONDS = 45.0
SAME_WORDS_LIMIT = 0.5                 # share of three-word runs two descriptions may have in common
RUN_WORDS = 5
RUN_CONTENT_WORDS = 3
HARD_RULE = ("Use only what is in this contract. Never invent a fact, a number, a quote, a customer or a service. "
             "Say nothing the person on camera did not say or the brand has not written down. If something you "
             "want to say is not here, leave it out and say what was missing.")

_STOP = frozenset("""a about above after again against all also am an and any are aren't as at be because been
before being below between both but by can can't cannot come comes could did do does doing don't down during each
even ever every few for from further get gets getting go goes going got had has have having he her here hers him his
how i if in into is isn't it its it's itself just keep know let like look made make makes many may me more most much
must my need needs never no nor not now of off on once one only or other our ours out over own really same say says
see she should so some still such take than that that's the their them then there these they thing things this those
through to too under until up us very want was way we well were what when where which while who why will with won't
would you your yours yourself""".split())
_ASK = re.compile(r"^\s*(?:save|send|share|follow|watch|try|tell|comment|visit|come|ask|tag|read|listen|subscribe|"
                  r"book|join|order|message|dm|call|email|sign|tap|click|see|find|learn)\b", re.IGNORECASE)
_GENERIC_SERVICE = frozenset("""class classes course courses workshop workshops service services programme programmes
program programs package packages session sessions clinic clinics assessment assessments membership memberships
subscription subscriptions treatment treatments menu range box plan plans appointment appointments consultation
consultations call visit place spot seat""".split())
# Sentences that OFFER something. Kept narrow on purpose: "I run every morning" is not an offer,
# and a check that cries wolf gets ignored.
_OFFERING = re.compile(
    r"\bwe\s+(?:(?:also|now|even|still)\s+)?(?:offer|provide|run|sell|teach|host|hold|stock|deliver|serve)\s+"
    r"|\bi\s+(?:(?:also|now|even|still)\s+)?(?:offer|provide|sell|teach)\s+"
    r"|\b(?:book|join|order|buy|reserve)\s+(?=(?:a|an|our|my|the|your)\b)"
    r"|\b(?:sign\s+up\s+for|enrol(?:l)?\s+(?:in|on)|register\s+for)\s+", re.IGNORECASE)
_PHRASE_END = re.compile(r"\b(?:at|on|in|for|with|to|from|every|each|so|that|and|or|but|when|where|which|while|because|"
                         r"if|before|after|by|this|next)\b|[.,;:!?\n]", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_HASHTAGS = re.compile(r"(?:\s*#\w+)+\s*$")
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000}


class DescribeError(VideoError):
    """The descriptions could not be prepared or checked. Worded for the person."""


# ----------------------------------------------------------------------------- small text tools
def _squash(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower().replace("\u2019", "'").replace("'", "")).strip()


def stem(word):
    """A rough, SYMMETRIC stem: the same rule is applied to the description and to the sources, so
    'baked', 'bakes' and 'baking' meet at the same place. It does not have to be good English."""
    w = word.lower().replace("\u2019", "'")
    w = re.sub(r"'s$|'$", "", w).replace("'", "")
    for ending, put in (("ives", "if"), ("ves", "f"), ("ies", "y"), ("ingly", ""), ("edly", ""), ("ing", ""), ("ed", ""),
                        ("es", ""), ("ly", ""), ("s", "")):
        if w.endswith(ending) and len(w) - len(ending) >= 3:
            w = w[:len(w) - len(ending)] + put
            break
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiouls":
        w = w[:-1]
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


def key_terms(text):
    """The words of a passage that carry its meaning, stemmed, in order, without repeats."""
    out = []
    for raw in re.findall(r"[A-Za-z][A-Za-z'\u2019-]*", text or ""):
        for part in raw.split("-"):
            low = part.lower().replace("\u2019", "'")
            if len(low) < 4 or low in _STOP:
                continue
            s = stem(low)
            if len(s) >= 3 and s not in out:
                out.append(s)
    return out


def spoken_numbers(text):
    """Numbers that were SAID, as values: '90', 'ninety', 'two hundred and forty', '9 out of 10'.
    A speech tool writes them either way, so both are read."""
    values = {n["value"] for n in grounding.extract_numbers(text or "")}
    total = current = 0
    kind, running = "", False

    def flush():
        nonlocal total, current, kind, running
        if running:
            values.add(float(total + current))
        total, current, kind, running = 0, 0, "", False
    for tok in re.findall(r"[a-z]+|[,.;:!?]", (text or "").lower().replace("-", " ")):
        if tok in _UNITS:
            if kind == "unit":
                flush()                                          # "one two" is two numbers, not three
            current, kind, running = current + _UNITS[tok], "unit", True
        elif tok in _TENS:
            if kind in ("unit", "tens"):
                flush()
            current, kind, running = current + _TENS[tok], "tens", True
        elif tok == "hundred":
            current, kind, running = max(1, current) * 100, "scale", True
        elif tok in _SCALES:
            total, current, kind, running = total + max(1, current) * _SCALES[tok], 0, "scale", True
        elif tok == "and" and kind == "scale":
            continue
        else:
            flush()
    flush()
    return values


def sentences(text):
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


def own_words(text, leave_out=()):
    """A description without its hashtags and without the passages it HAS to carry (the disclaimer,
    the brand's own call to action). Those are the same everywhere by design and are neither claims
    to check nor words that make two versions alike."""
    body = _HASHTAGS.sub("", text or "")
    for passage in sorted((p for p in leave_out if p and p.strip()), key=len, reverse=True):
        body = re.sub(re.escape(passage.strip()), " ", body, flags=re.IGNORECASE)
    return body.strip()


def same_words(a, b):
    """Share of three-word runs two descriptions have in common (0..1); 1.0 when they are the same."""
    if _squash(a) == _squash(b):
        return 1.0 if _squash(a) else 0.0
    sa, sb = dedup.shingles(a, 3), dedup.shingles(b, 3)
    return len(sa & sb) / float(len(sa | sb)) if sa and sb else 0.0


# ----------------------------------------------------------------------------- what is known about a clip
def video_platforms(brand):
    """Where this brand posts video: its linked accounts on video platforms, in a stable order.
    With none linked yet, the three that every short-video plan starts from, so writing can begin."""
    linked = [t["platform"] for t in brand.targets() if t["platform"] in VIDEO_PLATFORMS]
    seen = [p for p in VIDEO_PLATFORMS if p in linked]
    return seen or ["tiktok", "instagram", "youtube"]


class ClipContext(object):
    """Everything the check needs to know about ONE clip, gathered once."""

    def __init__(self, brand, recording, manifest, clip, transcript, policy):
        offset = float(manifest.get("offset") or 0.0)
        entry = clip["report_entry"]
        words, self.kept_out = V.clip_words(entry, transcript, offset, policy)
        self.clip_id = clip["id"]
        self.said = " ".join(w["word"] for w in words)
        if not transcript.words:                                    # a subtitle transcript: whole sentences
            self.said = " ".join(
                seg["text"] for seg in transcript.segments
                if any(a <= (seg["start"] + seg["end"]) / 2.0 + offset < z for a, z in entry.get("pieces") or [])
                and (not policy.labelled or policy.may_publish(seg.get("speaker"))))
        self.on_camera = sorted({w["speaker"] for w in words if w.get("speaker")})
        self.word_level = transcript.word_level
        self.gate = clip["gate"]
        self.disclaimer = clip.get("disclaimer") or ""
        self.signed_off = clip.get("signed_off") or ""
        self.sign_off_by = clip.get("sign_off_by") or ""
        self.hook = str(entry.get("hook_text") or "")
        self.title = str(entry.get("title") or "")
        self.on_screen_text = clip.get("on_screen_text") or ""
        self.versions = [v["version"] for v in clip["versions"]]

        gated = policy.labelled and not policy.everyone_on_camera
        off = [w for w in transcript.words if gated and not policy.may_publish(w.get("speaker"))]
        pieces = entry.get("pieces") or []
        lo = min(p[0] for p in pieces) - offset - NEARBY_SECONDS if pieces else 0.0
        hi = max(p[1] for p in pieces) - offset + NEARBY_SECONDS if pieces else 0.0
        self.off_camera_names = sorted({w["speaker"] for w in off if w.get("speaker")})
        self.off_camera_nearby = " ".join(w["word"] for w in off if lo <= w["start"] <= hi)
        everyone_on = " ".join(w["word"] for w in transcript.words if not gated or policy.may_publish(w.get("speaker")))
        self.off_camera_runs = _runs_only_in(" ".join(w["word"] for w in off), everyone_on)


def _runs_only_in(theirs, ours):
    """Runs of RUN_WORDS words that one voice said and the other never did, each holding at least
    RUN_CONTENT_WORDS words that mean something. A shorter or emptier run ("is one of the") is
    ordinary English that any two people share, and would accuse everyone of everything."""
    ours_flat = " " + _squash(ours) + " "
    toks = _squash(theirs).split()
    out = set()
    for i in range(len(toks) - RUN_WORDS + 1):
        window = toks[i:i + RUN_WORDS]
        if sum(1 for t in window if t not in _STOP and len(t) > 2) < RUN_CONTENT_WORDS:
            continue
        run = " ".join(window)
        if " " + run + " " not in ours_flat:
            out.add(run)
    return out


def _brand_words(brand):
    """The brand's own description of itself: what it does, who it serves, its pillars, offers,
    people and phrases. Vocabulary a description may use without it being a new claim."""
    d = brand.data
    parts = [brand.name, (d.get("business") or {}).get("what_we_do", ""), (d.get("business") or {}).get("industry", ""),
             (d.get("business") or {}).get("location", ""), (d.get("audience") or {}).get("who", "")]
    audience = d.get("audience") or {}
    parts += list(audience.get("problems") or []) + list(audience.get("questions_they_ask") or [])
    parts += [str(p) if isinstance(p, str) else " ".join(str(v) for v in p.values()) if isinstance(p, dict) else ""
              for p in d.get("pillars") or []]
    for o in d.get("offers") or []:
        parts += [o.get("name", ""), o.get("what", ""), o.get("call_to_action", ""), o.get("guarantee", "")]
    for i in d.get("identities") or []:
        parts += [i.get("display_name", ""), i.get("role", ""), i.get("credential_line", "")]
    parts += list((d.get("voice") or {}).get("signature_phrases") or []) + list(d.get("own_brands") or [])
    return " ".join(str(p) for p in parts if p)


def _offer_words(brand):
    parts = [(brand.data.get("business") or {}).get("what_we_do", "")]
    for o in brand.data.get("offers") or []:
        parts += [o.get("name", ""), o.get("what", ""), o.get("call_to_action", "")]
    return " ".join(p for p in parts if p)


def _required_passages(brand, ctx):
    """Text a description is ALLOWED to repeat word for word: the disclaimer and the brand's own
    calls to action."""
    passages = [ctx.disclaimer]
    for o in brand.data.get("offers") or []:
        passages.append(o.get("call_to_action", ""))
    try:
        for c in cta_mod.load_library(brand).get("ctas", []):
            passages.append(c.get("text", ""))
    except StudioError:
        pass
    return [p for p in passages if p and p.strip()]


# ----------------------------------------------------------------------------- the store
def store_path(brand, recording):
    return V.variants_dir(brand, recording, STORE_FILE)


def load_store(brand, recording):
    path = store_path(brand, recording)
    if not os.path.isfile(path):
        return []
    data = read_json(path, "The descriptions file for '%s'" % recording)
    if isinstance(data, dict) and data.get("brand") not in (None, brand.id):
        raise DescribeError("The descriptions file in this folder belongs to '%s', not to %s. Nothing was read."
                            % (data.get("brand"), brand.name))
    rows = data.get("descriptions") if isinstance(data, dict) else data
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            out.append({"clip": str(row.get("clip") or "").strip(), "version": str(row.get("version") or "").strip().lower(),
                        "platform": str(row.get("platform") or "").strip().lower(), "text": str(row["text"]).strip()})
    return out


def save_store(brand, recording, rows):
    rows = sorted(rows, key=lambda r: (r["clip"], r["version"], r["platform"]))
    write_json_atomic(store_path(brand, recording), {"schema": 1, "brand": brand.id, "recording": recording,
                                                     "descriptions": rows})
    return len(rows)


# ----------------------------------------------------------------------------- the contract
class Contract(object):
    def __init__(self, data, markdown):
        self.data, self.markdown = data, markdown

    def __getitem__(self, key):
        return self.data[key]


def _name_parts(name):
    return {t for t in (norm_token(p) for p in re.split(r"[\s._-]+", name or "")) if t}


def _short_form_guidance():
    """The part of the short-video playbook about length, links, hashtags and calls to action."""
    path = os.path.join(B.ROOT, "playbooks", "short-form-video.md")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return ""
    m = re.search(r"^##\s+\d*\.?\s*Length, links, hashtags.*?$(.*?)(?=^##\s)", text,
                  re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    # That section also covers how long the VIDEO should be and what is drawn on it. Neither is
    # about the words underneath, so only the parts that are get passed on. If the playbook is ever
    # rearranged and none of them can be found, the whole section is better than nothing.
    parts = re.split(r"(?m)^(?=\*\*[^*\n]+\*\*)", m.group(1).strip())
    wanted = [p.strip() for p in parts if re.match(r"\*\*(?:Links|Hashtags|Calls to action)", p, re.IGNORECASE)]
    return "\n\n".join(wanted) if wanted else m.group(1).strip()


def _setup(brand, recording):
    brand = as_brand(brand)
    manifest = V.load_manifest(brand, recording)
    report, _folder, _kind = V.load_report(brand, recording, manifest.get("made_from") or "auto")
    transcript = Transcript.load(brand, recording)
    return brand, manifest, transcript, V.speaker_policy(brand, transcript, report)


def _clip_in(manifest, clip_id):
    for clip in manifest["clips"]:
        if clip["id"].upper() == str(clip_id or "").upper():
            return clip
    raise DescribeError("The plan has no clip called '%s'. It has: %s."
                        % (clip_id, ", ".join(c["id"] for c in manifest["clips"]) or "none"))


def build_contract(brand, recording, clip_id, only_platforms=None, today=None):
    """Everything a writer may use for ONE clip's descriptions. The versions must already be
    planned: words are written for versions that have names."""
    brand, manifest, transcript, policy = _setup(brand, recording)
    clip = _clip_in(manifest, clip_id)
    ctx = ClipContext(brand, recording, manifest, clip, transcript, policy)
    wanted = [p.lower() for p in (only_platforms or video_platforms(brand))]
    unknown = [p for p in wanted if p not in VIDEO_PLATFORMS]
    if unknown:
        raise DescribeError("Video descriptions are written for %s, not for %s."
                            % (", ".join(VIDEO_PLATFORMS), ", ".join(unknown)))

    warnings = []
    if not ctx.said:
        warnings.append("This clip's words could not be read from the transcript, so there is nothing to write from. "
                        "Do not write a description until the transcript is fixed.")
    if not ctx.word_level:
        warnings.append("The transcript has sentence times only, so the words below may run a little past the clip's "
                        "edges. Quote nothing from the first or last line without checking it against the video.")
    mechanics = {}
    try:
        book = platforms.load()
        if book.warning(today):
            warnings.append(book.warning(today))
        for p in wanted:
            mechanics[p] = book.mechanics_for(p)
    except StudioError as e:
        warnings.append(str(e))
        mechanics = {p: {"known": False, "max_len": PLATFORM_CHAR_LIMITS.get(p)} for p in wanted}

    who = None
    for ident in brand.data.get("identities", []):
        name = _name_parts(ident.get("display_name", ""))
        if name and any(name <= _name_parts(s) or _name_parts(s) <= name for s in ctx.on_camera if _name_parts(s)):
            who = ident
            break
    voice = post_contract.voice_for(brand, who["id"]) if who else post_contract.voice_for(brand, "")
    own, notes = post_contract.load_own_words(brand)
    warnings.extend(notes)
    evidence = grounding.facts_for_topic(brand, " ".join([ctx.title, ctx.hook, ctx.said]))
    warnings.extend(evidence["notes"])
    said_numbers = sorted(spoken_numbers(ctx.said))
    try:
        endings = [c for c in cta_mod.load_library(brand).get("ctas", []) if c.get("active", True)
                   and (c.get("kind") != "keyword" or c.get("ready"))]
    except StudioError:
        endings = []
    style = brand.style
    comp = brand.data.get("compliance") or {}
    posts_as = {}
    for t in brand.targets():
        if t["platform"] in wanted:
            posts_as.setdefault(t["platform"], []).append(t["identity"])

    data = {
        "brand": {"id": brand.id, "name": brand.name, "what_we_do": (brand.data.get("business") or {}).get("what_we_do", ""),
                  "regulated": (brand.data.get("business") or {}).get("regulated", "none")},
        "recording": recording,
        "clip": {"id": clip["id"], "title": ctx.title, "hook": ctx.hook, "on_screen_text": ctx.on_screen_text,
                 "said_word_for_word": ctx.said, "on_camera": ctx.on_camera, "kept_off_camera": ctx.off_camera_names,
                 "gate": ctx.gate, "disclaimer": ctx.disclaimer, "sign_off_by": ctx.sign_off_by,
                 "signed_off": ctx.signed_off},
        "speaker": {"identity": who["id"] if who else "", "display_name": who["display_name"] if who else "",
                    "role": (who or {}).get("role", ""), "voice": voice, "own_words": own},
        "versions": ctx.versions, "platforms": wanted, "posts_as": posts_as, "mechanics": mechanics,
        "short_video_guidance": _short_form_guidance(),
        "limits": {p: PLATFORM_CHAR_LIMITS.get(p) for p in wanted},
        "offers": [{k: o.get(k, "") for k in ("id", "name", "what", "call_to_action", "link")}
                   for o in brand.data.get("offers") or []],
        "endings": [{k: c.get(k, "") for k in ("id", "kind", "text", "link")} for c in endings],
        "facts": {"brand_facts": evidence["facts"], "research_stats": evidence["stats"],
                  "numbers_said_on_camera": said_numbers,
                  "none": not (evidence["facts"] or evidence["stats"])},
        "rules": {"no_long_dashes": bool(style["no_em_dashes"]),
                  "no_tags_on": [p for p in wanted if p in [x.lower() for x in style["no_tags_on"]]],
                  "banned_words": list(style["banned_words"]), "banned_phrases": list(style["banned_phrases"]),
                  "never_mention": list(brand.data.get("never_mention") or []),
                  "never_publish_terms": list(comp.get("drop_terms") or []),
                  "needs_sign_off_terms": list(comp.get("hold_terms") or [])},
        "save_to": locate(brand, store_path(brand, recording)),
        "hard_rule": HARD_RULE, "warnings": warnings,
    }
    return Contract(data, _markdown(data))


def _bullets(items, empty="- (nothing recorded)"):
    items = [str(i) for i in (items or []) if str(i).strip()]
    return ["- " + i for i in items] if items else [empty]


def _markdown(c):
    clip, sp, fx, ru = c["clip"], c["speaker"], c["facts"], c["rules"]
    out = ["# Write the words under clip %s for %s" % (clip["id"], c["brand"]["name"]), "",
           "**The rule above every other:** " + c["hard_rule"], ""]
    if c["warnings"]:
        out += ["## Before you start"] + _bullets(c["warnings"]) + [""]
    out += ["## 1. What is said in the clip, word for word",
            "Title in the cut list: %s" % (clip["title"] or "(none)"),
            "The line it opens on: \"%s\"" % clip["hook"] if clip["hook"] else "It has no separate opening line.",
            "On-screen text already drawn on the video: %s" % (clip["on_screen_text"] or "(none)"), "",
            "    " + (clip["said_word_for_word"] or "(no words could be read)"), "",
            "On camera: %s." % (", ".join(clip["on_camera"]) or "not labelled in the transcript")]
    if clip["kept_off_camera"]:
        out.append("Off camera, and NOT in the clip: %s. Nothing they said may be put under this video, even where it "
                   "prompted the answer you are describing." % ", ".join(clip["kept_off_camera"]))

    out += ["", "## 2. Who is speaking, and how they sound"]
    if sp["display_name"]:
        out.append("%s%s." % (sp["display_name"], ", " + sp["role"] if sp["role"] else ""))
    out.append("How the brand sounds: " + (sp["voice"]["register"] or "(not described yet)"))
    out += ["They do:"] + _bullets(sp["voice"]["do"]) + ["They do not:"] + _bullets(sp["voice"]["dont"])
    if c["posts_as"]:
        whose = "; ".join("%s = %s" % (p, ", ".join(i)) for p, i in sorted(c["posts_as"].items()))
        out.append("Whose account each platform is: " + whose + ". On the person's own account write as \"I\". "
                   "On the company's account write as \"we\" and name the person.")
    if sp["own_words"]:
        out += ["", "### Their own words",
                "Echo the rhythm and vocabulary. Take no facts from here unless they are also in section 5."]
        for chunk in sp["own_words"]:
            out += ["", "From %s%s:" % (chunk["file"], " (shortened)" if chunk["shortened"] else ""), "", chunk["text"]]
    else:
        out.append("There are no samples of their own writing yet. Write plainly, in the register above.")

    out += ["", "## 3. Every version needs words of its own",
            "Versions of this clip: %s. Platforms: %s." % (", ".join(c["versions"]), ", ".join(c["platforms"])),
            "Write one description for each version on each platform. No two versions may share their words: start "
            "from a different line of the clip, or take a different angle on it, each time. Varying the length from "
            "one version to the next is a good way to do it, and tells you later which length did better."]

    out += ["", "## 4. How each platform wants it"]
    for p in c["platforms"]:
        m = c["mechanics"].get(p) or {}
        out.append("### %s (hard limit %s characters)" % (p, c["limits"].get(p) or "unknown"))
        if p == "youtube":
            out.append("The FIRST LINE is the video's title: %d characters at most, the words people would search for. "
                       "Then a blank line, then the description." % YOUTUBE_TITLE_LIMIT)
        if m.get("known"):
            out += ["Opening line: " + str(m.get("opening_line_pattern") or ""),
                    "Hashtags: " + str(m.get("hashtag_policy") or ""),
                    "Asking for something: " + str(m.get("cta_policy") or "")]
        else:
            out.append("There is no rulebook page for this platform in the playbooks. Follow the short-video "
                       "guidance below.")
    if c["short_video_guidance"]:
        out += ["", "### Short video, on every platform", c["short_video_guidance"]]

    out += ["", "## 5. What you may state as fact"]
    if fx["none"]:
        out.append("The brand has no verified facts or research on file for this subject. State only what the person "
                   "says in the clip.")
    if fx["brand_facts"]:
        out += ["The brand's verified facts:"]
        out += ["- %s  (source: %s)" % (f["claim"], f["source"]) for f in fx["brand_facts"]]
    if fx["research_stats"]:
        out += ["Research the brand collected (credit the source when you use one):"]
        out += ["- %s  (source: %s)" % (s["finding"], s["source"]) for s in fx["research_stats"]]
    out.append("Numbers said on camera in this clip, which you may repeat as they were said: %s. Every other number "
               "will be caught." % (", ".join("%g" % n for n in fx["numbers_said_on_camera"]) or "none"))

    out += ["", "## 6. How it may end", "One ask at most. A save or a send does better than a pitch."]
    if c["endings"]:
        out += ["The brand's own calls to action (use the wording as it is, or none):"] + \
               ["- %s%s" % (e["text"], "  (" + e["link"] + ")" if e["link"] else "") for e in c["endings"] if e["text"]]
    if c["offers"]:
        out += ["What the brand offers. Name nothing else as something people can book, buy or join:"] + \
               ["- %s%s" % (o["name"], ": " + o["what"] if o["what"] else "") for o in c["offers"]]
    else:
        out.append("The brand has no offers on file, so do not offer anything. Ask for a save, a send or a follow.")

    out += ["", "## 7. The brand's rules (the checker enforces these)"]
    rules = []
    if ru["no_long_dashes"]:
        rules.append("No long dashes. Use a comma, a full stop or brackets.")
    if ru["no_tags_on"]:
        rules.append("No @mentions and no #hashtags on: %s." % ", ".join(ru["no_tags_on"]))
    if ru["banned_words"] or ru["banned_phrases"]:
        rules.append("Never use: " + ", ".join("\"%s\"" % w for w in ru["banned_words"] + ru["banned_phrases"]) + ".")
    if ru["never_mention"]:
        rules.append("Never name: %s." % ", ".join(ru["never_mention"]))
    if ru["never_publish_terms"]:
        rules.append("Claims that must never be published: %s." % ", ".join("\"%s\"" % t for t in ru["never_publish_terms"]))
    if c["brand"]["regulated"] not in ("", "none", None):
        rules.append("This is a regulated field (%s). Promise no outcomes and give no individual advice."
                     % c["brand"]["regulated"])
    if clip["gate"] == gate.HOLD:
        rules.append("This clip is on HOLD. EVERY description of it must carry the brand's disclaimer, word for word: "
                     "\"%s\"" % clip["disclaimer"])
        if not clip["signed_off"]:
            rules.append("It has not been signed off by %s yet, so it cannot be delivered. The words can still be "
                         "written and checked." % (clip["sign_off_by"] or "the person named in the brand's settings"))
    out += _bullets(rules)

    out += ["", "## 8. Where the words go", "Save them all in one file: `%s`, in this shape:" % c["save_to"], "",
            "    {\"descriptions\": [{\"clip\": \"%s\", \"version\": \"v1\", \"platform\": \"%s\", \"text\": \"...\"}]}"
            % (clip["id"], c["platforms"][0]), "",
            "Then check them. Fix anything blocked. For anything unverified, either point to where the claim comes "
            "from or take it out.", "- " + c["hard_rule"], ""]
    return "\n".join(str(line) for line in out)


def write_contract(brand, recording, clip_id, only_platforms=None):
    brand = as_brand(brand)
    contract = build_contract(brand, recording, clip_id, only_platforms)
    path = V.variants_dir(brand, recording, "contracts", "%s.md" % re.sub(r"[^A-Za-z0-9-]", "", contract["clip"]["id"]))
    write_text_atomic(path, contract.markdown)
    return contract, path


# ----------------------------------------------------------------------------- the check
def check_text(text, brand, platform, ctx, rules=None, gate_rules=None, passages=None, brand_stems=None, offer_stems=None):
    """The verdict for ONE description. `ctx` is the clip's ClipContext."""
    rules = rules or Rules.for_brand(brand)
    gate_rules = gate_rules or gate.GateRules.for_brand(brand)
    passages = _required_passages(brand, ctx) if passages is None else passages
    problems, unconfirmed, warnings = [], [], []
    platform = (platform or "").lower()

    # 1. the brand's copy rules and the platform's limits
    for f in lint_caption(text, platform or "instagram", rules):
        (problems if f.severity == "ERROR" else warnings).append(
            "Copy check: %s%s" % (f.detail, " (\"%s\")" % f.excerpt if f.excerpt else ""))
    for name in post_contract.other_brand_names(brand, text):
        problems.append("It names '%s', which is another brand set up on this computer." % name)
    if platform == "youtube":
        title = text.splitlines()[0].strip() if text.strip() else ""
        if len(title) > YOUTUBE_TITLE_LIMIT:
            problems.append("On YouTube the first line is the title, and it is %d characters. The limit is %d."
                            % (len(title), YOUTUBE_TITLE_LIMIT))
    for issue in cta_mod.check_cta(text, brand, platform)["issues"]:
        problems.append(issue)

    # 2. what the brand's gate says about these words
    verdict = gate.check(text, gate_rules)
    carries = bool(ctx.disclaimer) and _squash(ctx.disclaimer) in _squash(text)
    if verdict.status == gate.DROP:
        problems.append("It makes a claim %s never publishes: %s." % (brand.name, "; ".join(verdict.reasons)))
    elif verdict.status == gate.HOLD and not (ctx.gate == gate.HOLD and carries):
        problems.append("It says something that needs the brand's disclaimer and a sign-off (%s)%s"
                        % ("; ".join(verdict.reasons), ". This clip was cleared without one, so take it out."
                           if ctx.gate != gate.HOLD else "."))
    if ctx.gate == gate.HOLD and not carries:
        problems.append("This clip is on HOLD, so the words under it must carry the brand's disclaimer word for word: "
                        "\"%s\"" % ctx.disclaimer)

    body = own_words(text, passages)
    clip_stems = set(key_terms(" ".join([ctx.said, ctx.hook, ctx.title, ctx.on_screen_text])))
    brand_stems = brand_stems if brand_stems is not None else _known_stems(brand)
    nearby_off = set(key_terms(ctx.off_camera_nearby)) - clip_stems
    off_names = ", ".join(ctx.off_camera_names) or "the off-camera voice"

    # 3. numbers: the brand's evidence, or said on camera in this clip
    said = spoken_numbers(" ".join([ctx.said, ctx.on_screen_text])) | spoken_numbers(" ".join(passages))
    only_off = spoken_numbers(ctx.off_camera_nearby) - said
    ground = grounding.ground_draft(body, brand)
    for n in ground["numbers"]:
        if n["structural"] or n["grounded"] or n["value"] in said:
            continue
        if n["value"] in only_off:
            problems.append("The number %s was only said by %s, who is off camera. It cannot go under %s's video."
                            % (n["raw"], off_names, ", ".join(ctx.on_camera) or "this"))
        else:
            problems.append("The number %s is not said in the clip and does not trace to anything in %s's files. %s"
                            % (n["raw"], brand.name, grounding.HOW_TO_ADD_A_FACT))

    # 4. the speaker rule, run by run and then word by word
    flat = " " + _squash(body) + " "
    for run in sorted(ctx.off_camera_runs):
        if " " + run + " " in flat:
            problems.append("These words were only said by %s, who is off camera: \"%s\". A question is not the "
                            "answer; describe what the person on camera said." % (off_names, run))
            break

    # 5. claims, sentence by sentence
    for sentence in sentences(body):
        terms = key_terms(sentence)
        if len(terms) < 2 or _ASK.match(sentence):
            continue
        missing = [t for t in terms if t not in clip_stems and t not in brand_stems]
        theirs = [t for t in missing if t in nearby_off]
        if len(theirs) >= 2:
            problems.append("This sentence leans on words only %s said (off camera): \"%s\"." % (off_names, sentence[:120]))
        elif len(missing) >= 2 and len(missing) * 2 > len(terms):
            unconfirmed.append("\"%s\" says something that is neither in the clip nor in %s's own files (it turns "
                               "on: %s). Point to where it comes from, or take it out."
                               % (sentence[:120], brand.name, ", ".join(missing[:5])))

    # 6. services
    offer_stems = offer_stems if offer_stems is not None else set(key_terms(_offer_words(brand)))
    generic = {stem(w) for w in _GENERIC_SERVICE}
    for m in _OFFERING.finditer(body):
        rest = body[m.end():m.end() + 90]
        stop = _PHRASE_END.search(rest)
        phrase = rest[:stop.start()] if stop else rest
        named = key_terms(phrase)
        if not named:
            continue
        particular = [t for t in named if t not in generic]
        ok = all(t in offer_stems for t in particular) if particular else any(t in offer_stems for t in named)
        if not ok:
            have = ", ".join(o.get("name", "") for o in brand.data.get("offers") or [] if o.get("name")) or "none on file"
            problems.append("It offers \"%s\", which is not among %s's offers (%s). Add the offer to the brand's settings "
                            "if it is real, or take it out." % (phrase.strip()[:60], brand.name, have))
            break

    sourcing = "blocked" if problems else ("unverified" if unconfirmed else "passed")
    return {"sourcing": sourcing, "problems": problems, "unverified": unconfirmed, "warnings": warnings,
            "own_words": body}


def _known_stems(brand):
    facts, _notes = grounding.load_facts(brand)
    return set(key_terms(_brand_words(brand) + " " + " ".join(f["claim"] for f in facts)))


def check_descriptions(brand, recording, only=None, save=True):
    """Check every description in the store. Returns the report (and writes it beside the store).

    The comparison between descriptions runs over the WHOLE store at once, never clip by clip:
    two clips cut from the same passage attract the same words, and a check that only ever sees
    one clip cannot notice."""
    brand, manifest, transcript, policy = _setup(brand, recording)
    rows = load_store(brand, recording)
    if not rows:
        raise DescribeError("No descriptions have been written for '%s' yet, so there was nothing to check. That is "
                            "not a pass. Write them from the contract first." % recording)
    rules, gate_rules = Rules.for_brand(brand), gate.GateRules.for_brand(brand)
    brand_stems, offer_stems = _known_stems(brand), set(key_terms(_offer_words(brand)))
    contexts, results = {}, []
    wanted = {c.upper() for c in only} if only else None
    for row in rows:
        entry = dict(row, problems=[], unverified=[], warnings=[], own_words="")
        results.append(entry)
        try:
            clip = _clip_in(manifest, row["clip"])
        except DescribeError as e:
            entry["problems"].append(str(e))
            continue
        entry["clip"] = clip["id"]
        if row["version"] not in [v["version"] for v in clip["versions"]]:
            entry["problems"].append("Clip %s has no version called '%s'. It has: %s."
                                     % (clip["id"], row["version"], ", ".join(v["version"] for v in clip["versions"])))
            continue
        if row["platform"] not in VIDEO_PLATFORMS + (ANY_PLATFORM,):
            entry["problems"].append("'%s' is not a platform video descriptions are written for (%s)."
                                     % (row["platform"], ", ".join(VIDEO_PLATFORMS)))
            continue
        if clip["id"] not in contexts:
            contexts[clip["id"]] = ClipContext(brand, recording, manifest, clip, transcript, policy)
        ctx = contexts[clip["id"]]
        if not ctx.said:
            entry["unverified"].append("This clip's words could not be read from the transcript, so nothing in the "
                                       "description could be confirmed against it.")
        found = check_text(row["text"], brand, row["platform"], ctx, rules, gate_rules,
                           brand_stems=brand_stems, offer_stems=offer_stems)
        for k in ("problems", "unverified", "warnings"):
            entry[k] += found[k]
        entry["own_words"] = found["own_words"]

    for i, a in enumerate(results):                                  # every pair, across the whole store
        for b in results[i + 1:]:
            if not a["own_words"] or not b["own_words"]:
                continue
            same_clip = a["clip"] == b["clip"]
            if same_clip and a["version"] == b["version"]:
                continue                                           # one version's words for two platforms may be alike
            if not same_clip and a["platform"] and b["platform"] and a["platform"] != b["platform"]:
                continue                                           # two clips only collide on the same platform
            share = same_words(a["own_words"], b["own_words"])
            if share > SAME_WORDS_LIMIT:
                for mine, other in ((a, b), (b, a)):
                    mine["problems"].append(
                        "It shares its words with %s %s%s (%d%% the same). %s"
                        % (other["clip"], other["version"], " on " + other["platform"] if other["platform"] else "",
                           round(share * 100), "Every version of a clip needs words of its own."
                           if mine["clip"] == other["clip"] else
                           "Two clips from the same passage still need different words."))

    for entry in results:
        entry["sourcing"] = "blocked" if entry["problems"] else ("unverified" if entry["unverified"] else "passed")
        entry.pop("own_words")
    shown = [r for r in results if wanted is None or r["clip"].upper() in wanted]
    if not shown:
        raise DescribeError("No descriptions matched what was asked for, so nothing was checked. That is not a pass.")
    counts = {k: sum(1 for r in shown if r["sourcing"] == k) for k in ("passed", "unverified", "blocked")}
    missing = []
    for clip in manifest["clips"]:
        if wanted is not None and clip["id"].upper() not in wanted:
            continue
        for v in clip["versions"]:
            if not any(r["clip"] == clip["id"] and r["version"] == v["version"] for r in results):
                missing.append("%s %s" % (clip["id"], v["version"]))
    report = {"schema": 1, "brand": brand.id, "recording": recording, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "checked": len(shown), "counts": counts, "no_words_yet": missing, "descriptions": shown}
    if save:
        write_json_atomic(V.variants_dir(brand, recording, CHECK_FILE), report)
    return report


def verdicts(brand, recording):
    """{(clip, version, platform): entry} from a fresh check, or {} when nothing has been written."""
    try:
        report = check_descriptions(brand, recording, save=False)
    except DescribeError:
        return {}
    return {(r["clip"], r["version"], r["platform"]): r for r in report["descriptions"]}


def format_report(report):
    out = ["%d description(s) checked: %d passed, %d unverified, %d blocked."
           % (report["checked"], report["counts"]["passed"], report["counts"]["unverified"], report["counts"]["blocked"])]
    for r in report["descriptions"]:
        if r["sourcing"] == "passed" and not r["warnings"]:
            continue
        out.append("")
        out.append("%s %s%s: %s" % (r["clip"], r["version"], " on " + r["platform"] if r["platform"] else "", r["sourcing"]))
        out += ["  to fix: " + p for p in r["problems"]] + ["  unconfirmed: " + u for u in r["unverified"]]
        out += ["  worth a look: " + w for w in r["warnings"]]
    if report["no_words_yet"]:
        out += ["", "No words yet for: %s. A version with no words is left out when it is scheduled."
                % ", ".join(report["no_words_yet"])]
    return "\n".join(out)


def dumps(report):
    return json.dumps(report, indent=2, ensure_ascii=False)
