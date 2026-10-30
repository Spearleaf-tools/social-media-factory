"""Long-form YouTube tests: a video's record is checked against ITS brand, the search phrase is
never reworded, the question slate is stable and keeps every phrase exactly as it was given,
chapters follow the platform's rules, a deck refuses what does not belong on a slide, and (where a
browser is installed) thumbnails and slides really draw, at the right size, offline.

    python -m unittest tests.test_youtube -v

Everything is written into a temporary folder whose name has a space, an apostrophe and an accent.
Every brand, phrase, number and title in here is invented. Nothing touches a network.
"""
from __future__ import annotations

import io
import json
import os
import re
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                              # noqa: E402
from smf.brands import BrandError                                   # noqa: E402
from smf.studio import grounding                                    # noqa: E402
from smf.studio.render import engine                                # noqa: E402
from smf.youtube import YouTubeError                                # noqa: E402
from smf.youtube import deck as DK                                  # noqa: E402
from smf.youtube import describe as D                               # noqa: E402
from smf.youtube import questions as Q                              # noqa: E402
from smf.youtube import script as S                                 # noqa: E402
from smf.youtube import thumbnail as TH                             # noqa: E402
from smf.youtube import titles as T                                 # noqa: E402
from smf.youtube import video as V                                  # noqa: E402
from smf.youtube.youtube_cli import cli_youtube                     # noqa: E402
from tests.test_brands import BAKERY, CLINIC                        # noqa: E402

THREE_COLOURS = {"visual": {"colors": {"ground": "#F7F4EC", "ink": "#1D2A26", "accent": "#0B7A5C"},
                            "wordmark": "Plain Goods"}}
OFFERS = [{"id": "weekend-class", "name": "Saturday sourdough class", "what": "A hands-on class.",
           "call_to_action": "Book a Saturday class", "link": "https://example.com/classes"}]
DISCLAIMER = "This is general information, not medical advice."

# An invented export. The headings are plain words on purpose: columns are found by what they mean.
KEYWORDS_CSV = """Search phrase,Intent,Monthly searches,Difficulty,Cost per click,What the results page shows
why is my sourdough dense,Informational,1300,22,0.4,"Video, People also ask"
how to store sourdough bread,Informational,880,18,0.2,"Video carousel"
best way to keep sourdough bread,Informational,320,15,0.2,
how to keep a sourdough starter alive,Informational,260,12,0.1,"Short videos"
what does proofing,Informational,210,10,0,
how to make a fake sourdough label,Informational,40,5,0,
how to spot fake sourdough,Informational,90,8,0,"Video"
harbour street cafe sourdough price,Commercial,70,5,0.5,
is sourdough gluten-free,Informational,2400,30,0.6,"Video"
sourdough minecraft recipe,Informational,150,3,0,
how long does sourdough take,Informational,15,9,0,
"""

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
    """A flat-colour PNG made with the standard library: a stand-in for a brand's own photo."""
    width, height = size
    row = b"\x00" + bytes(rgb) * width

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))
    return Path(path)


class YouTubeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="youtube o'brien café ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        bakery = json.loads(json.dumps(BAKERY))
        bakery["offers"] = OFFERS
        bakery["audience"]["questions_they_ask"] = ["How do I know when the dough has proofed enough?"]
        bakery["compliance"] = {"pack": "generic", "drop_terms": ["gluten-free"], "hold_terms": ["allergen"]}
        clinic = json.loads(json.dumps(CLINIC))
        clinic["compliance"] = {"pack": "health", "drop_terms": ["cures shin splints"], "hold_terms": ["shockwave therapy"],
                                "disclaimer": DISCLAIMER, "sign_off_by": "Tomas Okafor"}
        self.bakery = brands.create("maple-and-main", "Maple & Main Bakery", bakery)
        self.clinic = brands.create("stride-physio", "Stride Physio", clinic)
        self.empty = brands.create("plain-goods", "Plain Goods", json.loads(json.dumps(THREE_COLOURS)))
        grounding.add_fact(self.bakery, "Our sourdough ferments for at least 18 hours", "Our own production sheet",
                           fact_id="ferment-18h")
        self.files = Path(self.tmp.name) / "files from the café"
        self.files.mkdir()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def put(self, name, data):
        path = self.files / name
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return str(path)

    def packaged_bakery_video(self):
        """A complete, honest package for the bakery."""
        b = V.new_video(self.bakery, topic="Knowing when dough has proofed", identity="person", today="2026-06-11",
                        keyword="how do i know when dough has proofed enough", source_ref="audience.questions_they_ask[0]")
        for tail in ("the poke test, filmed", "for home bakers", None):
            V.add_title(self.bakery, b, T.with_keyword(b["keyword"], tail), "question-as-typed")
        V.choose_title(b, 3)
        b["thumbnails"] = [{"name": "a", "layout": "words", "text": "Looked ready.\nWas not.", "accent": "not"}]
        b["chosen_thumbnail"] = "a"
        b["hook"] = {"promise": "how to tell dough is ready", "say": "This loaf looked ready. It was not.",
                     "show": "The dense loaf, cut open, held to the lens.", "on_screen": "Looked ready. Was not."}
        V.set_structure(b, "straight-answer", 7, ["Why a clock cannot tell you", "The poke test, step by step",
                                                  "When the test misleads you"])
        V.set_call_to_action(self.bakery, b, "comparing", "weekend-class")
        b["description"]["answer"] = ("Dough is ready when a floured finger pressed a knuckle deep leaves a dent that "
                                      "fills back slowly. If it springs straight back, it needs longer. If it stays, it "
                                      "has gone too far. Time is only a guide: our own dough ferments for at least 18 "
                                      "hours, and we still test every batch by hand before it goes near the oven.")
        b["description"]["hashtags"] = ["sourdough", "homebaking", "bread"]
        b["tags"] = ["sourdough", "proofing"]
        V.save(self.bakery, b)
        return b


# ============================================================================ titles
class TestTheSearchPhraseIsNeverReworded(YouTubeCase):
    def test_a_title_built_around_a_phrase_keeps_it_and_only_changes_capitals(self):
        title = T.with_keyword("how do i know when i'm done proofing", "for home bakers")
        self.assertEqual(title, "How do I know when I'm done proofing? (for home bakers)")
        self.assertTrue(T.keeps_keyword(title, "how do i know when i'm done proofing")[0])

    def test_reordered_reworded_and_interrupted_phrases_are_all_caught(self):
        phrase = "why is my sourdough dense"
        self.assertTrue(T.keeps_keyword("Baker explains: WHY is my sourdough dense?! (3 causes)", phrase)[0])
        ok, why = T.keeps_keyword("Why your sourdough is dense", phrase)
        self.assertFalse(ok)
        self.assertIn("missing", why)
        ok, why = T.keeps_keyword("Why is my dense sourdough", phrase)
        self.assertFalse(ok)
        self.assertIn("reordered or interrupted", why)
        self.assertFalse(T.keeps_keyword("Why is my lovely sourdough dense", phrase)[0])
        self.assertFalse(T.keeps_keyword("Why is my sourdough denser", phrase)[0], "a longer word is not the same word")

    def test_a_phrase_too_long_for_a_title_is_handed_to_a_person_not_shortened(self):
        long_phrase = "how do i " + "really " * 16 + "know"
        with self.assertRaises(YouTubeError) as e:
            T.with_keyword(long_phrase, "for bakers")
        self.assertIn("cannot be shortened", str(e.exception))
        self.assertEqual(T.with_keyword("x" * 80, "a tail that will not fit in the room left over"), "X" + "x" * 79)

    def test_every_pattern_is_complete_and_its_examples_pass_the_bakery_and_the_clinic(self):
        self.assertEqual({p["job"] for p in T.PATTERNS}, set(T.JOBS))
        self.assertEqual(len({p["id"] for p in T.PATTERNS}), len(T.PATTERNS))
        for p in T.PATTERNS:
            for key in ("name", "template", "when", "avoid_when", "examples", "needs"):
                self.assertIn(key, p, p["id"])
            for brand_key in ("bakery", "clinic"):
                example = p["examples"][brand_key]
                self.assertLessEqual(len(example), T.HARD_LIMIT)
                self.assertNotRegex(example, "[%s%s]" % (chr(0x2014), chr(0x2013)), "no long dashes in an example")
        with self.assertRaises(YouTubeError) as e:
            T.pattern("clickbait")
        self.assertIn("question-as-typed", str(e.exception))

    def test_the_score_shows_its_working_and_bait_costs_points(self):
        phrase = "why is my sourdough dense"
        good = T.signals("Why is my sourdough dense? (3 causes, one fix each)", phrase)
        self.assertEqual([p["signal"] for p in good["parts"]], ["length", "search phrase", "a gap worth closing", "specific"])
        self.assertEqual(sum(p["of"] for p in good["parts"]), 100)
        self.assertTrue(all(p["why"] for p in good["parts"]))
        self.assertIn("Score %d out of 100" % good["score"], T.explain(good))
        bait = T.signals("You WON'T BELIEVE what happened next!!", None)
        self.assertLess(bait["score"], good["score"])
        self.assertTrue(any("bait" in n or "shock" in n for n in bait["notes"]))
        self.assertEqual(sum(p["of"] for p in bait["parts"]), 100, "with no search phrase its share goes to the others")
        late = T.signals("Three things every home baker gets wrong and then why is my sourdough dense", phrase)
        kept = next(p for p in late["parts"] if p["signal"] == "search phrase")
        self.assertLess(kept["points"], kept["of"])


