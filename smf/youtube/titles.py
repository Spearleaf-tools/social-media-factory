"""titles.py - title patterns as data, the keep-the-keyword rule, and scoring you can see into.

A title is written by a person (with Claude) from a PATTERN: a sentence shape with slots. The
patterns below are shapes only. Every example is invented for the two fictional brands the
Factory ships with, and none is, or is adapted from, a real video's title. A pattern is filled
from the brand's own material; when a slot needs a number and the brand has no real one, the
answer is a different pattern, never a made-up number.

Patterns are grouped by the JOB the title is doing, because the job decides the rules:

    search   someone typed a question. The title carries their words, exactly.
    browse   nobody searched. The title has to open a gap the viewer wants closed.
    proof    the brand's own experience is the reason to click. It needs real evidence.

THE KEEP-THE-KEYWORD RULE
When a video is made to be found for a search phrase, that phrase must survive in the title as
one unbroken run of words. Words may be added before it and after it, capitals and punctuation
around it may change, but it is never reordered, reworded or interrupted, however awkward it
reads. People find the video because of that exact wording; tidying it throws the match away.
`keeps_keyword()` is the single check, and `with_keyword()` can only build titles that pass it.

SCORING
`signals()` returns every measurement and the points it earned, in words. There is no model
call and nothing hidden: length, whether the search phrase is kept and how early it finishes,
whether the title opens a gap, and how specific it is. The score sorts options; it does not
decide. A person picks.

    from smf.youtube import titles
    titles.with_keyword("why is my sourdough dense", tail="3 causes, one fix each")
    titles.signals("Why is my sourdough dense? (3 causes, one fix each)", "why is my sourdough dense")
    problems, warnings = titles.check_title(brand, text, keyword="why is my sourdough dense")
"""
from __future__ import annotations

import re
import time

from smf.studio import grounding
from smf.studio.lint import Rules, lint_caption
from smf.youtube import YouTubeError, as_brand

HARD_LIMIT = 100            # the platform refuses a longer title (as of June 2026)
AIM = 50                    # what shows in full on a phone, give or take
SOFT_LIMIT = 60             # past this the end is cut off almost everywhere
KEYWORD_DONE_BY = 50        # the search phrase should have finished by this character

JOBS = ("search", "browse", "proof")

