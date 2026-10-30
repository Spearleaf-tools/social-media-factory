"""questions.py - keyword exports in; out comes a short list of videos a person has ruled on.

A keyword tool (any of them) will export thousands of phrases people search for. Most are the
same few questions asked in different words, some are junk, and a handful are worth a video.
This turns the exports a person supplies into a slate they can rule on in one sitting.

    exports (CSV)  ->  ingest  ->  triage  ->  group into videos  ->  score and tier
                   ->  review sheet (a person approves, parks, splits)  ->  apply  ->  briefs

TWO LAWS
1. The keyword string is never edited. It is carried, character for character, from the export
   to the title (see `titles.keeps_keyword`). People find a video because of that exact wording,
   awkwardness included. Everything done to the text here (lower-casing, dropping small words,
   folding "delete" into "remove") happens to a COPY, and only to decide which phrases belong
   together. A phrase that is too broken to say aloud gets a repaired SPOKEN version beside it;
   the written one stays as it was.
2. Group by what is being asked, not by how it is worded. Two phrases are one video when the
   same person wants the same answer. "how to store sourdough" and "best way to keep sourdough
   bread" are one video, and it answers both. The grouping errs on the side of keeping phrases
   apart: it joins only those that come down to exactly the same kind of question about exactly
   the same set of meaningful words. Joining too much is the expensive mistake, because a day is
   spent filming one video that should have been two. Joining too little is cheap: the review
   sheet lists near-matches, and a person joins them with a note.

TIERS (what to do with each group)
    film     real demand, and video already shows on the results page (or demand large enough to
             film anyway). A proper long video.
    batch    real demand, thinner signal. Record several in one sitting, short and plain.
    text     almost no demand. Never filmed: answer it in writing, in descriptions and on the
             website. Cheap coverage that search and AI answer tools still read.
    parked   every phrase in the group tripped the same flag. Nothing is ever deleted: parked
             groups stay on the sheet with the reason showing. Approving one overrules a soft flag
             (off-topic, harmful, cut off, too thin). The brand's own rules are not overruled by a
             click: a name it never mentions and a term it must never publish stay parked, and the
             title check would refuse them anyway.

FLAGS
    off_topic            a word the brand listed as not its subject (same spelling, other meaning)
    names_someone_else   the phrase names a business on the brand's never-mention list, or a website
    never_publish        it contains a term the brand's rules say must never publish
    harmful              the searcher wants to deceive or hurt someone. "how to spot a fake" is a
                         good video; "how to make a fake" is not, so the test reads the verb
    cut_off              a broken string ("what does proofing"). It keeps its demand, so it stays,
                         with a repaired spoken version
    too_thin             nothing is left once the small words go

A brand tunes this with an optional file, Strategy/youtube-questions/settings.json:
    {"same_meaning": [["starter", "levain"]], "off_topic": ["minecraft"],
     "tiers": {"film": 100, "batch": 20}, "split_min_volume": 250}

Standard library only. No network. Enrichment from a results-page check is optional, reads a
run that the research tools already saved, and is looked for only when it is asked for.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import unicodedata

from smf.studio.files import read_json, relative, write_json
from smf.youtube import YouTubeError, as_brand, slugify, write_text
from smf.youtube import titles as T

QUESTIONS_DIR = ("Strategy", "youtube-questions")
CORPUS_NAME = "questions.json"
REVIEW_NAME = "review.html"
SLATE_NAME = "slate.md"
SETTINGS_NAME = "settings.json"

TIERS = ("film", "batch", "text", "parked")
DECISIONS = ("approve", "edit", "park")
DEFAULT_TIERS = {"film": 100, "batch": 20}
SPLIT_MIN_VOLUME = 250
SPLIT_RATIO = 0.40              # a second phrase this close to the first probably deserves its own video
MERGE_MIN_OVERLAP = 0.60        # for the "these two may be one video" suggestions (two words of three)
# Flags a person can overrule by approving the group. The other two are the brand's own rules
# (a name it never mentions, a term it must never publish): those stay parked whatever is clicked.
SOFT_FLAGS = ("off_topic", "harmful", "cut_off", "too_thin")

# ----------------------------------------------------------------------------- reading exports
_COLUMN_WORDS = {
    "keyword": ("keyword", "query", "search term", "phrase", "question"),
    "volume": ("volume", "searches", "avg. monthly", "avg monthly", "search vol"),
    "difficulty": ("difficulty", "kd", "competition"),
    "cpc": ("cpc", "cost per click", "bid"),
    "intent": ("intent",),
    "features": ("serp", "feature", "result type", "results page"),
}
_LEVEL_WORDS = {"low": 25, "medium": 50, "med": 50, "high": 75}


def _read_table(path):
    """Rows of a CSV or tab-separated export. Spreadsheets are saved in several encodings, so the
    common ones are tried in turn rather than failing on the first odd byte."""
    raw = None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        raise YouTubeError("The keyword file '%s' could not be found or opened." % os.path.basename(str(path)))
    text = None
    for enc in (("utf-16",) if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ()) + ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    first = text.splitlines()[0] if text.splitlines() else ""
    delimiter = max(",;\t", key=first.count) if first else ","
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))


def _columns(header):
    found = {}
    for i, heading in enumerate(header):
        h = re.sub(r"\s+", " ", str(heading).strip().lower())
        for name, words in _COLUMN_WORDS.items():
            if name not in found and any(w in h for w in words):
                if name == "keyword" and any(w in h for w in ("difficulty", "volume")):
                    continue                     # "keyword difficulty" is not the keyword
                found[name] = i
                break
    return found


def _number(text):
    """(value, estimated). Understands 1,300 and 1.3K, and takes the low end of a range."""
    s = str(text or "").strip().lower().replace(",", "")
    if not s:
        return 0.0, False
    estimated = False
    m = re.match(r"^<?\s*(\d+(?:\.\d+)?)\s*([km])?\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*([km])?$", s)
    if m:
        s, estimated = m.group(1) + (m.group(2) or ""), True
    m = re.match(r"^[<>~]?\s*(\d+(?:\.\d+)?)\s*([km])?", s)
    if not m:
        return 0.0, False
    value = float(m.group(1)) * {"k": 1000.0, "m": 1000000.0}.get(m.group(2) or "", 1.0)
    return value, estimated or s[:1] in "<>~"


def read_keywords(path):
    """One export -> rows. Columns are found by what their headings mean, so any tool's file works.

        keyword (exactly as exported), volume, difficulty 0-100, cpc, intent, features [],
        features_known, volume_estimated, source (the file's name)"""
    table = [r for r in _read_table(path) if any(str(c).strip() for c in r)]
    if len(table) < 2:
        raise YouTubeError("The keyword file '%s' has no rows in it." % os.path.basename(str(path)))
    col = _columns(table[0])
    if "keyword" not in col:
        raise YouTubeError("The keyword file '%s' has no column that looks like the keyword (a heading with "
                           "'keyword', 'query' or 'search term' in it). Its headings are: %s."
                           % (os.path.basename(str(path)), ", ".join(str(h) for h in table[0])))

    def cell(row, name):
        i = col.get(name)
        return str(row[i]) if i is not None and i < len(row) else ""

    rows = []
    for r in table[1:]:
        keyword = cell(r, "keyword").strip()
        if not keyword:
            continue
        volume, estimated = _number(cell(r, "volume"))
        level = cell(r, "difficulty").strip().lower()
        if level in _LEVEL_WORDS:
            difficulty = float(_LEVEL_WORDS[level])
        else:
            difficulty, _e = _number(level)
            if 0 < difficulty <= 1:
                difficulty *= 100.0
        features_raw = cell(r, "features").strip()
        rows.append({"keyword": keyword, "volume": int(round(volume)), "difficulty": int(round(min(100.0, difficulty))),
                     "cpc": _number(cell(r, "cpc"))[0], "intent": cell(r, "intent").strip(),
                     "features": [f.strip() for f in re.split(r"[,;|]", features_raw) if f.strip()],
                     "features_known": bool(features_raw), "volume_estimated": estimated,
                     "source": os.path.basename(str(path))})
    return rows


def ingest(paths):
    """Every export, merged. The same phrase in two files is kept once: the row that knows what
    the results page shows wins, then the one with the higher volume."""
    merged, per_file = {}, []
    for path in paths:
        rows = read_keywords(path)
        per_file.append({"file": os.path.basename(str(path)), "rows": len(rows)})
        for row in rows:
            key = row["keyword"].lower()
            old = merged.get(key)
            if old is None:
                merged[key] = row
            elif (row["features_known"], row["volume"]) > (old["features_known"], old["volume"]):
                row["also_in"] = sorted(set(old.get("also_in", []) + [old["source"]]))
                merged[key] = row
            else:
                old["also_in"] = sorted(set(old.get("also_in", []) + [row["source"]]))
    return [merged[k] for k in sorted(merged)], per_file


# ----------------------------------------------------------------------------- what is being asked
# Longest and most specific first: "how much" has to win over "how".
FAMILIES = [
    (r"^what (?:does|do) .+ mean\b", "meaning"), (r"^(?:define|definition of|meaning of)\b", "meaning"),
    (r"^what(?:s| is| are| was| were)\b", "meaning"), (r"^what does\b", "meaning"),
    (r"^how much\b", "cost"), (r"^what(?:s| is| are) the (?:cost|price|fee)", "cost"), (r"^(?:cost|price) of\b", "cost"),
    (r"^how long\b", "time"), (r"^how (?:often|soon|frequently)\b", "time"), (r"^when\b", "time"),
    (r"^how many\b", "count"),
    (r"^how (?:to|do|does|can|could|would|should|did|i)\b", "how"), (r"^how\b", "how"),
    (r"^(?:steps|ways|best way|easiest way) to\b", "how"), (r"^can (?:i|you|we|a|an|the)\b", "how"),
    (r"^should (?:i|you|we)\b", "how"), (r"^do (?:i|you|we) (?:need|have) to\b", "how"),
    (r"^why\b", "why"), (r"^who\b", "who"), (r"^where\b", "where"),
    (r"^which\b", "which"), (r"^(?:what|which)(?:s| is| are) the best\b", "which"), (r"^best\b", "which"),
    (r"^(?:is|are|was|were|does|do|did|will|would|has|have)\b", "yes-or-no"),
]

# General English only. Anything about ONE trade (a bakery's "levain" and "starter") belongs in
# the brand's own settings file, never here.
PHRASES = [
    (r"\bget(?:ting)? rid of\b", " remove "), (r"\btake (?:off|out|away)\b", " remove "),
    (r"\bset(?:ting)? up\b", " start "), (r"\bhow come\b", " why "), (r"\blook(?:ing)? after\b", " keep "),
    (r"\bfind out\b", " check "), (r"\btell if\b", " check "), (r"\bknow (?:if|when|whether)\b", " check "),
]
VERBS = {
    "remove": ("remove", "delete", "erase", "eliminate", "clear"),
    "fix": ("fix", "repair", "mend", "restore", "rescue", "treat", "heal", "solve"),
    "make": ("make", "create", "build", "prepare", "produce"),
    "start": ("start", "begin", "launch", "open"),
    "choose": ("choose", "pick", "select", "decide"),
    "keep": ("keep", "store", "preserve", "maintain"),
    "stop": ("stop", "prevent", "avoid"),
    "improve": ("improve", "boost", "increase", "raise", "strengthen", "better"),
    "reduce": ("reduce", "lower", "decrease", "lessen", "ease", "relieve"),
    "check": ("check", "test", "measure", "tell"),
    "use": ("use", "apply"),
    "find": ("find", "locate"),
}
_VERB_OF = {word: family for family, words in VERBS.items() for word in words}

SMALL_WORDS = set("""a about all am an and any anyone are as at be been being best but by can could d did do does doing done
down easily easy for from get getting go going good got guide had has have having he help her here him his
how i if in into is it its just ll m many may me might more most much must my myself need no not of off on
onto or our out over own people person quick quickly re really s shall she should so some someone step
steps t than that the their them then there these they this those tip tips to too up us ve very want was
way ways we were what whats when where which who whose why will with would you your yourself""".split())
_KEEP_S = {"is", "as", "us", "this", "its", "does", "was", "has", "class", "process", "glass", "business", "stress",
           "loss", "less", "yes", "analysis", "basis"}

_NOT_WORD = re.compile(r"[^a-z0-9\s]+")
_SPACES = re.compile(r"\s+")
_YEAR = re.compile(r"^(?:19|20)\d\d$")


def plain(text):
    """Lower case, accents flattened, punctuation as spaces. Used only for comparing."""
    flat = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return _SPACES.sub(" ", _NOT_WORD.sub(" ", flat.lower().replace("'", ""))).strip()


def family_of(text):
    t = plain(text)
    for pattern, name in FAMILIES:
        if re.search(pattern, t):
            return name
    return "other"


def _singular(word):
    if word in _KEEP_S or len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _verb(word):
    if word in _VERB_OF:
        return _VERB_OF[word]
    stems = []
    if word.endswith("ing") and len(word) > 5:
        base = word[:-3]
        stems += [base, base + "e"] + ([base[:-1]] if len(base) > 2 and base[-1] == base[-2] else [])
    if word.endswith("ed") and len(word) > 4:
        base = word[:-2]
        stems += [base, word[:-1]] + ([base[:-1]] if len(base) > 2 and base[-1] == base[-2] else [])
    return next((_VERB_OF[s] for s in stems if s in _VERB_OF), word)


def _same_meaning(settings):
    """[(pattern, replacement)] from the brand's own groups of words that mean one thing."""
    out = []
    for group in settings.get("same_meaning") or []:
        words = [plain(w) for w in group if plain(w)]
        if len(words) < 2:
            continue
        target = words[0].replace(" ", "")
        for w in sorted(words, key=len, reverse=True):
            out.append((r"(?<![a-z0-9])%s(?:e?s)?(?![a-z0-9])" % re.escape(w), " %s " % target))
    return out


def meaningful_words(text, settings=None, fold=True):
    """The words of a phrase that carry its meaning, small words dropped. `fold=False` leaves
    synonyms unfolded, for when the question is how MUCH is being asked rather than what."""
    t = plain(text)
    if fold:
        for pattern, repl in PHRASES + _same_meaning(settings or {}):
            t = re.sub(pattern, repl, t)
    out = []
    for word in t.split():
        if word in SMALL_WORDS or _YEAR.match(word):
            continue
        word = _verb(_singular(word)) if fold else _singular(word)
        if word and word not in SMALL_WORDS:
            out.append(word)
    return out


def group_key(text, settings=None):
    """(family, the set of meaningful words). A set, because word order is a choice of phrasing,
    not a different question."""
    words = frozenset(meaningful_words(text, settings))
    fam = family_of(text)
    if not words:
        return "%s:=%s" % (fam, plain(text))           # nothing to group on: it stays on its own
    return "%s:%s" % (fam, "+".join(sorted(words)))


# ----------------------------------------------------------------------------- triage
_DANGLING = set("""a about an and are as at be been but by can did do does for from has have how i if in into is it
its my of on or our so than that the their then to was we were what when which who why will with
you your""".split())
_CUT_OFF = [r"^what (?:does|do) (?:\w+ ){0,2}\w+$", r"^how (?:does|do) (?:\w+ ){0,2}\w+$",
            r"^(?:what|how|why|who|when|where|which)$"]
_COMPLETE_ENDINGS = re.compile(r"\b(?:mean|means|meaning|work|works|cost|costs|do|matter|matters|help|helps|last|"
                               r"lasts|take|takes|look like|taste like|feel like)$")
_HARM = [r"\b(?:how to|how do i|how can i|ways to|best way to)\b.*\b(?:fake|forge|counterfeit|sabotage|ruin|destroy)\b",
         r"\b(?:make|write|buy|get|create|post)\b.*\bfake\b", r"\bwithout (?:paying|a licen[cs]e|getting caught)\b",
         r"\bhow to hack\b", r"\bget revenge\b", r"\brevenge on\b", r"\bblackmail\b", r"\bcheat (?:on|at|the)\b"]
_PROTECTIVE = re.compile(r"\b(?:spot|detect|identify|recogni[sz]e|report|avoid|protect|against|prevent|stop|"
                         r"tell if|know if|deal with|respond to|is it (?:legal|illegal)|penalt|law)\b")
_WEBSITE = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org|io|co|uk|us|ca|au|de|fr|biz|info|app)\b")


