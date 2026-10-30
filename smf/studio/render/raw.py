"""raw.py - the two deliberately plain formats.

A feed full of designed cards teaches people to skip designed cards. These two look like
something a person made in a minute, which is why they get read.

    notes            a slide that looks like a quick note: a bold title, a few ticked lines,
                     a closing line. Plain dark or plain light, almost no design.
                     slide: {"title": ..., "items": [...], "closer": ...}  or  {"text": ...}

    post-screenshot  a slide that looks like a screenshot of a short post: a round picture,
                     the name of whoever is speaking, the words. It imitates no particular
                     network: no logo, no counts, no date.
                     slide: {"text": ...}

THE ROUND PICTURE
It is the identity's initial in a circle of the brand's accent colour, unless the brand has
supplied its own photo. A photo is used only when it is clearly meant for that identity: the
spec names it with "avatar" (a file inside Brand/brand-kit/photos/), or the brand saved it as
Brand/brand-kit/photos/avatar-<identity>.png (or .jpg, .jpeg, .webp). No other photo in the
folder is ever picked. The name under the picture is the identity's display name, and the line
under that is its handle when it has one; nothing is made up to fill a gap.
"""
from __future__ import annotations

from smf.studio.render import layout as L
from smf.studio.render.kit import best_on, ensure_contrast, initials

THEMES = {
    "dark": {"bg": "#17171A", "text": "#F7F7F8", "muted": "#9C9CA6", "line": "#2C2C31", "card": "#1F1F24"},
    "light": {"bg": "#FFFDF8", "text": "#19191C", "muted": "#6F6F78", "line": "#E9E6DE", "card": "#FFFFFF"},
}

NOTES_CSS = """
.canvas.note{padding:0;background:var(--n-bg);color:var(--n-text);font-family:"smf-body",sans-serif;}
.nbar{flex:0 0 auto;display:flex;justify-content:space-between;align-items:center;
  padding:calc(var(--pad-top) - 40px) calc(var(--pad-right) - 32px) 26px 64px;border-bottom:1px solid var(--n-line);
  font-family:"smf-mono",monospace;letter-spacing:.18em;text-transform:uppercase;color:var(--n-muted);}
.nbar b{font-weight:500;color:var(--n-accent);}
.nbody{flex:1 1 0;min-height:0;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-start;
  padding:54px calc(var(--pad-right) - 32px) 30px 64px;}
.nbody.alone{justify-content:center;padding-bottom:90px;}
.ntitle{font-family:"smf-display",sans-serif;font-weight:750;letter-spacing:-0.022em;line-height:1.16;
  color:var(--n-text);text-wrap:balance;}
.nitems{display:flex;flex-direction:column;gap:.58em;margin-top:.9em;}
.nitem{display:flex;gap:.55em;align-items:flex-start;line-height:1.34;color:var(--n-text);}
.ntick{flex:0 0 auto;width:1.12em;height:1.12em;margin-top:.1em;border-radius:50%;background:var(--n-accent);
  color:var(--n-on);display:flex;align-items:center;justify-content:center;}
.ntick .ico{width:.64em;height:.64em;}
.ncloser{margin-top:1em;line-height:1.34;color:var(--n-text);}
.nfoot{flex:0 0 auto;padding:0 calc(var(--pad-right) - 32px) calc(var(--pad-bottom) + 18px) 64px;display:flex;justify-content:space-between;
  font-family:"smf-mono",monospace;letter-spacing:.05em;color:var(--n-muted);white-space:nowrap;overflow:hidden;}
"""

POST_CSS = """
.canvas.shot{background:var(--s-back);align-items:stretch;justify-content:center;
  padding:var(--pad-top) calc(var(--pad-right) - 24px) calc(var(--pad-bottom) + 44px) 72px;}
.card{flex:0 1 auto;min-height:0;max-height:100%;display:flex;flex-direction:column;gap:30px;background:var(--s-card);
  border:2px solid var(--s-line);border-radius:30px;padding:54px 54px 42px;color:var(--s-text);
  box-shadow:0 30px 70px -40px rgba(0,0,0,.38);font-family:"smf-body",sans-serif;overflow:hidden;}
.who{flex:0 0 auto;display:flex;gap:26px;align-items:center;min-width:0;}
.face{flex:0 0 auto;width:96px;height:96px;border-radius:50%;background:var(--s-accent);color:var(--s-on);
  display:flex;align-items:center;justify-content:center;font-family:"smf-display",sans-serif;font-weight:700;
  font-size:40px;letter-spacing:-0.01em;overflow:hidden;}
.face img{width:100%;height:100%;object-fit:cover;display:block;}
.names{flex:1 1 0;min-width:0;display:flex;flex-direction:column;gap:4px;overflow:hidden;}
.dname{font-family:"smf-display",sans-serif;font-weight:700;letter-spacing:-0.015em;line-height:1.1;
  white-space:nowrap;color:var(--s-text);}
.dline{color:var(--s-muted);white-space:nowrap;line-height:1.2;}
.words{flex:0 1 auto;min-height:0;overflow:hidden;}
.said{line-height:1.46;letter-spacing:-0.008em;font-weight:450;color:var(--s-text);}
.acts{flex:0 0 auto;display:flex;justify-content:space-between;padding:24px 8px 0;border-top:2px solid var(--s-line);
  color:var(--s-muted);font-size:34px;}
.count{position:absolute;left:0;right:0;bottom:calc(var(--pad-bottom) + 4px);text-align:center;
  font-family:"smf-mono",monospace;font-size:24px;letter-spacing:.12em;color:var(--s-count);}
"""


