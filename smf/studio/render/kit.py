"""kit.py - everything a picture needs to know about ONE brand.

A Kit is resolved from a Brand and from nothing else: its colours, the name stamped in the
corner, the footer line, its fonts, its logo, and the small round picture used beside a name.
There is no built-in brand here. A brand that chose three colours and nothing more gets a
complete kit, because every missing piece is either mixed from those three colours or is one
of the open-licence fonts that ship inside this folder.

    kit = resolve(brand)
    kit.palette("bold")          colours for one kind of background
    kit.font_face_css()          @font-face rules that point at files on THIS computer
    kit.notes                    plain sentences for the render report (for example a named
                                 font that was not found)

FONTS
Three families ship with the Factory (licence text beside each, see fonts/): a sans for
headlines, body and big numbers, a mono for small labels, and a condensed poster face for bold
text cards. Where each file came from, with its checksum, is recorded in BINARIES.lock. A brand can use its own: drop the files into Brand/brand-kit/fonts/ and name the family
(or one exact file) in brand-master.json under visual.fonts, for the roles `display`, `body`,
`mono` and `poster`. A named font that is not in that folder is never looked for anywhere
else, never downloaded: the built-in face is used and the report says so.

Inside the page every role gets a private family name (smf-display, smf-body, ...), so a font
with the same name that happens to be installed on the computer can never be picked instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from smf.brands import Brand, BrandError, contrast, mix

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
FONT_EXTENSIONS = (".ttf", ".otf", ".woff2", ".woff")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
LOGO_EXTENSIONS = IMAGE_EXTENSIONS + (".svg",)
ROLES = ("display", "body", "mono", "poster")
GROUNDS = ("main", "soft", "bold", "accent", "black")

# The fonts that ship in this folder. `weight` is what the file can draw: a range for a
# variable font, a single number for a static one.
BUNDLED = {
    "inter": {"family": "Inter", "file": "inter/Inter-Variable.ttf", "weight": "100 900"},
    "geistmono": {"family": "Geist Mono", "file": "geist-mono/GeistMono-Variable.ttf", "weight": "100 900"},
    "anton": {"family": "Anton", "file": "anton/Anton-Regular.ttf", "weight": "400"},
}
ROLE_BUILT_IN = {"display": "inter", "body": "inter", "mono": "geistmono", "poster": "anton"}

_WEIGHT_WORDS = [            # longest first, so "extrabold" is not read as "bold"
    ("extralight", 200), ("ultralight", 200), ("extrabold", 800), ("ultrabold", 800),
    ("semibold", 600), ("demibold", 600), ("hairline", 100), ("regular", 400), ("medium", 500),
    ("black", 900), ("heavy", 900), ("light", 300), ("thin", 100), ("book", 400), ("bold", 700),
]


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


@dataclass
class FontFace:
    role: str               # display | body | mono | poster
    path: Path
    weight: str = "400"     # "400" or "100 900"
    style: str = "normal"
    origin: str = "built-in"    # built-in | brand

    @property
    def css_family(self):
        return "smf-" + self.role

    def css(self):
        fmt = {".ttf": "truetype", ".otf": "opentype", ".woff2": "woff2", ".woff": "woff"}[self.path.suffix.lower()]
        return ('@font-face{font-family:"%s";src:url("%s") format("%s");font-weight:%s;font-style:%s;'
                'font-display:block;}' % (self.css_family, self.path.as_uri(), fmt, self.weight, self.style))


@dataclass
class Kit:
    brand_id: str
    brand_name: str
    colours: dict
    wordmark: str
    handle: str
    faces: list = field(default_factory=list)
    logo: Path | None = None
    photos_dir: Path | None = None
    notes: list = field(default_factory=list)

    # ---------------------------------------------------------------- fonts
    def font_face_css(self):
        return "\n".join(f.css() for f in self.faces)

    def font_files(self):
        return [f.path for f in self.faces]

    # ---------------------------------------------------------------- colours
    def is_dark(self):
        """True when the brand's own background is darker than its headline colour: navy and
        gold, not cream and brown. Worked out from the brand's colours, never stored."""
        c = self.colours
        return contrast(c["ground"], "#FFFFFF") > contrast(c["ground"], "#000000")

    def strong(self):
        """The background for a slide meant to stand out (a cover, a closing slide).

        For a light brand that is "bold": the headline colour as the background, which turns a
        cream brand's dark brown into a strong dark slide. For a dark brand the same rule would
        give a WHITE slide and push its accent toward mud, so it gets "soft" instead: its own
        dark surface, with its accent still reading. Asking for "bold" by name still gets bold.
        Use this, not "bold", wherever a default background is chosen (clip cards included)."""
        return "soft" if self.is_dark() else "bold"

    def palette(self, ground="main"):
        """Every colour one slide needs, for one kind of background.

        main    the brand's own background            soft    its slightly tinted surface
        bold    the headline colour as background     accent  the accent colour as background
        black   pure black, for maximum-contrast text cards

        Accent colours are checked against the background they will sit on and nudged toward
        the readable end of the brand's own palette when they would be hard to see, so three
        colours chosen by a person always produce legible cards."""
        c = self.colours
        if ground not in GROUNDS:
            raise ValueError("a background is one of: %s" % ", ".join(GROUNDS))
        if ground in ("main", "soft"):
            bg = c["ground"] if ground == "main" else c["surface"]
            head, body, muted, rule = c["ink"], c["text"], c["muted"], c["rule"]
            panel = c["surface"] if ground == "main" else c["ground"]
            number = c["accent2"]
        elif ground == "bold":
            bg, head = c["ink"], c["ground"]
            body, muted = mix(c["ink"], c["ground"], 0.80), mix(c["ink"], c["ground"], 0.58)
            rule, panel, number = mix(c["ink"], c["ground"], 0.18), mix(c["ink"], c["ground"], 0.09), c["accent"]
        elif ground == "accent":
            bg = c["accent"]
            head = best_on(bg, [c["ink"], c["ground"]])
            body, muted = mix(bg, head, 0.88), mix(bg, head, 0.70)
            rule, panel = mix(bg, head, 0.22), mix(bg, head, 0.10)
            number = head
        else:
            bg, head = "#000000", "#FFFFFF"
            body, muted, rule, panel, number = "#E8E8E8", "#A3A3A3", "#2A2A2A", "#141414", c["accent"]
        poles = [head, "#FFFFFF" if contrast(bg, "#FFFFFF") >= contrast(bg, "#000000") else "#000000"]
        accent, pill_bg = c["accent"], ensure_contrast(c["accent"], bg, 3.0, poles)
        if ground == "accent":
            # The accent cannot highlight anything on itself. The highlight becomes the brand
            # colour from the opposite end to the headline (light headline, dark highlight).
            far = "#FFFFFF" if contrast(head, "#FFFFFF") > contrast(head, "#000000") else "#000000"
            accent = max((c["ground"], c["ink"]), key=lambda col: contrast(head, col))
            poles, pill_bg = [far], head
        return {
            # Grey text carries the source line and the footer line, so it is held to the same
            # 4.5 to 1 as any small text.
            "bg": bg, "head": head, "body": body, "muted": ensure_contrast(muted, bg, 4.5, poles),
            "rule": rule, "panel": panel,
            "accent": ensure_contrast(accent, bg, 3.0, poles),          # large type and shapes
            "accent_small": ensure_contrast(accent, bg, 4.5, poles),    # small labels
            "number": ensure_contrast(number, bg, 3.0, poles),
            "pill_bg": pill_bg, "pill_fg": best_on(pill_bg, [c["ink"], c["ground"]], 3.0),
            "faint": mix(bg, head, 0.07), "dot_off": mix(bg, head, 0.26),
            "second": c["accent2"], "second_fg": best_on(c["accent2"], [c["ground"], c["ink"]], 3.0),
        }

    # ---------------------------------------------------------------- the small round picture
    def avatar(self, brand, identity_id, requested=""):
        """The picture beside a name: the brand's OWN photo when it supplied one, otherwise
        None (the caller then draws a plain initial in a circle).

        A photo is only ever used when it is unmistakably meant for this identity: either the
        spec names a file, or the brand saved one as Brand/brand-kit/photos/avatar-<identity>.
        Any other photo in the folder is left alone; guessing which face belongs beside which
        name is how the wrong person ends up on a post."""
        brand.identity(identity_id)
        photos = self.photos_dir
        if requested:
            wanted = Path(requested)
            path = wanted if wanted.is_absolute() else Path(brand.home) / wanted
            if photos is None or not _inside(path, photos):
                raise BrandError("the picture '%s' is not in %s's own photos folder (Brand/brand-kit/photos). "
                                 "Only a brand's own photos can be used on its posts." % (requested, self.brand_name))
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                raise BrandError("the picture '%s' was not found, or is not a PNG, JPG or WebP file." % requested)
            return path
        if photos is not None and photos.is_dir():
            for ext in IMAGE_EXTENSIONS:
                candidate = photos / ("avatar-%s%s" % (identity_id, ext))
                if candidate.is_file():
                    return candidate
        return None