class TestATitleIsCheckedAgainstItsOwnBrand(YouTubeCase):
    def test_a_traced_number_passes_and_an_untraceable_one_is_caught(self):
        self.assertEqual(T.check_title(self.bakery, "How long sourdough really takes (our 18 hour schedule)")[0], [])
        problems, _ = T.check_title(self.bakery, "We sold 4,000 loaves last year. Here is what changed")
        self.assertEqual(len(problems), 1)
        self.assertIn("4,000", problems[0])
        self.assertIn("does not trace", problems[0])
        # the same sentence for a brand with no facts at all: caught there too, and it says whose facts
        problems, _ = T.check_title(self.empty, "How long sourdough really takes (our 18 hour schedule)")
        self.assertIn("Plain Goods", problems[0])

    def test_the_clinics_compliance_term_blocks_a_title_that_is_fine_for_the_bakery(self):
        title = "This stretch cures shin splints (what I check first)"
        self.assertEqual(T.check_title(self.bakery, title)[0], [])
        problems, _ = T.check_title(self.clinic, title)
        self.assertTrue(any("must never publish" in p for p in problems), problems)
        _, warnings = T.check_title(self.clinic, "Shockwave therapy: what I check first")
        self.assertTrue(any("sign-off" in w for w in warnings), warnings)

    def test_a_never_mention_name_is_caught_once_and_only_for_the_brand_that_listed_it(self):
        title = "Better bread than Harbour Street Cafe?"
        problems, _ = T.check_title(self.bakery, title)
        self.assertEqual(len([p for p in problems if "never-mention" in p]), 1)
        self.assertEqual(T.check_title(self.clinic, title)[0], [])

    def test_promises_about_the_video_itself_are_checked_against_the_plan_not_the_facts(self):
        self.assertEqual(T.check_title(self.bakery, "Dough hydration in 6 minutes (for new bakers)", length_minutes=6)[0], [])
        problems, _ = T.check_title(self.bakery, "Dough hydration in 6 minutes (for new bakers)", length_minutes=9)
        self.assertIn("promises 6 minutes and the plan is 9", problems[0])
        problems, _ = T.check_title(self.bakery, "The 4 reasons behind a tight crumb", parts_in_video=3)
        self.assertIn("promises 4 and the structure has 3", problems[0])
        self.assertEqual(T.check_title(self.bakery, "The 4 reasons behind a tight crumb", parts_in_video=4)[0], [])
        self.assertEqual(T.promised_parts("The 3 diary habits behind most sore knees"), 3)
        problems, warnings = T.check_title(self.bakery, "Why is my loaf flat? (2026)", today="2026-06-11")
        self.assertEqual(problems, [], "a year used as a label is not a fact about the world")
        self.assertTrue(any("year" in w for w in warnings))

    def test_length_limits_are_a_problem_at_the_platforms_cap_and_advice_before_it(self):
        self.assertTrue(any("allows 100" in p for p in T.check_title(self.bakery, "A" * 101)[0]))
        problems, warnings = T.check_title(self.bakery, "A very long title about bread that keeps going past sixty characters")
        self.assertEqual(problems, [])
        self.assertTrue(any("cut off" in w for w in warnings))


# ============================================================================ the record and its check
class TestOneFolderPerVideoInsideTheRightBrand(YouTubeCase):
    def test_a_new_video_lands_in_its_brands_output_folder_with_both_files(self):
        b = V.new_video(self.bakery, topic="Knowing when dough has proofed", identity="person", today="2026-06-11")
        folder = Path(V.video_dir(self.bakery, b["video_id"]))
        self.assertEqual(b["video_id"], "2026-06-11-knowing-when-dough-has-proofed")
        self.assertEqual(folder.parent, Path(self.bakery.home) / "Output" / "youtube")
        self.assertTrue((folder / "brief.json").is_file() and (folder / "brief.md").is_file())
        self.assertIn("Maple & Main Bakery", (folder / "brief.md").read_text(encoding="utf-8"))
        self.assertEqual(V.list_ids(self.clinic), [], "nothing appears in another brand")
        again = V.new_video(self.bakery, topic="Knowing when dough has proofed", identity="person", today="2026-06-11")
        self.assertEqual(again["video_id"], b["video_id"] + "-2", "an existing folder is never reused")

    def test_text_a_person_typed_can_never_shape_the_path(self):
        b = V.new_video(self.bakery, topic="../../etc/passwd  Crème brûlée: \"why?\" \\ CON", identity="person", today="2026-06-11")
        self.assertRegex(b["video_id"], r"^2026-06-11-[a-z0-9-]+$")
        self.assertTrue(V.video_dir(self.bakery, b["video_id"]).startswith(self.bakery.home))
        for hostile in ("../stride-physio", "2026-06-11-../../x", "/etc/passwd", "2026-06-11-UPPER", "", None, "con"):
            with self.assertRaises(YouTubeError):
                V.video_dir(self.bakery, hostile)

    def test_a_record_that_names_another_brand_is_refused_and_nothing_is_changed(self):
        b = V.new_video(self.bakery, topic="Proofing", identity="person", today="2026-06-11")
        path = Path(V.video_dir(self.bakery, b["video_id"])) / "brief.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["brand"] = "stride-physio"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(YouTubeError) as e:
            V.load(self.bakery, b["video_id"])
        self.assertIn("stride-physio", str(e.exception))
        with self.assertRaises(YouTubeError):
            V.load(self.clinic, b["video_id"])                    # and the clinic cannot open the bakery's folder
        with self.assertRaises(YouTubeError):
            V.save(self.clinic, b)

    def test_who_presents_must_belong_to_the_brand_and_is_never_guessed(self):
        with self.assertRaises(YouTubeError) as e:
            V.new_video(self.bakery, topic="Proofing")           # two identities: the tool will not pick one
        self.assertIn("person, company", str(e.exception))
        with self.assertRaises(BrandError):
            V.new_video(self.clinic, topic="Shin pain", identity="company")
        self.assertEqual(V.new_video(self.clinic, topic="Shin pain")["identity"], "person", "one identity: no question to ask")

    def test_there_is_no_default_brand(self):
        for nothing in (None, "", "   "):
            with self.assertRaises(BrandError):
                V.new_video(nothing, topic="Proofing")
        with self.assertRaises(BrandError):
            V.new_video("nobody-here", topic="Proofing")


