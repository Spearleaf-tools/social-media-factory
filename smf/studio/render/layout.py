"""layout.py - the page shell and the small parts every format shares.

A slide is one self-contained HTML page: the brand's fonts as @font-face rules that point at
local files, the brand's colours as CSS variables, and markup built from escaped text. Nothing
in a page refers to the internet, and no text reaches the page without going through esc().

THE FITTING CONTRACT (see engine.py for the measuring side)
  data-fitbox="name"   a box with a fixed size that text must stay inside
  data-fit="field"     a piece of text inside it that may be scaled down to fit
  data-min="px"        the smallest size that text may reach
  data-soft="px"       for a "lead" text that starts oversized on purpose: it comes down alone to
                       this designed size before anything else in the box is touched
  data-fitgroup="x"    texts that must end up the same size as each other (two halves of a split)
Builders choose a generous starting size from the length of the text; the engine does the rest.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field

# How much room each picture size leaves. A tall (story) picture is seen full screen on TikTok,
# Reels and Shorts, where the app draws over it: its own bar at the top, the caption and music
# line along the bottom, and a column of buttons down the right. So a tall picture keeps its
# words out of all three, and its text is drawn larger, because it fills the whole phone.
# (Margins from the safe-zone guides for organic posts, checked October 2026; TikTok publishes
# none for ordinary posts, so these are on the generous side.)
GEOMETRY = {
    (1080, 1350): {"pad_top": 96, "pad_x": 96, "pad_right": 96, "foot": 132, "pad_bottom": 40, "scale": 1.0},
    (1080, 1080): {"pad_top": 80, "pad_x": 88, "pad_right": 88, "foot": 120, "pad_bottom": 34, "scale": 0.86},
    (1080, 1920): {"pad_top": 240, "pad_x": 96, "pad_right": 168, "foot": 132, "pad_bottom": 470, "scale": 1.15},
}

# The smallest any text on a picture may be, in pixels, on a 1080-wide picture: about 9 points
# on a phone held at arm's length. A floor written lower anywhere below is raised to this.
MIN_TEXT_PX = 24

ICONS = {
    "arrow": '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h16M13 5l7 7-7 7"/></svg>',
    "check": '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.6 4.6L19 7.5"/></svg>',
    "cross": '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" '
             'stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    "reply": '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H10l-5 4v-4H4z"/></svg>',
    "repeat": '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
              'stroke-linecap="round" stroke-linejoin="round"><path d="M7 7h10v6M17 17H7v-6"/>'
              '<path d="M14 4l3 3-3 3M10 20l-3-3 3-3"/></svg>',
    "heart": '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 '
             '5.6-7 10-7 10z"/></svg>',
    "send": '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4M8 8l4-4 4 4M5 13v6h14v-6"/></svg>',
}

BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:var(--w);height:var(--h);overflow:hidden;background:var(--bg);}
body{-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision;font-optical-sizing:auto;
  font-synthesis:none;}
.ico{width:1em;height:1em;display:block;flex:0 0 auto;}
.canvas{position:relative;width:var(--w);height:var(--h);overflow:hidden;background:var(--bg);
  color:var(--body);padding:var(--pad-top) var(--pad-right) var(--pad-bottom) var(--pad-x);display:flex;
  flex-direction:column;font-family:"smf-body",sans-serif;font-size:30px;line-height:1.4;}
.top{flex:0 0 auto;display:flex;justify-content:space-between;align-items:baseline;gap:32px;
  min-height:34px;position:relative;z-index:2;overflow:hidden;}
.eyebrow{font-family:"smf-mono",monospace;font-weight:500;letter-spacing:.2em;
  text-transform:uppercase;color:var(--accent-small);white-space:nowrap;}
.tag{font-family:"smf-mono",monospace;letter-spacing:.14em;text-transform:lowercase;
  color:var(--muted);white-space:nowrap;}
.main{flex:1 1 0;min-height:0;display:flex;flex-direction:column;justify-content:center;
  align-items:flex-start;overflow:hidden;position:relative;z-index:2;padding:26px 0;}
.main.from-top{justify-content:flex-start;padding-top:40px;}
.main > *{max-width:100%;}
.h{font-family:"smf-display",sans-serif;font-weight:800;letter-spacing:-0.035em;line-height:1.04;
  color:var(--head);text-wrap:balance;}
.num{font-family:"smf-display",sans-serif;font-weight:800;font-variant-numeric:tabular-nums;
  letter-spacing:-0.055em;color:var(--number);white-space:nowrap;}
.mark{color:var(--accent);}
.kick{color:var(--muted);line-height:1.42;max-width:30ch;margin-top:.95em;font-weight:450;text-wrap:pretty;}
.source{font-family:"smf-mono",monospace;color:var(--muted);letter-spacing:.04em;margin-top:1.6em;
  line-height:1.4;max-width:46ch;}
.mono{font-family:"smf-mono",monospace;}
.rule{align-self:stretch;height:1px;background:var(--rule);border:0;margin:34px 0;flex:0 0 auto;}
.pill{display:inline-flex;align-items:center;gap:.42em;background:var(--pill-bg);color:var(--pill-fg);
  font-family:"smf-display",sans-serif;font-weight:700;letter-spacing:-0.01em;padding:.74em 1.45em;
  border-radius:9999px;white-space:nowrap;margin-top:1.7em;line-height:1.1;}
/* the brand stamp along the bottom */
.foot{flex:0 0 var(--foot);height:var(--foot);display:flex;justify-content:space-between;
  align-items:center;gap:40px;position:relative;z-index:2;overflow:hidden;}
.wm{display:inline-flex;align-items:center;gap:.42em;font-family:"smf-display",sans-serif;font-weight:650;
  letter-spacing:-0.02em;color:var(--head);white-space:nowrap;}
.wm .chip{width:.42em;height:.42em;border-radius:.1em;background:var(--accent);display:block;flex:0 0 auto;}
.logo{height:46px;max-width:340px;object-fit:contain;object-position:left center;display:block;}
.handle{font-family:"smf-mono",monospace;letter-spacing:.04em;color:var(--muted);white-space:nowrap;}
/* the dots that say "there is more, swipe" */
.pager{position:absolute;left:0;right:0;bottom:var(--pager-bottom);height:26px;display:flex;
  justify-content:center;align-items:center;gap:11px;z-index:5;color:var(--accent);font-size:26px;}
.pager i{width:12px;height:12px;border-radius:50%;background:var(--dot-off);display:block;}
.pager i.on{width:30px;border-radius:999px;background:var(--accent);}
.pager .ico{margin-left:10px;}
"""