# ----------------------------------------------------------------------------- colour helpers
def best_on(bg, candidates, minimum=4.5):
    """The most readable text colour for a background: the brand's own colours first, and
    plain black or white only when neither of those can be read. `minimum` is 4.5 for
    ordinary text and 3.0 for large bold type (a button, a letter in a circle)."""
    ranked = sorted(candidates, key=lambda col: contrast(bg, col), reverse=True)
    if contrast(bg, ranked[0]) >= minimum:
        return ranked[0]
    return max(list(candidates) + ["#000000", "#FFFFFF"], key=lambda col: contrast(bg, col))


def ensure_contrast(colour, bg, target, poles):
    """Return `colour`, moved just far enough toward the most readable pole to reach `target`
    contrast against `bg`. A colour that already passes comes back unchanged."""
    if contrast(colour, bg) >= target:
        return colour
    pole = max(poles, key=lambda p: contrast(p, bg))
    for step in range(1, 21):
        candidate = mix(colour, pole, step / 20.0)
        if contrast(candidate, bg) >= target:
            return candidate
    # A mid-tone background can be out of reach from that side. Being readable matters more
    # than being a different colour from the headline, so take the most readable end there is.
    return max(list(poles) + ["#000000", "#FFFFFF"], key=lambda p: contrast(p, bg))


