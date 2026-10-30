"""render - a post's pictures, drawn in one brand's colours, with nothing but this computer.

    from smf import brands
    from smf.studio.render import render_post_visuals

    brand = brands.load("maple-and-main")
    files = render_post_visuals(brand, spec)            # -> [Path, Path, ...] in slide order

No key, no account and no internet connection are needed for anything in NO_KEY_FORMATS, and
every one of them works for a brand that has chosen three colours and nothing else: no logo,
no photos, no fonts of its own. The brand is always given; there is no brand to fall back to.

WHERE THE FILES GO
    Client/<brand>/Output/visuals/<date>-<time>-<name>/<name>-01-cover.png ...
plus `render-report.json` beside them (fonts used, text that was shrunk to fit, warnings such
as a number with no source). Pass `out_dir` to write somewhere else. Pictures are 1080x1350
unless the spec asks for another size, or 1080x1920 (tall) for a brand that posts only to
TikTok (see default_size).

THE SPEC (a plain dict; save it as JSON and it is a file Claude or a person can edit)

    {
      "format":   "carousel",            one of NO_KEY_FORMATS, below
      "identity": "person",              which of the brand's identities is speaking
      "slides":   [ {...}, {...} ],      what goes on each picture (fields depend on the format)

      "size":        "portrait",         optional: portrait 1080x1350 | square 1080x1080 | story 1080x1920
      "name":        "sourdough-myths",  optional: used in the folder and file names
      "pdf":         true,               optional: also save the slides as one PDF document
      "footer_line": "mapleandmain.example",   optional: replaces the brand's usual footer line
      "theme":       "dark",             notes and post-screenshot only: dark | light
      "avatar":      "Brand/brand-kit/photos/ava.jpg"    post-screenshot only, see raw.py
    }

In any `headline` (or `title`), "accent" names the word or words to colour: text or a list.
A line break in the text is kept. "ground" picks a slide's background from the brand's own
colours: main (its background) | soft (its tinted surface) | bold (its headline colour, text
reversed) | accent.

FORMATS AND THEIR SLIDES
  carousel         first slide is the cover, last is the closing slide, 2 to 8 in the middle.
                   Each slide may say its "kind"; without one, the first is `cover`, the last
                   `cta` and the rest `point`.
      cover        {eyebrow?, headline, accent?, kicker?, ground?}
      point        {eyebrow?, headline, accent?, kicker?, ground?}
      steps        {eyebrow?, title, steps: [{label?, head, body?} x 2-5], result?, ground?}
                   (*stars* around a word in title, head or result colour it)
      checklist    {eyebrow?, title, accent?, items: [2-7 short lines], ground?}
      compare      {left: {tag?, title, note?, items: [2-5]}, right: {the same}}
      stat         {eyebrow?, stat, headline, accent?, kicker?, source?, ground?}
      cta          {eyebrow?, headline, accent?, kicker?, button?, ground?}
  stat             {eyebrow?, tag?, stat, headline, accent?, kicker?, button?, source?, ground?}
  split            {eyebrow?, tag?, before: {tag, value, sub?}, after: {tag, value, sub?},
                    headline, accent?, button?, ground?}
  alert            {eyebrow?, tag?, headline, accent?, support?, button?, badge?, ground?}
  headline         {eyebrow?, tag?, headline, accent?, support?, button?, ground?}
  notes            {title, items?: [1-6 lines], closer?}   or   {text}
  post-screenshot  {text}
  bold-text        {headline, accent?, subline?, button?, ground?: bold|accent|main|black,
                    layout?: ad|statement}
The card formats draw one picture per entry in "slides".

A FREE DESIGN
  free             {name?, html, css?, source?}   one picture per entry
A page designed for this brand and this picture instead of a fixed layout. What may go in it,
what it is given (the brand's fonts and colours) and what it must pass are in free.py. It is
drawn locked (it can open the brand's fonts and nothing else on this computer, and scripts do
not run) and checked as drawn: every word on the picture, not cut off, big enough for a phone,
in the brand's fonts and readable against what is behind it. Its claims are read from the drawn
picture, not from the spec. The design is saved beside the pictures as `<name>-design.json`.

NUMBERS AND CLAIMS
Words drawn on a picture are read by exactly the same people as the caption, so they are checked
the same way. Every claim a picture makes is traced to the brand's own facts, research and linked
proof, and `render-report.json` records, per picture, each claim and whether it was confirmed.
`posts attach` reads that back: an unconfirmed claim in a picture makes the whole post unverified.

A `stat` slide's "source" may point into the brand's own files ("fact:<id>" or "proof:<id>"); the
picture then shows where the fact really comes from, and the pointer counts as evidence only when
that fact states the figure. A source line somebody typed is printed as written and confirms
nothing: a picture cannot carry an explanation, so a caption under a number is not a check.

NOTHING IS HALF-REPLACED
A set of pictures is drawn into a fresh folder beside the destination and moved into place only
once every one of them has passed. If any picture fails, nothing is moved and the pictures that
were already there are left exactly as they were, which matters most when they are the ones
somebody has already approved.

TEXT ALWAYS FITS, OR THE RENDER SAYS WHY NOT
`validate_spec(brand, spec)` explains problems in plain words before a browser starts. While
drawing, text is shrunk to fit its box down to a readable floor; text that still does not fit
stops the render with a message naming the slide, the field and the line.

Left for a later step (they need things a new brand does not have): cards built around a
screenshot or photo from the brand's proof library, and every format that needs an
image-generation key or photos of a person.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from smf import brands
from smf.brands import Brand, BrandError, replace_patiently
from smf.studio import grounding
from smf.studio.render import cards, carousel, free, raw, text_ad
from smf.studio.render.engine import RenderError, Renderer, renderer_available, size_for
from smf.studio.render.kit import resolve
from smf.studio.render.pdf import PdfError, images_to_pdf
from smf.studio.render.spec import (FORMATS_FOR_PLANNED_VISUAL, NO_KEY_FORMATS, SpecError, slide_texts,
                                    validate_spec)

__all__ = ["default_size", "NO_KEY_FORMATS", "FORMATS_FOR_PLANNED_VISUAL", "render_post_visuals", "render_with_report", "render_many", "validate_spec",
           "default_out_dir", "renderer_available", "SpecError", "RenderError", "PdfError", "BrandError"]

REPORT_NAME = "render-report.json"


def _as_brand(brand):
    """A Brand, from a Brand or a brand id. Anything else is an error: there is no default."""
    if isinstance(brand, Brand):
        return brand
    if isinstance(brand, str) and brand.strip():
        return brands.load(brand.strip())
    raise BrandError("no brand was named. Say which brand these pictures are for. Brands here: %s"
                     % (", ".join(brands.list_brands()) or "none yet"))


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48] or "post"


def default_out_dir(brand, spec):
    """A new folder under THIS brand's Output/visuals/. Never reuses a folder that exists."""
    stamp = time.strftime("%Y-%m-%d-%H%M%S")
    base = Path(brand.path("Output", "visuals")) / ("%s-%s" % (stamp, _slug(spec.get("name") or spec.get("format"))))
    folder, n = base, 1
    while folder.exists():
        n += 1
        folder = base.with_name("%s-%d" % (base.name, n))
    return folder


