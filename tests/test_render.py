"""Picture tests: a spec is checked in plain words, a brand's kit is only ever its own, and
(where a browser is installed) every no-key format really draws, at the right size, offline.

    python -m unittest discover -s tests -t . -v

The checks on specs, kits and fonts run on a bare Python. The PDF tests need the imaging
library and the drawing tests need the page renderer, both of which `python factory.py setup`
installs; without them those tests are skipped, and the skip says why.
Everything is written into a temporary folder whose name has a space, an apostrophe and an accent.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                              # noqa: E402
from smf.brands import BrandError, contrast                         # noqa: E402
from smf.studio import render                                       # noqa: E402
from smf.studio.render import carousel, engine, kit as K, raw       # noqa: E402
from smf.studio.render.demo import demo_specs                       # noqa: E402
from smf.studio.render.pdf import PdfError, images_to_pdf           # noqa: E402
from smf.studio.render.spec import NO_KEY_FORMATS, SpecError, validate_spec   # noqa: E402
from tests.test_brands import BAKERY, CLINIC                        # noqa: E402

# A brand that has answered the colour question and nothing else: no logo, no photos, no fonts.
THREE_COLOURS = {"visual": {"colors": {"ground": "#F7F4EC", "ink": "#1D2A26", "accent": "#0B7A5C"},
                            "wordmark": "Plain Goods"}}

_AVAILABLE = None


def browser():
    global _AVAILABLE
    if _AVAILABLE is None:
        _AVAILABLE = engine.renderer_available()
    return _AVAILABLE


def needs_browser(test):
    ok, why = browser()
    return unittest.skipUnless(ok, "pictures cannot be drawn here: %s" % why)(test)


def has_pillow():
    try:
        import PIL                                                  # noqa: F401
        return True
    except ImportError:
        return False


needs_pillow = unittest.skipUnless(has_pillow(), "the imaging library is not installed (python factory.py setup)")


def write_png(path, size, rgb):
    """A flat-colour PNG made with the standard library, so photo tests need no imaging library."""
    width, height = size
    row = b"\x00" + bytes(rgb) * width

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))
    return Path(path)


class RenderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="render o'brien café ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.bakery = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
        self.clinic = brands.create("stride-physio", "Stride Physio", json.loads(json.dumps(CLINIC)))
        self.empty = brands.create("plain-goods", "Plain Goods", json.loads(json.dumps(THREE_COLOURS)))
        self.out = Path(self.tmp.name) / "pictures for the café"

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def carousel_spec(self, identity="person", **extra):
        spec = {"format": "carousel", "identity": identity, "name": "bake day", "slides": [
            {"headline": "Why our crust cracks when you press it", "accent": ["cracks"], "eyebrow": "Bake day"},
            {"headline": "Eighteen hours of proofing.", "kicker": "The dough does the work overnight."},
            {"kind": "checklist", "title": "What to bring to class", "items": ["An apron", "A jar with a lid"]},
            {"headline": "Book a Saturday class", "button": "See the dates"}]}
        spec.update(extra)
        return spec


# ============================================================================ runs everywhere
class TestSpecIsCheckedInPlainWords(RenderCase):
    def test_every_demo_spec_is_valid_for_every_brand(self):
        self.assertEqual([s["format"] for s in demo_specs("company")], list(NO_KEY_FORMATS))
        for brand, identity in ((self.bakery, "person"), (self.clinic, "person"), (self.empty, "company")):
            for spec in demo_specs(identity):
                self.assertEqual(validate_spec(brand, spec), [], spec["format"])

    def test_every_planned_kind_of_visual_maps_to_formats_that_exist(self):
        drawn = [f for formats in render.FORMATS_FOR_PLANNED_VISUAL.values() for f in formats]
        self.assertTrue(set(drawn) <= set(NO_KEY_FORMATS))
        self.assertEqual(set(drawn), set(NO_KEY_FORMATS), "a format no planned visual ever leads to")

    def test_an_unknown_format_lists_the_real_ones_and_guesses_the_typo(self):
        problems = validate_spec(self.bakery, {"format": "carousell", "identity": "person", "slides": [{}]})
        self.assertIn("did you mean 'carousel'", problems[0])
        for fmt in NO_KEY_FORMATS:
            self.assertIn(fmt, problems[0])

    def test_the_identity_must_belong_to_this_brand(self):
        spec = self.carousel_spec(identity="company")
        self.assertEqual(validate_spec(self.bakery, spec), [])
        problems = validate_spec(self.clinic, spec)          # the clinic has no `company` identity
        self.assertEqual(len(problems), 1)
        self.assertIn("Stride Physio has no identity called 'company'", problems[0])
        missing = validate_spec(self.bakery, {"format": "headline", "slides": [{"headline": "Hello"}]})
        self.assertTrue(any("who is speaking" in p and "person, company" in p for p in missing))

    def test_a_misspelt_setting_is_named_with_a_suggestion(self):
        spec = {"format": "headline", "identity": "person", "slides": [{"headine": "Fresh at seven"}]}
        text = " | ".join(validate_spec(self.bakery, spec))
        self.assertIn("did you mean 'headline'", text)
        self.assertIn("needs 'headline'", text)

    def test_a_carousel_has_a_cover_a_middle_and_a_closing_slide(self):
        short = self.carousel_spec()
        short["slides"] = short["slides"][:2]
        self.assertTrue(any("cover, 2 to 8 slides in the middle" in p for p in validate_spec(self.bakery, short)))
        wrong = self.carousel_spec()
        wrong["slides"][0]["kind"] = "point"
        wrong["slides"][-1]["kind"] = "stat"
        text = " | ".join(validate_spec(self.bakery, wrong))
        self.assertIn("Slide 1 of a carousel is the cover", text)
        self.assertIn("last slide of a carousel is the closing slide", text)

    def test_text_that_belongs_in_the_caption_is_refused_by_slide_and_field(self):
        spec = self.carousel_spec()
        spec["slides"][1]["headline"] = "bread " * 40
        problems = validate_spec(self.bakery, spec)
        self.assertEqual(len(problems), 1)
        self.assertRegex(problems[0], r"^Slide 2: 'headline' is \d+ characters; at most \d+ fit")

    def test_a_statement_card_holds_one_idea(self):
        spec = {"format": "bold-text", "identity": "person", "slides": [
            {"layout": "statement", "headline": "one two three four five six seven eight nine ten",
             "subline": "eleven twelve thirteen fourteen fifteen sixteen"}]}
        self.assertTrue(any("at most 15 words" in p for p in validate_spec(self.bakery, spec)))

    def test_shape_problems_do_not_crash_the_checker(self):
        for bad in (None, [], "carousel", {"format": "stat"}, {"format": "stat", "identity": "person", "slides": "x"},
                    {"format": "stat", "identity": "person", "slides": [1, 2]},
                    {"format": "notes", "identity": "person", "slides": [{}] * 11}):
            self.assertTrue(validate_spec(self.bakery, bad), bad)

    def test_settings_that_belong_to_another_format_are_refused(self):
        spec = self.carousel_spec(theme="dark", avatar="Brand/brand-kit/photos/a.png")
        text = " | ".join(validate_spec(self.bakery, spec))
        self.assertIn("'theme' only applies", text)
        self.assertIn("'avatar' only applies", text)

    def test_an_unknown_size_is_refused_in_words(self):
        with self.assertRaises(render.RenderError) as cm:
            engine.size_for("poster")
        self.assertIn("portrait (1080x1350), square (1080x1080) or story (1080x1920)", str(cm.exception))
        self.assertEqual((engine.size_for(None), engine.size_for("1:1"), engine.size_for("Story")),
                         ((1080, 1350), (1080, 1080), (1080, 1920)))
        self.assertTrue(any("not a picture size" in p for p in validate_spec(self.bakery, self.carousel_spec(size="A4"))))

    def test_the_entry_point_refuses_a_bad_spec_before_any_browser_starts(self):
        with mock.patch.object(engine.Renderer, "__enter__", side_effect=AssertionError("a browser was started")):
            with self.assertRaises(SpecError) as cm:
                render.render_post_visuals(self.bakery, {"format": "stat", "identity": "person", "slides": [{}]}, self.out)
        self.assertIn("needs 'stat'", str(cm.exception))
        self.assertFalse(self.out.exists())


class TestTheBrandIsAlwaysExplicit(RenderCase):
    def test_no_brand_is_an_error_not_a_guess(self):
        for nothing in (None, "", 0, {}):
            with self.assertRaises(BrandError):
                render.render_post_visuals(nothing, self.carousel_spec(), self.out)
            with self.assertRaises(BrandError):
                K.resolve(nothing)
            with self.assertRaises(BrandError):
                validate_spec(nothing, self.carousel_spec())

    def test_an_unknown_brand_id_says_which_brands_exist(self):
        with self.assertRaises(BrandError) as cm:
            render.render_post_visuals("harbour-bakes", self.carousel_spec(), self.out)
        self.assertIn("maple-and-main", str(cm.exception))

    def test_pictures_go_under_the_brands_own_output_folder(self):
        folder = render.default_out_dir(self.clinic, {"format": "stat", "name": "Knee Pain"})
        self.assertEqual(folder.parent, Path(self.clinic.path("Output", "visuals")))
        self.assertTrue(folder.name.endswith("-knee-pain"))

    def test_one_brands_pages_carry_nothing_of_the_other(self):
        spec = self.carousel_spec()
        bakery_pages = "".join(s.html for s in carousel.build(K.resolve(self.bakery), spec, (1080, 1350)))
        clinic_pages = "".join(s.html for s in carousel.build(K.resolve(self.clinic), spec, (1080, 1350)))
        self.assertIn("Maple &amp; Main", bakery_pages)
        self.assertIn("#C2571A", bakery_pages)
        for theirs in ("Maple", "#C2571A", "#FBF7F0", "#2B1D14"):
            self.assertNotIn(theirs, clinic_pages)
        self.assertIn("Stride Physio", clinic_pages)
        self.assertIn("#0E7C86", clinic_pages)


class TestKit(RenderCase):
    def test_three_colours_are_enough(self):
        kit = K.resolve(self.empty)
        self.assertEqual((kit.wordmark, kit.handle, kit.logo, kit.notes), ("Plain Goods", "", None, []))
        self.assertEqual({f.role for f in kit.faces}, set(K.ROLES))
        self.assertTrue(all(f.origin == "built-in" and f.path.is_file() for f in kit.faces))
        self.assertIsNone(kit.avatar(self.empty, "company"))

    def test_accents_stay_readable_on_every_background(self):
        odd = brands.create("pale-accent", "Pale Accent", {"visual": {
            "colors": {"ground": "#FFFFFF", "ink": "#222222", "accent": "#FFE680"}, "wordmark": "Pale"}})
        for brand in (self.bakery, self.clinic, self.empty, odd):
            kit = K.resolve(brand)
            for ground in K.GROUNDS:
                pal = kit.palette(ground)
                where = "%s on %s" % (brand.id, ground)
                # a mid-tone background caps what ANY colour can reach; the promise is "as readable
                # as that background allows", and never less than large type needs
                ceiling = max(contrast(pal["bg"], "#000000"), contrast(pal["bg"], "#FFFFFF")) - 0.01
                self.assertGreaterEqual(contrast(pal["accent"], pal["bg"]), 3.0, where)
                self.assertGreaterEqual(contrast(pal["accent_small"], pal["bg"]), min(4.5, ceiling), where)
                self.assertGreaterEqual(contrast(pal["pill_fg"], pal["pill_bg"]), 3.0, where)
                self.assertGreaterEqual(contrast(pal["head"], pal["bg"]), min(4.5, ceiling), where)
        self.assertEqual(K.resolve(self.bakery).palette("main")["accent"], "#C2571A")     # readable already: untouched

    def test_a_named_font_that_is_missing_falls_back_and_says_so(self):
        self.bakery.data["visual"]["fonts"] = {"display": "Recoleta", "body": "", "mono": "Geist Mono"}
        kit = K.resolve(self.bakery)
        self.assertEqual(len(kit.notes), 1)
        self.assertIn("'Recoleta'", kit.notes[0])
        self.assertIn("built-in Inter", kit.notes[0])
        self.assertIn("Nothing was downloaded", kit.notes[0])
        display = [f for f in kit.faces if f.role == "display"]
        self.assertEqual([f.origin for f in display], ["built-in"])

    def test_a_brands_own_font_files_are_used_by_family_or_by_exact_file(self):
        fonts = Path(self.bakery.kit_dir) / "fonts"
        bundled = K.FONTS_DIR / "anton" / "Anton-Regular.ttf"
        shutil.copyfile(bundled, fonts / "Bakery Display-Bold.ttf")
        self.bakery.data["visual"]["fonts"] = {"display": "Bakery Display"}
        kit = K.resolve(self.bakery)
        self.assertEqual(kit.notes, [])
        face = [f for f in kit.faces if f.role == "display"][0]
        self.assertEqual((face.origin, face.path.name, face.weight), ("brand", "Bakery Display-Bold.ttf", "100 900"))
        self.bakery.data["visual"]["fonts"] = {"poster": "bakery display-bold.TTF"}
        face = [f for f in K.resolve(self.bakery).faces if f.role == "poster"][0]
        self.assertEqual((face.origin, face.path.name), ("brand", "Bakery Display-Bold.ttf"))

    def test_font_addresses_survive_spaces_apostrophes_and_accents(self):
        fonts = Path(self.bakery.kit_dir) / "fonts"
        shutil.copyfile(K.FONTS_DIR / "anton" / "Anton-Regular.ttf", fonts / "Crème d'Or.ttf")
        self.bakery.data["visual"]["fonts"] = {"display": "Crème d'Or.ttf"}
        css = K.resolve(self.bakery).font_face_css()
        urls = re.findall(r'url\("([^"]+)"\)', css)
        self.assertEqual(len(urls), 4)
        for url in urls:
            self.assertTrue(url.startswith("file:"), url)
            self.assertNotRegex(url, r"[ 'é]")
            self.assertTrue(Path(unquote(urlparse(url).path)).is_file() or os.name == "nt", url)
        self.assertTrue(any("Cr%C3%A8me%20d%27Or.ttf" in u for u in urls))
        self.assertNotIn("http", css)

    def test_a_missing_logo_is_a_note_not_a_crash(self):
        self.bakery.data["visual"]["logo"] = "Brand/brand-kit/logos/mark.svg"
        kit = K.resolve(self.bakery)
        self.assertIsNone(kit.logo)
        self.assertIn("was not found", kit.notes[0])
        logo = Path(self.bakery.kit_dir) / "logos" / "mark.svg"
        logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',
                        encoding="utf-8")
        self.assertEqual(K.resolve(self.bakery).logo, logo)

    def test_initials(self):
        self.assertEqual(K.initials("Ava Lindqvist"), "AL")
        self.assertEqual(K.initials("Maple & Main", "company"), "M")
        self.assertEqual(K.initials("Élodie"), "É")
        self.assertEqual(K.initials("  "), "?")


class TestTheRoundPictureIsNeverSomeoneElse(RenderCase):
    def picture(self, brand, name):
        return write_png(Path(brand.kit_dir) / "photos" / name, (64, 64), (0, 200, 0))

    def test_a_loose_photo_is_not_picked_up(self):
        self.picture(self.bakery, "team at the market.png")
        self.assertIsNone(K.resolve(self.bakery).avatar(self.bakery, "person"))

    def test_a_photo_saved_for_the_identity_is_used_for_that_identity_only(self):
        mine = self.picture(self.bakery, "avatar-person.png")
        kit = K.resolve(self.bakery)
        self.assertEqual(kit.avatar(self.bakery, "person"), mine)
        self.assertIsNone(kit.avatar(self.bakery, "company"))
        with self.assertRaises(BrandError):
            kit.avatar(self.bakery, "doctor")

    def test_a_named_photo_must_be_in_this_brands_photos_folder(self):
        theirs = self.picture(self.clinic, "tomas.png")
        named = self.picture(self.bakery, "ava at the oven.png")
        kit = K.resolve(self.bakery)
        self.assertEqual(kit.avatar(self.bakery, "person", "Brand/brand-kit/photos/ava at the oven.png"), named)
        for outside in (str(theirs), "../stride-physio/Brand/brand-kit/photos/tomas.png", "brand-master.json"):
            with self.assertRaises(BrandError) as cm:
                kit.avatar(self.bakery, "person", outside)
            self.assertIn("own photos folder", str(cm.exception))

    def test_with_no_photo_the_page_shows_initials_and_the_identitys_own_name(self):
        spec = {"format": "post-screenshot", "identity": "person", "slides": [{"text": "Bake day is Saturday."}]}
        page = raw.build_post_screenshots(K.resolve(self.clinic), self.clinic, spec, (1080, 1350))[0].html
        self.assertIn(">TO</div>", page)
        self.assertIn("Tomas Okafor", page)
        self.assertNotIn("<img", page)


class TestPagesAreSelfContained(RenderCase):
    def test_no_page_mentions_a_web_address(self):
        for brand, identity in ((self.bakery, "person"), (self.empty, "company")):
            kit = K.resolve(brand)
            for spec in demo_specs(identity):
                for slide in render._build_slides(brand, kit, spec, (1080, 1350)):
                    self.assertNotRegex(slide.html, r"(?i)https?:|ftp:|wss?:", spec["format"])
                    addresses = re.findall(r'(?:url\(|src=|href=)"?([^")\s]+)', slide.html)
                    self.assertEqual(len(addresses), 4, spec["format"])          # the four font files
                    self.assertTrue(all(a.startswith("file:///") for a in addresses), addresses)

    def test_text_cannot_smuggle_markup_into_a_page(self):
        spec = self.carousel_spec()
        spec["slides"][0]["headline"] = 'Fresh <img src="https://example.com/x.png"> at "seven" & <script>1</script>'
        page = carousel.build(K.resolve(self.bakery), spec, (1080, 1350))[0].html
        self.assertNotIn("<img", page)
        self.assertNotIn("<script", page)
        self.assertIn("&lt;script&gt;", page)

    def test_an_accent_phrase_that_is_not_there_is_reported(self):
        spec = self.carousel_spec()
        spec["slides"][0]["accent"] = ["sourdough"]
        slide = carousel.build(K.resolve(self.bakery), spec, (1080, 1350))[0]
        self.assertTrue(any("'sourdough'" in w for w in slide.warnings))


class TestSlideOrder(unittest.TestCase):
    def test_numbered_files_sort_the_way_people_count(self):
        from smf.studio.render.pdf import natural_key
        names = ["slide-10.png", "slide-2.png", "slide-1.png"]
        self.assertEqual(sorted(names, key=natural_key), ["slide-1.png", "slide-2.png", "slide-10.png"])


class TestBundledFonts(unittest.TestCase):
    def font_files(self):
        return sorted(p for p in K.FONTS_DIR.rglob("*") if p.is_file() and p.suffix.lower() in K.FONT_EXTENSIONS)

    @needs_pillow
    def test_the_imaging_library_can_open_every_font_too(self):
        from PIL import ImageFont
        names = {ImageFont.truetype(str(p), 40).getname()[0] for p in self.font_files()}
        self.assertEqual(names, {"Inter", "Geist Mono", "Anton"})

    def test_every_font_has_its_licence_beside_it_and_is_listed_with_its_checksum(self):
        lock = json.loads((ROOT / "BINARIES.lock").read_text(encoding="utf-8"))["binaries"]
        files = self.font_files()
        self.assertEqual(len(files), 3)
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            self.assertEqual(path.read_bytes()[:4], b"\x00\x01\x00\x00", "%s is not a TrueType font" % rel)
            licence = (path.parent / "OFL.txt").read_text(encoding="utf-8")
            self.assertIn("SIL OPEN FONT LICENSE Version 1.1", licence)
            self.assertIn(rel, lock, "%s is not listed in BINARIES.lock" % rel)
            self.assertEqual(lock[rel]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertTrue(lock[rel]["source"].startswith("https://raw.githubusercontent.com/google/fonts/"))
        self.assertEqual({spec["file"] for spec in K.BUNDLED.values()},
                         {p.relative_to(K.FONTS_DIR).as_posix() for p in files})


@needs_pillow
class TestPdf(RenderCase):
    def pictures(self, sizes):
        from PIL import Image
        self.out.mkdir(parents=True)
        paths = []
        for i, size in enumerate(sizes, 1):
            p = self.out / ("slide-%d.png" % i)
            Image.new("RGBA", size, (200, 80 + 40 * i, 20, 255)).save(p)
            paths.append(p)
        return paths

    def test_pictures_become_pages_in_order(self):
        paths = self.pictures([(1080, 1350)] * 3)
        pdf, notes = images_to_pdf(paths, self.out / "set.pdf")
        data = pdf.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b(?!s)", data)), 3)
        self.assertEqual(notes, [])
        self.assertEqual([p.name for p in self.out.iterdir() if p.name.startswith(".tmp")], [])

    def test_mixed_sizes_are_made_but_mentioned(self):
        _pdf, notes = images_to_pdf(self.pictures([(1080, 1350), (1080, 1080)]), self.out / "set.pdf")
        self.assertIn("not all the same size", notes[0])

    def test_problems_are_named_and_nothing_is_written(self):
        good = self.pictures([(1080, 1350)])
        broken = self.out / "broken.png"
        broken.write_bytes(b"not a picture")
        for paths, word in (([], "no pictures"), (good + [self.out / "gone.png"], "gone.png"),
                            (good + [broken], "broken.png")):
            with self.assertRaises(PdfError) as cm:
                images_to_pdf(paths, self.out / "bad.pdf")
            self.assertIn(word, str(cm.exception))
        self.assertFalse((self.out / "bad.pdf").exists())

class TestTheVisualsVerb(RenderCase):
    def run_verb(self, *args):
        from smf.studio.render_cli import cli_visuals
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_visuals(list(args))
        return code, buf.getvalue()

    def test_check_reads_a_spec_file_and_draws_nothing(self):
        spec_file = Path(self.tmp.name) / "my spec.json"
        spec_file.write_text(json.dumps(self.carousel_spec()), encoding="utf-8")
        code, said = self.run_verb("--brand", "maple-and-main", "--spec", str(spec_file), "--check")
        self.assertEqual(code, 0)
        self.assertIn("The spec is fine", said)
        bad = self.carousel_spec(identity="ghost")
        spec_file.write_text(json.dumps([self.carousel_spec(), bad]), encoding="utf-8")
        code, said = self.run_verb("--brand", "maple-and-main", "--spec", str(spec_file), "--check")
        self.assertEqual(code, 1)
        self.assertIn("Spec 2:", said)
        self.assertIn("no identity called 'ghost'", said)

    def test_the_brand_is_required_and_must_exist(self):
        with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.run_verb("--demo")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("Say which brand", err.getvalue())
        code, said = self.run_verb("--brand", "harbour-bakes", "--demo")
        self.assertEqual(code, 1)
        self.assertIn("there is no brand called 'harbour-bakes'", said)


# ============================================================================ needs the browser
@needs_browser
class TestEveryNoKeyFormatDraws(RenderCase):
    def assert_real_picture(self, path, size):
        from PIL import Image
        self.assertGreater(path.stat().st_size, 6000, path.name)
        with Image.open(path) as im:
            self.assertEqual(im.size, size, path.name)
            low, high = im.convert("L").getextrema()
        self.assertGreater(high - low, 60, "%s is a flat colour" % path.name)

    def test_an_empty_brand_and_the_bakery_draw_every_format_offline(self):
        for brand, identity in ((self.empty, "company"), (self.bakery, "person")):
            results = render.render_many(brand, demo_specs(identity), self.out / brand.id)
            self.assertEqual([rep["format"] for _f, rep in results], list(NO_KEY_FORMATS))
            for files, report in results:
                self.assertEqual(report["brand"], brand.id)
                self.assertEqual(report["network_requests"], [])
                self.assertEqual(report["notes"], [])
                pictures = [f for f in files if f.suffix == ".png"]
                self.assertEqual([p.name for p in pictures], report["files"])
                self.assertTrue(pictures)
                for p in pictures:
                    self.assertIn("o'brien café", str(p))
                    self.assert_real_picture(p, (1080, 1350))
                saved = json.loads((pictures[0].parent / render.REPORT_NAME).read_text(encoding="utf-8"))
                self.assertEqual(saved["files"], report["files"])
                self.assertEqual([p.name for p in pictures[0].parent.iterdir() if p.name.startswith(".")], [])
            carousel_files, carousel_report = results[0]
            self.assertEqual(carousel_files[-1].name, carousel_report["pdf"])
            self.assertTrue(carousel_files[-1].read_bytes().startswith(b"%PDF"))
            self.assertIn("smf-display", carousel_report["fonts_drawn"])

    def test_the_other_two_sizes_are_exact(self):
        for name, size in (("square", (1080, 1080)), ("story", (1080, 1920)), ("9:16", (1080, 1920))):
            spec = {"format": "headline", "identity": "company", "size": name,
                    "slides": [{"headline": "Fresh at seven, gone by ten.", "support": "Come early on Saturdays."}]}
            files = render.render_post_visuals(self.empty, spec, self.out / name.replace(":", "-"))
            self.assert_real_picture(files[0], size)

    def test_two_brands_draw_the_same_spec_differently_and_one_brand_draws_it_the_same_twice(self):
        from PIL import Image, ImageChops
        spec = {"format": "stat", "identity": "person", "slides": [
            {"stat": "18h", "headline": "of proofing before the oven.", "source": "our own bake sheet"}]}

        def pixels(brand, folder):
            with Image.open(render.render_post_visuals(brand, spec, self.out / folder)[0]) as im:
                return im.convert("RGB").copy()

        first, again, other = pixels(self.bakery, "a"), pixels(self.bakery, "b"), pixels(self.clinic, "c")
        self.assertIsNone(ImageChops.difference(first, again).getbbox(), "the same brand drew two different pictures")
        self.assertIsNotNone(ImageChops.difference(first, other).getbbox(), "two brands drew the same picture")
        colours = {c for _n, c in other.getcolors(maxcolors=1 << 24)}
        self.assertIn((0x0E, 0x7C, 0x86), colours)                 # the clinic's accent is on the clinic's card
        self.assertNotIn((0xC2, 0x57, 0x1A), colours)              # and the bakery's is not

    def test_the_brands_own_photo_is_drawn_from_a_hostile_folder(self):
        from PIL import Image
        write_png(Path(self.bakery.kit_dir) / "photos" / "avatar-person.png", (300, 300), (0, 200, 0))
        spec = {"format": "post-screenshot", "identity": "person", "slides": [{"text": "Bake day is Saturday."}]}
        files, report = render.render_with_report(self.bakery, spec, self.out / "with photo")
        with Image.open(files[0]) as im:
            green = sum(n for n, c in im.convert("RGB").getcolors(maxcolors=1 << 24) if c == (0, 200, 0))
        self.assertGreater(green, 5000)
        self.assertEqual(report["network_requests"], [])

    def test_long_text_is_shrunk_to_fit_and_the_report_says_so(self):
        spec = self.carousel_spec()
        spec["slides"][2] = {"kind": "steps", "title": "Five steps from flour to a loaf worth queueing for",
                             "steps": [{"label": "Step %d" % i, "head": "Give the dough the time it asks for",
                                        "body": "Mix, rest, fold and wait. Every shortcut here shows up later as a flat, "
                                                "pale loaf that nobody comes back for."} for i in range(1, 6)],
                             "result": "A crust that cracks when you press it, every single Saturday."}
        files, report = render.render_with_report(self.bakery, spec, self.out / "long")
        self.assertEqual(len(files), 4)
        shrunk = [s for s in report["shrunk_to_fit"] if s["slide"] == 3]
        self.assertTrue(shrunk)
        self.assertTrue(all(s["to"] < s["from"] for s in shrunk))

    def test_a_line_that_cannot_fit_stops_the_render_and_names_the_slide_and_the_line(self):
        spec = self.carousel_spec()
        word = "Sauerteigbrotbackkursanmeldungsformular" * 2
        spec["slides"][2]["title"] = word
        with self.assertRaises(render.RenderError) as cm:
            render.render_post_visuals(self.bakery, spec, self.out / "too long")
        said = str(cm.exception)
        self.assertIn("Slide 3 of 4", said)
        self.assertIn("title", said)
        self.assertIn(word, said)
        self.assertIn("too long to fit", said)
        self.assertNotIn("Traceback", said)
        self.assertEqual(list((self.out / "too long").glob("*.png")), [], "half a carousel was left behind")


@needs_browser
class TestNothingLeavesThisComputer(RenderCase):
    def test_a_page_that_asks_for_a_web_address_fails_and_the_request_never_leaves(self):
        page = ('<!doctype html><html><body style="margin:0;background:#fff"><h1>Hello</h1>'
                '<img src="https://example.com/tracker.png"></body></html>')
        target = self.out / "leak.png"
        with engine.Renderer() as r:
            with self.assertRaises(render.RenderError) as cm:
                r.render(page, target, (1080, 1350), "The test page")
            self.assertEqual(r.refused, ["https://example.com/tracker.png"])
            self.assertIn("tried to load something from the internet", str(cm.exception))
            self.assertFalse(target.exists())
            ok = r.render("<!doctype html><html><body><h1>Only local</h1></body></html>", self.out / "fine.png")
            self.assertEqual(ok["shrunk"], [])
        self.assertTrue((self.out / "fine.png").is_file())


# ============================================================================ a free design
def free_spec(html, css="", **extra):
    spec = {"format": "free", "identity": "person", "name": "free one", "slides": [{"html": html, "css": css}]}
    spec.update(extra)
    return spec


GOOD_HTML = "<div class='h'>Your dough is not late.</div><p class='p'>It is cold.</p>"
GOOD_CSS = (".h{margin:120px 90px 40px;font:800 120px/1 'smf-display';color:var(--ink)}"
            ".p{margin:0 90px;font:500 48px/1.3 'smf-body';color:var(--ink)}")


class TestAFreeDesignIsCheckedBeforeABrowserStarts(RenderCase):
    def test_a_plain_free_design_is_accepted_and_the_fixed_formats_are_unchanged(self):
        self.assertEqual(validate_spec(self.bakery, free_spec(GOOD_HTML, GOOD_CSS)), [])
        self.assertNotIn("free", NO_KEY_FORMATS)                       # the demo and the planner still mean the eight
        said = " ".join(validate_spec(self.bakery, {"format": "fre", "identity": "person", "slides": [{}]}))
        self.assertIn("did you mean 'free'", said)

    def test_anything_that_runs_code_or_loads_a_file_is_refused_with_the_reason(self):
        refused = {
            "<script>x()</script>": "<script>",
            "<div onclick='x()'>Hi</div>": "'onclick' runs code",
            "<img src='file:///etc/hosts'>": "'src' loads a file",
            "<iframe src='keys.env'></iframe>": "<iframe>",
            "<svg><image href='a.png'/></svg>": "<image>",
            "<div style='background:url(a.png)'>Hi</div>": "loads a file (url)",
            "<a href='https://example.com'>Hi</a>": "<a>",
        }
        for html, expected in refused.items():
            said = " ".join(validate_spec(self.bakery, free_spec(html)))
            self.assertIn(expected, said, html)
        for css, expected in {"@import 'x.css';": "@import", ".a{background:URL( 'a.png' )}": "loads a file (url)",
                              ".a{background:u\\72l(a.png)}": "backslash",
                              "@font-face{font-family:x;src:local(Arial)}": "loads a font",
                              ".a::before{content:'97% of bakers'}": "writes words onto the picture",
                              "</style><script>x()</script>": "page markup"}.items():
            said = " ".join(validate_spec(self.bakery, free_spec(GOOD_HTML, css)))
            self.assertIn(expected, said, css)
        fine = ".row{display:flex;justify-content:space-between;align-content:center}.a::before{content:''}"
        self.assertEqual(validate_spec(self.bakery, free_spec(GOOD_HTML, GOOD_CSS + fine)), [])

    def test_the_identity_and_the_slide_settings_are_still_checked(self):
        said = " ".join(validate_spec(self.bakery, free_spec(GOOD_HTML, identity="ghost")))
        self.assertIn("no identity called 'ghost'", said)
        spec = free_spec(GOOD_HTML)
        spec["slides"][0]["headline"] = "A setting from another format"
        self.assertIn("'headline'", " ".join(validate_spec(self.bakery, spec)))
        self.assertIn("needs 'html'", " ".join(validate_spec(self.bakery, free_spec("   "))))


@needs_browser
@needs_pillow
class TestAFreeDesignIsCheckedAsDrawn(RenderCase):
    def refused(self, html, css=""):
        with self.assertRaises(render.RenderError) as cm:
            render.render_with_report(self.bakery, free_spec(html, GOOD_CSS + css), self.out)
        self.assertEqual(list(self.out.glob("*.png")), [], "a picture that failed a check was saved")
        return str(cm.exception)

    def test_a_good_one_draws_offline_and_its_words_are_read_from_the_picture(self):
        files, report = render.render_with_report(self.bakery, free_spec(GOOD_HTML, GOOD_CSS), self.out)
        self.assertEqual([f.name for f in files], ["free-one-01-picture.png"])
        self.assertEqual(report["network_requests"], [])
        self.assertEqual(report["picture_claims"][0]["texts"], ["Your dough is not late.", "It is cold."])
        design = json.loads((self.out / report["design"]).read_text(encoding="utf-8"))
        self.assertEqual(design["slides"][0]["html"], GOOD_HTML)        # "same as last time" can be read back

    def test_a_number_on_the_picture_is_checked_even_though_no_field_declares_it(self):
        html = GOOD_HTML + "<p class='p'>97% of our loaves sell out by noon.</p>"
        _files, report = render.render_with_report(self.bakery, free_spec(html, GOOD_CSS), self.out)
        checked = report["picture_claims"][0]["checked"]
        self.assertTrue(any("97" in c["phrase"] and not c["confirmed"] for c in checked), checked)
        self.assertTrue(any("not confirmed" in w for w in report["warnings"]), report["warnings"])

    def test_words_that_are_cut_off_too_small_faint_or_in_another_font_stop_the_picture(self):
        said = self.refused("<div class='h' style='width:300px;white-space:nowrap;overflow:hidden'>A line far too long</div>")
        self.assertIn("cut off", said)
        said = self.refused("<div class='h' style='position:absolute;left:900px;white-space:nowrap'>Off the side</div>")
        self.assertIn("cut off", said)
        said = self.refused("<div class='h' style='margin:0;position:absolute;left:0;top:-60px'>Off the top</div>")
        self.assertIn("cut off", said)
        said = self.refused(GOOD_HTML + "<p style='font:500 16px smf-body;color:var(--ink)'>Source: our sheet</p>")
        self.assertIn("too small to read on a phone (16 pixels; the smallest allowed here is 24)", said)
        said = self.refused(GOOD_HTML + "<p class='p' style='color:#F2EDE4'>Pale words on a pale page</p>")
        self.assertIn("hard to read against what is behind them", said)
        said = self.refused(GOOD_HTML + "<p class='p' style='font-family:Arial'>Another font</p>")
        self.assertIn("not one of this brand's", said)

    def test_words_over_a_dark_patch_are_measured_against_the_patch_not_the_page(self):
        html = ("<div style='position:absolute;inset:0;background:linear-gradient(#1b1009,#3a2416)'></div>"
                "<p class='p' style='position:absolute;left:90px;top:400px;color:#FBF7F0'>Light on dark</p>")
        files, _report = render.render_with_report(self.bakery, free_spec(html, GOOD_CSS), self.out)
        self.assertEqual(len(files), 1)

    def test_a_locked_page_can_open_its_fonts_and_nothing_else_on_this_computer(self):
        secret = Path(self.tmp.name) / "another brand's photo.png"
        write_png(secret, (40, 40), (10, 200, 10))
        kit = K.resolve(self.bakery)
        from smf.studio.render import free
        page = free.page(kit, (1080, 1350), "<img src='%s'><div class='h'>Hello</div>" % secret.as_uri(), GOOD_CSS)
        with engine.Renderer() as r:
            with self.assertRaises(engine.RenderError) as cm:
                r.render(page, self.out / "x.png", (1080, 1350), "The picture", locked=free.lock_for(kit, (1080, 1350)))
            self.assertIn("not allowed to use", str(cm.exception))
            self.assertEqual(len(r.blocked), 1)
            ran = free.page(kit, (1080, 1350), "<div class='h' id='t'>Before</div>"
                            "<script>document.getElementById('t').textContent='A script ran'</script>", GOOD_CSS)
            info = r.render(ran, self.out / "y.png", (1080, 1350), "The picture", locked=free.lock_for(kit, (1080, 1350)))
            self.assertEqual(info["texts"], ["Before"])                # scripts in a free page do not run
        self.assertFalse((self.out / "x.png").exists())

    def test_a_name_the_brand_never_mentions_stops_a_free_design(self):
        data = json.loads(Path(self.bakery.path("brand-master.json")).read_text(encoding="utf-8"))
        data["never_mention"] = ["Crumb & Co"]
        Path(self.bakery.path("brand-master.json")).write_text(json.dumps(data), encoding="utf-8")
        bakery = brands.load("maple-and-main")
        with self.assertRaises(render.RenderError) as cm:
            render.render_with_report(bakery, free_spec("<div class='h'>Better than Crumb &amp; Co</div>", GOOD_CSS), self.out)
        self.assertIn("own rules", str(cm.exception))

    def test_the_fixed_formats_are_not_held_to_the_new_checks(self):
        files, report = render.render_with_report(self.bakery, self.carousel_spec(), self.out)
        self.assertEqual(len([f for f in files if f.suffix == ".png"]), 4)
        self.assertIsNone(report["design"])


# ============================================================================ pictures, looks, generated images
class LibraryCase(RenderCase):
    def photo(self, name="loaf.png", rgb=(120, 70, 30), size=(60, 60)):
        folder = Path(self.bakery.kit_dir) / "photos"
        folder.mkdir(parents=True, exist_ok=True)
        return write_png(folder / name, size, rgb)

    def download(self, name="stock loaf.png", rgb=(250, 248, 244), size=(1080, 1350)):
        return write_png(Path(self.tmp.name) / name, size, rgb)


class TestABrandsPicturesKeepTheirSource(LibraryCase):
    def test_a_stock_photo_is_filed_with_where_it_came_from_and_an_own_photo_needs_nothing(self):
        from smf.studio.render import library
        self.photo()
        with self.assertRaises(BrandError) as cm:
            library.file_image(self.bakery, self.download(), "stock")
        self.assertIn("where this picture came from", str(cm.exception))
        rel = library.file_image(self.bakery, self.download(), "stock", "https://unsplash.com/photos/abc",
                                 "Unsplash licence: free to use", shows_person=False)
        self.assertEqual(rel, "Brand/brand-kit/photos/stock/stock-loaf.png")
        again = library.file_image(self.bakery, self.download(), "stock", "https://unsplash.com/photos/abc")
        self.assertEqual(again, "Brand/brand-kit/photos/stock/stock-loaf-2.png", "an earlier file was overwritten")
        rows = {r["image"]: r for r in library.list_images(self.bakery)}
        self.assertEqual(rows["Brand/brand-kit/photos/loaf.png"]["source"], "own")
        self.assertEqual(rows[rel]["source"], "stock")
        self.assertEqual(rows[rel]["from"], "https://unsplash.com/photos/abc")

    def test_a_design_can_only_name_pictures_in_this_brands_own_photos_folder(self):
        self.photo()
        theirs = Path(self.clinic.kit_dir) / "photos"
        theirs.mkdir(parents=True, exist_ok=True)
        write_png(theirs / "clinic.png", (20, 20), (1, 2, 3))
        ok = free_spec("<img src='brand:Brand/brand-kit/photos/loaf.png'>" + GOOD_HTML, GOOD_CSS)
        self.assertEqual(validate_spec(self.bakery, ok), [])
        for ref, expected in {"brand:Brand/brand-kit/photos/missing.png": "was not found",
                              "brand:../stride-physio/Brand/brand-kit/photos/clinic.png": "not in Maple & Main Bakery's own",
                              "brand:brand-master.json": "not in Maple & Main Bakery's own",
                              "https://example.com/a.png": "loads a file"}.items():
            said = " ".join(validate_spec(self.bakery, free_spec("<img src='%s'>" % ref + GOOD_HTML, GOOD_CSS)))
            self.assertIn(expected, said, ref)
        css = GOOD_CSS + ".bg{background-image:url(brand:Brand/brand-kit/photos/loaf.png)}"
        self.assertEqual(validate_spec(self.bakery, free_spec(GOOD_HTML, css)), [])
        said = " ".join(validate_spec(self.bakery, free_spec(GOOD_HTML, GOOD_CSS + ".bg{background:url(/etc/hosts)}")))
        self.assertIn("loads a file (url)", said)


@needs_browser
@needs_pillow
class TestPicturesInsideAFreeDesign(LibraryCase):
    PHOTO = "<img style='position:absolute;inset:0;width:100%%;height:100%%;object-fit:cover' src='brand:%s'>"

    def test_a_brand_picture_is_drawn_and_the_report_says_where_it_came_from(self):
        from smf.studio.render import library
        rel = library.file_image(self.bakery, self.download(rgb=(40, 26, 16)), "stock", "https://www.pexels.com/photo/1",
                                 shows_person=True)
        html = self.PHOTO % rel + ("<p class='p' style='position:absolute;left:90px;top:300px;color:#FBF7F0'>"
                                   "“Best loaf in town”</p>")
        files, report = render.render_with_report(self.bakery, free_spec(html, GOOD_CSS), self.out)
        self.assertEqual(report["network_requests"], [])
        self.assertEqual(report["images"][0]["uses"], [{"image": rel, "source": "stock", "shows_person": True}])
        notes = " ".join(report["notes"])
        self.assertIn("uses a stock photo", notes)
        self.assertIn("beside a claim or a quotation", notes)
        colours = hashlib.sha256(files[0].read_bytes()).hexdigest()
        self.assertTrue(colours)

    def test_light_words_over_a_light_photo_stop_the_picture(self):
        from smf.studio.render import library
        rel = library.file_image(self.bakery, self.download(rgb=(250, 248, 244)), "stock", "https://www.pexels.com/photo/2")
        html = self.PHOTO % rel + "<p class='p' style='position:absolute;left:90px;top:300px;color:#FFFFFF'>Hard to read</p>"
        with self.assertRaises(render.RenderError) as cm:
            render.render_with_report(self.bakery, free_spec(html, GOOD_CSS), self.out)
        self.assertIn("hard to read against what is behind them", str(cm.exception))

    def test_a_drawn_design_can_be_kept_as_a_look_and_read_back_by_name(self):
        from smf.studio.render import library
        out = Path(self.bakery.path("Output", "visuals", "first"))
        _files, report = render.render_with_report(self.bakery, free_spec(GOOD_HTML, GOOD_CSS), out)
        recent = library.recent_designs(self.bakery)
        self.assertEqual([Path(r["design"]).name for r in recent], [report["design"]])
        self.assertEqual(len(recent[0]["pictures"]), 1)
        folder = library.save_look(self.bakery, "Recipe card", recent[0]["design"], "A cream card with a hard shadow")
        self.assertTrue((folder / "sample.png").is_file())
        looks = library.list_looks(self.bakery)
        self.assertEqual([(r["name"], r["about"]) for r in looks], [("recipe-card", "A cream card with a hard shadow")])
        self.assertEqual(library.load_look(self.bakery, "Recipe card")["slides"][0]["html"], GOOD_HTML)
        self.assertEqual(library.list_looks(self.clinic), [], "one brand's look reached another")
        with self.assertRaises(BrandError) as cm:
            library.load_look(self.bakery, "gold poster")
        self.assertIn("recipe-card", str(cm.exception))


class _Answer(object):
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class TestAGeneratedImageCostsNothingWithoutAYes(LibraryCase):
    KEY = "sk-test-0123456789abcdef"  # gitleaks:allow (a made-up value the test needs)

    def setUp(self):
        LibraryCase.setUp(self)
        from smf.studio.render import imagegen
        self.gen = imagegen
        self.calls = []
        self.env = mock.patch.dict(os.environ, {imagegen.KEY_NAME: self.KEY})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        LibraryCase.tearDown(self)

    def opener(self, request, timeout=None):
        self.calls.append(request)
        png = (Path(self.tmp.name) / "made.png")
        write_png(png, (32, 48), (200, 150, 90))
        import base64
        return _Answer({"data": [{"b64_json": base64.b64encode(png.read_bytes()).decode("ascii")}]})

    def test_the_price_and_the_request_come_first_and_nothing_is_sent(self):
        with self.assertRaises(self.gen.NotConfirmed) as cm:
            self.gen.generate(self.bakery, "a warm loaf on a floured board", opener=self.opener)
        self.assertEqual(self.calls, [], "a request was sent before the person said yes")
        said = str(cm.exception)
        self.assertIn("about 5 cents", said)
        self.assertIn('"a warm loaf on a floured board"', said)
        self.assertEqual(cm.exception.plan["price_usd"], 0.05)
        with self.assertRaises(self.gen.ImageError) as cm:
            self.gen.plan("a loaf", model="some-newer-model")
        self.assertIn("could not be said first", str(cm.exception))

    @needs_pillow
    def test_a_yes_makes_one_image_filed_as_generated_with_its_cost(self):
        from smf.studio.render import library
        rel = self.gen.generate(self.bakery, "a person kneading dough", name="kneading", shape="square", quality="low",
                                shows_person=True, confirm=True, opener=self.opener)
        self.assertEqual(rel, "Brand/brand-kit/photos/generated/kneading.png")
        self.assertEqual(len(self.calls), 1)
        sent = json.loads(self.calls[0].data.decode("utf-8"))
        self.assertEqual((sent["model"], sent["size"], sent["quality"], sent["n"]), ("gpt-image-1.5", "1024x1024", "low", 1))
        self.assertNotIn(self.KEY, self.calls[0].full_url)                         # the key travels in a header only
        record = library.read_record(Path(self.bakery.home) / rel)
        self.assertEqual((record["source"], record["shows_person"], record["cost_usd"]), ("generated", True, 0.009))
        self.assertEqual(record["from"], "a person kneading dough")
        self.assertEqual(self.gen.spent(self.bakery), (1, 0.009))
        self.assertEqual(validate_spec(self.bakery, free_spec("<img src='brand:%s'>" % rel + GOOD_HTML, GOOD_CSS)), [])

    def test_no_key_and_a_refused_key_are_explained_without_showing_a_key(self):
        import urllib.error

        def refuses(request, timeout=None):
            body = io.BytesIO(json.dumps({"error": {"message": "Incorrect API key provided: %s" % self.KEY}}).encode())
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, body)

        for status, expected in ((401, "did not accept the key"),):
            with self.assertRaises(self.gen.ImageError) as cm:
                self.gen.generate(self.bakery, "a loaf", confirm=True, opener=refuses)
            self.assertIn(expected, str(cm.exception), status)
            self.assertNotIn(self.KEY, str(cm.exception))

        def turned_down(request, timeout=None):
            body = io.BytesIO(json.dumps({"error": {"message": "Rejected. Key was %s" % self.KEY}}).encode())
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, body)

        with self.assertRaises(self.gen.ImageError) as cm:
            self.gen.generate(self.bakery, "a loaf", confirm=True, opener=turned_down)
        self.assertNotIn(self.KEY, str(cm.exception))
        with mock.patch.dict(os.environ, {self.gen.KEY_NAME: ""}), mock.patch("smf.keys.load", return_value={}):
            with self.assertRaises(self.gen.ImageError) as cm:
                self.gen.generate(self.bakery, "a loaf", confirm=True, opener=self.opener)
        self.assertIn("no OpenAI key yet", str(cm.exception))
        self.assertEqual(self.calls, [])

    def test_the_verb_shows_the_price_and_stops(self):
        from smf.studio.render_cli import cli_visuals
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch("urllib.request.urlopen", side_effect=AssertionError("a request was sent")):
            code = cli_visuals(["--brand", "maple-and-main", "--generate", "a warm loaf", "--quality", "high"])
        self.assertEqual(code, 0)
        self.assertIn("Nothing was made and nothing was spent", buf.getvalue())
        self.assertIn("about 20 cents", buf.getvalue())


# ============================================================================ version 2: dark brands, small text, tall
# A made-up dark brand: deep navy background, white headlines, gold accent. Nobody's real colours.
DARK = {"visual": {"colors": {"ground": "#0A1024", "ink": "#FFFFFF", "accent": "#D9B23A"}, "wordmark": "Night Choir"},
        "accounts": {"targets": [{"identity": "company", "platform": "tiktok", "connected": False}]}}


def pixel(path, xy=(12, 12)):
    from PIL import Image
    with Image.open(str(path)) as im:
        return im.convert("RGB").getpixel(xy)


def lightness(rgb):
    return sum(rgb) / 3.0


class VersionTwoCase(RenderCase):
    def setUp(self):
        RenderCase.setUp(self)
        self.dark = brands.create("night-choir", "Night Choir", json.loads(json.dumps(DARK)))


class TestADarkBrandIsNeverTurnedWhite(VersionTwoCase):
    def test_the_standout_background_is_the_brands_own_dark_surface_and_light_brands_keep_bold(self):
        dark, light = K.resolve(self.dark), K.resolve(self.bakery)
        self.assertTrue(dark.is_dark())
        self.assertFalse(light.is_dark())
        self.assertEqual(dark.strong(), "soft")
        self.assertEqual(light.strong(), "bold")
        self.assertLess(lightness(tuple(int(dark.palette("soft")["bg"][i:i + 2], 16) for i in (1, 3, 5))), 60)
        self.assertEqual(dark.palette("soft")["accent"], "#D9B23A", "the gold was pushed toward mud")
        for ground in ("main", "soft", "bold", "accent"):
            for kit in (dark, light):
                pal = kit.palette(ground)
                self.assertGreaterEqual(contrast(pal["bg"], pal["head"]), 4.5, (kit.brand_id, ground))
                self.assertGreaterEqual(contrast(pal["bg"], pal["muted"]), 4.5, (kit.brand_id, ground, "grey text"))

    @needs_browser
    @needs_pillow
    def test_every_default_background_stays_dark_for_a_dark_brand(self):
        specs = demo_specs("company", "portrait")
        results = render.render_many(self.dark, specs, self.out / "dark")
        for spec, (files, report) in zip(specs, results):
            pictures = [f for f in files if f.suffix == ".png"]
            for slide, f in zip(spec["slides"], pictures):
                if report["format"] == "post-screenshot" or slide.get("ground"):
                    continue                              # a white post card, or a background asked for by name
                self.assertLess(lightness(pixel(f, (20, 675))), 100, "%s came out light" % f.name)
        bold = {"format": "headline", "identity": "company", "slides": [{"headline": "Asked for on purpose", "ground": "bold"}]}
        files, _report = render.render_with_report(self.dark, bold, self.out / "asked")
        self.assertGreater(lightness(pixel(files[0])), 200, "asking for bold by name no longer gets bold")

    @needs_browser
    @needs_pillow
    def test_a_light_brands_cover_is_exactly_as_before(self):
        files, _report = render.render_with_report(self.bakery, self.carousel_spec(), self.out / "light")
        ink = K.resolve(self.bakery).colours["ink"]
        self.assertEqual(pixel(files[0]), tuple(int(ink[i:i + 2], 16) for i in (1, 3, 5)))


class TestNoTextIsTooSmallForAPhone(VersionTwoCase):
    def test_no_fitted_text_may_start_or_shrink_below_24_pixels_at_any_size(self):
        from smf.studio.render import layout as L
        kit = K.resolve(self.bakery)
        for size_name in ("portrait", "square", "story"):
            size = engine.size_for(size_name)
            for spec in demo_specs("person", size_name):
                for slide in render._build_slides(self.bakery, kit, spec, size):
                    for floor in re.findall(r'data-min="(\d+)"', slide.html):
                        self.assertGreaterEqual(int(floor), L.MIN_TEXT_PX, (size_name, spec["format"], slide.name))
                    for px in re.findall(r'style="font-size:(\d+)px', slide.html):
                        self.assertGreaterEqual(int(px), L.MIN_TEXT_PX, (size_name, spec["format"], slide.name))

    @needs_browser
    def test_every_word_on_every_demo_picture_is_drawn_at_24_pixels_or_more(self):
        from smf.studio.render import checks
        kit = K.resolve(self.bakery)
        with engine.Renderer() as r:
            for size_name in ("portrait", "square", "story"):
                size = engine.size_for(size_name)
                for spec in demo_specs("person", size_name):
                    for slide in render._build_slides(self.bakery, kit, render._shown_sources(self.bakery, spec), size):
                        page_file = self.out / ("%s-%s-%s.html" % (size_name, spec["format"], slide.name))
                        page_file.parent.mkdir(parents=True, exist_ok=True)
                        page_file.write_text(slide.html, encoding="utf-8")
                        page = r._context.new_page()
                        try:
                            page.set_viewport_size({"width": size[0], "height": size[1]})
                            page.goto(page_file.as_uri(), wait_until="load")
                            page.evaluate(engine.FONT_SCRIPT)
                            page.evaluate(engine.FIT_SCRIPT)
                            seen = page.evaluate(checks.CHECK_SCRIPT, {"w": size[0], "h": size[1], "min": 24})
                        finally:
                            page.close()
                        small = [p for p in seen["problems"] if p["kind"] == "small"]
                        self.assertEqual(small, [], (size_name, spec["format"], slide.label))
                        if size_name == "story":                     # clear of TikTok's buttons and caption
                            for spot in seen["spots"]:
                                for left, top, right, bottom in spot["rects"]:
                                    self.assertLessEqual(bottom, 1920 - 440, (spec["format"], spot["text"]))
                                    if top > 700:
                                        self.assertLessEqual(right, 1080 - 130, (spec["format"], spot["text"]))

    @needs_browser
    def test_a_long_source_line_still_fits_and_is_still_checked(self):
        spec = {"format": "stat", "identity": "person", "slides": [{
            "stat": "18h", "headline": "of slow proofing in every loaf.",
            "source": "Our own production sheet, kept by the bakers every morning for the whole of last year"}]}
        files, report = render.render_with_report(self.bakery, spec, self.out / "long source")
        self.assertEqual(len(files), 1)
        self.assertTrue(report["picture_claims"][0]["checked"])


class TestTallPicturesForATikTokBrand(VersionTwoCase):
    def test_a_brand_that_only_posts_to_tiktok_gets_tall_pictures_unless_it_asks(self):
        self.assertEqual(render.default_size(self.dark), "story")
        self.assertEqual(render.default_size(self.bakery), "portrait")
        self.assertEqual(render.default_size(self.empty), "portrait")

    @needs_browser
    @needs_pillow
    def test_the_size_is_chosen_said_and_overridable(self):
        spec = {"format": "headline", "identity": "company", "slides": [{"headline": "Step into light"}]}
        files, report = render.render_with_report(self.dark, spec, self.out / "tall")
        self.assertEqual(report["size"], [1080, 1920])
        self.assertTrue(any("posts only to TikTok" in n for n in report["notes"]), report["notes"])
        files, report = render.render_with_report(self.dark, dict(spec, size="portrait"), self.out / "asked")
        self.assertEqual(report["size"], [1080, 1350])
        self.assertFalse(any("TikTok" in n for n in report["notes"]))


@needs_browser
@needs_pillow
class TestEverySetComesWithAPhoneSizeOverview(VersionTwoCase):
    def test_the_overview_shows_every_picture_small_and_is_never_one_of_the_pictures(self):
        from PIL import Image
        files, report = render.render_with_report(self.bakery, self.carousel_spec(), self.out / "set")
        sheet = Path(report["overview"])
        self.assertTrue(sheet.is_file())
        self.assertEqual(sheet.parent.name, "phone-size")
        self.assertNotIn(sheet, files)
        self.assertEqual(sorted(p.name for p in (self.out / "set").glob("*.png")), sorted(f.name for f in files if f.suffix == ".png"))
        with Image.open(str(sheet)) as im:
            self.assertEqual(im.width, 4 * render.PHONE_WIDTH + 5 * 16)
        saved = json.loads((self.out / "set" / render.REPORT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(saved["overview"], report["overview"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
