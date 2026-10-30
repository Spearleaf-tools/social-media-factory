"""session.py - the two files the onboarding page and the agent share.

    .factory/tmp/onboarding-page.json               the session: address, private code, hand-off times, result
    .factory/tmp/onboarding-intake-<time>.json      the answers file (shape: intake.schema.json)

Each file has one writer, so the two sides never overwrite each other:

    the answers file   only the page server writes it (every confirmed answer, then Finish)
    the session file   the page server writes it once at start; after that only the `onboard-page`
                       command writes it: --wait (picked up), --result (the brand is built), --stop

The life of a session, as `onboard-page --status` reports it:

    in progress   the page is open and the person is answering
    complete      they clicked Finish (or Finish in chat); the answers are ready for the agent
    finished      the agent handed the page its result
    stopped       the page server is no longer running
"""
from __future__ import annotations

import difflib
import json
import os
import re
import secrets
import socket
import tempfile
import time
from datetime import datetime, timezone

from smf import bootstrap, brands
from smf.onboarding_page import secrets_check

ROOT = bootstrap.ROOT
SESSION_NAME = "onboarding-page.json"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intake.schema.json")

# The core (spec rev 10, fields 1-31), in the page's order, then the optional deeper answers. The first eight
# are version 1's answers, unchanged.
CORE_KEYS = ("name", "what_you_do", "audience", "identities", "voice_samples", "colours", "rules", "make",
             "why_started", "voice", "positioning", "teach", "ladder", "goal", "platforms", "capacity", "show")
# Rev 12 (spec "Next phase"): the first screen, the starter pack, ideas and suggestions waiting for the owner,
# how people find you, filming, fonts, and where each field's words came from. None is counted in the 31.
EXTRA_KEYS = ("business_start", "starter_pack", "topic_ideas", "platform_candidates", "acquisition", "filming",
              "fonts", "provenance", "inventory", "influences")
ANSWER_KEYS = CORE_KEYS + ("deep",) + EXTRA_KEYS
# Words a starter pack or Claude (from the owner's short description) suggested, rather than the owner's own.
GENERATED_ORIGINS = ("starter-pack", "description")
# The only page fields such words may fill (N3's allowlist), plus the look, which is only ever suggested.
GENERATED_FIELDS = ("audience_who", "audience_way", "myths", "mistakes", "rules", "goal_platforms", "colours")
GENERATED_KEYS = ("rules", "colours", "platform_candidates", "topic_ideas", "starter_pack", "fonts")
BASICS = CORE_KEYS[:8]          # what today's page asks (questions.json); the v2 page designs ask the rest
GROUP_KEYS = ("positioning", "teach", "deep")       # headings: each part inside is confirmed or skipped on its own
# F8 B, D and E: only ever the person's own words. Since rev 13 (M6) that includes their own writing, quoted:
# a draft here must be a labelled quote from their book, documents or website, said by them, with its page.
NEVER_DRAFTED = ("core_belief", "contrarian", "differentiation", "non_negotiables")
# Who inspires them: only ever the owner's own answers too, or quotes of their own writing (influences spec).
NEVER_DRAFTED_KEYS = ("influences",)
# The parts of an answer or row a quote can fill.
QUOTE_PARTS = ("value", "others", "us", "name", "why")
QUOTE_GENERATORS = {"document": "claude-from-document", "website": "claude-from-website"}
QUOTE_SPEAKERS = ("owner", "brand")
COVERAGE = ("found", "partly", "missing", "your words needed")
NEVER_DRAFTED_WORDS = {"core_belief": "what you believe that most in your industry don't",
                       "contrarian": "your other beliefs against the grain",
                       "differentiation": "what others do and what you do instead",
                       "non_negotiables": "what every piece of your content must show"}
LIST_KEYS = ("identities", "voice_samples")
STATUSES = ("confirmed", "skipped", "unconfirmed", "for_chat")

WAIT_LIMIT = 540            # seconds: about 9 minutes, under every agent's command time limit
PICKUP_BACKSTOP = 60        # seconds after Finish with no agent: tell the person to go back to the chat
BUILD_TIMEOUT = 600         # seconds after pick-up with no result: the "having trouble" recovery screen


class SessionError(Exception):
    """A problem with the onboarding page, worded for the person, not the programmer."""


# ----------------------------------------------------------------------------- files
def tmp_dir():
    return os.path.join(ROOT, ".factory", "tmp")


def session_path():
    return os.path.join(tmp_dir(), SESSION_NAME)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path, data, tries=8):
    """Atomic write. On Windows the swap can fail for a moment while the other side has the file
    open to read it; wait a little and try again rather than lose an answer."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    for attempt in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == tries - 1:
                os.unlink(tmp)
                raise
            time.sleep(0.05 * (attempt + 1))


def read_json(path, tries=8):
    for attempt in range(tries):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def load_session():
    """The current session, or None when no page has been started here."""
    path = session_path()
    if not os.path.isfile(path):
        return None
    try:
        data = read_json(path)
    except (OSError, ValueError):
        raise SessionError("The onboarding page's session file is damaged. Start the page again; "
                           "answers already confirmed are kept in the answers file.")
    return data if isinstance(data, dict) else None


def save_session(data):
    write_json(session_path(), data)


def load_intake(session):
    try:
        return read_json(session["intake"])
    except (OSError, ValueError, KeyError, TypeError):
        raise SessionError("The answers file for this onboarding could not be read.")


# ----------------------------------------------------------------------------- the answers file
def _schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_intake(data):
    """Problems with an answers file, in plain words. An empty list means it is sound."""
    out = []
    brands._validate(data, _schema(), "", out)
    if isinstance(data, dict) and not isinstance(data.get("answers"), dict):
        out.append("answers is missing")
    if isinstance(data, dict) and isinstance(data.get("answers"), dict):
        for key in data["answers"]:
            if key not in ANSWER_KEYS:
                out.append("answers.%s is not one of the onboarding answers" % key)
            else:
                out += _never_drafted_problems(key, data["answers"][key])
                out += _generated_problems(key, data["answers"][key])
        out += inventory_problems(data["answers"])
    return out


def _generated(value):
    return isinstance(value, dict) and (value.get("origin") in GENERATED_ORIGINS or str(
        value.get("generator") or "").startswith(("pack:", "claude-from-description")))


def _generated_problems(key, answer):
    """Suggested words (a starter pack, or Claude from the owner's short description) may only fill the
    allowlisted fields (spec rev 12, N3). Anything else must be the owner's own: refused wherever it appears."""
    out = []
    if key == "provenance":
        for fid, p in (answer.items() if isinstance(answer, dict) else []):
            if _generated(p) and fid not in GENERATED_FIELDS:
                out.append("answers.provenance.%s: suggested words can't fill this question; only your own words "
                           "go there" % fid)
        return out
    if key in GENERATED_KEYS:
        return out
    if key in ("teach", "audience") and _generated(answer):
        return ["answers.%s: suggested words are kept question by question, never on the whole answer" % key]
    if key == "teach" and isinstance(answer, dict):
        for part, value in answer.items():
            items = value if isinstance(value, list) else [value]
            if part not in ("myths", "mistakes") and any(_generated(v) for v in items):
                out.append("answers.teach.%s: suggested words can't fill this question; only your own words go "
                           "there" % part)
        return out
    if key == "audience" and isinstance(answer, dict):
        if any(_generated(v) for v in answer.get("objections") or []):
            out.append("answers.audience.objections: the objections you hear are only ever your own words")
        return out

    def walk(v):
        if isinstance(v, list):
            return any(walk(x) for x in v)
        if isinstance(v, dict):
            return _generated(v) or any(walk(x) for x in v.values())
        return False
    if walk(answer):
        out.append("answers.%s: suggested words can't fill this question; only your own words go there" % key)
    return out


def quote_problems(v):
    """Why a drafted belief, others/us row or non-negotiable isn't an acceptable quote of the owner's own writing
    (rev 13, M6). An empty list: it's a quote, labelled, from their own document or website, said by them."""
    out = []
    if v.get("quoted") is not True:
        out.append("it isn't marked as a quote")
    origin = v.get("origin")
    if origin not in QUOTE_GENERATORS:
        out.append("it doesn't come from your own document or website")
    elif v.get("generator") != QUOTE_GENERATORS[origin]:
        out.append("it doesn't say it was quoted by Claude from that %s" % origin)
    refs = v.get("refs")
    if not (isinstance(refs, list) and refs and all(isinstance(r, str) and r.strip() for r in refs)):
        out.append("it doesn't say where it was found (the page)")
    if v.get("said_by") not in QUOTE_SPEAKERS:
        out.append("it isn't recorded as the owner's own words")
    if v.get("status") == "confirmed" and v.get("accepted") is not True:
        out.append("it was confirmed without its own yes (each quote is confirmed on its own)")
    if not (isinstance(v.get("excerpt"), str) and v["excerpt"].strip()):
        out.append("the exact words it came from aren't kept")
    else:
        listed = "quoted_parts" in v
        quoted = v.get("quoted_parts") if listed else [p for p in QUOTE_PARTS if v.get(p)]
        if not isinstance(quoted, list) or not quoted or \
                not all(isinstance(v.get(p), str) and v[p].strip() for p in quoted):
            out.append("it doesn't say which of its words are quoted")
        else:
            for part in quoted:
                if not close_extract(v[part], v["excerpt"]):
                    out.append("its words aren't in the passage it says it came from")
                    break
    return out


def _unquoted_parts(v):
    """In a draft from Claude (not yet the owner's), the parts with words that aren't quoted. They must stay empty
    (rev 13, M6: the unsupported part stays empty, the item is "partly"); the owner fills them on the page."""
    quoted = v.get("quoted_parts") if "quoted_parts" in v else [p for p in QUOTE_PARTS if v.get(p)]
    return [p for p in QUOTE_PARTS if isinstance(v.get(p), str) and v[p].strip()
            and p not in (quoted if isinstance(quoted, list) else [])]


def close_extract(text, excerpt):
    """True when `text` is the owner's own words from `excerpt`: the same words in the same order, as one
    unbroken stretch of the passage. Only capitals and punctuation may differ, so no word can be added."""
    words, source = _plain(text).split(), _plain(excerpt).split()
    if not words:
        return True
    n = len(words)
    return any(source[i:i + n] == words for i in range(len(source) - n + 1))


def _never_drafted_problems(key, answer):
    """A drafted core belief, others/us row or non-negotiable (F8 B, D, E) is refused unless it's a quote of the
    owner's own writing (rev 13, M6). A pack or a description never fills them (also refused by N3's rules)."""
    if key in NEVER_DRAFTED_KEYS:
        out = []
        for v in (answer.get("items") if isinstance(answer, dict) else None) or []:
            if isinstance(v, dict) and v.get("source") in ("draft", "draft-edited") and not v.get("remove"):
                why = quote_problems(v)
                if why:
                    out.append("answers.%s only takes your own answers, or a quote from your own writing: %s"
                               % (key, "; ".join(why)))
                    break
        return out
    if key != "positioning" or not isinstance(answer, dict):
        return []
    out = []
    for part in NEVER_DRAFTED:
        value = answer.get(part)
        items = value if isinstance(value, list) else [value]
        for v in items:
            if isinstance(v, dict) and v.get("source") in ("draft", "draft-edited") and not v.get("remove"):
                why = quote_problems(v)
                if why:
                    out.append("answers.positioning.%s only takes your own words (%s), or a quote from your own "
                               "writing: %s" % (part, NEVER_DRAFTED_WORDS[part], "; ".join(why)))
                    break
    return out


def inventory_problems(answers, needs_refs=False):
    """Rev 13 (M3): the inventory's shape, and nothing drafted from a file marked "don't use". With needs_refs (a
    new draft made from the owner's material), every draft from a document says where it was found; older
    drafts without refs stay readable, and the page says "source not recorded"."""
    out = []
    inv = answers.get("inventory")
    banned, known_ids = set(), set()
    if isinstance(inv, dict):
        ids = set()
        for src in inv.get("sources") or []:
            if isinstance(src, dict) and src.get("id"):
                if src["id"] in ids:
                    out.append("answers.inventory: two sources share the id %s" % src["id"])
                ids.add(src["id"])
                known_ids.add(src["id"])
                if src.get("dont_use"):
                    banned.add(src["id"])
        known = {f["id"] for f in fields()["core"] + (fields().get("extra") or [])}
        for fid, cov in (inv.get("fields") or {}).items():
            if fid not in known:
                out.append("answers.inventory.fields.%s is not one of the 31 questions" % fid)

    def refs_of(v):
        refs = v.get("refs")
        return [r for r in refs if isinstance(r, str) and r.strip()] if isinstance(refs, list) else []

    prov = answers.get("provenance") if isinstance(answers.get("provenance"), dict) else {}
    every = fields()["core"] + fields()["deep"] + (fields().get("extra") or [])

    def prov_refs(where):
        """Refs recorded for the question this part belongs to: answers.<key>[.<part>] -> its question ids."""
        bits = re.split(r"[.\[]", where)
        key, part = bits[1], (bits[2] if len(bits) > 2 and not bits[2].endswith("]") else "")
        ids = [f["id"] for f in every if f.get("key") == key and
               (not part or part in (f.get("list"), f.get("path"), f.get("id")) or (key not in GROUP_KEYS))]
        return any(refs_of(prov[fid]) for fid in ids if isinstance(prov.get(fid), dict))

    def walk(v, where):
        if isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, "%s[%d]" % (where, i + 1))
            return
        if not isinstance(v, dict):
            return
        rs = refs_of(v)
        if needs_refs and isinstance(inv, dict) and v.get("origin") == "document":
            unknown = [r for r in rs if r.split() and r.split()[0] not in known_ids]
            if unknown:
                out.append("%s points at a source the inventory doesn't list (%s)" % (where, unknown[0]))
        if any(r.split()[0] in banned for r in rs if r.split()):
            out.append("%s comes from a file marked \"don't use\"" % where)
        if needs_refs and v.get("origin") in ("document", "website") and v.get("source") in ("draft", "draft-edited") \
                and not rs and not v.get("remove") and not prov_refs(where):
            out.append("%s was drafted from %s but doesn't say where (refs: %s)" % (
                where, "your website" if v.get("origin") == "website" else "a document",
                "the page and section" if v.get("origin") == "website" else "the source and page"))
        for k, x in v.items():
            if isinstance(x, (dict, list)) and k not in ("refs",):
                walk(x, where + "." + k)
    for key, value in answers.items():
        if key in ("inventory",):
            continue
        if key == "provenance" and isinstance(value, dict):
            for fid, p in value.items():
                if isinstance(p, dict) and any(r.split()[0] in banned for r in refs_of(p) if r.split()):
                    out.append("answers.provenance.%s comes from a file marked \"don't use\"" % fid)
            continue
        walk(value, "answers." + key)
    return out