class TestTheCheckReadsThePackageInPlainWords(YouTubeCase):
    def test_a_complete_honest_package_passes_and_can_be_called_packaged(self):
        b = self.packaged_bakery_video()
        rep = V.check(self.bakery, b, final=True)
        self.assertEqual(rep.problems, [])
        self.assertTrue(any("Demand" in w for w in rep.warnings), "a skipped demand check is said out loud")
        V.set_status(self.bakery, b, "packaged")
        self.assertEqual(b["status"], "packaged")
        page = V.render_md(self.bakery, b)
        self.assertIn("`how do i know when dough has proofed enough`", page)
        self.assertIn("00:00  The question, said aloud", page)

    def test_an_unfinished_package_is_advice_while_an_idea_and_a_wall_at_packaging(self):
        b = V.new_video(self.bakery, topic="Proofing", identity="person", today="2026-06-11")
        self.assertTrue(V.check(self.bakery, b).ok, "gaps in an idea are not problems yet")
        final = V.check(self.bakery, b, final=True)
        for part in ("Titles", "Thumbnail", "Opening", "Structure", "Description"):
            self.assertTrue(any(p.startswith(part) for p in final.problems), part)
        with self.assertRaises(YouTubeError) as e:
            V.set_status(self.bakery, b, "packaged")
        self.assertIn("not packaged yet", str(e.exception))
        with self.assertRaises(YouTubeError):
            V.set_status(self.bakery, b, "filmed")               # no skipping ahead

    def test_an_untraceable_number_anywhere_a_viewer_can_read_it_stops_the_package(self):
        b = self.packaged_bakery_video()
        b["hook"]["say"] = "Nine in ten home loaves fail for one reason, and 90 percent of bakers never check it."
        b["thumbnails"][0]["text"] = "72 hours"
        rep = V.check(self.bakery, b, final=True)
        self.assertTrue(any(p.startswith("Opening") and "90" in p for p in rep.problems), rep.problems)
        self.assertTrue(any(p.startswith("Thumbnail a") and "72" in p for p in rep.problems), rep.problems)

    def test_a_title_cannot_be_added_when_it_rewords_the_phrase_or_names_a_rival(self):
        b = V.new_video(self.bakery, topic="Proofing", identity="person", keyword="why is my sourdough dense", today="2026-06-11")
        with self.assertRaises(YouTubeError) as e:
            V.add_title(self.bakery, b, "Why your sourdough turns out dense")
        self.assertIn("word for word", str(e.exception))
        with self.assertRaises(YouTubeError) as e:
            V.add_title(self.bakery, b, "Why is my sourdough dense? Ask Harbour Street Cafe")
        self.assertIn("never-mention", str(e.exception))
        self.assertEqual(b["titles"], [])
        V.add_title(self.bakery, b, "Why is my sourdough dense? (the poke test)", "question-as-typed")
        self.assertEqual(b["titles"][0]["pattern"], "question-as-typed")
        with self.assertRaises(YouTubeError):
            V.add_title(self.bakery, b, "Why is my sourdough dense? (again)", "no-such-pattern")

    def test_the_ask_only_ever_points_at_an_offer_the_brand_really_has(self):
        b = V.new_video(self.clinic, topic="Shin pain", today="2026-06-11")
        with self.assertRaises(YouTubeError) as e:
            V.set_call_to_action(self.clinic, b, "ready", "weekend-class")     # the bakery's offer
        self.assertIn("Stride Physio has no offer called 'weekend-class'", str(e.exception))
        V.set_call_to_action(self.clinic, b, "ready")
        self.assertTrue(any("The ask" in w and "no offers on file" in w for w in V.check(self.clinic, b).warnings))
        mine = V.new_video(self.bakery, topic="Proofing", identity="person", today="2026-06-11")
        cta = V.set_call_to_action(self.bakery, mine, "comparing", "weekend-class")
        self.assertEqual((cta["text"], cta["link"]), ("Book a Saturday class", "https://example.com/classes"))

    def test_a_regulated_brand_must_carry_its_disclaimer_and_the_builder_puts_it_there(self):
        b = V.new_video(self.clinic, topic="Shin pain", today="2026-06-11")
        b["description"]["answer"] = "Most shin pain in new runners settles when the week is changed, not the shoes."
        V.set_structure(b, "straight-answer", 6, ["Why it starts", "What to change"])
        built = D.build(self.clinic, b)
        self.assertIn(DISCLAIMER, built)
        without = built.replace(DISCLAIMER, "")
        problems, _ = D.check(self.clinic, without, final=True)
        self.assertTrue(any("standing disclaimer" in p for p in problems), problems)
        self.assertNotIn(DISCLAIMER, D.build(self.bakery, self.packaged_bakery_video()))

    def test_structures_are_shares_that_add_up_and_stretch_to_any_length(self):
        for name, spec in V.STRUCTURES.items():
            self.assertEqual(sum(s["share"] for s in spec["segments"]), 100, name)
        b = V.new_video(self.bakery, topic="Proofing", identity="person", today="2026-06-11")
        V.set_structure(b, "countdown", 10, parts=5)
        self.assertEqual(V.counted_parts(b), 5)
        self.assertAlmostEqual(sum(s["share"] for s in b["structure"]["segments"]), 100, places=1)
        short = [c["at"] for c in D.chapters_from_structure(b["structure"])]
        V.set_structure(b, "countdown", 20, parts=5)
        doubled = [c["at"] for c in D.chapters_from_structure(b["structure"])]
        self.assertEqual(len(doubled), len(short))
        for a, twice in zip(short, doubled):
            self.assertLessEqual(abs(twice - 2 * a), 2 * D.ROUND_TO, "twice the length, the same shape")
        self.assertTrue(all(t % D.ROUND_TO == 0 for t in doubled), "planned times are rounded to five seconds")
        with self.assertRaises(YouTubeError) as e:
            V.set_structure(b, "straight-answer", 7, parts=9)
        self.assertIn("between 2 and 4 parts", str(e.exception))


# ============================================================================ description and chapters
class TestChaptersFollowThePlatformsRules(YouTubeCase):
    def test_times_are_written_the_way_the_platform_reads_them(self):
        self.assertEqual([D.stamp(s) for s in (0, 5, 65, 600, 3599, 3600, 3723)],
                         ["00:00", "00:05", "01:05", "10:00", "59:59", "1:00:00", "1:02:03"])
        self.assertEqual([D.to_seconds(t) for t in ("00:00", "4:30", "1:02:03")], [0, 270, 3723])
        for bad in ("4.30", "00:75", "soon", ""):
            with self.assertRaises(YouTubeError):
                D.to_seconds(bad)

    def test_chapters_are_read_back_out_of_a_description(self):
        found = D.parse_chapters("Intro line\n00:00 The question\n04:30 - The poke test\n1:02:03 Late one\n12:345 not a time")
        self.assertEqual(found, [{"at": 0, "title": "The question"}, {"at": 270, "title": "The poke test"},
                                 {"at": 3723, "title": "Late one"}])
        self.assertEqual(D.format_chapters(found).splitlines()[0], "00:00 The question")

    def test_every_rule_that_makes_the_platform_drop_the_chapters_is_a_problem(self):
        good = [{"at": 0, "title": "The question"}, {"at": 60, "title": "Why a clock lies"}, {"at": 200, "title": "The test"}]
        self.assertEqual(D.check_chapters(good, 420), ([], []))
        self.assertTrue(any("00:00" in p for p in D.check_chapters([dict(good[0], at=5)] + good[1:])[0]))
        self.assertTrue(any("at least 3" in p for p in D.check_chapters(good[:2])[0]))
        self.assertTrue(any("only 4 seconds" in p for p in D.check_chapters([good[0], {"at": 4, "title": "x"}, good[2]])[0]))
        self.assertTrue(any("Times must rise" in p for p in D.check_chapters([good[0], good[2], good[1]])[0]))
        self.assertTrue(any("after the video ends" in p for p in D.check_chapters(good, 150)[0]))
        _, warnings = D.check_chapters([good[0], {"at": 60, "title": "Part 2"}, good[2]])
        self.assertTrue(any("Part 2" in w for w in warnings))
        self.assertTrue(D.check_chapters([])[0])

    def test_planned_chapters_start_at_zero_and_skip_segments_that_are_not_chapters(self):
        structure = {"length_minutes": 9, "segments": [{"title": "Cut open", "share": 5}, {"title": "Why", "share": 25},
                                                       {"title": "a breath", "share": 3, "chapter": False},
                                                       {"title": "The test", "share": 40}, {"title": "Saturday", "share": 27}]}
        self.assertEqual(D.format_chapters(D.chapters_from_structure(structure)),
                         "00:00 Cut open\n00:25 Why\n03:00 The test\n06:35 Saturday")
        self.assertEqual(D.chapters_from_structure({}), [])

    def test_the_description_is_in_order_and_is_checked_like_any_other_claim(self):
        b = self.packaged_bakery_video()
        text = D.build(self.bakery, b)
        lines = text.splitlines()
        self.assertEqual(lines[0], "How do I know when dough has proofed enough?")
        self.assertIn("https://example.com/classes", lines[1], "the link is in the first two lines")
        self.assertLess(text.index("Chapters"), text.index("#sourdough"))
        self.assertEqual(D.check(self.bakery, text, keyword=b["keyword"], link="https://example.com/classes"), ([], []))
        problems, _ = D.check(self.bakery, text.replace("at least 18 hours", "at least 36 hours"))
        self.assertTrue(any("36" in p and "does not trace" in p for p in problems), "timestamps are not claims; 36 is")
        problems, _ = D.check(self.bakery, text + "\n" + " ".join("#tag%d" % i for i in range(70)))
        self.assertTrue(any("ignores every one" in p for p in problems))
        problems, _ = D.check(self.bakery, "x" * 5001)
        self.assertTrue(any("allows 5000" in p for p in problems))
        unfinished = D.build(self.bakery, V.new_video(self.bakery, topic="Proofing", identity="person", today="2026-06-12"))
        self.assertTrue(any("TODO" in p for p in D.check(self.bakery, unfinished, final=True)[0]))
        self.assertFalse(any("does not trace" in p for p in D.check(self.bakery, unfinished, final=True)[0]))