@dataclass
class Slide:
    name: str                       # goes into the file name: cover, point, stat, ...
    html: str
    size: tuple
    label: str = ""                 # "Slide 2 of 6", used in messages
    warnings: list = field(default_factory=list)


def esc(text):
    return _html.escape(str(text), quote=True)


def geometry(size):
    return GEOMETRY.get((int(size[0]), int(size[1])), GEOMETRY[(1080, 1350)])


def px(base, size, floor=0):
    """A starting size in pixels, scaled for the picture size."""
    return max(int(floor), int(round(base * geometry(size)["scale"])))


def start_size(text, base, size):
    """A generous first guess from the length of the text: short lines start huge, long ones
    start smaller. The engine shrinks from here only if it has to."""
    n = len(" ".join(str(text).split()))
    factor = 1.0 if n <= 38 else 0.87 if n <= 68 else 0.75 if n <= 105 else 0.64
    return px(base * factor, size)


def rich(text, accent=None, warnings=None, where="the headline"):
    """Escaped text with line breaks kept and each accent phrase coloured once.
    An accent phrase that is not in the text is reported rather than ignored silently."""
    out = esc(text)
    phrases = [accent] if isinstance(accent, str) else list(accent or [])
    for phrase in phrases:
        if not str(phrase).strip():
            continue
        pattern = re.compile("(%s)" % re.escape(esc(phrase)), re.IGNORECASE)
        out, count = pattern.subn(r'<span class="mark">\1</span>', out, count=1)
        if not count and warnings is not None:
            warnings.append("The words to highlight, '%s', are not in %s, so nothing was coloured." % (phrase, where))
    return out.replace("\n", "<br>")


