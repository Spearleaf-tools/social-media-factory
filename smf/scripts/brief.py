"""brief.py - the script file: what is said, what is shown, and where each fact comes from.

One script is one Markdown file that a person can read top to bottom and a tool can read without
guessing. Every field is one labelled line, so nothing a person says on camera can hide in an
unlabelled paragraph and miss the checks or the teleprompter.

    # Why a loaf comes out dense

    - Brand: maple-and-main
    - Batch: october-week-1
    - Script: 03
    - Speaker: person
    - Job: trust
    - Pillar: fix-my-loaf
    - Format: talking to camera
    - Length: 40 seconds
    - Hook pattern: a belief corrected
    - Comes from: audience.questions_they_ask[0]

    ## The one idea
    A dense loaf is usually dough that went into the oven before it had proofed enough.

    ## Opening
    Promise: how to tell whether dough has proofed enough
    On screen: Dense loaf? Check the proof
    Show: Two cut loaves side by side, one dense, one open.
    Say: A dense loaf is rarely the flour. It is the proof.

    ## Line 1
    Say: Our dough ferments for at least 18 hours.
    Show: The dough tub with yesterday's time written on the lid.
    On screen: 18 hours
    Source: fact:ferment-18h

    ## Call to action
    Kind: question
    Say: What does your dough do when you press it?
    Show: Ava presses the dough and looks up.

    ## To shoot this
    - Two loaves, one under-proofed, both cut in half

The three parts of the opening (the words on screen, the first picture, the first spoken line)
sit together under one promise so they can be checked against each other. `Say` is what goes to
the teleprompter. `Show` is the visual direction, and every spoken line has one. `Source` says
where a fact comes from, in the same pointer style the topic planner uses ("fact:<id>",
"proof:<id>", a file inside the brand's folder, "audience.questions_they_ask[2]").

Anything between <!-- and --> is guidance for the writer and is ignored everywhere.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

JOBS = ("reach", "lead_gen", "trust")
_JOB_WORDS = {"reach": "reach", "leads": "lead_gen", "lead": "lead_gen", "lead gen": "lead_gen",
              "lead-gen": "lead_gen", "lead_gen": "lead_gen", "leadgen": "lead_gen", "trust": "trust"}
JOB_NAMES = {"reach": "reach", "lead_gen": "leads", "trust": "trust"}

# How a script may end, and which jobs may use each ending. Only a leads script may point at
# something the brand sells; a reach script asks for a save, a send or a follow; a trust script
# asks a real question or asks for nothing.
CTA_KINDS = {
    "offer": ("lead_gen",), "keyword": ("lead_gen",),
    "save": ("reach",), "share": ("reach",), "follow": ("reach",),
    "question": ("trust", "lead_gen"), "none": ("trust", "lead_gen"),
}

HEADER_KEYS = ("brand", "batch", "script", "speaker", "job", "pillar", "format", "length", "hook pattern",
               "platforms", "comes from", "proof")
_LABELS = {
    "say": "say", "says": "say", "spoken": "say",
    "show": "show", "picture": "show", "visual": "show",
    "on screen": "on_screen", "on-screen": "on_screen", "text on screen": "on_screen",
    "source": "source", "sources": "source",
    "promise": "promise", "kind": "kind", "offer": "offer", "keyword": "keyword",
}
_SECTION_FIELDS = {
    "opening": ("promise", "on_screen", "show", "say", "source"),
    "line": ("say", "show", "on_screen", "source"),
    "cta": ("kind", "say", "show", "on_screen", "offer", "keyword", "source"),
}

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FIELD = re.compile(r"^\s*(?:[-*]\s+)?\*{0,2}([A-Za-z][A-Za-z -]{0,24}?)\*{0,2}\s*:\*{0,2}\s*(.*?)\s*$")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)\s*$")
_LENGTH = re.compile(r"(\d{1,3})")
_PLACEHOLDER = re.compile(r"\bTODO\b")


def is_filled(value):
    """A field counts once a person or a writer has replaced its placeholder."""
    return bool(value and value.strip()) and not _PLACEHOLDER.search(value)


def normalise_job(text):
    """'leads', 'lead gen' and 'lead_gen' all mean the same job. Anything else returns None."""
    return _JOB_WORDS.get(re.sub(r"\s+", " ", str(text or "").strip().lower()))


@dataclass
class Opening:
    promise: str = ""
    on_screen: str = ""
    show: str = ""
    say: str = ""
    source: str = ""


@dataclass
class Line:
    number: int = 0
    say: str = ""
    show: str = ""
    on_screen: str = ""
    source: str = ""


@dataclass
class CallToAction:
    kind: str = ""
    say: str = ""
    show: str = ""
    on_screen: str = ""
    offer: str = ""
    keyword: str = ""
    source: str = ""
    present: bool = False          # was there a "Call to action" section at all


@dataclass
class Brief:
    title: str = ""
    header: dict = field(default_factory=dict)
    idea: str = ""
    opening: Opening = field(default_factory=Opening)
    lines: list = field(default_factory=list)
    cta: CallToAction = field(default_factory=CallToAction)
    shoot_notes: list = field(default_factory=list)
    problems: list = field(default_factory=list)      # trouble reading the file, in plain words

    @property
    def job(self):
        return normalise_job(self.header.get("job"))

    @property
    def speaker(self):
        return (self.header.get("speaker") or "").strip()

    @property
    def length_seconds(self):
        m = _LENGTH.search(self.header.get("length") or "")
        return int(m.group(1)) if m else None

    @property
    def platforms(self):
        return [p.strip().lower() for p in re.split(r"[,;]", self.header.get("platforms") or "") if p.strip()]

    @property
    def proof_ids(self):
        return [p.strip() for p in re.split(r"[,;]", self.header.get("proof") or "") if p.strip()]

    def spoken(self):
        """Everything said on camera, in order: [(where, text)]. A placeholder that has not been
        filled in yet is not speech, so it never reaches a word count or a teleprompter."""
        out = []
        if is_filled(self.opening.say):
            out.append(("The opening", self.opening.say))
        out += [("Line %d" % ln.number, ln.say) for ln in self.lines if is_filled(ln.say)]
        if is_filled(self.cta.say):
            out.append(("The call to action", self.cta.say))
        return out

    @property
    def unwritten(self):
        """True for a starter file nobody has filled in yet: there is nothing to check."""
        return not self.spoken()

    def spoken_words(self):
        return sum(len(text.split()) for _where, text in self.spoken())


# ----------------------------------------------------------------------------- reading
def _section_kind(heading):
    h = re.sub(r"\s+", " ", heading.strip().lower())
    if h.startswith("the one idea") or h == "one idea" or h == "idea":
        return "idea", None
    if h.startswith("opening"):
        return "opening", None
    m = re.match(r"^line\s+(\d{1,2})\b", h)
    if m:
        return "line", int(m.group(1))
    if h.startswith("call to action") or h == "cta":
        return "cta", None
    if h.startswith("to shoot this") or h.startswith("shoot notes") or h.startswith("to film this"):
        return "shoot", None
    return "other", None


def parse(text):
    """Read a script file into a Brief. Never raises on odd content: anything that could not be
    understood is described in `brief.problems`, so the person is told instead of the tool guessing."""
    brief = Brief()
    body = _COMMENT.sub("", text or "")
    kind, target = "top", None
    idea_lines = []
    seen_lines = set()

    for raw in body.splitlines():
        line = raw.rstrip()
        h = _HEADING.match(line)
        if h:
            level, heading = len(h.group(1)), h.group(2)
            if level == 1:
                if not brief.title:
                    brief.title = heading.strip()
                kind, target = "top", None
                continue
            kind, number = _section_kind(heading)
            target = None
            if kind == "opening":
                target = brief.opening
            elif kind == "cta":
                brief.cta.present = True
                target = brief.cta
            elif kind == "line":
                if number in seen_lines:
                    brief.problems.append("There are two sections called 'Line %d'. Number each line once." % number)
                seen_lines.add(number)
                target = Line(number=number)
                brief.lines.append(target)
            continue

        if not line.strip():
            continue

        if kind == "top":
            m = _FIELD.match(line)
            key = re.sub(r"\s+", " ", m.group(1).strip().lower()) if m else ""
            if m and key in HEADER_KEYS:
                brief.header[key] = m.group(2).strip()
            continue
        if kind == "idea":
            idea_lines.append(line.strip())
            continue
        if kind == "shoot":
            b = _BULLET.match(line)
            brief.shoot_notes.append(b.group(1) if b else line.strip())
            continue
        if kind == "other":
            continue

        # opening, line, cta: every line must be a labelled field
        where = {"opening": "the opening", "cta": "the call to action"}.get(kind) or "Line %d" % target.number
        m = _FIELD.match(line)
        name = _LABELS.get(re.sub(r"\s+", " ", m.group(1).strip().lower())) if m else None
        if not name or name not in _SECTION_FIELDS[kind]:
            brief.problems.append("In %s there is text with no label the tools know (\"%s\"). Start it with "
                                  "Say:, Show:, On screen: or Source:, or it is left out of the checks and the "
                                  "teleprompter." % (where, line.strip()[:70]))
            continue
        if getattr(target, name):
            brief.problems.append("In %s, '%s' appears twice. Keep one, or start a new Line." % (where, m.group(1).strip()))
            continue
        setattr(target, name, m.group(2).strip())

    brief.idea = " ".join(idea_lines).strip()
    brief.lines.sort(key=lambda ln: ln.number)
    brief.cta.kind = brief.cta.kind.strip().lower()
    return brief


# ----------------------------------------------------------------------------- writing
def _field_line(label, value):
    return "%s: %s" % (label, value) if value else None


def render(brief):
    """The file for a Brief. parse(render(b)) gives the same script back."""
    out = ["# %s" % (brief.title or "Untitled script"), ""]
    for key in HEADER_KEYS:
        if brief.header.get(key):
            out.append("- %s: %s" % (key[0].upper() + key[1:], brief.header[key]))
    out += ["", "## The one idea", "", brief.idea or "", "", "## Opening", ""]
    o = brief.opening
    out += [x for x in (_field_line("Promise", o.promise), _field_line("On screen", o.on_screen),
                        _field_line("Show", o.show), _field_line("Say", o.say), _field_line("Source", o.source)) if x]
    for ln in brief.lines:
        out += ["", "## Line %d" % ln.number, ""]
        out += [x for x in (_field_line("Say", ln.say), _field_line("Show", ln.show),
                            _field_line("On screen", ln.on_screen), _field_line("Source", ln.source)) if x]
    c = brief.cta
    out += ["", "## Call to action", ""]
    out += [x for x in (_field_line("Kind", c.kind), _field_line("Offer", c.offer), _field_line("Keyword", c.keyword),
                        _field_line("Say", c.say), _field_line("Show", c.show),
                        _field_line("On screen", c.on_screen), _field_line("Source", c.source)) if x]
    out += ["", "## To shoot this", ""]
    out += ["- %s" % n for n in brief.shoot_notes]
    return "\n".join(out).rstrip() + "\n"


STARTER_GUIDE = """<!--
HOW TO FILL THIS IN (this note is ignored by the tools; you can leave it or delete it)

