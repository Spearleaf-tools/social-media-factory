"""carousel.py - the polished, swipeable carousel in the brand's own colours.

The order is enforced because the order is what makes a carousel work:

    cover        the hook, in the largest type on any slide, with a "swipe" cue
    2 to 8 middle slides, one idea each, any mix of:
        point      a statement with a supporting line
        steps      a numbered method (2 to 5 steps)
        checklist  a list worth saving (2 to 7 rows)
        compare    two columns: the old way against the new way, row against row
        stat       one big number with the sentence that explains it
    cta          the closing slide: what to do next

Every slide carries the brand stamp along the bottom and a row of dots that shows where the
reader is; every slide but the last also shows an arrow.

A `stat` slide may carry a `source` line (where the number comes from). Whether the number is
true is not a question a drawing can answer: every claim a slide makes is traced to the brand's
own files afterwards, and the render report says which ones were confirmed.
"""
from __future__ import annotations

from smf.studio.render import layout as L

MIN_MIDDLE, MAX_MIDDLE = 2, 8
MIDDLE_KINDS = ("point", "steps", "checklist", "compare", "stat")
DEFAULT_GROUND = {"cover": "strong", "point": "main", "steps": "strong", "checklist": "soft",
                  "compare": "main", "stat": "main", "cta": "strong"}


def _default(kit, kind):
    """A slide's background when the spec does not say. "strong" is the brand's own standout
    background, which is never white for a dark brand (see Kit.strong)."""
    ground = DEFAULT_GROUND[kind]
    return kit.strong() if ground == "strong" else ground