def _theme(spec, default):
    """Notes default to dark and post screenshots to light; a spec may ask for the other."""
    wanted = spec.get("theme") or default
    return wanted, THEMES[wanted]


def build_notes(kit, spec, size):
    _name, t = _theme(spec, "dark")
    accent = ensure_contrast(kit.colours["accent"], t["bg"], 3.0, [t["text"]])
    on = best_on(accent, [t["bg"], t["text"]])
    pal = kit.palette("main")
    slides, total = spec["slides"], len(spec["slides"])
    out = []
    for i, s in enumerate(slides):
        title = s.get("title") or s.get("text") or ""
        n = len(title)
        title_px = L.px(90 if n <= 40 else 76 if n <= 70 else 62 if n <= 110 else 52, size)
        items = "".join(L.fit("line %d" % k, '<span class="ntick">%s</span><span>%s</span>' % (L.ICONS["check"], L.esc(it)),
                              L.px(52, size), 26, "nitem")
                        for k, it in enumerate(s.get("items") or [], 1))
        closer = (L.fit("closing line", L.esc(s["closer"]).replace("\n", "<br>"), L.px(50, size), 26, "ncloser")
                  if s.get("closer") else "")
        counter = "%d / %d" % (i + 1, total) if total > 1 else ""
        inner = ('<div class="nbar" style="font-size:%dpx"><span><b>&#9679;</b>&nbsp; Note</span><span>%s</span></div>'
                 '<div class="nbody%s" data-fitbox="note">%s%s%s</div>'
                 '<div class="nfoot" style="font-size:%dpx"><span>%s</span><span>%s</span></div>'
                 % (L.px(24, size, L.MIN_TEXT_PX), counter, "" if (items or closer) else " alone",
                    L.fit("title", L.esc(title).replace("\n", "<br>"), title_px, 34, "ntitle"),
                    '<div class="nitems">%s</div>' % items if items else "", closer,
                    L.px(24, size, L.MIN_TEXT_PX), L.esc(kit.wordmark), L.esc(spec.get("footer_line", kit.handle) or "")))
        css = NOTES_CSS + (":root{--n-bg:%s;--n-text:%s;--n-muted:%s;--n-line:%s;--n-accent:%s;--n-on:%s;--bg:%s;}"
                           % (t["bg"], t["text"], t["muted"], t["line"], accent, on, t["bg"]))
        out.append(L.Slide(name="note", html=L.page(kit, pal, size, inner, css, "note"), size=size,
                           label="Slide %d of %d" % (i + 1, total)))
    return out


def build_post_screenshots(kit, brand, spec, size):
    identity = brand.identity(spec["identity"])
    theme, t = _theme(spec, "light")
    pal = kit.palette("soft" if theme == "light" else ("main" if kit.is_dark() else "bold"))
    back = pal["bg"]
    accent = ensure_contrast(kit.colours["accent"], t["card"], 3.0, [t["text"]])
    on = best_on(accent, ["#FFFFFF"], 3.0)            # white initials unless they would vanish
    photo = kit.avatar(brand, spec["identity"], spec.get("avatar", ""))
    if photo is not None:
        face = '<div class="face"><img src="%s" alt=""></div>' % L.esc(photo.as_uri())
    else:
        face = '<div class="face">%s</div>' % L.esc(initials(identity["display_name"], identity.get("kind", "person")))
    second = identity.get("handle") or identity.get("role") or ""
    who = ('<div class="who" data-fitbox="name">%s<div class="names">%s%s</div></div>'
           % (face, L.fit("name", L.esc(identity["display_name"]), L.px(38, size), 22, "dname"),
              L.fit("handle", L.esc(second), L.px(29, size), 18, "dline") if second else ""))
    acts = '<div class="acts">%s</div>' % "".join(L.ICONS[k] for k in ("reply", "repeat", "heart", "send"))
    slides, total = spec["slides"], len(spec["slides"])
    out = []
    for i, s in enumerate(slides):
        n = len(s["text"])
        said_px = L.px(60 if n <= 80 else 50 if n <= 150 else 42 if n <= 230 else 36, size)
        count = '<div class="count">%d / %d</div>' % (i + 1, total) if total > 1 else ""
        inner = ('<div class="card">%s<div class="words" data-fitbox="post">%s</div>%s</div>%s'
                 % (who, L.fit("text", L.esc(s["text"]).replace("\n", "<br>"), said_px, 27, "said"), acts, count))
        css = POST_CSS + (":root{--s-back:%s;--s-card:%s;--s-text:%s;--s-muted:%s;--s-line:%s;--s-accent:%s;"
                          "--s-on:%s;--s-count:%s;--bg:%s;}"
                          % (back, t["card"], t["text"], t["muted"], t["line"], accent, on,
                             ensure_contrast(pal["muted"], back, 3.0, [pal["head"], "#FFFFFF"]), back))
        out.append(L.Slide(name="post", html=L.page(kit, pal, size, inner, css, "shot"), size=size,
                           label="Slide %d of %d" % (i + 1, total)))
    return out