def triage(keyword, brand, settings=None):
    """(flags, notes) for one phrase. Flags are reasons not to make the video; notes are not."""
    settings = settings or {}
    text = plain(keyword)
    flags, notes = [], []
    for word in settings.get("off_topic") or []:
        if plain(word) and re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(plain(word)), text):
            flags.append("off_topic")
            break
    names = [plain(n) for n in (brand.data.get("never_mention") or []) if plain(n)]
    if any(re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(n), text) for n in names) or _WEBSITE.search(str(keyword).lower()):
        flags.append("names_someone_else")
    compliance = brand.data.get("compliance") or {}
    if any(plain(term) and plain(term) in text for term in compliance.get("drop_terms") or []):
        flags.append("never_publish")
    if any(plain(term) and plain(term) in text for term in compliance.get("hold_terms") or []):
        notes.append("needs_sign_off")
    if any(re.search(p, text) for p in _HARM) and not _PROTECTIVE.search(text):
        flags.append("harmful")
    words = text.split()
    if words and (any(re.search(p, text) for p in _CUT_OFF) or words[-1] in _DANGLING) \
            and not _COMPLETE_ENDINGS.search(text):
        flags.append("cut_off")
    if not meaningful_words(keyword, settings, fold=False):
        flags.append("too_thin")
    return flags, notes