CSS = """
.index{position:absolute;top:calc(var(--pad-top) - 40px);right:var(--pad-right);font-family:"smf-display",sans-serif;
  font-weight:800;line-height:.8;letter-spacing:-0.06em;color:var(--faint);z-index:1;
  font-variant-numeric:tabular-nums;}
.swipe{display:inline-flex;align-items:center;gap:.5em;font-family:"smf-mono",monospace;font-weight:500;
  letter-spacing:.2em;text-transform:uppercase;color:var(--accent);margin-top:2em;}
.bignum{line-height:.9;}
/* steps: the rail takes all the room there is, so a short method still fills the slide */
/* (the rail and its steps may grow but never shrink below their text: a rail that gave way
   would let the last step slide under the result line without anything measuring as too tall) */
.rail{align-self:stretch;flex:1 0 auto;display:flex;flex-direction:column;margin-top:36px;}
.step{position:relative;display:flex;gap:30px;flex:1 0 auto;padding-bottom:20px;}
.step:last-child{flex:0 0 auto;padding-bottom:0;}
.step:not(:last-child)::before{content:"";position:absolute;left:37px;top:84px;bottom:8px;width:2px;
  background:repeating-linear-gradient(180deg,var(--muted) 0 7px,transparent 7px 15px);opacity:.55;}
.node{flex:0 0 76px;width:76px;height:76px;border-radius:50%;background:var(--accent);color:var(--bg);
  display:flex;align-items:center;justify-content:center;font-family:"smf-mono",monospace;font-weight:500;
  font-size:28px;}
.sbody{flex:1 1 0;min-width:0;padding-top:2px;}
.sk{font-family:"smf-mono",monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);}
.sh{font-family:"smf-display",sans-serif;font-weight:700;letter-spacing:-0.02em;color:var(--head);
  line-height:1.12;margin:4px 0 8px;}
.sd{color:var(--body);line-height:1.34;max-width:44ch;text-wrap:pretty;}
.result{align-self:stretch;flex:0 0 auto;margin-top:36px;padding-top:30px;border-top:1px solid var(--rule);
  font-family:"smf-display",sans-serif;font-weight:800;letter-spacing:-0.025em;line-height:1.12;
  color:var(--head);text-wrap:balance;}
/* checklist */
.rows{align-self:stretch;display:flex;flex-direction:column;gap:.78em;}
.row{display:flex;gap:.62em;align-items:flex-start;align-self:stretch;}
.tick{flex:0 0 auto;width:1.36em;height:1.36em;border-radius:50%;background:var(--accent);color:var(--bg);
  display:flex;align-items:center;justify-content:center;margin-top:-.06em;}
.tick .ico{width:.74em;height:.74em;}
.rowtext{flex:1 1 0;min-width:0;font-family:"smf-display",sans-serif;font-weight:700;letter-spacing:-0.02em;
  line-height:1.2;color:var(--head);}
/* compare: one grid, so row 1 on the left lines up with row 1 on the right */
.canvas.cmp{padding:0;}
.cmpbg{position:absolute;top:0;bottom:0;width:50%;background:var(--bg);}
.cmpbg.l{left:0;} .cmpbg.r{right:0;}
.cgrid{position:absolute;left:0;right:0;top:var(--pad-top);bottom:calc(var(--foot) + var(--pad-bottom) + 70px);
  display:grid;grid-template-columns:1fr 1fr;align-content:center;overflow:hidden;z-index:2;}
.cell{min-width:0;overflow:hidden;color:var(--body);}
.cell.l{padding:0 64px 0 76px;} .cell.r{padding:0 calc(var(--pad-right) - 20px) 0 64px;}
.cell.headc{padding-bottom:30px;}
.ctag{font-family:"smf-mono",monospace;letter-spacing:.2em;text-transform:uppercase;color:var(--accent-small);}
.cell.l .ctag{color:var(--muted);}
.chead{font-family:"smf-display",sans-serif;font-weight:800;letter-spacing:-0.03em;line-height:1.05;
  color:var(--head);margin:.3em 0 .22em;text-wrap:balance;}
.cnote{font-family:"smf-mono",monospace;letter-spacing:.05em;color:var(--muted);}
.item{display:flex;gap:.6em;align-items:flex-start;padding:.85em 0;border-top:1px solid var(--rule);height:100%;}
.mk{flex:0 0 auto;width:1.34em;height:1.34em;border-radius:50%;display:flex;align-items:center;
  justify-content:center;margin-top:-.02em;}
.mk .ico{width:.7em;height:.7em;}
.cell.l .mk{border:1.5px solid var(--muted);color:var(--muted);}
.cell.r .mk{background:var(--accent);color:var(--bg);}
.it{flex:1 1 0;min-width:0;line-height:1.3;}
.cell.r .it{color:var(--head);font-weight:550;}
.vs{position:absolute;left:50%;top:var(--vs-top);transform:translate(-50%,-50%);z-index:6;width:100px;height:100px;
  border-radius:50%;background:var(--pill-bg);color:var(--pill-fg);display:flex;align-items:center;
  justify-content:center;font-family:"smf-mono",monospace;font-weight:500;font-size:30px;
  box-shadow:0 18px 30px -12px rgba(0,0,0,.45);}
.footbar{position:absolute;left:50%;bottom:calc(var(--pad-bottom) + 38px);transform:translateX(-50%);z-index:7;
  display:flex;align-items:center;gap:16px;background:var(--bar-bg);border:1px solid var(--bar-line);
  padding:17px 34px;border-radius:9999px;box-shadow:0 18px 34px -14px rgba(0,0,0,.45);white-space:nowrap;
  max-width:calc(var(--w) - 120px);overflow:hidden;}
.footbar .wm{color:var(--bar-fg);} .footbar .handle{color:var(--bar-muted);}
.footbar .sep{width:1px;height:24px;background:var(--bar-muted);opacity:.5;flex:0 0 auto;}
"""


def _statement(kit, s, size, warnings, kind, base, floor):
    ground = s.get("ground") or _default(kit, kind)
    pal = kit.palette(ground)
    head = L.fit("headline", L.rich(s["headline"], s.get("accent"), warnings),
                 L.start_size(s["headline"], base, size), floor, "h")
    support = s.get("kicker") or s.get("body") or ""
    kick = L.fit("supporting line", L.esc(support).replace("\n", "<br>"), L.px(34, size), 22, "kick") if support else ""
    extra, deco = "", ""
    if kind == "cover":
        deco = '<div class="index" style="font-size:%dpx">01</div>' % L.px(300, size)
        if s.get("swipe", True):
            extra = '<div class="swipe" style="font-size:%dpx">Swipe%s</div>' % (L.px(24, size, L.MIN_TEXT_PX), L.ICONS["arrow"])
    if kind == "cta" and s.get("button"):
        extra = L.pill(s["button"], size)
    inner = (deco + L.top_row(s.get("eyebrow", ""), size)
             + '<div class="main" data-fitbox="%s">%s%s%s</div>' % (kind, head, kick, extra))
    return ground, pal, inner


