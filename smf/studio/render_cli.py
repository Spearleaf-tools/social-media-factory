"""render_cli.py - the `visuals` verb: draw a post's pictures for one named brand.

    python factory.py visuals --brand maple-and-main --spec my-carousel.json
    python factory.py visuals --brand maple-and-main --demo
    python factory.py visuals --brand maple-and-main --spec my-carousel.json --check

    python factory.py visuals --brand maple-and-main --looks                    saved looks and recent designs
    python factory.py visuals --brand maple-and-main --save-look "recipe card" --design <design file>
    python factory.py visuals --brand maple-and-main --images                   the brand's pictures and their sources
    python factory.py visuals --brand maple-and-main --add-image loaf.jpg --source stock --from <page address>
    python factory.py visuals --brand maple-and-main --generate "a warm loaf on a floured board"
    python factory.py visuals --brand maple-and-main --generate "..." --confirm     after the person said yes

--brand is required every time: pictures are always FOR someone. --spec is a JSON file holding
one spec, or a list of specs (the format is described in smf/studio/render/__init__.py).
--demo draws one of every no-key format in the brand's colours with placeholder copy, so a
person can choose formats before writing anything. --check reads the spec and reports problems
without drawing. Nothing is posted anywhere, and nothing uses a key or the internet except
--generate, which makes one image with the person's own OpenAI key: it shows the price and the
exact request and stops, and only spends anything when it is run again with --confirm.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from smf import brands
from smf.brands import BrandError


class _PlainParser(argparse.ArgumentParser):
    def error(self, message):
        if "--brand" in message:
            self.exit(2, "Say which brand these pictures are for:  --brand <brand id>\n")
        if "--spec" in message and "--demo" in message:
            self.exit(2, "Say what to draw:  --spec <file>  for your own pictures, or  --demo  for a sample of "
                         "every format.\n")
        self.exit(2, "That command was not understood (%s).\n" % message)


def _load_specs(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except OSError:
        raise ValueError("The spec file '%s' was not found." % path)
    except ValueError as e:
        raise ValueError("The spec file could not be read; it is not valid JSON (%s)." % e)
    return data if isinstance(data, list) else [data]


def _library(brand, a):
    """The verbs that keep things for later: looks, the brand's pictures, a generated image."""
    from smf.studio.render import imagegen, library

    person = {"yes": True, "no": False}.get(a.shows_person)
    if a.looks:
        looks = library.list_looks(brand)
        print("%s has %d saved look%s." % (brand.name, len(looks), "" if len(looks) == 1 else "s"))
        for row in looks:
            print("  %-24s %s" % (row["name"], row["about"]))
            print("  %-24s design: %s" % ("", row["design"]))
            if row["sample"]:
                print("  %-24s sample: %s" % ("", row["sample"]))
        recent = library.recent_designs(brand)
        if recent:
            print("Most recent free designs, newest first (look at these before designing, so the same look is "
                  "not repeated without saying so):")
            for row in recent:
                print("  %s  %s  (%s)" % (row["made"], row["name"] or "unnamed", row["identity"]))
                print("      design: %s" % row["design"])
                for picture in row["pictures"]:
                    print("      picture: %s" % picture)
        elif not looks:
            print("No free design has been drawn for this brand yet.")
        return 0
    if a.save_look:
        if not a.design:
            print("Say which design to keep:  --design <the design file saved beside the pictures>")
            return 1
        folder = library.save_look(brand, a.save_look, a.design, a.about or "")
        print("Saved as the look '%s' for %s. Ask for it by that name next time." % (folder.name, brand.name))
        return 0
    if a.images:
        rows = library.list_images(brand)
        if not rows:
            print("%s has no pictures in its photos folder yet." % brand.name)
        for row in rows:
            shows = {True: ", shows a person", False: ""}.get(row["shows_person"], "")
            print("  %-10s brand:%s%s" % (row["source"], row["image"], shows))
        count, total = imagegen.spent(brand)
        if count:
            print("Generated so far: %d image%s, $%.2f in all." % (count, "" if count == 1 else "s", total))
        return 0
    if a.add_image:
        if not a.source:
            print("Say whose picture this is:  --source own  (the brand's own)  or  --source stock  (from a stock site, "
                  "with --from <the page it came from>)")
            return 1
        rel = library.file_image(brand, a.add_image, a.source, a.where_from or "", a.licence or "", person,
                                 a.image_name)
        print("Filed for %s as %s. Use it in a design as:  brand:%s" % (brand.name, library.SPOKEN[a.source], rel))
        return 0
    try:
        rel = imagegen.generate(brand, a.generate, a.image_name, a.shape, a.quality, shows_person=person,
                                confirm=a.confirm)
    except imagegen.NotConfirmed as e:
        count, total = imagegen.spent(brand)
        print(str(e))
        if count:
            print("Generated for %s so far: %d image%s, $%.2f in all." % (brand.name, count, "" if count == 1 else "s",
                                                                           total))
        return 0
    print("Made and saved for %s. Use it in a design as:  brand:%s" % (brand.name, rel))
    print("Look at it on its own before putting it on a picture. Another try is another charge.")
    return 0


