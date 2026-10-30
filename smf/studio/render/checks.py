"""checks.py - what a FREE page must pass, measured on the page as it was actually drawn.

The fixed formats are safe by construction: the Factory writes every element, marks every text
and knows every colour. A free page (see free.py) is written by whoever designs the picture, so
nothing can be assumed about it. These checks read the drawn page instead:

    every visible word       is on the picture, not cut off by its box or by the edge
                             is at least the smallest readable size
                             is set in one of the brand's own fonts
                             stands out from what is really behind it (measured from the pixels)
    no word                  is drawn by the styling (content: "..."), where it cannot be read

`CHECK_SCRIPT` runs inside the page and returns the words it found, grouped the way a reader
would group them. Those are the words the fact check and the brand's own rules are given, so a
picture is checked on what it shows, never on what its author says it shows.
"""
from __future__ import annotations

import io
import re

MIN_TEXT_SHARE = 24.0 / 1080.0          # the smallest text, as a share of the picture's width
LARGE_TEXT_SHARE = 48.0 / 1080.0        # from this size up, large-type contrast applies
CONTRAST_SMALL = 4.5
CONTRAST_LARGE = 3.0
MAX_PROBLEMS_SHOWN = 6

# Hides the letters and nothing else, so a second picture shows what is behind every word.
HIDE_TEXT_SCRIPT = """
() => { const s = document.createElement('style');
  s.textContent = '*{-webkit-text-fill-color:transparent !important;text-shadow:none !important;'
    + '-webkit-text-stroke-color:transparent !important;text-decoration-color:transparent !important;}';
  document.head.appendChild(s); }
"""

CHECK_SCRIPT = r"""
(cfg) => {
  const out = {texts: [], problems: [], spots: []};
  const W = cfg.w, H = cfg.h, slack = 1.5;
  const blockOf = el => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const d = getComputedStyle(e).display;
      if (!d.startsWith('inline') && d !== 'contents') return e;
    }
    return document.body;
  };
  const groups = new Map();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const words = node.nodeValue.replace(/\s+/g, ' ').trim();
    if (!words) continue;
    const el = node.parentElement, cs = getComputedStyle(el);
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
    if (!rects.length || cs.visibility !== 'visible') continue;          // not drawn at all
    let opacity = 1;
    for (let e = el; e; e = e.parentElement) opacity *= parseFloat(getComputedStyle(e).opacity);
    if (opacity < 0.02) continue;                                         // not drawn at all
    const box = {left: Math.min(...rects.map(r => r.left)), right: Math.max(...rects.map(r => r.right)),
                 top: Math.min(...rects.map(r => r.top)), bottom: Math.max(...rects.map(r => r.bottom))};
    const size = parseFloat(cs.fontSize);
    const family = cs.fontFamily.split(',')[0].trim().replace(/["']/g, '');
    // Sideways the letters themselves are measured. Up and down, a letter's own box is taller
    // than the letter (and taller still with tight line spacing), so some overhang there is not
    // a cut. Letters that really touch the edge of the picture are caught from the pixels.
    const lean = size * 0.5;
    let cut = box.left < -slack || box.right > W + slack || box.top < -lean || box.bottom > H + lean;
    for (let e = el; e && !cut; e = e.parentElement) {
      const es = getComputedStyle(e);
      if (es.overflowX === 'visible' && es.overflowY === 'visible') continue;
      const r = e.getBoundingClientRect();
      cut = box.left < r.left - slack || box.right > r.right + slack
         || box.top < r.top - lean || box.bottom > r.bottom + lean;
    }
    if (cut) out.problems.push({kind: 'cut', text: words});
    if (size < cfg.min - 0.5) out.problems.push({kind: 'small', text: words, size: Math.round(size)});
    if (!family.startsWith('smf-')) out.problems.push({kind: 'font', text: words, family});
    out.spots.push({text: words, color: cs.color, opacity, size, weight: parseInt(cs.fontWeight, 10) || 400,
      rects: rects.map(r => [Math.max(0, r.left), Math.max(0, r.top), Math.min(W, r.right), Math.min(H, r.bottom)])});
    const block = blockOf(el);
    if (!groups.has(block)) groups.set(block, []);
    groups.get(block).push(words);
  }
  out.texts = [...groups.values()].map(parts => parts.join(' '));
  for (const el of document.body.querySelectorAll('*')) {
    for (const pseudo of ['::before', '::after']) {
      const c = getComputedStyle(el, pseudo).content;
      if (c && !['none', 'normal', '""', "''"].includes(c)) out.problems.push({kind: 'generated', text: c});
    }
  }
  return out;
}
"""


def min_text_px(size):
    """The smallest text allowed on a free page of this size, in pixels."""
    return int(round(MIN_TEXT_SHARE * int(size[0])))


def _short(text, limit=70):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _luminance(rgb):
    def channel(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])