def emph(text):
    """Escaped text where *starred words* take the accent colour."""
    return re.sub(r"\*(.+?)\*", r'<span class="mark">\1</span>', esc(text)).replace("\n", "<br>")


def fit(field_name, inner_html, size_px, floor_px, cls="", tag="div", group="", style="", lead=0.0):
    """One piece of fitted text. `lead` above 1 makes it a lead text: it starts at size_px x lead
    and is brought down to size_px on its own before the rest of its box gives way."""
    floor_px = max(int(floor_px), MIN_TEXT_PX)
    size_px = max(int(size_px), floor_px)
    attrs = 'data-fit="%s" data-min="%d"' % (esc(field_name), int(floor_px))
    if group:
        attrs += ' data-fitgroup="%s"' % esc(group)
    if lead and lead > 1:
        attrs += ' data-soft="%d"' % int(size_px)
        size_px = int(size_px * lead)
    return ('<%s class="%s" %s style="font-size:%dpx;%s">%s</%s>'
            % (tag, cls, attrs, int(size_px), style, inner_html, tag))


def palette_style(palette):
    names = {"bg": "--bg", "head": "--head", "body": "--body", "muted": "--muted", "rule": "--rule",
             "panel": "--panel", "accent": "--accent", "accent_small": "--accent-small", "number": "--number",
             "pill_bg": "--pill-bg", "pill_fg": "--pill-fg", "faint": "--faint", "dot_off": "--dot-off",
             "second": "--second", "second_fg": "--second-fg"}
    return "".join("%s:%s;" % (names[k], v) for k, v in palette.items() if k in names)


def top_row(eyebrow, size, tag=""):
    parts = ""
    if eyebrow:
        parts += fit("eyebrow", esc(eyebrow), px(21, size), 14, "eyebrow", "span")
    if tag:
        parts += fit("tag", esc(tag), px(19, size), 13, "tag", "span")
    return '<div class="top" data-fitbox="top">%s</div>' % parts


def pill(text, size, base=31):
    if not text:
        return ""
    return fit("button", esc(text) + ICONS["arrow"], px(base, size), 20, "pill", "div")


def footer(kit, ground, size, line=None):
    """The brand stamp: its logo on its own background, its name as text everywhere else."""
    handle = kit.handle if line is None else line
    if kit.logo is not None and ground in ("main", "soft"):
        mark = '<img class="logo" src="%s" alt="">' % esc(kit.logo.as_uri())
    else:
        mark = fit("wordmark", '<i class="chip"></i>' + esc(kit.wordmark), px(34, size), 16, "wm", "span")
    right = fit("footer line", esc(handle), px(20, size), 13, "handle", "span") if handle else ""
    return '<div class="foot" data-fitbox="footer">%s%s</div>' % (mark, right)


def pager(index, total):
    if total < 2:
        return ""
    dots = "".join('<i class="on"></i>' if i == index else "<i></i>" for i in range(total))
    more = ICONS["arrow"] if index < total - 1 else ""
    return '<div class="pager">%s%s</div>' % (dots, more)


def page(kit, palette, size, inner, css="", canvas_class=""):
    """The complete page for one slide."""
    g = geometry(size)
    root = ("--w:%dpx;--h:%dpx;--pad-top:%dpx;--pad-x:%dpx;--pad-right:%dpx;--pad-bottom:%dpx;--foot:%dpx;"
            "--pager-bottom:%dpx;"
            % (size[0], size[1], g["pad_top"], g["pad_x"], g["pad_right"], g["pad_bottom"], g["foot"],
               max(28, g["pad_bottom"] - 8)))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>slide</title>'
            '<style>%s\n:root{%s%s}\n%s\n%s</style></head><body><div class="canvas %s">%s</div></body></html>'
            % (kit.font_face_css(), root, palette_style(palette), BASE_CSS, css, canvas_class, inner))