# ----------------------------------------------------------------------------- the pattern library
# `needs` says what the brand must really have before the pattern may be used:
#   keyword   a search phrase, kept word for word
#   number    a number that traces to the brand's facts, research or linked proof
#   proof     a real case, with permission to talk about it
#   length    the planned running time (the title makes a promise about the video itself)
#   count     the number of parts the video really has
PATTERNS = [
    # ---- search -------------------------------------------------------------------------
    {"id": "question-as-typed", "job": "search", "name": "The question, as typed",
     "template": "{keyword} ({what they get, or who it is for})",
     "needs": ["keyword"],
     "when": "A question people type into search, and the brand can answer it from its own bench.",
     "avoid_when": "The phrase is about someone else's business, or the brand cannot show the answer.",
     "examples": {"bakery": "How do I know when dough has proofed enough? (The poke test, filmed)",
                  "clinic": "Should I run with sore shins? (What I check first)"}},
    {"id": "whole-subject", "job": "search", "name": "The whole subject, in one place",
     "template": "{subject}, from {the first step} to {the last} ({who it is for})",
     "needs": [],
     "when": "A beginner would otherwise stitch the answer together from ten partial videos.",
     "avoid_when": "The video covers one corner of the subject. Promise only what is in it.",
     "examples": {"bakery": "Your first sourdough loaf, from flour to slicing (no mixer needed)",
                  "clinic": "Back from a calf strain, from day one to your first 5K"}},
    {"id": "in-minutes", "job": "search", "name": "The subject, with a clock on it",
     "template": "{subject} in {N} minutes ({who it is for})",
     "needs": ["length"],
     "when": "The subject sounds big and the viewer fears it will take an hour.",
     "avoid_when": "The finished video runs longer than the title says. The check compares them.",
     "examples": {"bakery": "Dough hydration in 6 minutes (for new bakers)",
                  "clinic": "Training load in 7 minutes (for weekend runners)"}},
    {"id": "counted-answer", "job": "search", "name": "The counted answer",
     "template": "The {N} {reasons / checks / signs} behind {the outcome they want, or fear}",
     "needs": ["count"],
     "when": "The honest answer has a small, fixed number of parts. The count becomes the chapters.",
     "avoid_when": "The count was chosen because it sounds good. The video must contain exactly that many.",
     "examples": {"bakery": "The 4 reasons behind a tight crumb",
                  "clinic": "The 3 diary habits behind most sore knees"}},
    {"id": "price-or-time", "job": "search", "name": "What it really costs, or how long it takes",
     "template": "How {much / long} {the thing} really {costs / takes} ({what the figures are based on})",
     "needs": ["number"],
     "when": "People ask the money or time question and get vague answers everywhere else.",
     "avoid_when": "The brand has no real figures on file. Without them this is a guess in a suit.",
     "examples": {"bakery": "How long sourdough really takes (our 18 hour schedule)",
                  "clinic": "How long a calf strain really takes to settle (what I tell runners)"}},
    # ---- browse -------------------------------------------------------------------------
    {"id": "belief-corrected", "job": "browse", "name": "The belief, corrected",
     "template": "Why {common advice} {makes it worse / misses the point} (and what to do instead)",
     "needs": [],
     "when": "The brand sees a popular piece of advice fail, repeatedly, in its own work.",
     "avoid_when": "The correction is a matter of taste, or it attacks a named person or business.",
     "examples": {"bakery": "Why kneading harder makes a worse loaf (and what we do instead)",
                  "clinic": "Why resting a sore shin for a month often brings it back"}},
    {"id": "the-warning", "job": "browse", "name": "The warning",
     "template": "Stop {the habit} before {the cost they already feel}",
     "needs": [],
     "when": "One small habit causes a cost the viewer already recognises.",
     "avoid_when": "The cost is invented or exaggerated. A warning that is not true is bait.",
     "examples": {"bakery": "Stop putting your starter in the fridge before you read this",
                  "clinic": "Stop adding miles the week after a race"}},
    {"id": "plain-outcome", "job": "browse", "name": "The outcome, in the viewer's words",
     "template": "{the result they want}, without {the thing they dread}",
     "needs": [],
     "when": "The subject has a trade name the customer would never say. Lead with what they get.",
     "avoid_when": "The outcome cannot be shown in the video.",
     "examples": {"bakery": "A crisp crust at home, without a special oven",
                  "clinic": "Run three times a week, without the Monday limp"}},
    {"id": "what-changed", "job": "browse", "name": "What changed, explained calmly",
     "template": "{what changed} {where}: what it means for {who}",
     "needs": [],
     "when": "Something in the viewer's world has changed and people are confused or worried.",
     "avoid_when": "The brand has no first-hand view of the change. Reporting rumours is not a video.",
     "examples": {"bakery": "Flour prices went up again: what it means for your weekly loaf",
                  "clinic": "The park path is closed till spring: three flat loops that still work"}},
    {"id": "side-by-side", "job": "browse", "name": "Two things, side by side",
     "template": "{A} vs {B}: {how they are judged}",
     "needs": [],
     "when": "The difference can be SEEN, and the brand can make both versions honestly.",
     "avoid_when": "One side is a named competitor. Compare methods, never businesses.",
     "examples": {"bakery": "Cold oven vs hot oven: same dough, cut open",
                  "clinic": "Treadmill vs pavement: what changes in the same runner"}},
    # ---- proof --------------------------------------------------------------------------
    {"id": "count-of-experience", "job": "proof", "name": "What a count of experience taught",
     "template": "I have {taught / assessed / baked} {N} {things}. {The pattern that surprised me}",
     "needs": ["number"],
     "when": "The brand has really done the thing many times and the count is on file.",
     "avoid_when": "The number is a guess. Round it and it reads as made up; invent it and it is.",
     "examples": {"bakery": "We teach 8 beginners every Saturday. They all make the same first mistake",
                  "clinic": "What a runner's first appointment usually tells me"}},
    {"id": "test-over-time", "job": "proof", "name": "A test, run over time",
     "template": "I {did one thing} for {N days or weeks}. {What you will see}",
     "needs": ["number"],
     "when": "The brand really ran the test and filmed along the way.",
     "avoid_when": "The test was not run. This pattern cannot be written in advance.",
     "examples": {"bakery": "I fed one starter rye and one white for 12 days. Here are both loaves",
                  "clinic": "I filmed one runner's stride every week for 8 weeks"}},
    {"id": "case-story", "job": "proof", "name": "One real case, from before to after",
     "template": "How {someone, described not named} went from {before} to {after}",
     "needs": ["proof"],
     "when": "A proof item is on file, with permission, and every figure in it can be shown.",
     "avoid_when": "There is no permission, or the brand is regulated and the story reads as a promise.",
     "examples": {"bakery": "How one class regular went from bricks to an open crumb",
                  "clinic": "How one runner's week changed before her knee did"}},
    {"id": "looking-back", "job": "proof", "name": "Looking back, what I would do first",
     "template": "What I would {do / buy / skip} first if I were {starting the thing} today",
     "needs": [],
     "when": "The person has years in the work and a clear regret or lesson to share.",
     "avoid_when": "The presenter is new to the work. The pattern borrows authority it needs to have.",
     "examples": {"bakery": "What I would buy last if I were opening a bakery today",
                  "clinic": "What I would do in month one if I took up running at 40"}},
    {"id": "with-what-you-have", "job": "proof", "name": "With what you already have",
     "template": "How to {outcome} with {the thing they think rules them out}",
     "needs": [],
     "when": "The viewer's usual excuse is what they lack. Show the outcome without it.",
     "avoid_when": "The brand cannot actually demonstrate it from that starting point.",
     "examples": {"bakery": "How to bake a good loaf with a cheap oven and no scales",
                  "clinic": "How to start running when a flight of stairs leaves you winded"}},
]

