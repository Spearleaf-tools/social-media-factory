"""overlays.py - every word that appears on a finished clip is drawn here, as a picture.

Text is never handed to the video program to draw. Whether that program can draw text at all
depends on how it was built, and that differs from one computer to the next. So each piece of text
is drawn with the imaging library, in the fonts that ship with the Factory (or the brand's own)
and the brand's own colours, saved as a see-through picture, and laid over the video.

WHAT IS DRAWN, AND WHERE THE WORDS COME FROM
  on-screen text   the 3 to 7 words the clip report carries. A card for the first seconds of a
                   full-frame version, a heading above the picture in a square version.
  lower third      the credit line from the clip report, exactly as written there.
  captions         the transcript's own words, two to four at a time, the word being spoken in
                   the brand's accent colour. They come from the recording's transcript, retimed
                   to the clip by arithmetic. A finished clip is never listened to again to make
                   captions: a second, weaker listen is how a misheard word gets burned in.
  disclaimer       the brand's disclaimer, on a solid plate, for the whole length of any clip
                   whose gate is HOLD.
  PREVIEW stamp    across any version made for a person to watch before sign-off.
Nothing here writes a word of its own. A claim that is not in the clip report is never on screen.

THE DISCLAIMER CANNOT BE LEFT OFF. `compose()` is the only way a set of overlays is made. When a
clip needs its disclaimer and there is no text for one, it raises instead of returning a set
without it. The renderer then checks the finished pixels before a file is given its real name
(`band_present`), so a band that was planned but did not reach the picture is caught too.

ONE LAYOUT FOR EVERY PLATFORM. Each app covers a different part of the frame with its own
buttons and captions. Rendering a separate file per app would multiply every batch, so text is
kept inside the area that is clear on ALL of them (`design_box`). The margins below are working
estimates as of September 2026, not measurements taken from each app. Designing to the strictest
one on every side is what makes a small error in any single number harmless. Refresh them when
an app changes its layout.

PLACEMENT IS MEASURED, NOT ASSUMED. After anything is drawn, the picture's real ink (its
non-transparent pixels) is measured and compared with the clear area, and the pieces are checked
against each other. Measuring the result, rather than repeating the sums that placed it, is the
only check that can disagree with a mistake in those sums. An outline is ink too.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from smf.brands import mix
from smf.studio.render import kit as KIT
from smf.video.common import VideoError, as_brand, norm_token
from smf.video.fine_cut import is_filler

CANVAS_W, CANVAS_H = 1080, 1920
FORMATS = ("fullbleed", "square")

# Pixels of a 1080 x 1920 frame that each app covers with its own interface. Working estimates.
SAFE_MARGINS_AS_OF = "September 2026"
SAFE_MARGINS_LAST_REVIEWED = "2026-09-20"
SAFE_MARGINS = {
    "tiktok": {"top": 180, "bottom": 320, "left": 60, "right": 120},
    "instagram": {"top": 220, "bottom": 420, "left": 60, "right": 120},
    "facebook": {"top": 220, "bottom": 420, "left": 60, "right": 120},
    "youtube": {"top": 200, "bottom": 400, "left": 60, "right": 140},
    "linkedin": {"top": 120, "bottom": 240, "left": 60, "right": 60},
}

GAP = 24                       # the least space between two pieces of text
HOOK_HOLD = 3.0                # seconds the opening card stays up in a full-frame version
HOOK_FADE = 0.35
FB_HOOK_CY = 1030              # where the card sits when nothing is known about the face
FB_CAPTION_CY = 1300
SQUARE_SIDE = 880              # the picture in a square version, before anything has to make room
SQUARE_SIDE_MIN = 600
HEAD_CLEARANCE = 0.04          # of the frame's height, kept between a face and a card

HOOK_SIZES = (100, 64)         # largest and smallest type for the card
HEADING_SIZES = (88, 56)
THIRD_SIZES = (40, 30)
CAPTION_SIZES = (64, 40)
CAPTION_HARD_FLOOR = 22        # one very long word is drawn smaller rather than cut off
CAPTION_STRIP_H = 132
CAPTION_PLATE = "#0D0D0D"
CAPTION_PLATE_ALPHA = 230
CAPTION_MIN_WORDS, CAPTION_MAX_WORDS = 2, 4
CAPTION_PAUSE = 0.7            # a silence this long always starts a new caption line
CAPTION_LEAD, CAPTION_LINGER = 0.08, 0.25
CAPTION_MIN_STATE = 0.05
ACCENT_CONTRAST = 4.5
FILLER_GUARD = 0.4             # above this share of "fillers" the transcript is suspect, not the speaker

DISCLAIMER_SIZES = (44, 38)    # 38 is the smallest that still reads on a phone held at arm's length
DISCLAIMER_MAX_LINES = 4
DISCLAIMER_PLATE = "#0B0B0B"
DISCLAIMER_INK = "#FFFFFF"
DISCLAIMER_KEYLINE = 3         # pixels of light outline round the plate

_CUT_OFF_WORD = re.compile(r"^[A-Za-z]{1,4}-$")     # "th-", "beca-": a word the speaker abandoned
_TRAILING = ",.;:\u2026"


class OverlayError(VideoError):
    """On-screen text could not be drawn safely. Worded for the person."""


# ----------------------------------------------------------------------------- the clear area
def design_box(platforms=None):
    """(left, top, right, bottom) of the area no listed app covers. All of them by default."""
    names = list(platforms or SAFE_MARGINS)
    unknown = [n for n in names if n not in SAFE_MARGINS]
    if unknown:
        raise OverlayError("There are no screen margins recorded for %s. The ones recorded are: %s."
                           % (", ".join(unknown), ", ".join(sorted(SAFE_MARGINS))))
    side = {k: max(SAFE_MARGINS[n][k] for n in names) for k in ("top", "bottom", "left", "right")}
    return side["left"], side["top"], CANVAS_W - side["right"], CANVAS_H - side["bottom"]


def text_column(box=None):
    """(left, right) of the widest column that is centred on the frame and still inside the clear
    area. The clear area is not centred (one side carries a rail of buttons), and text centred on
    an off-centre box looks like a mistake, so the column is centred and made narrower instead."""
    left, _top, right, _bottom = box or design_box()
    half = min(CANVAS_W // 2 - left, right - CANVAS_W // 2)
    return CANVAS_W // 2 - half, CANVAS_W // 2 + half


def clear_on(rect):
    """Which apps' clear areas hold this rectangle completely. For reports."""
    out = []
    for name in sorted(SAFE_MARGINS):
        left, top, right, bottom = design_box([name])
        if rect[0] >= left and rect[1] >= top and rect[2] <= right and rect[3] <= bottom:
            out.append(name)
    return out


