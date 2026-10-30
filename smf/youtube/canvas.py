"""canvas.py - wide pages (a thumbnail, a slide) drawn by the Factory's one picture renderer.

There is one renderer in the Factory (`smf.studio.render.engine`): it opens one browser for a
batch, draws pages from files on this computer only, refuses and records any request to the
internet, and shrinks marked text until it fits or says which line is too long. It accepts any
page size. The social formats around it are all upright, so their page shell assumes upright
margins; this module is the same shell with margins that suit a 16:9 picture. It reuses the
renderer's stylesheet, its brand kit (colours mixed from the brand's three choices, fonts that
ship with the Factory or that the brand supplied) and its text-fitting marks. Nothing is drawn
here: this only builds the page that the renderer draws.

    THUMBNAIL = (1280, 720)      the size YouTube asks for
    SLIDE     = (1920, 1080)     a full HD frame, so a deck can sit straight on a video timeline
"""
from __future__ import annotations

from pathlib import Path

from smf.studio.render import layout as L
from smf.studio.render.kit import IMAGE_EXTENSIONS
from smf.youtube import YouTubeError, inside_folder

THUMBNAIL = (1280, 720)
SLIDE = (1920, 1080)

EXTRA_CSS = """
.canvas.wide{padding:0;display:block;}
.abs{position:absolute;overflow:hidden;}
.box{display:flex;flex-direction:column;justify-content:center;align-items:flex-start;}
.box.centre{align-items:center;text-align:center;}
.box.bottom{justify-content:flex-end;}
.box.top{justify-content:flex-start;}
.box > *{max-width:100%;}
.poster{font-family:"smf-poster",sans-serif;font-weight:400;text-transform:uppercase;line-height:1.02;
  letter-spacing:.004em;color:var(--head);text-wrap:balance;}
.poster .mark,.h .mark{color:var(--accent);}
.photo{position:absolute;overflow:hidden;background:var(--panel);}
.photo img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;}
"""


def page(kit, palette, size, inner, css=""):
    """A complete wide page. `inner` is positioned by the caller with absolute boxes, because a
    thumbnail's and a slide's parts sit at known places (which is also what lets the small-size
    check know where the words are)."""
    root = ("--w:%dpx;--h:%dpx;--pad-top:0px;--pad-x:0px;--pad-right:0px;--pad-bottom:0px;--foot:0px;"
            "--pager-bottom:0px;"
            % (size[0], size[1]))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>picture</title>'
            '<style>%s\n:root{%s%s}\n%s\n%s\n%s</style></head><body><div class="canvas wide">%s</div></body></html>'
            % (kit.font_face_css(), root, L.palette_style(palette), L.BASE_CSS, EXTRA_CSS, css, inner))


def box(name, rect, inner, cls="box", style=""):
    """An absolutely placed box that fitted text must stay inside. rect = (x, y, width, height)."""
    x, y, w, h = rect
    return ('<div class="abs %s" data-fitbox="%s" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx;%s">%s</div>'
            % (cls, L.esc(name), x, y, w, h, style, inner))


def brand_picture(brand, rel, what="picture", folder=None):
    """A picture the BRAND supplied, as a path, or an error in plain words.

    Only files inside the brand's own folder are ever used (by default, only its photos folder),
    and only ordinary image files. A web address is refused: pictures are never fetched while
    drawing. Stock and generated pictures are filed into that folder first (see
    smf/studio/render/library.py)."""
    text = str(rel or "").strip()
    if not text:
        raise YouTubeError("No %s was named." % what)
    if "://" in text or text.lower().startswith(("data:", "//")):
        raise YouTubeError("'%s' is a web address. Pictures are only ever taken from %s's own folder: save the "
                           "file into its brand kit's photos folder and name it from there." % (text[:60], brand.name))
    allowed = Path(folder) if folder else Path(brand.kit_dir) / "photos"
    wanted = Path(text)
    path = wanted if wanted.is_absolute() else Path(brand.home) / wanted
    if not inside_folder(path, allowed):
        where = "Brand/brand-kit/photos" if folder is None else "its own folder"
        raise YouTubeError("The %s '%s' is not in %s's %s. Only the brand's own pictures can be used."
                           % (what, text, brand.name, where))
    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise YouTubeError("The %s '%s' was not found, or is not a PNG, JPG or WebP file." % (what, text))
    return path
