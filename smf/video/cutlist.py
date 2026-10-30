"""cutlist.py - the cut list: the one document that says which clips to make from a recording.

A person (or Claude, reading the transcript) writes it. The cutting tools read it. It is plain
Markdown so both can.

    # Cut list: 2026-09-12 shop interview

    > **Recording:** Shop interview about dense loaves, 12 September, 14 minutes
    > **Brand:** maple-and-main
    > **Cut from:** interview-main.mp4
    > **Timestamps from:** Transcriptions/transcript.json (made from interview-main.mp4)
    > **Offset:** 0

    ## Body A: Why loaves come out dense

    - **Gate:** SHIP
    - **Body:** [02:14.2 - 02:51.8]
    - **Starts with:** "most dense loaves are simply underproofed"
    - **Ends with:** "watch the dough, not the clock"
    - **On-screen text:** Your loaf is not broken
    - **Lower-third:** Ava Lindqvist, Head Baker
    - **Hook 1:** [02:47.9 - 02:51.8] "watch the dough, not the clock"
    - **Hook 2:** [02:14.2 - 02:18.0] "most dense loaves are simply underproofed"

THE REFERENCE BLOCK comes first, always. A cut list that does not say which recording it is
about, which exact video file its times belong to, and where those times came from cannot be
acted on: times against a file the editor does not have are just numbers.

A BODY is one self-contained idea. Each body has one or more HOOKS, and every hook makes one clip
(A1, A2, ...). A hook that sits at the very start of its body is "in place": the clip is simply
the body. A hook from anywhere else is lifted to the front: the clip is the hook, a hard cut,
then the whole body (in which the hook is heard again, on purpose).

WHAT `validate` PROVES, against the transcript:
  * every hook is words that were really said, near the time written, by someone on camera;
  * the body's first and last words are really there. Those words, not the times, are what the
    cutter lines up on, because times drift and words do not;
  * on-screen text is 3 to 7 words and carries no claim the brand's gate would stop;
  * the gate written on each clip is at least as strict as the brand's rules require.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from smf.studio.lint import Finding
from smf.video import gate
from smf.video.common import (VideoError, as_brand, fmt_ts, minutes_words, parse_ts, resolve, slug, stream_of,
                              tokens_of)

SHIP = "SHIP"
GATES = (SHIP, gate.HOLD, gate.DROP)
_GATE_RANK = {SHIP: 0, gate.HOLD: 1, gate.DROP: 2}

ON_SCREEN_MIN, ON_SCREEN_MAX = 3, 7
IN_PLACE_SLACK = 1.5          # a hook this close to its body's start is the body's own opening
WORD_TOLERANCE = 6.0          # how far a written time may sit from the words, word-level transcript
SEGMENT_TOLERANCE = 25.0      # ... and when the transcript only knows sentence times
MIN_ANCHOR_TOKENS = 3

REFERENCE_LABELS = [("recording", "Recording"), ("brand", "Brand"), ("cut_from", "Cut from"),
                    ("timestamps_from", "Timestamps from"), ("offset", "Offset"), ("this_file", "This file")]
REQUIRED_REFERENCE = ("recording", "brand", "cut_from", "timestamps_from")

_REF_LINE = re.compile(r"^>\s*\*{0,2}([^:*]+?)\s*:\*{0,2}\s*(.*)$")
_BODY_HEAD = re.compile(r"^##\s+Body\s+([A-Za-z0-9]+)\s*[:.\-]?\s*(.*)$", re.IGNORECASE)
_FIELD = re.compile(r"^\s*[-*]\s+\*{0,2}([^:*]+?)\s*:\*{0,2}\s*(.*)$")
_RANGE = re.compile(r"\[\s*([\d:.,]+)\s*(?:-|\u2013|\u2014|to)\s*([\d:.,]+)\s*\]")
_QUOTE = re.compile(r"[\"\u201c](.+?)[\"\u201d]")
_HOOK_KEY = re.compile(r"^hook\s*(\d+)?\s*(?:\(\s*(ship|hold|drop)\s*\))?$", re.IGNORECASE)
_ELISION = re.compile(r"\.\.\.|\u2026")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass
class Hook:
    number: int
    start: float
    end: float
    text: str
    gate: str = ""                    # optional; can only make the clip stricter than its body


@dataclass
class Body:
    key: str
    title: str = ""
    start: float = None
    end: float = None
    starts_with: str = ""
    ends_with: str = ""
    on_screen_text: str = ""
    lower_third: str = ""
    gate: str = ""
    signed_off: str = ""
    note: str = ""
    hooks: list = field(default_factory=list)


@dataclass
class Clip:
    id: str
    file_stem: str
    body: Body
    hook: Hook
    gate: str
    segments: list                     # [{"role", "start", "end", "starts_with", "ends_with"}] in TRANSCRIPT time


@dataclass
class CutList:
    title: str = ""
    reference: dict = field(default_factory=dict)
    bodies: list = field(default_factory=list)
    problems: list = field(default_factory=list)      # what the parser could not make sense of

    @property
    def offset(self):
        raw = str(self.reference.get("offset", "") or "0").split()[0]
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def clips(self):
        out = []
        for body in self.bodies:
            if body.start is None or body.end is None:
                continue
            for hook in body.hooks:
                body_seg = {"role": "body", "start": body.start, "end": body.end,
                            "starts_with": body.starts_with, "ends_with": body.ends_with}
                if abs(hook.start - body.start) <= IN_PLACE_SLACK:
                    segments = [body_seg]
                else:
                    pieces = [p.strip() for p in _ELISION.split(hook.text) if p.strip()]
                    segments = [{"role": "hook", "start": hook.start, "end": hook.end,
                                 "starts_with": pieces[0] if pieces else "",
                                 "ends_with": pieces[-1] if pieces else ""}, body_seg]
                declared = body.gate if body.gate in GATES else gate.DROP      # unreadable = strictest
                if hook.gate in GATES and _GATE_RANK[hook.gate] > _GATE_RANK[declared]:
                    declared = hook.gate
                clip_id = "%s%d" % (body.key, hook.number)
                stem = "-".join(x for x in (clip_id, slug(body.title)) if x)
                out.append(Clip(clip_id, stem, body, hook, declared, segments))
        return out


# ----------------------------------------------------------------------------- reading
def _time_range(value, where, problems):
    m = _RANGE.search(value)
    if not m:
        problems.append(Finding("ERROR", "time", "%s needs a time range written like [02:14.2 - 02:51.8]." % where,
                                value[:60]))
        return None, None
    try:
        a, b = parse_ts(m.group(1)), parse_ts(m.group(2))
    except VideoError as e:
        problems.append(Finding("ERROR", "time", "%s: %s" % (where, e), value[:60]))
        return None, None
    if b <= a:
        problems.append(Finding("ERROR", "time", "%s ends before it starts." % where, value[:60]))
        return None, None
    return a, b


def _unquote(value):
    m = _QUOTE.search(value)
    return (m.group(1) if m else value).strip()


def parse(text):
    """Markdown -> CutList. Nothing is guessed: a line that cannot be understood becomes a problem
    the person sees, because a mistyped 'Gate' that silently fell back to SHIP would be the worst
    kind of bug."""
    cl = CutList()
    body = None
    labels = {label.lower(): key for key, label in REFERENCE_LABELS}
    for raw in _COMMENT.sub("", text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("# ") and not cl.title:
            cl.title = re.sub(r"^#\s+(?:Cut list\s*[:\-]\s*)?", "", line, flags=re.IGNORECASE).strip()
            continue
        head = _BODY_HEAD.match(line)
        if head:
            key = head.group(1).upper()
            if any(b.key == key for b in cl.bodies):
                cl.problems.append(Finding("ERROR", "duplicate", "Two bodies are both called %s." % key, line[:60]))
            body = Body(key=key, title=head.group(2).strip())
            cl.bodies.append(body)
            continue
        if line.startswith("## "):
            body = None                       # any other section (notes, a summary) is prose; leave it alone
            continue
        if line.lstrip().startswith(">") and body is None:
            m = _REF_LINE.match(line.strip())
            if m and m.group(1).strip().lower() in labels:
                cl.reference[labels[m.group(1).strip().lower()]] = m.group(2).strip()
            continue
        m = _FIELD.match(line)
        if not m or body is None:
            continue
        key, value = re.sub(r"\s+", " ", m.group(1).strip().lower()), m.group(2).strip()
        where = "Body %s" % body.key
        hook = _HOOK_KEY.match(key)
        if hook:
            a, b = _time_range(value, "%s, a hook" % where, cl.problems)
            number = int(hook.group(1)) if hook.group(1) else len(body.hooks) + 1
            if any(h.number == number for h in body.hooks):
                cl.problems.append(Finding("ERROR", "duplicate", "%s has two hooks numbered %d." % (where, number)))
            quoted = _QUOTE.search(value)
            if not quoted:
                cl.problems.append(Finding("ERROR", "hook", "%s, hook %d has no quoted line. A hook is the exact "
                                           "words that were said, in double quotes." % (where, number), value[:60]))
            if a is not None and quoted:
                body.hooks.append(Hook(number, a, b, quoted.group(1).strip(), (hook.group(2) or "").upper()))
        elif key == "gate":
            word = value.split()[0].upper().strip("*.,") if value.split() else ""
            if word not in GATES:
                cl.problems.append(Finding("ERROR", "gate", "%s: the gate must be SHIP, HOLD or DROP." % where, value[:40]))
            body.gate = word
        elif key == "body":
            body.start, body.end = _time_range(value, where, cl.problems)
        elif key == "starts with":
            body.starts_with = _unquote(value)
        elif key == "ends with":
            body.ends_with = _unquote(value)
        elif key in ("on-screen text", "on screen text"):
            body.on_screen_text = _unquote(value)
        elif key in ("lower-third", "lower third"):
            body.lower_third = value.strip()
        elif key == "signed off":
            body.signed_off = value.strip()
        elif key == "note":
            body.note = value.strip()
        else:
            cl.problems.append(Finding("WARN", "unknown-line", "%s has a line the cutter does not know: '%s'. "
                                       "If it is a typo for another line, that line is currently missing."
                                       % (where, m.group(1).strip()), line.strip()[:60]))
    return cl


def load(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return parse(f.read())
    except OSError:
        raise VideoError("There is no cut list yet. It is the file that says which clips to make; "
                         "run find-clips first, then fill it in from the transcript.")


# ----------------------------------------------------------------------------- writing
def write(cl):
    """CutList -> Markdown. `parse(write(x))` gives back the same cut list."""
    lines = ["# Cut list: %s" % (cl.title or cl.reference.get("recording", "")), ""]
    for key, label in REFERENCE_LABELS:
        if key in cl.reference and str(cl.reference[key]).strip() != "":
            lines.append("> **%s:** %s" % (label, cl.reference[key]))
    for body in cl.bodies:
        lines += ["", "## Body %s: %s" % (body.key, body.title), ""]
        lines.append("- **Gate:** %s" % body.gate)
        if body.start is not None and body.end is not None:
            lines.append("- **Body:** [%s - %s]" % (fmt_ts(body.start), fmt_ts(body.end)))
        lines.append('- **Starts with:** "%s"' % body.starts_with)
        lines.append('- **Ends with:** "%s"' % body.ends_with)
        lines.append("- **On-screen text:** %s" % body.on_screen_text)
        lines.append("- **Lower-third:** %s" % body.lower_third)
        for h in body.hooks:
            tag = " (%s)" % h.gate if h.gate else ""
            lines.append('- **Hook %d%s:** [%s - %s] "%s"' % (h.number, tag, fmt_ts(h.start), fmt_ts(h.end), h.text))
        if body.signed_off:
            lines.append("- **Signed off:** %s" % body.signed_off)
        if body.note:
            lines.append("- **Note:** %s" % body.note)
    return "\n".join(lines) + "\n"


HOW_TO_FILL = """<!--
HOW TO FILL THIS IN (this note is ignored by the tools; delete it when you are done)

