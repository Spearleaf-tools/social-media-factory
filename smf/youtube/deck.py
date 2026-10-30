"""deck.py - a support deck for a talking video: the SHOW, never the script.

THE ONE LAW
The person talks; the slide backs them up with ONE thing the viewer can take in without effort.
It is never the narration written out, and it never carries anything meant for the people making
the video.
Everything below follows from that: the limits on how much a slide may hold, the refusal of
production notes, and the check against the script.

A deck is a spec (a dict; save it as JSON), drawn as 1920x1080 pictures by the Factory's own
renderer, in the brand's colours and fonts, offline:

    {"name": "proofing", "identity": "person", "ground": "bold", "slides": [
        {"type": "title", "title": "Is the dough *ready*?"},
        {"type": "number", "number": "18h", "label": "how long our dough ferments", "source": "fact:ferment-18h"},
        {"type": "steps", "title": "The poke test", "steps": ["Flour a finger", "Press in a knuckle deep", "Watch it come back"]},
        {"type": "ask", "title": "Bake it with us", "button": "Book a Saturday class"}]}

Wrap a word in *stars* to colour it. `ground` is bold (the brand's headline colour as the
background, words reversed), main or soft; one slide can override it.

SLIDE TYPES are data (`ARCHETYPES`): what each is for, its fields, and how much it may hold.
Reach for a type that SHOWS the idea (a share of a hundred dots, a comparison, steps, a ranking,
the brand's own picture) before one that only states it.

WHAT IS REFUSED, WITH THE SLIDE NAMED
  * more words than the type may hold, or more items, or a missing field
  * a production note on a slide: a timecode, "B-roll", "Hook", "Slide 4", anything in [brackets]
  * a slide that repeats a spoken line from the script word for word
  * a number that traces to nothing AND gives no source. (A number with a written source that
    the brand's files cannot confirm is drawn, and listed in the report as unverified.)
  * a picture from outside the brand's own folder, or from the internet
  * a name the brand never mentions, or a word its rules forbid

THE LOOK-AT-IT LOOP
Drawing a deck writes every slide as a picture, one PDF of them all, and `contact-sheet.png`:
every slide small, in order, on one page. Open the contact sheet. Read the slide headings top
to bottom: the argument should hold with nobody talking. Then open any slide that looks crowded
or empty at that size, fix the spec, and draw again. Grade by what is on the page.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from smf.studio import grounding
from smf.studio.render import layout as L
from smf.studio.render.engine import RenderError, Renderer
from smf.studio.render.kit import ensure_contrast, resolve
from smf.studio.render.pdf import PdfError, images_to_pdf
from smf.youtube import YouTubeError, as_brand, slugify
from smf.youtube import canvas as C
from smf.youtube import titles as T
from smf.brands import replace_patiently

SIZE = C.SLIDE
MAX_SLIDES = 60
MAX_WORDS_ON_A_SLIDE = 28
NARRATION_RUN = 7                 # this many spoken words in a row on a slide is the script, not a slide
REPORT_NAME = "deck-report.json"
SHEET_NAME = "contact-sheet.png"
GROUNDS = ("bold", "main", "soft")
TOP_KEYS = {"name", "identity", "ground", "slides", "pdf"}
COMMON_KEYS = {"type", "ground", "source"}

# words = the most words a text field may hold; chars = the most characters; items = (fewest, most).
ARCHETYPES = {
    "title": {"name": "Title", "use_when": "The first slide: the subject, in the viewer's words.",
              "fields": {"title": {"required": True, "words": 9}, "sub": {"words": 12}}, "head": "title"},
    "statement": {"name": "Statement", "use_when": "A pure change of mind, when nothing can be shown for it.",
                  "fields": {"text": {"required": True, "words": 12}}, "head": "text"},
    "number": {"name": "One number", "use_when": "A single figure carries the point. It needs a source.",
               "fields": {"number": {"required": True, "chars": 8}, "label": {"required": True, "words": 10}},
               "head": "label", "is_claim": True},
    "share": {"name": "A share of a hundred", "use_when": "A proportion. A hundred dots, some of them lit, shows it.",
              "fields": {"percent": {"required": True, "percent": True}, "label": {"required": True, "words": 10}},
              "head": "label", "is_claim": True},
    "compare": {"name": "Side by side", "use_when": "Two ways, two results, before and after.",
                "fields": {"title": {"words": 8},
                           "left": {"required": True, "side": True}, "right": {"required": True, "side": True}},
                "head": "title"},
    "steps": {"name": "Steps", "use_when": "A short process, in order. The viewer sees where they are.",
              "fields": {"title": {"required": True, "words": 8}, "steps": {"required": True, "items": (2, 5), "words": 6}},
              "head": "title"},
    "list": {"name": "Short list", "use_when": "A few things to remember. Not sentences.",
             "fields": {"title": {"required": True, "words": 8}, "items": {"required": True, "items": (2, 4), "words": 7}},
             "head": "title"},
    "ranking": {"name": "Ranking", "use_when": "An order that matters, with one row that is the point.",
                "fields": {"title": {"required": True, "words": 8}, "rows": {"required": True, "items": (3, 5), "words": 5},
                           "highlight": {"index_of": "rows"}}, "head": "title"},
    "progress": {"name": "How far along", "use_when": "Most of the way there, and the part that is left is the point.",
                 "fields": {"percent": {"required": True, "percent": True}, "label": {"required": True, "words": 8},
                            "rest": {"words": 6}}, "head": "label", "is_claim": True},
    "picture": {"name": "The brand's own picture", "use_when": "Real proof: a photo or a screenshot the brand owns, "
                "cropped to the point, with one mark on it.",
                "fields": {"image": {"required": True, "image": True}, "caption": {"words": 9}, "point": {"point": True}},
                "head": "caption"},
    "quote": {"name": "Someone's words", "use_when": "A real person said it, the brand may repeat it, and it is on file.",
              "fields": {"text": {"required": True, "words": 24}, "who": {"required": True, "words": 8}},
              "head": "text", "needs_source": True},
    "ask": {"name": "The ask", "use_when": "The one next step, near the close.",
            "fields": {"title": {"required": True, "words": 8}, "sub": {"words": 12}, "button": {"words": 5}},
            "head": "title"},
    "next": {"name": "What is next", "use_when": "The last slide: the video to watch after this one.",
             "fields": {"title": {"required": True, "words": 9}, "sub": {"words": 12}}, "head": "title"},
}

_PRODUCTION = [
    (re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)"), "a timecode"),
    (re.compile(r"\[[^\]]+\]"), "a note in [brackets]"),
    (re.compile(r"\b(b-?roll|voice ?over|v\.?o\.?:|speaker notes?|talking point|teleprompter|cut to|on camera|"
                r"lower third|sfx|gfx)\b", re.IGNORECASE), "a production term"),
    (re.compile(r"^\s*(hook|intro|outro|setup|stakes|payoff|cta|beat|segment|slide|scene|section)\s*[\d:.#-]", re.IGNORECASE),
     "a label for the people making the video"),
]
_WORD = re.compile(r"[A-Za-z0-9'%]+")

CSS = """
.foot16{position:absolute;left:120px;bottom:44px;right:120px;height:56px;display:flex;align-items:center;
  justify-content:space-between;overflow:hidden;}