FLAG_WORDS = {
    "off_topic": "not this brand's subject", "names_someone_else": "names another business or a website",
    "never_publish": "contains a term this brand must never publish", "harmful": "the searcher wants to deceive or harm",
    "cut_off": "a broken phrase (kept as written; say the repaired version)", "too_thin": "too little to go on",
    "needs_sign_off": "needs the brand's disclaimer and a named sign-off",
}

_REPAIRS = [(r"^(what (?:does|do) [\w\s]+?)$", r"\1 mean"), (r"^(how (?:does|do) [\w\s]+?)$", r"\1 work"),
            (r"^(.+?)\s+(?:of|for|to|in|on|with|from|by|at|that|and|or|is|are|do|does|the|a|an)$", r"\1")]


def speakable(keyword, flags=()):
    """(what to say aloud, was it repaired, does a person need to fix it).

    The written phrase is never touched. This is only the sentence a presenter can say."""
    text = _SPACES.sub(" ", str(keyword or "")).strip()
    low = text.lower()
    repaired = False
    if "cut_off" in flags:
        for pattern, repl in _REPAIRS:
            if re.match(pattern, low):
                fixed = _SPACES.sub(" ", re.sub(pattern, repl, low)).strip()
                if fixed and fixed != low:
                    text, repaired = fixed, True
                    break
    said = text[:1].upper() + text[1:]
    if T._ASKS.match(said) and not said.endswith(("?", ".", "!")):
        said += "?"
    return said, repaired, ("cut_off" in flags and not repaired)


