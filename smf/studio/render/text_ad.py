"""text_ad.py - bold text cards: just the words, large and unavoidable.

No eyebrow, no soft supporting paragraph, no decoration. A condensed poster face in capitals,
one highlight colour, an optional second line and an optional call-to-action bar. It is meant
to look nothing like the brand's polished cards, so it interrupts a feed of them.

Two layouts:
    ad          headline, optional `subline`, optional `button`. The default.
    statement   ONE idea, for when the picture will be seen small (a story sticker, a video
                frame, a thumbnail). Hard limits instead of quiet shrinking: at most 15 words
                across the headline and the supporting line, at most three lines. Anything
                denser is refused, because shrunk-down dense text is unreadable text.

Backgrounds: bold (the brand's headline colour), accent, main, or black for maximum contrast.
"""
from __future__ import annotations

import re

from smf.studio.render import layout as L

STATEMENT_MAX_WORDS = 15
STATEMENT_MAX_LINES = 3
GROUNDS = ("bold", "accent", "main", "black")

CSS = """
.canvas.ad{justify-content:center;}
.adbox{flex:1 1 0;min-height:0;overflow:hidden;display:flex;flex-direction:column;justify-content:center;
  align-items:flex-start;}
.adbox > *{max-width:100%;}
.shout{font-family:"smf-poster",sans-serif;font-weight:400;text-transform:uppercase;line-height:1.06;
  letter-spacing:.004em;color:var(--head);text-wrap:balance;}
.shout .mark{color:var(--accent);}
.subline{font-family:"smf-display",sans-serif;font-weight:800;text-transform:uppercase;line-height:1.2;
  letter-spacing:-0.005em;color:var(--body);margin-top:1.1em;max-width:26ch;text-wrap:balance;}
.bar{display:inline-block;background:var(--pill-bg);color:var(--pill-fg);font-family:"smf-display",sans-serif;
  font-weight:800;text-transform:uppercase;letter-spacing:.04em;padding:.78em 1.45em;margin-top:1.7em;
  white-space:nowrap;line-height:1.1;}
.adfoot{flex:0 0 auto;height:var(--foot);display:flex;align-items:center;overflow:hidden;}
.adfoot .wm{color:var(--muted);font-weight:600;}
"""


def word_count(*parts):
    return sum(len(re.findall(r"\S+", p or "")) for p in parts)


def statement_problems(slide, where):
    """Density rules for the `statement` layout, as plain sentences."""
    problems = []
    words = word_count(slide.get("headline"), slide.get("subline"))
    if words > STATEMENT_MAX_WORDS:
        problems.append("%s: a statement card holds one idea in at most %d words; this one has %d. "
                        "Cut it down, or use the 'ad' layout." % (where, STATEMENT_MAX_WORDS, words))
    lines = str(slide.get("headline") or "").count("\n") + 1
    if lines > STATEMENT_MAX_LINES:
        problems.append("%s: the headline has %d lines; a statement card takes at most %d."
                        % (where, lines, STATEMENT_MAX_LINES))
    return problems


def build(kit, spec, size):
    slides, total = spec["slides"], len(spec["slides"])
    out = []
    for i, s in enumerate(slides):
        warnings = []
        ground = s.get("ground") or kit.strong()
        pal = kit.palette(ground)
        statement = (s.get("layout") or "ad") == "statement"
        headline = str(s["headline"])
        if statement:
            longest = max(len(line) for line in headline.split("\n"))
            head_px = L.px(250 if longest <= 9 else 200 if longest <= 13 else 160 if longest <= 18 else 128, size)
        else:
            n = len(headline.replace("\n", ""))
            head_px = L.px(176 if n <= 24 else 150 if n <= 40 else 124 if n <= 60 else 102, size)
        # A lead text: it starts oversized and comes down alone, so a short headline fills the card.
        head = L.fit("headline", L.rich(headline, s.get("accent"), warnings), head_px, 54, "shout", lead=1.5)
        sub = (L.fit("second line", L.esc(s["subline"]).replace("\n", "<br>"), L.px(46 if statement else 40, size), 24,
                     "subline") if s.get("subline") else "")
        bar = L.fit("button", L.esc(s["button"]), L.px(34, size), 20, "bar") if s.get("button") and not statement else ""
        inner = ('<div class="adbox" data-fitbox="card">%s%s%s</div>'
                 '<div class="adfoot" data-fitbox="footer">%s</div>'
                 % (head, sub, bar,
                    L.fit("wordmark", '<i class="chip"></i>' + L.esc(kit.wordmark), L.px(28, size), 15, "wm", "span")))
        label = "The bold text card" if total == 1 else "Card %d of %d" % (i + 1, total)
        out.append(L.Slide(name="statement" if statement else "text", html=L.page(kit, pal, size, inner, CSS, "ad"),
                           size=size, label=label, warnings=warnings))
    return out