.foot16 .wm{font-size:30px;color:var(--muted);font-weight:600;}
.sub{font-family:"smf-body",sans-serif;color:var(--muted);font-weight:450;line-height:1.3;margin-top:.9em;text-wrap:pretty;}
.lab{font-family:"smf-display",sans-serif;font-weight:700;color:var(--head);line-height:1.12;letter-spacing:-0.02em;
  text-wrap:balance;}
.src{font-family:"smf-mono",monospace;color:var(--muted);letter-spacing:.03em;margin-top:1.1em;line-height:1.35;}
.bignum{font-family:"smf-display",sans-serif;font-weight:800;letter-spacing:-0.055em;line-height:.9;color:var(--number);
  font-variant-numeric:tabular-nums;white-space:nowrap;}
.dots{display:grid;grid-template-columns:repeat(10,1fr);gap:16px;width:100%;height:100%;}
.dots i{display:block;border-radius:50%;background:var(--dot-off);}
.dots i.on{background:var(--accent);}
.panel{position:absolute;border-radius:28px;background:var(--panel);border:3px solid var(--rule);overflow:hidden;
  padding:64px 64px;display:flex;flex-direction:column;justify-content:flex-start;gap:34px;}
.panel.win{border-color:var(--accent);}
.ptitle{font-family:"smf-display",sans-serif;font-weight:800;color:var(--head);letter-spacing:-0.03em;line-height:1.05;}
.panel.win .ptitle{color:var(--accent);}
.pitem{display:flex;gap:.5em;align-items:flex-start;color:var(--body);line-height:1.25;font-weight:500;}
.pitem .ico{margin-top:.12em;color:var(--accent-small);}
.cardrow{position:absolute;display:flex;gap:28px;align-items:stretch;}
.card{flex:1 1 0;min-width:0;border-radius:26px;background:var(--panel);border:3px solid var(--rule);padding:44px 42px;
  display:flex;flex-direction:column;justify-content:center;gap:30px;overflow:hidden;}