def _steps(kit, s, size, warnings):
    ground = s.get("ground") or _default(kit, "steps")
    pal = kit.palette(ground)
    count = len(s["steps"])
    head_px, body_px = {2: (50, 30), 3: (46, 28), 4: (41, 25)}.get(count, (37, 23))
    rows = []
    for i, st in enumerate(s["steps"], 1):
        label = L.fit("step %d label" % i, L.esc(st["label"]), L.px(17, size), 12, "sk") if st.get("label") else ""
        body = L.fit("step %d text" % i, L.esc(st["body"]), L.px(body_px, size), 17, "sd") if st.get("body") else ""
        rows.append('<div class="step"><div class="node">%02d</div><div class="sbody">%s%s%s</div></div>'
                    % (i, label, L.fit("step %d heading" % i, L.emph(st["head"]), L.px(head_px, size), 24, "sh"), body))
    result = L.fit("result line", L.emph(s["result"]), L.px(40, size), 22, "result") if s.get("result") else ""
    inner = (L.top_row(s.get("eyebrow", ""), size)
             + '<div class="main from-top" data-fitbox="steps">%s<div class="rail">%s</div>%s</div>'
             % (L.fit("title", L.emph(s["title"]), L.start_size(s["title"], 80, size), 38, "h"), "".join(rows), result))
    return ground, pal, inner


def _checklist(kit, s, size, warnings):
    ground = s.get("ground") or _default(kit, "checklist")
    pal = kit.palette(ground)
    count = len(s["items"])
    base = 50 if count <= 3 else 46 if count == 4 else 41 if count == 5 else 36
    # The whole row is what gets fitted: the tick is sized in em, so it follows the text down.
    rows = "".join(L.fit("row %d" % i, '<span class="tick">%s</span><span class="rowtext">%s</span>'
                         % (L.ICONS["check"], L.esc(item)), L.px(base, size), 22, "row")
                   for i, item in enumerate(s["items"], 1))
    inner = (L.top_row(s.get("eyebrow", ""), size)
             + '<div class="main" data-fitbox="checklist">%s<hr class="rule" style="margin:44px 0">'
               '<div class="rows">%s</div></div>'
             % (L.fit("title", L.rich(s["title"], s.get("accent"), warnings, "the title"),
                      L.start_size(s["title"], 72, size), 36, "h"), rows))
    return ground, pal, inner


def _stat(kit, s, size, warnings):
    ground = s.get("ground") or _default(kit, "stat")
    pal = kit.palette(ground)
    n = len(str(s["stat"]))
    number = L.fit("number", L.esc(s["stat"]), L.px(270 if n <= 4 else 210 if n <= 6 else 160, size), 84, "num bignum")
    head = L.fit("headline", L.rich(s["headline"], s.get("accent"), warnings),
                 L.start_size(s["headline"], 64, size), 32, "h", style="margin-top:.5em;")
    kick = L.fit("supporting line", L.esc(s["kicker"]), L.px(32, size), 21, "kick") if s.get("kicker") else ""
    # Whether the number is backed up is decided by the fact check on the whole slide (see
    # render/__init__.py), not by whether a source line was typed. This only draws it.
    src = L.fit("source", "Source: " + L.esc(s["source"]), L.px(18, size), 13, "source") if s.get("source") else ""
    inner = (L.top_row(s.get("eyebrow", ""), size)
             + '<div class="main" data-fitbox="stat">%s%s%s%s</div>' % (number, head, kick, src))
    return ground, pal, inner


