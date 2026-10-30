"""thumbnail.py - a thumbnail as a three-second read, drawn in the brand's colours, checked small.

A thumbnail is seen for a moment, at the size of a postage stamp, beside a dozen others. So it
holds ONE subject (one face or one object), THREE TO FIVE WORDS at most, and ONE contrast. It is
drawn at 1280x720 by the Factory's own picture renderer: the brand's colours, the fonts that ship
with the Factory (or the brand's own), offline, with text that is made to fit.

A spec is a small dict (save it as JSON and a person can edit it):

    {"name": "a", "layout": "photo-right", "text": "Looked ready.\\nWas not.", "accent": "not",
     "photo": "Brand/brand-kit/photos/dense-loaf.jpg", "ground": "bold"}

LAYOUTS
    words         the words alone, as large as they will go
    photo-right   words on the left, the brand's photo filling the right
    photo-left    the mirror of it
    photo-full    the brand's photo edge to edge, darkened on one side, words over the dark side
    versus        two halves, a word or two on each, an optional photo behind each
    number        one very large number and up to four words. The number must trace to the
                  brand's facts, like any number a viewer can read

`ground` picks the background from the brand's own colours: bold (its headline colour, words
reversed), main, soft, accent or black. `face` is `poster` (condensed capitals, the default) or
`display`. `focus` says which part of a photo to keep when it is cropped: top, centre, bottom,
left or right.

PHOTOS COME FROM THE BRAND'S OWN FOLDER
A photo is only ever a file in the brand kit's photos folder. It is used as it is: no cut-out
is needed, and none is made. That folder may hold the brand's own photos, stock photos filed
there, and images generated for the brand at the person's request (smf/studio/render/library.py
records which is which). Nothing is generated or fetched here. A brand with no photos uses
`words`, `versus` or `number`, which need none.

THE SMALL-SIZE CHECK
Every drawn thumbnail is also saved at 320 pixels wide, which is about how it is met in a feed,
and measured there, from the pixels: how strongly the words stand out from what is behind them
(a contrast of at least 4.5 to 1), and how tall the smallest line of words is (at least 12
pixels). A thumbnail that fails is still saved, so a person can see why, and is reported as
not legible with what to change. Then LOOK at the small one. The measurement catches faint and
tiny; only eyes catch confusing.

The bottom right corner is kept clear, because the platform draws the running time there.
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
from smf.brands import contrast, replace_patiently
from smf.studio.render.kit import ensure_contrast, resolve
from smf.youtube import YouTubeError, as_brand, slugify
from smf.youtube import canvas as C
from smf.youtube import titles as T

SIZE = C.THUMBNAIL
SMALL_WIDTH = 320
MAX_WORDS = 5
MIN_CONTRAST = 4.5
MIN_TEXT_HEIGHT = 12            # pixels, in the 320-wide copy
FLOOR_PX = 72                   # the words are never drawn smaller than this at full size
REPORT_NAME = "thumbnails-report.json"

LAYOUTS = ("words", "photo-right", "photo-left", "photo-full", "versus", "number")
GROUNDS = ("bold", "main", "soft", "accent", "black")
FACES = ("poster", "display")
FOCUS = {"top": "center 12%", "centre": "center center", "center": "center center", "bottom": "center 88%",
         "left": "18% center", "right": "82% center"}
KEYS = {"name", "layout", "text", "accent", "photo", "ground", "face", "focus", "left", "right", "number", "source"}
SIDE_KEYS = {"text", "photo", "focus"}

# Where the words sit, per layout: (x, y, width, height) at 1280x720. The small-size check
# measures inside these, scaled down. Every box stops short of the bottom right corner.
TEXT_BOXES = {
    "words": [(72, 56, 1136, 560)],
    "photo-right": [(64, 56, 640, 608)],
    "photo-left": [(576, 56, 640, 540)],
    "photo-full": [(64, 56, 600, 608)],
    "versus": [(40, 190, 510, 410), (730, 190, 510, 410)],
    "number": [(72, 40, 1136, 370), (72, 430, 1000, 230)],
}
# In `photo-full` the photo fills everything to the right of the words and fades into the
# background beneath them, so a subject in the middle of the photo stays in view.
PHOTO_BOXES = {"photo-right": (768, 0, 512, 720), "photo-left": (0, 0, 512, 720), "photo-full": (400, 0, 880, 720)}
TARGET_CONTRAST = MIN_CONTRAST + 0.4       # aimed a little high: soft edges cost some contrast when shrunk

CSS = """
.scrim{position:absolute;inset:0;}
.edge{position:absolute;left:0;top:0;bottom:0;width:14px;background:var(--accent);}
.half{position:absolute;top:0;bottom:0;width:640px;overflow:hidden;}
.half.one{left:0;background:var(--bg);}
.half.two{left:640px;background:var(--panel);}
.divide{position:absolute;left:634px;top:0;bottom:0;width:12px;background:var(--accent);}
.badge{position:absolute;left:575px;top:295px;width:130px;height:130px;border:10px solid var(--bg);
  border-radius:50%;background:var(--accent);
  color:var(--pill-fg);display:flex;align-items:center;justify-content:center;font-family:"smf-poster",sans-serif;
  font-size:64px;text-transform:uppercase;line-height:1;}
