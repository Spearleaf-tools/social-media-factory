"""free.py - a picture designed from scratch for one brand and one post: no template.

The fixed formats draw the same layouts for every brand. A free design is a page written for
this picture, drawn by the same engine, and held to checks instead of to a template.

THE FREE PAGE CONTRACT (what the designer hands over)

    {
      "format":   "free",
      "identity": "person",
      "size":     "portrait",            optional, as for every format
      "name":     "sourdough-poster",    optional
      "pdf":      false,                 optional
      "slides": [
        {"name": "cover",                optional: goes into the file name
         "html": "<div class='big'>Your dough is not late.</div><p>It is cold.</p>",
         "css":  ".big{font:800 120px/1 'smf-display';color:var(--accent)}",
         "source": "fact:ferment-18h"}   optional: where a number on this picture comes from
      ]
    }

`html` is what goes INSIDE the picture; the Factory supplies the page around it. It sits in a
box the exact size of the picture (class `canvas`: positioned, the brand's background, the
brand's headline colour, overflow hidden). `css` styles it.

WHAT THE PAGE IS GIVEN
    fonts     smf-display, smf-body, smf-mono, smf-poster: the brand's own files where it
              supplied them, the bundled ones otherwise. No other font can load.
    colours   var(--ground) var(--surface) var(--ink) var(--text) var(--muted) var(--rule)
              var(--accent) var(--accent2): the brand's own. They are a starting point: any
              other colour may be written out when the person asks for it.
    size      var(--w) and var(--h), in pixels.
    pictures  an image from the brand's own photos folder, named from the brand's folder with
              "brand:" in front:   <img src="brand:Brand/brand-kit/photos/loaf.jpg">
              or in the styling:   background-image:url(brand:Brand/brand-kit/photos/loaf.jpg)
              The brand's own photos, stock photos filed there and generated images all work
              (see library.py). The report lists which pictures each drawing used.
    fitting   optional. Text marked data-fit="name" inside a box marked data-fitbox="name" is
              shrunk until it fits, down to data-min="px", exactly as in the fixed formats.

WHAT A PAGE MAY NOT HOLD (refused before a browser starts, each with the reason)
    scripts, event handlers, embedded pages, forms, canvases, anything that loads a file other
    than a brand: picture (href, a web address, @import, @font-face) and words written in the
    styling (content: "...").

WHAT IS CHECKED ON THE DRAWN PAGE (see checks.py; a failure saves nothing)
    every word is on the picture and not cut off, is at least 24 pixels on a 1080-wide picture,
    is in one of the four fonts above, and stands out from what is really behind it, photo
    included. The words read from the drawn page are the ones checked against the brand's facts
    and its own rules. Words that are part of a photo or a generated image cannot be read, so
    look at the picture: lettering inside an image is not checked.

While it is drawn, a free page can load its own file, the font files and the brand: pictures it
named, and NOTHING else on this computer, and scripts in the page do not run.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from pathlib import Path

from smf.brands import BrandError
from smf.studio.render import layout as L
from smf.studio.render import library
from smf.studio.render.checks import min_text_px

FORMAT = "free"
MAX_HTML = 20000
MAX_CSS = 20000
MANY_WORDS = 60                         # more words than this on one picture earns a note
SLIDE_KEYS = {"name", "html", "css", "source"}

TEXT_TAGS = {"div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "ul", "ol", "li", "strong", "b",
             "em", "i", "u", "s", "small", "sup", "sub", "blockquote", "q", "cite", "figure", "figcaption",
             "section", "header", "footer", "main", "article", "aside", "mark", "wbr"}
SHAPE_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "defs",
              "lineargradient", "radialgradient", "stop", "clippath", "mask"}
ALLOWED_TAGS = TEXT_TAGS | SHAPE_TAGS | {"img"}
LOADING_ATTRS = {"src", "srcset", "href", "xlink:href", "action", "formaction", "background", "poster", "data"}
BRAND_REF = re.compile(r"brand:([^'\")\s>]+)")
_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.S)
CSS_REFUSED = (("@import", "loads a file (@import)"),
               ("@font-face", "loads a font; only the brand's four fonts can be used"),
               ("image-set(", "loads a file (image-set)"), ("expression(", "runs code (expression)"),
               ("element(", "draws another part of the page (element)"))
_CONTENT = re.compile(r"(?<![\w-])content\s*:\s*([^;}]*)")     # not justify-content, align-content
_EMPTY_CONTENT = {"", "none", "normal", '""', "''"}

SHELL_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:var(--w);height:var(--h);overflow:hidden;background:var(--ground);}
body{-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision;font-optical-sizing:auto;
  font-synthesis:none;}
.canvas{position:relative;width:var(--w);height:var(--h);overflow:hidden;background:var(--ground);
  color:var(--ink);font-family:"smf-body",sans-serif;font-size:40px;line-height:1.3;}
"""