# ============================================================================ script and teleprompter
SCRIPT = """# How do I know when dough has proofed enough?

<!-- guidance for the writer: [never spoken] 99 -->
## The question, said aloud
Say: This loaf looked ready. It was **not**. So how do I know when dough has proofed enough?
Show: The dense loaf, cut open, held to the lens.
On screen: Looked ready. Was not.

## Why a clock cannot tell you
Say: Our dough ferments for at least 18 hours, and we still test every batch by hand,
because a warm kitchen and a cold one are different clocks. [hold up the tub]
Show: The dough tub with yesterday's time on the lid.
Source: fact:ferment-18h
"""


class TestTheTeleprompterHoldsOnlyWhatIsSaid(YouTubeCase):
    def make(self, text=SCRIPT):
        b = self.packaged_bakery_video()
        folder = V.video_dir(self.bakery, b["video_id"])
        Path(S.path_for(folder)).write_text(text, encoding="utf-8")
        return b, folder

    def test_spoken_words_only_in_short_lines_with_no_markings(self):
        b, folder = self.make()
        script = S.load(folder)
        self.assertEqual(script.title, "How do I know when dough has proofed enough?")
        self.assertEqual(len(script.spoken()), 2)
        text = S.teleprompter_text(script)
        for forbidden in ("Say:", "Show:", "##", "**", "[", "Source", "99", "lens"):
            self.assertNotIn(forbidden, text)
        self.assertIn("different clocks.", text, "a spoken line that runs on to the next line is kept whole")
        self.assertTrue(all(len(line.split()) <= 10 for line in text.splitlines()))
        self.assertIn("\n\n", text)

    def test_a_stamp_says_whether_the_file_is_current_stale_edited_or_missing(self):
        b, folder = self.make()
        script = S.load(folder)
        self.assertEqual(S.teleprompter_state(folder, {}, script)[0], "missing")
        stamp = S.write_teleprompter(folder, script)
        self.assertEqual(S.teleprompter_state(folder, stamp, script)[0], "current")
        Path(S.path_for(folder, S.TELEPROMPTER_NAME)).write_text("hello\n", encoding="utf-8")
        self.assertEqual(S.teleprompter_state(folder, stamp, script)[0], "edited")
        changed = S.parse(SCRIPT.replace("It was **not**.", "It was nowhere near."))
        self.assertEqual(S.teleprompter_state(folder, stamp, changed)[0], "stale")

    def test_the_script_is_checked_for_facts_names_and_leftover_gaps(self):
        b, folder = self.make()
        problems, warnings = S.check(self.bakery, S.load(folder), b)
        self.assertEqual(problems, [])
        self.assertTrue(any("minutes" in w for w in warnings), "far shorter than the seven minute plan")
        bad = S.parse(SCRIPT.replace("at least 18 hours", "at least 31 hours").replace("This loaf", "Hello, I'm Ava. This loaf")
                      + "\n## What to do next\nSay: TODO\n")
        problems, warnings = S.check(self.bakery, bad, b)
        self.assertTrue(any("31" in p for p in problems))
        self.assertTrue(any("TODO" in p for p in problems))
        self.assertTrue(any("greeting" in w for w in warnings))
        rival = S.parse(SCRIPT.replace("a cold one", "the one at Harbour Street Cafe"))
        self.assertTrue(any("never-mention" in p for p in S.check(self.bakery, rival, b)[0]))

    def test_scripted_needs_a_clean_script_and_a_current_teleprompter(self):
        b, folder = self.make()
        V.set_status(self.bakery, b, "packaged")
        with self.assertRaises(YouTubeError) as e:
            V.set_status(self.bakery, b, "scripted")
        self.assertIn("no teleprompter", str(e.exception))
        b["teleprompter"] = S.write_teleprompter(folder, S.load(folder))
        V.set_status(self.bakery, b, "scripted")
        self.assertEqual(b["status"], "scripted")
        self.assertIn("TODO", S.starter(self.bakery, b), "a starter script never contains invented words")