# Platforms that show a picture full screen and tall. A brand that posts ONLY to these gets tall
# pictures unless a spec asks for another size.
TALL_ONLY_PLATFORMS = {"tiktok"}


def default_size(brand):
    """The picture size for a spec that does not name one: tall (story, 9:16) for a brand whose
    only platforms show pictures full screen, the 4:5 portrait everywhere else."""
    targets = (brand.data.get("accounts") or {}).get("targets") or []
    platforms = {str(t.get("platform") or "").lower() for t in targets if isinstance(t, dict)} - {""}
    return "story" if platforms and platforms <= TALL_ONLY_PLATFORMS else "portrait"


def _build_slides(brand, kit, spec, size):
    fmt = spec["format"]
    if fmt == free.FORMAT:
        return free.build(kit, brand, spec, size)
    if fmt == "carousel":
        return carousel.build(kit, spec, size)
    if fmt in cards.BUILDERS:
        return cards.build(kit, spec, size)
    if fmt == "notes":
        return raw.build_notes(kit, spec, size)
    if fmt == "post-screenshot":
        return raw.build_post_screenshots(kit, brand, spec, size)
    return text_ad.build(kit, spec, size)


def _write_json_atomic(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(Path(path).parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    replace_patiently(tmp, str(path))


def _shown_sources(brand, spec):
    """A copy of the spec whose every `source` says what a reader should see. A pointer into the
    brand's files ("fact:<id>") is for the check, not for the picture: the picture shows the
    source that fact really has. A pointer that leads nowhere shows nothing at all, rather than
    printing a pointer at a reader."""
    slides = []
    for slide in spec.get("slides") or []:
        if isinstance(slide, dict) and str(slide.get("source") or "").strip():
            found = grounding.resolve_source_pointer(brand, slide["source"])
            slide = dict(slide, source=found["shown"] if found["pointer"] else slide["source"])
            if not slide["source"]:
                slide.pop("source")
        slides.append(slide)
    return dict(spec, slides=slides)


def _claims_on(brand, spec, files, labels, proof_ids=(), drawn=None):
    """What each drawn picture claims, and whether the brand's files confirm it. `drawn` holds
    the words read from each drawn page (a free design); without it they come from the spec."""
    out, warnings = [], []
    corpus = grounding.build_corpus(brand, proof_ids)       # the brand's files are read once for the whole set
    for i, slide in enumerate(spec.get("slides") or []):
        if i >= len(files):
            break
        texts = drawn[i] if drawn is not None else slide_texts(slide) if isinstance(slide, dict) else []
        source = str((slide or {}).get("source") or "") if isinstance(slide, dict) else ""
        checked = grounding.check_drawn_text(brand, texts, source=source, proof_ids=proof_ids, corpus=corpus)
        # The words are kept with the answer so that attaching the picture can ask again, against
        # the brand's files as they stand then: adding the missing fact is enough to clear it.
        out.append({"file": files[i].name, "slide": labels[i], "source": source, "texts": texts,
                    "checked": checked})
        for claim in checked:
            if not claim["confirmed"]:
                warnings.append("%s shows \"%s\", which is not confirmed: %s. Record the fact with its source, "
                                "point the slide's source at it (fact:<id>), or change the slide."
                                % (labels[i], claim["phrase"], claim["why"]))
    return out, warnings


def _brand_rules_on(brand, label, texts):
    """Stop a free design that shows a name this brand never mentions or a word it has banned.
    The words are the ones read from the drawn page."""
    from smf.youtube.titles import brand_findings       # the brand's own rules, for short text
    found, _advice = brand_findings(brand, "\n".join(texts))
    if found:
        raise RenderError("%s breaks one of %s's own rules: %s. Change the words and draw it again."
                          % (label, brand.name, "; ".join(found)))


OVERVIEW_FOLDER = "phone-size"
PHONE_WIDTH = 360            # about how wide a picture is on a phone, in pixels of the picture


def _overview(files, out_dir, name):
    """One sheet with every picture of a set at about phone size, in order, so the whole set can be
    judged at the size people will meet it. Kept in its own folder beside the pictures, so it is
    never mistaken for one of them. None when the imaging library is missing."""
    try:
        from PIL import Image
    except ImportError:
        return None
    tiles = []
    for path in files:
        with Image.open(str(path)) as im:
            tile = im.convert("RGB")
            tiles.append(tile.resize((PHONE_WIDTH, max(1, round(tile.height * PHONE_WIDTH / tile.width))),
                                     Image.LANCZOS))
    if not tiles:
        return None
    gap, columns = 16, min(4, len(tiles))
    rows = (len(tiles) + columns - 1) // columns
    height = max(t.height for t in tiles)
    sheet = Image.new("RGB", (columns * PHONE_WIDTH + (columns + 1) * gap, rows * height + (rows + 1) * gap),
                      (128, 128, 128))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (gap + (i % columns) * (PHONE_WIDTH + gap), gap + (i // columns) * (height + gap)))
    folder = Path(out_dir) / OVERVIEW_FOLDER
    folder.mkdir(exist_ok=True)
    path = folder / (name + "-overview.png")
    sheet.save(str(path))
    return path


class _CouldNotPlace(Exception):
    """A picture could not be put in its folder. `stranded` names the ones whose originals could
    not be put back either, which is the one case where the staging folder must be kept."""

    def __init__(self, stranded):
        self.stranded = list(stranded)
        Exception.__init__(self, "could not place the pictures")


def _move_into_place(staging, out_dir, names):
    """Replace `names` in out_dir with the ones in staging, file by file, or leave every one of
    them exactly as it was. Nothing is deleted: what is there is moved aside first, and moved
    back if any step fails. One file at a time, so no file is renamed over an open one."""
    kept, placed = [], []
    try:
        for name in names:
            target = out_dir / name
            if target.exists():
                os.replace(str(target), str(staging / ("kept-" + name)))
                kept.append(name)
        for name in names:
            os.replace(str(staging / name), str(out_dir / name))
            placed.append(name)
    except OSError:
        stranded = []
        for name in placed:
            try:
                os.replace(str(out_dir / name), str(staging / name))
            except OSError:
                pass
        for name in kept:
            try:
                os.replace(str(staging / ("kept-" + name)), str(out_dir / name))
            except OSError:
                stranded.append(name)
        raise _CouldNotPlace(stranded)


def _render_one(renderer, brand, spec, out_dir, proof_ids=()):
    problems = validate_spec(brand, spec)
    if problems:
        raise SpecError(problems)
    kit = resolve(brand)
    size = size_for(spec.get("size") or default_size(brand))
    size_note = []
    if not spec.get("size") and default_size(brand) == "story":
        size_note = ["Drawn tall (9:16), because %s posts only to TikTok. Ask for portrait or square to change it."
                     % brand.name]
    slides = _build_slides(brand, kit, _shown_sources(brand, spec), size)
    out_dir = Path(out_dir) if out_dir else default_out_dir(brand, spec)
    out_dir = Path(os.path.abspath(str(out_dir)))          # a page's address has to be absolute
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _slug(spec.get("name") or spec["format"])

    # Everything is drawn into a folder of its own, beside where it is going. Pictures already in
    # the destination are untouched until the whole set has been drawn and has passed its layout
    # check, so a set that fails half way cannot take an approved picture with it.
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(out_dir.parent)))
    written, shrunk, warnings, fonts_seen = [], [], [], set()
    refused_before, keep_staging = len(renderer.refused), False
    is_free = spec["format"] == free.FORMAT
    used = free.images_used(brand, spec) if is_free else []
    locked, drawn = (None, None)
    if is_free:
        locked, drawn = free.lock_for(kit, size, [row["file"] for rows in used for row in rows]), []
    try:
        for i, slide in enumerate(slides, 1):
            path = staging / ("%s-%02d-%s.png" % (name, i, slide.name))
            info = (renderer.render(slide.html, path, slide.size, slide.label, locked=locked) if is_free
                    else renderer.render(slide.html, path, slide.size, slide.label))
            if is_free:
                drawn.append(info["texts"])
                _brand_rules_on(brand, slide.label, info["texts"])
            written.append(path)
            fonts_seen.update(info["fonts"])
            shrunk.extend(dict(item, slide=i) for item in info["shrunk"])
            warnings.extend("%s: %s" % (slide.label, w) for w in slide.warnings)
        pdf_path, notes = None, list(kit.notes) + size_note
        if spec.get("pdf"):
            pdf_path, pdf_notes = images_to_pdf(written, staging / (name + ".pdf"))
            notes.extend(pdf_notes)

        claims, claim_warnings = _claims_on(brand, spec, written, [s.label for s in slides], proof_ids, drawn)
        warnings.extend(claim_warnings)
        design_name = None
        if is_free:
            # The design is kept beside its pictures: a later session has no memory of it, and
            # "the same as last time" has to be something that can be read back.
            notes.extend(free.word_notes([s.label for s in slides], drawn))
            notes.extend(free.picture_notes(brand, [s.label for s in slides], used, claims, drawn))
            design_name = name + "-design.json"
            _write_json_atomic(staging / design_name, spec)
        report = {
            "brand": brand.id, "identity": spec["identity"], "format": spec["format"],
            "size": [size[0], size[1]], "folder": str(out_dir),
            "files": [p.name for p in written], "pdf": pdf_path.name if pdf_path else None,
            "fonts": {f.role: "%s (%s)" % (f.path.name, f.origin) for f in kit.faces},
            "fonts_drawn": sorted(fonts_seen),
            "notes": notes, "warnings": warnings, "shrunk_to_fit": shrunk,
            "picture_claims": claims, "design": design_name,
            "images": [{"file": written[i].name, "uses": [{k: row[k] for k in ("image", "source", "shows_person")}
                                                          for row in rows]} for i, rows in enumerate(used)],
            "network_requests": renderer.refused[refused_before:],
            "made_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _write_json_atomic(staging / REPORT_NAME, report)
        _move_into_place(staging, out_dir, [p.name for p in written]
                         + ([pdf_path.name] if pdf_path else []) + ([design_name] if design_name else [])
                         + [REPORT_NAME])
    except _CouldNotPlace as e:
        if e.stranded:
            keep_staging = True
            raise RenderError("These pictures could not be put into their folder, most often because one of them is "
                              "open in another program. Nothing new was saved. Your own copies of %s could not be "
                              "put back either, so they are being kept safe in the folder %s: close whatever is "
                              "using them, then move them back."
                              % (", ".join(e.stranded), staging.name))
        raise RenderError("These pictures could not be put into their folder, most often because one of them is "
                          "open in another program. Nothing was saved, and the pictures that were already in that "
                          "folder were left as they were.")
    except (RenderError, PdfError) as e:
        raise RenderError("%s Nothing was saved, and the pictures that were already in that folder were left as "
                          "they were." % e)
    except OSError:
        raise RenderError("These pictures could not be saved. Nothing was written, and the pictures that were "
                          "already in that folder were left as they were.")
    finally:
        if not keep_staging:
            shutil.rmtree(str(staging), ignore_errors=True)

    written = [out_dir / p.name for p in written]
    try:
        overview = _overview(written, out_dir, name)
    except OSError:
        overview = None
    report["overview"] = str(overview) if overview else None
    if overview:
        try:
            _write_json_atomic(out_dir / REPORT_NAME, report)
        except OSError:
            pass
    return written + ([out_dir / pdf_path.name] if pdf_path else []), report


def render_with_report(brand, spec, out_dir=None, renderer=None, proof_ids=()):
    """Draw one spec. Returns (files, report). `files` is the slide PNGs in order, then the PDF
    when the spec asked for one. Pass an open Renderer to share one browser across calls, and
    `proof_ids` when the post links proof, so a figure drawn from it can be confirmed."""
    brand = _as_brand(brand)
    if renderer is not None:
        return _render_one(renderer, brand, spec, out_dir, proof_ids)
    problems = validate_spec(brand, spec)           # fail before a browser is started
    if problems:
        raise SpecError(problems)
    with Renderer() as r:
        return _render_one(r, brand, spec, out_dir, proof_ids)


def render_post_visuals(brand, spec, out_dir=None, proof_ids=()):
    """THE entry point: draw a post's pictures for one brand. Returns the files, in order.

    Raises BrandError (no such brand or identity), SpecError (the spec is wrong, with every
    problem listed) or RenderError (text that cannot fit, or the renderer is not installed)."""
    files, _report = render_with_report(brand, spec, out_dir, proof_ids=proof_ids)
    return files


def render_many(brand, specs, out_root=None, proof_ids=()):
    """Draw several specs for ONE brand with one browser. Returns [(files, report), ...].
    With `out_root`, each spec gets its own numbered folder inside it."""
    brand = _as_brand(brand)
    specs = list(specs)
    for spec in specs:
        problems = validate_spec(brand, spec)
        if problems:
            raise SpecError(problems)
    results = []
    with Renderer() as r:
        for n, spec in enumerate(specs, 1):
            folder = None
            if out_root:
                folder = Path(out_root) / ("%02d-%s" % (n, _slug(spec.get("name") or spec["format"])))
            results.append(_render_one(r, brand, spec, folder, proof_ids))
    return results