def css_problems(css, where):
    """Why a piece of styling cannot be used, as plain sentences. Empty = fine."""
    text = re.sub(r"/\*.*?\*/", " ", str(css or ""), flags=re.S).lower()
    out = []
    if "\\" in text:
        out.append("%s: the styling uses a backslash escape, which can hide what it does. Write it plainly." % where)
    if "<" in text:
        out.append("%s: the styling holds page markup ('<'). Styling goes in 'css', the picture in 'html'." % where)
    squeezed = re.sub(r"\s+", "", text)
    if any(not target.strip().startswith("brand:") for _q, target in _URL.findall(text)) \
            or squeezed.count("url(") != len(_URL.findall(text)):
        out.append("%s: the styling loads a file (url). Only this brand's own pictures can be used, written as "
                   "url(brand:Brand/brand-kit/photos/<file>)." % where)
    for needle, why in CSS_REFUSED:
        if needle in squeezed:
            out.append("%s: the styling %s. A free design uses only this brand's fonts and colours for now." % (where, why))
    for value in _CONTENT.findall(text):
        if value.replace("!important", "").strip() not in _EMPTY_CONTENT:
            out.append("%s: the styling writes words onto the picture (content: ...). Words drawn that way cannot "
                       "be checked, so put them in the page itself." % where)
            break
    return out


class _Reader(HTMLParser):
    def __init__(self, where):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.where, self.problems, self.said = where, [], set()

    def _add(self, key, text):
        if key not in self.said:
            self.said.add(key)
            self.problems.append("%s: %s" % (self.where, text))

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in ALLOWED_TAGS:
            self._add(("tag", tag), "<%s> cannot be used in a free design. It is built from text, boxes and "
                                    "simple shapes: scripts, embedded pages, forms and files are not drawn." % tag)
        for name, value in attrs:
            name = (name or "").lower()
            if name.startswith("on"):
                self._add(("on", name), "'%s' runs code when something happens. A picture has nothing to run." % name)
            elif name == "src" and tag == "img" and str(value or "").strip().lower().startswith("brand:"):
                continue
            elif name in LOADING_ATTRS:
                self._add(("load", name), "'%s' loads a file. Only this brand's own pictures can be used, written "
                                          "as <img src=\"brand:Brand/brand-kit/photos/<file>\">." % name)
            elif name == "style":
                for p in css_problems(value, self.where):
                    self._add(("css", p), p.split(": ", 1)[1])

    handle_startendtag = handle_starttag

    def handle_pi(self, data):
        self._add(("pi", ""), "it holds a processing instruction ('<?'), which a picture does not need.")


def pictures_named(slide):
    """The brand: pictures one slide names, as written, in order and once each."""
    seen = []
    for rel in BRAND_REF.findall(str(slide.get("html") or "") + "\n" + str(slide.get("css") or "")):
        if rel not in seen:
            seen.append(rel)
    return seen


