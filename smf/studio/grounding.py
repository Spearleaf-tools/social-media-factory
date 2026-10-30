"""grounding.py - every number in a draft has to come from somewhere the brand can point to.

A number in a post is a claim a reader can check. So a draft's numbers are compared with the
brand's OWN evidence, and each match keeps a note of where it came from, so the writer can credit
the source and a reviewer can see when a number matched the wrong thing.

Three places count as evidence:

  1. Studio/facts.json          facts the brand has verified, each with a source
                                {"facts": [{"id": "proof-18h", "claim": "We proof our sourdough for 18 hours.",
                                            "values": ["18"], "source": "Ava's recipe card"}]}
                                Numbers are read from the claim and from `values` (or a single
                                `value`). A fact with no source backs nothing; it is reported instead.
  2. Inputs/Research/**/*.csv   stat files the brand collected. Column names vary from file to
                                file, so they are found by meaning (finding/stat/claim, source,
                                url/link, confidence), and a broken file is skipped, not fatal.
  3. Studio/registry.db         proof items, but only the ones LINKED to this piece of writing.
                                A number that only appears in unlinked proof gets a hint instead.

Numbers that merely describe the post itself are not claims: a list marker ("2."), "Step 3",
or the count in "3 tips". They are reported as structural and never need evidence.

A MATCHING VALUE IS NOT ENOUGH. "18" in "18 hours" says nothing about "18%". A number is
traced only when the value AND what it measures agree (a percentage, money, a multiple, a
measurement, or a plain count). When they agree but the sentence is about something else than the
evidence it matched, nothing is provably wrong and nothing is confirmed either: it is reported
as `unconfirmed`, with the evidence it resembles, for a person to decide. The same goes for a
number whose only trace is a research row that is itself unconfirmed (no source, or marked
unverified or low confidence): that row is background, never proof.

CLAIMS WITHOUT DIGITS are read too. A number written in words ("eighteen percent") is traced
like a number written in digits. "Half of our customers", "doubled", "dozens of", and
achievement or result claims ("we won", "voted best", "certified", "our revenue grew") have to
be said by the brand's own evidence; otherwise they are `unconfirmed` (see `check_wording`).

An empty brand works. No numbers in the draft: fine. Numbers with nothing to trace to: the report
says which ones and exactly how to add a fact.

    from smf.studio.grounding import ground_draft
    report = ground_draft(text, brand, proof_ids=["p-003"])
    report["ok"], report["ungrounded"], report["unconfirmed"], report["attributions"]
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from smf.studio.files import StudioError, as_brand, read_json, relative, write_json

FACTS_FILE = ("Studio", "facts.json")
RESEARCH_DIR = ("Inputs", "Research")
REGISTRY = ("Studio", "registry.db")

# 4,420 | 4.42K | 0.6 | $1,200 | 35%. A full stop that ends the sentence is not part of the number.
# A number may be glued to a unit of measurement ("72h", "5kg", "3x"). Those are claims like any
# other and must be checked; without the unit list they were invisible to the fact check. The
# list is closed on purpose so that "10am", "B12" or "MP3" do not turn into facts.
_UNIT = r"(?:hrs?|h|mins?|secs?|s|kg|g|mg|lbs?|oz|km|cm|mm|ml|l|x|px|gb|mb|tb|kw|w|v|c|f)"
_NUMBER = re.compile(r"(?<![\w.])[$£€]?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)([KkMm])?(?!\.?\d)"
                     r"(?:(?=(?i:%s)\b)|(?!\w))" % _UNIT)
_MULTIPLIER = {"k": 1000.0, "m": 1000000.0}

# Words that make a number a count of the post's own parts rather than a fact about the world.
STRUCTURAL_NOUNS = ("things?|ways?|steps?|reasons?|mistakes?|signs?|lessons?|questions?|tips?|myths?|rules?|ideas?|"
                    "parts?|points?|moves?|habits?|checks?|beliefs?|objections?|misconceptions?")
_COUNT_OF_PARTS = re.compile(r"^\s+(?:\w+\s+){0,2}?(?:%s)\b" % STRUCTURAL_NOUNS, re.IGNORECASE)
_LIST_MARKER_AFTER = re.compile(r"^[.)]\s")
# "Step 2" is a label. "#1" and "number 1" are NOT: they are ranking claims and need evidence like any other.
_LABEL_BEFORE = re.compile(r"(?:^|\s)(?:step|part|tip|lesson|rule|myth|mistake|reason|question)\s*$", re.IGNORECASE)

# What a number measures, read from what is glued to it or follows it. Different spellings of
# one unit meet at one name, so "18h", "18 hrs" and "an 18-hour proof" all agree with "18 hours".
# The list is closed for the same reason the glued list is: a word that is not here leaves the
# number a plain count, and the sentence around it has to match instead.
_MEASURES = {
    "hours": "h hr hrs hour hours", "minutes": "min mins minute minutes", "seconds": "s sec secs second seconds",
    "days": "day days", "weeks": "wk wks week weeks", "months": "month months", "years": "yr yrs year years",
    "kg": "kg kgs kilo kilos kilogram kilograms", "g": "g gram grams gramme grammes", "mg": "mg",
    "lb": "lb lbs", "oz": "oz ounce ounces", "km": "km kilometre kilometres kilometer kilometers",
    "metres": "metre metres meter meters", "cm": "cm", "mm": "mm", "ml": "ml", "litres": "l litre litres liter liters",
    "px": "px", "gb": "gb", "mb": "mb", "tb": "tb", "kw": "kw", "watts": "w watt watts", "volts": "v volt volts",
    "degrees": "c f degree degrees",
}
_MEASURE_OF = {form: name for name, forms in _MEASURES.items() for form in forms.split()}
_AFTER_NUMBER = re.compile(
    r"^(?:(?P<percent>\s?%|\s(?:percent|per\s+cent|pct|percentage\s+points?)\b)"
    r"|(?P<money>\s(?:dollars?|euros?|cents?|pence|quid|bucks|usd|gbp|eur)\b)"
    r"|(?P<pounds>\s(?:pounds?)\b)"
    r"|(?P<times>x\b|\s?×|\s(?:x|times)\b|[\s-]?fold\b)"
    r"|(?P<degrees>\s?°(?:\s?[cf]\b)?)"
    r"|[\s-]?(?P<measure>"
    + "|".join(sorted(_MEASURE_OF, key=len, reverse=True)) + r")\b)", re.IGNORECASE)
COUNT = "count"
ANY_KIND = frozenset()                  # a value written beside a fact, with nothing to say what it measures

# Numbers written in words. In a DRAFT only thirteen and upwards is a claim, or a smaller one
# that is a percentage or money ("five percent"): "the two loaves" describes, it does not claim.
_SMALL = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"thousand": 1000, "million": 1000000, "billion": 1000000000}
_NUMBER_WORD = "(?:%s)" % "|".join(sorted(list(_SMALL) + list(_TENS) + list(_SCALES) + ["hundred"], key=len, reverse=True))
_SPELLED = re.compile(r"\b%s(?:[\s-]+(?:and\s+)?%s)*\b" % (_NUMBER_WORD, _NUMBER_WORD), re.IGNORECASE)
SPELLED_CLAIM_FROM = 13


class GroundingError(StudioError):
    """The brand's evidence files could not be used."""