# ============================================================================ the question slate
class TestTheQuestionSlate(YouTubeCase):
    def build(self, brand=None, csv_text=KEYWORDS_CSV, settings=None):
        brand = brand or self.bakery
        if settings is not None:
            os.makedirs(Q.folder(brand), exist_ok=True)
            Path(Q.folder(brand), Q.SETTINGS_NAME).write_text(json.dumps(settings), encoding="utf-8")
        return Q.build(brand, [self.put("keywords from the café.csv", csv_text)], today="2026-06-11")

    def test_every_phrase_survives_exactly_as_it_was_given(self):
        given = [ln.split(",")[0] for ln in KEYWORDS_CSV.strip().splitlines()[1:]]
        corpus = self.build(settings={"off_topic": ["minecraft"]})
        kept = [m["keyword"] for g in corpus["groups"] for m in g["members"]]
        self.assertEqual(sorted(kept), sorted(given))
        self.assertTrue(all(g["head"] in given for g in corpus["groups"]))
        for g in corpus["groups"]:
            if g["title"]:
                self.assertTrue(T.keeps_keyword(g["title"], g["head"])[0], g["title"])
        awkward = next(g for g in corpus["groups"] if g["head"] == "what does proofing")
        self.assertEqual((awkward["say"], awkward["say_was_repaired"]), ("What does proofing mean?", True))
        self.assertEqual(awkward["members"][0]["keyword"], "what does proofing", "only what is SAID was repaired")

    def test_phrases_that_ask_the_same_thing_become_one_video_and_others_do_not(self):
        corpus = self.build()
        storing = next(g for g in corpus["groups"] if g["head"] == "how to store sourdough bread")
        self.assertEqual([m["keyword"] for m in storing["members"]],
                         ["how to store sourdough bread", "best way to keep sourdough bread"])
        self.assertEqual(storing["volume"], 1200)
        self.assertEqual(Q.group_key("remove mould from bread"), Q.group_key("how to delete mould from the breads")
                         .replace("how:", "other:"), "word order, plurals and small words do not split a video")
        self.assertNotEqual(Q.group_key("how to store sourdough"), Q.group_key("why store sourdough"))
        folded = {"same_meaning": [["starter", "levain"]]}
        self.assertEqual(Q.group_key("how to feed a levain", folded), Q.group_key("how to feed a starter", folded))
        self.assertNotEqual(Q.group_key("how to feed a levain"), Q.group_key("how to feed a starter"),
                            "a trade's own words are joined only when the brand says so")

    def test_flags_come_from_the_brands_own_rules_and_the_verb_matters(self):
        corpus = self.build(settings={"off_topic": ["minecraft"]})
        flags = {g["head"]: g["flags"] for g in corpus["groups"]}
        self.assertEqual(flags["is sourdough gluten-free"], ["never_publish"])
        self.assertEqual(flags["harbour street cafe sourdough price"], ["names_someone_else"])
        self.assertEqual(flags["sourdough minecraft recipe"], ["off_topic"])
        self.assertEqual(flags["how to make a fake sourdough label"], ["harmful"])
        self.assertEqual(flags["how to spot fake sourdough"], [], "spotting a fake is a good video")
        self.assertEqual(flags["what does proofing"], ["cut_off"])
        for g in corpus["groups"]:
            self.assertEqual(g["tier"] == "parked", bool(g["flags"]), g["head"])
        clinic = self.build(self.clinic)                           # the same file, another brand's rules
        theirs = {g["head"]: g["flags"] for g in clinic["groups"]}
        self.assertEqual(theirs["is sourdough gluten-free"], [])
        self.assertEqual(theirs["harbour street cafe sourdough price"], [])

    def test_tiers_and_order_are_stable_run_after_run(self):
        first = self.build()
        again = self.build()
        shuffled = KEYWORDS_CSV.strip().splitlines()
        third = self.build(csv_text="\n".join([shuffled[0]] + shuffled[:0:-1]) + "\n")
        order = [(g["rank"], g["head"], g["tier"], g["score"]) for g in first["groups"]]
        self.assertEqual(order, [(g["rank"], g["head"], g["tier"], g["score"]) for g in again["groups"]])
        self.assertEqual(order, [(g["rank"], g["head"], g["tier"], g["score"]) for g in third["groups"]],
                         "the order of rows in the export changes nothing")
        tiers = {g["head"]: g["tier"] for g in first["groups"]}
        self.assertEqual(tiers["why is my sourdough dense"], "film")
        self.assertEqual(tiers["how to spot fake sourdough"], "batch")
        self.assertEqual(tiers["how long does sourdough take"], "text")
        self.assertEqual([g["tier"] == "parked" for g in first["groups"]], sorted(g["tier"] == "parked" for g in first["groups"]),
                         "what can be made comes first")
        self.assertEqual(first["summary"]["tiers"], {"film": 3, "batch": 2, "text": 1, "parked": 4})
        listed = self.build(settings={"off_topic": ["minecraft"]})
        self.assertEqual(listed["summary"]["tiers"], {"film": 3, "batch": 1, "text": 1, "parked": 5},
                         "a word the brand lists as not its subject parks that phrase")

    def test_any_tools_export_is_read_by_what_its_headings_mean(self):
        other = "Search term;Avg. monthly searches;Competition\nwhy is my sourdough dense;1K - 10K;Low\nbread;;High\n"
        rows = Q.read_keywords(self.put("another tool.csv", other))
        self.assertEqual([(r["keyword"], r["volume"], r["difficulty"], r["volume_estimated"]) for r in rows],
                         [("why is my sourdough dense", 1000, 25, True), ("bread", 0, 75, False)])
        third = Q.read_keywords(self.put("a third tool.csv", "Keyword difficulty,Keyword,Volume\n31,rye starter,40\n"))
        self.assertEqual((third[0]["keyword"], third[0]["difficulty"], third[0]["volume"]), ("rye starter", 31, 40),
                         "a 'keyword difficulty' column is not mistaken for the keyword")
        with self.assertRaises(YouTubeError) as e:
            Q.read_keywords(self.put("no keyword column.csv", "Volume,Difficulty\n10,2\n"))
        self.assertIn("no column that looks like the keyword", str(e.exception))
        windows = self.files / "saved on windows.csv"
        windows.write_bytes("Keyword\tVolume\ncrème brûlée top\t90\n".encode("utf-16"))
        self.assertEqual(Q.read_keywords(str(windows))[0]["keyword"], "crème brûlée top")

    def test_the_review_sheet_is_one_light_file_that_asks_the_internet_for_nothing(self):
        self.build()
        html = Path(Q.folder(self.bakery), Q.REVIEW_NAME).read_text(encoding="utf-8")
        for forbidden in ("http://", "https://", "//cdn", "@import", "url(", "<link", "src=", "prefers-color-scheme",
                          "data-theme"):
            self.assertNotIn(forbidden, html, forbidden)
        self.assertIn("color-scheme:light", html)
        self.assertIn("--ground:#ffffff", html)
        self.assertIn("why is my sourdough dense", html)
        self.assertIn('"brand": "maple-and-main"', html)
        hostile = "Keyword,Volume\n</script><script>alert(1)</script> bread,50\n"
        self.build(self.empty, hostile)
        page = Path(Q.folder(self.empty), Q.REVIEW_NAME).read_text(encoding="utf-8")
        self.assertEqual(page.count("</script>"), 2, "a phrase can never close the page's own script")

    def test_decisions_are_applied_split_out_and_refused_for_the_wrong_brand(self):
        corpus = self.build()
        key = next(g["key"] for g in corpus["groups"] if g["head"] == "how to store sourdough bread")
        odd = next(g["key"] for g in corpus["groups"] if g["head"] == "what does proofing")
        rival = next(g["key"] for g in corpus["groups"] if g["head"] == "harbour street cafe sourdough price")
        rulings = {"brand": "maple-and-main", "decisions": {
            key: {"decision": "approve", "note": "film with the rye loaf", "splits": ["best way to keep sourdough bread"]},
            odd: {"decision": "approve"}, rival: {"decision": "approve"}, "nothing:like+this": {"decision": "park"}}}
        for _attempt in ("before the clinic has a slate", "after"):
            with self.assertRaises(YouTubeError) as e:
                Q.apply_decisions(self.clinic, rulings)
            self.assertIn("not for Stride Physio", str(e.exception))
            self.build(self.clinic)
        with self.assertRaises(YouTubeError) as e:
            Q.load(self.empty)
        self.assertIn("no question slate", str(e.exception))

        counts = Q.apply_decisions(self.bakery, self.put("decisions.json", rulings))
        self.assertEqual((counts["approve"], counts["split"], counts["unknown"]), (3, 1, 1))
        after = {g["head"]: g for g in Q.load(self.bakery)["groups"]}
        self.assertEqual(after["how to store sourdough bread"]["note"], "film with the rye loaf")
        self.assertEqual(len(after["how to store sourdough bread"]["members"]), 1)
        own = after["best way to keep sourdough bread"]
        self.assertEqual((own["split_from"], own["decision"], own["tier"]), ("how to store sourdough bread", "approve", "film"))
        self.assertEqual(after["what does proofing"]["tier"], "film", "a person can overrule a soft flag")
        self.assertEqual(after["harbour street cafe sourdough price"]["tier"], "parked",
                         "a click does not overrule the brand's own never-mention list")
        self.assertEqual(Q.apply_decisions(self.bakery, rulings)["split"], 0, "applying twice splits nothing twice")

        rebuilt = self.build()
        self.assertEqual({g["head"]: g["decision"] for g in rebuilt["groups"]}["what does proofing"], "approve",
                         "decisions survive a rebuild from fresh exports")

    def test_approved_groups_become_videos_with_the_phrase_locked_in(self):
        corpus = self.build()
        rulings = {"brand": "maple-and-main", "decisions": {g["key"]: {"decision": "approve"} for g in corpus["groups"]
                                                            if g["head"] in ("why is my sourdough dense", "how to store sourdough bread")}}
        Q.apply_decisions(self.bakery, rulings)
        made, skipped = Q.make_briefs(self.bakery, "film", identity="person", today="2026-06-11")
        self.assertEqual(sorted(m["head"] for m in made), ["how to store sourdough bread", "why is my sourdough dense"])
        self.assertEqual(skipped, [])
        b = V.load(self.bakery, "2026-06-11-how-to-store-sourdough-bread")
        self.assertEqual(b["keyword"], "how to store sourdough bread")
        self.assertEqual(b["titles"][0]["text"], "How to store sourdough bread")
        self.assertEqual(b["description"]["also_answers"], ["Best way to keep sourdough bread"])
        self.assertTrue(b["source_ref"].startswith("Strategy/youtube-questions/questions.json#"))
        self.assertFalse(any("Topic" in w and "points to" in w for w in V.check(self.bakery, b).warnings))
        self.assertEqual(Q.make_briefs(self.bakery, "film", identity="person", today="2026-06-11")[0], [], "safe to run again")
        with self.assertRaises(YouTubeError):
            Q.make_briefs(self.bakery, "text")

    def test_a_saved_results_page_check_is_folded_in_without_touching_a_network(self):
        from smf.research import store
        corpus = self.build()
        run = store.new_run_dir(self.bakery, "serp", "storing bread", None)
        store.write_json(self.bakery, os.path.join(run, "pages.json"), {"queries": [
            {"query": "how to store sourdough bread", "people_also_ask": ["Can you freeze sourdough?"],
             "results": [{"url": "https://example.com/a", "site": "example.com"}, {"url": "https://example.com/b", "site": "example.com"}]},
            {"query": "best way to keep sourdough bread", "people_also_ask": [],
             "results": [{"url": "https://example.org/x", "site": "example.org"}, {"url": "https://www.youtube.com/watch?v=x", "site": "youtube.com"}]}]})
        store.write_record(self.bakery, run, "serp", {"queries": ["how to store sourdough bread"]})
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")):
            found = Q.enrich_from_results_pages(self.bakery, store.rel(self.bakery, run))
        self.assertEqual(found["groups_touched"], 1)
        g = next(g for g in Q.load(self.bakery)["groups"] if g["head"] == "how to store sourdough bread")
        self.assertEqual(g["also_asked"], ["Can you freeze sourdough?"])
        self.assertEqual(g["results_pages_suggest_split"], ["best way to keep sourdough bread"])
        self.assertEqual(len(g["members"]), 2, "a suggestion changes nothing by itself")
        with self.assertRaises(YouTubeError):
            Q.enrich_from_results_pages(self.clinic, store.rel(self.bakery, run))   # another brand's research
        self.assertTrue(corpus["groups"])

    def test_the_slate_works_when_the_research_tools_are_not_there(self):
        self.build()
        with mock.patch.dict(sys.modules, {"smf.research": None, "smf.research.store": None}):
            with self.assertRaises(YouTubeError) as e:
                Q.enrich_from_results_pages(self.bakery, "Inputs/Research/serp/whatever")
            self.assertIn("works without it", str(e.exception))
            self.assertTrue(Q.load(self.bakery)["groups"])