def cli_visuals(args):
    ap = _PlainParser(prog="factory.py visuals", description="Draw a post's pictures for one brand.")
    ap.add_argument("--brand", required=True, help="the brand id (its folder name under Client/)")
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--spec", help="a JSON file with one spec, or a list of specs")
    what.add_argument("--demo", action="store_true", help="one of every no-key format, with placeholder copy")
    what.add_argument("--looks", action="store_true", help="list this brand's saved looks and its recent free designs")
    what.add_argument("--save-look", metavar="NAME", help="keep a drawn free design as a look, by name (with --design)")
    what.add_argument("--images", action="store_true", help="list this brand's pictures and where each came from")
    what.add_argument("--add-image", metavar="FILE", help="file a picture into this brand's photos folder (with --source)")
    what.add_argument("--generate", metavar="DESCRIPTION", help="make one image with the person's own OpenAI key; shows "
                                                                 "the price and stops unless --confirm is given")
    ap.add_argument("--design", help="with --save-look: the design file saved beside the pictures")
    ap.add_argument("--about", help="with --save-look: one line saying what the look is")
    ap.add_argument("--source", choices=("own", "stock"), help="with --add-image: whose picture it is")
    ap.add_argument("--from", dest="where_from", help="with --add-image: the page the picture was downloaded from")
    ap.add_argument("--licence", help="with --add-image: its licence, in a sentence")
    ap.add_argument("--shows-person", choices=("yes", "no"), help="with --add-image or --generate: does it show a person")
    ap.add_argument("--image-name", help="with --add-image or --generate: a short name for the file")
    ap.add_argument("--shape", default="tall", help="with --generate: tall, square or wide")
    ap.add_argument("--quality", default="medium", help="with --generate: low, medium or high")
    ap.add_argument("--confirm", action="store_true", help="with --generate: the person has seen the price and said yes")
    ap.add_argument("--identity", help="with --demo: which identity to show (default: the brand's first)")
    ap.add_argument("--size", help="with --demo: portrait, square or story")
    ap.add_argument("--out", help="write here instead of the brand's Output/visuals folder")
    ap.add_argument("--check", action="store_true", help="only check the spec; draw nothing")
    a = ap.parse_args(args)

    from smf.studio import render

    try:
        brand = brands.load(a.brand)
        if a.looks or a.save_look or a.images or a.add_image or a.generate:
            return _library(brand, a)
        if a.demo:
            from smf.studio.render.demo import demo_specs
            identity = a.identity or brand.identities[0]
            brand.identity(identity)
            specs = demo_specs(identity, a.size or render.default_size(brand))
        else:
            specs = _load_specs(a.spec)

        problems = []
        for n, spec in enumerate(specs, 1):
            prefix = "Spec %d: " % n if len(specs) > 1 else ""
            problems.extend(prefix + p for p in render.validate_spec(brand, spec))
        if problems:
            print("Nothing was drawn. Fix these first:")
            for p in problems:
                print("  - " + p)
            return 1
        if a.check:
            print("The spec is fine: %d picture set%s ready to draw for %s."
                  % (len(specs), "" if len(specs) == 1 else "s", brand.name))
            return 0

        out_root = a.out
        if not out_root and len(specs) > 1:
            out_root = str(render.default_out_dir(brand, {"name": "demo" if a.demo else "set"}))
        if len(specs) == 1 and not out_root:
            results = [render.render_with_report(brand, specs[0])]
        elif len(specs) == 1:
            results = [render.render_with_report(brand, specs[0], out_root)]
        else:
            results = render.render_many(brand, specs, out_root)
    except (BrandError, ValueError, render.SpecError, render.RenderError, render.PdfError) as e:
        print(str(e))
        return 1

    pictures = sum(len([f for f in files if f.suffix == ".png"]) for files, _ in results)
    print("Drew %d picture%s for %s." % (pictures, "" if pictures == 1 else "s", brand.name))
    if a.demo:
        print("The copy on them is placeholder text, so you can judge the look in this brand's colours.")
    for files, report in results:
        print("  %-16s %d picture%s%s" % (report["format"], len(report["files"]),
                                          "" if len(report["files"]) == 1 else "s",
                                          " + a PDF" if report["pdf"] else ""))
    folder = Path(results[0][1]["folder"]) if len(results) == 1 else Path(results[0][1]["folder"]).parent
    print("They are in: %s" % folder)
    sheets = [report["overview"] for _files, report in results if report.get("overview")]
    if sheets:
        print("To judge them at phone size, open the overview%s:" % ("" if len(sheets) == 1 else "s"))
        for sheet in sheets:
            print("  %s" % sheet)
    if a.demo and not a.size and render.default_size(brand) == "story":
        print("They are tall (9:16), because %s posts only to TikTok." % brand.name)
    seen = []
    for _files, report in results:
        for line in report["notes"] + report["warnings"]:
            if line not in seen:
                seen.append(line)
    if seen:
        print("Worth knowing:")
        for line in seen:
            print("  - " + line)
    return 0
