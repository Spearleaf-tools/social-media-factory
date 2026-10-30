"""script.py - the long-form script file, the checks on it, and the teleprompter cut.

THE SCRIPT IS THE PERSON'S OWN WORDS
A long video is not written from a blank page. The person talks the subject through (a voice
note, a recording, an answer typed in the conversation), and the script is that, tidied for
speaking: repeats removed, the order fixed, sentences shortened so they can be said in one breath.
Nothing is added that they did not say, and every fact in it has to trace to the brand's files.

The file lives in the video's folder as `script.md`, and uses the same labels as the short-form
scripts so nothing a person says on camera can hide in an unlabelled paragraph:

    # How do I know when dough has proofed enough?

    ## The dough that looked ready
    Say: This loaf looked ready. It was not.
    Say: Our dough ferments for at least 18 hours, and this one had twelve.
    Show: The dense loaf cut open, held to the lens.
    On screen: Looked ready. Was not.
    Source: fact:ferment-18h

`Say` is what is spoken (and the only thing that reaches the teleprompter). A `Say` may run on
over the following lines until a blank line or the next label. `Show` is what the viewer sees.
`On screen` is text drawn over the picture. `Source` says where a fact comes from. Anything
between <!-- and --> is guidance for the writer and is ignored everywhere.

THE TELEPROMPTER
`teleprompter.txt` holds only the spoken words: no labels, no headings, no directions, in short
lines paced for reading at a glance. The pacing and the stripping of markings are the same ones
the short-form scripts use (`smf.scripts.teleprompter`), so a person reads the same kind of file
whichever kind of video they are filming. The file is made from the script, never edited by
hand; a stamp in the video's record says whether it is current, out of date, edited or missing.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field

from smf.scripts import teleprompter as spoken_words
from smf.studio import grounding
from smf.youtube import YouTubeError, as_brand, read_text, write_text
from smf.youtube import titles as T

SCRIPT_NAME = "script.md"
TELEPROMPTER_NAME = "teleprompter.txt"
WORDS_PER_MINUTE = 150          # an unhurried talking pace; people vary by a fifth either way
LENGTH_TOLERANCE = 0.25

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FIELD = re.compile(r"^\s*(?:[-*]\s+)?\*{0,2}(say|says|spoken|show|picture|visual|on screen|on-screen|"
                    r"text on screen|source|sources)\*{0,2}\s*:\*{0,2}\s*(.*?)\s*$", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^\s*[-*]\s+([A-Za-z][A-Za-z ]{1,20}):\s*(.*?)\s*$")
_LABELS = {"say": "say", "says": "say", "spoken": "say", "show": "show", "picture": "show", "visual": "show",
           "on screen": "on_screen", "on-screen": "on_screen", "text on screen": "on_screen",
           "source": "source", "sources": "source"}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_PLACEHOLDER = re.compile(r"\bTODO\b")
_GREETING = re.compile(r"^\s*(hi|hello|hey|welcome|good (?:morning|afternoon|evening)|my name is|i am|i'm)\b",
                       re.IGNORECASE)


@dataclass
class Section:
    name: str
    says: list = field(default_factory=list)
    shows: list = field(default_factory=list)
    on_screen: list = field(default_factory=list)
    sources: list = field(default_factory=list)


@dataclass
class Script:
    title: str = ""
    header: dict = field(default_factory=dict)
    sections: list = field(default_factory=list)

    def spoken(self):
        """[(section name, spoken text)] in order, skipping placeholders."""
        return [(s.name, say) for s in self.sections for say in s.says if say.strip() and not _PLACEHOLDER.search(say)]

    def words(self):
        return sum(len(spoken_words.strip_markings(say).split()) for _name, say in self.spoken())


# ----------------------------------------------------------------------------- reading the file
def parse(text):
    """A script file -> Script. Never raises on odd input; what cannot be read is left out."""
    script = Script()
    current, last = None, None                    # last = (list, index) of the field being continued
    for raw in _COMMENT.sub("", str(text or "")).splitlines():
        line = raw.rstrip()
        h = _HEADING.match(line)
        if h:
            last = None
            if len(h.group(1)) == 1 and not script.title:
                script.title = h.group(2).strip()
                continue
            current = Section(name=h.group(2).strip())
            script.sections.append(current)
            continue
        if not line.strip():
            last = None
            continue
        f = _FIELD.match(line)
        if f and current is not None:
            bucket = {"say": current.says, "show": current.shows, "on_screen": current.on_screen,
                      "source": current.sources}[_LABELS[f.group(1).lower()]]
            bucket.append(f.group(2).strip())
            last = (bucket, len(bucket) - 1)
            continue
        if current is None:
            m = _HEADER_LINE.match(line)
            if m:
                script.header[m.group(1).strip().lower()] = m.group(2).strip()
            continue
        if last is not None:                       # a field that runs on to the next line
            bucket, i = last
            bucket[i] = (bucket[i] + " " + line.strip()).strip()
    return script


def path_for(video_folder, name=SCRIPT_NAME):
    return os.path.join(video_folder, name)


def load(video_folder):
    path = path_for(video_folder)
    if not os.path.isfile(path):
        raise YouTubeError("This video has no script yet. Write it with the person first: their own words, "
                           "tidied for speaking.")
    return parse(read_text(path, "The script"))


def starter(brand, brief):
    """A starter script.md laid out from the video's structure, with nothing written in it.
    Every spoken line is a TODO on purpose: the words have to come from the person."""
    brand = as_brand(brand)
    title = brief.get("chosen_title") or brief.get("topic") or "Untitled"
    lines = ["# %s" % title, "", "- Brand: %s" % brand.id, "- Video: %s" % brief.get("video_id", ""),
             "- Speaker: %s" % (brief.get("identity") or ""), "",
             "<!-- Write this from what the person actually said: a recording, a voice note, or their answers in",
             "     the conversation. Tidy it for speaking. Add nothing they did not say. Every number needs a Source",
             "     line that points into the brand's files (fact:<id>, proof:<id>, or a file in the brand folder). -->",
             ""]
    hook = brief.get("hook") or {}
    segments = list((brief.get("structure") or {}).get("segments") or []) or [{"title": "Opening"}, {"title": "The answer"},
                                                                               {"title": "What to do next"}]
    for i, seg in enumerate(segments):
        lines.append("## %s" % (seg.get("title") or "Section %d" % (i + 1)))
        if i == 0 and hook.get("say"):
            lines += ["Say: %s" % hook["say"], "Show: %s" % (hook.get("show") or "TODO: what the viewer sees first"),
                      "On screen: %s" % (hook.get("on_screen") or "")]
        else:
            lines += ["Say: TODO", "Show: TODO"]
        if seg.get("note"):
            lines.append("<!-- %s -->" % seg["note"])
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- checks
def check(brand, script, brief=None):
    """(problems, warnings) for a script, in plain words.

    Problems: nothing spoken yet, a TODO still in it, a number that does not trace to the brand's
    facts, research or linked proof, a name the brand never mentions, a word its rules forbid.
    Warnings: a spoken section with nothing to show, a greeting for an opening, a running time far
    from the plan, a search phrase that is never said aloud."""
    brand = as_brand(brand)
    brief = brief or {}
    problems, warnings = [], []
    if not script.spoken():
        return ["The script has no spoken lines yet (lines that begin with 'Say:')."], []

    for s in script.sections:
        for say in s.says:
            if _PLACEHOLDER.search(say):
                problems.append("\"%s\" still has a TODO where the spoken words go." % s.name)
                break
        if any(x.strip() and not _PLACEHOLDER.search(x) for x in s.says) and not any(
                x.strip() and not _PLACEHOLDER.search(x) for x in s.shows):
            warnings.append("\"%s\" says something and shows nothing. Every claim wants its picture within a few "
                            "seconds: add a 'Show:' line." % s.name)

    proof_ids = list(brief.get("proof_ids") or [])
    for s in script.sections:
        for src in s.sources:
            for ref in re.split(r"[,;]\s*", src):
                if ref.lower().startswith("proof:") and ref[6:].strip() not in proof_ids:
                    proof_ids.append(ref[6:].strip())
    everything_said = "\n".join(spoken_words.strip_markings(say) for _n, say in script.spoken())
    report = grounding.ground_draft(T.claims_only(everything_said), brand, proof_ids=proof_ids)
    if report["ungrounded"]:
        problems.append("The script states %s, which does not trace to anything in %s's facts, research or linked "
                        "proof. If a number is true, record it as a fact with its source; otherwise say it without "
                        "the number." % (", ".join(report["ungrounded"]), brand.name))
    if report["unknown_proof_ids"]:
        problems.append("The script points at proof that is not in %s's proof library: %s."
                        % (brand.name, ", ".join(report["unknown_proof_ids"])))
    warnings.extend(report["hints"])

    on_screen = "\n".join(x for s in script.sections for x in s.on_screen)
    for label, text in (("What is said", everything_said), ("The text on screen", on_screen)):
        found_problems, found_warnings = T.brand_findings(brand, text)
        problems.extend("%s: %s" % (label, p) for p in found_problems)
        warnings.extend("%s: %s" % (label, w) for w in found_warnings)

    first = script.spoken()[0][1]
    if _GREETING.match(spoken_words.strip_markings(first)):
        warnings.append("The video opens with a greeting or an introduction. Open on the point, and earn the "
                        "introduction by showing something first (see the long-form playbook, 'Openings to drop').")
    keyword = str(brief.get("keyword") or "").strip()
    if keyword:
        opening_words = " ".join(say for _n, say in script.spoken()[:4])
        if not T.keeps_keyword(opening_words, keyword)[0]:
            warnings.append("The search phrase \"%s\" is never said aloud near the start. The platform reads what "
                            "is spoken; say the question in the words people type." % keyword)
    planned = (brief.get("structure") or {}).get("length_minutes")
    minutes = estimated_minutes(script)
    if planned:
        try:
            planned = float(planned)
        except (TypeError, ValueError):
            planned = 0
        if planned and abs(minutes - planned) > planned * LENGTH_TOLERANCE:
            warnings.append("The script runs to about %.1f minutes at a talking pace; the plan is %g. Cut, or change "
                            "the plan (and any running time promised in the title)." % (minutes, planned))
    return problems, warnings


def estimated_minutes(script):
    return round(script.words() / float(WORDS_PER_MINUTE), 1)


# ----------------------------------------------------------------------------- the teleprompter cut
def teleprompter_text(script):
    """Only the spoken words, in short lines, with a blank line where the picture changes."""
    blocks = []
    for _name, say in script.spoken():
        clean = spoken_words.strip_markings(say)
        lines = []
        for sentence in _SENTENCE_END.split(clean):
            if sentence.strip():
                lines += spoken_words.pace(sentence.strip())
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def spoken_sha(script):
    return _sha("\n".join(spoken_words.strip_markings(say) for _n, say in script.spoken()))


def write_teleprompter(video_folder, script):
    """Write teleprompter.txt beside the script and return its stamp for the video's record."""
    text = teleprompter_text(script)
    write_text(path_for(video_folder, TELEPROMPTER_NAME), text)
    return {"file": TELEPROMPTER_NAME, "spoken_sha": spoken_sha(script), "text_sha": _sha(text),
            "made_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lines": len([ln for ln in text.splitlines() if ln.strip()]),
            "minutes": estimated_minutes(script)}


def teleprompter_state(video_folder, stamp_in_record, script):
    """(state, explanation). state is one of: current, stale, edited, missing."""
    path = path_for(video_folder, TELEPROMPTER_NAME)
    stamp = stamp_in_record or {}
    if not os.path.isfile(path) or not stamp:
        return "missing", "There is no teleprompter file for this video yet."
    if stamp.get("spoken_sha") != spoken_sha(script):
        return "stale", "The spoken words changed after the teleprompter file was made, so it is out of date."
    if stamp.get("text_sha") != _sha(read_text(path, "The teleprompter file")):
        return "edited", ("The teleprompter file was changed by hand. The script is the source: change the script, "
                          "then make the teleprompter again.")
    return "current", "The teleprompter file matches the script."