# ----------------------------------------------------------------------------- fonts and colours
def _rgba(hex_colour, alpha=255):
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)) + (alpha,)


class Faces(object):
    """The font file for each kind of text, for ONE brand. A brand's own font is used when it is a
    kind the imaging library reads (TTF or OTF); otherwise the built-in face, with a note. No font
    is ever looked for on the computer itself."""

    def __init__(self, brand_kit):
        self.paths, self.notes, self._cache = {}, [], {}
        for role in KIT.ROLES:
            own = [f for f in brand_kit.faces if f.role == role]
            usable = [f for f in own if f.path.suffix.lower() in (".ttf", ".otf")]
            if usable:
                self.paths[role] = str(usable[0].path)
                continue
            if own and own[0].origin == "brand":
                self.notes.append("The brand's %s font is a web font file, which cannot be used on video, so the "
                                  "built-in one was used. Add a TTF or OTF copy to use it." % role)
            built_in = KIT.FONTS_DIR / KIT.BUNDLED[KIT.ROLE_BUILT_IN[role]]["file"]
            if not built_in.is_file():
                raise OverlayError("A font that ships with the Factory is missing. Download the Factory again, "
                                   "or ask Claude to restore the fonts folder.")
            self.paths[role] = str(built_in)

    def get(self, role, size, weight=400):
        from PIL import ImageFont
        key = (role, int(size), int(weight))
        if key not in self._cache:
            font = ImageFont.truetype(self.paths[role], int(size), layout_engine=ImageFont.Layout.BASIC)
            try:
                axes = font.get_variation_axes()
            except Exception:                       # a font with one fixed weight has no axes to set
                axes = []
            if axes:
                values = []
                for axis in axes:
                    name = axis.get("name", b"")
                    name = (name.decode("utf-8", "ignore") if isinstance(name, bytes) else str(name)).lower()
                    low, high = axis["minimum"], axis["maximum"]
                    if name in ("weight", "wght"):
                        values.append(min(high, max(low, weight)))
                    elif name in ("optical size", "opsz"):
                        values.append(min(high, max(low, size)))
                    else:
                        values.append(axis["default"])
                try:
                    font.set_variation_by_axes(values)
                except Exception:
                    pass                            # the default weight still reads; nothing to stop for
            self._cache[key] = font
        return self._cache[key]


@dataclass
class Look(object):
    """How ONE brand's text looks on video. Made from the brand; there is no default look."""
    brand_id: str
    brand_name: str
    card_bg: str
    card_fg: str
    tag_bg: str
    tag_fg: str
    canvas_bg: str
    canvas_fg: str
    accent_on_plate: str
    faces: Faces
    notes: list = field(default_factory=list)


def caption_plate_at_its_lightest():
    """The plate behind captions is slightly see-through, so a white picture underneath lightens
    it. Colours are checked against that lightest case, not against the plate's own colour."""
    return mix(CAPTION_PLATE, "#FFFFFF", 1.0 - CAPTION_PLATE_ALPHA / 255.0)


def look_for(brand):
    brand = as_brand(brand)
    brand_kit = KIT.resolve(brand)                                    # plain errors for a brand with no colours
    bold = brand_kit.palette("bold")
    faces = Faces(brand_kit)
    notes = list(brand_kit.notes) + faces.notes
    accent = brand_kit.colours["accent"]
    # The word being spoken has to stand out at a glance, on a phone, in daylight. Large type would
    # pass at a lower figure, but a word that merely passes does not pop, so it is held to the
    # figure for ordinary text and the accent is lightened until it gets there.
    # Most mid-tone accents get lightened a little, so this is not worth a note on every file; the
    # colour really used is kept on the Look and written into the record of each version.
    readable = KIT.ensure_contrast(accent, caption_plate_at_its_lightest(), ACCENT_CONTRAST, ["#FFFFFF"])
    return Look(brand_id=brand.id, brand_name=brand.name, card_bg=bold["bg"], card_fg=bold["head"],
                tag_bg=bold["pill_bg"], tag_fg=bold["pill_fg"], canvas_bg=bold["bg"], canvas_fg=bold["head"],
                accent_on_plate=readable, faces=faces, notes=notes)