.big{font-family:"smf-display",sans-serif;font-weight:800;letter-spacing:-0.05em;line-height:.92;
  font-variant-numeric:tabular-nums;color:var(--number);white-space:nowrap;}
.disp{font-family:"smf-display",sans-serif;font-weight:800;letter-spacing:-0.035em;line-height:1.0;color:var(--head);
  text-wrap:balance;}
.disp .mark{color:var(--accent);}
"""


def _words(*parts):
    return sum(len(re.findall(r"\S+", str(p or ""))) for p in parts)


def _side_of(spec, side):
    """One side of a 'versus' thumbnail as a group of settings. A side written as plain words is
    reported by the check; everywhere else it is simply treated as empty rather than crashing."""
    part = (spec or {}).get(side)
    return part if isinstance(part, dict) else {}


def all_text(spec):
    bits = [spec.get("text"), spec.get("number")]
    bits += [_side_of(spec, side).get("text") for side in ("left", "right")]
    return " ".join(str(b) for b in bits if b)


# ----------------------------------------------------------------------------- checking a spec
def validate_spec(brand, spec, proof_ids=()):
    """Problems with one thumbnail spec, as plain sentences. An empty list means it can be drawn."""
    brand = as_brand(brand)
    if not isinstance(spec, dict):
        return ["A thumbnail is described by a group of settings (layout, text and so on)."]
    problems = []
    layout = spec.get("layout")
    if layout not in LAYOUTS:
        return ["'%s' is not a thumbnail layout. Choose from: %s." % (layout, ", ".join(LAYOUTS))]
    for key in sorted(set(spec) - KEYS):
        problems.append("'%s' is not a thumbnail setting. The settings are: %s." % (key, ", ".join(sorted(KEYS))))
    if spec.get("ground") not in (None,) + GROUNDS:
        problems.append("The background is one of: %s." % ", ".join(GROUNDS))
    if spec.get("face") not in (None,) + FACES:
        problems.append("The lettering is one of: %s." % ", ".join(FACES))
    if spec.get("focus") not in (None,) + tuple(FOCUS):
        problems.append("The part of the photo to keep is one of: top, centre, bottom, left, right.")

    if layout == "versus":
        for side in ("left", "right"):
            part = spec.get(side)
            if not isinstance(part, dict) or not str(part.get("text") or "").strip():
                problems.append("A 'versus' thumbnail needs a word or two on the %s side." % side)
                continue
            for key in sorted(set(part) - SIDE_KEYS):
                problems.append("'%s' is not a setting for one side. A side takes: %s." % (key, ", ".join(sorted(SIDE_KEYS))))
        if spec.get("text"):
            problems.append("A 'versus' thumbnail has its words on the two sides, not in 'text'.")
    elif layout == "number":
        if not str(spec.get("number") or "").strip():
            problems.append("A 'number' thumbnail needs the number.")
        elif len(str(spec["number"]).strip()) > 7:
            problems.append("The number is %d characters. At most 7 read at a glance (for example 18h, 72%%, 4,420)."
                            % len(str(spec["number"]).strip()))
    elif not str(spec.get("text") or "").strip() and layout == "words":
        problems.append("A 'words' thumbnail needs its words.")

    # A side written as plain words instead of a group of settings has already been reported
    # above; it must not crash the check on the way past.
    count = _words(spec.get("text"), *[_side_of(spec, s).get("text") for s in ("left", "right")])
    if count > MAX_WORDS:
        problems.append("There are %d words. A thumbnail is read in under three seconds at the size of a stamp: "
                        "%d words at most. The title carries the rest." % (count, MAX_WORDS))
    if str(spec.get("text") or "").count("\n") > 2:
        problems.append("The words are on %d lines. Three lines at most." % (str(spec["text"]).count("\n") + 1))

    needs_photo = layout in PHOTO_BOXES
    if needs_photo and not spec.get("photo"):
        problems.append("The '%s' layout needs one of %s's own photos (from its brand kit's photos folder). With no "
                        "photo, use 'words', 'versus' or 'number'." % (layout, brand.name))
    photos = [("photo", spec.get("photo"))] + [("%s photo" % s, _side_of(spec, s).get("photo")) for s in ("left", "right")
                                               if isinstance(spec.get(s), dict)]
    for what, rel in photos:
        if rel:
            try:
                C.brand_picture(brand, rel, what)
            except YouTubeError as e:
                problems.append(str(e))
    if spec.get("photo") and not needs_photo and layout != "versus":
        problems.append("The '%s' layout has no place for a photo. Use photo-right, photo-left or photo-full." % layout)

    text = all_text(spec)
    if text.strip():
        report = grounding.ground_draft(T.claims_only(text), brand, proof_ids=proof_ids)
        if report["ungrounded"]:
            problems.append("It shows %s, which does not trace to anything in %s's facts, research or linked proof. "
                            "A number on a thumbnail is a claim like any other." % (", ".join(report["ungrounded"]), brand.name))
        found, _warnings = T.brand_findings(brand, text)
        problems.extend(found)
    return problems


def advice(spec, title=""):
    """Warnings that do not stop a thumbnail being drawn."""
    out = []
    mine = set(re.findall(r"[a-z0-9']+", all_text(spec).lower()))
    theirs = set(re.findall(r"[a-z0-9']+", str(title or "").lower()))
    small = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "my", "your", "for", "vs"}
    mine, theirs = mine - small, theirs - small
    if mine and theirs and len(mine & theirs) >= max(2, int(round(len(mine) * 0.6))):
        out.append("the words repeat the title. The thumbnail and the title are read together, so let the "
                   "thumbnail add something the title does not say")
    if not mine and (spec or {}).get("layout") in PHOTO_BOXES:
        out.append("there are no words, which can work when the photo says it all. Draw a version with words too, "
                   "and compare them small")
    return out


# ----------------------------------------------------------------------------- building the page
def _img(path, focus):
    return ('<img src="%s" alt="" style="object-position:%s">' % (L.esc(Path(path).as_uri()), FOCUS.get(focus or "centre")))


def _headline(spec, field, text, accent, warnings, designed, lead, group=""):
    face = spec.get("face") or "poster"
    cls = "poster" if face == "poster" else "disp"
    return L.fit(field, L.rich(text, accent, warnings, "the words"), designed, FLOOR_PX, cls, group=group, lead=lead)


def build(brand, kit, spec):
    """One thumbnail spec -> a Slide the renderer can draw."""
    layout = spec["layout"]
    ground = spec.get("ground") or ("black" if layout == "photo-full" else kit.strong())
    pal = dict(kit.palette(ground))
    # Card-sized type may use a highlight at 3 to 1. At the size of a stamp that is too faint, so
    # the highlight and the number are moved toward the headline colour until they read.
    for slot in ("accent", "number"):
        pal[slot] = ensure_contrast(pal[slot], pal["bg"], TARGET_CONTRAST, [pal["head"]])
    warnings = []
    if spec.get("accent") and contrast(pal["accent"], pal["head"]) < 1.25:
        warnings.append("On this background no second colour stays readable, so the highlighted word is drawn in the "
                        "same colour as the rest. Use the bold or main background if the highlight matters.")
    boxes = TEXT_BOXES[layout]
    inner = ""

    if layout in PHOTO_BOXES:
        x, y, w, h = PHOTO_BOXES[layout]
        photo = C.brand_picture(brand, spec["photo"], "photo")
        inner += '<div class="photo" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx;">%s</div>' % (
            x, y, w, h, _img(photo, spec.get("focus")))
        if layout == "photo-full":
            inner += ('<div class="scrim" style="background:linear-gradient(90deg,%s 0px,%s 400px,%s 580px,'
                      'transparent 820px);"></div>' % (pal["bg"], pal["bg"], _rgba(pal["bg"], .74)))
    if layout not in ("versus", "photo-left"):            # the brand's edge: only where the left is not a photo
        inner += '<div class="edge"></div>'

    if layout == "versus":
        sides = []
        for cls, side in (("one", "left"), ("two", "right")):
            part = spec[side]
            behind = ""
            if part.get("photo"):
                behind = ('<div class="photo" style="inset:0;">%s</div><div class="scrim" style="background:%s;"></div>'
                          % (_img(C.brand_picture(brand, part["photo"], "%s photo" % side), part.get("focus")),
                             _rgba(pal["bg"], .80)))
            sides.append('<div class="half %s">%s</div>' % (cls, behind))
        inner += "".join(sides) + '<div class="divide"></div><div class="badge">vs</div>'
        for rect, side in zip(boxes, ("left", "right")):          # one group: both sides end the same size
            inner += C.box(side, rect, _headline(spec, "the %s words" % side, spec[side]["text"], spec.get("accent"),
                                                 warnings, 150, 1.8, group="versus"), "box centre")
    elif layout == "number":
        inner += C.box("number", boxes[0], L.fit("the number", L.esc(spec["number"]), 330, 150, "big"), "box")
        if spec.get("text"):
            inner += C.box("words", boxes[1], _headline(spec, "the words", spec["text"], spec.get("accent"), warnings, 110, 1.4),
                           "box top")
    elif spec.get("text"):
        inner += C.box("words", boxes[0], _headline(spec, "the words", spec["text"], spec.get("accent"), warnings,
                                                    150 if layout == "words" else 130, 2.4 if layout == "words" else 1.9))
    name = slugify(spec.get("name") or layout, "thumbnail", 24)
    return L.Slide(name=name, html=C.page(kit, pal, SIZE, inner, CSS), size=SIZE,
                   label="Thumbnail '%s'" % (spec.get("name") or layout), warnings=warnings), pal


def _rgba(hex_colour, alpha):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return "rgba(%d,%d,%d,%.2f)" % (r, g, b, alpha)


# ----------------------------------------------------------------------------- the small-size check
_LINEAR = [(v / 255.0) / 12.92 if v / 255.0 <= 0.03928 else ((v / 255.0 + 0.055) / 1.055) ** 2.4 for v in range(256)]


def _luminance(rgb):
    return 0.2126 * _LINEAR[rgb[0]] + 0.7152 * _LINEAR[rgb[1]] + 0.0722 * _LINEAR[rgb[2]]


def _median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


def _split_point(lums):
    """The luminance that best separates a region into two groups (the method is the classic one
    for separating ink from paper: choose the cut that makes the two groups most different)."""
    bins = 64
    hist = [0] * bins
    for v in lums:
        hist[min(bins - 1, int(v * bins))] += 1
    total, sum_all = float(len(lums)), sum(i * h for i, h in enumerate(hist))
    best, cut, w0, sum0 = -1.0, 0, 0.0, 0.0
    for i in range(bins):
        w0 += hist[i]
        if not w0 or w0 == total:
            continue
        sum0 += i * hist[i]
        m0, m1 = sum0 / w0, (sum_all - sum0) / (total - w0)
        between = w0 * (total - w0) * (m0 - m1) ** 2
        if between > best:
            best, cut = between, i
    return (cut + 1) / float(bins)


def measure_small(png_path, boxes, small_path=None):
    """Save a 320-wide copy and measure the words inside `boxes` (given at full size).

    Returns {"contrast", "text_height", "legible", "why"}. The words are taken to be the smaller
    of the two groups of pixels in each box; what is behind them is the larger."""
    from PIL import Image

    with Image.open(png_path) as im:
        full = im.convert("RGB")
    scale = SMALL_WIDTH / float(full.size[0])
    small = full.resize((SMALL_WIDTH, int(round(full.size[1] * scale))), Image.LANCZOS)
    if small_path:
        small.save(small_path, "PNG")

    contrasts, heights = [], []
    for x, y, w, h in boxes:
        region = small.crop((int(x * scale), int(y * scale), int((x + w) * scale), int((y + h) * scale)))
        width, height = region.size
        raw = region.tobytes()                              # three bytes a pixel, row after row
        lums = [_luminance(raw[i:i + 3]) for i in range(0, len(raw), 3)]
        if not lums or max(lums) - min(lums) < 0.02:
            continue                                        # an empty box: nothing was written here
        cut = _split_point(lums)
        dark = [v for v in lums if v < cut]
        light = [v for v in lums if v >= cut]
        if not dark or not light:
            continue
        ink_is_dark = len(dark) <= len(light)
        ink, paper = (dark, light) if ink_is_dark else (light, dark)
        if len(ink) < 0.004 * len(lums):
            continue
        a, b = sorted((_median(ink), _median(paper)), reverse=True)
        contrasts.append((a + 0.05) / (b + 0.05))
        rows, need = [], max(2, int(width * 0.012))
        for r in range(height):
            row = lums[r * width:(r + 1) * width]
            rows.append(sum(1 for v in row if (v < cut) == ink_is_dark) >= need)
        run, runs = 0, []
        for inked in rows + [False]:
            if inked:
                run += 1
            elif run:
                runs.append(run)
                run = 0
        runs = [r for r in runs if r >= 4]
        if runs:
            heights.append(min(runs))

    if not contrasts:
        return {"contrast": None, "text_height": None, "legible": True,
                "why": "There are no words on this one, so there was nothing to measure."}
    contrast, text_height = round(min(contrasts), 1), (min(heights) if heights else 0)
    reasons = []
    if contrast < MIN_CONTRAST:
        reasons.append("the words only stand out %.1f to 1 from what is behind them (%.1f is the least that reads "
                       "at this size). Choose a different background, or a plainer part of the photo" % (contrast, MIN_CONTRAST))
    if text_height < MIN_TEXT_HEIGHT:
        reasons.append("the smallest line of words is %d pixels tall at feed size (%d is the least that reads). "
                       "Use fewer words" % (text_height, MIN_TEXT_HEIGHT))
    return {"contrast": contrast, "text_height": text_height, "legible": not reasons,
            "why": "; ".join(reasons) or "The words read at feed size."}


# ----------------------------------------------------------------------------- drawing
def _write_json_atomic(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(Path(path).parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    replace_patiently(tmp, str(path))


def render(brand, specs, out_dir, proof_ids=(), title="", renderer=None):
    """Draw several thumbnail concepts for ONE brand with one browser. Returns (files, report).

    For each concept two files are written: `thumb-<name>.png` at 1280x720 and
    `thumb-<name>-small.png` at 320 wide, which is the one to look at. The report says how each
    one measured. Raises YouTubeError before any browser starts when a spec is wrong."""
    brand = as_brand(brand)
    specs = [dict(s) for s in (specs or [])]
    if not specs:
        raise YouTubeError("There are no thumbnail concepts to draw.")
    problems, seen = [], set()
    for i, spec in enumerate(specs, 1):
        spec.setdefault("name", chr(96 + i) if i <= 26 else str(i))
        label = "Thumbnail '%s'" % spec["name"]
        if slugify(spec["name"], "x", 24) in seen:
            problems.append("%s: two concepts share that name." % label)
        seen.add(slugify(spec["name"], "x", 24))
        problems += ["%s: %s" % (label, p) for p in validate_spec(brand, spec, proof_ids)]
    if problems:
        raise YouTubeError("These thumbnails cannot be drawn yet:\n  - " + "\n  - ".join(problems))

    kit = resolve(brand)
    out_dir = Path(os.path.abspath(str(out_dir)))
    out_dir.mkdir(parents=True, exist_ok=True)
    files, rows = [], []

    def draw(r):
        before = len(r.refused)
        for spec in specs:
            slide, _pal = build(brand, kit, spec)
            path = out_dir / ("thumb-%s.png" % slide.name)
            small = out_dir / ("thumb-%s-small.png" % slide.name)
            info = r.render(slide.html, path, slide.size, slide.label)
            measured = measure_small(path, TEXT_BOXES[spec["layout"]], small)
            files.extend([path, small])
            rows.append({"name": spec["name"], "layout": spec["layout"], "file": path.name, "small": small.name,
                         "words": _words(all_text(spec)), "shrunk_to_fit": info["shrunk"],
                         "notes": list(slide.warnings) + advice(spec, title), **measured})
        return r.refused[before:]

    try:
        if renderer is not None:
            asked = draw(renderer)
        else:
            with Renderer() as r:
                asked = draw(r)
    except RenderError as e:
        raise YouTubeError(str(e))
    report = {"brand": brand.id, "size": list(SIZE), "small_width": SMALL_WIDTH, "folder": str(out_dir),
              "thumbnails": rows, "fonts": {f.role: "%s (%s)" % (f.path.name, f.origin) for f in kit.faces},
              "notes": list(kit.notes), "network_requests": asked,
              "all_legible": all(row["legible"] for row in rows), "made_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write_json_atomic(out_dir / REPORT_NAME, report)
    return files, report