def validate_answer(key, answer):
    """Problems with one answer, checked against the same schema as the whole file."""
    if key not in ANSWER_KEYS:
        return ["'%s' is not one of the onboarding answers" % key]
    out = []
    sub = _schema()["properties"]["answers"]["properties"][key]
    brands._validate(answer, sub, "answers." + key, out)
    return out + _never_drafted_problems(key, answer) + _generated_problems(key, answer)


QUESTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json")
TAP_REQUIRED = ("name", "identities", "rules")      # names, handles, never-name, never-claim (spec 3b)
EXAMPLE_KEYS = ("name", "what_you_do", "audience")
NOT_TAPPED = ("Names, handles and your rules are only confirmed by a tap on the page. "
              "Check the spelling, then tap to confirm.")
LIKE_THE_EXAMPLE = ("That reads a lot like the example. Is it really yours? If it is, tap "
                    "“Yes, these are my own words”.")


def questions():
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["questions"]


def _plain(text):
    return " ".join(re.findall(r"[a-z0-9&]+", (text or "").lower()))


def reads_like_example(key, answer):
    """True when a typed answer is (nearly) the example's own words and the person has not said
    they are theirs. Examples are there to show the kind of answer, never to be copied."""
    if key not in EXAMPLE_KEYS or not isinstance(answer, dict) or answer.get("own_words") is True:
        return False
    if answer.get("status") != "confirmed" or answer.get("source") == "draft":
        return False                                # only a typed answer being confirmed is questioned
    example = next((q.get("example_text") for q in questions() if q["key"] == key), None)
    mine, theirs = _plain(answer.get("value")), _plain(example)
    if not mine or not theirs:
        return False
    return mine == theirs or difflib.SequenceMatcher(None, mine, theirs).ratio() >= 0.85


def confirmed_without_tap(key, answer):
    """True when an answer that needs a tap (spec 3b) says confirmed but was not tapped."""
    if key not in TAP_REQUIRED:
        return False
    items = answer if isinstance(answer, list) else [answer]
    return any(isinstance(a, dict) and a.get("status") == "confirmed" and a.get("tapped") is not True
               for a in items)


def blank_intake(brand=None):
    return {"version": 2, "state": "in_progress", "brand": brand, "consent": None,
            "answers": {}, "skipped": [], "reflection": None}


def _as_draft(key, value):
    """A website draft is a guess until the person confirms it: every drafted answer, and every
    drafted item in a list, starts as 'unconfirmed' with source 'draft', whatever the file said.
    Inside a group (what they stand for, what they teach, go deeper) each part is drafted on its own,
    and a part that looks like a key is dropped by itself."""
    if isinstance(value, list):
        return [_as_draft(key, v) for v in value if isinstance(v, dict)]
    if key == "inventory":                          # what was read and what it gave each question: a record
        return value if not secrets_check.any_secret(value) else {}
    if key == "provenance":                         # where each field's words came from: a record, not an answer
        return {f: p for f, p in value.items() if isinstance(p, dict) and not secrets_check.any_secret(p)}
    if key in GROUP_KEYS:
        return {part: (_as_draft(part, v) if isinstance(v, (dict, list)) else v) for part, v in value.items()
                if not secrets_check.any_secret(v)}
    if key in NEVER_DRAFTED_KEYS:                   # a question with its own answer: each row is a draft on its own
        rows = value.get("items") if isinstance(value.get("items"), list) else []
        return {"status": "unconfirmed", "items": [_as_draft(key + ".items", v) for v in rows
                                                   if isinstance(v, dict) and not secrets_check.any_secret(v)]}
    value = dict(value)
    value["status"] = "unconfirmed"
    if key != "voice_samples":                      # a voice sample keeps its own source: typed or pasted
        value["source"] = "draft"
    return value


FOLLOWUP_MAX = 240          # one short question, never a paragraph


def _followups(given):
    """The draft's prepared follow-up questions (spec: "One follow-up when an answer is generic"): one per
    page field, short, never a key. Anything else is dropped rather than shown."""
    if not isinstance(given, dict):
        return {}
    ids = {f["id"] for f in fields()["core"] + fields()["deep"] + (fields().get("extra") or [])}
    out = {}
    for fid, text in given.items():
        if fid in ids and isinstance(text, str) and 0 < len(text.strip()) <= FOLLOWUP_MAX \
                and not secrets_check.any_secret(text):
            out[fid] = text.strip()
    return out