# ----------------------------------------------------------------------------- measuring and fitting
_scratch = {}


def _pen():
    if "d" not in _scratch:
        from PIL import Image, ImageDraw
        _scratch["d"] = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    return _scratch["d"]


def _width(text, font):
    box = _pen().textbbox((0, 0), text, font=font)
    return box[2] - min(0, box[0])


def _wrap(text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if not cur or _width(trial, font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _balanced(text, font, max_w, count):
    """The same words in `count` lines of the most even width. A greedy wrap fills the first line
    and strands one word on the last; on a card of five words that looks like an accident."""
    words = text.split()
    if count <= 1 or count >= len(words) or len(words) > 12:
        return None
    best, best_width = None, None

    def walk(start, left, so_far):
        nonlocal best, best_width
        if left == 1:
            lines = so_far + [" ".join(words[start:])]
            widest = max(_width(ln, font) for ln in lines)
            if widest <= max_w and (best_width is None or widest < best_width):
                best, best_width = lines, widest
            return
        for cut in range(start + 1, len(words) - left + 2):
            walk(cut, left - 1, so_far + [" ".join(words[start:cut])])

    walk(0, count, [])
    return best


def fit_lines(faces, role, weight, text, max_w, sizes, max_lines, hard_floor=None, what="The text"):
    """(font, lines): the largest type at which `text` wraps into `max_lines` and every line fits.
    When even the smallest size needs another line, it gets one: an extra line can be read, a
    clipped word cannot. A single word wider than the column is a plain error."""
    start, floor = sizes
    size = start
    while size >= floor:
        font = faces.get(role, size, weight)
        lines = _wrap(text, font, max_w)
        if len(lines) <= max_lines and all(_width(ln, font) <= max_w for ln in lines):
            return font, _balanced(text, font, max_w, len(lines)) or lines
        size -= 2
    size = floor
    while size >= (hard_floor or floor):
        font = faces.get(role, size, weight)
        lines = _wrap(text, font, max_w)
        if len(lines) <= max_lines + 1 and all(_width(ln, font) <= max_w for ln in lines):
            return font, _balanced(text, font, max_w, len(lines)) or lines
        size -= 2
    raise OverlayError("%s does not fit on the screen at a size people can read: \"%s\". Shorten it."
                       % (what, text[:80]))


def ink_box(image):
    """The rectangle holding every pixel that is not fully see-through, or None."""
    return image.getchannel("A").getbbox()


def _text_image(lines, font, fill, line_gap=0.18, capitals=False):
    """Centred lines as a tight see-through picture (cropped to its ink). Lines of capitals have
    no tails hanging below them, so they are spaced by the height of a capital, not by the
    font's full line height, which would leave a card looking half empty."""
    from PIL import Image, ImageDraw
    ascent, descent = font.getmetrics()
    if capitals:
        tall = _pen().textbbox((0, 0), "H", font=font)
        step = int(round((tall[3] - tall[1]) * (1.0 + line_gap)))
    else:
        step = ascent + descent + int(round(font.size * line_gap))
    widths = [_width(ln, font) for ln in lines]
    img = Image.new("RGBA", (max(widths) + 8, step * (len(lines) - 1) + ascent + descent + 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, (ln, w) in enumerate(zip(lines, widths)):
        box = draw.textbbox((0, 0), ln, font=font)
        draw.text(((img.width - w) // 2 - min(0, box[0]), 4 + i * step), ln, font=font, fill=fill)
    box = ink_box(img)
    return img.crop(box) if box else img


def _plate(width, height, radius, fill):
    """A rounded rectangle with smooth corners (drawn large, then reduced)."""
    from PIL import Image, ImageDraw
    k = 3
    big = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle([0, 0, width * k - 1, height * k - 1], radius=radius * k, fill=fill)
    return big.resize((width, height), Image.LANCZOS)


def _on_plate(text_img, pad_x, pad_y, radius, fill, width=None):
    w = width or text_img.width + 2 * pad_x
    plate = _plate(w, text_img.height + 2 * pad_y, radius, fill)
    plate.alpha_composite(text_img, ((w - text_img.width) // 2, pad_y))
    return plate


# ----------------------------------------------------------------------------- the pieces
def hook_card(look, text, largest=None):
    """The opening card of a full-frame version: the clip's on-screen text, in capitals, on a
    plate of the brand's headline colour."""
    left, right = text_column()
    pad_x, pad_y = 44, 30
    sizes = (max(HOOK_SIZES[1], min(HOOK_SIZES[0], largest or HOOK_SIZES[0])), HOOK_SIZES[1])
    font, lines = fit_lines(look.faces, "poster", 400, text.upper(), right - left - 2 * pad_x, sizes, 2,
                            hard_floor=44, what="The on-screen text")
    return _on_plate(_text_image(lines, font, _rgba(look.card_fg), 0.34, capitals=True), pad_x, pad_y, 26,
                     _rgba(look.card_bg, 245))


def heading(look, text):
    """The same words as a heading above the picture, in a square version. No plate: the canvas
    behind it is already the brand's colour."""
    left, right = text_column()
    font, lines = fit_lines(look.faces, "poster", 400, text.upper(), right - left, HEADING_SIZES, 2,
                            hard_floor=40, what="The on-screen text")
    return _text_image(lines, font, _rgba(look.canvas_fg), 0.34, capitals=True)


def third_tag(look, text):
    """The credit line, exactly as the clip report has it."""
    left, right = text_column()
    pad_x, pad_y = 26, 14
    font, lines = fit_lines(look.faces, "body", 650, text, right - left - 2 * pad_x, THIRD_SIZES, 1,
                            hard_floor=26, what="The lower-third line")
    return _on_plate(_text_image(lines, font, _rgba(look.tag_fg)), pad_x, pad_y, 14, _rgba(look.tag_bg))


def disclaimer_band(look, text):
    """(picture, facts) for the brand's disclaimer. The plate is solid, the full width of the text
    column and always the same two colours. That is deliberate: it reads over any picture, and a
    later check can recognise it in the finished pixels. The type never goes below a size that
    reads on a phone; a disclaimer too long for that is an error, not smaller print."""
    text = " ".join((text or "").split())
    if not text:
        raise OverlayError("There is no disclaimer text to draw.")
    left, right = text_column()
    pad_x, pad_y = 28, 22
    start, floor = DISCLAIMER_SIZES
    chosen = None
    for size in range(start, floor - 1, -2):
        font = look.faces.get("body", size, 600)
        lines = _wrap(text, font, right - left - 2 * pad_x)
        if all(_width(ln, font) <= right - left - 2 * pad_x for ln in lines) and \
                len(lines) <= (DISCLAIMER_MAX_LINES - 1 if size > floor else DISCLAIMER_MAX_LINES):
            chosen = (font, lines, size)
            break
    if chosen is None:
        raise OverlayError("The disclaimer is too long to be read on a phone (%d words). On video it has to fit in "
                           "%d short lines. Shorten it in the brand's settings to about 25 words."
                           % (len(text.split()), DISCLAIMER_MAX_LINES))
    font, lines, size = chosen
    words = _text_image(lines, font, _rgba(DISCLAIMER_INK), 0.22)
    band = framed_plate(right - left, words.height + 2 * pad_y)
    band.alpha_composite(words, ((band.width - words.width) // 2, pad_y))
    return band, {"text": text, "type_size": size, "lines": len(lines), "plate": DISCLAIMER_PLATE,
                  "ink": DISCLAIMER_INK, "keyline": DISCLAIMER_KEYLINE}


def framed_plate(width, height):
    """The disclaimer's plate: solid, with a thin light line all the way round it. The line is not
    decoration. A dark plate with light writing on it is also what a caption looks like, and a
    brand whose own colour is black has a dark frame anyway; a light outline at exactly this place
    is what lets a later check tell the band from both."""
    plate = _plate(width, height, 16, _rgba(DISCLAIMER_INK))
    inner = _plate(width - 2 * DISCLAIMER_KEYLINE, height - 2 * DISCLAIMER_KEYLINE, 16 - DISCLAIMER_KEYLINE,
                   _rgba(DISCLAIMER_PLATE))
    plate.alpha_composite(inner, (DISCLAIMER_KEYLINE, DISCLAIMER_KEYLINE))
    return plate


def preview_stamp(look, waiting_for=""):
    """PREVIEW across the picture, at an angle so it cannot be cropped off an edge."""
    from PIL import Image
    big = _text_image(["PREVIEW"], look.faces.get("poster", 210, 400), (255, 255, 255, 150))
    small_text = "NOT FOR POSTING" + ((" \u00b7 WAITING FOR " + waiting_for.upper()) if waiting_for.strip() else "")
    small_font, small_lines = fit_lines(look.faces, "body", 800, small_text, big.width, (44, 24), 1,
                                        hard_floor=18, what="The preview note")
    small = _text_image(small_lines, small_font, (255, 255, 255, 235))
    tag = _on_plate(small, 22, 12, 12, (0, 0, 0, 200))
    img = Image.new("RGBA", (max(big.width, tag.width) + 40, big.height + tag.height + 50), (0, 0, 0, 0))
    shade = _plate(img.width, img.height, 30, (0, 0, 0, 70))
    img.alpha_composite(shade)
    img.alpha_composite(big, ((img.width - big.width) // 2, 16))
    img.alpha_composite(tag, ((img.width - tag.width) // 2, big.height + 30))
    return img.rotate(20, resample=Image.BICUBIC, expand=True)


# ----------------------------------------------------------------------------- captions: the words
def caption_token(word):
    """How one transcript word is printed: as it was transcribed, without the comma or full stop
    that would trail it. Question and exclamation marks stay; they change how a line is read."""
    t = (word or "").strip().strip("\"\u201c\u201d")
    while t and t[-1] in _TRAILING:
        t = t[:-1]
    return t


def printable_words(words):
    """(kept, dropped, note). Captions leave out "um", "uh" and words the speaker abandoned half
    way ("th-"). The sound is untouched; this only decides what is PRINTED. When a large share of
    a clip would go, the likelier explanation is a transcript that does not belong to this clip,
    so everything is kept and the note says so."""
    kept = [w for w in words if caption_token(w["word"]) and not is_filler(w["word"])
            and not _CUT_OFF_WORD.match(w["word"].strip())]
    dropped = len(words) - len(kept)
    if words and dropped > FILLER_GUARD * len(words):
        return list(words), 0, ("%d of %d words looked like fillers, which is too many to be a hesitant speaker. "
                                "The captions were left word for word; check the transcript belongs to this clip."
                                % (dropped, len(words)))
    return kept, dropped, ""


def _ends_sentence(word):
    return word["word"].strip().rstrip("\"\u201d")[-1:] in ".?!"


def caption_lines(words, fits=None, min_words=CAPTION_MIN_WORDS, max_words=CAPTION_MAX_WORDS, pause=CAPTION_PAUSE):
    """Group a clip's words into caption lines of `min_words` to `max_words`.

    `words` are [{"word", "start", "end", "piece"}] timed from the clip's start; `piece` says which
    joined stretch of the recording the word belongs to. Two rules are never broken:

      * a line never holds words from two pieces. Between two pieces something was removed (a
        pause, a filler, another person), the picture jumps there, and a caption that straddles
        the jump reads as one sentence that was never said that way;
      * a line never runs wider than the text column. `fits(list of printed words)` decides;
        a line is shortened, down to a single word, until it does.

    Within those, a line prefers to end where a sentence ends, and a single left-over word is
    avoided by rebalancing with the line before it."""
    fits = fits or (lambda _texts: True)
    runs, run = [], []
    for w in words:
        if run and (w.get("piece") != run[-1].get("piece") or w["start"] - run[-1]["end"] > pause):
            runs.append(run)
            run = []
        run.append(w)
    if run:
        runs.append(run)

    lines = []
    for run in runs:
        i = 0
        while i < len(run):
            take = min(max_words, len(run) - i)
            for k in range(min_words, take + 1):
                if _ends_sentence(run[i + k - 1]):
                    take = k
                    break
            left_over = len(run) - (i + take)
            if left_over == 1:
                if take < max_words:
                    take += 1                                   # three words read better than two and one
                elif take > min_words:
                    take -= 1                                   # four and one becomes three and two
            while take > 1 and not fits([caption_token(w["word"]) for w in run[i:i + take]]):
                take -= 1
            chunk = run[i:i + take]
            lines.append({"words": chunk, "piece": chunk[0].get("piece"), "start": chunk[0]["start"],
                          "end": chunk[-1]["end"], "text": " ".join(caption_token(w["word"]) for w in chunk)})
            i += take
    return lines


def caption_timeline(lines, duration, joins=()):
    """[(start, end, line index or None, active word)] covering the clip from 0 to `duration` with
    no gaps and no overlaps. `joins` are the moments where two pieces meet; a line is taken down
    at a join rather than left hanging over the jump."""
    shows = []
    for i, line in enumerate(lines):
        first, last = line["start"], line["end"]
        begin = max(0.0, first - CAPTION_LEAD, shows[-1][1] if shows else 0.0)
        finish = min(duration, last + CAPTION_LINGER)
        if i + 1 < len(lines):
            finish = min(finish, max(last, lines[i + 1]["start"] - CAPTION_LEAD))
            if lines[i + 1].get("piece") != line.get("piece"):
                ahead = [j for j in joins if j >= last - 0.01]
                if ahead:
                    finish = min(finish, max(last, min(ahead)))
        shows.append((begin, max(begin, finish)))

    raw, cursor = [], 0.0
    for i, (line, (begin, finish)) in enumerate(zip(lines, shows)):
        if finish <= begin:
            continue
        if begin > cursor:
            raw.append([cursor, begin, None, 0])
        words = line["words"]
        for k, w in enumerate(words):
            s = begin if k == 0 else min(max(w["start"], begin), finish)
            e = finish if k == len(words) - 1 else min(max(words[k + 1]["start"], s), finish)
            if e > s:
                raw.append([s, e, i, k])
        cursor = finish
    if duration > cursor or not raw:
        raw.append([cursor, max(duration, cursor + CAPTION_MIN_STATE), None, 0])

    # Nothing shorter than a frame or two survives on its own: it is folded into its neighbour, so
    # the lengths still add up to the clip exactly and later captions cannot drift.
    states = []
    for state in raw:
        if states and state[1] - state[0] < CAPTION_MIN_STATE:
            states[-1][1] = state[1]
        elif states and states[-1][1] - states[-1][0] < CAPTION_MIN_STATE:
            state[0] = states[-1][0]
            states[-1] = state
        else:
            states.append(state)
    return [(round(a, 3), round(b, 3), index, active) for a, b, index, active in states]


def caption_fits(look):
    """The `fits` test for caption_lines: can these words be drawn, at the smallest caption size,
    inside the text column with the plate's padding?"""
    left, right = text_column()
    room = right - left - 2 * 30
    font = look.faces.get("display", CAPTION_SIZES[1], 800)
    return lambda texts: _width(" ".join(texts), font) <= room


def caption_strip(look, texts, active):
    """One caption line as a strip the width of the frame: every word white on the dark plate,
    the word being spoken in the brand's accent."""
    from PIL import Image, ImageDraw
    left, right = text_column()
    pad_x = 30
    room = right - left - 2 * pad_x
    size = CAPTION_SIZES[0]
    while True:
        font = look.faces.get("display", size, 800)
        space = _width("n n", font) - 2 * _width("n", font)
        widths = [_width(t, font) for t in texts]
        total = sum(widths) + space * (len(texts) - 1)
        if total <= room or size <= CAPTION_HARD_FLOOR:
            break
        size -= 2
    if total > room:
        raise OverlayError("A caption word is too long to fit on the screen: \"%s\"." % " ".join(texts)[:60])
    strip = Image.new("RGBA", (CANVAS_W, CAPTION_STRIP_H), (0, 0, 0, 0))
    plate_w, plate_h = int(total) + 2 * pad_x, CAPTION_STRIP_H - 16
    strip.alpha_composite(_plate(plate_w, plate_h, 22, _rgba(CAPTION_PLATE, CAPTION_PLATE_ALPHA)),
                          ((CANVAS_W - plate_w) // 2, 8))
    draw = ImageDraw.Draw(strip)
    ascent, descent = font.getmetrics()
    x = (CANVAS_W - total) / 2.0
    y = 8 + (plate_h - (ascent + descent)) // 2
    for i, (t, w) in enumerate(zip(texts, widths)):
        box = draw.textbbox((0, 0), t, font=font)
        draw.text((int(round(x)) - min(0, box[0]), y), t, font=font,
                  fill=_rgba(look.accent_on_plate if i == active else "#FFFFFF"))
        x += w + space
    return strip


# ----------------------------------------------------------------------------- putting a set together
@dataclass
class Layer(object):
    kind: str                  # under | hook | captions | disclaimer | preview
    path: str
    x: int
    y: int
    rect: tuple                # where its ink sits on the frame
    start: float = 0.0
    end: float = None          # None: the whole clip
    fade: float = 0.0


@dataclass
class OverlaySet(object):
    format: str
    video_rect: tuple          # (x, y, w, h) of the picture on the frame
    canvas_colour: str
    layers: list = field(default_factory=list)
    disclaimer: dict = None    # facts about the band, or None when the clip needs none
    caption_lines: int = 0
    notes: list = field(default_factory=list)

    def layer(self, kind):
        return next((layer for layer in self.layers if layer.kind == kind), None)


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _save(image, x, y, scratch, name, kind, **timing):
    """Crop a piece to its ink, save it, and remember where it goes."""
    box = ink_box(image)
    if box is None:
        return None
    path = os.path.join(scratch, name)
    image.crop(box).save(path)
    return Layer(kind=kind, path=path, x=x + box[0], y=y + box[1],
                 rect=(x + box[0], y + box[1], x + box[2], y + box[3]), **timing)


def _place_card(block_h, default_cy, top_limit, bottom_limit, face):
    """Top edge for the opening card. It sits at its usual height unless that would cover the
    face; then below the chin if there is room, above the head if not, and where it was (with a
    note) when neither fits. `face` is (centre, height) as shares of the frame's height."""
    top = int(min(max(default_cy - block_h / 2.0, top_limit), bottom_limit - block_h))
    if not face:
        return top, ""
    centre, height = face
    pad = HEAD_CLEARANCE * CANVAS_H
    crown, chin = centre * CANVAS_H - height * CANVAS_H / 2.0 - pad, centre * CANVAS_H + height * CANVAS_H / 2.0 + pad
    if top + block_h <= crown or top >= chin:
        return top, ""
    if chin + block_h <= bottom_limit:
        return int(chin), ""
    if crown - block_h >= top_limit:
        return int(crown - block_h), ""
    return top, "The opening text may sit over the face in this version. Watch it before using it."


def compose(look, fmt, scratch, on_screen_text="", lower_third="", disclaimer="", need_disclaimer=False,
            preview_for=None, lines=(), duration=0.0, joins=(), face=None, hook_hold=HOOK_HOLD):
    """Draw every overlay for ONE version into `scratch` and return the OverlaySet.

    `need_disclaimer` comes from the clip's gate. When it is true and there is no disclaimer text,
    this raises: there is no way to get a set of overlays for such a clip without its band.
    `preview_for` is None for a version meant for posting, and the name of the person whose
    sign-off is awaited (or "") for a preview; a preview always carries the PREVIEW stamp."""
    from PIL import Image
    if fmt not in FORMATS:
        raise OverlayError("A version is either full frame ('fullbleed') or 'square', not '%s'." % fmt)
    if need_disclaimer and not (disclaimer or "").strip():
        raise OverlayError("This clip is on HOLD, which means it may only be shown with the brand's disclaimer on "
                           "screen, and there is no disclaimer text. Add one in the brand's settings. Nothing was made.")
    box_l, box_t, box_r, box_b = design_box()
    col_l, col_r = text_column()
    out = OverlaySet(format=fmt, video_rect=(0, 0, CANVAS_W, CANVAS_H), canvas_colour=look.canvas_bg,
                     notes=list(look.notes))
    text = " ".join((on_screen_text or "").split())
    credit = " ".join((lower_third or "").split())
    band_img = band_facts = None
    if need_disclaimer:
        band_img, band_facts = disclaimer_band(look, disclaimer)
    tag_img = third_tag(look, credit) if credit else None
    want_captions = bool(lines)

    if fmt == "fullbleed":
        band_top = box_b - band_img.height if band_img else box_b
        cap_top = int(FB_CAPTION_CY - CAPTION_STRIP_H / 2)
        if band_img:
            cap_top = min(cap_top, band_top - GAP - CAPTION_STRIP_H)
        floor_for_card = (cap_top - GAP) if want_captions else (band_top - GAP)
        parts, top, note = [], 0, ""
        for largest in (HOOK_SIZES[0], 84, 72, HOOK_SIZES[1]):     # a card that would cover the face is tried smaller
            card = hook_card(look, text, largest) if text else None
            parts = [p for p in (card, tag_img) if p is not None]
            if not parts:
                break
            block_h = sum(p.height for p in parts) + 16 * (len(parts) - 1)
            top, note = _place_card(block_h, FB_HOOK_CY, box_t, floor_for_card, face)
            if not note or not text:
                break
        if parts:
            if note:
                out.notes.append(note)
            sheet = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
            y = top
            for p in parts:
                sheet.alpha_composite(p, ((CANVAS_W - p.width) // 2, y))
                y += p.height + 16
            out.layers.append(_save(sheet, 0, 0, scratch, "opening.png", "hook", start=0.0,
                                    end=min(hook_hold, max(1.0, duration - 0.2)), fade=HOOK_FADE))
    else:
        head_img = heading(look, text) if text else None
        top = box_t
        video_top = top + (head_img.height + 28 if head_img else 0)
        below = (GAP + CAPTION_STRIP_H if want_captions else 0) + (GAP + band_img.height if band_img else 0)
        side = min(SQUARE_SIDE, box_b - below - video_top)
        side -= side % 2
        if side < SQUARE_SIDE_MIN:
            raise OverlayError("There is not enough room for the picture in a square version once the on-screen "
                               "text, captions and disclaimer are in. Shorten the disclaimer or the on-screen text.")
        spare = box_b - (video_top + side + below)
        shift = max(0, spare // 2)                                  # centre the whole stack in the clear area
        video_top += shift
        out.video_rect = ((CANVAS_W - side) // 2, video_top, side, side)
        sheet = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        if head_img:
            sheet.alpha_composite(head_img, ((CANVAS_W - head_img.width) // 2, top + shift))
        if tag_img:
            sheet.alpha_composite(tag_img, ((CANVAS_W - tag_img.width) // 2, video_top + side - tag_img.height - 18))
        under = _save(sheet, 0, 0, scratch, "furniture.png", "under")
        if under:
            out.layers.append(under)
        cap_top = video_top + side + GAP
        band_top = cap_top + (CAPTION_STRIP_H + GAP if want_captions else 0)

    if want_captions:
        states = caption_timeline(lines, duration, joins)
        blank = os.path.join(scratch, "c-blank.png")
        Image.new("RGBA", (CANVAS_W, CAPTION_STRIP_H), (0, 0, 0, 0)).save(blank)
        widest = None
        listing = ["ffconcat version 1.0"]
        drawn = {}
        for start, end, index, active in states:
            name = "c-blank.png"
            if index is not None:
                name = "c-%04d-%d.png" % (index, active)
                if name not in drawn:
                    strip = caption_strip(look, [caption_token(w["word"]) for w in lines[index]["words"]], active)
                    strip.save(os.path.join(scratch, name))
                    ink = ink_box(strip)
                    drawn[name] = ink
                    if ink and (widest is None or ink[2] - ink[0] > widest[2] - widest[0]):
                        widest = ink
            listing += ["file '%s'" % name, "duration %.3f" % (end - start)]
        listing.append("file 'c-blank.png'")        # the list format ignores the last length unless a file follows it
        path = os.path.join(scratch, "captions.txt")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(listing) + "\n")
        ink = widest or (col_l, 8, col_r, CAPTION_STRIP_H - 8)
        out.layers.append(Layer(kind="captions", path=path, x=0, y=cap_top,
                                rect=(ink[0], cap_top + ink[1], ink[2], cap_top + ink[3])))
        out.caption_lines = len(lines)

    if band_img:
        layer = _save(band_img, (CANVAS_W - band_img.width) // 2, band_top, scratch, "disclaimer.png", "disclaimer")
        out.layers.append(layer)
        out.disclaimer = dict(band_facts, rect=list(layer.rect), clear_on=clear_on(layer.rect))

    if preview_for is not None:
        stamp = preview_stamp(look, preview_for)
        centre_y = 640 if fmt == "fullbleed" else out.video_rect[1] + out.video_rect[3] // 2 - 40
        card = out.layer("hook")
        if card is not None:
            # Whoever signs the clip off has to be able to read the opening text, so the stamp sits
            # above it whenever there is room to.
            centre_y = max(box_t + stamp.height / 2.0, min(centre_y, card.rect[1] - GAP - stamp.height / 2.0))
        out.layers.append(_save(stamp, (CANVAS_W - stamp.width) // 2, int(centre_y - stamp.height / 2), scratch,
                                "preview.png", "preview"))

    out.layers = [layer for layer in out.layers if layer is not None]
    _check_placement(out, (box_l, box_t, box_r, box_b))
    if need_disclaimer and out.layer("disclaimer") is None:
        raise OverlayError("The disclaimer could not be drawn, so nothing was made.")
    return out


def _check_placement(overlays, box):
    """Measured, not assumed: every piece inside the clear area, no piece on top of another. The
    PREVIEW stamp is meant to lie across the picture, so it is only kept off the captions and the
    disclaimer."""
    names = {"under": "the heading and credit line", "hook": "the opening text", "captions": "the captions",
             "disclaimer": "the disclaimer", "preview": "the PREVIEW stamp"}
    for layer in overlays.layers:
        r = layer.rect
        if r[0] < box[0] - 2 or r[1] < box[1] - 2 or r[2] > box[2] + 2 or r[3] > box[3] + 2:
            raise OverlayError("On-screen text would sit under an app's own buttons (%s reaches %s, the clear area "
                               "is %s). Shorten the text; the clear area belongs to the apps and cannot be widened."
                               % (names[layer.kind], list(r), list(box)))
    for i, a in enumerate(overlays.layers):
        for b in overlays.layers[i + 1:]:
            kinds = {a.kind, b.kind}
            if "preview" in kinds and kinds & {"hook", "under"}:
                continue                                           # the stamp is meant to lie across the picture
            if _overlaps(a.rect, b.rect):
                raise OverlayError("Two pieces of on-screen text would land on top of each other (%s and %s). "
                                   "Shorten the on-screen text or the disclaimer." % (names[a.kind], names[b.kind]))


# ----------------------------------------------------------------------------- is the band in the picture?
def band_present(frame, facts):
    """(True or False, why) for ONE finished frame, given the band's facts from the variant log.

    `frame` is the whole frame as an image. Four things must all be true at the band's rectangle:
    a light line runs round its edge, just inside that line it is the plate's colour all the way
    round, most of it is the plate's colour, and some of it, but not most of it, is the colour of
    the writing. Footage, a caption on its own plate, or a brand's dark frame can each look like
    one or two of those. None of them puts a light outline with a dark plate and light writing
    inside it at exactly this spot, and a band that is missing, half covered or blank fails."""
    import numpy as np
    x0, y0, x1, y1 = [int(v) for v in facts["rect"]]
    if x1 - x0 < 80 or y1 - y0 < 40 or x1 > frame.width or y1 > frame.height:
        return False, "the disclaimer's place on the frame could not be read"
    region = np.asarray(frame.convert("RGB").crop((x0, y0, x1, y1)), dtype="int16")
    plate = np.array(_rgba(facts.get("plate", DISCLAIMER_PLATE))[:3], dtype="int16")
    is_plate = (np.abs(region - plate).max(axis=2) <= 24)
    light = region.min(axis=2)
    h, w = is_plate.shape
    cut, line = 28, int(facts.get("keyline", DISCLAIMER_KEYLINE)) + 1       # skip the rounded corners
    outline = np.concatenate([light[0:line, cut:w - cut].max(axis=0), light[h - line:h, cut:w - cut].max(axis=0),
                              light[cut:h - cut, 0:line].max(axis=1), light[cut:h - cut, w - line:w].max(axis=1)])
    if outline.size == 0 or (outline >= 140).mean() < 0.85:
        return False, "the disclaimer's outline is not there"
    a, b = line + 3, line + 7                                       # a few pixels in from the light line
    ring = np.concatenate([is_plate[a:b, cut:w - cut].ravel(), is_plate[h - b:h - a, cut:w - cut].ravel(),
                           is_plate[cut:h - cut, a:b].ravel(), is_plate[cut:h - cut, w - b:w - a].ravel()])
    if ring.size == 0 or ring.mean() < 0.9:
        return False, "the plate behind the disclaimer is not there"
    if is_plate.mean() < 0.45:
        return False, "most of the disclaimer's plate is covered"
    share = (light[line + 8:h - line - 8, line + 8:w - line - 8] >= 165).mean()
    if share < 0.015:
        return False, "the plate is there but the words are not"
    if share > 0.5:
        return False, "the disclaimer's place is filled with something else"
    return True, ""


def check_words(text, low=3, high=7):
    """On-screen text is 3 to 7 words. Returns "" or the plain reason it will not be drawn."""
    n = len([t for t in (norm_token(p) for p in (text or "").split()) if t])
    if n == 0:
        return "The clip report has no on-screen text, so none was drawn."
    if not low <= n <= high:
        return ("The on-screen text is %d word%s; a card holds %d to %d, so it was left off. Fix it in the cut list "
                "and cut the clip again." % (n, "" if n == 1 else "s", low, high))
    return ""