# ----------------------------------------------------------------------------- grouping
def group(rows, settings=None):
    """Rows (already triaged) -> groups, one per video. Deterministic: the same input always gives
    the same groups, the same heads and the same order."""
    settings = settings or {}
    split_min = int(settings.get("split_min_volume") or SPLIT_MIN_VOLUME)
    buckets = {}
    for row in rows:
        buckets.setdefault(group_key(row["keyword"], settings), []).append(row)
    groups = []
    for key in sorted(buckets):
        members = sorted(buckets[key], key=lambda r: (-r["volume"], not r["features_known"], len(r["keyword"]), r["keyword"]))
        head = members[0]
        if head["flags"]:                           # a flagged phrase never leads when a clean one can
            clean = [m for m in members if not m["flags"]]
            if clean:
                head = clean[0]
                members = [head] + [m for m in members if m is not head]
        all_flags = sorted({f for m in members for f in m["flags"]})
        blocking = sorted(f for f in all_flags if all(f in m["flags"] for m in members))
        second = members[1] if len(members) > 1 else None
        features = sorted({f for m in members for f in m["features"]})
        groups.append({
            "key": key, "family": key.split(":", 1)[0], "head": head["keyword"], "head_volume": head["volume"],
            "head_difficulty": head["difficulty"], "head_flags": list(head["flags"]),
            "volume": sum(m["volume"] for m in members), "features": features,
            "features_known": any(m["features_known"] for m in members),
            "intent": next((m["intent"] for m in members if m["intent"]), ""),
            "volume_estimated": all(m["volume_estimated"] for m in members),
            "flags": all_flags, "blocking_flags": blocking, "notes": sorted({n for m in members for n in m["notes"]}),
            "split_candidate": bool(second and head["volume"] and second["volume"] >= split_min
                                    and second["volume"] >= head["volume"] * SPLIT_RATIO),
            "members": [{"keyword": m["keyword"], "volume": m["volume"], "difficulty": m["difficulty"],
                         "features": m["features"], "features_known": m["features_known"], "flags": m["flags"],
                         "notes": m["notes"], "intent": m["intent"], "volume_estimated": m["volume_estimated"],
                         "source": m["source"]} for m in members],
            "decision": "", "note": "", "video_id": ""})
    return groups


def possible_merges(groups, limit=100):
    """Pairs of groups in the same family that share most of their words: a suggestion only."""
    by_word = {}
    words_of = [set(g["key"].split(":", 1)[1].split("+")) if ":=" not in g["key"] else set() for g in groups]
    for i, g in enumerate(groups):
        for w in words_of[i]:
            by_word.setdefault((g["family"], w), []).append(i)
    seen, pairs = set(), []
    for idxs in by_word.values():
        if len(idxs) > 300:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                union = words_of[i] | words_of[j]
                overlap = len(words_of[i] & words_of[j]) / float(len(union)) if union else 0.0
                if overlap >= MERGE_MIN_OVERLAP:
                    pairs.append({"a": groups[i]["head"], "b": groups[j]["head"], "overlap": round(overlap, 2),
                                  "volume": groups[i]["volume"] + groups[j]["volume"]})
    pairs.sort(key=lambda p: (-p["volume"], p["a"], p["b"]))
    return pairs[:limit]


# ----------------------------------------------------------------------------- score and tier
def video_weight(features):
    """How strongly the results page already says "video belongs here". The strongest signal wins."""
    best = 1.0
    for f in features or []:
        low = f.lower()
        if "video" not in low:
            continue
        best = max(best, 2.0 if "short" in low else 1.6 if ("carousel" in low or "videos" in low) else 1.3)
    return best


def score(g):
    """Demand, weighted by whether a video can win the spot. Every factor is a plain multiplier:

        a video already on the results page   x1.3 to x2.0 (short videos strongest)
        an AI answer on the page              x1.15 (being quoted is possible)
        "people also ask" on the page         x1.10 (it really is asked as a question)
        a buying intent                       x1.20
        difficulty                            down by at most a quarter (it matters less for a
                                              video spot than for a web page)
        volume that was only a range          x0.75"""
    mult = video_weight(g["features"])
    low = " | ".join(g["features"]).lower()
    if "ai " in (low + " ") and ("overview" in low or "answer" in low):
        mult *= 1.15
    if "people also ask" in low or "related questions" in low:
        mult *= 1.10
    if any(w in (g.get("intent") or "").lower() for w in ("commercial", "transactional", "buy")):
        mult *= 1.20
    if g.get("volume_estimated"):
        mult *= 0.75
    return round(g["volume"] * mult * (1.0 - (g.get("head_difficulty") or 0) / 100.0 * 0.25), 1)


def tier_of(g, settings=None):
    limits = dict(DEFAULT_TIERS)
    limits.update({k: v for k, v in ((settings or {}).get("tiers") or {}).items() if k in DEFAULT_TIERS})
    overruled = g.get("decision") == "approve" and all(f in SOFT_FLAGS for f in g["blocking_flags"])
    if g["blocking_flags"] and not overruled:
        return "parked"
    has_video = video_weight(g["features"]) > 1.0
    if g["volume"] >= limits["film"] and has_video:
        return "film"
    if g["volume"] >= limits["film"] * 2:
        return "film"                               # big enough to film even with no video showing yet
    if g["volume"] >= limits["batch"]:
        return "batch"
    return "text"


def rank(groups, settings=None):
    for g in groups:
        g["score"] = score(g)
        g["tier"] = tier_of(g, settings)
        g["video_on_results_page"] = video_weight(g["features"]) > 1.0
        said, repaired, needs_person = speakable(g["head"], g["head_flags"])
        g["say"] = said
        g["say_was_repaired"] = repaired
        g["say_needs_a_person"] = needs_person
        try:
            g["title"] = T.with_keyword(g["head"])
        except YouTubeError:
            g["title"] = ""
    # What can be made comes first; parked groups follow, each part in order of score.
    groups.sort(key=lambda g: (g["tier"] == "parked", -g["score"], -g["volume"], g["head"].lower(), g["key"]))
    for i, g in enumerate(groups, 1):
        g["rank"] = i
    return groups