# Short additions in brackets after a search phrase. The phrase does the finding; the addition
# earns the click. An addition is a promise about the video, so it is written last, from the
# script, and the checks compare any count or running time in it with the plan.
TAILS = [
    {"id": "who-for", "template": "for {who}", "example": "for home bakers"},
    {"id": "what-you-get", "template": "{N} {checks / causes / steps}", "example": "3 causes, one fix each"},
    {"id": "how-shown", "template": "{how it is shown}", "example": "filmed at the bench"},
    {"id": "held-back", "template": "and the {one thing} most people skip", "example": "and the step most people skip"},
    {"id": "on-the-clock", "template": "in under {N} minutes", "example": "in under 8 minutes"},
    {"id": "this-year", "template": "{year}", "example": "this year's date, which then has to be kept current"},
]

_BY_ID = {p["id"]: p for p in PATTERNS}


def pattern(pattern_id):
    """One pattern by id, or an error that lists the real ones."""
    if pattern_id in _BY_ID:
        return _BY_ID[pattern_id]
    raise YouTubeError("'%s' is not a title pattern. The patterns are: %s."
                       % (pattern_id, ", ".join(p["id"] for p in PATTERNS)))


def patterns_for(job=None):
    if job is None:
        return list(PATTERNS)
    if job not in JOBS:
        raise YouTubeError("A title's job is one of: %s." % ", ".join(JOBS))
    return [p for p in PATTERNS if p["job"] == job]


# ----------------------------------------------------------------------------- keep the keyword
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACES = re.compile(r"\s+")
_ASKS = re.compile(r"^(what|why|who|when|where|which|can|could|is|are|was|were|do|does|did|should|will|would|"
                   r"how (?:do|does|did|can|could|would|should|is|are|much|long|many|often|far|soon))\b", re.IGNORECASE)


def _plain(text):
    """The form two strings are compared in: lower case, punctuation as spaces, single spaces."""
    return _SPACES.sub(" ", _PUNCT.sub(" ", str(text or "").lower().replace("_", " "))).strip()


def keeps_keyword(title, keyword):
    """(ok, reason). True when the search phrase survives in the title as one unbroken run."""
    t, k = _plain(title), _plain(keyword)
    if not k:
        return False, "no search phrase was given"
    if (" %s " % k) in (" %s " % t):
        return True, "the search phrase is in the title, word for word"
    missing = [w for w in k.split() if w not in t.split()]
    if missing:
        return False, "the title is missing these words from the search phrase: %s" % " ".join(missing)
    return False, "every word is there, but the phrase has been reordered or interrupted"


