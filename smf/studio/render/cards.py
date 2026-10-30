"""cards.py - single cards that lead with a strong graphic instead of a paragraph.

People scroll past pictures that look like every other picture. Each of these has ONE focal
point that can be read in a second, and is meant to sit first in a post, with a carousel or a
caption doing the explaining behind it.

    stat       one oversized number, then the sentence that makes it matter
    split      a before/after (or this/that) panel: the contrast is the message
    alert      warning stripes and a blunt sentence: a pattern interrupt
    headline   one large claim or question, a line of support, and nothing else

Every card carries the brand stamp, and may carry a `button` (a short call to action in a
pill) and a small `tag` in the top corner. A `stat` card may name its `source`; whether the
number is backed up is decided by the fact check on the drawn words, not by that line.
"""
from __future__ import annotations

from smf.studio.render import layout as L

DEFAULT_GROUND = {"stat": "main", "split": "main", "alert": "main", "headline": "strong"}


def _default(kit, fmt):
    """A card's background when the spec does not say (see Kit.strong for "strong")."""
    ground = DEFAULT_GROUND[fmt]
    return kit.strong() if ground == "strong" else ground

CSS = """
.statnum{line-height:.86;letter-spacing:-0.065em;}
.support{color:var(--muted);line-height:1.42;max-width:30ch;margin-top:.8em;font-weight:450;text-wrap:pretty;}
/* warning stripes */
.stripe{position:absolute;left:0;right:0;height:30px;z-index:3;
  background:repeating-linear-gradient(45deg,var(--accent) 0 26px,var(--stripe) 26px 52px);}
.stripe.t{top:0;} .stripe.b{bottom:0;}
.badge{flex:0 0 auto;display:flex;align-items:center;justify-content:center;width:94px;height:94px;
  border-radius:50%;background:var(--pill-bg);color:var(--pill-fg);font-family:"smf-display",sans-serif;
  font-size:54px;font-weight:800;margin-bottom:30px;line-height:1;}
/* before / after */
.split{align-self:stretch;flex:0 0 auto;border-radius:24px;overflow:hidden;display:grid;
  grid-template-columns:1fr 1fr;border:1px solid var(--rule);}
.half{min-width:0;padding:60px 46px;display:flex;flex-direction:column;justify-content:center;
  min-height:var(--half-h);overflow:hidden;}
.half.was{background:var(--panel);color:var(--muted);}
.half.now{background:var(--second);color:var(--second-fg);}
.half .htag,.half .hsub{font-family:"smf-mono",monospace;text-transform:uppercase;line-height:1.3;}
.half .htag{letter-spacing:.16em;} .half .hsub{letter-spacing:.1em;}
.half.now .htag,.half.now .hsub{opacity:.78;}
.half .hval{font-family:"smf-display",sans-serif;font-weight:800;letter-spacing:-0.035em;line-height:.98;
  margin:.14em 0 .12em;white-space:nowrap;}
.half.was .hval{color:var(--head);opacity:.62;}
"""


def _stat(kit, s, size, warnings):
    ground = s.get("ground") or _default(kit, "stat")
    pal = kit.palette(ground)
    n = len(str(s["stat"]))
    number = L.fit("number", L.esc(s["stat"]), L.px(330 if n <= 3 else 280 if n <= 4 else 215 if n <= 6 else 160, size),
                   96, "num statnum", lead=1.3)
    head = L.fit("headline", L.rich(s["headline"], s.get("accent"), warnings),
                 L.start_size(s["headline"], 64, size), 32, "h", style="margin-top:.42em;")
    kick = L.fit("supporting line", L.esc(s["kicker"]), L.px(32, size), 21, "support") if s.get("kicker") else ""
    # Whether the number is backed up is decided by the fact check on the whole card (see
    # render/__init__.py), not by whether a source line was typed. This only draws it.
    src = L.fit("source", "Source: " + L.esc(s["source"]), L.px(18, size), 13, "source") if s.get("source") else ""
    inner = (L.top_row(s.get("eyebrow", ""), size, s.get("tag", ""))
             + '<div class="main" data-fitbox="card">%s%s%s%s%s</div>'
             % (number, head, kick, L.pill(s.get("button"), size), src))
    return ground, pal, inner, ""