def summarise(groups):
    out = {"groups": len(groups), "keywords": sum(len(g["members"]) for g in groups),
           "tiers": {t: 0 for t in TIERS}, "volume": sum(g["volume"] for g in groups),
           "video_on_results_page": sum(1 for g in groups if g.get("video_on_results_page")),
           "split_candidates": sum(1 for g in groups if g.get("split_candidate")),
           "decided": sum(1 for g in groups if g.get("decision")),
           "results_page_known": any(g.get("features_known") for g in groups)}
    for g in groups:
        out["tiers"][g["tier"]] += 1
    return out


# ----------------------------------------------------------------------------- files
def folder(brand):
    return as_brand(brand).path(*QUESTIONS_DIR)


def load_settings(brand):
    path = os.path.join(folder(brand), SETTINGS_NAME)
    if not os.path.isfile(path):
        return {}
    data = read_json(path, "%s's question settings" % brand.name)
    if not isinstance(data, dict):
        raise YouTubeError("%s's question settings are not in the expected shape. Ask Claude to repair the file." % brand.name)
    return data


def load(brand):
    brand = as_brand(brand)
    path = os.path.join(folder(brand), CORPUS_NAME)
    if not os.path.isfile(path):
        raise YouTubeError("%s has no question slate yet. Give Claude a keyword export to start one." % brand.name)
    data = read_json(path, "%s's question slate" % brand.name)
    if not isinstance(data, dict) or data.get("brand") != brand.id:
        raise YouTubeError("That question slate belongs to '%s', not to %s. It was not opened."
                           % ((data or {}).get("brand") if isinstance(data, dict) else "nobody", brand.name))
    return data


def _save(brand, corpus):
    corpus["summary"] = summarise(corpus["groups"])
    home = folder(brand)
    write_json(os.path.join(home, CORPUS_NAME), corpus)
    write_text(os.path.join(home, REVIEW_NAME), review_html(brand, corpus))
    write_text(os.path.join(home, SLATE_NAME), slate_md(brand, corpus))
    return corpus


def build(brand, paths, today=None):
    """Exports in, slate out. Writes questions.json, review.html and slate.md into the brand's
    strategy folder. Decisions already made on an earlier slate are carried over by group."""
    brand = as_brand(brand)
    paths = [str(p) for p in (paths or [])]
    if not paths:
        raise YouTubeError("Give at least one keyword export (a CSV file saved from any keyword tool).")
    settings = load_settings(brand)
    rows, per_file = ingest(paths)
    if not rows:
        raise YouTubeError("Those files held no keywords.")
    for row in rows:
        row["flags"], row["notes"] = triage(row["keyword"], brand, settings)
    groups = rank(group(rows, settings), settings)
    earlier = {}
    try:
        earlier = {g["key"]: g for g in load(brand)["groups"]}
    except YouTubeError:
        pass
    for g in groups:
        old = earlier.get(g["key"])
        if old:
            g["decision"], g["note"], g["video_id"] = old.get("decision", ""), old.get("note", ""), old.get("video_id", "")
    corpus = {"brand": brand.id, "made": today or time.strftime("%Y-%m-%d"), "files": per_file,
              "settings_used": settings, "groups": groups, "possible_merges": possible_merges(groups)}
    return _save(brand, corpus)


# ----------------------------------------------------------------------------- decisions
def apply_decisions(brand, decisions):
    """Apply a person's rulings from the review sheet. `decisions` is the exported file's content
    (or its path). Returns counts. A file exported for a different brand is refused."""
    brand = as_brand(brand)
    if isinstance(decisions, (str, os.PathLike)):
        decisions = read_json(str(decisions), "The decisions file")
    if not isinstance(decisions, dict) or not isinstance(decisions.get("decisions"), dict):
        raise YouTubeError("That is not a decisions file from the review sheet.")
    if decisions.get("brand") != brand.id:
        raise YouTubeError("Those decisions were made for '%s', not for %s. Nothing was applied."
                           % (decisions.get("brand"), brand.name))
    corpus = load(brand)
    settings = corpus.get("settings_used") or {}
    by_key = {g["key"]: g for g in corpus["groups"]}
    counts = {"approve": 0, "edit": 0, "park": 0, "split": 0, "unknown": 0}
    for key in sorted(decisions["decisions"]):
        ruling = decisions["decisions"][key] or {}
        g = by_key.get(key)
        if g is None:
            counts["unknown"] += 1
            continue
        verdict = ruling.get("decision") or ""
        if verdict:
            if verdict not in DECISIONS:
                raise YouTubeError("'%s' is not a decision. A group is approved, marked for an edit, or parked." % verdict)
            g["decision"] = verdict
            counts[verdict] += 1
        if str(ruling.get("note") or "").strip():
            g["note"] = str(ruling["note"]).strip()
        for kw in ruling.get("splits") or []:
            member = next((m for m in g["members"] if m["keyword"] == kw), None)
            if member is None or kw == g["head"]:
                continue                               # already split out, or it is the head
            g["members"] = [m for m in g["members"] if m["keyword"] != kw]
            g["volume"] = max(0, g["volume"] - member["volume"])
            g["features"] = sorted({f for m in g["members"] for f in m["features"]})
            new_key = "%s|own:%s" % (key, slugify(kw, "phrase", 40))
            fresh = {"key": new_key, "family": g["family"], "head": kw, "head_volume": member["volume"],
                     "head_difficulty": member["difficulty"], "head_flags": list(member["flags"]),
                     "volume": member["volume"], "features": list(member["features"]),
                     "features_known": member["features_known"], "intent": member.get("intent", ""),
                     "volume_estimated": member.get("volume_estimated", False), "flags": list(member["flags"]),
                     "blocking_flags": list(member["flags"]), "notes": list(member["notes"]), "split_candidate": False,
                     "members": [member], "decision": verdict or "approve", "note": "", "video_id": "",
                     "split_from": g["head"]}
            corpus["groups"].append(fresh)
            by_key[new_key] = fresh
            counts["split"] += 1
    rank(corpus["groups"], settings)
    corpus["decisions_applied"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save(brand, corpus)
    counts["undecided"] = sum(1 for g in corpus["groups"] if not g.get("decision"))
    return counts


def make_briefs(brand, tier="film", identity=None, approved_only=True, limit=None, today=None):
    """Start a video folder for each approved group in a tier. A group that already has a video
    is skipped, so this is safe to run again. Returns (made, skipped-with-reasons)."""
    from smf.youtube import video as V                   # late, to keep this module light to import

    brand = as_brand(brand)
    if tier not in ("film", "batch"):
        raise YouTubeError("Videos are made from the 'film' and 'batch' tiers. The 'text' tier is answered in "
                           "writing, and 'parked' groups are waiting for a person to overrule their flag.")
    corpus = load(brand)
    made, skipped = [], []
    for g in corpus["groups"]:
        if g["tier"] != tier or g.get("video_id"):
            continue
        if approved_only and g.get("decision") != "approve":
            continue
        if limit is not None and len(made) >= int(limit):
            break
        others = [speakable(m["keyword"], m["flags"])[0] for m in g["members"][1:] if not m["flags"]]
        try:
            brief = V.new_video(brand, topic=g["say"], keyword=g["head"], identity=identity, today=today,
                                source_ref="%s/%s#%s" % ("/".join(QUESTIONS_DIR), CORPUS_NAME, g["key"]),
                                also_answers=others)
        except YouTubeError as e:
            skipped.append({"head": g["head"], "why": str(e)})
            continue
        try:
            V.add_title(brand, brief, T.with_keyword(g["head"]), "question-as-typed")
        except YouTubeError as e:
            brief.setdefault("history", []).append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "idea",
                                                    "note": "The plain title was not added: %s" % e})
        V.save(brand, brief)
        g["video_id"] = brief["video_id"]
        made.append({"head": g["head"], "video_id": brief["video_id"]})
    _save(brand, corpus)
    return made, skipped