.stepno{width:74px;height:74px;border-radius:50%;background:var(--accent);color:var(--pill-fg);display:flex;
  align-items:center;justify-content:center;font-family:"smf-display",sans-serif;font-weight:800;font-size:38px;flex:0 0 auto;}
.cardtext{font-family:"smf-display",sans-serif;font-weight:700;color:var(--head);line-height:1.14;letter-spacing:-0.02em;
  text-wrap:balance;}
.rowlist{position:absolute;display:flex;flex-direction:column;gap:20px;}
.rrow{flex:1 1 0;min-height:0;display:flex;align-items:center;gap:32px;border-radius:22px;background:var(--panel);
  border:3px solid var(--rule);padding:0 40px;overflow:hidden;}
.rrow.on{background:var(--accent);border-color:var(--accent);}
.rrow .pos{font-family:"smf-mono",monospace;color:var(--muted);font-size:40px;flex:0 0 auto;width:70px;}
.rrow .rt{font-family:"smf-display",sans-serif;font-weight:700;color:var(--head);letter-spacing:-0.02em;line-height:1.1;}
.rrow.on .pos,.rrow.on .rt{color:var(--pill-fg);}
.bar{position:absolute;height:96px;border-radius:48px;background:var(--dot-off);overflow:hidden;display:flex;}
.bar .done{height:100%;background:var(--muted);}
.bar .rest{height:100%;background:var(--accent);flex:1 1 0;}
.mat{position:absolute;border-radius:30px;background:var(--panel);border:3px solid var(--rule);overflow:hidden;}
.mat img{position:absolute;left:28px;top:28px;width:calc(100% - 56px);height:calc(100% - 56px);object-fit:fill;display:block;}
.ring{position:absolute;width:150px;height:150px;margin:-75px 0 0 -75px;border-radius:50%;border:12px solid var(--accent);
  box-shadow:0 0 0 6px var(--bg);}
.qmark{font-family:"smf-display",sans-serif;font-weight:800;font-size:220px;line-height:.7;color:var(--accent);}
.qtext{font-family:"smf-display",sans-serif;font-weight:650;color:var(--head);line-height:1.18;letter-spacing:-0.02em;
  text-wrap:pretty;}