def initials(display_name, kind="person"):
    """One or two letters for the circle beside a name. Works with accents and with names
    that start with a symbol; never returns an empty string."""
    words = [w for w in re.split(r"[\s\-_/&+.,]+", display_name or "") if any(ch.isalnum() for ch in w)]
    letters = [next(ch for ch in w if ch.isalnum()).upper() for w in words]
    if not letters:
        return "?"
    if kind == "person" and len(letters) > 1:
        return letters[0] + letters[-1]
    return letters[0]


# ----------------------------------------------------------------------------- fonts
def _inside(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except (ValueError, OSError):
        return False


def _describe_font_file(path):
    """(family, weight, style) for one font file. Reads the names stored inside the file when
    the imaging library can open it, and falls back to the file name when it cannot."""
    family, weight, style = "", "400", "normal"
    stem = path.stem
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(path), 40)
        family, sub = font.getname()
        label = _norm(sub or "")
        try:
            axes = font.get_variation_axes()
        except Exception:
            axes = []
        for axis in axes:
            name = axis.get("name", b"")
            name = name.decode("utf-8", "ignore") if isinstance(name, bytes) else str(name)
            if name.lower() in ("weight", "wght"):
                weight = "%d %d" % (int(axis["minimum"]), int(axis["maximum"]))
                label = ""
    except Exception:
        label = _norm(stem)
        family = ""
    text = label or _norm(stem)
    if "italic" in text or "oblique" in text:
        style = "italic"
    if " " not in weight:
        for word, value in _WEIGHT_WORDS:
            if word in text:
                weight = str(value)
                break
    return family or stem, weight, style