# ----------------------------------------------------------------------------- optional: the results page
def enrich_from_results_pages(brand, run_folder):
    """Fold a SAVED results-page check into the slate. Nothing is fetched here: the check is run
    (and paid for, and confirmed) by the research tools. This reads what they saved.

    For a group whose phrases were checked: a video among the results counts as "video shows
    here"; the follow-up questions people also ask are kept as candidates; and when the head and
    another phrase in the group return almost entirely different pages, the sheet suggests
    splitting them, because one video will not be found for both."""
    brand = as_brand(brand)
    try:
        from smf.research import store
    except ImportError:
        raise YouTubeError("The research tools are not part of this copy of the Factory, so there is no "
                           "results-page check to read. The slate works without it.")
    try:
        store.read_run(brand, run_folder, job="serp")
        where = run_folder if os.path.isabs(run_folder) else brand.path(*str(run_folder).replace("\\", "/").split("/"))
        reading = store.read_json(brand, where, "pages.json")
    except store.ResearchError as e:
        raise YouTubeError(str(e))
    pages = {plain(q.get("query")): q for q in reading.get("queries") or []}
    corpus = load(brand)
    touched = 0
    for g in corpus["groups"]:
        seen = [(m, pages[plain(m["keyword"])]) for m in g["members"] if plain(m["keyword"]) in pages]
        if not seen:
            continue
        touched += 1
        asked = []
        for _m, page in seen:
            if any(str(r.get("site") or "").endswith(("youtube.com", "youtu.be", "vimeo.com")) for r in page.get("results") or []):
                if not any("video" in f.lower() for f in g["features"]):
                    g["features"] = sorted(set(g["features"]) | {"Video (seen on the results page)"})
                g["features_known"] = True
            asked += [q for q in page.get("people_also_ask") or [] if q not in asked]
        g["also_asked"] = asked[:12]
        head_page = pages.get(plain(g["head"]))
        suggest = []
        if head_page:
            head_urls = {r.get("url") for r in (head_page.get("results") or [])[:10] if r.get("url")}
            for m, page in seen:
                if m["keyword"] == g["head"]:
                    continue
                urls = {r.get("url") for r in (page.get("results") or [])[:10] if r.get("url")}
                if head_urls and urls and len(head_urls & urls) / float(min(len(head_urls), len(urls))) < 0.2:
                    suggest.append(m["keyword"])
        g["results_pages_suggest_split"] = suggest
    rank(corpus["groups"], corpus.get("settings_used") or {})
    corpus["enriched_from"] = relative(brand, where)
    _save(brand, corpus)
    return {"groups_touched": touched, "queries_read": len(pages)}


# ----------------------------------------------------------------------------- the readable summary
def slate_md(brand, corpus):
    s = summarise(corpus["groups"])
    lines = ["# Question slate for %s" % brand.name, "",
             "%d phrases from %d file%s, grouped into **%d possible videos**."
             % (s["keywords"], len(corpus.get("files") or []), "" if len(corpus.get("files") or []) == 1 else "s", s["groups"]), "",
             "| Tier | What it means | Groups |", "|---|---|---|",
             "| film | Real demand, and a video can win the spot. A proper long video | %d |" % s["tiers"]["film"],
             "| batch | Real demand, thinner signal. Record several in one sitting | %d |" % s["tiers"]["batch"],
             "| text | Almost no demand. Answer in writing, never filmed | %d |" % s["tiers"]["text"],
             "| parked | Flagged. Waiting for a person to overrule | %d |" % s["tiers"]["parked"], ""]
    if not s["results_page_known"]:
        lines += ["None of these exports says what the results page shows, so the strongest signal (is a video "
                  "already there?) is missing. Tiers are based on demand alone. A results-page check on the top "
                  "phrases fills that in.", ""]
    lines += ["**The phrase in the first column is never reworded.** It goes into the title exactly as written.", "",
              "| # | Search phrase (exact) | Say it as | Monthly searches | Tier | Decision |", "|---|---|---|---|---|---|"]
    for g in corpus["groups"][:60]:
        lines.append("| %d | `%s` | %s | %s | %s | %s |" % (g["rank"], g["head"].replace("|", "/"), g["say"].replace("|", "/"),
                                                         "{:,}".format(g["volume"]), g["tier"], g.get("decision") or "-"))
    if len(corpus["groups"]) > 60:
        lines += ["", "Showing the first 60 of %d. The review sheet has them all." % len(corpus["groups"])]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- the review sheet