def intake_from_draft(draft, brand=None):
    """The starting answers file. `draft` is the agent's website draft ({"answers": {...}} or just
    the answers), or None when there was no website. Drafted answers that look like a key are
    dropped, never carried onto the page."""
    intake = blank_intake(brand)
    if draft is None:
        return intake
    if not isinstance(draft, dict):
        raise SessionError("The website draft is not in the shape the page reads.")
    answers = draft.get("answers", draft)
    if not isinstance(answers, dict):
        raise SessionError("The website draft is not in the shape the page reads.")
    for key, value in answers.items():
        if key not in ANSWER_KEYS:
            raise SessionError("The website draft has an answer the page does not ask: %s" % key)
        if key == "positioning" and isinstance(value, dict):
            drafted = [p for p in NEVER_DRAFTED if value.get(p) not in (None, [], {}) and any(
                not isinstance(v, dict) or quote_problems(v) or _unquoted_parts(v)
                for v in (value[p] if isinstance(value[p], list) else [value[p]]))]
            if drafted:
                raise SessionError("The draft fills in what only the person can say: %s. Leave %s out of the "
                                   "draft, or give each as a quote of their own writing (quoted, said_by, excerpt, "
                                   "refs); the page asks the person." % (
                                       "; ".join(NEVER_DRAFTED_WORDS[p] for p in drafted),
                                       "it" if len(drafted) == 1 else "them"))
        if key in NEVER_DRAFTED_KEYS and isinstance(value, dict):
            rows = value.get("items") if isinstance(value.get("items"), list) else []
            if any(not isinstance(v, dict) or quote_problems(v) or _unquoted_parts(v) for v in rows):
                raise SessionError("The draft fills in who inspires them, which only the person can say. Leave it "
                                   "out of the draft, or give each name as a quote of their own writing (quoted, "
                                   "said_by, excerpt, refs; every filled part quoted); the page asks the person.")
        if not isinstance(value, (dict, list)):
            continue
        if key not in GROUP_KEYS and secrets_check.any_secret(value):
            continue
        intake["answers"][key] = _as_draft(key, value)
    intake["followups"] = _followups(draft.get("followups") if "answers" in draft else None)
    problems = validate_intake(intake)
    problems += [p for p in inventory_problems(intake["answers"], needs_refs=True) if p not in problems]
    if problems:
        raise SessionError("The draft does not fit the page: " + "; ".join(problems[:5]))
    return intake


def has_confirmed(value):
    """True when the answer, or (for a group or a list) any part of it, is confirmed."""
    if isinstance(value, list):
        return any(has_confirmed(v) for v in value)
    if not isinstance(value, dict):
        return False
    if "status" in value:
        return value["status"] == "confirmed"
    return any(has_confirmed(v) for v in value.values())


FIELDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fields.json")
# The two v2 page designs (spec rev 11): A, one long page; B, one question at a time. Without a
# layout, today's page (index.html) runs, unchanged, until the A/B test picks a default.
LAYOUTS = {"one-page": "one-page.html", "steps": "steps.html"}


def fields():
    """The v2 questions both designs ask: the 31 core fields and Go deeper (fields.json)."""
    with open(FIELDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


PACKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "starter_packs.json")