def check_slides(c, slides, brand):
    """Add every problem with a free design's slides to the checker `c` (see spec.py)."""
    total = len(slides)
    for i, s in enumerate(slides):
        where = "Picture %d" % (i + 1) if total > 1 else "The picture"
        c.unknown(s, where, SLIDE_KEYS)
        html, css = s.get("html"), s.get("css", "")
        if not isinstance(html, str) or not html.strip():
            c.add("%s needs 'html': what goes inside the picture." % where)
            continue
        if not isinstance(css, str):
            c.add("%s: 'css' is the styling, as text." % where)
            continue
        if len(html) > MAX_HTML or len(css) > MAX_CSS:
            c.add("%s is very long for one picture (over %d characters). Split it, or simplify it." % (where, MAX_HTML))
            continue
        name = s.get("name")
        if name is not None and not (isinstance(name, str) and re.match(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,29}$", name)):
            c.add("%s: 'name' becomes part of the file name, so it is short and simple: letters, numbers, spaces "
                  "and dashes." % where)
        if s.get("source") is not None and not isinstance(s.get("source"), str):
            c.add("%s: 'source' says where a number on the picture comes from, as text (for example fact:<id>)." % where)
        reader = _Reader(where)
        try:
            reader.feed(html)
            reader.close()
        except Exception:
            c.add("%s: the 'html' could not be read. Check that every tag is closed." % where)
            continue
        for p in reader.problems + css_problems(css, where):
            c.add(p)
        for rel in pictures_named(s):
            try:
                library.brand_image(brand, rel)
            except BrandError as e:
                c.add("%s: %s." % (where, str(e)[0].upper() + str(e)[1:]))


def lock_for(kit, size, pictures=()):
    """What the engine needs to draw a free page safely: the only files it may open besides the
    page itself (the fonts, and the brand's pictures this design named), and the smallest text
    allowed at this size."""
    return {"allow": [str(p) for p in kit.font_files()] + [str(p) for p in pictures], "min_px": min_text_px(size)}


def images_used(brand, spec):
    """For each slide, the brand's pictures it uses and where each came from:
    [[{image, source, shows_person, file}], ...]."""
    out = []
    for s in spec["slides"]:
        rows = []
        for rel in pictures_named(s):
            path = library.brand_image(brand, rel)
            record = library.read_record(path)
            rows.append({"image": rel, "source": record["source"], "shows_person": record.get("shows_person"),
                         "file": str(path)})
        out.append(rows)
    return out


def page(kit, size, inner, css=""):
    """The complete page around one free design."""
    c = kit.colours
    root = "--w:%dpx;--h:%dpx;" % (size[0], size[1])
    root += "".join("--%s:%s;" % (name, c[name]) for name in
                    ("ground", "surface", "ink", "text", "muted", "rule", "accent", "accent2") if c.get(name))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>picture</title>'
            '<style>%s\n:root{%s}\n%s\n%s</style></head><body><div class="canvas">%s</div></body></html>'
            % (kit.font_face_css(), root, SHELL_CSS, css, inner))


def build(kit, brand, spec, size):
    """One Slide per picture. The spec has already passed validate_spec, so every brand:
    picture exists and is inside the brand's own photos folder."""
    slides, total = spec["slides"], len(spec["slides"])

    def address(match):
        return Path(library.brand_image(brand, match.group(1))).resolve().as_uri()

    out = []
    for i, s in enumerate(slides):
        label = "Picture %d of %d" % (i + 1, total) if total > 1 else "The picture"
        name = re.sub(r"[^a-z0-9]+", "-", str(s.get("name") or "picture").lower()).strip("-") or "picture"
        html, css = BRAND_REF.sub(address, s["html"]), BRAND_REF.sub(address, s.get("css", ""))
        out.append(L.Slide(name, page(kit, size, html, css), size, label))
    return out


def picture_notes(brand, labels, used, claims, drawn):
    """What the person should be told about the pictures inside these pictures: which are stock
    or generated, and when one that shows a person sits beside a claim or a quotation."""
    notes = []
    for i, rows in enumerate(used):
        for row in rows:
            if row["source"] == "own":
                continue
            what = library.SPOKEN[row["source"]]
            notes.append("%s uses %s (%s), not one of %s's own photos."
                         % (labels[i], what, Path(row["image"]).name, brand.name))
            words = " ".join(drawn[i]) if i < len(drawn) else ""
            says = bool(claims[i]["checked"]) if i < len(claims) else False
            quotes = any(mark in words for mark in ('"', "\u201c", "\u201d"))
            if row["shows_person"] is not False and (says or quotes):
                notes.append("%s puts %s that may show a person beside a claim or a quotation. A reader could take "
                             "that person for a real customer. Say so to the person and ask before using it."
                             % (labels[i], what))
    return notes


def word_notes(labels, drawn):
    """A plain note for each picture that carries a lot of words. Advice, never a refusal."""
    notes = []
    for label, texts in zip(labels, drawn):
        words = sum(len(str(t).split()) for t in texts)
        if words > MANY_WORDS:
            notes.append("%s has %d words on it. That is a lot for one picture; consider moving some to the caption."
                         % (label, words))
    return notes