_SHEET_CSS = """
:root{color-scheme:light;--ground:#ffffff;--ink:#111111;--muted:#555555;--rule:#d9d9d9;--soft:#f4f4f4;}
*{box-sizing:border-box;}
body{margin:0;background:var(--ground);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Arial,sans-serif;}
header{position:sticky;top:0;background:var(--ground);border-bottom:1px solid var(--rule);padding:14px 16px;z-index:5;}
h1{margin:0 0 4px;font-size:19px;}
.lead{color:var(--muted);font-size:14px;max-width:70ch;}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center;}
input,select,button{font:inherit;font-size:14px;color:var(--ink);background:var(--ground);border:1px solid var(--rule);
  border-radius:6px;padding:7px 10px;}
input[type=search]{flex:1 1 220px;min-width:0;}
button{cursor:pointer;}
button.main{border-color:var(--ink);font-weight:700;}
button.on{background:var(--ink);color:var(--ground);border-color:var(--ink);}
.counts{font-size:14px;color:var(--muted);margin-top:8px;}
.counts b{color:var(--ink);}
main{padding:12px 16px 90px;max-width:1100px;margin:0 auto;}
.row{border:1px solid var(--rule);border-radius:8px;padding:12px 14px;margin:0 0 10px;}
.row.cursor{outline:2px solid var(--ink);}
.row[data-d=park]{background:var(--soft);}
.top{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;}
.kw{font-weight:700;font-size:17px;word-break:break-word;}
.meta{color:var(--muted);font-size:14px;margin-left:auto;}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;font-size:12px;}
.tag{border:1px solid var(--rule);border-radius:4px;padding:1px 7px;text-transform:uppercase;letter-spacing:.04em;}
.tag.strong{border-color:var(--ink);font-weight:700;}
.say{margin-top:8px;font-size:14px;color:var(--muted);}
.say b{color:var(--ink);font-weight:600;}
.say u{text-decoration-style:wavy;}
.acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;}
.acts input{flex:1 1 200px;min-width:0;}
details{margin-top:8px;font-size:14px;}
summary{cursor:pointer;color:var(--muted);}
.member{display:flex;gap:10px;align-items:baseline;padding:3px 0;border-top:1px solid var(--soft);}
.member .v{min-width:64px;text-align:right;color:var(--muted);}
.member .k{flex:1 1 auto;word-break:break-word;}
.empty{color:var(--muted);padding:40px 0;text-align:center;}
footer{position:fixed;left:0;right:0;bottom:0;background:var(--ground);border-top:1px solid var(--rule);
  padding:8px 16px;font-size:13px;color:var(--muted);}
kbd{border:1px solid var(--rule);border-radius:4px;padding:0 5px;font:12px ui-monospace,monospace;color:var(--ink);}
"""

_SHEET_JS = r"""
const KEY = 'question-slate-' + DATA.brand;
const store = (() => {            // some browsers refuse storage for a page opened from a file
  try { localStorage.setItem('__t', '1'); localStorage.removeItem('__t');
    return {ok: true, get: k => localStorage.getItem(k), set: (k, v) => localStorage.setItem(k, v), del: k => localStorage.removeItem(k)}; }
  catch (e) { const m = {}; return {ok: false, get: k => (k in m ? m[k] : null), set: (k, v) => { m[k] = v; }, del: k => { delete m[k]; }}; }
})();
let rulings = {};
try { rulings = JSON.parse(store.get(KEY) || '{}'); } catch (e) { rulings = {}; }
for (const g of DATA.groups) if (g.decision && !rulings[g.key]) rulings[g.key] = {decision: g.decision, note: g.note || ''};
let cursor = 0, shown = [], unsaved = false;
const opened = new Set(DATA.groups.filter(g => g.split_candidate).map(g => g.key));
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = n => Number(n || 0).toLocaleString();

function visible(g) {
  const tier = $('#tier').value, dec = $('#dec').value, q = $('#q').value.trim().toLowerCase();
  const d = (rulings[g.key] || {}).decision || '';
  if (tier && g.tier !== tier) return false;
  if (dec === 'none' ? d : (dec && d !== dec)) return false;
  if (q && !g.members.some(m => m.keyword.toLowerCase().includes(q))) return false;
  return true;
}
function draw() {
  shown = DATA.groups.filter(visible);
  if (cursor >= shown.length) cursor = Math.max(0, shown.length - 1);
  $('#list').innerHTML = shown.length ? shown.map((g, i) => {
    const r = rulings[g.key] || {};
    const tags = ['<span class="tag strong">' + esc(g.tier) + '</span>'];
    if (g.video_on_results_page) tags.push('<span class="tag">video already shows</span>');
    if (g.split_candidate) tags.push('<span class="tag">two videos?</span>');
    for (const f of g.flags) tags.push('<span class="tag strong">' + esc(DATA.flag_words[f] || f) + '</span>');
    for (const f of g.notes) tags.push('<span class="tag">' + esc(DATA.flag_words[f] || f) + '</span>');
    for (const k of (g.results_pages_suggest_split || [])) tags.push('<span class="tag">results pages differ: ' + esc(k) + '</span>');
    const say = g.say_needs_a_person ? '<u>' + esc(g.say) + '</u> (needs a person to reword what is SAID)' : esc(g.say);
    const members = g.members.map(m => {
      const own = (r.splits || []).includes(m.keyword);
      const btn = m.keyword === g.head ? '<span class="tag">leads</span>'
        : '<button data-split="' + esc(m.keyword) + '" class="' + (own ? 'on' : '') + '">' + (own ? 'own video: yes' : 'give it its own video') + '</button>';
      return '<div class="member"><span class="v">' + num(m.volume) + '</span><span class="k">' + esc(m.keyword) + '</span>' + btn + '</div>';
    }).join('');
    return '<div class="row' + (i === cursor ? ' cursor' : '') + '" data-d="' + esc(r.decision || '') + '" data-key="' + esc(g.key) + '" data-i="' + i + '">'
      + '<div class="top"><span class="kw">' + esc(g.head) + '</span><span class="meta">' + num(g.volume) + ' a month &middot; ' + g.members.length + ' phrase' + (g.members.length === 1 ? '' : 's') + ' &middot; #' + g.rank + '</span></div>'
      + '<div class="tags">' + tags.join('') + '</div>'
      + '<div class="say">Written exactly as above. Say it as: <b>' + say + '</b></div>'
      + '<div class="acts"><button data-act="approve" class="' + (r.decision === 'approve' ? 'on' : '') + '">Approve</button>'
      + '<button data-act="edit" class="' + (r.decision === 'edit' ? 'on' : '') + '">Needs an edit</button>'
      + '<button data-act="park" class="' + (r.decision === 'park' ? 'on' : '') + '">Park</button>'
      + '<input data-note placeholder="A note for later" value="' + esc(r.note || '') + '"></div>'
      + (g.members.length > 1 ? '<details' + (opened.has(g.key) ? ' open' : '') + '><summary>The ' + g.members.length + ' phrases in this video</summary>' + members + '</details>' : '')
      + '</div>';
  }).join('') : '<div class="empty">Nothing matches.</div>';
  const all = Object.values(rulings), n = k => all.filter(v => v.decision === k).length;
  $('#counts').innerHTML = '<b>' + n('approve') + '</b> approved &middot; <b>' + n('edit') + '</b> to edit &middot; <b>' + n('park') + '</b> parked &middot; <b>'
    + (DATA.groups.length - all.filter(v => v.decision).length) + '</b> left &middot; ' + shown.length + ' showing'
    + (store.ok ? (unsaved ? ' &middot; <b>NOT SAVED TO A FILE YET</b>' : '') : ' &middot; <b>THIS BROWSER WILL NOT REMEMBER YOUR WORK: SAVE BEFORE YOU CLOSE</b>');
}
function keep() { store.set(KEY, JSON.stringify(rulings)); unsaved = true; draw(); }
function rule(key, d) { const r = rulings[key] || {}; r.decision = r.decision === d ? '' : d; rulings[key] = r; keep(); }

$('#list').addEventListener('click', e => {
  const row = e.target.closest('.row'); if (!row) return;
  cursor = Number(row.dataset.i);
  const s = e.target.closest('button[data-split]');
  if (s) { const r = rulings[row.dataset.key] || {}; const set = new Set(r.splits || []);
    set.has(s.dataset.split) ? set.delete(s.dataset.split) : set.add(s.dataset.split); r.splits = [...set]; rulings[row.dataset.key] = r; keep(); return; }
  const a = e.target.closest('button[data-act]');
  if (a) { rule(row.dataset.key, a.dataset.act); return; }
  // Any other click only moves the cursor. Redrawing here would close an opened list and take
  // the typing position out of the note box.
  document.querySelectorAll('.row.cursor').forEach(el => el.classList.remove('cursor'));
  row.classList.add('cursor');
});
$('#list').addEventListener('toggle', e => {           // a list someone opened stays open across redraws
  const row = e.target.closest && e.target.closest('.row'); if (!row) return;
  e.target.open ? opened.add(row.dataset.key) : opened.delete(row.dataset.key);
}, true);
$('#list').addEventListener('change', e => {
  if (!e.target.matches('input[data-note]')) return;
  const row = e.target.closest('.row'), r = rulings[row.dataset.key] || {}; r.note = e.target.value; rulings[row.dataset.key] = r;
  store.set(KEY, JSON.stringify(rulings)); unsaved = true;
});
for (const id of ['#tier', '#dec', '#q']) $(id).addEventListener('input', () => { cursor = 0; draw(); });
document.addEventListener('keydown', e => {
  if (e.target.matches('input,select')) return;
  const g = shown[cursor];
  if (e.key === 'j') { cursor = Math.min(shown.length - 1, cursor + 1); draw(); }
  else if (e.key === 'k') { cursor = Math.max(0, cursor - 1); draw(); }
  else if (g && e.key === 'a') rule(g.key, 'approve');
  else if (g && e.key === 'e') rule(g.key, 'edit');
  else if (g && e.key === 'x') rule(g.key, 'park');
  const el = document.querySelector('.row.cursor'); if (el) el.scrollIntoView({block: 'nearest'});
});
$('#save').addEventListener('click', () => {
  const kept = {};
  for (const [k, v] of Object.entries(rulings)) if (v.decision || v.note || (v.splits || []).length) kept[k] = v;
  const blob = new Blob([JSON.stringify({brand: DATA.brand, made: new Date().toISOString(), decisions: kept}, null, 2)], {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'decisions-' + DATA.brand + '.json';
  document.body.appendChild(a); a.click(); a.remove(); unsaved = false; draw();
});
$('#clear').addEventListener('click', () => { if (confirm('Clear every decision on this sheet?')) { rulings = {}; store.del(KEY); unsaved = false; draw(); } });
draw();
"""