@dataclass(frozen=True)
class GroundedValue:
    value: float
    kind: str            # brand_fact | research_stat | proof
    source: str          # who or what says so
    snippet: str         # the sentence the number came from
    ref: str = ""        # fact id, proof id, or the research file
    url: str = ""
    confidence: str = ""
    units: frozenset = ANY_KIND     # what the number measures: {"percent"}, {"hours"}, {"count"}; empty = not said
    shown: str = ""      # the number as the evidence writes it: "18 hours", "$1,200"
    weak: str = ""       # why this cannot confirm anything by itself ("" when it can)

    def cite(self):
        """A short line the writer can use to credit the number."""
        if self.kind == "brand_fact":
            return "the brand's own fact (%s): %s" % (self.source, self.snippet)
        if self.kind == "proof":
            return "proof item %s: %s" % (self.ref, self.snippet)
        tail = " (%s confidence)" % self.confidence if self.confidence else ""
        return "%s%s: %s" % (self.source, tail, self.snippet)

    def as_dict(self):
        return {"kind": self.kind, "source": self.source, "snippet": self.snippet, "ref": self.ref,
                "url": self.url, "confidence": self.confidence, "cite": self.cite(),
                "shown": self.shown, "units": sorted(self.units), "unconfirmed": self.weak}


class Corpus(object):
    """Everything a brand can point to, plus the things that went wrong while collecting it."""

    def __init__(self, items=None, notes=None):
        self.items = list(items or [])
        self.notes = list(notes or [])

    def values(self):
        return {i.value for i in self.items}

    def provenance(self, value):
        return [i for i in self.items if i.value == value]

    def of_kind(self, kind):
        return [i for i in self.items if i.kind == kind]

    def __len__(self):
        return len(self.items)


# ----------------------------------------------------------------------------- numbers in text
def _normalise(number, suffix):
    value = float(number.replace(",", ""))
    if suffix:
        value *= _MULTIPLIER[suffix.lower()]
    return round(value, 6)


def _is_structural(text, match):
    """True for a number that only organises the post: a list marker, a 'Step 2' label, '3 tips'."""
    line_start = text.rfind("\n", 0, match.start()) + 1
    before = text[line_start:match.start()]
    after = text[match.end():match.end() + 40]
    if not before.strip() and _LIST_MARKER_AFTER.match(after):
        return True
    if _LABEL_BEFORE.search(before):
        return True
    raw = match.group(0)
    return raw.isdigit() and int(raw) <= 12 and bool(_COUNT_OF_PARTS.match(after))


def _units_after(text, end, raw=""):
    """(what the number measures, the words that said so). A currency sign in front wins; after
    that it is whatever follows the number. "pounds" is money in one country and weight in
    another, so it agrees with both."""
    m = _AFTER_NUMBER.match(text[end:end + 24])
    said = m.group(0) if m else ""
    if raw[:1] and raw[0] in "$£€":
        return frozenset(["money"]), said if m and (m.group("money") or m.group("pounds")) else ""
    if not m:
        return frozenset([COUNT]), ""
    for name in ("percent", "money", "times", "degrees"):
        if m.group(name):
            return frozenset([name]), said
    if m.group("pounds"):
        return frozenset(["money", "lb"]), said
    return frozenset([_MEASURE_OF[m.group("measure").lower()]]), said


def same_kind(a, b):
    """Do two numbers measure the same thing? A value with no kind of its own agrees with any."""
    return not a or not b or bool(frozenset(a) & frozenset(b))


def extract_numbers(text):
    """Every number written in digits, in order: [{raw, value, structural, units, shown, start}].
    `units` is what it measures and `shown` is the number with its unit, as written ("18%")."""
    text = text or ""
    out = []
    for m in _NUMBER.finditer(text):
        raw = m.group(0).strip()
        units, said = _units_after(text, m.end(), raw)
        out.append({"raw": raw, "value": _normalise(m.group(1), m.group(2)), "structural": _is_structural(text, m),
                    "units": sorted(units), "shown": (raw + said).strip(), "start": m.start()})
    return out


def _words_value(phrase):
    """'eighteen' -> 18, 'two hundred and forty' -> 240. None for a bare 'hundred' or 'thousand',
    which is a figure of speech more often than a figure."""
    total = current = 0
    counted = False
    for token in re.split(r"[\s-]+", phrase.lower()):
        if token == "and":
            continue
        if token in _SMALL or token in _TENS:
            current += _SMALL.get(token, 0) + _TENS.get(token, 0)
            counted = True
        elif token == "hundred":
            current = (current or 1) * 100
        else:
            total, current = total + (current or 1) * _SCALES[token], 0
    return float(total + current) if counted else None


def spelled_numbers(text, every_size=False):
    """Numbers written in words, shaped like extract_numbers(). In a draft only the ones that are
    claims come back (see SPELLED_CLAIM_FROM); `every_size` returns them all, which is how a fact
    that says "eight people" gives its kind to the value 8 written beside it."""
    text = text or ""
    out = []
    for m in _SPELLED.finditer(text):
        value = _words_value(m.group(0))
        if value is None:
            continue
        units, said = _units_after(text, m.end())
        if not every_size and value < SPELLED_CLAIM_FROM and not units & {"percent", "money"}:
            continue
        out.append({"raw": m.group(0), "value": value, "structural": False, "units": sorted(units),
                    "shown": (m.group(0) + said).strip(), "start": m.start(), "in_words": True})
    return out


