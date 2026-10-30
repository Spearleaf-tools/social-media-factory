"""quality.py - does the reader walk away with something? The takeaway gate, plus style notes.

Clean, on-voice copy can still be empty. This gate asks three things of every post before it goes
to review, and each is a mechanical pre-screen, so it costs nothing to run:

  1. A CONCRETE MOVE. The body gives the reader something specific: an instruction ("Weigh the
     flour"), a numbered or bulleted list, a script they could copy, or at least two specific
     terms from the brand's OWN vocabulary (the names in its offers and pillars). The vocabulary
     comes from the brand, so the check means the same thing for a bakery and a clinic.
  2. A PROMISE IN THE FIRST LINE that the reader can hold the post to: a number, a list
     ("3 checks"), "here is ...", or "how / why ...". A bare rhetorical question or a teaser
     promises nothing, so it fails, which pushes the promise up into the hook where it belongs.
  3. A RECEIPT. An evergreen post carries a real figure in the text, or has proof attached, or
     is honestly labelled lane="opinion". News and opinion posts are excused.

On top of the pre-screens sits a judged rubric: whoever reviews the draft (Claude, or a person)
scores it 1 to 5. Two scores are floors: `value` and `promise_kept` must both be 4 or more, or
the post is held. The pre-screens are arithmetic; the scores are judgement. Fill them honestly.

`style_notes()` is advisory only. It points at habits that make copy read as machine-written,
and each note says when the pattern is fine. It never blocks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from smf.studio.files import as_brand
from smf.studio.grounding import STRUCTURAL_NOUNS

CRAFT_CRITERIA = ("on_voice", "specific", "one_idea", "proof", "earns_save", "first_line")
CRAFT_PASS_TOTAL = 24           # out of 30
CRAFT_MIN_EACH = 3
TAKEAWAY_CRITERIA = ("value", "promise_made", "promise_kept", "route", "authority")
TAKEAWAY_FLOORS = {"value": 4, "promise_kept": 4}

LANES = ("evergreen", "news", "opinion")


@dataclass
class RubricScore:
    """Scores from 1 to 5, given by whoever judged the draft. This class only holds and weighs them."""
    # craft (advisory)
    on_voice: int = None
    specific: int = None
    one_idea: int = None
    proof: int = None
    earns_save: int = None
    first_line: int = None
    # takeaway (value and promise_kept are floors)
    value: int = None           # the reader gets something concrete to act on
    promise_made: int = None    # the first line commits to something checkable
    promise_kept: int = None    # the body delivers exactly that, before any ask
    route: int = None           # it leads the reader toward more from this brand
    authority: int = None       # it shows earned know-how, not general knowledge
    notes: list = field(default_factory=list)

    @staticmethod
    def _valid(v):
        return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5

    def craft(self):
        return {c: getattr(self, c) for c in CRAFT_CRITERIA}

    def takeaway(self):
        return {c: getattr(self, c) for c in TAKEAWAY_CRITERIA}

    def craft_passed(self):
        """True or False once every craft score is in; None while any is missing."""
        scores = list(self.craft().values())
        if not all(self._valid(v) for v in scores):
            return None
        return sum(scores) >= CRAFT_PASS_TOTAL and min(scores) >= CRAFT_MIN_EACH

    def as_dict(self):
        scores = list(self.craft().values())
        return {"craft": self.craft(), "craft_total": sum(scores) if all(self._valid(v) for v in scores) else None,
                "craft_passed": self.craft_passed(), "takeaway": self.takeaway(), "notes": list(self.notes)}


# ----------------------------------------------------------------------------- 1. a concrete move
_SCRIPT = re.compile(r"[\"“][^\"“”]{25,}[\"”]")
_STEP_LIST = re.compile(r"(?m)^\s*(?:\d+[.)]\s|[-*•]\s)\S")
_ACTION_VERBS = (
    "add|ask|audit|book|bring|build|call|change|check|choose|claim|clean|close|compare|copy|count|cut|do|draw|drop|"
    "email|feed|fill|find|fix|fold|get|give|go|grab|hold|keep|leave|let|list|look|make|map|mark|measure|mix|move|"
    "note|open|pick|plan|post|press|print|pull|put|read|record|remove|replace|reply|request|rest|review|run|save|"
    "say|search|send|set|share|show|sit|skip|slow|sort|stand|start|stop|stretch|swap|take|tell|test|time|track|"
    "try|turn|update|use|verify|wait|walk|warm|wash|watch|weigh|write")
_IMPERATIVE = re.compile(r"(?:^|[.!?:]\s+|\n\s*(?:\d+[.)]\s+|[-*•]\s+)?)(?:" + _ACTION_VERBS + r")\b(?!\s+(?:is|are|was|were)\b)",
                         re.IGNORECASE)

_STOPWORDS = frozenset("""about after again also always another around because before being best better between both
brand business company could does doing done each every first from gets give good great have help here into just know
like made make many more most much need never often only other over people really same should since some such than that
their them then there these they thing things this those through time today under very want what when where which while
will with without work would your yours ours service services offer offers product products class classes course
programme program plan plans session sessions""".split())
_TERM = re.compile(r"[a-z][a-z'-]{3,}")


def brand_vocabulary(brand):
    """The specific words this brand owns: the names in its offers and pillars, minus everyday
    words. Full names count too ("weekend baking class"), so naming an offer is recognised."""
    brand = as_brand(brand)
    words, names = set(), set()
    for group in (brand.data.get("offers") or [], brand.data.get("pillars") or []):
        for item in group:
            name = str(item.get("name") or "").strip().lower()
            if len(name.split()) >= 2:
                names.add(" ".join(name.split()))
            for text in (name, str(item.get("what") or "").lower(), str(item.get("about") or "").lower()):
                for w in _TERM.findall(text):
                    if w not in _STOPWORDS:
                        words.add(w)
    return {"words": words, "names": names}


def _vocabulary_hits(text, vocabulary):
    low = " ".join((text or "").lower().split())
    hits = {n for n in vocabulary["names"] if n in low}
    covered = {w for n in hits for w in n.split()}
    for w in vocabulary["words"] - covered:
        stem = w[:-1] if w.endswith("s") and len(w) > 4 else w
        if re.search(r"(?<![a-z])" + re.escape(stem) + r"(?:s|es)?(?![a-z])", low):
            hits.add(w)
    return sorted(hits)


def concrete_move(text, vocabulary=None):
    terms = _vocabulary_hits(text, vocabulary) if vocabulary else []
    found = {"instruction": bool(_IMPERATIVE.search(text or "")), "list": bool(_STEP_LIST.search(text or "")),
             "script": bool(_SCRIPT.search(text or "")), "brand_terms": terms}
    found["ok"] = found["instruction"] or found["list"] or found["script"] or len(terms) >= 2
    return found


# ----------------------------------------------------------------------------- 2. a promise in the hook
# A figure that could be a receipt: 240+, 41%, a price, any number of two or more digits, 3x, or a
# small number counting real things ("7 loaves"). A small number counting the post's own parts
# ("3 tips") is structure, not a receipt, and a lone list marker never counts.
_RECEIPT = re.compile(
    r"\d[\d,]*\s?\+|\d[\d,.]*\s?%|[$£€]\s?\d|\b\d{2,}(?:[.,]\d+)?\b|\b\d+(?:\.\d+)?\s?x\b"
    r"|\b\d+\s+(?!(?:\w+\s+){0,2}?(?:" + STRUCTURAL_NOUNS + r")\b)[a-z]{3,}", re.IGNORECASE)
_HOOK_LIST = re.compile(r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+(?:\w+\s+){0,2}?(?:"
                        + STRUCTURAL_NOUNS + r")\b", re.IGNORECASE)
_HOOK_HERE = re.compile(r"\bhere(?:'s|’s| is| are)\b", re.IGNORECASE)
_HOOK_HOW_WHY = re.compile(r"\b(?:how|why)\s+(?:to|i|we|you|your|the|a|an|our|my)\b", re.IGNORECASE)
_HOOK_TEASE = re.compile(r"\b(?:i\s+dare\s+you|go\s+ask|go\s+check|you\s+won'?t\s+believe|wait\s+for\s+it)\b", re.IGNORECASE)


def first_line(text):
    t = (text or "").strip()
    m = re.search(r"[.!?\n]", t)
    hook = t[:m.start() + 1] if m and t[m.start()] == "?" else (t[:m.start()] if m else t)
    return hook[:220].strip()


def hook_promise(text):
    hook = first_line(text)
    has_number = bool(re.search(r"\d", hook))
    has_list = bool(_HOOK_LIST.search(hook))
    made = has_list or has_number or bool(_HOOK_HERE.search(hook)) or bool(_HOOK_HOW_WHY.search(hook))
    reason = ""
    if hook.endswith("?") and not (has_list or has_number):
        made, reason = False, "the first line is a question with no number or list, so it promises nothing"
    elif _HOOK_TEASE.search(hook) and not (has_list or has_number):
        made, reason = False, "the first line is a teaser, not a statement of what the reader will get"
    elif not made:
        reason = "the first line states no number, no list, no \"here is\", and no how or why"
    return {"made": made, "reason": reason, "hook": hook}


# ----------------------------------------------------------------------------- 3. a receipt
def has_receipt(text):
    return bool(_RECEIPT.search(text or ""))


# ----------------------------------------------------------------------------- the gate
def takeaway_prescreen(text, brand, lane="evergreen", has_proof=False):
    brand = as_brand(brand)
    lane = lane or "evergreen"
    move = concrete_move(text, brand_vocabulary(brand))
    hook = hook_promise(text)
    receipt = has_receipt(text)
    holds = []
    if not move["ok"]:
        holds.append("There is no concrete move for the reader. Give one clear instruction, a short numbered list, "
                     "a line they could copy, or name the specific things %s actually does." % brand.name)
    if not hook["made"]:
        holds.append("The first line makes no promise: %s." % hook["reason"])
    if lane == "evergreen" and not (receipt or has_proof):
        holds.append("There is no receipt: no real figure in the text and no proof attached. Add a fact the brand "
                     "can back up, attach proof, or label the topic as opinion.")
    return {"holds": holds, "concrete_move": move, "hook_promise": hook, "has_receipt": receipt,
            "has_proof": bool(has_proof), "lane": lane}


def takeaway_gate(text, brand, lane="evergreen", has_proof=False, rubric=None):
    """The full gate. `passed` False means hold the post and revise it; do not send it to review."""
    pre = takeaway_prescreen(text, brand, lane=lane, has_proof=has_proof)
    holds = list(pre["holds"])
    scores = None
    if rubric is not None:
        scores = rubric.takeaway()
        for name, floor in TAKEAWAY_FLOORS.items():
            v = getattr(rubric, name)
            if RubricScore._valid(v) and v < floor:
                holds.append("The reviewer scored %s at %d; it has to be %d or more for the post to go out."
                             % (name.replace("_", " "), v, floor))
    return {"passed": not holds, "holds": holds, "prescreen": pre, "scores": scores, "lane": pre["lane"]}


# ----------------------------------------------------------------------------- style notes (advisory)
_OWNED_PAST = re.compile(r"\b(?:i|we)\s+(?:\w+\s+){0,2}?(?:transformed|rebuilt|turned|grew|fixed|moved|changed|built)\b",
                         re.IGNORECASE)
_CONCRETE_HINT = re.compile(r"\d")
_STYLE_CHECKS = [
    ("inflated-weight",
     re.compile(r"\b(?:a\s+pivotal\s+(?:moment|role)|lasting\s+legacy|watershed\s+moment|mark(?:ed|s|ing)?\s+a\s+turning\s+point"
                r"|underscor(?:es|ed|ing)\s+the\s+importance)\b", re.IGNORECASE),
     "Big-moment framing. Fine only when the evidence in the post really is that big."),
    ("trailing-ing-clause",
     re.compile(r",\s+(?:highlighting|showcasing|underscoring|reflecting|emphasi[sz]ing|demonstrating|signal+ing|"
                r"cementing|solidifying)\s+[^.!?\n]{3,}", re.IGNORECASE),
     "A trailing -ing clause that claims a meaning the post has not earned. Cut it, or state the fact."),
    ("brochure-adjective",
     re.compile(r"\b(?:seamless(?:ly)?|effortless(?:ly)?|stunning|unmatched|exceptional|remarkable|transformative|"
                r"incredible|truly)\b", re.IGNORECASE),
     "A brochure adjective. Let the fact or the figure carry the weight instead."),
    ("borrowed-authority",
     re.compile(r"\b(?:experts?\s+(?:agree|believe)|studies\s+(?:suggest|indicate)|research\s+(?:shows|indicates)|"
                r"many\s+people\s+(?:say|believe)|some\s+say|it'?s\s+widely\s+known|industry\s+leaders)\b", re.IGNORECASE),
     "Authority with no name. Name the source from the brand's research, or drop the claim."),
    ("fancy-is",
     re.compile(r"\b(?:serves?\s+as|stands?\s+as|functions?\s+as|acts?\s+as|represents?\s+a)\b", re.IGNORECASE),
     "A dressed-up way of saying 'is'. Fine when it is literally a role; otherwise say 'is'."),
    ("empty-range",
     re.compile(r"\beverything\s+from\s+[^.!?\n\d]{2,40}\s+to\s+[^.!?\n\d]{2,40}", re.IGNORECASE),
     "'Everything from X to Y' with nothing measurable. A real range with figures is fine."),
    ("announcing-the-post",
     re.compile(r"\b(?:in\s+this\s+post|let'?s\s+(?:unpack|get\s+started)|first,\s+let'?s|here'?s\s+the\s+thing:)", re.IGNORECASE),
     "This announces the post instead of starting it. Open with the substance."),
    ("hollow-ending",
     re.compile(r"\b(?:at\s+the\s+end\s+of\s+the\s+day|ultimately,\s+it'?s\s+about|here'?s\s+to\s+the)\b", re.IGNORECASE),
     "A rising, empty sign-off. End on the takeaway, a real question, or the planned call to action."),
]
_PROMISE_VERB = re.compile(r"\b(?:will|can|to)\s+(?:transform|revolutioni[sz]e|elevate|empower|unlock)\b"
                           r"|\b(?:transform|elevate|empower|unlock)\s+your\b", re.IGNORECASE)
_TRIPLET = re.compile(r"\b([A-Za-z]{3,12}),\s+([A-Za-z]{3,12}),?\s+and\s+([A-Za-z]{3,12})\b")
_NO_NO_NO = re.compile(r"\b(no|more|less|zero)\s+\w+,\s+\1\s+\w+,\s+(?:and\s+)?\1\s+\w+", re.IGNORECASE)


def style_notes(text):
    """Advisory notes: [{signal, excerpt, note}]. Nothing here blocks a post."""
    text = text or ""
    out = []

    def add(signal, match, note):
        out.append({"signal": signal, "excerpt": match.group(0).strip()[:80], "note": note})

    for signal, pattern, note in _STYLE_CHECKS:
        for m in pattern.finditer(text):
            add(signal, m, note)
    for m in _PROMISE_VERB.finditer(text):
        # Reporting something the speaker really did ("we rebuilt the oven") is not a sales promise.
        if _OWNED_PAST.search(text[max(0, m.start() - 60):m.end() + 20]):
            continue
        add("sales-promise-verb", m, "A promise verb aimed at the reader. Saying what you actually did, in the past "
                                     "tense, is fine.")
    for m in _TRIPLET.finditer(text):
        if _CONCRETE_HINT.search(text[max(0, m.start() - 20):m.end() + 20]):
            continue
        add("rhythm-of-three", m, "Three abstract words in a row. Fine for three real things; padding otherwise.")
    for m in _NO_NO_NO.finditer(text):
        add("rhythm-of-three", m, "'No X, no Y, no Z' is almost always padding.")
    return out
