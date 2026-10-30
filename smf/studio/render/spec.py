"""spec.py - check a picture spec before any browser is started, and say what is wrong in words.

`validate_spec(brand, spec)` returns a list of plain sentences. An empty list means the spec
can be drawn. It checks the shape (the right fields for the format, nothing misspelt), that the
identity belongs to THIS brand, and generous length limits, so text that could never fit is
caught here rather than after a browser has started. Text that is merely a little long is not
a problem at this stage: the engine shrinks it to fit, and only refuses what still overflows
at the smallest readable size.
"""
from __future__ import annotations

import difflib
import re

from smf.brands import Brand, BrandError
from smf.studio.render import text_ad
from smf.studio.render.engine import SIZE_ALIASES, SIZES

NO_KEY_FORMATS = ("carousel", "stat", "split", "alert", "headline", "notes", "post-screenshot", "bold-text")
FREE_FORMAT = "free"                # a page designed for one picture; its rules are in free.py
MAX_SLIDES = 10

# The content planner names a KIND of visual for each post; these are the formats here that can
# draw each kind with no key. Kinds that are not listed (a real photo or video, an untouched
# screenshot, a topical image) are things a person supplies, not things this package draws.
FORMATS_FOR_PLANNED_VISUAL = {
    "brand-card": ["headline", "alert", "split"],
    "carousel": ["carousel"],
    "stat-card": ["stat", "split"],
    "quote-card": ["post-screenshot"],
    "notes-card": ["notes"],
    "bold-text": ["bold-text"],
}
TOP_KEYS = {"format", "identity", "slides", "size", "name", "pdf", "theme", "avatar", "footer_line"}
CARD_GROUNDS = ("main", "soft", "bold", "accent")

# Longest each kind of text may be, in characters. Deliberately roomy: these catch text that
# belongs in the caption, not on a picture. Fine fitting happens in the browser.
LIMITS = {"eyebrow": 44, "tag": 24, "headline": 150, "kicker": 210, "body": 210, "support": 210, "button": 34,
          "stat": 9, "source": 120, "title": 90, "result": 110, "closer": 140, "text": 420, "subline": 130,
          "badge": 2, "footer_line": 60, "item": 110, "label": 28, "head": 48, "step_body": 170,
          "value": 12, "sub": 30, "side_title": 60, "note": 40, "note_item": 120}


class SpecError(Exception):
    """The spec cannot be drawn. The message lists every problem found, in plain words."""

    def __init__(self, problems):
        self.problems = list(problems)
        Exception.__init__(self, "This picture spec cannot be drawn yet:\n  - " + "\n  - ".join(self.problems))


class _Check(object):
    def __init__(self):
        self.problems = []

    def add(self, text):
        self.problems.append(text)

    def text(self, holder, key, where, limit, required=False):
        value = holder.get(key)
        if value is None or value == "":
            if required:
                self.add("%s needs '%s'." % (where, key))
            return
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            self.add("%s: '%s' should be text." % (where, key))
            return
        value = str(value)
        if not value.strip():
            if required:
                self.add("%s needs '%s'; it is blank." % (where, key))
            return
        if len(value) > limit:
            self.add("%s: '%s' is %d characters; at most %d fit on a picture. Move the rest into the caption."
                     % (where, key, len(value), limit))

    def texts(self, holder, key, where, low, high, limit, required=True):
        value = holder.get(key)
        if value is None:
            if required:
                self.add("%s needs '%s': a list of %d to %d short lines." % (where, key, low, high))
            return
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            self.add("%s: '%s' should be a list of short lines of text." % (where, key))
            return
        if not low <= len(value) <= high:
            self.add("%s: '%s' has %d lines; it takes %d to %d." % (where, key, len(value), low, high))
        for i, v in enumerate(value, 1):
            if len(v) > limit:
                self.add("%s: line %d of '%s' is %d characters; at most %d fit." % (where, i, key, len(v), limit))

    def accent(self, holder, where):
        value = holder.get("accent")
        if value is None:
            return
        ok = isinstance(value, str) or (isinstance(value, list) and all(isinstance(v, str) for v in value))
        if not ok:
            self.add("%s: 'accent' is the word or words to colour: text, or a list of texts." % where)

    def choice(self, holder, key, where, allowed):
        value = holder.get(key)
        if value is not None and value not in allowed:
            self.add("%s: '%s' must be one of: %s." % (where, key, ", ".join(allowed)))

    def unknown(self, holder, where, known):
        for key in holder:
            if key not in known:
                near = difflib.get_close_matches(str(key), sorted(known), n=1)
                self.add("%s has a setting this format does not use: '%s'%s."
                         % (where, key, " (did you mean '%s'?)" % near[0] if near else ""))