# Nouns that make a sentence a claim about the business rather than about baking or exercise.
# "We grew our sales" is a result; "We grew our starter" is a Tuesday. The list is short on
# purpose: every word in it is something a reader could ask to see the figures for.
BUSINESS_NOUNS = ("sales|revenue|turnover|profit|profits|income|margin|margins|takings|orders|bookings|enquiries|"
                  "inquiries|leads|customers|clients|patients|students|members|subscribers|followers|readers|"
                  "regulars|visitors|guests|audience|waitlist|traffic|reach|engagement|conversions|sign-?ups|"
                  "prices|costs|fees|waiting|wait|queue|people|businesses|shops|cafes|families|households")
# Quantity words that really are a number. Each needs the thing it is a share OF, so that
# "add half the flour" and "double-check the oven" stay what they are: instructions.
# Is the sentence about the business, or about what the reader should do?
ANYWHERE, ABOUT_ITSELF = "anywhere", "about itself"
_SPEAKING_OF_ITSELF = re.compile(r"\b(?:we|we're|we've|our|ours|us|%s)\b" % BUSINESS_NOUNS, re.IGNORECASE)
_SHARES = r"(?:of\s+)?(?:our|the|my|their|its|all\s+(?:of\s+)?(?:our|the|my|their))\s+(?:\w+\s+){0,1}?(?:%s)\b" % BUSINESS_NOUNS
_QUANTITY_WORDS = [
    (r"\bhalf\s+" + _SHARES, 50.0, "percent"),
    (r"\b(?:a|one)[\s-]thirds?\s+" + _SHARES, round(100.0 / 3, 6), "percent"),
    (r"\btwo[\s-]thirds\s+" + _SHARES, round(200.0 / 3, 6), "percent"),
    (r"\b(?:a|one)[\s-]quarters?\s+" + _SHARES, 25.0, "percent"),
    (r"\bthree[\s-]quarters\s+" + _SHARES, 75.0, "percent"),
    # "Twice as long" and "doubled" are a claim when the business is talking about ITSELF, and an
    # instruction when it is telling the reader what to do. "We bake twice as many loaves as last
    # year" is a claim; "rest it twice as long as you think you need to" is advice, and warning a
    # person about their own how-to copy would teach them to ignore the warnings. So these carry
    # ABOUT_ITSELF: the sentence must also be speaking about the business.
    (r"\btwice\s+as\s+(?:many|much|fast|long|often|big|large|likely)\b", 2.0, "times", ABOUT_ITSELF),
    (r"\b(?:doubled|doubles|doubling)\b", 2.0, "times", ABOUT_ITSELF),
    (r"\b(?:tripled|triples|tripling)\b", 3.0, "times", ABOUT_ITSELF),
    (r"\b(?:halved|halves|halving)\b", 0.5, "times", ABOUT_ITSELF),
]
_QUANTITY_WORDS = [(re.compile(row[0], re.IGNORECASE),) + tuple(row[1:]) + ((ANYWHERE,) if len(row) == 3 else ())
                   for row in _QUANTITY_WORDS]


def quantity_numbers(text):
    """Quantity words that mean a number, shaped like extract_numbers(): "half of our customers"
    is 50 percent, "doubled" is 2 times. Only the ones that convert; "dozens" and "hundreds" are
    claims too, but they are not a figure, so they are handled with the other wording claims."""
    out = []
    for pattern, value, units, needs in _QUANTITY_WORDS:
        for m in pattern.finditer(text or ""):
            if needs is ABOUT_ITSELF and not _SPEAKING_OF_ITSELF.search(_sentence_around(text, m.start())):
                continue                                    # an instruction to the reader, not a claim
            out.append({"raw": m.group(0), "value": value, "structural": False, "units": [units],
                        "shown": m.group(0).strip(), "start": m.start(), "in_words": True})
    return sorted(out, key=lambda n: n["start"])


def _values_in(text):
    return {n["value"] for n in extract_numbers(text)}


# ----------------------------------------------------------------------------- the brand's facts
def facts_path(brand):
    return brand.path(*FACTS_FILE)


def load_facts(brand):
    """(facts, notes). A fact needs a claim and a source; anything else is described in notes."""
    path = facts_path(brand)
    if not os.path.isfile(path):
        return [], []
    data = read_json(path, "%s's facts file (Studio/facts.json)" % brand.name)
    rows = data.get("facts") if isinstance(data, dict) else data
    facts, notes = [], []
    for i, row in enumerate(rows if isinstance(rows, list) else [], start=1):
        if not isinstance(row, dict) or not str(row.get("claim") or "").strip():
            notes.append("Fact number %d in the facts file has no claim, so it was skipped." % i)
            continue
        if not str(row.get("source") or "").strip():
            notes.append("The fact \"%s\" has no source, so it cannot back a claim yet. Add where it comes from."
                         % str(row["claim"])[:80])
            continue
        facts.append({"id": str(row.get("id") or "fact-%d" % i), "claim": str(row["claim"]).strip(),
                      "values": sorted(_declared_values(row) | _values_in(str(row["claim"]))),
                      "source": str(row["source"]).strip()})
    return facts, notes


def _declared_values(row):
    """Numbers a fact states outright, as `values` (a list) or `value` (one), written as numbers
    or as text. Useful when the claim spells the number out in words."""
    given = list(row["values"]) if isinstance(row.get("values"), list) else []
    if "value" in row:
        given.append(row["value"])
    out = set()
    for v in given:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.add(round(float(v), 6))
        elif isinstance(v, str):
            out |= _values_in(v)
    return out