# ============================================================================ decks
class TestADeckIsTheShowNeverTheScript(YouTubeCase):
    def deck(self, *slides):
        return {"identity": "person", "slides": list(slides)}

    def test_an_honest_deck_passes_for_every_brand(self):
        spec = {"slides": [{"type": "title", "title": "Is the dough *ready*?"}, {"type": "statement", "text": "Watch the dough, not the clock"},
                           {"type": "ask", "title": "Bake it with us", "button": "Book a Saturday class"}]}
        for brand in (self.bakery, self.clinic, self.empty):
            self.assertEqual(DK.validate(brand, spec), ([], []))

    def test_density_errors_name_the_slide_and_say_what_to_do(self):
        problems, _ = DK.validate(self.bakery, self.deck(
            {"type": "title", "title": "Ready?"},
            {"type": "statement", "text": "Flour a finger and press it in a knuckle deep and then watch what the dent does next"},
            {"type": "list", "title": "Remember", "items": ["One", "Two", "Three", "Four", "Five"]},
            {"type": "steps", "title": "The test", "steps": ["Flour a finger", "Press it all the way in until it is a knuckle deep"]},
            {"type": "compare", "left": {"title": "Cold", "items": ["a", "b", "c", "d"]}, "right": {"title": "Hot"}}))
        self.assertTrue(any(p.startswith("Slide 2 (Statement)") and "holds 12 at most" in p and "split it" in p for p in problems), problems)
        self.assertTrue(any(p.startswith("Slide 3 (Short list)") and "5 entries" in p and "2 to 4" in p for p in problems), problems)
        self.assertTrue(any(p.startswith("Slide 4 (Steps)") and "label, not a sentence" in p for p in problems), problems)
        self.assertTrue(any(p.startswith("Slide 5 (Side by side)") and "3 at most on a side" in p for p in problems), problems)
        self.assertFalse(any(p.startswith("Slide 1") for p in problems))

    def test_a_slide_is_refused_for_a_missing_field_an_unknown_kind_or_a_stray_setting(self):
        problems, _ = DK.validate(self.bakery, self.deck({"type": "number", "number": "18h"}, {"type": "pie-chart"},
                                                         {"type": "title", "title": "Ready?", "headline": "oops"}))
        self.assertTrue(any("Slide 1" in p and "needs 'label'" in p for p in problems))
        self.assertTrue(any("Slide 2" in p and "not a kind of slide" in p and "statement" in p for p in problems))
        self.assertTrue(any("Slide 3" in p and "'headline' is not a setting" in p for p in problems))
        self.assertTrue(DK.validate(self.bakery, {"slides": []})[0])

    def test_notes_for_the_people_making_the_video_never_reach_a_slide(self):
        for text in ("0:45 show the loaf", "Hook: the dense loaf", "B-roll of the oven", "The loaf [hold it up]", "Slide 4: the test"):
            problems, _ = DK.validate(self.bakery, self.deck({"type": "statement", "text": text}))
            self.assertTrue(any("only for the viewer" in p for p in problems), text)
            self.assertEqual(len(problems), 1, "said once, for what it is: %s" % problems)

    def test_a_slide_may_not_repeat_the_spoken_line(self):
        script = S.parse(SCRIPT)
        problems, _ = DK.validate(self.bakery, self.deck({"type": "statement", "text": "A warm kitchen and a cold one are different clocks"}), script=script)
        self.assertTrue(any("word for word" in p for p in problems), problems)
        self.assertEqual(DK.validate(self.bakery, self.deck({"type": "statement", "text": "Different kitchens, different clocks"}), script=script)[0], [])

    def test_numbers_trace_or_carry_a_source_and_a_source_alone_is_reported_unverified(self):
        traced = {"type": "number", "number": "18h", "label": "how long our dough ferments"}
        self.assertEqual(DK.validate(self.bakery, self.deck(traced)), ([], []))
        problems, _ = DK.validate(self.bakery, self.deck({"type": "share", "percent": 72, "label": "of home loaves are under-proofed"}))
        self.assertTrue(any("Slide 1" in p and "72" in p and "no source" in p for p in problems), problems)
        problems, unverified = DK.validate(self.bakery, self.deck(
            {"type": "share", "percent": 72, "label": "of home loaves are under-proofed", "source": "A survey we read once"}))
        self.assertEqual(problems, [])
        self.assertTrue(unverified and "cannot confirm" in unverified[0])
        problems, _ = DK.validate(self.empty, {"slides": [traced]})
        self.assertTrue(any("18" in p and "Plain Goods" in p for p in problems), "another brand's fact backs nothing here")
        problems, _ = DK.validate(self.bakery, self.deck({"type": "quote", "text": "I finally get it", "who": "A class regular"}))
        self.assertTrue(any("needs a 'source'" in p for p in problems))

    def test_the_brands_rules_apply_to_slides_and_pictures_stay_inside_the_brand(self):
        problems, _ = DK.validate(self.clinic, self.deck({"type": "statement", "text": "This stretch cures shin splints"}))
        self.assertTrue(any("must never publish" in p for p in problems))
        self.assertEqual(DK.validate(self.bakery, {"slides": [{"type": "statement", "text": "This stretch cures shin splints"}]})[0], [])
        write_png(Path(self.bakery.kit_dir) / "photos" / "loaf.png", (8, 8), (150, 90, 40))
        ok = {"type": "picture", "image": "Brand/brand-kit/photos/loaf.png", "caption": "Under-proofed: tight and heavy", "point": {"x": 50, "y": 40}}
        self.assertEqual(DK.validate(self.bakery, self.deck(ok))[0], [])
        for bad in ("../stride-physio/brand-master.json", "https://example.com/loaf.png", "Brand/brand-kit/photos/missing.png",
                    str(Path(self.clinic.home) / "brand-master.json")):
            problems, _ = DK.validate(self.bakery, self.deck(dict(ok, image=bad)))
            self.assertTrue(problems, bad)
        self.assertTrue(DK.validate(self.clinic, {"slides": [ok]})[0], "the bakery's photo is not the clinic's")