def with_keyword(keyword, tail=None, limit=HARD_LIMIT):
    """A title made of the search phrase, untouched, plus an optional addition in brackets.

    Only the first letter's capital changes, and a question mark is added when the phrase asks
    something. If the phrase plus the addition is too long, the addition is dropped; the phrase
    itself is never shortened. A phrase longer than a title can be is an error for a person."""
    phrase = _SPACES.sub(" ", str(keyword or "")).strip()
    if not phrase:
        raise YouTubeError("A search phrase is needed to build this kind of title.")
    base = phrase[:1].upper() + phrase[1:]
    base = re.sub(r"(?<![\w'])i(?=$|[\s,.?!]|'(?:m|ve|d|ll)\b)", "I", base)      # capitals may change; words may not
    if _ASKS.match(base) and not base.endswith(("?", "!", ".")):
        base += "?"
    tail = str(tail or "").strip().strip("()").strip()
    title = "%s (%s)" % (base, tail) if tail else base
    if len(title) > limit and tail:
        title = base
    if len(title) > limit:
        raise YouTubeError("The search phrase \"%s\" is %d characters, which is longer than a title can be (%d). "
                           "It cannot be shortened without losing the match, so this one needs a person: choose a "
                           "shorter phrase from the same group." % (phrase, len(base), limit))
    ok, reason = keeps_keyword(title, phrase)
    if not ok:                                  # cannot happen by construction; kept as a guard
        raise YouTubeError("The title would not keep the search phrase (%s)." % reason)
    return title


def keyword_ends_at(title, keyword):
    """The character position in the title where the search phrase finishes, or None."""
    words = _plain(keyword).split()
    if not words:
        return None
    gap = r"[^\w]+"
    m = re.search(r"(?<!\w)" + gap.join(re.escape(w) for w in words) + r"(?!\w)", str(title or "").replace("_", " "),
                  re.IGNORECASE | re.UNICODE)
    return m.end() if m else None


# ----------------------------------------------------------------------------- promises in a title
_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
_MINUTES = re.compile(r"\b(?:in|under|in under|in just)?\s*(\d{1,3})\s*[- ]?\s*min(?:ute)?s?\b", re.IGNORECASE)
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "eleven": 11, "twelve": 12}
_PARTS = re.compile(r"(?<![\w.])(\d{1,2}|%s)\s+(?:\w+\s+){0,2}?(%s)\b"
                    % ("|".join(_NUMBER_WORDS), grounding.STRUCTURAL_NOUNS), re.IGNORECASE)


def year_stamps(title, today=None):
    """Years in a title that are there as a freshness label: last year, this year or next."""
    now = int((today or time.strftime("%Y-%m-%d"))[:4])
    return [int(y) for y in _YEAR.findall(str(title or "")) if now - 1 <= int(y) <= now + 1]


def promised_minutes(title):
    m = _MINUTES.search(str(title or ""))
    return int(m.group(1)) if m else None


def promised_parts(title):
    """The count a title promises ("4 things that ...", "three mistakes"), or None."""
    m = _PARTS.search(str(title or ""))
    if not m:
        return None
    raw = m.group(1).lower()
    return _NUMBER_WORDS.get(raw) or int(raw)


_GLUED_UNIT = re.compile(r"(\d)(?![KkMm](?!\w))(?=[A-Za-z])")


def claims_only(title, today=None):
    """Text made ready for the fact check. Two things happen to a COPY of it.

    Promises about the video itself are taken out: a year used as a label and a running time are
    not facts about the world, and are checked separately, against the calendar and the plan.

    A number glued to its unit is pulled apart ("72h" becomes "72 h", "5kg" becomes "5 kg"),
    because the fact check reads a number only when it stands alone, and a figure on a thumbnail
    or a slide is usually written glued. "4.4K" is left alone: there the letter is part of the
    number."""
    text = str(title or "")
    for y in year_stamps(text, today):
        text = re.sub(r"(?<!\d)%d(?!\d)" % y, "this year", text)
    return _GLUED_UNIT.sub(r"\1 ", _MINUTES.sub(" a few minutes", text))


# ----------------------------------------------------------------------------- signals and score
_GAP_WORDS = re.compile(r"\b(why|what happens|here is|here's|the one|this is|before you|until you|instead|"
                        r"without|the reason|the mistake|the step|most people|nobody|what i|what we)\b", re.IGNORECASE)
_CONTRAST = re.compile(r"\b(vs|versus|but|not|never|stop|instead|without)\b", re.IGNORECASE)
_TIME_SPAN = re.compile(r"\b\d+\s*(?:second|minute|hour|day|week|month|year)s?\b", re.IGNORECASE)
_AUDIENCE = re.compile(r"\b(?:for|if you(?: are|'re)?)\s+(?:a |an |the |your |my )?[a-z][a-z' -]{2,30}", re.IGNORECASE)
_BAIT = re.compile(r"(you won'?t believe|shocking|insane|mind[- ]?blowing|gone wrong|what happened next|"
                   r"this changes everything|secret they)", re.IGNORECASE)
_SHOUT = re.compile(r"\b[A-Z]{3,}\b")