def add_fact(brand, claim, source, values=None, fact_id=None):
    """Record one verified fact. Both the claim and where it comes from are required. `values` is
    only needed when the claim spells a number out in words ("two hundred and forty")."""
    brand = as_brand(brand)
    if not str(claim or "").strip():
        raise GroundingError("A fact needs the claim itself, in a sentence.")
    if not str(source or "").strip():
        raise GroundingError("A fact needs a source: who said it, which document, or where it can be checked. "
                             "Without one it cannot back a claim in a post.")
    path = facts_path(brand)
    data = {"brand": brand.id, "facts": []}
    if os.path.isfile(path):
        loaded = read_json(path, "%s's facts file (Studio/facts.json)" % brand.name)
        if isinstance(loaded, dict) and isinstance(loaded.get("facts"), list):
            data = loaded
    taken = {str(f.get("id")) for f in data["facts"] if isinstance(f, dict)}
    n = len(data["facts"]) + 1
    while not fact_id or fact_id in taken:
        fact_id, n = "fact-%d" % n, n + 1
    if values is not None and not isinstance(values, (list, tuple)):
        values = [values]
    stated = _declared_values({"values": list(values or [])}) | _values_in(str(claim))
    row = {"id": fact_id, "claim": str(claim).strip(), "values": [_plain(v) for v in sorted(stated)],
           "source": str(source).strip()}
    data["facts"].append(row)
    data["brand"] = brand.id
    write_json(path, data)
    return row


def _plain(value):
    return "%d" % value if float(value).is_integer() else "%g" % value


def evidence_numbers(text):
    """Every number a piece of evidence states, however it is written: in digits, in words, and as
    a quantity word ("half of our customers", "doubled"). Evidence is read generously, because a
    brand writes its facts in sentences; a draft is read strictly."""
    return extract_numbers(text) + spelled_numbers(text, every_size=True) + quantity_numbers(text)


def _evidence_from(text, kind, source, ref, **more):
    """One piece of evidence per number written in `text`, each with what it measures."""
    return [GroundedValue(n["value"], kind, source, text.strip()[:200], ref=ref, units=frozenset(n["units"]),
                          shown=n["shown"], **more) for n in evidence_numbers(text)]


def _fact_values(brand):
    facts, notes = load_facts(brand)
    out = []
    for f in facts:
        written = _evidence_from(f["claim"], "brand_fact", f["source"], f["id"])
        out.extend(written)
        # A value written beside the fact takes its kind from the sentence when the sentence
        # spells the same number out ("four hours" beside 4). Otherwise it has no kind of its own.
        in_words = {n["value"]: n for n in spelled_numbers(f["claim"], every_size=True)}
        for v in f["values"]:
            if v in {w.value for w in written}:
                continue
            said = in_words.get(v)
            out.append(GroundedValue(v, "brand_fact", f["source"], f["claim"][:200], ref=f["id"],
                                     units=frozenset(said["units"]) if said else ANY_KIND,
                                     shown=said["shown"] if said else _plain(v)))
    return out, notes


# ----------------------------------------------------------------------------- research stat files
# A research row can only confirm a number when somebody stands behind it. These are the ways a
# row says, in its own file, that nobody does yet: the source cell is empty or a shrug, or the
# confidence cell says the row was never checked. Such a row stays as background: it can explain
# where a number came from, but a draft that rests on it is unverified, never passed.
_NOT_A_SOURCE = frozenset(["", "-", "--", "?", "n/a", "na", "none", "no source", "unknown", "not known",
                           "unsourced", "tbc", "tbd", "unverified", "somewhere", "the internet", "online"])
_WEAK_CONFIDENCE = frozenset(["unverified", "unconfirmed", "not verified", "low", "very low", "guess", "guessed",
                              "estimate", "estimated", "rumour", "rumor", "unsure", "unknown", "no"])


def _row_weakness(source_cell, confidence, label):
    """Why a research row cannot confirm anything by itself, as the end of a sentence, or ""."""
    if str(source_cell or "").strip().lower() in _NOT_A_SOURCE:
        return "the row it comes from has no source of its own (it is in %s)" % label
    if str(confidence or "").strip().lower() in _WEAK_CONFIDENCE:
        return "the row it comes from is marked \"%s\" in its own file (%s)" % (str(confidence).strip(), label)
    return ""


def _detect_columns(header):
    """Find the finding, source, link and confidence columns by what their headings mean."""
    found = {"finding": None, "source": None, "url": None, "confidence": None}
    for i, heading in enumerate(header):
        h = heading.strip().lower()
        if found["finding"] is None and (any(w in h for w in ("insight", "stat", "finding", "fact")) or h == "claim"):
            found["finding"] = i
        if found["source"] is None and any(w in h for w in ("source", "publisher", "author", "who ")):
            found["source"] = i
        if found["url"] is None and ("url" in h or "link" in h):
            found["url"] = i
        if found["confidence"] is None and "confidence" in h:
            found["confidence"] = i
    return found