def starter_packs():
    """The bundled starter packs (spec rev 12, N3): suggestions by type of business, on this computer only."""
    with open(PACKS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def match_pack(text, packs=None):
    """The closest bundled pack for what the owner typed ("Auto repair"), or None. Whole words and phrases
    only, longest match first, so "coach" never beats "life coach"."""
    words = " " + re.sub(r"[^a-z0-9&]+", " ", (text or "").lower()) + " "
    best, best_len = None, 0
    for pack in (packs or starter_packs())["packs"]:
        for m in pack.get("matches", []):
            m2 = " " + re.sub(r"[^a-z0-9&]+", " ", m.lower()).strip() + " "
            if m2.strip() and m2 in words and len(m2) > best_len:
                best, best_len = pack, len(m2)
    return best


def asked_keys(layout=None):
    """The core answers the page asks, in its order. Today's page asks the basics (questions.json);
    the v2 designs (`layout`) ask the whole core, so every core answer can be a placeholder."""
    if layout is None:
        session = load_session()
        layout = session.get("layout") if session else None
    if layout in LAYOUTS:
        return CORE_KEYS
    asked = {q["key"] for q in questions()}
    return tuple(k for k in CORE_KEYS if k in asked)


def placeholders(intake, keys=None):
    """Every answer the agent must treat as a placeholder: anything the page asks (or `keys`, for
    example CORE_KEYS) that is not confirmed, plus any that never got an answer at all. Going deeper
    is optional, so it is never a placeholder."""
    answers = intake.get("answers", {})
    return [key for key in (asked_keys() if keys is None else keys) if not has_confirmed(answers.get(key))]


# ----------------------------------------------------------------------------- starting
def new_session(port, intake, brand=None, layout=None):
    """Write a fresh answers file and session file, replacing any earlier session (an earlier page
    server notices its code is gone and stops itself). `layout` picks a v2 design (LAYOUTS)."""
    if layout is not None and layout not in LAYOUTS:
        raise SessionError("There's no page design called %s. Choose one-page or steps." % layout)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    intake_path = os.path.join(tmp_dir(), "onboarding-intake-%s.json" % stamp)
    write_json(intake_path, intake)
    code = secrets.token_urlsafe(18)
    session = {"version": 1, "code": code, "port": port,
               "url": "http://127.0.0.1:%d/%s/" % (port, code),
               "intake": intake_path, "brand": brand, "started_at": now_iso(), "started": time.time(),
               "picked_up": None, "result": None, "finished": None, "stop": False}
    if layout:
        session["layout"] = layout
    save_session(session)
    return session


# ----------------------------------------------------------------------------- what the command asks
def server_answers(session, timeout=0.3):
    """Is anything listening on the session's port right now?"""
    try:
        with socket.create_connection(("127.0.0.1", int(session.get("port") or 0)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def state_of(session, intake=None):
    """in progress / complete / finished / stopped, from the two files (and the port)."""
    if session is None:
        return "no page"
    if session.get("stop") or not server_answers(session):
        return "stopped"
    if session.get("finished"):
        return "finished"
    intake = intake if intake is not None else load_intake(session)
    return "complete" if intake.get("state") == "complete" else "in progress"


def status():
    """What `--status` prints: the state and where things are, never the answers themselves."""
    session = load_session()
    if session is None:
        return {"state": "no page"}
    out = {"state": state_of(session), "address": session.get("url"), "answers_file": session.get("intake"),
           "brand": session.get("brand")}
    try:
        intake = load_intake(session)
        out["still_open"] = placeholders(intake)
        out["microphone"] = (intake.get("microphone") or {}).get("state")      # F6: why the page can't hear
        out["voice_consent"] = bool((intake.get("consent") or {}).get("recording"))
    except SessionError:
        pass
    return out


def wait(limit=WAIT_LIMIT, poll=0.5, clock=time.monotonic, sleep=time.sleep):
    """Block until the person does the next thing. Before the result: ("complete", session) when they
    finish, or ("still answering", session) on the time limit. After the result: ("first-post" or
    "done", session) on their last tap, or ("still looking", session). Also ("stopped", session) or
    ("no page", None).
    On "complete" the session records that an agent has picked the answers up, which is what tells
    the page to show "Finishing your brand..." instead of the go-back-to-the-chat backstop."""
    end = clock() + limit
    while True:
        session = load_session()
        if session is None:
            return "no page", None
        intake = load_intake(session)
        if session.get("finished"):
            # The result is on the page; now wait for their last tap (write my first post / I'm done).
            if intake.get("closing") in ("first-post", "done"):
                return intake["closing"], session
            if session.get("stop") or not server_answers(session):
                return "stopped", session
            if clock() >= end:
                return "still looking", session
            sleep(poll)
            continue
        if intake.get("state") == "complete":
            if not session.get("picked_up"):
                session["picked_up"] = time.time()
                save_session(session)
            return "complete", session
        if session.get("stop") or not server_answers(session):
            return "stopped", session
        if clock() >= end:
            return "still answering", session
        sleep(poll)


RESULT_FIELDS = {"version": int, "ok": bool, "message": str}


def set_result(result):
    """Hand the page the agent's result. Only after the person has finished, and only the fields
    the page shows. The page never sees raw errors: `message` is the one sentence it displays."""
    session = load_session()
    if session is None:
        raise SessionError("No onboarding page is running here, so there is nobody to show the result to.")
    if not isinstance(result, dict):
        raise SessionError("The result is not in the shape the page reads.")
    for key, kind in RESULT_FIELDS.items():
        if not isinstance(result.get(key), kind) or (kind is int and isinstance(result.get(key), bool)):
            raise SessionError("The result is missing '%s'." % key)
    intake = load_intake(session)
    if intake.get("state") != "complete":
        raise SessionError("The person has not finished the page yet, so the result was not handed over.")
    # Only the words the page shows are checked: the paths are locked to the brand's folder by the server.
    if secrets_check.any_secret({k: result.get(k) for k in ("message", "brand", "steps")}):
        raise SessionError("The result holds something that looks like a key, so it was not handed to the page.")
    keep = ("version", "ok", "brand", "demo_image", "summary", "steps", "message")
    session["result"] = {k: result[k] for k in keep if k in result}
    session["finished"] = time.time()
    if not session.get("picked_up"):
        session["picked_up"] = session["finished"]
    save_session(session)
    return session


def request_stop():
    session = load_session()
    if session is None:
        return None
    session["stop"] = True
    save_session(session)
    return session

# ----------------------------------------------------------------------------- add more, any time (rev 13, M5)
MATERIAL_TMP = "onboarding-material"                 # in .factory/tmp: a new brand's material, before it's built


def brand_answers_path(brand):
    return brand.path("_state", "onboarding-answers.json")


def brand_fingerprint(brand):
    """What the brand's settings look like now, so answers saved earlier know if it changed since."""
    import hashlib
    try:
        with open(brand.path("brand-master.json"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return ""


def material_dir(brand=None):
    """Where the owner drops their material: the brand's own Inputs/Material, or .factory/tmp for a new brand.
    Both are git-ignored, so nothing the owner brings goes to GitHub."""
    path = brand.path("Inputs", "Material") if brand is not None else os.path.join(tmp_dir(), MATERIAL_TMP)
    os.makedirs(path, exist_ok=True)
    return path


def keep_answers(brand, intake, save=None):
    """After the brand is built: keep the whole answers file (confirmed, skipped and waiting) and the inventory
    in the brand's own _state folder, and move a new brand's material into Client/<id>/Inputs/Material/.
    `save(intake)` writes the session's own answers file, so which files are this brand's, and whether they've all
    moved, survives a failed move and a retry. Returns (answers path, files moved)."""
    import shutil
    if intake.get("brand") and intake["brand"] != brand.id:
        raise SessionError("These answers belong to %s, not %s, so they weren't kept." % (intake["brand"], brand.id))
    src = os.path.join(tmp_dir(), MATERIAL_TMP)
    owns = not intake.get("brand") and not intake.get("material_moved_to")     # a new brand's first build
    if owns and intake.get("material_files") is None:
        intake["material_files"] = sorted(os.listdir(src)) if os.path.isdir(src) else []
        if save:
            save(intake)                             # the list is this session's, before anything moves
    moved = 0
    if owns:
        dst = material_dir(brand)
        for name in list(intake["material_files"]):
            here = os.path.join(src, name)
            if os.path.exists(here):
                target, stem, n = os.path.join(dst, name), os.path.splitext(name), 2
                while os.path.exists(target):        # never overwrite a file already in the brand
                    target = os.path.join(dst, "%s (%d)%s" % (stem[0], n, stem[1]))
                    n += 1
                shutil.move(here, target)
                moved += 1
            intake["material_files"].remove(name)
            if save:
                save(intake)
        intake["material_moved_to"] = brand.id      # only once every one of this brand's files has moved
        intake.pop("material_files", None)
        if save:
            save(intake)
        try:
            os.rmdir(src)
        except OSError:
            pass
    kept = json.loads(json.dumps(intake))
    kept["brand"] = brand.id
    kept["state"] = "kept"
    kept["brand_fingerprint"] = brand_fingerprint(brand)
    kept["brand_baseline"] = answers_from_brand(brand)
    kept["brand_tracked"] = tracked_from_brand(brand)
    kept["kept_at"] = now_iso()
    for k in ("new_keys", "brand_changed", "opened_fingerprint", "brand_samples_file"):
        kept.pop(k, None)
    path = brand_answers_path(brand)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, kept)
    inv = (kept.get("answers") or {}).get("inventory")
    if isinstance(inv, dict):
        write_json(brand.path("_state", "inventory.json"), inv)
    if save and intake.get("kept_as") != brand.id:
        intake["kept_as"] = brand.id                # a retried build of this session knows its brand (proof once)
        save(intake)
    return path, moved


def _text_of(v):
    """A short plain line for an answer, to show a candidate beside the owner's own."""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "; ".join(t for t in (_text_of(x) for x in v if not (isinstance(x, dict) and x.get("remove"))) if t)
    if isinstance(v, dict):
        for k in ("value", "who", "catalyst"):
            if isinstance(v.get(k), str) and v[k].strip():
                return v[k]
        if v.get("others") or v.get("us"):
            return "%s / %s" % (v.get("others") or "", v.get("us") or "")
    return ""


def _occupied(v):
    """True when the answers file already holds something of the owner's here: confirmed, typed or waiting."""
    if isinstance(v, list):
        return any(_occupied(x) for x in v)
    return isinstance(v, dict) and not v.get("remove") and v.get("status") in ("confirmed", "unconfirmed", "for_chat")


def _decided(v):
    """Confirmed or skipped: an empty list is how a list answer is skipped."""
    if isinstance(v, list):
        return v == [] or all(isinstance(x, dict) and x.get("status") in ("confirmed", "skipped") for x in v)
    return isinstance(v, dict) and v.get("status") in ("confirmed", "skipped")


TYPING_MAX = 64 * 1024          # one question's waiting typing, as JSON


ROW_MARK_NAMES = ("gen", "origin", "text", "cand", "source")
PART_NAME = re.compile(r"^[a-z_]{1,40}$")
ROW_ID = re.compile(r"^[a-z0-9-]{0,60}$")


PART_YES = ("goal", "platforms", "make", "acquisition")


def _typing_shape(fid, snap, depth=0):
    """Every part of one question's waiting typing, checked: plain values in the page's own shape, and only that
    question's boxes, choices and lists. Returns "" when it's fine."""
    bad = "That didn't arrive in the shape the onboarding page sends."
    own = "f-%s-" % fid
    if not isinstance(snap, dict) or not set(snap) <= {"inputs", "pressed", "lists", "dirty", "usedCand", "coreYes", "partYes"}:
        return bad
    inputs, pressed, lists = snap.get("inputs", {}), snap.get("pressed", {}), snap.get("lists", {})
    if not (isinstance(inputs, dict) and isinstance(pressed, dict) and isinstance(lists, dict)):
        return bad
    for k, v in inputs.items():
        if not (isinstance(k, str) and k.startswith(own) and isinstance(v, (str, bool))):
            return bad
    for k, v in pressed.items():
        if not (isinstance(k, str) and k.startswith(own) and isinstance(v, list) and all(isinstance(x, str) for x in v)):
            return bad
    for k, l in lists.items():
        if not (isinstance(k, str) and k.startswith(own) and isinstance(l, dict) and set(l) <= {"rows", "removed"}):
            return bad
        if not isinstance(l.get("removed", ""), str) or not isinstance(l.get("rows", []), list):
            return bad
        for r in l.get("rows", []):
            if not (isinstance(r, dict) and set(r) <= {"id", "hidden", "inputs", "pressed", "marks", "quoteYes"}):
                return bad
            if not (isinstance(r.get("id", ""), str) and ROW_ID.match(r.get("id", ""))):
                return bad
            if not isinstance(r.get("hidden", False), bool) or not isinstance(r.get("quoteYes", False), bool):
                return bad
            ri, rp, rm = r.get("inputs", {}), r.get("pressed", {}), r.get("marks", {})
            if not (isinstance(ri, dict) and all(isinstance(n, str) and PART_NAME.match(n) and isinstance(v, (str, bool))
                                                 for n, v in ri.items())):
                return bad
            if not (isinstance(rp, dict) and all(isinstance(n, str) and PART_NAME.match(n) and isinstance(v, list)
                                                 and all(isinstance(x, str) for x in v) for n, v in rp.items())):
                return bad
            if not (isinstance(rm, dict) and all(n in ROW_MARK_NAMES and isinstance(v, str) for n, v in rm.items())):
                return bad
    if not isinstance(snap.get("dirty", False), bool) or not isinstance(snap.get("coreYes", False), bool):
        return bad
    py = snap.get("partYes", {})                    # question 29's own "Yes, keep this" per part
    if not (isinstance(py, dict) and all(k in PART_YES and isinstance(v, bool) for k, v in py.items())):
        return bad
    if py and fid != "goal_platforms":
        return bad
    uc = snap.get("usedCand")
    if uc is not None:
        if depth or not isinstance(uc, dict) or not set(uc) <= {"key", "part", "cid", "origin", "refs", "generator", "snap", "text"}:
            return bad
        if not all(isinstance(uc.get(k, ""), str) for k in ("key", "part", "cid", "origin", "generator", "text")):
            return bad
        if not (isinstance(uc.get("refs", []), list) and all(isinstance(x, str) for x in uc.get("refs", []))):
            return bad
        if uc.get("snap") is not None:
            return _typing_shape(fid, uc["snap"], depth + 1)
    return ""


def typing_problems(fid, snap):
    """Why one question's waiting typing can't be kept, or "" when it can: the question must exist, the record must
    be plain values in the page's shape (only that question's own boxes, no page code), small, and never hold
    anything that looks like a key."""
    ids = {f["id"] for f in fields()["core"] + fields()["deep"] + (fields().get("extra") or [])}
    if not isinstance(fid, str) or fid not in ids:
        return "That isn't one of the page's questions."
    if snap is None:
        return ""
    try:
        raw = json.dumps(snap)
    except (TypeError, ValueError):
        return "That didn't arrive in the shape the onboarding page sends."
    if len(raw) > TYPING_MAX:
        return "That's more typing than one question holds. Confirm what you have, or answer in the chat."
    shape = _typing_shape(fid, snap)
    if shape:
        return shape
    # Page code, never ordinary writing: a real tag ("<b>", "</p>", "<!--") is refused; "price <$50" or "under <5 kids"
    # or "a <b and c" isn't (Gemini review, Oct 22).
    if re.search(r"<\s*(/\s*)?[a-zA-Z][a-zA-Z0-9-]*(\s[^<>]*)?\s*/?\s*>|<!--", raw):
        return "That didn't arrive in the shape the onboarding page sends."
    if secrets_check.any_secret(snap):
        return secrets_check.MESSAGE
    return ""


def candidate_id(value):
    """A stable id for one alternative, from its content: the same words read twice are one alternative."""
    import hashlib
    return "c-" + hashlib.sha1(json.dumps(_norm(value), sort_keys=True).encode("utf-8")).hexdigest()[:10]


def add_candidate(where, k, value):
    """Keep new material beside the owner's answer, as one alternative with its own id. A later reading adds
    another; none is dropped, and the same words twice are kept once. Only the owner's own choice on that
    alternative (Use instead, Add to mine, Keep mine) settles it."""
    alt = {"cid": candidate_id(value), "answer": value}
    cur = where.get(k)
    if isinstance(cur, dict) and isinstance(cur.get("alternatives"), list):
        alts = [x if isinstance(x, dict) and "cid" in x else {"cid": candidate_id(x), "answer": x} for x in cur["alternatives"]]
        if alt["cid"] not in {x["cid"] for x in alts}:
            alts.append(alt)
        cur["alternatives"] = alts
    else:
        where[k] = {"alternatives": [alt]}


def _shared_fields():
    """Answer keys that more than one page question stores into (name and handle, the four audience questions,
    voice and phrases, the four offer rungs), each with its questions. New material for such a key is kept per
    question, so each question shows, uses and settles only its own part."""
    every = fields()["core"] + (fields().get("extra") or [])
    by = {}
    for f in every:
        if f.get("key") and f["key"] not in GROUP_KEYS:
            by.setdefault(f["key"], []).append(f)
    return {k: v for k, v in by.items() if len(v) > 1}


def _own_parts(f):
    if f.get("kind") == "name":
        return ["value"]
    if f.get("list"):
        return [f["list"]]
    return [x["name"] for x in f.get("parts") or [] if not x.get("key")]


def project_for(f, value, siblings):
    """The part of a shared key's value that question `f` asks: its own parts, plus the marks that say where it
    came from (never a sibling question's parts). None when there's nothing of its own in it."""
    if f.get("kind") == "rung":
        items = [x for x in (value if isinstance(value, list) else [value]) if isinstance(x, dict) and x.get("rung") == f.get("rung")]
        return items or None
    if not isinstance(value, dict):
        return None
    own = _own_parts(f)
    others = {n for g in siblings if g is not f for n in _own_parts(g)} - set(own)
    if f.get("list"):
        items = value.get(f["list"])
        if not isinstance(items, list) or not items:
            return None
        marks = {k: v for k, v in value.items() if k not in others and k != f["list"]}
        return [dict(marks, **x) if isinstance(x, dict) and not x.get("refs") and marks.get("refs") else x
                for x in items if isinstance(x, dict)] or None
    if not any(value.get(n) not in (None, "", [], {}) for n in own):
        return None
    return {k: v for k, v in value.items() if k not in others}


def add_candidate_split(cands, key, value, answers):
    """add_candidate, but for a key several questions share, one alternative per question that the new value
    really changes (rev 13, M5): {key: {<question id>: {"alternatives": [...]}}}."""
    shared = _shared_fields().get(key)
    if not shared:
        add_candidate(cands, key, value)
        return
    box = cands.get(key) if isinstance(cands.get(key), dict) and "alternatives" not in cands.get(key) else {}
    for f in shared:
        mine = project_for(f, value, shared)
        if mine is None or _norm(mine) == _norm(project_for(f, answers.get(key), shared)):
            continue
        add_candidate(box, f["id"], mine)
    if box:
        cands[key] = box


def _by_question(key, box):
    """A candidates box kept part by part (a group key) or question by question (a shared key)."""
    return isinstance(box, dict) and "alternatives" not in box and (key in GROUP_KEYS or key in _shared_fields())


def normalize_candidates(cands):
    """Older saved alternatives (no id) get their id, so each can be decided on its own. Returns `cands`."""
    if not isinstance(cands, dict):
        return {}

    def fix(box):
        if isinstance(box, dict) and isinstance(box.get("alternatives"), list):
            box["alternatives"] = [x if isinstance(x, dict) and "cid" in x and "answer" in x
                                   else {"cid": candidate_id(x), "answer": x} for x in box["alternatives"]]
    for key, box in list(cands.items()):
        if _by_question(key, box):
            for part in box.values():
                fix(part)
        elif key in _shared_fields() and isinstance(box, dict) and isinstance(box.get("alternatives"), list):
            del cands[key]                          # saved before #43's split: each alternative goes to its questions
            for x in box["alternatives"]:
                add_candidate_split(cands, key, x.get("answer") if isinstance(x, dict) and "cid" in x else x, {})
        else:
            fix(box)
    return cands


def decide_candidate(intake, key, part, cid):
    """The owner chose for one alternative (used it, added it, or kept their own): that one goes; the rest stay
    until they're decided too. Returns False when that alternative isn't there (already decided, or stale)."""
    cands = intake.get("candidates")
    if not isinstance(cands, dict):
        return False
    box = cands.get(key)
    holder, name = cands, key
    if part and isinstance(box, dict) and "alternatives" not in box:
        holder, name, box = box, part, box.get(part)
    if not (isinstance(box, dict) and isinstance(box.get("alternatives"), list)):
        return False
    left = [x for x in box["alternatives"] if not (isinstance(x, dict) and x.get("cid") == cid)]
    if len(left) == len(box["alternatives"]):
        return False
    if left:
        box["alternatives"] = left
    else:
        del holder[name]
        if holder is not cands and not holder:
            del cands[key]
    return True


# The parts of a grouped answer each page question stores (positioning, teach, deep).
FIELD_PARTS = {"beliefs": ("core_belief", "contrarian"), "foragainst": ("for", "against"), "home": ("home_medium", "stage"),
               "story": ("story",)}


def field_parts(f):
    return FIELD_PARTS.get(f.get("kind")) or tuple(x for x in (f.get("list"), f.get("path")) if x)


def merge_inventory(old, new):
    """A later reading's inventory, merged by source id: earlier sources stay recorded, a source read again is
    updated, and a "don't use" mark stays unless the new reading explicitly changes it. Coverage is per question."""
    old = old if isinstance(old, dict) else {}
    new = new if isinstance(new, dict) else {}
    sources = [dict(x) for x in old.get("sources") or [] if isinstance(x, dict)]
    by_id = {x.get("id"): x for x in sources}
    for src in new.get("sources") or []:
        if not isinstance(src, dict):
            continue
        was = by_id.get(src.get("id"))
        if was is None:
            sources.append(dict(src))
            by_id[src.get("id")] = sources[-1]
            continue
        keep_mark = was.get("dont_use") and "dont_use" not in src
        was.update(src)
        if keep_mark:
            was["dont_use"] = True
    out = dict(old, **{k: v for k, v in new.items() if k not in ("sources", "fields")})
    out["sources"] = sources
    out["fields"] = dict(old.get("fields") or {}, **(new.get("fields") or {}))
    return out


def reopen_intake(brand, draft=None):
    """The answers file for `--brand <id>`: the brand's kept answers (confirmed stay confirmed, waiting stay
    waiting), then anything new from `draft`. New reading never replaces what's there: where the owner already
    has an answer (confirmed, typed or a waiting draft), the new one is kept beside it as a candidate. If the
    brand changed since the answers were kept (an edit in the chat), the page says so."""
    path = brand_answers_path(brand)
    intake = None
    if os.path.exists(path):
        try:
            intake = read_json(path)
        except (OSError, ValueError):
            raise SessionError("This brand's saved answers (%s) can't be read, so the page didn't open. Nothing was "
                               "changed. Restore the file from a backup, or move it aside to start the page from the "
                               "brand's settings." % os.path.relpath(path, ROOT))
        if not isinstance(intake, dict) or (intake.get("brand") and intake["brand"] != brand.id):
            raise SessionError("This brand's saved answers (%s) belong to another brand, so the page didn't open. "
                               "Nothing was changed." % os.path.relpath(path, ROOT))
        problems = validate_intake(dict(intake, state="in_progress"))
        if problems:
            raise SessionError("This brand's saved answers (%s) aren't in the shape the page writes (%s), so the page "
                               "didn't open. Nothing was changed." % (os.path.relpath(path, ROOT), problems[0]))
    from_brand = answers_from_brand(brand)
    if intake is None:
        intake = blank_intake(brand.id)
        intake["answers"] = from_brand
    else:
        if intake.get("brand_fingerprint") and intake["brand_fingerprint"] != brand_fingerprint(brand):
            intake["brand_changed"] = bool(reconcile_with_brand(intake, brand))
        for key, value in from_brand.items():            # anything the kept answers don't have, from the brand
            if key not in intake.setdefault("answers", {}):
                intake["answers"][key] = value
        kept_vs = [x for x in intake["answers"].get("voice_samples") or [] if isinstance(x, dict)]
        waiting = [x for x in kept_vs if _waiting(x)]
        # The brand's samples whole, each keeping where it came from (so a later "don't use" still finds it),
        # then any still to confirm.
        was = {_norm(x.get("text")): x for x in kept_vs if not _waiting(x) and x.get("text")}
        samples = []
        for x in from_brand.get("voice_samples") or []:
            old = was.get(_norm(x.get("text")))
            if old:
                x = dict(x)
                for k in ("refs", "derived_from", "excerpt", "said_by"):
                    if old.get(k) is not None:
                        x[k] = json.loads(json.dumps(old[k]))
            samples.append(x)
        samples += waiting
        if samples:
            intake["answers"]["voice_samples"] = samples
        else:
            intake["answers"].pop("voice_samples", None)     # deleted in the chat: never brought back
        for k in ("brand_fingerprint", "kept_at", "completed", "finished_via", "closing"):
            intake.pop(k, None)
    intake["opened_fingerprint"] = brand_fingerprint(brand)
    try:                                            # the brand's own samples, word for word, to add new ones after
        with open(brand.path("Brand", "voice-samples.md"), "r", encoding="utf-8-sig") as f:
            intake["brand_samples_file"] = f.read()
    except OSError:
        intake.pop("brand_samples_file", None)
    intake["brand"], intake["state"] = brand.id, "in_progress"
    intake["candidates"] = normalize_candidates(intake.get("candidates") if isinstance(intake.get("candidates"), dict) else {})
    intake["new_keys"] = list(intake["candidates"].keys())
    if draft is None:
        return intake
    new = intake_from_draft(draft, brand.id)
    answers = intake.setdefault("answers", {})
    typed_keys = set()
    for f in fields()["core"] + fields()["deep"] + (fields().get("extra") or []):
        if f["id"] in (intake.get("typing") or {}):
            typed_keys.add(f.get("key"))
            typed_keys.update("%s.%s" % (f.get("key"), p) for p in field_parts(f))
    for key, value in new["answers"].items():
        if key == "inventory":
            before = {x.get("id") for x in (answers.get(key) or {}).get("sources") or [] if isinstance(x, dict) and x.get("dont_use")}
            merged = merge_inventory(answers.get(key), value)
            newly = sorted({x.get("id") for x in merged.get("sources") or [] if isinstance(x, dict) and x.get("dont_use")} - before)
            if newly and brand_answers_path(brand) and os.path.exists(brand_answers_path(brand)):
                raise SessionError("%s is newly marked \"don't use\". Take it out first, which also changes the brand at "
                                   "once: factory.py onboard-page --dont-use %s --brand %s. Then open the page again."
                                   % (newly[0], newly[0], brand.id))
            answers[key] = merged
            continue
        if key == "provenance":                     # merged after the answers, below
            continue
        if key in GROUP_KEYS and isinstance(value, dict):
            have = answers.setdefault(key, {})
            for part, pv in value.items():
                if _occupied(have.get(part)) or "%s.%s" % (key, part) in typed_keys:
                    add_candidate(intake["candidates"].setdefault(key, {}), part, pv)
                else:
                    have[part] = pv
                intake["new_keys"].append("%s.%s" % (key, part))
            continue
        if _occupied(answers.get(key)) or key in typed_keys:
            add_candidate_split(intake["candidates"], key, value, answers)
        else:
            answers[key] = value
        intake["new_keys"].append(key)
    filled = set(intake["new_keys"]) - {"%s.%s" % (k, p) for k, v in intake["candidates"].items()
                                        if k in GROUP_KEYS and isinstance(v, dict) and "alternatives" not in v
                                        for p in v} - {k for k in intake["candidates"]}
    prov = new["answers"].get("provenance") or {}
    if prov:
        mine = dict(answers.get("provenance") or {})
        for fid, p in prov.items():
            f = next((x for x in fields()["core"] + fields()["deep"] + (fields().get("extra") or []) if x["id"] == fid), None)
            if f and (f.get("key") in filled or any("%s.%s" % (f.get("key"), part) in filled for part in field_parts(f))):
                mine[fid] = p                       # this reading filled the question: its source is the one now
        answers["provenance"] = mine
    intake["followups"] = dict(intake.get("followups") or {}, **(new.get("followups") or {}))
    problems = validate_intake(intake)
    if problems:
        raise SessionError("The new material doesn't fit the brand's answers: " + "; ".join(problems[:5]))
    return intake


# ----------------------------------------------------------------------------- the brand, back as answers (#43)
def _restored(d):
    """A setting read back from the brand: the owner said it before, but it's shown to check again
    ("From your brand. Please check."). Never a new draft, never a quote: F8's checks don't apply."""
    d = dict(d)
    d.update({"status": "unconfirmed", "source": "typed", "origin": "brand", "restored": True})
    return d


def _text(v):
    return v.strip() if isinstance(v, str) and v.strip() and "TODO" not in v else ""


def _strings(v):
    return [x.strip() for x in v if isinstance(x, str) and x.strip() and "TODO" not in x] if isinstance(v, list) else []


def _brand_items(v, names):
    out = []
    for i, x in enumerate(v if isinstance(v, list) else []):
        if isinstance(x, dict):
            got = {n: _text(x.get(src)) for n, src in names.items() if _text(x.get(src))}
            if got:
                out.append(_restored(dict(got, id=x.get("id") or "b-%d" % (i + 1))))
        elif _text(x):
            out.append(_restored({"id": "b-%d" % (i + 1), "value": _text(x)}))
    return out


def brand_influences(v):
    """The brand's influences as page rows [{id, name, why?}]. A name written by hand (a plain string, or a row
    without an id) gets a stable id from its place, so a check again can edit or remove it."""
    out, taken = [], set()
    for i, x in enumerate(v if isinstance(v, list) else []):
        if isinstance(x, str):
            row = {"name": _text(x)}
        elif isinstance(x, dict):
            row = {"name": _text(x.get("name")), "why": _text(x.get("why"))}
        else:
            continue
        if not row["name"]:
            continue
        rid = x.get("id") if isinstance(x, dict) else None
        if not (isinstance(rid, str) and re.match(r"^[a-z0-9-]+$", rid)) or rid in taken:
            rid = next("influence-%d" % n for n in range(i + 1, i + 1000) if "influence-%d" % n not in taken)
        taken.add(rid)
        got = dict({k: val for k, val in row.items() if val}, id=rid)
        # Where a quoted name came from stays with it, so a file marked "don't use" later still finds it.
        refs = ((x.get("provenance") or {}).get("refs") if isinstance(x, dict) and isinstance(x.get("provenance"), dict) else None)
        if isinstance(refs, list) and any(isinstance(r, str) and r.strip() for r in refs):
            got["refs"] = [r for r in refs if isinstance(r, str) and r.strip()]
        out.append(got)
    return out


def brand_samples(brand):
    """The brand's voice samples, word for word, from Brand/voice-samples.md."""
    path = brand.path("Brand", "voice-samples.md")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return []
    out = []
    for i, m in enumerate(re.finditer(r"^## Sample \d+[^\n]*\n\n(.*?)(?=^## Sample \d+[^\n]*\n\n|\Z)", text, re.M | re.S), 1):
        body = m.group(1).strip()
        if body and not secrets_check.any_secret(body):
            out.append({"id": "vs-%d" % i, "text": body, "verbatim": True, "status": "confirmed",
                        "source": "pasted", "origin": "brand", "restored": True})
    return out


def answers_from_brand(brand):
    """What the brand already says, as page answers to check again. Only what the brand really holds:
    nothing from a TODO or an empty setting, and never a goal (the brand can't tell a chosen goal from the
    default one, so it shows "not answered yet"). Voice samples come back whole and already confirmed: they're
    the owner's own words, word for word, and must never shrink when the brand is rebuilt."""
    d = brand.data if isinstance(brand.data, dict) else {}
    biz, aud, voice = d.get("business") or {}, d.get("audience") or {}, d.get("voice") or {}
    vis, comp, pos = d.get("visual") or {}, d.get("compliance") or {}, d.get("positioning") or {}
    a = {}
    if _text(d.get("name")):
        n = {"value": _text(d["name"])}
        if _text(vis.get("handle")):
            n["handle"] = _text(vis["handle"])
        a["name"] = _restored(n)
    if _text(biz.get("what_we_do")):
        a["what_you_do"] = _restored({"value": _text(biz["what_we_do"])})
    if _text(aud.get("who")):
        got = {"value": _text(aud["who"])}
        if _strings(aud.get("questions_they_ask")):
            got["questions"] = _strings(aud["questions_they_ask"])
        if _strings(aud.get("problems")):
            got["in_the_way"] = _strings(aud["problems"])
        objections = _brand_items(aud.get("objections"), {"value": "value", "reply": "reply"})
        if objections:
            got["objections"] = objections
        for k in ("type", "where"):
            if _text(aud.get(k)):
                got[k] = _text(aud[k])
        a["audience"] = _restored(got)
    people = []
    for i in d.get("identities") or []:
        if isinstance(i, dict) and _text(i.get("display_name")) and i.get("kind") in ("person", "company"):
            p = {"id": i.get("id"), "kind": i["kind"], "name": _text(i["display_name"])}
            for src, dst in (("role", "role"), ("handle", "handle"), ("credential_line", "video_line")):
                if _text(i.get(src)):
                    p[dst] = _text(i[src])
            people.append(_restored(p))
    if people:
        a["identities"] = people
    samples = brand_samples(brand)
    if samples:
        a["voice_samples"] = samples
    colors = vis.get("colors") or {}
    if all(re.match(r"^#[0-9A-Fa-f]{6}$", colors.get(k) or "") for k in ("ground", "ink", "accent")):
        a["colours"] = _restored({"background": colors["ground"], "text": colors["ink"], "accent": colors["accent"]})
    rules = {}
    if _text(biz.get("regulated")):
        rules["industry"] = _text(biz["regulated"])
    for src, dst in ((comp.get("drop_terms"), "never_claim"), (d.get("never_mention"), "never_name"),
                     ((d.get("style") or {}).get("banned_words"), "hated_words")):
        if _strings(src):
            rules[dst] = _strings(src)
    if rules:
        a["rules"] = _restored(rules)
    if _strings(d.get("wants")):
        a["make"] = _restored({"value": _strings(d["wants"])})
    why = (d.get("person") or {}).get("why_started")
    if _text(why):
        a["why_started"] = _restored({"value": _text(why)})
    v = {}
    if _text(voice.get("register")):
        v["register"] = _text(voice["register"])
    for k in ("do", "dont", "signature_phrases"):
        if _strings(voice.get(k)):
            v[k] = _strings(voice[k])
    if v:
        a["voice"] = _restored(v)
    p = {}
    for part in ("known_for", "core_belief"):
        x = pos.get(part)
        if isinstance(x, dict) and _text(x.get("value")):
            got = {"value": _text(x["value"])}
            if _text(x.get("experience")):
                got["experience"] = _text(x["experience"])
            p[part] = _restored(got)
    for part, names in (("contrarian", {"value": "value", "experience": "experience"}),
                        ("for", {"value": "value", "experience": "experience"}),
                        ("against", {"value": "value", "experience": "experience"}),
                        ("differentiation", {"others": "others", "us": "us"}),
                        ("non_negotiables", {"value": "value"})):
        got = _brand_items(pos.get(part), names)
        if got:
            p[part] = got
    story = pos.get("story") if isinstance(pos.get("story"), dict) else {}
    st = {k: _text((story.get(k) or {}).get("value") if isinstance(story.get(k), dict) else story.get(k))
          for k in ("catalyst", "core_truth")}
    st = {k: x for k, x in st.items() if x}
    proof = _brand_items(story.get("proof"), {"value": "value"})
    if st or proof:
        got = dict(st)
        if proof:
            got["proof"] = proof
        p["story"] = _restored(got)
    for part in ("home_medium", "stage"):
        if _text(pos.get(part)):
            p[part] = _restored({"value": _text(pos[part])})
    if p:
        a["positioning"] = p
    t = {}
    for src, dst in (("myths", "myths"), ("mistakes", "mistakes"), ("steps_to_result", "steps")):
        got = _brand_items(d.get(src), {"value": "value"})
        if got:
            t[dst] = got
    if t:
        a["teach"] = t
    ladder = []
    for o in d.get("offers") or []:
        if isinstance(o, dict) and o.get("rung") in ("free", "entry", "main", "premium") and _text(o.get("name")):
            r = {"rung": o["rung"], "id": o.get("id"), "name": _text(o["name"])}
            for src, dst in (("what", "line"), ("link", "link"), ("price", "price"), ("call_to_action", "call_to_action")):
                if _text(o.get(src)):
                    r[dst] = _text(o[src])
            ladder.append(_restored(r))
    if ladder:
        a["ladder"] = ladder
    plat = d.get("intended_platforms") or {}
    if isinstance(plat.get("by_speaker"), dict) and any(plat["by_speaker"].values()):
        a["platforms"] = _restored({"by_speaker": {k: list(v) for k, v in plat["by_speaker"].items() if isinstance(v, list)},
                                    **({"other": _text(plat.get("other"))} if _text(plat.get("other")) else {})})
    cap = d.get("capacity") or {}
    got = {k: cap[k] for k in ("hours_per_week", "posts_per_week") if isinstance(cap.get(k), (int, float))}
    if _text(cap.get("helpers")):
        got["helpers"] = _text(cap["helpers"])
    if got:
        a["capacity"] = _restored(got)
    start = {k: _text(biz.get(src)) for k, src in (("what", "industry"), ("where", "location"), ("website", "website"))}
    start = {k: x for k, x in start.items() if x}
    if start:
        a["business_start"] = _restored(start)
    acq = _brand_items(aud.get("acquisition"), {"value": "value"})
    if acq:
        a["acquisition"] = acq
    rows = brand_influences(d.get("influences"))
    if rows:
        a["influences"] = {"status": "unconfirmed", "restored": True, "items": [_restored(r) for r in rows]}
    fp = vis.get("font_preference") or {}
    if _text(fp.get("heading")) or _text(fp.get("body")):
        a["fonts"] = _restored({k: _text(fp[k]) for k in ("heading", "body") if _text(fp.get(k))})
    sp = biz.get("starter_pack")
    if isinstance(sp, dict) and sp.get("id"):
        a["starter_pack"] = {"id": sp["id"], "version": sp.get("version", 1), "status": "confirmed", "source": "typed",
                             "origin": "brand"}
    return a


SETTLED_KEYS = ("status", "source", "origin", "restored", "tapped", "spelled", "own_words", "generator", "refs",
                "quoted", "said_by", "excerpt", "verbatim")


def _norm(v):
    """An answer's content only (no status, no source marks), for "did the brand change here?"."""
    if isinstance(v, list):
        return sorted((_norm(x) for x in v if not (isinstance(x, dict) and x.get("remove"))), key=lambda x: json.dumps(x, sort_keys=True))
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items() if k not in SETTLED_KEYS and x not in (None, "", [], {})}
    return v.strip() if isinstance(v, str) else v


def tracked_from_brand(brand):
    """What the brand says that's never restored as an answer but must still be watched for chat changes: the
    goal (never shown as answered, since a default can't be told from a choice) and the deeper answers."""
    d = brand.data if isinstance(brand.data, dict) else {}
    pos = d.get("positioning") or {}
    deep = {k: pos[k] for k in ("journey", "formats", "world", "compliments", "adjacent_topics") if pos.get(k)}
    return {"goal": d.get("goal") or "", "deep": deep}


def _waiting(v):
    return isinstance(v, dict) and not v.get("remove") and v.get("status") in ("unconfirmed", "for_chat")


def _changed_item(x):
    x = json.loads(json.dumps(x))
    if isinstance(x, dict):
        x["changed_in_chat"] = True
    return x


def _reconcile_value(answers, key, base, now, cands, where):
    """One answer (or one part of a group): the brand's current value wins where it changed since; a waiting
    answer there is kept beside it as an alternative. Lists go item by item (by id), so an unchanged item keeps
    its confirmation."""
    if _norm(base) == _norm(now):
        return False
    have = answers.get(key)
    if isinstance(base, list) or isinstance(now, list):
        old = {x.get("id"): x for x in (base or []) if isinstance(x, dict)}
        new = {x.get("id"): x for x in (now or []) if isinstance(x, dict)}
        mine = [x for x in (have if isinstance(have, list) else []) if isinstance(x, dict)]
        out, done = [], set()
        for x in mine:
            i = x.get("id")
            if i in old or i in new:
                done.add(i)
                if _norm(old.get(i)) == _norm(new.get(i)):
                    out.append(x)                           # unchanged in the brand: keeps its own state
                    continue
                if _waiting(x):
                    add_candidate_split(cands, where, [x], {}) if where in _shared_fields() else add_candidate(cands, where, x)
                if i in new:
                    out.append(_changed_item(new[i]))       # changed in the chat: the brand's value, to check
                continue                                    # removed in the chat: gone
            out.append(x)                                   # only on the page (new, waiting): kept
        for i, x in new.items():
            if i not in done and _norm(old.get(i)) != _norm(x):
                out.append(_changed_item(x))                # added in the chat
        answers[key] = out
        return True
    if _waiting(have):
        add_candidate_split(cands, where, have, {where: now}) if where in _shared_fields() else add_candidate(cands, where, have)
    if now is None:
        answers.pop(key, None)
    else:
        answers[key] = _changed_item(now)
    return True


def reconcile_with_brand(intake, brand):
    """The brand changed in the chat since its answers were kept (#43, gap 10). Only what changed is touched,
    part by part and item by item: the brand's current value wins there, shown "Changed in the chat since.
    Please check."; a waiting answer is kept beside it as an alternative; everything unchanged keeps its state.
    A goal or deeper answer changed in the chat drops the stale confirmed one, so it can't be sent back.
    Returns the places that changed."""
    base = intake.get("brand_baseline") or {}
    now = answers_from_brand(brand)
    answers = intake.setdefault("answers", {})
    cands = intake.setdefault("candidates", {})
    changed = []
    for key in sorted(set(base) | set(now)):
        if key in ("voice_samples", "starter_pack"):
            continue
        if key in GROUP_KEYS:
            group = answers.setdefault(key, {})
            b, n = base.get(key) or {}, now.get(key) or {}
            for part in sorted(set(b) | set(n)):
                if _reconcile_value(group, part, b.get(part), n.get(part), cands.setdefault(key, {}), part):
                    changed.append("%s.%s" % (key, part))
            if not cands.get(key):
                cands.pop(key, None)
            continue
        if _reconcile_value(answers, key, base.get(key), now.get(key), cands, key):
            changed.append(key)
    tb, tn = intake.get("brand_tracked") or {}, tracked_from_brand(brand)
    if _norm(tb.get("goal")) != _norm(tn.get("goal")):
        answers.pop("goal", None)
        changed.append("goal")
    for part in sorted(set(tb.get("deep") or {}) | set(tn.get("deep") or {})):
        if _norm((tb.get("deep") or {}).get(part)) != _norm((tn.get("deep") or {}).get(part)):
            (answers.get("deep") or {}).pop(part, None)
            changed.append("deep." + part)
    return changed


def brand_changed_since(intake, brand):
    """True when the brand's settings changed after the page opened (checked again before the brand is built)."""
    seen = intake.get("opened_fingerprint")
    return bool(seen) and seen != brand_fingerprint(brand)


# ----------------------------------------------------------------------------- "don't use", marked later (#43, M3)
WITHDRAWN_TODO = "TODO: ask again (the file this came from is marked \"don't use\")"
# Where a confirmed answer lives in the brand, for taking it out: answer path -> brand path, and how.
REMOVE_LISTS = {("positioning", "contrarian"): ("positioning", "contrarian"), ("positioning", "for"): ("positioning", "for"),
                ("positioning", "against"): ("positioning", "against"),
                ("positioning", "differentiation"): ("positioning", "differentiation"),
                ("positioning", "non_negotiables"): ("positioning", "non_negotiables"),
                ("teach", "myths"): ("myths",), ("teach", "mistakes"): ("mistakes",), ("teach", "steps"): ("steps_to_result",),
                ("audience", "objections"): ("audience", "objections")}
# Lists the brand replaces whole (never merged by id): answer path -> brand path. Taking an item out sends the
# brand the whole list that's left, never a remove marker.
REPLACE_LISTS = {("influences", "items"): ("influences",)}
CLEAR_VALUES = {("what_you_do",): ("business", "what_we_do"), ("audience",): ("audience", "who"),
                ("positioning", "core_belief"): ("positioning", "core_belief"),
                ("positioning", "known_for"): ("positioning", "known_for")}


def _from_source(v, src):
    """True when this answer (or item) came from `src`: its refs, or (an edited quote) where it was derived from."""
    if not isinstance(v, dict):
        return False
    refs = list(v.get("refs") or []) + list((v.get("derived_from") or {}).get("refs") or [])
    return any(isinstance(r, str) and r.split() and r.split()[0] == src for r in refs)


def _set_path(d, path, value):
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def _question_answers(answers, f):
    """The answers (dicts, list items flattened) one page question stores: only that question's own, so a
    question's source never spreads to another question sharing its key (an offer rung, a story kind, proof)."""
    v = answers.get(f["key"])
    if f.get("kind") == "rung":
        parts = [[x for x in v if isinstance(x, dict) and x.get("rung") == f.get("rung")]] if isinstance(v, list) else []
    elif f.get("kind") == "story_card":
        st = v.get("stories") if isinstance(v, dict) else None
        parts = [[x for x in st if isinstance(x, dict) and x.get("kind") == f.get("story_kind")]] if isinstance(st, list) else []
    elif f.get("kind") == "proof":
        parts = [v.get("proof")] if isinstance(v, dict) else []
    elif f.get("own_status"):                       # who inspires you: {status, items}, the rows are the answers
        parts = [v.get(f.get("list") or "items")] if isinstance(v, dict) else []
    elif f["key"] in GROUP_KEYS:
        parts = [v.get(x) for x in field_parts(f)] if isinstance(v, dict) and field_parts(f) else []
    else:
        parts = [v]
    out = []
    for t in parts:
        out.extend(x for x in (t if isinstance(t, list) else [t]) if isinstance(x, dict))
    return out


def withdraw_source(intake, src):
    """Take everything that came from source `src` out of the answers file: waiting drafts, quotes, candidates,
    proposals, provenance and waiting typing go; a confirmed value is cleared (the question is empty again, never
    pre-filled from that file). The supporting excerpts are kept only in intake.restricted, never shown again.
    Returns {"removals": brand update answers, "manual": [plain notes], "places": [answer paths], "texts": [the
    withdrawn words, only for checking the brand files afterwards; never shown]}."""
    answers = intake.setdefault("answers", {})
    restricted = intake.setdefault("restricted", {}).setdefault(src, [])
    out = {"removals": {}, "manual": [], "places": [], "texts": []}

    def note_words(v):
        for k in ("value", "others", "us", "catalyst", "core_truth", "experience", "title", "text", "name", "why"):
            if isinstance(v.get(k), str) and len(v[k].strip()) >= 8:
                out["texts"].append(v[k].strip())
        if isinstance(v.get("excerpt"), str):
            restricted.append(v["excerpt"])

    # A question whose source is recorded only for the whole question (answers.provenance): its drafted answers
    # came from that file too, so they carry its refs into the removal below. Words the owner typed are their own.
    prov = answers.get("provenance")
    if isinstance(prov, dict):
        every = {f["id"]: f for f in fields()["core"] + fields()["deep"] + (fields().get("extra") or [])}
        for fid, p in prov.items():
            f = every.get(fid)
            if not (f and f.get("key") and _from_source(p, src)):
                continue
            for x in _question_answers(answers, f):
                if isinstance(x, dict) and not x.get("refs") and x.get("source") in ("draft", "draft-edited", "quoted"):
                    x["refs"] = list(p.get("refs") or [])
    replaced = set()

    def withdraw_list(path, holder, name, v):
        kept = []
        for x in v:
            if isinstance(x, dict) and _from_source(x, src) and not x.get("remove"):
                note_words(x)
                out["places"].append(".".join(path))
                if (x.get("status") == "confirmed" or x.get("restored")) and x.get("id") and path in REPLACE_LISTS:
                    kept.append({"id": x["id"], "remove": True, "status": "confirmed"})
                    replaced.add(path)
                elif x.get("status") == "confirmed" and x.get("id"):
                    if path in REMOVE_LISTS:
                        bp = REMOVE_LISTS[path]
                        cur = out["removals"]
                        for k in bp[:-1]:
                            cur = cur.setdefault(k, {})
                        cur.setdefault(bp[-1], []).append({"id": x["id"], "remove": True})
                        kept.append({"id": x["id"], "remove": True, "status": "confirmed"})
                    else:
                        out["manual"].append("A confirmed %s came from that file: remove it in the chat." % ".".join(path))
                continue
            kept.append(x)
        holder[name] = kept

    for key in list(answers):
        if key in ("inventory", "provenance"):
            continue
        value = answers[key]
        groups = value.items() if key in GROUP_KEYS and isinstance(value, dict) else [(None, value)]
        for part, v in list(groups):
            path = (key, part) if part else (key,)
            holder_parent = value if part else answers
            name = part if part else key
            if isinstance(v, list):
                withdraw_list(path, holder_parent, name, v)
            elif isinstance(v, dict) and not _from_source(v, src):
                # Lists inside an answer (audience.objections, a group part's rows): each item by its own refs.
                for k, lst in list(v.items()):
                    if isinstance(lst, list) and k != "proof":
                        withdraw_list(path + (k,), v, k, lst)
            elif isinstance(v, dict) and _from_source(v, src):
                note_words(v)
                out["places"].append(".".join(path))
                if v.get("status") == "confirmed":
                    if path in CLEAR_VALUES:
                        bp = CLEAR_VALUES[path]
                        _set_path(out["removals"], bp, {"id": part.replace("_", "-"), "value": WITHDRAWN_TODO}
                                  if key == "positioning" else WITHDRAWN_TODO)
                    else:
                        out["manual"].append("A confirmed answer (%s) came from that file: change it in the chat." % ".".join(path))
                # The question is empty again, but what the owner gave inside it (a list another question asks,
                # such as their objections inside the audience answer) stays, each item by its own source.
                kept = {}
                for k, lst in list(v.items()):
                    if isinstance(lst, list) and k != "proof":
                        withdraw_list(path + (k,), v, k, lst)
                        if any(isinstance(x, dict) and not x.get("remove") for x in v[k]) or any(
                                isinstance(x, dict) and x.get("remove") for x in v[k]):
                            kept[k] = v[k]
                if kept:                                # an empty, unanswered question that still holds them
                    holder_parent[name] = dict(kept, status="unconfirmed", source="typed", origin="person")
                else:
                    del holder_parent[name]
        if key in GROUP_KEYS and isinstance(answers.get(key), dict):
            # story proof and other nested lists inside a group part
            for part, v in list(answers[key].items()):
                if isinstance(v, dict) and isinstance(v.get("proof"), list):
                    keep = []
                    for x in v["proof"]:
                        if isinstance(x, dict) and _from_source(x, src):
                            note_words(x)
                            out["places"].append("%s.%s.proof" % (key, part))
                            if x.get("status") == "confirmed" and x.get("id"):
                                _set_path(out["removals"], ("positioning", "story", "proof"),
                                          ((out["removals"].get("positioning") or {}).get("story") or {}).get("proof", []) +
                                          [{"id": x["id"], "remove": True}])
                            continue
                        keep.append(x)
                    v["proof"] = keep
    prov = answers.get("provenance")
    if isinstance(prov, dict):
        for fid in [f for f, p in prov.items() if _from_source(p, src)]:
            del prov[fid]
    cands = intake.get("candidates") or {}

    def drop_alts(box):
        if isinstance(box, dict) and isinstance(box.get("alternatives"), list):
            box["alternatives"] = [a for a in box["alternatives"]
                                   if not (isinstance(a, dict) and any(_from_source(x, src) for x in
                                           ([a.get("answer")] if isinstance(a.get("answer"), dict) else (a.get("answer") or []))))]
            return bool(box["alternatives"])
        return True
    for key in list(cands):
        box = cands[key]
        if _by_question(key, box):
            for part in list(box):
                if not drop_alts(box[part]):
                    del box[part]
            if not box:
                del cands[key]
        elif not drop_alts(box):
            del cands[key]
    typing = intake.get("typing") or {}
    for fid in list(typing):
        if src in json.dumps(typing[fid]):         # a proposal or an added row from that file: the waiting copy goes
            del typing[fid]
    ideas = answers.get("topic_ideas")
    if isinstance(ideas, list):
        answers["topic_ideas"] = [i for i in ideas if not _from_source(i, src)]
    for path in replaced:                           # what's left of a replaced list goes to the brand whole
        from smf.onboarding_page import to_brand
        holder = answers.get(path[0]) if isinstance(answers.get(path[0]), dict) else {}
        _set_path(out["removals"], REPLACE_LISTS[path], to_brand.surviving_rows(holder.get(path[1]) or []))
    return out


def proof_from_source(brand, src):
    """The proof library items recorded as coming from source `src` (their ids), from _state/proof-provenance.json."""
    try:
        with open(brand.path("_state", "proof-provenance.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return sorted(pid for pid, p in (data.get("items") or {}).items() if _from_source(p, src))


def record_proof(brand, intake_id, proof_id, provenance):
    """After `factory.py proof add`: keep which proof item came from which answer and source, by its library id,
    so a retry never adds it twice and a later "don't use" finds it. Never holds the excerpt."""
    path = brand.path("_state", "proof-provenance.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    items = data.setdefault("items", {})
    clean = {k: provenance[k] for k in ("origin", "refs", "generator") if isinstance(provenance, dict) and k in provenance}
    items[proof_id] = dict(clean, intake_id=intake_id)
    data.setdefault("by_answer", {})[intake_id] = proof_id
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, data)
    return path


def recorded_proof_ids(brand):
    try:
        with open(brand.path("_state", "proof-provenance.json"), "r", encoding="utf-8") as f:
            return dict(json.load(f).get("by_answer") or {})
    except (OSError, ValueError):
        return {}
