"""library.py - what a brand keeps for its pictures: its images, and the looks it chose to keep.

Both live in the brand's own kit folder, so they travel with the brand and never mix with
another brand's.

IMAGES      Brand/brand-kit/photos/            the brand's own photos, exactly as before
            Brand/brand-kit/photos/stock/      photos from a free stock site, filed here
            Brand/brand-kit/photos/generated/  images made for the brand by an image model

Every image that is not the brand's own has a small record beside it (`<file>.source.json`):
where it came from (the page it was downloaded from, or the request that made it), its licence
in a sentence, the date, and whether it shows a person. A file with no record is the brand's
own. The record is what lets a later session, the render report and the person tell a stock
loaf from the bakery's own loaf.

LOOKS       Brand/brand-kit/looks/<name>/      a free design the person asked to keep
                design.json   the whole design, exactly as it was drawn
                sample.png    its first picture, small
                about.txt     one line saying what it is

A look is a saved design, not a fill-in form. To use it again the designer writes the new words
into it, and the result goes through every check again like any free design.

Nothing here reaches the internet, and nothing is ever overwritten: a name already in use gets
a number added.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from smf.brands import BrandError, replace_patiently
from smf.studio.render.kit import IMAGE_EXTENSIONS, _inside

SOURCES = ("own", "stock", "generated")
SUBFOLDER = {"own": "", "stock": "stock", "generated": "generated"}
SPOKEN = {"own": "the brand's own photo", "stock": "a stock photo", "generated": "a generated image"}
MAX_IMAGE_BYTES = 40 * 1024 * 1024
RECORD_SUFFIX = ".source.json"
DESIGN_SUFFIX = "-design.json"


def _slug(text, fallback="picture"):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:48] or fallback


def _write_json(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(Path(path).parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    replace_patiently(tmp, str(path))


def _free_name(folder, stem, suffix):
    """A name in `folder` that is not taken: stem.suffix, stem-2.suffix, ..."""
    candidate, n = folder / (stem + suffix), 1
    while candidate.exists():
        n += 1
        candidate = folder / ("%s-%d%s" % (stem, n, suffix))
    return candidate


# ----------------------------------------------------------------------------- images
def photos_dir(brand):
    return Path(brand.kit_dir) / "photos"


def brand_image(brand, rel):
    """The file for an image named from the brand's folder, or a BrandError in plain words.
    Only ordinary image files inside the brand kit's photos folder are ever used."""
    text = str(rel or "").strip()
    if not text:
        raise BrandError("no picture was named")
    if "://" in text or text.lower().startswith(("data:", "//")):
        raise BrandError("'%s' is a web address. Save the picture into %s's brand kit photos folder first; "
                         "pictures are never fetched while drawing" % (text[:60], brand.name))
    wanted = Path(text)
    path = wanted if wanted.is_absolute() else Path(brand.home) / wanted
    if not _inside(path, photos_dir(brand)):
        raise BrandError("the picture '%s' is not in %s's own photos folder (Brand/brand-kit/photos). Only a "
                         "brand's own folder is used for its pictures" % (text, brand.name))
    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise BrandError("the picture '%s' was not found, or is not a PNG, JPG or WebP file" % text)
    return path