Add one section per idea worth a clip. Copy this shape:

## Body A: a few words naming the idea

- **Gate:** SHIP
- **Body:** [MM:SS.s - MM:SS.s]
- **Starts with:** "the first five or six words of the body, exactly as the transcript has them"
- **Ends with:** "the last five or six words of the body, exactly as the transcript has them"
- **On-screen text:** Three to seven words
- **Lower-third:** %(lower_third)s
- **Hook 1:** [MM:SS.s - MM:SS.s] "the strongest line, copied from the transcript word for word"

Rules the checker enforces:
  * Hooks and boundary words are copied from the transcript, never written fresh. Copy the
    transcript's own spelling, even where it misheard; put a correction in [square brackets].
  * Only quote people who are on camera. Work from the on-camera transcript and this is automatic.
  * Gate is SHIP, HOLD (needs the brand's disclaimer and a named sign-off) or DROP (never publish).
  * More hooks for the same body: add Hook 2, Hook 3. Each one becomes its own clip.
-->
"""


def starter(brand, recording, transcript, policy):
    """A new cut list with the reference block already filled in from what is known, so the part
    that must be exact is never typed from memory."""
    brand = as_brand(brand)
    src = transcript.source or {}
    media = src.get("media") or "WRITE THE EXACT VIDEO FILE NAME HERE"
    made_by = src.get("made_by") or "the transcript"
    cl = CutList(title=recording)
    cl.reference = {
        "recording": "%s (%s)" % (recording, minutes_words(transcript.duration)),
        "brand": brand.id,
        "cut_from": media,
        "timestamps_from": "Transcriptions/transcript.json (%s, from %s)"
                           % (made_by, os.path.basename(str(src.get("media") or "")) or "a file not recorded"),
        "offset": "0",
    }
    on_camera = policy.on_camera()
    third = gate.lower_third_for(brand, on_camera[0] if len(on_camera) == 1 else "")
    note = HOW_TO_FILL % {"lower_third": third or "the exact line shown under the speaker's face"}
    return write(cl) + "\n" + note


# ----------------------------------------------------------------------------- checking
class _Index(object):
    """Where every run of words sits in the transcript: when, and in whose voice."""

    def __init__(self, transcript):
        self.word_level = transcript.word_level
        self.units = transcript.words if self.word_level else transcript.segments
        key = "word" if self.word_level else "text"
        self.stream = stream_of([u[key] for u in self.units], keep_numbers=True)
        self.first = {}
        for pos, (_i, tok) in enumerate(self.stream):
            self.first.setdefault(tok, []).append(pos)

    def occurrences(self, phrase):
        """Every place the phrase is said, word for word: [(start, end, {speakers})]."""
        toks = tokens_of(phrase, keep_numbers=True)
        if not toks:
            return []
        out, n = [], len(toks)
        for pos in self.first.get(toks[0], []):
            if [t for _i, t in self.stream[pos:pos + n]] == toks:
                a, z = self.stream[pos][0], self.stream[pos + n - 1][0]
                units = self.units[a:z + 1]
                out.append((units[0]["start"], units[-1]["end"], {u["speaker"] for u in units}))
        return out


def _pieces(quote):
    return [p.strip() for p in _ELISION.split(quote or "") if len(tokens_of(p, keep_numbers=True)) >= 2]


def _check_quote(index, policy, quote, cited, use_end, what, tolerance, findings, rule):
    """One quoted phrase: is it really said, near `cited`, by someone who may appear?"""
    pieces = _pieces(quote)
    if not pieces:
        findings.append(Finding("ERROR", rule, "%s is missing or too short to find. Quote at least a few words."
                                % what, (quote or "")[:60]))
        return
    piece = pieces[-1] if use_end else pieces[0]
    for p in pieces:
        if not index.occurrences(p):
            findings.append(Finding(
                "ERROR", rule, "%s is not in the transcript. It must be words that were really said, copied "
                "exactly, including how the transcript wrote any numbers." % what, p[:60]))
            return
    found = index.occurrences(piece)
    when = (lambda o: o[1]) if use_end else (lambda o: o[0])
    nearest = min(found, key=lambda o: abs(when(o) - cited))
    if abs(when(nearest) - cited) > tolerance:
        findings.append(Finding("ERROR", rule, "%s is said at %s, not near %s where the cut list puts it."
                                % (what, fmt_ts(when(nearest)), fmt_ts(cited)), piece[:60]))
        return
    if not index.word_level or not policy.labelled:
        return
    blocked = sorted(s or "an unnamed voice" for s in nearest[2] if not policy.may_publish(s))
    if blocked:
        elsewhere = [o for o in found if o is not nearest and all(policy.may_publish(s) for s in o[2])]
        hint = (" Someone on camera says the same words at %s: use that delivery and its time."
                % fmt_ts(elsewhere[0][0])) if elsewhere else \
            " A line read out by someone off camera is not the speaker's own delivery."
        findings.append(Finding("ERROR", "speaker", "%s is spoken by %s, who does not appear in clips.%s"
                                % (what, ", ".join(blocked), hint), piece[:60]))


def _spoken_text(transcript, policy, segments):
    """The on-camera words inside a clip's segments: what the compliance gate reads."""
    units = transcript.words if transcript.word_level else transcript.segments
    key = "word" if transcript.word_level else "text"
    out = []
    for seg in segments:
        for u in units:
            mid = (u["start"] + u["end"]) / 2.0
            if seg["start"] - 0.05 <= mid <= seg["end"] + 0.05 and policy.may_publish(u["speaker"]):
                out.append(u[key])
    return " ".join(out)


def validate(cl, transcript, brand, recording=None, policy=None, check_files=True):
    """Every problem with a cut list, as Findings. ERROR blocks the cut; WARN is for the person."""
    brand = as_brand(brand)
    rules = gate.GateRules.for_brand(brand)
    policy = policy or gate.SpeakerPolicy.for_transcript(brand, transcript)
    findings = list(cl.problems)
    index = _Index(transcript)
    tolerance = WORD_TOLERANCE if transcript.word_level else SEGMENT_TOLERANCE

    # ---- the reference block
    for key in REQUIRED_REFERENCE:
        if not str(cl.reference.get(key, "")).strip():
            label = dict(REFERENCE_LABELS)[key]
            findings.append(Finding("ERROR", "reference", "The cut list does not open with a '%s' line. Without it "
                                    "nobody can tell which recording or which video file the times belong to." % label))
    named = str(cl.reference.get("brand", "")).strip()
    if named and named != brand.id:
        findings.append(Finding("ERROR", "reference", "This cut list says it belongs to the brand '%s', but it is "
                                "being used for '%s'." % (named, brand.id)))
    if check_files and recording and cl.reference.get("cut_from"):
        if not resolve(brand, recording, cl.reference["cut_from"]):
            findings.append(Finding("ERROR", "reference", "The video named under 'Cut from' cannot be found. The times "
                                    "only mean something against a file that is really there. Put the video in the "
                                    "recording's folder, or write its full location.", str(cl.reference["cut_from"])[:80]))
    try:
        float(str(cl.reference.get("offset", "") or "0").split()[0])
    except ValueError:
        findings.append(Finding("ERROR", "reference", "'Offset' must be a number of seconds (0 when the clips are cut "
                                "from the same file that was transcribed).", str(cl.reference.get("offset"))[:40]))

    if not transcript.word_level:
        findings.append(Finding("WARN", "unverified", "This transcript came from a subtitle file, so it has sentence "
                                "times only and no voice labels. Who is speaking is unverified."))
    elif not policy.labelled:
        findings.append(Finding("WARN", "unverified", "This transcript does not say who is speaking, so the speaker "
                                "check is unverified."))

    if not cl.bodies:
        findings.append(Finding("ERROR", "empty", "The cut list has no bodies yet, so there is nothing to cut."))

    turns = transcript.turns()
    for body in cl.bodies:
        where = "Body %s" % body.key
        if body.gate not in GATES and not any(f.rule == "gate" and where in f.detail for f in findings):
            findings.append(Finding("ERROR", "gate", "%s has no Gate line. Every body says SHIP, HOLD or DROP." % where))
        if body.start is None or body.end is None:
            if not any(f.rule == "time" and f.detail.startswith(where) for f in findings):
                findings.append(Finding("ERROR", "time", "%s has no Body line with its start and end times." % where))
            continue
        if body.end > transcript.duration + 1.0:
            findings.append(Finding("ERROR", "time", "%s ends at %s but the recording is only %s long."
                                    % (where, fmt_ts(body.end), fmt_ts(transcript.duration))))
        if not body.hooks:
            findings.append(Finding("ERROR", "hook", "%s has no hook. Each body needs at least one." % where))

        # boundary words: what the cutter actually lines up on
        for label, quote, cited, use_end in (("first words", body.starts_with, body.start, False),
                                             ("last words", body.ends_with, body.end, True)):
            what = "%s's %s" % (where, label)
            _check_quote(index, policy, quote, cited, use_end, what, tolerance, findings, "boundary")
            toks = tokens_of(quote, keep_numbers=True)
            if toks and len(toks) < MIN_ANCHOR_TOKENS:
                findings.append(Finding("WARN", "boundary", "%s are only %d word(s). Short, common words turn up "
                                        "everywhere; quote five or six." % (what, len(toks)), quote[:60]))
            edge = toks[-1] if use_end and toks else (toks[0] if toks else "")
            if edge and any(c.isdigit() for c in edge):
                findings.append(Finding("WARN", "boundary", "%s begin or end on a number. Numbers are heard "
                                        "differently every time, so the cutter cannot line up on one. Start the "
                                        "quote a word earlier or later." % what, quote[:60]))

        for h in body.hooks:
            what = "%s, hook %d" % (where, h.number)
            _check_quote(index, policy, h.text, h.start, False, what, tolerance, findings, "verbatim")
            if h.end > transcript.duration + 1.0:
                findings.append(Finding("ERROR", "time", "%s ends after the recording does." % what))

        # on-screen text
        n = len(body.on_screen_text.split())
        if not ON_SCREEN_MIN <= n <= ON_SCREEN_MAX:
            findings.append(Finding("ERROR", "on-screen", "%s: on-screen text is %d word(s); it must be %d to %d, "
                                    "short enough to read before the first sentence ends."
                                    % (where, n, ON_SCREEN_MIN, ON_SCREEN_MAX), body.on_screen_text[:60]))
        else:
            seen = gate.check(body.on_screen_text, rules)
            if seen.status != gate.PASS:
                findings.append(Finding("ERROR", "on-screen", "%s: on-screen text carries a claim this brand's rules "
                                        "stop (%s). Text on screen has no room for a qualifier, so keep claims out "
                                        "of it." % (where, "; ".join(seen.reasons)), body.on_screen_text[:60]))

        # lower-third: the brand's exact line, never an invented credential
        voices = {}
        for t in turns:
            if policy.may_publish(t["speaker"]):
                overlap = min(t["end"], body.end) - max(t["start"], body.start)
                if overlap > 0:
                    voices[t["speaker"]] = voices.get(t["speaker"], 0.0) + overlap
        main_voice = max(voices, key=voices.get) if voices else ""
        expected = gate.lower_third_for(brand, main_voice)
        if not body.lower_third.strip():
            findings.append(Finding("WARN", "lower-third", "%s has no lower-third.%s" % (
                where, (" The brand's line for this speaker is '%s'." % expected) if expected else
                " The brand has no credential line for this speaker yet; add one in onboarding rather than "
                "writing one here.")))
        elif expected and body.lower_third.strip() != expected:
            findings.append(Finding("WARN", "lower-third", "%s: the lower-third differs from the brand's own line "
                                    "('%s'). Credentials are a claim; use the brand's wording." % (where, expected),
                                    body.lower_third[:60]))

        # off-camera talking inside the body: removed automatically, but it leaves a visible jump
        inside = gate.off_camera_seconds(body.start, body.end, turns, policy) if policy.labelled else 0.0
        if inside > 0:
            findings.append(Finding("WARN", "speaker", "%s has %.1f seconds of someone off camera talking inside it. "
                                    "That will be cut out, which leaves a jump. Consider ending the body before "
                                    "they speak." % (where, inside)))
        # ... and an edge that sits right against an off-camera voice gets trimmed to keep it out
        if policy.labelled and not policy.everyone_on_camera:
            spans = [("the body", body.start, body.end)] + [("hook %d" % h.number, h.start, h.end) for h in body.hooks]
            for label, a, z in spans:
                kept = gate.publishable_pieces({"start": a, "end": z}, turns, policy)
                if not kept:
                    findings.append(Finding("ERROR", "speaker", "%s, %s: once the off-camera voice and the margin "
                                            "around it are taken out, nothing is left." % (where, label)))
                    continue
                lost_head, lost_tail = kept[0]["lost_head"], kept[-1]["lost_tail"]
                if lost_head > 0.05 or lost_tail > 0.05:
                    findings.append(Finding(
                        "WARN", "speaker", "%s, %s sits right against someone off camera. To keep their voice out, "
                        "%.1fs of the on-camera speaker will be trimmed from its %s. Pick a moment with more air "
                        "around it if that clips a word."
                        % (where, label, max(lost_head, lost_tail), "start" if lost_head >= lost_tail else "end")))

    # ---- the compliance gate, clip by clip
    seen_ids = set()
    for clip in cl.clips():
        if clip.id in seen_ids:
            continue
        seen_ids.add(clip.id)
        verdict = gate.check(_spoken_text(transcript, policy, clip.segments), rules)
        needed = SHIP if verdict.status == gate.PASS else verdict.status
        if _GATE_RANK[clip.gate] < _GATE_RANK[needed]:
            findings.append(Finding("ERROR", "gate", "Clip %s is marked %s, but this brand's rules make it %s: %s."
                                    % (clip.id, clip.gate, needed, "; ".join(verdict.reasons))))
        if clip.gate == gate.HOLD:
            if not rules.sign_off_by or not rules.disclaimer:
                findings.append(Finding("ERROR", "gate", "Clip %s is on HOLD, which means 'disclaimer plus a named "
                                        "person's sign-off', but %s has not set %s yet. Add it in the brand's settings."
                                        % (clip.id, brand.name, " or ".join(
                                            n for n, v in (("a disclaimer", rules.disclaimer),
                                                           ("who signs off", rules.sign_off_by)) if not v))))
            elif not clip.body.signed_off:
                findings.append(Finding("WARN", "needs-sign-off", "Clip %s is on HOLD. It can be cut so %s can watch "
                                        "it, but it must not be posted until they sign it off."
                                        % (clip.id, rules.sign_off_by)))
    return findings


def is_valid(findings):
    return not any(f.severity == "ERROR" for f in findings)