# ============================================================================ thumbnails (no browser needed)
class TestAThumbnailSpecIsCheckedInPlainWords(YouTubeCase):
    def test_words_are_few_and_photos_are_the_brands_own(self):
        self.assertEqual(TH.validate_spec(self.empty, {"layout": "words", "text": "Plain works"}), [])
        problems = TH.validate_spec(self.bakery, {"layout": "words", "text": "This is how you can tell that dough is ready"})
        self.assertTrue(any("5 words at most" in p for p in problems))
        problems = TH.validate_spec(self.bakery, {"layout": "photo-right", "text": "Poke it first"})
        self.assertTrue(any("own photos" in p and "'words', 'versus' or 'number'" in p for p in problems))
        write_png(Path(self.bakery.kit_dir) / "photos" / "loaf.png", (8, 8), (150, 90, 40))
        spec = {"layout": "photo-right", "text": "Poke it first", "photo": "Brand/brand-kit/photos/loaf.png"}
        self.assertEqual(TH.validate_spec(self.bakery, spec), [])
        self.assertTrue(TH.validate_spec(self.clinic, spec), "the clinic cannot use the bakery's photo")
        for bad in ("https://example.com/face.png", "../../stride-physio/Brand/brand-kit/photos/x.png", "brand-master.json"):
            self.assertTrue(TH.validate_spec(self.bakery, dict(spec, photo=bad)), bad)
        self.assertIn("not a thumbnail layout", TH.validate_spec(self.bakery, {"layout": "collage"})[0])
        self.assertTrue(any("'headline' is not a thumbnail setting" in p for p in
                            TH.validate_spec(self.bakery, {"layout": "words", "text": "Ready?", "headline": "x"})))

    def test_a_number_on_a_thumbnail_is_a_claim_and_the_brands_rules_apply(self):
        self.assertEqual(TH.validate_spec(self.bakery, {"layout": "number", "number": "18h", "text": "not a minute less"}), [])
        self.assertTrue(any("72" in p for p in TH.validate_spec(self.bakery, {"layout": "number", "number": "72h", "text": "cold proof"})))
        self.assertTrue(any("must never publish" in p for p in
                            TH.validate_spec(self.clinic, {"layout": "words", "text": "Cures shin splints"})))
        self.assertEqual(TH.validate_spec(self.bakery, {"layout": "words", "text": "Cures shin splints"}), [])

    def test_words_that_repeat_the_title_earn_a_nudge(self):
        self.assertTrue(TH.advice({"layout": "words", "text": "Why sourdough is dense"}, "Why is my sourdough dense?"))
        self.assertEqual(TH.advice({"layout": "words", "text": "Looked ready. Was not."}, "Why is my sourdough dense?"), [])