def _ratio(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


_RGB = re.compile(r"^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$")


def parse_colour(text):
    """((r, g, b), alpha) from the browser's own spelling of a colour, or None when it is written
    in a form this check cannot read."""
    m = _RGB.match(str(text or "").strip().lower())
    if not m:
        return None
    alpha = m.group(4)
    if alpha is None:
        a = 1.0
    elif alpha.endswith("%"):
        a = float(alpha[:-1]) / 100.0
    else:
        a = float(alpha)
    return (float(m.group(1)), float(m.group(2)), float(m.group(3))), max(0.0, min(1.0, a))


def contrast_problems(spots, behind_png, size):
    """Words that do not stand out from what is behind them, as problem rows.

    `behind_png` is the page drawn again with its letters hidden. For each run of words the
    pixels under it are sampled and the text colour is compared with each one; the tenth lowest
    in a hundred is the figure used, so one thin line crossing a word does not fail it, and a
    word half over a pale patch does."""
    from PIL import Image
    behind = Image.open(io.BytesIO(behind_png)).convert("RGB")
    width, height = behind.size
    pixels = behind.load()
    large = LARGE_TEXT_SHARE * int(size[0])
    out = []
    for spot in spots:
        parsed = parse_colour(spot.get("color"))
        if parsed is None:
            out.append({"kind": "colour", "text": spot["text"], "colour": spot.get("color")})
            continue
        ink, alpha = parsed
        alpha *= float(spot.get("opacity") or 1.0)
        ratios = []
        for left, top, right, bottom in spot["rects"]:
            x0, y0 = max(0, int(left)), max(0, int(top))
            x1, y1 = min(width, int(right + 0.999)), min(height, int(bottom + 0.999))
            step_x, step_y = max(1, (x1 - x0) // 24), max(1, (y1 - y0) // 8)
            for y in range(y0, y1, step_y):
                for x in range(x0, x1, step_x):
                    back = pixels[x, y]
                    seen = tuple(ink[i] * alpha + back[i] * (1.0 - alpha) for i in range(3))
                    ratios.append(_ratio(seen, back))
        if not ratios:
            continue
        ratios.sort()
        measured = ratios[len(ratios) // 10]
        needed = CONTRAST_LARGE if float(spot.get("size") or 0) >= large else CONTRAST_SMALL
        if measured < needed:
            out.append({"kind": "faint", "text": spot["text"], "measured": measured, "needed": needed})
    return out


def edge_problems(drawn_png, behind_png):
    """A problem row when letters reach the very edge of the picture, which means some of them
    are off it. Found by comparing the picture with the one whose letters are hidden: any
    difference in the outermost pixels is ink that ran to the edge."""
    from PIL import Image, ImageChops
    drawn = Image.open(str(drawn_png)).convert("RGB")
    behind = Image.open(io.BytesIO(behind_png)).convert("RGB")
    diff = ImageChops.difference(drawn, behind).convert("L").point(lambda v: 255 if v > 24 else 0)
    width, height = diff.size
    frame = [(0, 0, width, 2), (0, height - 2, width, height), (0, 0, 2, height), (width - 2, 0, width, height)]
    if any(diff.crop(box).getbbox() for box in frame):
        return [{"kind": "edge", "text": ""}]
    return []


def problem_message(label, problems, min_px):
    """One message for the person, naming the picture and the words, for every kind of problem."""
    lines, said = [], set()
    for p in problems:
        words = _short(p.get("text"))
        if p["kind"] == "edge":
            line = "some words run right to the edge of the picture and are cut off. Give them more room."
        elif p["kind"] == "cut":
            line = 'these words run off the picture or are cut off: "%s". Make them smaller or give them more room.' % words
        elif p["kind"] == "small":
            line = ('these words are too small to read on a phone (%d pixels; the smallest allowed here is %d): "%s".'
                    % (p.get("size") or 0, min_px, words))
        elif p["kind"] == "font":
            line = ('these words use a font that is not one of this brand\'s ("%s"): "%s". Use smf-display, smf-body, '
                    'smf-mono or smf-poster.' % (_short(p.get("family"), 30), words))
        elif p["kind"] == "generated":
            line = ("the page draws words from its styling (content: %s), where they cannot be checked. Put the "
                    "words in the page itself." % _short(p.get("text"), 40))
        elif p["kind"] == "colour":
            line = ('the colour of these words is written in a form that cannot be checked (%s): "%s". Use a hex or '
                    'rgb colour.' % (_short(p.get("colour"), 30), words))
        else:
            line = ('these words are hard to read against what is behind them (%.1f to 1; at least %.1f is needed): '
                    '"%s".' % (p["measured"], p["needed"], words))
        if line not in said:
            said.add(line)
            lines.append(line)
    more = len(lines) - MAX_PROBLEMS_SHOWN
    shown = lines[:MAX_PROBLEMS_SHOWN] + (["and %d more like these." % more] if more > 0 else [])
    return "%s: %s" % (label, " Also: ".join(shown))