def review_html(brand, corpus):
    """The review sheet: ONE file, nothing loaded from anywhere, light background, dark text.
    Decisions are kept in the browser as you go and saved to a file with one button."""
    brand = as_brand(brand)
    data = {"brand": brand.id, "name": brand.name, "flag_words": FLAG_WORDS,
            "groups": [{k: g.get(k) for k in ("key", "head", "volume", "tier", "rank", "flags", "notes", "say",
                                              "say_needs_a_person", "video_on_results_page", "split_candidate",
                                              "decision", "note", "results_pages_suggest_split")}
                       | {"members": [{"keyword": m["keyword"], "volume": m["volume"]} for m in g["members"]],
                          "flags": g.get("flags") or [], "notes": g.get("notes") or []}
                       for g in corpus["groups"]]}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    s = summarise(corpus["groups"])
    title = "Question slate: %s" % brand.name
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>%s</title><style>%s</style></head><body>"
            "<header><h1>%s</h1><div class=\"lead\">%d phrases grouped into %d possible videos. Approve the ones worth "
            "making, park the rest, and give any phrase its own video when it is really a different question. "
            "The phrase in bold is never reworded: it goes into the title exactly as written.</div>"
            "<div class=\"bar\"><input id=\"q\" type=\"search\" placeholder=\"Find a phrase\">"
            "<select id=\"tier\"><option value=\"\">Every tier</option><option value=\"film\">film</option>"
            "<option value=\"batch\">batch</option><option value=\"text\">text</option><option value=\"parked\">parked</option></select>"
            "<select id=\"dec\"><option value=\"\">Any decision</option><option value=\"none\">Not decided</option>"
            "<option value=\"approve\">Approved</option><option value=\"edit\">Needs an edit</option>"
            "<option value=\"park\">Parked</option></select>"
            "<button id=\"save\" class=\"main\">Save decisions to a file</button><button id=\"clear\">Clear</button></div>"
            "<div class=\"counts\" id=\"counts\"></div></header><main><div id=\"list\"></div></main>"
            "<footer><kbd>j</kbd> <kbd>k</kbd> move &nbsp; <kbd>a</kbd> approve &nbsp; <kbd>e</kbd> needs an edit &nbsp; "
            "<kbd>x</kbd> park. When you are done, save the file and give it to Claude.</footer>"
            "<script>const DATA = %s;</script><script>%s</script></body></html>\n"
            % (_html(title), _SHEET_CSS, _html(title), s["keywords"], s["groups"], blob, _SHEET_JS))


def _html(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))