def signals(title, keyword=None, own_names=()):
    """Every measurement behind the score, in plain words. Returns
    {"score": 0-100, "chars": n, "parts": [{"signal", "points", "of", "why"}, ...], "notes": [...]}.

    The weights: length 25, the search phrase 25 (or, with no phrase, shared between the other
    two), a gap worth closing 25, being specific 25. Anything that reads as bait takes points off.
    `own_names` are the brand's own names, which are allowed to be in capitals."""
    text = str(title or "").strip()
    n = len(text)
    parts, notes = [], []

    if n == 0:
        return {"score": 0, "chars": 0, "parts": [], "notes": ["There is no title yet."]}
    if n <= AIM:
        pts, why = 25, "%d characters: it shows in full on a phone" % n
    elif n <= SOFT_LIMIT:
        pts, why = 17, "%d characters: the last few may be cut off on a phone (aim for %d)" % (n, AIM)
    elif n <= 70:
        pts, why = 8, "%d characters: the end will be cut off in most places" % n
    else:
        pts, why = 0, "%d characters: most of the second half will never be seen" % n
    parts.append({"signal": "length", "points": pts, "of": 25, "why": why})

    has_keyword = bool(_plain(keyword))
    if has_keyword:
        ok, reason = keeps_keyword(text, keyword)
        end = keyword_ends_at(text, keyword) if ok else None
        if not ok:
            pts, why = 0, reason
        elif end is not None and end <= KEYWORD_DONE_BY:
            pts, why = 25, "the search phrase is kept word for word and has finished by character %d" % end
        else:
            pts, why = 15, ("the search phrase is kept word for word, but it finishes at character %s, "
                            "past where a phone cuts the title off" % end)
        parts.append({"signal": "search phrase", "points": pts, "of": 25, "why": why})
    share = 25 if has_keyword else 37.5

    gap_bits = []
    if re.search(r"\(.+\)", text):
        gap_bits.append("an addition in brackets")
    if text.rstrip().endswith("?") or _ASKS.match(text):
        gap_bits.append("it asks a question")
    if _GAP_WORDS.search(text):
        gap_bits.append("it points at something held back")
    if _CONTRAST.search(text):
        gap_bits.append("it sets two things against each other")
    pts = min(share, round(share * len(gap_bits) / 2.0, 1))
    parts.append({"signal": "a gap worth closing", "points": pts, "of": share,
                  "why": "; ".join(gap_bits) if gap_bits else "nothing in it makes a viewer want the next sentence"})

    specific = []
    digits = [d for d in re.findall(r"\d+(?:\.\d+)?", claims_only(text)) if d]
    if digits or promised_parts(text):
        specific.append("a number")
        if any(float(d) % 5 for d in digits):
            specific.append("and not a round one")
    if _TIME_SPAN.search(text) or promised_minutes(text):
        specific.append("a span of time")
    if _AUDIENCE.search(text):
        specific.append("it says who it is for")
    pts = min(share, round(share * len(specific) / 2.0, 1))
    parts.append({"signal": "specific", "points": pts, "of": share,
                  "why": ", ".join(specific) if specific else "no number, no time span, nobody named"})

    penalty = 0
    allowed = {w.upper() for name in own_names for w in str(name).split()}
    shouts = [w for w in _SHOUT.findall(text) if w not in allowed]
    if len(shouts) > 1:
        penalty += 10
        notes.append("More than one word is in capitals (%s). One, at most, carries emphasis." % ", ".join(shouts[:4]))
    if text.count("!") > 1 or "?!" in text or "!!" in text:
        penalty += 10
        notes.append("Stacked exclamation marks read as shouting.")
    if _BAIT.search(text):
        penalty += 25
        notes.append("It promises a shock and hides the subject. That attracts the wrong viewers, and the "
                     "platform measures how they feel afterwards.")
    if year_stamps(text):
        notes.append("There is a year in the title. It helps while it is current and ages the video the day it "
                     "is not: put a reminder in the diary to update it.")

    score = max(0, int(round(sum(p["points"] for p in parts) - penalty)))
    return {"score": min(100, score), "chars": n, "parts": parts, "notes": notes, "penalty": penalty}


def explain(sig):
    """The score as lines a person can read."""
    lines = ["Score %d out of 100 (%d characters)." % (sig["score"], sig["chars"])]
    for p in sig["parts"]:
        lines.append("  %-20s %4.1f of %4.1f   %s" % (p["signal"], p["points"], p["of"], p["why"]))
    for note in sig["notes"]:
        lines.append("  note: " + note)
    return "\n".join(lines)