def _split(kit, s, size, warnings):
    ground = s.get("ground") or _default(kit, "split")
    pal = kit.palette(ground)
    longest = max(len(str(s["before"]["value"])), len(str(s["after"]["value"])))
    value_px = L.px(128 if longest <= 3 else 100 if longest <= 5 else 82 if longest <= 7 else 64, size)

    def half(side, cls):
        tag = L.fit(cls + " label", L.esc(side.get("tag", "")), L.px(21, size), 13, "htag", group="split-label")
        sub = (L.fit(cls + " note", L.esc(side["sub"]), L.px(20, size), 13, "hsub", group="split-note")
               if side.get("sub") else "")
        return ('<div class="half %s" data-fitbox="%s panel">%s%s%s</div>'
                % (cls, cls, tag, L.fit(cls + " value", L.esc(side["value"]), value_px, 34, "hval",
                                       group="split-value"), sub))

    head = L.fit("headline", L.rich(s["headline"], s.get("accent"), warnings),
                 L.start_size(s["headline"], 64, size), 32, "h", style="margin-top:.8em;")
    inner = (L.top_row(s.get("eyebrow", ""), size, s.get("tag", ""))
             + '<div class="main" data-fitbox="card"><div class="split" style="--half-h:%dpx">%s%s</div>%s%s</div>'
             % (L.px(400, size), half(s["before"], "was"), half(s["after"], "now"), head,
                L.pill(s.get("button"), size)))
    return ground, pal, inner, ""


def _alert(kit, s, size, warnings):
    ground = s.get("ground") or _default(kit, "alert")
    pal = kit.palette(ground)
    badge = str(s.get("badge", "!"))[:2]
    inner = ('<div class="stripe t"></div><div class="stripe b"></div>'
             + L.top_row(s.get("eyebrow", ""), size, s.get("tag", ""))
             + '<div class="main" data-fitbox="card">%s%s%s%s</div>'
             % ('<div class="badge">%s</div>' % L.esc(badge) if badge else "",
                L.fit("headline", L.rich(s["headline"], s.get("accent"), warnings),
                      L.start_size(s["headline"], 86, size), 38, "h"),
                L.fit("supporting line", L.esc(s["support"]), L.px(33, size), 21, "support") if s.get("support") else "",
                L.pill(s.get("button"), size)))
    return ground, pal, inner, "--stripe:%s;" % pal["head"]


def _headline(kit, s, size, warnings):
    ground = s.get("ground") or _default(kit, "headline")
    pal = kit.palette(ground)
    inner = (L.top_row(s.get("eyebrow", ""), size, s.get("tag", ""))
             + '<div class="main" data-fitbox="card">%s%s%s</div>'
             % (L.fit("headline", L.rich(s["headline"], s.get("accent"), warnings),
                      L.start_size(s["headline"], 104, size), 42, "h"),
                L.fit("supporting line", L.esc(s["support"]), L.px(34, size), 21, "support") if s.get("support") else "",
                L.pill(s.get("button"), size)))
    return ground, pal, inner, ""


BUILDERS = {"stat": _stat, "split": _split, "alert": _alert, "headline": _headline}


def build(kit, spec, size):
    """Cards for a spec that has already passed validate_spec. One card per entry in `slides`."""
    fmt, slides = spec["format"], spec["slides"]
    out = []
    for i, s in enumerate(slides):
        warnings = []
        ground, pal, inner, extra_vars = BUILDERS[fmt](kit, s, size, warnings)
        css = CSS + (":root{%s}" % extra_vars if extra_vars else "")
        html = L.page(kit, pal, size, inner + L.footer(kit, ground, size, spec.get("footer_line")), css)
        label = "The %s card" % fmt if len(slides) == 1 else "Card %d of %d" % (i + 1, len(slides))
        out.append(L.Slide(name=fmt, html=html, size=size, label=label, warnings=warnings))
    return out