One script, one idea. Every field is ONE line and starts with its label.
  Say:        the words spoken on camera. Short enough to say in one breath.
  Show:       what the viewer sees while that is said. Every Say needs a Show.
  On screen:  a few words of text on screen (optional, except in the Opening).
  Source:     where a fact comes from: fact:<id>, proof:<id>, a file in the brand's folder,
              or audience.questions_they_ask[0]. Any line that states a number needs one.
              Write facts with digits (18 hours, not eighteen hours) so they can be checked.

The Opening's three parts (On screen, Show, Say) must all make the SAME promise, and each must
name the subject of that promise. The opening never states a fact the brand cannot back.
Add "## Line 2", "## Line 3" and so on as you need them. Replace every TODO.
-->"""


def starter(title, brand_id, batch, script_id, speaker, job, pillar="", comes_from="", hook="", angle="",
            length=45, cta=None, platforms=""):
    """A script file with the header filled in from an approved pitch and every section waiting to
    be written. The labels are already in place, so a writer fills blanks instead of inventing a layout."""
    cta = cta or {}
    head = ["# %s" % title, "",
            "- Brand: %s" % brand_id, "- Batch: %s" % batch, "- Script: %s" % script_id,
            "- Speaker: %s" % speaker, "- Job: %s" % JOB_NAMES.get(job, job)]
    if pillar:
        head.append("- Pillar: %s" % pillar)
    head += ["- Format: TODO (talking to camera, hands in frame, screen recording, voice over footage, side by side)",
             "- Length: %d seconds" % length,
             "- Hook pattern: TODO (the opening pattern you chose, in a few words)"]
    if platforms:
        head.append("- Platforms: %s" % platforms)
    if comes_from:
        head.append("- Comes from: %s" % comes_from)
    out = head + ["", STARTER_GUIDE, "", "## The one idea", ""]
    out.append("TODO: the single point this video makes, in one sentence.%s" % ((" Angle agreed in the pitch: " + angle) if angle else ""))
    out += ["", "## Opening", "", "Promise: TODO what the viewer will get, in a few plain words",
            "On screen: %s" % (hook or "TODO"), "Show: TODO the first picture. It shows the subject of the promise.",
            "Say: TODO the first spoken line. It makes the same promise.",
            "", "## Line 1", "", "Say: TODO", "Show: TODO",
            "", "## Line 2", "", "Say: TODO", "Show: TODO",
            "", "## Call to action", ""]
    if cta.get("instruction"):
        out.append("<!-- Chosen for this script's job: %s%s -->"
                   % (cta["instruction"], (" The brand's own wording: \"%s\"" % cta["text"]) if cta.get("text") else ""))
    out.append("Kind: %s" % (cta.get("kind") or "TODO"))
    if cta.get("offer"):
        out.append("Offer: %s" % cta["offer"])
    if cta.get("keyword"):
        out.append("Keyword: %s" % cta["keyword"])
    if (cta.get("kind") or "") != "none":
        out += ["Say: TODO", "Show: TODO"]
    out += ["", "## To shoot this", "", "- TODO what to have to hand when filming"]
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- fingerprints
def spoken_sha(brief):
    """A fingerprint of exactly what is said, in order. The teleprompter is made from this and
    nothing else, so a teleprompter is out of date when (and only when) this changes."""
    joined = "\n".join(re.sub(r"\s+", " ", text).strip() for _where, text in brief.spoken())
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20]


def text_sha(text):
    """A fingerprint of a whole file, ignoring how its lines end (Windows and Mac differ)."""
    return hashlib.sha256((text or "").replace("\r\n", "\n").encode("utf-8")).hexdigest()[:20]
