"""pdf.py - a set of slide pictures as ONE multi-page PDF.

Some networks show an uploaded document as a swipeable carousel in the feed, one page per
card, and that document format tends to travel further there than a set of loose pictures.
This turns the slides a carousel produced into that document: one picture per page, in order,
at the pictures' own pixel size.

Uses the imaging library only (no browser, no other program). `dpi` is a label written into
the file; the pictures are embedded as they are, not rescaled.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from smf.brands import replace_patiently


class PdfError(Exception):
    """The document could not be made. Worded for the person."""


def natural_key(path):
    """Sort key that reads numbers as numbers, so slide-2 comes before slide-10."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", Path(path).name)]


def images_to_pdf(image_paths, out_path, dpi=150):
    """Write `image_paths`, in the order given, as the pages of one PDF. Returns
    (out_path, notes): `notes` is a list of plain sentences worth showing the person."""
    from PIL import Image

    paths = [Path(p) for p in (image_paths or [])]
    if not paths:
        raise PdfError("There are no pictures to put in the document.")
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise PdfError("These pictures were not found, so no document was made: %s" % ", ".join(missing))
    if not isinstance(dpi, (int, float)) or dpi <= 0:
        raise PdfError("The document's resolution has to be a number above zero.")

    pages, sizes, notes = [], set(), []
    for p in paths:
        try:
            with Image.open(p) as im:
                im.load()                        # a damaged file fails here, with its name, not while saving
                page = im.convert("RGB")         # a PDF page has no transparency
        except Exception:
            raise PdfError("'%s' could not be read as a picture, so no document was made." % p.name)
        sizes.add(page.size)
        pages.append(page)
    if len(sizes) > 1:
        notes.append("The pictures are not all the same size (%s). The document was still made, but pages of "
                     "different shapes can be cropped or boxed in when it is shown as a carousel."
                     % ", ".join("%dx%d" % s for s in sorted(sizes)))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".pdf", dir=str(out_path.parent))
    os.close(fd)
    try:
        pages[0].save(tmp, "PDF", save_all=True, append_images=pages[1:], resolution=float(dpi))
        replace_patiently(tmp, str(out_path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out_path, notes