def read_record(path):
    """Where an image came from. A file with no record beside it is the brand's own."""
    record = {"source": "own", "from": "", "licence": "", "date": "", "shows_person": None}
    try:
        with open(str(path) + RECORD_SUFFIX, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            record.update(saved)
    except (OSError, ValueError):
        pass
    if record.get("source") not in SOURCES:
        record["source"] = "own"
    return record


def file_image(brand, source_file, source, where_from="", licence="", shows_person=None, name=None, extra=None):
    """Copy an image into the brand's photos folder and write its record. Returns the path
    relative to the brand's folder, which is how a design names it (brand:<that path>)."""
    if source not in SOURCES:
        raise BrandError("an image is one of: %s" % ", ".join(SOURCES))
    src = Path(source_file)
    if not src.is_file() or src.suffix.lower() not in IMAGE_EXTENSIONS:
        raise BrandError("'%s' was not found, or is not a PNG, JPG or WebP file" % src.name)
    if src.stat().st_size > MAX_IMAGE_BYTES:
        raise BrandError("'%s' is very large (over 40 MB). Save a smaller copy and file that" % src.name)
    if source != "own" and not str(where_from or "").strip():
        raise BrandError("say where this picture came from (the page it was downloaded from), so it is never "
                         "mistaken for the brand's own")
    folder = photos_dir(brand) / SUBFOLDER[source]
    folder.mkdir(parents=True, exist_ok=True)
    dest = _free_name(folder, _slug(name or src.stem), src.suffix.lower())
    shutil.copyfile(str(src), str(dest))
    if source != "own":
        record = {"source": source, "from": str(where_from).strip(), "licence": str(licence or "").strip(),
                  "date": time.strftime("%Y-%m-%d"), "shows_person": shows_person}
        record.update(extra or {})
        _write_json(str(dest) + RECORD_SUFFIX, record)
    return os.path.relpath(str(dest), brand.home).replace(os.sep, "/")


def list_images(brand):
    """Every image in the brand's photos folder with where it came from, own photos first."""
    root = photos_dir(brand)
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            record = read_record(path)
            rows.append({"image": os.path.relpath(str(path), brand.home).replace(os.sep, "/"),
                         "source": record["source"], "from": record.get("from") or "",
                         "shows_person": record.get("shows_person")})
    return sorted(rows, key=lambda r: (SOURCES.index(r["source"]), r["image"]))


# ----------------------------------------------------------------------------- designs and looks
def looks_dir(brand):
    return Path(brand.kit_dir) / "looks"


def _pictures_beside(design_path):
    """The pictures a design file was saved with, in order."""
    design_path = Path(design_path)
    stem = design_path.name[:-len(DESIGN_SUFFIX)]
    return sorted(p for p in design_path.parent.glob(stem + "-*.png"))


def _read_design(path):
    try:
        with open(str(path), "r", encoding="utf-8-sig") as f:
            design = json.load(f)
    except (OSError, ValueError):
        raise BrandError("the design file '%s' could not be read" % Path(path).name)
    if not isinstance(design, dict) or design.get("format") != "free":
        raise BrandError("'%s' is not a free design" % Path(path).name)
    return design


def recent_designs(brand, identity=None, limit=3):
    """The brand's most recently drawn free designs, newest first: what "the same as last time"
    means, and what a new design is compared with so the same look is not repeated unnoticed."""
    root = Path(brand.path("Output", "visuals"))
    found = []
    if root.is_dir():
        for path in root.rglob("*" + DESIGN_SUFFIX):
            try:
                design = _read_design(path)
            except BrandError:
                continue
            if identity and design.get("identity") != identity:
                continue
            found.append((path.stat().st_mtime, path, design))
    found.sort(key=lambda item: item[0], reverse=True)
    return [{"design": str(path), "identity": design.get("identity"), "name": design.get("name") or "",
             "pictures": [str(p) for p in _pictures_beside(path)],
             "made": time.strftime("%Y-%m-%d %H:%M", time.localtime(made))}
            for made, path, design in found[:max(0, int(limit))]]


def save_look(brand, name, design_path, about=""):
    """Keep a drawn free design as a look this brand can ask for by name. Returns its folder."""
    if not str(name or "").strip():
        raise BrandError("a look needs a name, in the person's own words (for example: gold poster)")
    design_path = Path(design_path)
    if not _inside(design_path, brand.home):
        raise BrandError("that design is not in %s's folder. A look is saved from one of the brand's own designs"
                         % brand.name)
    design = _read_design(design_path)
    root = looks_dir(brand)
    root.mkdir(parents=True, exist_ok=True)
    folder = _free_name(root, _slug(name, "look"), "")
    folder.mkdir()
    _write_json(folder / "design.json", design)
    (folder / "about.txt").write_text((str(about or "").strip() or str(name).strip()) + "\n", encoding="utf-8")
    pictures = _pictures_beside(design_path)
    if pictures:
        try:
            from PIL import Image
            with Image.open(str(pictures[0])) as im:
                small = im.convert("RGB")
                small.thumbnail((360, 640))
                small.save(str(folder / "sample.png"))
        except Exception:
            shutil.copyfile(str(pictures[0]), str(folder / "sample.png"))
    return folder


def list_looks(brand):
    """Every look this brand has kept: [{name, about, design, sample}], by name."""
    root = looks_dir(brand)
    rows = []
    if root.is_dir():
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and (p / "design.json").is_file()):
            try:
                about = (folder / "about.txt").read_text(encoding="utf-8").strip()
            except OSError:
                about = ""
            sample = folder / "sample.png"
            rows.append({"name": folder.name, "about": about, "design": str(folder / "design.json"),
                         "sample": str(sample) if sample.is_file() else ""})
    return rows


def load_look(brand, name):
    """The saved design for one look, or a BrandError naming the looks that exist."""
    wanted = _slug(name, "")
    for row in list_looks(brand):
        if row["name"] == wanted:
            return _read_design(row["design"])
    have = ", ".join(r["name"] for r in list_looks(brand)) or "none yet"
    raise BrandError("%s has no saved look called '%s'. Saved looks: %s" % (brand.name, name, have))