# ============================================================================ the command line
class TestEveryStepNeedsABrand(YouTubeCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli_youtube(list(args))
        return rc, out.getvalue()

    def test_a_step_with_no_brand_or_an_unknown_one_stops_and_says_so(self):
        for step in ("new", "titles", "set", "check", "thumbnail", "deck", "teleprompter", "status"):
            rc, said = self.run_cli(step)
            self.assertEqual(rc, 2, step)
            self.assertIn("--brand", said)
            self.assertIn("maple-and-main", said, "it lists the brands that exist")
        rc, said = self.run_cli("questions", "status")
        self.assertEqual(rc, 2)
        rc, said = self.run_cli("status", "--brand", "nobody-here")
        self.assertEqual(rc, 1)
        self.assertIn("no brand called 'nobody-here'", said)
        self.assertNotIn("Traceback", said)
        self.assertEqual(self.run_cli()[0], 2)

    def test_the_whole_package_can_be_built_from_the_command_line(self):
        rc, said = self.run_cli("new", "--brand", "maple-and-main", "--topic", "Knowing when dough has proofed", "--identity", "person",
                                "--keyword", "how do i know when dough has proofed enough", "--source-ref", "audience.questions_they_ask[0]")
        self.assertEqual(rc, 0, said)
        self.assertIn("never to be reworded", said)
        self.assertIn("Demand has not been checked", said)
        vid = V.list_ids(self.bakery)[0]
        for tail in ("the poke test, filmed", "for home bakers"):
            self.assertEqual(self.run_cli("titles", "--brand", "maple-and-main", "--video", vid, "--from-keyword", "--tail", tail)[0], 0)
        self.assertEqual(self.run_cli("titles", "--brand", "maple-and-main", "--video", vid, "--from-keyword")[0], 0)
        rc, said = self.run_cli("titles", "--brand", "maple-and-main", "--video", vid, "--add", "When is dough ready? Ask Harbour Street Cafe")
        self.assertEqual(rc, 1)
        self.assertIn("was not added", said)
        self.assertEqual(self.run_cli("titles", "--brand", "maple-and-main", "--video", vid, "--choose", "3")[0], 0)

        rc, said = self.run_cli("set", "--brand", "maple-and-main", "--video", vid, "--stage", "ready", "--offer", "no-such-offer",
                                "--tags", "sourdough")
        self.assertEqual(rc, 1)
        self.assertIn("Nothing was saved", said)
        self.assertEqual(V.load(self.bakery, vid)["tags"], [], "a refused step saves none of its parts")

        hook = self.put("hook.json", {"promise": "how to tell dough is ready", "say": "This loaf looked ready. It was not.",
                                      "show": "The dense loaf, cut open.", "on_screen": "Looked ready. Was not."})
        desc = self.put("desc.json", {"answer": "Dough is ready when a floured finger pressed a knuckle deep leaves a dent that fills "
                                                "back slowly. If it springs straight back, it needs longer. If it stays, it has gone too "
                                                "far. Our own dough ferments for at least 18 hours, and we still test every batch by hand.",
                                      "hashtags": ["sourdough", "homebaking", "bread"]})
        rc, said = self.run_cli("set", "--brand", "maple-and-main", "--video", vid, "--hook", hook, "--description", desc,
                                "--structure", "straight-answer", "--minutes", "7", "--parts", "Why a clock lies|The poke test|When it misleads",
                                "--stage", "comparing", "--offer", "weekend-class", "--tags", "sourdough, proofing")
        self.assertEqual(rc, 0, said)
        thumbs = self.put("thumbs.json", [{"layout": "words", "text": "Looked ready.\nWas not.", "accent": "not"}])
        self.assertEqual(self.run_cli("thumbnail", "--brand", "maple-and-main", "--video", vid, "--spec", thumbs, "--check")[0], 0)
        self.assertEqual(self.run_cli("thumbnail", "--brand", "maple-and-main", "--video", vid, "--choose", "a")[0], 0)
        rc, said = self.run_cli("check", "--brand", "maple-and-main", "--video", vid, "--final")
        self.assertEqual(rc, 0, said)
        self.assertEqual(self.run_cli("status", "--brand", "maple-and-main", "--video", vid, "--set", "packaged")[0], 0)

        rc, said = self.run_cli("check", "--brand", "stride-physio", "--video", vid)
        self.assertEqual(rc, 1, "the clinic cannot see the bakery's video")
        self.assertIn("Stride Physio has no video", said)
        rc, said = self.run_cli("status", "--brand", "maple-and-main")
        self.assertIn("packaged", said)

    def test_the_question_steps_run_from_the_command_line(self):
        export = self.put("keywords.csv", KEYWORDS_CSV)
        rc, said = self.run_cli("questions", "build", "--brand", "maple-and-main", "--file", export)
        self.assertEqual(rc, 0, said)
        self.assertIn("possible videos", said)
        corpus = Q.load(self.bakery)
        key = next(g["key"] for g in corpus["groups"] if g["head"] == "why is my sourdough dense")
        decisions = self.put("decisions.json", {"brand": "maple-and-main", "decisions": {key: {"decision": "approve"}}})
        self.assertEqual(self.run_cli("questions", "apply", "--brand", "maple-and-main", "--decisions", decisions)[0], 0)
        rc, said = self.run_cli("questions", "apply", "--brand", "stride-physio", "--decisions", decisions)
        self.assertEqual(rc, 1)
        rc, said = self.run_cli("questions", "briefs", "--brand", "maple-and-main", "--identity", "person")
        self.assertIn("why is my sourdough dense", said)
        self.assertEqual(len(V.list_ids(self.bakery)), 1)
        self.assertEqual(self.run_cli("questions", "status", "--brand", "maple-and-main")[0], 0)
        self.assertEqual(self.run_cli("deck", "--brand", "maple-and-main", "--types")[0], 0)
        self.assertEqual(self.run_cli("titles", "--brand", "maple-and-main", "--patterns", "--job", "search")[0], 0)


# ============================================================================ really drawing (needs the browser)
@needs_browser
@needs_pillow
class TestPicturesReallyDraw(YouTubeCase):
    def looks_drawn(self, path, size):
        from PIL import Image
        with Image.open(path) as im:
            self.assertEqual(im.size, size, path.name)
            colours = im.convert("RGB").getcolors(maxcolors=1 << 24)
        self.assertGreater(len(colours), 40, "%s looks blank" % path.name)
        self.assertGreater(Path(path).stat().st_size, 4000)

    def test_a_thumbnail_draws_for_the_bakery_and_for_an_empty_brand_offline_and_legibly(self):
        out = Path(self.tmp.name) / "thumbs for the café"
        specs = [{"name": "a", "layout": "words", "text": "Looked ready.\nWas not.", "accent": "not"},
                 {"name": "b", "layout": "versus", "left": {"text": "Cold oven"}, "right": {"text": "Hot oven"}, "ground": "main"},
                 {"name": "c", "layout": "number", "number": "18h", "text": "not a minute less", "ground": "main"}]
        files, report = TH.render(self.bakery, specs, out / "bakery")
        self.assertEqual([f.name for f in files], ["thumb-a.png", "thumb-a-small.png", "thumb-b.png", "thumb-b-small.png",
                                                   "thumb-c.png", "thumb-c-small.png"])
        self.assertEqual(report["network_requests"], [])
        self.assertTrue(report["all_legible"], report["thumbnails"])
        for row in report["thumbnails"]:
            self.assertGreaterEqual(row["contrast"], TH.MIN_CONTRAST, row)
            self.assertGreaterEqual(row["text_height"], TH.MIN_TEXT_HEIGHT, row)
        self.looks_drawn(files[0], (1280, 720))
        self.looks_drawn(files[1], (320, 180))

        files, report = TH.render(self.empty, [{"layout": "words", "text": "Plain works", "accent": "works"}], out / "empty")
        self.looks_drawn(files[0], (1280, 720))
        self.assertEqual(report["network_requests"], [])
        self.assertTrue(report["all_legible"])
        self.assertTrue(all("built-in" in f for f in report["fonts"].values()), "an empty brand needs no fonts of its own")

    def test_the_small_size_check_really_measures_the_pixels(self):
        from PIL import Image, ImageDraw
        faint = Path(self.tmp.name) / "faint.png"
        im = Image.new("RGB", (1280, 720), (250, 250, 250))
        ImageDraw.Draw(im).rectangle((100, 200, 900, 420), fill=(225, 225, 225))
        im.save(faint)
        measured = TH.measure_small(faint, [(72, 56, 1136, 560)])
        self.assertFalse(measured["legible"])
        self.assertIn("only stand out", measured["why"])
        tiny = Path(self.tmp.name) / "tiny.png"
        im = Image.new("RGB", (1280, 720), (250, 250, 250))
        ImageDraw.Draw(im).rectangle((100, 200, 900, 228), fill=(10, 10, 10))
        im.save(tiny)
        measured = TH.measure_small(tiny, [(72, 56, 1136, 560)])
        self.assertFalse(measured["legible"])
        self.assertIn("pixels tall", measured["why"])

    def test_a_three_slide_deck_draws_for_the_bakery_and_for_an_empty_brand(self):
        spec = {"name": "proofing", "identity": "person", "slides": [
            {"type": "title", "title": "Is the dough *ready*?", "sub": "One test. Ten seconds."},
            {"type": "steps", "title": "The poke test", "steps": ["Flour a finger", "Press a knuckle deep", "Watch it come back"]},
            {"type": "ask", "title": "Bake it *with us*", "button": "Book a Saturday class"}]}
        for brand, folder in ((self.bakery, "bakery deck"), (self.empty, "empty deck")):
            use = dict(spec, identity="person" if brand is self.bakery else "company")
            files, report = DK.render(brand, use, Path(self.tmp.name) / folder)
            self.assertEqual([f.name for f in files], ["proofing-01-title.png", "proofing-02-steps.png", "proofing-03-ask.png",
                                                       "proofing.pdf", "contact-sheet.png"])
            self.assertEqual(report["network_requests"], [])
            self.assertEqual(report["headings_in_order"], ["Is the dough ready?", "The poke test", "Bake it with us"])
            for png in files[:3]:
                self.looks_drawn(png, (1920, 1080))
            self.assertEqual(files[3].read_bytes()[:5], b"%PDF-")
            self.assertGreater(files[3].stat().st_size, 10000)
            self.assertTrue(files[4].is_file())
            self.assertEqual(json.loads((Path(report["folder"]) / DK.REPORT_NAME).read_text(encoding="utf-8"))["brand"], brand.id)

    def test_a_line_that_cannot_fit_stops_the_deck_and_leaves_nothing_half_made(self):
        out = Path(self.tmp.name) / "too long"
        spec = {"slides": [{"type": "title", "title": "Ready?"},
                           {"type": "number", "number": "1" * 8, "label": "Pneumonoultramicroscopicsilicovolcanoconiosisly"
                                                                          "antidisestablishmentarianismsupercalifragilistic", "source": "x"}]}
        with self.assertRaises(YouTubeError) as e:
            DK.render(self.empty, spec, out)
        self.assertIn("Slide 2", str(e.exception))
        self.assertEqual(list(out.glob("*.png")), [])

    def test_the_command_line_draws_into_the_videos_own_folder(self):
        b = V.new_video(self.bakery, topic="Proofing", identity="person", today="2026-06-11")
        thumbs = self.put("thumbs.json", [{"layout": "words", "text": "Looked ready.\nWas not."}])
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli_youtube(["thumbnail", "--brand", "maple-and-main", "--video", b["video_id"], "--spec", thumbs])
        self.assertEqual(rc, 0, out.getvalue())
        folder = Path(V.video_dir(self.bakery, b["video_id"])) / "thumbnails"
        self.assertTrue((folder / "thumb-a.png").is_file() and (folder / "thumb-a-small.png").is_file())
        self.assertIn("reads at feed size", out.getvalue())
        self.assertFalse(re.search(r"/(Users|home|tmp|var)/", out.getvalue()), "no file paths at the person")



class TestAWronglyShapedThumbnailSpecIsExplained(unittest.TestCase):
    def test_a_side_written_as_plain_words_is_explained_not_crashed(self):
        from smf import brands
        from smf.youtube import thumbnail
        brand = brands.load("maple-and-main")
        problems = thumbnail.validate_spec(brand, {"layout": "versus", "left": "4 hours", "right": "18 hours"})
        self.assertTrue(any("left side" in p for p in problems), problems)
        self.assertTrue(any("right side" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
