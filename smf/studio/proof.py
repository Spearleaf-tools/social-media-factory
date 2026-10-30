"""proof.py - the brand's proof library: results, testimonials, screenshots, photos, facts.

Proof is evidence the person adds over time. It is never derived from settings and never
invented. Each item records where it came from and, separately, whether it may be published:

    no           keep it as background; it can inform writing but never appears in a post
    anonymised   it may appear once names, faces and identifying details are removed
    yes          it may appear as it is

THE CONSENT RULE
A file from the proof folder may ride along on a post only when its item says `anonymised` or
`yes`. A file in that folder with no item at all is refused: an unaccounted file never ships.
Images the Factory renders itself (the brand's Output/visuals) are made only from cleared
inputs, so they pass.

    python factory.py proof add  --brand maple-and-main --kind testimonial --title "..." --source "..." --may-publish anonymised
    python factory.py proof list --brand maple-and-main
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import time

from smf import brands

KINDS = ("result", "testimonial", "screenshot", "photo", "fact")
MAY_PUBLISH = ("no", "anonymised", "yes")


def registry_path(brand):
    return brand.path("Studio", "registry.db")


def connect(brand):
    """Open the brand's library, creating it (empty, with its tables) if it is not there yet.
    The example brand ships without one because database files are never part of the repo."""
    path = registry_path(brand)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(brands.REGISTRY_SCHEMA)
    return con


def _next_id(con):
    row = con.execute("SELECT proof_id FROM proof ORDER BY proof_id DESC LIMIT 1").fetchone()
    n = int(row["proof_id"].split("-")[1]) + 1 if row else 1
    return "PRF-%04d" % n


def add(brand, kind, title, detail="", source="", file_path="", may_publish="no", names_third_party=False):
    if kind not in KINDS:
        raise brands.BrandError("a proof item is one of: %s" % ", ".join(KINDS))
    if may_publish not in MAY_PUBLISH:
        raise brands.BrandError("'may publish' is one of: %s" % ", ".join(MAY_PUBLISH))
    if not title.strip():
        raise brands.BrandError("a proof item needs a short title")
    if not source.strip():
        raise brands.BrandError("a proof item needs a source: where it came from (a file, a link, a date, a person). "
                                "Proof with no source is a claim, not proof.")
    if names_third_party and may_publish == "yes":
        raise brands.BrandError("this item names someone else. It can be published anonymised, or kept private. "
                                "To publish it as it is, get their permission first and say so in the source.")
    stored = ""
    if file_path:
        if not os.path.isfile(file_path):
            raise brands.BrandError("that file could not be found")
        proof_dir = brand.path("Inputs", "Proof")
        os.makedirs(proof_dir, exist_ok=True)
        inside = os.path.abspath(file_path).startswith(os.path.abspath(brand.home) + os.sep)
        if inside:
            stored = os.path.relpath(os.path.abspath(file_path), brand.home).replace(os.sep, "/")
        else:
            dst = os.path.join(proof_dir, os.path.basename(file_path))
            n = 1
            while os.path.exists(dst):
                stem, ext = os.path.splitext(os.path.basename(file_path))
                dst = os.path.join(proof_dir, "%s-%d%s" % (stem, n, ext))
                n += 1
            shutil.copy2(file_path, dst)                      # a copy; the original is never moved
            stored = os.path.relpath(dst, brand.home).replace(os.sep, "/")
    con = connect(brand)
    try:
        pid = _next_id(con)
        con.execute("INSERT INTO proof (proof_id, kind, title, detail, source, file_path, may_publish, "
                    "names_third_party, added_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (pid, kind, title.strip(), detail.strip(), source.strip(), stored, may_publish,
                     1 if names_third_party else 0, time.strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()
    finally:
        con.close()
    return pid


def items(brand, publishable_only=False):
    con = connect(brand)
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM proof ORDER BY proof_id")]
    finally:
        con.close()
    if publishable_only:
        rows = [r for r in rows if r["may_publish"] in ("anonymised", "yes")]
    return rows


def media_block_reason(brand, media_path):
    """Why this file may not ride on a post, or None when it is cleared."""
    abs_path = media_path if os.path.isabs(media_path) else brand.path(*media_path.replace("\\", "/").split("/"))
    abs_path = os.path.abspath(abs_path)
    home = os.path.abspath(brand.home) + os.sep
    if not abs_path.startswith(home):
        return "it is outside this brand's folder, so nobody has said it may be published"
    rel = abs_path[len(home):].replace(os.sep, "/")
    if rel.startswith("Output/"):
        return None                                           # made by the Factory from cleared inputs
    if rel.startswith("Brand/brand-kit/"):
        return None                                           # the brand's own logo, photos and marks
    if rel.startswith("Inputs/Proof/"):
        for r in items(brand):
            if r["file_path"] == rel:
                if r["may_publish"] in ("anonymised", "yes"):
                    return None
                return "its proof item (%s) is marked 'do not publish'" % r["proof_id"]
        return "it is in the proof folder but has no proof item saying whether it may be published"
    return None


# ----------------------------------------------------------------------------- verbs
def main(args):
    ap = argparse.ArgumentParser(prog="factory.py proof")
    sub = ap.add_subparsers(dest="action", required=True)
    a_add = sub.add_parser("add")
    a_add.add_argument("--brand", required=True)
    a_add.add_argument("--kind", required=True, choices=KINDS)
    a_add.add_argument("--title", required=True)
    a_add.add_argument("--detail", default="")
    a_add.add_argument("--source", required=True)
    a_add.add_argument("--file", default="")
    a_add.add_argument("--may-publish", default="no", choices=MAY_PUBLISH)
    a_add.add_argument("--names-third-party", action="store_true")
    a_list = sub.add_parser("list")
    a_list.add_argument("--brand", required=True)
    a = ap.parse_args(args)
    try:
        brand = brands.load(a.brand)
        if a.action == "add":
            pid = add(brand, a.kind, a.title, a.detail, a.source, a.file, a.may_publish, a.names_third_party)
            print("Saved as %s (%s)." % (pid, {"no": "kept private", "anonymised": "may be published once anonymised",
                                               "yes": "may be published"}[a.may_publish]))
            return 0
        rows = items(brand)
        if not rows:
            print("No proof yet. That is fine: the Factory simply will not claim results it cannot show.")
            return 0
        for r in rows:
            print("%s  %-11s %-10s %s  [%s]" % (r["proof_id"], r["kind"], r["may_publish"], r["title"], r["source"]))
        return 0
    except brands.BrandError as e:
        print(str(e))
        return 1