# ----------------------------------------------------------------------------- the brand's checks
# Rules from the caption checker that make sense for a handful of words on a title, a thumbnail,
# a chapter heading or a tag. Sentence and paragraph lengths do not.
SHORT_TEXT_RULES = {"never-mention", "never-publish", "needs-sign-off", "banned-word", "banned-phrase", "em-dash",
                    "overpromise", "negative-parallelism"}


def brand_findings(brand, text, rules=None, keep=SHORT_TEXT_RULES):
    """(problems, warnings) from the brand's own rules: names it never mentions, words it has
    banned, its punctuation rule and its regulated terms."""
    brand = as_brand(brand)
    rules = rules or Rules.for_brand(brand)
    problems, warnings, said = [], [], set()
    for f in lint_caption(str(text or ""), "youtube", rules):
        if f.rule not in keep and f.rule != "char-limit":
            continue
        if (f.rule, f.detail) in said:          # a name is matched in full and by its first word: say it once
            continue
        said.add((f.rule, f.detail))
        line = "%s%s" % (f.detail, (' ("%s")' % f.excerpt) if f.excerpt else "")
        (problems if f.severity == "ERROR" else warnings).append(line)
    return problems, warnings


def check_title(brand, title, keyword=None, proof_ids=(), length_minutes=None, parts_in_video=None, today=None):
    """(problems, warnings) for one title, in plain words. A problem stops the title being
    chosen; a warning is advice.

    Problems: empty or over the platform's limit; the search phrase not kept word for word; a
    number that does not trace to the brand's facts, research or linked proof; a name the brand
    never mentions; a word its rules say must never publish; a running time or a count the
    planned video does not deliver."""
    brand = as_brand(brand)
    text = str(title or "").strip()
    problems, warnings = [], []
    if not text:
        return ["The title is empty."], []
    if "\n" in text:
        problems.append("A title is one line.")
    if len(text) > HARD_LIMIT:
        problems.append("The title is %d characters. YouTube allows %d, and only the first %d or so are seen."
                        % (len(text), HARD_LIMIT, AIM))
    elif len(text) > SOFT_LIMIT:
        warnings.append("The title is %d characters. Past about %d the end is cut off; aim for %d or fewer."
                        % (len(text), SOFT_LIMIT, AIM))

    if _plain(keyword):
        ok, reason = keeps_keyword(text, keyword)
        if not ok:
            problems.append("This video is meant to be found for \"%s\", and the title does not keep that phrase "
                            "word for word: %s. Add words before or after it; never change it."
                            % (str(keyword).strip(), reason))
        else:
            end = keyword_ends_at(text, keyword)
            if end and end > KEYWORD_DONE_BY:
                warnings.append("The search phrase finishes at character %d. Move it to the front so it is seen "
                                "before a phone cuts the title off." % end)

    report = grounding.ground_draft(claims_only(text, today), brand, proof_ids=proof_ids)
    if report["ungrounded"]:
        problems.append("The title states %s, which does not trace to anything in %s's facts, research or linked "
                        "proof. If it is true, record it as a fact with its source first; if it cannot be backed "
                        "up, take it out or choose a pattern that needs no number."
                        % (", ".join(report["ungrounded"]), brand.name))
    if report["unknown_proof_ids"]:
        problems.append("The title links proof that is not in %s's proof library: %s."
                        % (brand.name, ", ".join(report["unknown_proof_ids"])))
    warnings.extend(report["hints"])

    more_problems, more_warnings = brand_findings(brand, text)
    problems.extend(more_problems)
    warnings.extend(more_warnings)

    minutes = promised_minutes(text)
    if minutes is not None:
        if length_minutes is None:
            warnings.append("The title promises %d minutes. Set the planned length so that promise can be checked."
                            % minutes)
        elif float(length_minutes) > minutes:
            problems.append("The title promises %d minutes and the plan is %s. Change one of them: a viewer who "
                            "was promised a short video and got a long one does not stay." % (minutes, length_minutes))
    parts = promised_parts(text)
    if parts is not None:
        if parts_in_video is None:
            warnings.append("The title promises %d parts. Write the structure so that count can be checked." % parts)
        elif int(parts_in_video) != parts:
            problems.append("The title promises %d and the structure has %d counted parts. The count in a title is "
                            "a promise: fix the structure or fix the title." % (parts, int(parts_in_video)))
    for note in signals(text, keyword, own_names=brand.data.get("own_brands") or [])["notes"]:
        if note not in warnings:
            warnings.append(note)
    return problems, warnings