# ----------------------------------------------------------------------------- per slide
def _statement(c, s, where, extra=()):
    c.unknown(s, where, {"kind", "eyebrow", "headline", "accent", "kicker", "body", "ground"} | set(extra))
    c.text(s, "eyebrow", where, LIMITS["eyebrow"])
    c.text(s, "headline", where, LIMITS["headline"], required=True)
    c.text(s, "kicker", where, LIMITS["kicker"])
    c.text(s, "body", where, LIMITS["body"])
    c.accent(s, where)
    c.choice(s, "ground", where, CARD_GROUNDS)


def _carousel_slide(c, s, where, kind):
    if kind == "cover":
        _statement(c, s, where, {"swipe"})
    elif kind == "cta":
        _statement(c, s, where, {"button"})
        c.text(s, "button", where, LIMITS["button"])
    elif kind == "point":
        _statement(c, s, where)
    elif kind == "steps":
        c.unknown(s, where, {"kind", "eyebrow", "title", "steps", "result", "ground"})
        c.text(s, "eyebrow", where, LIMITS["eyebrow"])
        c.text(s, "title", where, LIMITS["title"], required=True)
        c.text(s, "result", where, LIMITS["result"])
        c.choice(s, "ground", where, CARD_GROUNDS)
        steps = s.get("steps")
        if not isinstance(steps, list) or not all(isinstance(st, dict) for st in steps):
            c.add("%s needs 'steps': a list of 2 to 5 steps, each with a 'head'." % where)
        else:
            if not 2 <= len(steps) <= 5:
                c.add("%s has %d steps; a steps slide takes 2 to 5." % (where, len(steps)))
            for i, st in enumerate(steps, 1):
                w = "%s, step %d" % (where, i)
                c.unknown(st, w, {"label", "head", "body"})
                c.text(st, "label", w, LIMITS["label"])
                c.text(st, "head", w, LIMITS["head"], required=True)
                c.text(st, "body", w, LIMITS["step_body"])
    elif kind == "checklist":
        c.unknown(s, where, {"kind", "eyebrow", "title", "items", "accent", "ground"})
        c.text(s, "eyebrow", where, LIMITS["eyebrow"])
        c.text(s, "title", where, LIMITS["title"], required=True)
        c.texts(s, "items", where, 2, 7, LIMITS["item"])
        c.accent(s, where)
        c.choice(s, "ground", where, CARD_GROUNDS)
    elif kind == "stat":
        _stat(c, s, where, {"kind"}, card=False)
    elif kind == "compare":
        c.unknown(s, where, {"kind", "left", "right"})
        for side in ("left", "right"):
            col = s.get(side)
            w = "%s, the %s column" % (where, side)
            if not isinstance(col, dict):
                c.add("%s needs '%s': a column with a 'title' and a list of 'items'." % (where, side))
                continue
            c.unknown(col, w, {"tag", "title", "note", "items"})
            c.text(col, "tag", w, LIMITS["label"])
            c.text(col, "title", w, LIMITS["side_title"], required=True)
            c.text(col, "note", w, LIMITS["note"])
            c.texts(col, "items", w, 2, 5, LIMITS["item"])


def _stat(c, s, where, extra=(), card=True):
    """A stat card, or (card=False) the stat slide inside a carousel, which has no tag or button."""
    own = {"tag", "button"} if card else set()
    c.unknown(s, where, {"eyebrow", "stat", "headline", "accent", "kicker", "source", "ground"} | own | set(extra))
    for key, req in (("eyebrow", False), ("tag", False), ("stat", True), ("headline", True), ("kicker", False),
                     ("button", False), ("source", False)):
        if key in own or key not in ("tag", "button"):
            c.text(s, key, where, LIMITS[key], required=req)
    c.accent(s, where)
    c.choice(s, "ground", where, CARD_GROUNDS)