.small{font-family:"smf-mono",monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--accent-small);}
"""


def _count(text):
    return len(_WORD.findall(str(text or "").replace("*", "")))


def _texts(slide):
    """Every piece of viewer-facing text on a slide, as (field, text)."""
    out = []
    for key, value in slide.items():
        if key in ("type", "ground", "image", "point", "highlight", "percent"):
            continue
        if isinstance(value, str):
            out.append((key, value))
        elif isinstance(value, list):
            out += [("%s %d" % (key, i), v) for i, v in enumerate(value, 1) if isinstance(v, str)]
        elif isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, str):
                    out.append(("%s %s" % (key, k), v))
                elif isinstance(v, list):
                    out += [("%s %s %d" % (key, k, i), x) for i, x in enumerate(v, 1) if isinstance(x, str)]
    return out


def heading_of(slide):
    arch = ARCHETYPES.get(slide.get("type")) or {}
    text = str(slide.get(arch.get("head") or "") or "").replace("*", "").strip()
    if slide.get("type") in ("number", "share", "progress"):
        lead = str(slide.get("number") or ("%s%%" % slide.get("percent")))
        text = ("%s %s" % (lead, text)).strip()
    return text


def _where(i, slide):
    return "Slide %d (%s)" % (i, (ARCHETYPES.get(slide.get("type")) or {}).get("name", slide.get("type") or "no type"))


# ----------------------------------------------------------------------------- the checks
def _check_field(problems, where, key, rule, value, brand):
    missing = value is None or value == "" or value == []
    if missing:
        if rule.get("required"):
            problems.append("%s needs '%s'." % (where, key))
        return
    if rule.get("side"):
        if not isinstance(value, dict) or not str(value.get("title") or "").strip():
            problems.append("%s: '%s' needs a title of its own (and up to three short points)." % (where, key))
            return
        if _count(value.get("title")) > 5:
            problems.append("%s: the %s title has %d words; at most 5." % (where, key, _count(value.get("title"))))
        points = value.get("items") or []
        if not isinstance(points, list) or len(points) > 3:
            problems.append("%s: the %s side has %d points; a comparison reads at a glance with 3 at most on a side."
                            % (where, key, len(points) if isinstance(points, list) else 0))
        for p in points if isinstance(points, list) else []:
            if _count(p) > 7:
                problems.append("%s: \"%s\" is %d words; a point on a comparison is 7 at most. It is a label, not a sentence."
                                % (where, str(p)[:50], _count(p)))
        return
    if rule.get("percent"):
        try:
            pct = float(value)
        except (TypeError, ValueError):
            pct = -1
        if not 0 < pct < 100:
            problems.append("%s: 'percent' is a number between 1 and 99." % where)
        return
    if rule.get("image"):
        try:
            C.brand_picture(brand, value, "picture", folder=brand.home)
        except YouTubeError as e:
            problems.append("%s: %s" % (where, e))
        return
    if rule.get("point"):
        ok = isinstance(value, dict) and all(isinstance(value.get(k), (int, float)) and 0 <= value[k] <= 100 for k in ("x", "y"))
        if not ok:
            problems.append("%s: 'point' says where the mark goes on the picture, as {\"x\": 0-100, \"y\": 0-100}." % where)
        return
    if "index_of" in rule:                      # checked against its list by the caller
        return
    if "items" in rule:
        low, high = rule["items"]
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            problems.append("%s: '%s' is a list of short lines." % (where, key))
            return
        if not low <= len(value) <= high:
            problems.append("%s: '%s' has %d entries; this kind of slide takes %d to %d. %s"
                            % (where, key, len(value), low, high,
                               "Split it across two slides." if len(value) > high else "Add one, or use a statement slide."))
        for v in value:
            if _count(v) > rule["words"]:
                problems.append("%s: \"%s\" is %d words; an entry here is %d at most. It is a label, not a sentence."
                                % (where, v[:50], _count(v), rule["words"]))
        return
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        problems.append("%s: '%s' should be text." % (where, key))
        return
    text = str(value)
    if "words" in rule and _count(text) > rule["words"]:
        problems.append("%s: '%s' has %d words; this kind of slide holds %d at most. Keep the one idea and cut the "
                        "rest, or split it across two slides." % (where, key, _count(text), rule["words"]))
    if "chars" in rule and len(text.strip()) > rule["chars"]:
        problems.append("%s: '%s' is %d characters; at most %d read at a glance." % (where, key, len(text.strip()), rule["chars"]))


def _spoken_runs(script):
    """Every run of NARRATION_RUN spoken words in the script, for the no-narration check."""
    runs = set()
    if script is None:
        return runs
    for _name, say in script.spoken():
        words = [w.lower() for w in _WORD.findall(say)]
        for i in range(len(words) - NARRATION_RUN + 1):
            runs.add(" ".join(words[i:i + NARRATION_RUN]))
    return runs


def validate(brand, spec, script=None, proof_ids=()):
    """(problems, unverified). Problems stop the deck being drawn and each one names its slide.
    `unverified` lists numbers that will be drawn with a written source the brand's files cannot
    confirm; the person is told about each of them."""
    brand = as_brand(brand)
    problems, unverified = [], []
    if not isinstance(spec, dict) or not isinstance(spec.get("slides"), list) or not spec["slides"]:
        return ["A deck is a group of settings with a list of 'slides' in it, and it needs at least one slide."], []
    for key in sorted(set(spec) - TOP_KEYS):
        problems.append("'%s' is not a deck setting. The settings are: %s." % (key, ", ".join(sorted(TOP_KEYS))))
    if spec.get("ground") not in (None,) + GROUNDS:
        problems.append("The deck's background is one of: %s." % ", ".join(GROUNDS))
    try:
        brand.identity(spec.get("identity")) if spec.get("identity") else None
    except Exception as e:
        problems.append(str(e))
    if len(spec["slides"]) > MAX_SLIDES:
        problems.append("The deck has %d slides; %d is the most that can be drawn at once." % (len(spec["slides"]), MAX_SLIDES))

    spoken = _spoken_runs(script)
    for i, slide in enumerate(spec["slides"], 1):
        if not isinstance(slide, dict):
            problems.append("Slide %d is not a group of settings." % i)
            continue
        where = _where(i, slide)
        arch = ARCHETYPES.get(slide.get("type"))
        if arch is None:
            problems.append("%s: '%s' is not a kind of slide. The kinds are: %s."
                            % (where, slide.get("type"), ", ".join(ARCHETYPES)))
            continue
        for key in sorted(set(slide) - set(arch["fields"]) - COMMON_KEYS):
            problems.append("%s: '%s' is not a setting for this kind of slide. It takes: %s."
                            % (where, key, ", ".join(sorted(arch["fields"]))))
        if slide.get("ground") not in (None,) + GROUNDS:
            problems.append("%s: the background is one of: %s." % (where, ", ".join(GROUNDS)))
        for key, rule in arch["fields"].items():
            _check_field(problems, where, key, rule, slide.get(key), brand)
        if slide.get("type") == "ranking" and slide.get("highlight") is not None:
            rows = slide.get("rows") if isinstance(slide.get("rows"), list) else []
            if not isinstance(slide["highlight"], int) or not 1 <= slide["highlight"] <= max(1, len(rows)):
                problems.append("%s: 'highlight' is the number of the row that is the point (1 to %d)." % (where, len(rows)))

        texts = _texts(slide)
        total = sum(_count(t) for k, t in texts if k != "source")
        if total > MAX_WORDS_ON_A_SLIDE:
            problems.append("%s holds %d words in all; %d is the most a viewer takes in while someone is talking. "
                            "Split it across two slides." % (where, total, MAX_WORDS_ON_A_SLIDE))
        has_note = False
        for key, text in texts:
            if key == "source":
                continue
            for pattern, what in _PRODUCTION:
                if pattern.search(text):
                    has_note = True
                    problems.append("%s: '%s' contains %s (\"%s\"). Slides are only for the viewer; keep notes for "
                                    "the people making the video in the script." % (where, key, what, text[:50]))
                    break
            words = [w.lower() for w in _WORD.findall(text)]
            for j in range(len(words) - NARRATION_RUN + 1):
                if " ".join(words[j:j + NARRATION_RUN]) in spoken:
                    problems.append("%s: '%s' repeats a spoken line from the script word for word (\"%s\"). A slide "
                                    "shows the idea; the person says the sentence." % (where, key, text[:60]))
                    break

        shown = " ".join(t for k, t in texts if k != "source")
        if slide.get("percent") is not None:
            shown += " %s%%" % slide.get("percent")
        report = grounding.ground_draft(T.claims_only(shown), brand, proof_ids=proof_ids)
        source = str(slide.get("source") or "").strip()
        if report["ungrounded"] and not has_note:       # a timecode is already reported for what it is
            if source:
                unverified.append("%s shows %s with the source \"%s\", which the brand's files cannot confirm."
                                  % (where, ", ".join(report["ungrounded"]), source[:80]))
            else:
                problems.append("%s shows %s, which does not trace to %s's facts, research or linked proof, and no "
                                "source is written on the slide. Record the fact, add its source, or change the slide."
                                % (where, ", ".join(report["ungrounded"]), brand.name))
        if arch.get("needs_source") and not source:
            problems.append("%s needs a 'source': where these words were said, so that they can be checked." % where)
        found, _warnings = T.brand_findings(brand, shown)
        problems.extend("%s: %s" % (where, p) for p in found)
    return problems, unverified


# ----------------------------------------------------------------------------- drawing each kind
def _e(text):
    return L.emph(str(text))


def _footer(kit):
    return '<div class="foot16"><span class="wm">%s</span></div>' % ('<i class="chip"></i>' + L.esc(kit.wordmark))


MAIN = (120, 96, 1680, 820)


def _draw_title(s, kit):
    inner = L.fit("title", _e(s["title"]), 150, 72, "h", lead=1.45)
    if s.get("sub"):
        inner += L.fit("sub", _e(s["sub"]), 52, 36, "sub")
    return C.box("slide", MAIN, inner)


def _draw_statement(s, kit):
    return C.box("slide", MAIN, L.fit("text", _e(s["text"]), 128, 64, "h", lead=1.5))



def shown_source(brand, source):
    """What the audience reads under a number. A pointer into the brand's own files
    (`fact:<id>`, `proof:<id>`) is for the fact check, not for viewers: show where the fact
    really comes from instead. Anything else is shown as written."""
    text = str(source or "").strip()
    low = text.lower()
    try:
        if low.startswith("fact:"):
            from smf.studio import grounding
            facts, _notes = grounding.load_facts(brand)
            for f in facts:
                if f.get("id") == text[5:].strip() and str(f.get("source") or "").strip():
                    return str(f["source"]).strip()
            return ""
        if low.startswith("proof:"):
            from smf.studio import grounding
            found, _missing = grounding.load_proof(brand, [text[6:].strip()])
            return str(found[0].get("source") or "").strip() if found else ""
    except Exception:
        return ""
    return text

def _draw_number(s, kit):
    inner = L.fit("number", L.esc(s["number"]), 420, 180, "bignum")
    inner += L.fit("label", _e(s["label"]), 70, 40, "lab", style="margin-top:.5em;max-width:22ch;")
    if s.get("_shown_source"):
        inner += L.fit("source", L.esc("Source: " + s["_shown_source"]), 30, 24, "src")
    return C.box("slide", MAIN, inner)


def _draw_share(s, kit):
    lit = int(round(float(s["percent"])))
    dots = "".join('<i class="on"></i>' if i < lit else "<i></i>" for i in range(100))
    right = L.fit("number", L.esc("%g%%" % float(s["percent"])), 300, 150, "bignum")
    right += L.fit("label", _e(s["label"]), 62, 38, "lab", style="margin-top:.45em;")
    if s.get("_shown_source"):
        right += L.fit("source", L.esc("Source: " + s["_shown_source"]), 28, 24, "src")
    return ('<div class="abs" style="left:120px;top:150px;width:700px;height:700px;"><div class="dots">%s</div></div>%s'
            % (dots, C.box("words", (920, 120, 880, 780), right)))


def _side(name, part, rect, win):
    x, y, w, h = rect
    items = "".join('<div class="pitem" data-fit="%s point" data-min="36" data-fitgroup="points" style="font-size:64px;">'
                    '%s<span>%s</span></div>'
                    % (name, L.ICONS["check" if win else "cross"], _e(p)) for p in (part.get("items") or []))
    return ('<div class="panel%s" data-fitbox="%s" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx;">%s%s</div>'
            % (" win" if win else "", name, x, y, w, h,
               L.fit("%s title" % name, _e(part["title"]), 104, 52, "ptitle", group="side titles"), items))


def _draw_compare(s, kit):
    top = 96
    inner = ""
    if s.get("title"):
        inner += C.box("heading", (120, 80, 1680, 170), L.fit("title", _e(s["title"]), 84, 48, "h"))
        top = 280
    height = 900 - top
    return inner + _side("left", s["left"], (120, top, 820, height), False) + _side("right", s["right"], (980, top, 820, height), True)


def _draw_steps(s, kit):
    cards = "".join('<div class="card" data-fitbox="step %d"><div class="stepno">%d</div>%s</div>'
                    % (i, i, L.fit("step %d" % i, _e(t), 76, 36, "cardtext", group="steps"))
                    for i, t in enumerate(s["steps"], 1))
    return (C.box("heading", (120, 90, 1680, 230), L.fit("title", _e(s["title"]), 96, 52, "h"))
            + '<div class="cardrow" style="left:120px;top:380px;width:1680px;height:480px;">%s</div>' % cards)


def _draw_list(s, kit):
    items = "".join('<div class="pitem" data-fit="item %d" data-min="38" data-fitgroup="items" style="font-size:66px;'
                    'margin-top:.5em;">%s<span>%s</span></div>' % (i, L.ICONS["check"], _e(t)) for i, t in enumerate(s["items"], 1))
    return C.box("slide", MAIN, L.fit("title", _e(s["title"]), 100, 54, "h") + items, "box top", "padding-top:40px;")


def _draw_ranking(s, kit):
    hi = s.get("highlight") or 1
    rows = "".join('<div class="rrow%s" data-fitbox="row %d"><span class="pos">%d</span>%s</div>'
                   % (" on" if i == hi else "", i, i, L.fit("row %d" % i, _e(t), 60, 36, "rt", "span", group="rows"))
                   for i, t in enumerate(s["rows"], 1))
    return (C.box("heading", (120, 80, 1680, 200), L.fit("title", _e(s["title"]), 92, 52, "h"))
            + '<div class="rowlist" style="left:120px;top:320px;width:1680px;height:600px;">%s</div>' % rows)


def _draw_progress(s, kit):
    pct = float(s["percent"])
    inner = L.fit("label", _e(s["label"]), 110, 56, "h", lead=1.2)
    bar = ('<div class="bar" style="left:120px;top:600px;width:1680px;"><div class="done" style="width:%g%%;"></div>'
           '<div class="rest"></div></div>' % pct)
    under = ('<div class="abs" style="left:120px;top:730px;width:1680px;height:150px;display:flex;justify-content:space-between;'
             'align-items:flex-start;" data-fitbox="under">%s%s</div>'
             % (L.fit("number", L.esc("%g%%" % pct), 72, 44, "lab", "span"),
                L.fit("rest", _e(s.get("rest") or ""), 60, 36, "lab", "span", style="color:var(--accent);") if s.get("rest") else ""))
    if s.get("_shown_source"):
        under += C.box("source", (120, 880, 1680, 60), L.fit("source", L.esc("Source: " + s["_shown_source"]), 28, 24, "src", style="margin-top:0;"))
    # Bottom-aligned text needs a little room under it: with tight line spacing the letters' own
    # boxes reach a few pixels below the line, and flush against the edge that reads as overflow.
    return C.box("heading", (120, 96, 1680, 460), inner, "box bottom", "padding-bottom:28px;") + bar + under


def _draw_picture(s, kit, brand):
    path = C.brand_picture(brand, s["image"], "picture", folder=brand.home)
    room_w, room_h, pad = 1680, (760 if s.get("caption") else 880), 28
    try:
        from PIL import Image
        with Image.open(path) as im:
            pic_w, pic_h = im.size
    except Exception:
        raise YouTubeError("The picture '%s' could not be opened as an image." % s["image"])
    scale = min((room_w - 2 * pad) / float(pic_w), (room_h - 2 * pad) / float(pic_h))
    shown_w, shown_h = int(pic_w * scale), int(pic_h * scale)
    mat_w, mat_h = shown_w + 2 * pad, shown_h + 2 * pad
    left, top = 120 + (room_w - mat_w) // 2, 80 + (room_h - mat_h) // 2
    ring = ""
    if s.get("point"):
        ring = ('<div class="ring" style="left:%dpx;top:%dpx;"></div>'
                % (pad + shown_w * float(s["point"]["x"]) / 100.0, pad + shown_h * float(s["point"]["y"]) / 100.0))
    inner = ('<div class="mat" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx;"><img src="%s" alt="">%s</div>'
             % (left, top, mat_w, mat_h, L.esc(Path(path).as_uri()), ring))
    if s.get("caption"):
        inner += C.box("caption", (120, 856, 1680, 110), L.fit("caption", _e(s["caption"]), 58, 36, "lab"))
    return inner


def _draw_quote(s, kit):
    inner = '<div class="qmark">&ldquo;</div>' + L.fit("text", _e(s["text"]), 84, 44, "qtext")
    inner += L.fit("who", L.esc(s["who"]), 44, 30, "sub")
    inner += L.fit("source", L.esc("Source: " + str(s.get("_shown_source") or "")), 28, 24, "src")
    return C.box("slide", MAIN, inner)


def _draw_ask(s, kit):
    inner = L.fit("title", _e(s["title"]), 140, 68, "h", lead=1.35)
    if s.get("sub"):
        inner += L.fit("sub", _e(s["sub"]), 54, 36, "sub")
    if s.get("button"):
        inner += L.fit("button", L.esc(s["button"]) + L.ICONS["arrow"], 52, 34, "pill")
    return C.box("slide", MAIN, inner)


def _draw_next(s, kit):
    inner = L.fit("label", "Watch next", 34, 26, "small", style="margin-bottom:1.2em;")
    inner += L.fit("title", _e(s["title"]), 124, 64, "h", lead=1.3)
    if s.get("sub"):
        inner += L.fit("sub", _e(s["sub"]), 52, 36, "sub")
    return C.box("slide", MAIN, inner)


_DRAW = {"title": _draw_title, "statement": _draw_statement, "number": _draw_number, "share": _draw_share,
         "compare": _draw_compare, "steps": _draw_steps, "list": _draw_list, "ranking": _draw_ranking,
         "progress": _draw_progress, "quote": _draw_quote, "ask": _draw_ask, "next": _draw_next}


def build(brand, kit, spec):
    """Spec -> [Slide]. The spec is assumed valid (see `validate`)."""
    slides, total = [], len(spec["slides"])
    for i, s in enumerate(spec["slides"], 1):
        ground = s.get("ground") or spec.get("ground") or ("soft" if kit.is_dark() else "bold")
        pal = dict(kit.palette(ground))
        for slot in ("accent", "number"):            # a deck is often watched small, in a corner of the video
            pal[slot] = ensure_contrast(pal[slot], pal["bg"], 4.5, [pal["head"]])
        s = dict(s, _shown_source=shown_source(brand, s.get("source")))      # viewers see a source, never a pointer
        inner = _draw_picture(s, kit, brand) if s["type"] == "picture" else _DRAW[s["type"]](s, kit)
        slides.append(L.Slide(name=s["type"], html=C.page(kit, pal, SIZE, inner + _footer(kit), CSS), size=SIZE,
                              label="Slide %d of %d (%s)" % (i, total, ARCHETYPES[s["type"]]["name"])))
    return slides


# ----------------------------------------------------------------------------- every slide on one page
def contact_sheet(image_paths, out_path, columns=4, tile=(480, 270), gap=16, ground=(255, 255, 255)):
    """One picture showing every slide small, in order, so the whole deck can be looked at at once."""
    from PIL import Image, ImageDraw

    paths = [Path(p) for p in image_paths]
    columns = max(1, min(columns, len(paths)))
    rows = (len(paths) + columns - 1) // columns
    label_h = 30
    sheet = Image.new("RGB", (gap + columns * (tile[0] + gap), gap + rows * (tile[1] + label_h + gap)), ground)
    pen = ImageDraw.Draw(sheet)
    for n, p in enumerate(paths):
        with Image.open(p) as im:
            small = im.convert("RGB").resize(tile, Image.LANCZOS)
        x = gap + (n % columns) * (tile[0] + gap)
        y = gap + (n // columns) * (tile[1] + label_h + gap)
        sheet.paste(small, (x, y))
        pen.rectangle((x, y, x + tile[0] - 1, y + tile[1] - 1), outline=(200, 200, 200))
        pen.text((x + 2, y + tile[1] + 8), "%d" % (n + 1), fill=(60, 60, 60))
    out_path = Path(out_path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".png", dir=str(out_path.parent))
    os.close(fd)
    try:
        sheet.save(tmp, "PNG")
        replace_patiently(tmp, str(out_path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out_path


def _write_json_atomic(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(Path(path).parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    replace_patiently(tmp, str(path))


def render(brand, spec, out_dir, script=None, proof_ids=(), renderer=None):
    """Draw a deck for ONE brand. Returns (files, report): the slide pictures in order, then the
    PDF, then the contact sheet. Raises YouTubeError, naming the slide, before any browser starts
    when the spec breaks a rule."""
    brand = as_brand(brand)
    problems, unverified = validate(brand, spec, script=script, proof_ids=proof_ids)
    if problems:
        raise YouTubeError("This deck cannot be drawn yet:\n  - " + "\n  - ".join(problems))
    kit = resolve(brand)
    slides = build(brand, kit, spec)
    out_dir = Path(os.path.abspath(str(out_dir)))
    out_dir.mkdir(parents=True, exist_ok=True)
    name = slugify(spec.get("name") or "deck", "deck", 32)
    written, shrunk = [], []

    def draw(r):
        before = len(r.refused)
        for i, slide in enumerate(slides, 1):
            path = out_dir / ("%s-%02d-%s.png" % (name, i, slide.name))
            info = r.render(slide.html, path, slide.size, slide.label)
            written.append(path)
            shrunk.extend(dict(item, slide=i) for item in info["shrunk"])
        return r.refused[before:]

    try:
        if renderer is not None:
            asked = draw(renderer)
        else:
            with Renderer() as r:
                asked = draw(r)
        pdf_path, pdf_notes = images_to_pdf(written, out_dir / (name + ".pdf"))
        sheet = contact_sheet(written, out_dir / SHEET_NAME)
    except (RenderError, PdfError) as e:
        for p in written:                                   # half a deck is worse than none
            try:
                p.unlink()
            except OSError:
                pass
        raise YouTubeError(str(e))
    report = {"brand": brand.id, "size": list(SIZE), "folder": str(out_dir), "files": [p.name for p in written],
              "pdf": pdf_path.name, "contact_sheet": sheet.name,
              "headings_in_order": [heading_of(s) for s in spec["slides"]],
              "unverified": unverified, "shrunk_to_fit": shrunk, "notes": list(kit.notes) + list(pdf_notes),
              "fonts": {f.role: "%s (%s)" % (f.path.name, f.origin) for f in kit.faces},
              "network_requests": asked, "made_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write_json_atomic(out_dir / REPORT_NAME, report)
    return written + [pdf_path, sheet], report