def _read_rows(path):
    """Spreadsheets saved on Windows are often not UTF-8; try the common alternative before giving up."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with open(path, "r", newline="", encoding=encoding) as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            continue
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.reader(f))


def load_research_file(path, label):
    rows = _read_rows(path)
    if len(rows) < 2:
        return []
    header, body = rows[0], rows[1:]
    col = _detect_columns(header)
    finding_i = col["finding"]
    if finding_i is None:
        # No recognisable heading: the column holding the most text is the finding.
        skip = {c for c in (col["source"], col["url"], col["confidence"]) if c is not None}
        widths = [(sum(len(r[i]) for r in body if i < len(r)), -i) for i in range(len(header)) if i not in skip]
        if not widths:
            return []
        finding_i = -max(widths)[1]

    def cell(row, key):
        i = col[key]
        return row[i].strip() if i is not None and i < len(row) else ""

    out = []
    for row in body:
        if finding_i >= len(row) or not row[finding_i].strip():
            continue
        finding = row[finding_i].strip()
        out.extend(_evidence_from(finding, "research_stat", cell(row, "source") or label, label,
                                  url=cell(row, "url"), confidence=cell(row, "confidence"),
                                  weak=_row_weakness(cell(row, "source"), cell(row, "confidence"), label)))
    return out


def _research_values(brand):
    folder = brand.path(*RESEARCH_DIR)
    out, notes = [], []
    if not os.path.isdir(folder):
        return out, notes
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if name.startswith(".") or not name.lower().endswith(".csv"):
                continue
            path = os.path.join(root, name)
            try:
                out.extend(load_research_file(path, relative(brand, path)))
            except (OSError, csv.Error, ValueError):
                notes.append("The research file %s could not be read as a table, so it was skipped."
                             % relative(brand, path))
    return out, notes


# ----------------------------------------------------------------------------- the proof library
def _open_registry(brand):
    """Read-only. None when the brand has no proof library yet, which is a normal state."""
    path = brand.path(*REGISTRY)
    if not os.path.isfile(path):
        return None
    try:
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def list_proof(brand):
    """Every proof item the brand has, newest first. Empty list for an empty or missing library."""
    con = _open_registry(brand)
    if con is None:
        return []
    try:
        rows = con.execute("SELECT proof_id, kind, title, detail, source, file_path, may_publish, "
                           "names_third_party, added_at FROM proof ORDER BY added_at DESC, proof_id").fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def load_proof(brand, proof_ids):
    """(found, missing) for the ids asked for."""
    wanted = [p for p in (proof_ids or []) if p]
    if not wanted:
        return [], []
    by_id = {p["proof_id"]: p for p in list_proof(brand)}
    return [by_id[p] for p in wanted if p in by_id], [p for p in wanted if p not in by_id]


def _proof_values(items):
    out = []
    for p in items:
        text = "%s. %s" % (p.get("title") or "", p.get("detail") or "")
        out.extend(_evidence_from(text, "proof", p.get("source") or "the proof library", p["proof_id"]))
    return out


# ----------------------------------------------------------------------------- put together
def build_corpus(brand, proof_ids=()):
    """Facts + research stats + the LINKED proof items, with notes about anything unusable."""
    brand = as_brand(brand)
    facts, notes = _fact_values(brand)
    research, more = _research_values(brand)
    linked, _missing = load_proof(brand, proof_ids)
    return Corpus(facts + research + _proof_values(linked), notes + more)


HOW_TO_ADD_A_FACT = ("If a number is true, record it so it can be checked: ask Claude to \"add a fact\" with the "
                     "sentence and where it comes from (it is saved in the brand's Studio/facts.json), put a stat "
                     "file with a Source column under Inputs/Research, or link the proof item that shows it. "
                     "If it cannot be backed up, take the number out.")
WHAT_TO_DO = ("Add the fact with its source, link the proof that shows it, or take it out.")


# ----------------------------------------------------------------------------- what a sentence turns on
# Finding a WORD somewhere proves nothing: every common word is somewhere. What is asked is
# whether the words a sentence turns on are in the brand's own writing. (smf/video/describe.py
# asks the same question of a video description and carries its own copy of these two helpers;
# it could use these instead.)
_STOP = frozenset("""about after again against all also always another any are because been before being best better
between both but came come comes could did does doing done down during each even ever every few for from get gets
getting give given goes going good got great had has have having her here hers him his how into its itself just keep
kept know known let like look looks made make makes many may more most much must need needs never new next not now
off once one only other others our ours out over own really said same say says see seen she should show shows since
some still such take taken tell than that the their theirs them then there these they thing things this those through
time today too under until upon use used uses very want wants was way ways well went were what when where which while
who why will with without would yet you your yours""".split())
_WORDISH = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def stem(word):
    """A rough, SYMMETRIC stem: the same rule is used on the draft and on the evidence, so
    "bakes", "baked" and "baking" meet in one place. It does not have to be good English."""
    w = word.lower().replace("’", "'")
    w = re.sub(r"'s$|'$", "", w).replace("'", "")
    for ending, put in (("ives", "if"), ("ves", "f"), ("ies", "y"), ("ingly", ""), ("edly", ""), ("ing", ""),
                        ("ed", ""), ("es", ""), ("ly", ""), ("s", "")):
        if w.endswith(ending) and len(w) - len(ending) >= 3:
            w = w[:len(w) - len(ending)] + put
            break
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiouls":
        w = w[:-1]
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


_UNIT_WORDS = list(_MEASURE_OF) + ["percent", "percentage", "dollars", "dollar", "euros", "cents", "pence",
                                   "pounds", "times", "degrees", "hundred", "thousand", "million"]


def key_terms(text):
    """The words a passage turns on, stemmed, in order, without repeats."""
    out = []
    for raw in _WORDISH.findall(text or ""):
        for part in raw.split("-"):
            low = part.lower().replace("’", "'")
            if len(low) < 4 or low in _STOP:
                continue
            s = stem(low)
            if len(s) >= 3 and s not in out:
                out.append(s)
    return out


_UNIT_STEMS = frozenset(stem(w) for w in _UNIT_WORDS)


def brand_own_words(brand):
    """What the brand has written about ITSELF: what it does, who it serves, its pillars, offers,
    the people who speak for it and their credentials. A claim about the brand may lean on this;
    a figure may not, because none of it has a source attached."""
    d = as_brand(brand).data
    business, audience = d.get("business") or {}, d.get("audience") or {}
    parts = [d.get("name", ""), business.get("what_we_do", ""), business.get("industry", ""),
             business.get("location", ""), audience.get("who", "")]
    parts += list(audience.get("problems") or []) + list(audience.get("questions_they_ask") or [])
    for group in (d.get("pillars") or [], d.get("offers") or []):
        for item in group:
            if isinstance(item, dict):
                parts += [str(item.get(k) or "") for k in ("name", "about", "what", "call_to_action", "guarantee")]
            else:
                parts.append(str(item))
    for who in d.get("identities") or []:
        parts += [str(who.get(k) or "") for k in ("display_name", "role", "credential_line")]
    parts += [str(p) for p in (d.get("voice") or {}).get("signature_phrases") or []]
    parts += [str(p) for p in d.get("own_brands") or []]
    return " ".join(p for p in parts if p)


# ----------------------------------------------------------------------------- claims with no digits
# A claim a reader could ask to see proof of, written without a single digit. Each marker is the
# START of the claim; the phrase runs on to the end of what is being claimed. The list is short
# and every entry is tested against ordinary sentences from a bakery and a physiotherapy clinic,
# because a check that flags "we grew up baking" or "save the date" teaches people to ignore it.
_PHRASE_END = re.compile(r"\b(?:and|but|so|because|while|when|where|which|that|after|before|since|with|from|"
                         r"than|then|though|although|if|as)\b|[.,;:!?\n()]", re.IGNORECASE)
_RESULT_VERBS = r"(?:grew|grown|growing|increased|increases|doubled|doubles|halved|tripled|saved|saves|cut|cuts|" \
                r"reduced|reduces|boosted|boosts|lifted|lifts)"
_CLAIM_MARKERS = [
    ("an award or a win", r"\bwon\b(?!['’]t)\s+(?:the|a|an|our|first|second|third|\d)"),
    ("an award or a win", r"\b(?:award[\s-]winning|prize[\s-]winning|multi[\s-]award)\b"),
    ("being voted or ranked top", r"\b(?:voted|rated|named|ranked|judged|crowned)\s+(?:the\s+)?"
                                  r"(?:best|top|number\s+one|#1|first)\b"),
    # "best in town" is a claim; "best in the first two days" is how bread works, so the place has to be a place.
    ("being voted or ranked top", r"\b(?:best|number\s+one|#1|top)\s+(?:\w+\s+){0,2}?in\s+"
                                  r"(?:town|the\s+(?:city|county|state|country|region|area|world|industry|business))\b"),
    ("being certified or accredited", r"\b(?:certified|accredited|licensed|registered|approved)\s+(?:by|in|as|with)\b"),
    ("having been featured somewhere", r"\b(?:featured|profiled|covered|reviewed)\s+(?:in|on|by)\b"),
    ("a guarantee", r"\b(?:money[\s-]back\s+guarantee|guarantee[sd]?\s+(?:that|you|your|to|a|an|the)|"
                    r"\bwith\s+a\s+\w*\s*guarantee)\b"),
    ("a result for the business or its customers",
     r"\b(?:we|i|they|it)\s+(?:\w+\s+){0,2}?" + _RESULT_VERBS + r"\s+(?:\w+\s+){0,2}?(?:" + BUSINESS_NOUNS + r")\b"),
    ("a result for the business or its customers",
     r"\b" + _RESULT_VERBS + r"\s+(?:our|their|its|the|my|your)\s+(?:\w+\s+){0,1}?(?:" + BUSINESS_NOUNS + r")\b"),
    ("a vague quantity", r"\b(?:dozens|hundreds|thousands|millions)\s+of\b"),
]
_CLAIM_MARKERS = [(what, re.compile(p, re.IGNORECASE)) for what, p in _CLAIM_MARKERS]
_HAS_FIGURE = re.compile(r"\d")


def _claim_phrase(text, start, end):
    """The claim itself: from the marker to the end of what is being claimed."""
    rest = text[end:end + 70]
    stop = _PHRASE_END.search(rest)
    return (text[start:end] + (rest[:stop.start()] if stop else rest)).strip(" .,:;-")


def wording_claims(text):
    """Claims a reader could ask to see proof of, written without digits: an award, a ranking, a
    certificate, a guarantee, a result for the business, "half of our customers", "dozens of".
    Returns [{phrase, what, value, units, start}]. A phrase that already carries a figure is left
    out: a number is checked as a number, and saying it twice buries the real finding."""
    text = text or ""
    found, taken = [], []

    def overlaps(a, z):
        return any(a < zz and aa < z for aa, zz in taken)

    for n in quantity_numbers(text):
        a, z = n["start"], n["start"] + len(n["raw"])
        phrase = _claim_phrase(text, a, z)
        taken.append((a, a + len(phrase)))
        found.append({"phrase": phrase or n["raw"].strip(), "what": "a quantity written in words",
                      "value": n["value"], "units": list(n["units"]), "start": a})
    for what, pattern in _CLAIM_MARKERS:
        for m in pattern.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            phrase = _claim_phrase(text, m.start(), m.end())
            if not phrase or _HAS_FIGURE.search(phrase):
                continue
            taken.append((m.start(), m.start() + len(phrase)))
            found.append({"phrase": phrase, "what": what, "value": None, "units": [], "start": m.start()})
    return sorted(found, key=lambda c: c["start"])


def check_wording(text, brand, proof_ids=(), corpus=None):
    """Are the claims with no digits in them said by the brand's own material? Returns
    {"claims": [...], "unconfirmed": [plain sentences]}. Nothing here ever blocks a post: a
    sentence code cannot confirm is for the person reviewing to decide."""
    brand = as_brand(brand)
    claims = wording_claims(text)
    if not claims:
        return {"claims": [], "unconfirmed": []}
    corpus = build_corpus(brand, proof_ids) if corpus is None else corpus
    facts, _notes = load_facts(brand)
    linked, _missing = load_proof(brand, proof_ids)
    publishable = [p for p in linked if p.get("may_publish") in ("anonymised", "yes")]
    said = " ".join([brand_own_words(brand)] + [f["claim"] for f in facts]
                    + ["%s. %s" % (p.get("title") or "", p.get("detail") or "") for p in publishable])
    known = set(key_terms(said))
    out, unconfirmed = [], []
    for claim in claims:
        terms = [t for t in key_terms(claim["phrase"]) if t not in ("half", "third", "quarter", "dozen", "hundred")]
        by_words = bool(terms) and all(t in known for t in terms)
        traced = _trace(text, claim, corpus) if claim["value"] is not None else None
        confirmed = bool(by_words or (traced and traced["confirmed"]))
        out.append(dict(claim, confirmed=confirmed,
                        provenance=[p.as_dict() for p in (traced or {}).get("provenance", [])[:3]]))
        if not confirmed:
            unconfirmed.append("Nothing in %s's own files says \"%s\". %s" % (brand.name, claim["phrase"], WHAT_TO_DO))
    return {"claims": out, "unconfirmed": unconfirmed}


# ----------------------------------------------------------------------------- tracing one number
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _pieces(text):
    out, at = [], 0
    for m in _SENTENCE_SPLIT.finditer(text or ""):
        out.append((at, m.start()))
        at = m.end()
    out.append((at, len(text or "")))
    return [(a, z) for a, z in out if (text or "")[a:z].strip()]


def _sentence_around(text, start):
    """The sentence a number sits in, widened to its neighbours when it is too short to say what
    it is about. "18 hours." on a line of its own takes its subject from the lines beside it."""
    pieces = _pieces(text)
    if not pieces:
        return text or ""
    i = next((k for k, (a, z) in enumerate(pieces) if a <= start < z), len(pieces) - 1)
    window = text[pieces[i][0]:pieces[i][1]]
    if len(key_terms(window)) < 2 and len(pieces) > 1:
        window = text[pieces[max(0, i - 1)][0]:pieces[min(len(pieces) - 1, i + 1)][1]]
    return window


def _trace(text, item, corpus):
    """Match ONE number in a draft against the brand's evidence. A value alone is not a match:
    the value, what it measures, and what the sentence is about all have to agree. Returns
    {grounded, confirmed, why, provenance, best, near}. `why` says what is missing:
      ""         nothing: the evidence says this
      "context"  the same figure is in the files, but about something else
      "weak"     the only evidence for it has not been confirmed itself
      "nothing"  no evidence has this figure at all (with `near`: same value, other units)
    """
    same = [e for e in corpus.items if e.value == item["value"] and same_kind(item["units"], e.units)]
    if not same:
        return {"grounded": False, "confirmed": False, "why": "nothing", "provenance": [], "best": None,
                "near": [e for e in corpus.items if e.value == item["value"]][:2]}
    # The unit is not a subject: "18 hours" of proofing and "18 hours" saved share the word
    # "hours" and nothing else. Only the words around the figure say what it is about.
    context = set(key_terms(_sentence_around(text, item["start"]))) - _UNIT_STEMS

    def shares(e):
        return bool(context & (set(key_terms(e.snippet)) - _UNIT_STEMS))

    same.sort(key=lambda e: (shares(e), not e.weak), reverse=True)
    best = same[0]
    why = "" if shares(best) and not best.weak else ("weak" if shares(best) else "context")
    return {"grounded": True, "confirmed": not why, "why": why, "provenance": same[:3], "best": best, "near": []}


def _unconfirmed_sentence(text, item, traced, brand_name):
    """Why one number could not be confirmed, in a sentence that quotes it and says what to do."""
    best = traced["best"]
    if traced["why"] == "weak":
        return ("%s traces only to research that has not been confirmed: %s. %s"
                % (item["shown"], best.weak, WHAT_TO_DO))
    said = " ".join(_sentence_around(text, item["start"]).split())[:120]
    return ("\"%s\" states %s. The brand's files have that figure in something else: \"%s\" (%s). "
            "Point to the fact it really comes from, link the proof that shows it, or take it out."
            % (said, item["shown"], best.snippet, best.source))


def ground_draft(text, brand, proof_ids=(), corpus=None):
    """Trace every number in a draft to the brand's evidence.

    Returns a dict:
      ok               True when no number is left untraced and every linked proof id exists
      numbers          [{raw, value, structural, grounded, confirmed, provenance: [...]}]
      ungrounded       the raw numbers that traced to nothing
      unconfirmed      plain sentences about numbers that are traced but not confirmed
      attributions     credit lines for every research stat the draft used
      sources_used     who is being relied on
      unknown_proof_ids
      hints            e.g. "27 appears in proof item p-004, which is not linked to this post"
      notes            evidence files that could not be used
      explanation      one or two plain sentences

    `ok` means only that nothing is provably wrong. A draft can be `ok` and still have entries in
    `unconfirmed`; those are for a person to decide, which is why they never block.

    `corpus` is the brand's evidence when the caller already has it (checking ten slides of one
    carousel should read the brand's files once, not twenty times).
    """
    brand = as_brand(brand)
    linked, missing = load_proof(brand, proof_ids)
    corpus = build_corpus(brand, proof_ids) if corpus is None else corpus
    linked_ids = {p["proof_id"] for p in linked}

    numbers, ungrounded, attributions, sources_used = [], [], [], []
    unconfirmed, near_misses = [], []
    for n in extract_numbers(text) + spelled_numbers(text):
        entry = dict(n)
        if n["structural"]:
            entry["grounded"] = entry["confirmed"] = True
            entry["provenance"] = []
            numbers.append(entry)
            continue
        traced = _trace(text, n, corpus)
        entry["grounded"] = traced["grounded"]
        entry["confirmed"] = traced["confirmed"]
        entry["provenance"] = [p.as_dict() for p in traced["provenance"]]
        for p in traced["provenance"]:
            if p.source not in sources_used:
                sources_used.append(p.source)
            if p.kind == "research_stat" and not p.weak and p.cite() not in attributions:
                attributions.append(p.cite())
        if not traced["grounded"] and n.get("in_words") and not set(n["units"]) & {"percent", "money"}:
            # A number written out in words is as often prose as it is a figure ("past sixty
            # characters"), so one that traces to nothing is put in front of a person rather than
            # treated as an invention. Written as a share or an amount, it is a figure like any other.
            line = ("\"%s\" is written in words, and nothing in %s's files says it. %s"
                    % (n["shown"], brand.name, WHAT_TO_DO))
            if line not in unconfirmed:
                unconfirmed.append(line)
        elif not traced["grounded"]:
            if n["raw"] not in ungrounded:
                ungrounded.append(n["raw"])
            for near in traced["near"]:                  # the same figure, measuring something else
                miss = ("%s is not in %s's files. The closest match is \"%s\" (%s), which measures something else."
                        % (n["shown"], brand.name, near.snippet, near.source))
                if miss not in near_misses:
                    near_misses.append(miss)
        elif not traced["confirmed"]:
            line = _unconfirmed_sentence(text, n, traced, brand.name)
            if line not in unconfirmed:
                unconfirmed.append(line)
        numbers.append(entry)
    numbers.sort(key=lambda n: n.get("start", 0))

    hints = list(near_misses)
    if ungrounded:
        unlinked = [p for p in list_proof(brand) if p["proof_id"] not in linked_ids]
        for p in unlinked:
            shown = _values_in("%s. %s" % (p.get("title") or "", p.get("detail") or ""))
            for n in numbers:
                if not n["grounded"] and n["value"] in shown:
                    hint = ("%s appears in proof item %s (\"%s\"), which is not linked to this post. "
                            "Link it if that is where the number comes from."
                            % (n["raw"], p["proof_id"], (p.get("title") or "")[:60]))
                    if hint not in hints:
                        hints.append(hint)

    claims = [n for n in numbers if not n["structural"]]
    if missing:
        explanation = ("This post links proof that is not in %s's proof library: %s. Nothing can be checked "
                       "against it." % (brand.name, ", ".join(missing)))
    elif not claims:
        explanation = "The draft states no numbers, so there is nothing to trace."
    elif ungrounded:
        where = ("%s has no facts, research stats or linked proof yet. " % brand.name) if not len(corpus) else ""
        explanation = ("%sThese numbers do not trace to anything in the brand's files: %s. %s"
                       % (where, ", ".join(ungrounded), HOW_TO_ADD_A_FACT))
    elif unconfirmed:
        explanation = ("Every number in the draft appears in the brand's files, but %d of them cannot be confirmed "
                       "as this claim." % len(unconfirmed))
    else:
        explanation = "Every number in the draft traces to the brand's own facts, research or linked proof."

    return {"ok": not ungrounded and not missing, "numbers": numbers, "ungrounded": ungrounded,
            "unconfirmed": unconfirmed, "attributions": attributions, "sources_used": sources_used,
            "unknown_proof_ids": missing, "hints": hints, "notes": list(corpus.notes),
            "corpus_size": len(corpus), "explanation": explanation}


# ----------------------------------------------------------------------------- words inside a picture
def resolve_source_pointer(brand, source):
    """A `source` written on a picture, resolved. "fact:<id>" and "proof:<id>" point into the
    brand's own files; anything else is a label somebody typed.

    Returns {pointer, ok, shown, numbers}. `shown` is what a reader should be shown instead of
    the pointer (the real source), and `numbers` are the figures that fact or proof item states,
    so that a pointer only confirms the figure it actually holds."""
    brand = as_brand(brand)
    text = str(source or "").strip()
    low = text.lower()
    if low.startswith("fact:"):
        for f in load_facts(brand)[0]:
            if f["id"] == text[5:].strip():
                return {"pointer": True, "ok": True, "shown": f["source"],
                        "numbers": _evidence_from(f["claim"], "brand_fact", f["source"], f["id"])}
        return {"pointer": True, "ok": False, "shown": "", "numbers": []}
    if low.startswith("proof:"):
        found, _missing = load_proof(brand, [text[6:].strip()])
        if found and found[0].get("may_publish") in ("anonymised", "yes"):
            p = found[0]
            body = "%s. %s" % (p.get("title") or "", p.get("detail") or "")
            return {"pointer": True, "ok": True, "shown": str(p.get("source") or "").strip(),
                    "numbers": _evidence_from(body, "proof", p.get("source") or "the proof library", p["proof_id"])}
        return {"pointer": True, "ok": False, "shown": "", "numbers": []}
    return {"pointer": False, "ok": bool(text), "shown": text, "numbers": []}


def check_drawn_text(brand, texts, source="", proof_ids=(), corpus=None):
    """The claims in the words drawn ON one picture, each with whether the brand's files confirm
    it: [{phrase, what, confirmed, why}].

    A picture carries no explanation, so a `source` line written on it counts only when it POINTS
    into the brand's own files AND that fact or proof item really states the figure. A source
    somebody typed is a caption, not evidence, and never turns an unchecked number into a checked
    one."""
    brand = as_brand(brand)
    joined = "\n".join(str(t) for t in texts if str(t or "").strip())
    if not joined.strip():
        return []
    corpus = build_corpus(brand, proof_ids) if corpus is None else corpus
    pointer = resolve_source_pointer(brand, source)
    report = ground_draft(joined, brand, proof_ids, corpus=corpus)
    said = check_wording(joined, brand, proof_ids, corpus=corpus)
    out = []
    for n in report["numbers"]:
        if n["structural"]:
            continue
        by_pointer = any(e.value == n["value"] and same_kind(n["units"], e.units) and not e.weak
                         for e in pointer["numbers"])
        confirmed = bool(n["confirmed"] or by_pointer)
        out.append({"phrase": n["shown"], "what": "a figure", "confirmed": confirmed,
                    "why": "" if confirmed else _why_not_drawn(brand, source, pointer)})
    for claim in said["claims"]:
        out.append({"phrase": claim["phrase"], "what": claim["what"], "confirmed": claim["confirmed"],
                    "why": "" if claim["confirmed"] else "nothing in %s's own files says it" % brand.name})
    return out


def _why_not_drawn(brand, source, pointer):
    text = str(source or "").strip()
    if pointer["pointer"] and not pointer["ok"]:
        return "the source written on it (\"%s\") does not point at anything in %s's files" % (text[:60], brand.name)
    if pointer["pointer"]:
        return "the fact it points at does not state that figure"
    if text:
        return "the source written on it (\"%s\") is a label %s's files cannot confirm" % (text[:60], brand.name)
    return "nothing in %s's files states it" % brand.name


# ----------------------------------------------------------------------------- facts for a contract
_WORD = re.compile(r"[a-z][a-z'-]{3,}")


def _overlap(a, b):
    return len(set(_WORD.findall(a.lower())) & set(_WORD.findall(b.lower())))


def facts_for_topic(brand, topic_text, proof_ids=(), max_facts=40, max_stats=15):
    """What a writer may lean on for one topic: the brand's facts, the research stats closest to
    the subject, and the linked proof. Ranked by shared words with the topic, then file order."""
    brand = as_brand(brand)
    facts, notes = load_facts(brand)
    research, more = _research_values(brand)
    linked, missing = load_proof(brand, proof_ids)

    ranked_facts = sorted(enumerate(facts), key=lambda t: (-_overlap(topic_text, t[1]["claim"]), t[0]))
    seen, stats = set(), []
    for item in research:
        if item.snippet in seen:
            continue
        seen.add(item.snippet)
        stats.append(item)
    ranked_stats = sorted(enumerate(stats), key=lambda t: (-_overlap(topic_text, t[1].snippet), t[0]))

    return {"facts": [f for _i, f in ranked_facts[:max_facts]],
            "stats": [{"finding": s.snippet, "source": s.source, "url": s.url, "confidence": s.confidence,
                       "file": s.ref, "confirmed": not s.weak, "not_confirmed_because": s.weak}
                      for _i, s in ranked_stats[:max_stats]],
            "stats_left_out": max(0, len(stats) - max_stats),
            "proof": linked, "unknown_proof_ids": missing, "notes": notes + more}


def dumps(report):
    return json.dumps(report, indent=2, ensure_ascii=False)