def _split(c, s, where):
    c.unknown(s, where, {"eyebrow", "tag", "before", "after", "headline", "accent", "button", "ground"})
    for key, req in (("eyebrow", False), ("tag", False), ("headline", True), ("button", False)):
        c.text(s, key, where, LIMITS[key], required=req)
    c.accent(s, where)
    c.choice(s, "ground", where, ("main", "soft", "bold"))
    for side in ("before", "after"):
        half = s.get(side)
        w = "%s, the '%s' panel" % (where, side)
        if not isinstance(half, dict):
            c.add("%s needs '%s': a panel with a 'tag' and a 'value'." % (where, side))
            continue
        c.unknown(half, w, {"tag", "value", "sub"})
        c.text(half, "tag", w, LIMITS["label"], required=True)
        c.text(half, "value", w, LIMITS["value"], required=True)
        c.text(half, "sub", w, LIMITS["sub"])


def _alert_or_headline(c, s, where, fmt):
    known = {"eyebrow", "tag", "headline", "accent", "support", "button", "ground"} | ({"badge"} if fmt == "alert" else set())
    c.unknown(s, where, known)
    for key, req in (("eyebrow", False), ("tag", False), ("headline", True), ("support", False), ("button", False)):
        c.text(s, key, where, LIMITS[key], required=req)
    if fmt == "alert":
        c.text(s, "badge", where, LIMITS["badge"])
    c.accent(s, where)
    c.choice(s, "ground", where, CARD_GROUNDS)


def _note(c, s, where):
    c.unknown(s, where, {"title", "text", "items", "closer"})
    if not (s.get("title") or s.get("text")):
        c.add("%s needs a 'title' (or, for a single thought, 'text')." % where)
    if s.get("title") and s.get("text"):
        c.add("%s has both 'title' and 'text'; use one." % where)
    c.text(s, "title", where, LIMITS["title"] + 40)
    c.text(s, "text", where, 240)
    c.texts(s, "items", where, 1, 6, LIMITS["note_item"], required=False)
    c.text(s, "closer", where, LIMITS["closer"])


def _post(c, s, where):
    c.unknown(s, where, {"text"})
    c.text(s, "text", where, LIMITS["text"], required=True)


def _bold_text(c, s, where):
    c.unknown(s, where, {"headline", "accent", "subline", "button", "ground", "layout"})
    c.text(s, "headline", where, 110, required=True)
    c.text(s, "subline", where, LIMITS["subline"])
    c.text(s, "button", where, LIMITS["button"])
    c.accent(s, where)
    c.choice(s, "ground", where, text_ad.GROUNDS)
    c.choice(s, "layout", where, ("ad", "statement"))
    if s.get("layout") == "statement":
        if s.get("button"):
            c.add("%s: a statement card has no button; it holds one idea and nothing else." % where)
        for p in text_ad.statement_problems(s, where):
            c.add(p)


# ----------------------------------------------------------------------------- the whole spec
def carousel_kind(slide, index, total):
    """The kind of a carousel slide. The first is the cover and the last is the call to action
    unless the slide says otherwise (and then validate_spec objects)."""
    given = slide.get("kind") if isinstance(slide, dict) else None
    return given or ("cover" if index == 0 else "cta" if index == total - 1 else "point")


# Every field of a slide that a reader ends up reading. The source line is kept apart: it is
# where a figure comes from, not a claim of its own.
_READABLE = ("eyebrow", "tag", "headline", "kicker", "body", "support", "button", "stat", "title", "result",
             "closer", "text", "subline", "badge")
_READABLE_LISTS = ("items",)


def slide_texts(slide):
    """The words drawn on ONE slide, in no particular order. Used to check what a picture claims,
    so it reaches into the nested parts too (a steps rail, the two columns of a comparison)."""
    out = []
    if not isinstance(slide, dict):
        return out
    for key in _READABLE:
        value = slide.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip():
            out.append(str(value))
    for key in _READABLE_LISTS:
        out.extend(str(v) for v in slide.get(key) or [] if isinstance(v, str) and v.strip())
    for key in ("steps", "left", "right", "before", "after"):
        part = slide.get(key)
        for inner in (part if isinstance(part, list) else [part]):
            if isinstance(inner, dict):
                out.extend(slide_texts(dict(inner, source=None)))
            elif isinstance(inner, (str, int, float)) and str(inner).strip():
                out.append(str(inner))
    for key in ("value", "sub", "head", "note", "label"):     # the parts of a panel or a step
        value = slide.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip():
            out.append(str(value))
    return out


