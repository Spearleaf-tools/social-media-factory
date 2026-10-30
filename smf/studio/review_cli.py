"""review_cli.py - the two verbs a person uses after the posts are written.

    python factory.py review --brand maple-and-main                 open the newest batch on the review page
    python factory.py review --brand maple-and-main "week 1.json"   open a named batch (or several)
    python factory.py export --brand maple-and-main                 write approved posts to a ready-to-post folder
    python factory.py export --brand maple-and-main --check         say what would be written, write nothing

The brand is always named. There is no default brand: leave it out and the answer is a list of
the brands that exist. Neither verb sends anything anywhere.
"""
from __future__ import annotations

import argparse
import glob
import os

from smf import brands
from smf.brands import BrandError
from smf.studio.files import StudioError, relative


class _Parser(argparse.ArgumentParser):
    def error(self, message):                             # a sentence, not a usage dump
        raise StudioError("That command was not understood (%s). Ask Claude, or try: python factory.py %s --help"
                          % (message, self.prog.split()[-1]))


def _batches_folder(brand):
    return brand.path("Output", "batches")


def all_batches(brand):
    """Every batch file in the brand's Output/batches/, oldest first. Side files are not batches."""
    folder = _batches_folder(brand)
    if not os.path.isdir(folder):
        return []
    found = [os.path.join(folder, n) for n in os.listdir(folder)
             if n.lower().endswith(".json") and not n.startswith(".")]
    return sorted((p for p in found if os.path.isfile(p)), key=lambda p: (os.path.getmtime(p), p))


def newest_batch(brand):
    found = all_batches(brand)
    if not found:
        raise StudioError("%s has no batches yet. Write some posts first, then open the review page."
                          % brand.name)
    return found[-1]


def resolve_batches(brand, given):
    """Turn what the person typed into real batch files. A bare file name is looked for in the
    brand's own Output/batches/ folder, and a * pattern works even where the shell does not expand it."""
    out = []
    for raw in given:
        tries = [raw, os.path.join(_batches_folder(brand), raw)]
        hits = []
        for t in tries:
            if os.path.isfile(t):
                hits = [t]
                break
            if any(ch in t for ch in "*?["):
                hits = sorted(p for p in glob.glob(t) if os.path.isfile(p))
                if hits:
                    break
        if not hits:
            raise StudioError("No batch called '%s' was found. Batches for %s live in %s."
                              % (raw, brand.name, relative(brand, _batches_folder(brand))))
        for h in hits:
            full = os.path.abspath(h)
            if full not in out:
                out.append(full)
    return out


def _say_where(brand, path):
    """A folder the way the person would find it: from the Factory's own folder when it is inside."""
    try:
        rel = os.path.relpath(path, brands.ROOT)
    except ValueError:                                    # another drive, on Windows
        return path
    return path if rel.startswith("..") else rel


# ----------------------------------------------------------------------------- review
def cli_review(args):
    ap = _Parser(prog="factory.py review", description="Open the review page for one brand's posts.")
    ap.add_argument("--brand", help="the brand's id (required; there is no default brand)")
    ap.add_argument("batches", nargs="*", help="batch files to review together; none = the newest batch")
    ap.add_argument("--port", type=int, default=None, help="a port to prefer; a free one is found if it is taken")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    try:
        a = ap.parse_args(args)
        brand = brands.load(a.brand)                      # no brand named, or an unknown one: a plain BrandError
        paths = resolve_batches(brand, a.batches) if a.batches else [newest_batch(brand)]
        try:
            from smf.studio.review import server
        except ImportError:
            print("The review page needs the Factory's packages, which are not installed yet.\n"
                  "Next step: python factory.py setup")
            return 3
        return server.serve(brand, paths, port=a.port, open_browser=not a.no_browser)
    except (BrandError, StudioError) as e:
        print(str(e))
        return 1
    except OSError:
        print("The review page could not start on this computer. Close any other copy of it and try again.")
        return 1


# ----------------------------------------------------------------------------- export
def cli_export(args):
    from smf.studio.export import export_posts

    ap = _Parser(prog="factory.py export", description="Write approved posts to a ready-to-post folder.")
    ap.add_argument("--brand", help="the brand's id (required; there is no default brand)")
    ap.add_argument("batches", nargs="*", help="batch files to export from; none = every batch of this brand")
    ap.add_argument("--check", action="store_true", help="say what would be written, and write nothing")
    try:
        a = ap.parse_args(args)
        brand = brands.load(a.brand)
        paths = resolve_batches(brand, a.batches) if a.batches else all_batches(brand)
        if not paths:
            raise StudioError("%s has no batches yet. Write and approve some posts first." % brand.name)
        report = export_posts(brand, paths, check_only=a.check)
    except (BrandError, StudioError) as e:
        print(str(e))
        return 1

    would = "would be " if a.check else ""
    if report.exported:
        print("%d post%s %swritten to the ready-to-post folder:" % (len(report.exported),
              "" if len(report.exported) == 1 else "s", would))
        print("  %s" % _say_where(brand, report.folder))
    else:
        print("No new posts %s." % ("would be written" if a.check else "were written"))
    if report.already:
        print("%d already exported earlier, left as they are:" % len(report.already))
        for item in report.already:
            print("  - %s%s" % (item["post_id"], ("  (%s)" % os.path.basename(item["folder"])) if item["folder"] else ""))
    if report.refused:
        print("%d approved post%s left out:" % (len(report.refused), "" if len(report.refused) == 1 else "s"))
        for item in report.refused:
            print("  - %s: %s." % (item["post_id"], item["reason"]))
    waiting = sum(report.waiting.values())
    if waiting:
        print("%d post%s not approved yet, so %s not included." % (waiting, "" if waiting == 1 else "s",
              "it is" if waiting == 1 else "they are"))
    if report.exported and not a.check:
        print("Next step: open README.txt in that folder. It lists the order to post in. Nothing was posted for you.")
    elif report.refused or waiting:
        print("Next step: python factory.py review --brand %s" % brand.id)
    return 0