def _brand_faces(role, wanted, fonts_dir):
    """Font files in the brand's own fonts folder that match what it named, as FontFace rows."""
    if not fonts_dir.is_dir():
        return []
    files = sorted(p for p in fonts_dir.iterdir() if p.is_file() and p.suffix.lower() in FONT_EXTENSIONS)
    if Path(wanted).suffix.lower() in FONT_EXTENSIONS:              # one exact file was named
        exact = [p for p in files if p.name.lower() == Path(wanted).name.lower()]
        # a single named file draws every weight the cards ask for, so nothing is faked
        return [FontFace(role, exact[0], "100 900", "normal", "brand")] if exact else []
    key = _norm(wanted)
    faces, seen = [], set()
    for p in files:
        family, weight, style = _describe_font_file(p)
        if _norm(family) != key and not _norm(p.stem).startswith(key):
            continue
        if (weight, style) in seen:
            continue
        seen.add((weight, style))
        faces.append(FontFace(role, p, weight, style, "brand"))
    if len(faces) == 1 and " " not in faces[0].weight:
        faces[0].weight = "100 900"                                   # the only file there is: use it throughout
    return faces


def _built_in_face(role, key=None):
    spec = BUNDLED[key or ROLE_BUILT_IN[role]]
    path = FONTS_DIR / spec["file"]
    if not path.is_file():
        raise BrandError("a font that ships with the Factory is missing (%s). Download the Factory again, "
                         "or ask Claude to restore the fonts folder." % spec["file"])
    return FontFace(role, path, spec["weight"], "normal", "built-in")


def resolve_fonts(brand):
    """(faces, notes) for a brand. Never raises for a font the brand named but did not supply."""
    named = (brand.data.get("visual") or {}).get("fonts") or {}
    fonts_dir = Path(brand.kit_dir) / "fonts"
    faces, notes = [], []
    for role in ROLES:
        wanted = str(named.get(role) or "").strip()
        if not wanted:
            faces.append(_built_in_face(role))
            continue
        if _norm(wanted) in BUNDLED:
            faces.append(_built_in_face(role, _norm(wanted)))
            continue
        own = _brand_faces(role, wanted, fonts_dir)
        if own:
            faces.extend(own)
            continue
        fallback = BUNDLED[ROLE_BUILT_IN[role]]["family"]
        notes.append("The font '%s' (for %s text) was not found in this brand's Brand/brand-kit/fonts folder, "
                     "so the built-in %s was used instead. Nothing was downloaded."
                     % (wanted, {"display": "headline", "body": "body", "mono": "label",
                                 "poster": "poster"}[role], fallback))
        faces.append(_built_in_face(role))
    return faces, notes


# ----------------------------------------------------------------------------- the resolver
def resolve(brand):
    """Build the Kit for one brand. The brand is required; there is nothing to fall back to."""
    if not isinstance(brand, Brand):
        raise BrandError("no brand was given to the picture maker. Say which brand these pictures are for.")
    visual = brand.data.get("visual") or {}
    colours = visual.get("colors") or {}
    missing = [k for k in ("ground", "ink", "accent") if not colours.get(k)]
    if missing:
        raise BrandError("%s has not chosen its colours yet (missing: %s). Pick a background, a headline colour "
                         "and an accent colour in onboarding first." % (brand.name, ", ".join(missing)))
    wordmark = str(visual.get("wordmark") or "").strip()
    if not wordmark:
        raise BrandError("%s has no wordmark yet: the name stamped on every picture. Add it in onboarding." % brand.name)

    faces, notes = resolve_fonts(brand)
    kit = Kit(brand_id=brand.id, brand_name=brand.name, colours=brand.colours, wordmark=wordmark,
              handle=str(visual.get("handle") or "").strip(), faces=faces, notes=notes,
              photos_dir=Path(brand.kit_dir) / "photos")

    logo = str(visual.get("logo") or "").strip()
    if logo:
        path = Path(logo) if Path(logo).is_absolute() else Path(brand.home) / logo
        if not _inside(path, brand.home):
            kit.notes.append("The logo file is outside this brand's folder, so it was not used. "
                             "Put it in Brand/brand-kit/logos and the name is used until then.")
        elif not path.is_file() or path.suffix.lower() not in LOGO_EXTENSIONS:
            kit.notes.append("The logo file '%s' was not found (or is not a PNG, JPG, WebP or SVG), "
                             "so the brand name is shown as text instead." % logo)
        else:
            kit.logo = path
    return kit