def validate_spec(brand, spec):
    """Every problem with `spec` for THIS brand, as plain sentences. Empty list = ready to draw."""
    if not isinstance(brand, Brand):
        raise BrandError("no brand was given. Say which brand these pictures are for.")
    c = _Check()
    if not isinstance(spec, dict):
        return ["A picture spec is a group of settings: a format, an identity and a list of slides."]
    fmt = spec.get("format")
    if fmt not in NO_KEY_FORMATS and fmt != FREE_FORMAT:
        near = difflib.get_close_matches(str(fmt), NO_KEY_FORMATS + (FREE_FORMAT,), n=1)
        c.add("'%s' is not a picture format the Factory can draw%s. Choose one of: %s."
              % (fmt, " (did you mean '%s'?)" % near[0] if near else "",
                 ", ".join(NO_KEY_FORMATS + (FREE_FORMAT,))))
    c.unknown(spec, "The spec", TOP_KEYS)

    identity = spec.get("identity")
    if not identity or not isinstance(identity, str):
        c.add("The spec needs an 'identity': who is speaking. %s has: %s." % (brand.name, ", ".join(brand.identities)))
    else:
        try:
            brand.identity(identity)
        except BrandError as e:
            c.add(str(e)[0].upper() + str(e)[1:] + ".")

    size = spec.get("size")
    if size is not None and SIZE_ALIASES.get(str(size).lower(), str(size).lower()) not in SIZES:
        c.add("'%s' is not a picture size. Choose portrait (1080x1350), square (1080x1080) or story (1080x1920)." % size)
    name = spec.get("name")
    if name is not None and not (isinstance(name, str) and re.match(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,59}$", name)):
        c.add("'name' becomes part of the file names, so it is short and simple: letters, numbers, spaces and dashes.")
    if spec.get("pdf") is not None and not isinstance(spec.get("pdf"), bool):
        c.add("'pdf' is true or false.")
    c.choice(spec, "theme", "The spec", ("dark", "light"))
    if spec.get("theme") and fmt not in ("notes", "post-screenshot"):
        c.add("'theme' only applies to the notes and post-screenshot formats; other formats use 'ground' on each slide.")
    if spec.get("avatar") is not None:
        if fmt != "post-screenshot":
            c.add("'avatar' only applies to the post-screenshot format.")
        elif not isinstance(spec["avatar"], str):
            c.add("'avatar' is the path of a photo inside the brand's Brand/brand-kit/photos folder.")
    c.text(spec, "footer_line", "The spec", LIMITS["footer_line"])

    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        c.add("The spec needs 'slides': a list with at least one slide.")
        return c.problems
    if not all(isinstance(s, dict) for s in slides):
        c.add("Every slide is a group of settings (for example a headline and a supporting line).")
        return c.problems
    if len(slides) > MAX_SLIDES:
        c.add("There are %d slides; a post holds at most %d pictures." % (len(slides), MAX_SLIDES))
    if fmt == FREE_FORMAT:
        from smf.studio.render import free
        free.check_slides(c, slides, brand)
        return c.problems
    if fmt not in NO_KEY_FORMATS:
        return c.problems

    total = len(slides)
    if fmt == "carousel":
        from smf.studio.render.carousel import MAX_MIDDLE, MIDDLE_KINDS, MIN_MIDDLE
        kinds = [carousel_kind(s, i, total) for i, s in enumerate(slides)]
        if total < MIN_MIDDLE + 2:
            c.add("A carousel needs a cover, %d to %d slides in the middle, and a closing slide; this one has %d "
                  "slide%s in all." % (MIN_MIDDLE, MAX_MIDDLE, total, "" if total == 1 else "s"))
        if kinds[0] != "cover":
            c.add("Slide 1 of a carousel is the cover (kind: cover); this one is '%s'." % kinds[0])
        if total > 1 and kinds[-1] != "cta":
            c.add("The last slide of a carousel is the closing slide (kind: cta); this one is '%s'." % kinds[-1])
        for i, kind in enumerate(kinds):
            where = "Slide %d" % (i + 1)
            if 0 < i < total - 1 and kind not in MIDDLE_KINDS:
                c.add("%s: '%s' is not a kind of middle slide. Choose one of: %s." % (where, kind, ", ".join(MIDDLE_KINDS)))
                continue
            if kind in ("cover", "cta") + MIDDLE_KINDS:
                _carousel_slide(c, slides[i], where, kind)
    else:
        checker = {"stat": _stat, "split": _split, "notes": _note, "post-screenshot": _post, "bold-text": _bold_text}
        for i, s in enumerate(slides):
            where = "Slide %d" % (i + 1) if total > 1 else "The slide"
            if fmt in ("alert", "headline"):
                _alert_or_headline(c, s, where, fmt)
            else:
                checker[fmt](c, s, where)
    return c.problems