def _compare(kit, s, size, warnings):
    """Two columns laid out as ONE grid: a row on the left is always as tall as the row beside
    it, so the pairs read across. Each cell is its own box for fitting, and texts of the same
    kind share a group so the two columns finish at the same sizes."""
    was_pal, now_pal = kit.palette(kit.strong()), kit.palette("main")
    sides = (("l", "left", s["left"], was_pal, "cross"), ("r", "right", s["right"], now_pal, "check"))
    rows = max(len(s["left"]["items"]), len(s["right"]["items"]))
    item_px = L.px(33 if rows <= 3 else 30 if rows == 4 else 27, size)

    cells = []
    for cls, name, side, pal, _icon in sides:
        tag = L.fit(name + " label", L.esc(side["tag"]), L.px(20, size), 12, "ctag", group="cmp-tag") if side.get("tag") else ""
        note = L.fit(name + " note", L.esc(side["note"]), L.px(18, size), 12, "cnote", group="cmp-note") if side.get("note") else ""
        cells.append('<div class="cell headc %s" data-fitbox="%s column heading" style="%s">%s%s%s</div>'
                     % (cls, name, L.palette_style(pal), tag,
                        L.fit(name + " title", L.esc(side["title"]), L.start_size(side["title"], 62, size), 28,
                              "chead", group="cmp-title"), note))
    for i in range(rows):
        for cls, name, side, pal, icon in sides:
            if i >= len(side["items"]):
                cells.append('<div class="cell %s"></div>' % cls)
                continue
            cells.append('<div class="cell %s" data-fitbox="%s column row %d" style="%s">%s</div>'
                         % (cls, name, i + 1, L.palette_style(pal),
                            L.fit("%s row %d" % (name, i + 1), '<span class="mk">%s</span><span class="it">%s</span>'
                                  % (L.ICONS[icon], L.esc(side["items"][i])), item_px, 17, "item", group="cmp-row")))

    # The brand stamp floats over both columns, so it carries its own colours.
    handle = ('<span class="sep"></span>' + L.fit("footer line", L.esc(kit.handle), L.px(16, size), 12, "handle", "span")
              if kit.handle else "")
    footbar = ('<div class="footbar" data-fitbox="footer" style="--bar-bg:%s;--bar-fg:%s;--bar-muted:%s;'
               '--bar-line:%s;">%s%s</div>'
               % (was_pal["panel"], was_pal["head"], was_pal["muted"], was_pal["rule"],
                  L.fit("wordmark", '<i class="chip"></i>' + L.esc(kit.wordmark), L.px(27, size), 15, "wm", "span"),
                  handle))
    g = L.geometry(size)
    vs_top = g["pad_top"] + (size[1] - g["pad_top"] - g["foot"] - g["pad_bottom"] - 70) // 2
    inner = ('<div class="cmpbg l" style="%s"></div><div class="cmpbg r" style="%s"></div>'
             '<div class="cgrid" data-fitbox="comparison">%s</div><div class="vs" style="--vs-top:%dpx">VS</div>%s'
             % (L.palette_style(was_pal), L.palette_style(now_pal), "".join(cells), vs_top, footbar))
    return "compare", now_pal, inner


BUILDERS = {"steps": _steps, "checklist": _checklist, "stat": _stat, "compare": _compare}


def build(kit, spec, size):
    """Slides for a carousel spec that has already passed validate_spec."""
    from smf.studio.render.spec import carousel_kind
    slides = spec["slides"]
    total = len(slides)
    out = []
    for i, s in enumerate(slides):
        kind = carousel_kind(s, i, total)
        warnings = []
        if kind in ("cover", "point", "cta"):
            base, floor = {"cover": (112, 46), "point": (88, 40), "cta": (88, 40)}[kind]
            ground, pal, inner = _statement(kit, s, size, warnings, kind, base, floor)
        else:
            ground, pal, inner = BUILDERS[kind](kit, s, size, warnings)
        if kind == "compare":
            html = L.page(kit, pal, size, inner + L.pager(i, total), CSS, "cmp")
        else:
            html = L.page(kit, pal, size, inner + L.footer(kit, ground, size, spec.get("footer_line"))
                          + L.pager(i, total), CSS)
        out.append(L.Slide(name=kind, html=html, size=size, label="Slide %d of %d" % (i + 1, total),
                           warnings=warnings))
    return out
