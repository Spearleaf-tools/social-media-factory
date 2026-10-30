"""Sourcing honesty: a claim only counts as checked when the brand's own files really say it.

`passed` has to mean that nothing in the post was taken on trust. These tests cover the ways a
claim used to slip through with that label: a number that matched a different kind of number,
research nobody had confirmed, claims with no digits in them, words outside the caption, words
inside a picture, and a redraw that could remove pictures somebody had already approved.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf.studio import batch_cli, contract, grounding, render, topics     # noqa: E402
from smf.studio import posts as P                                         # noqa: E402
from smf.studio.lint import Rules                                         # noqa: E402
from tests.test_render import RenderCase                                  # noqa: E402
from tests.test_writing import GOOD_DRAFT, WritingCase                    # noqa: E402

OPENING = "Here is why your loaf comes out flat.\n\n"
CLOSING = "\n\nWeigh the flour instead of scooping it."


class SourcingCase(WritingCase):
    def check(self, text, topic=None, identity="person", platform="linkedin", **kw):
        return contract.validate_draft(text, self.brand, identity, platform, topic or self.approved(lane="opinion"), **kw)

    def research(self, name, text):
        path = Path(self.brand.path("Inputs", "Research", name))
        path.write_text(text, encoding="utf-8")
        return path


# =============================================================================== 8. value, kind and context
class TestANumberNeedsTheSameKindAndTheSameSubject(SourcingCase):
    def setUp(self):
        super().setUp()
        self.facts()

    def test_hours_in_the_files_do_not_back_a_percentage_in_the_draft(self):
        report = grounding.ground_draft("We saved customers 18%.", self.brand)
        self.assertFalse(report["ok"])
        self.assertEqual(report["ungrounded"], ["18"])
        self.assertEqual(len(report["hints"]), 1)
        self.assertIn("18%", report["hints"][0])
        self.assertIn("We proof our sourdough for 18 hours.", report["hints"][0])
        checked = self.check(OPENING + "We saved customers 18%." + CLOSING)
        self.assertEqual((checked["ok"], checked["sourcing"]), (False, "blocked"))
        self.assertTrue(any("18%" in p and "hours" in p for p in checked["problems"]), checked["problems"])

    def test_the_same_kind_about_something_else_is_left_to_the_person(self):
        report = grounding.ground_draft("We saved customers 18 hours.", self.brand)
        self.assertTrue(report["ok"])                                       # the number is in the files...
        self.assertEqual(len(report["unconfirmed"]), 1)                     # ...but not about this
        self.assertIn("18 hours", report["unconfirmed"][0])
        self.assertIn("We proof our sourdough for 18 hours.", report["unconfirmed"][0])
        number = report["numbers"][0]
        self.assertEqual((number["grounded"], number["confirmed"]), (True, False))
        self.assertEqual(number["provenance"][0]["ref"], "fact-1")           # the evidence it resembles is carried
        checked = self.check(OPENING + "We saved customers 18 hours." + CLOSING)
        self.assertEqual((checked["ok"], checked["sourcing"]), (True, "unverified"))
        self.assertTrue(any("18 hours" in w and "Ava's recipe card" in w for w in checked["warnings"]), checked["warnings"])

    def test_the_honest_sentence_still_passes_however_the_unit_is_written(self):
        for said in ("We proof our sourdough for 18 hours.", "Our dough gets an 18-hour proof.",
                     "We proof the sourdough 18h.", "Proofing takes 18 hrs here."):
            report = grounding.ground_draft(said, self.brand)
            self.assertEqual((report["ok"], report["unconfirmed"]), (True, []), said)
        self.assertEqual(self.check(GOOD_DRAFT, topic=self.approved())["sourcing"], "passed")

    def test_a_short_line_borrows_its_subject_from_the_lines_around_it(self):
        report = grounding.ground_draft("Our sourdough takes its time.\n18 hours.\nThat is the whole proof.", self.brand)
        self.assertEqual((report["ok"], report["unconfirmed"]), (True, []))

    def test_money_percentages_and_plain_counts_do_not_stand_in_for_each_other(self):
        grounding.add_fact(self.brand, "Bread Club members save $1,200 a year.", "the till report for 2025")
        grounding.add_fact(self.brand, "35% of our class places go to people who came before.", "class sign-up sheets")
        self.assertTrue(grounding.ground_draft("Bread Club members save $1,200 a year.", self.brand)["ok"])
        self.assertTrue(grounding.ground_draft("Members of the Bread Club save 1,200 dollars a year.", self.brand)["ok"])
        self.assertEqual(grounding.ground_draft("The Bread Club has 1,200 members.", self.brand)["ungrounded"], ["1,200"])
        self.assertTrue(grounding.ground_draft("35 percent of class places go to people who came before.", self.brand)["ok"])
        self.assertEqual(grounding.ground_draft("We have 35 people in every class.", self.brand)["ungrounded"], ["35"])

    def test_a_value_written_beside_a_fact_takes_its_kind_from_the_sentence(self):
        grounding.add_fact(self.brand, "A class lasts four hours and takes eight people.", "the booking page", values=[4, 8])
        self.assertTrue(grounding.ground_draft("A class lasts 4 hours and takes 8 people.", self.brand)["ok"])
        self.assertEqual(grounding.ground_draft("A class costs 4% more this year.", self.brand)["ungrounded"], ["4"])

    def test_numbers_that_only_organise_the_post_still_need_nothing(self):
        report = grounding.ground_draft("3 checks before bake day.\n1. Flour weight.\n2. Water.\nStep 3: wait.", self.brand)
        self.assertEqual((report["ok"], report["unconfirmed"]), (True, []))
        self.assertEqual(grounding.extract_numbers("Open at 10am. Vitamin B12. An MP3 file."), [])


# =============================================================================== 9. research nobody confirmed
class TestUnconfirmedResearchNeverGrantsAPass(SourcingCase):
    DRAFT = OPENING + "97% of home bakers give up after one flat loaf." + CLOSING

    def test_a_row_marked_unverified_with_no_source_is_background_only(self):
        self.research("rumours.csv", "claim,source,confidence\n"
                                     "\"97% of home bakers give up after one flat loaf\",,unverified\n")
        report = grounding.ground_draft("97% of home bakers give up after one flat loaf.", self.brand)
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["unconfirmed"]), 1)
        self.assertIn("97%", report["unconfirmed"][0])
        self.assertIn("rumours.csv", report["unconfirmed"][0])
        checked = self.check(self.DRAFT)
        self.assertEqual((checked["ok"], checked["sourcing"]), (True, "unverified"))
        self.assertTrue(any("has not been confirmed" in w for w in checked["warnings"]), checked["warnings"])

    def test_a_file_name_is_not_a_source_and_low_confidence_is_not_confidence(self):
        self.research("no source column.csv", "note,finding\nx,97% of home bakers give up after one flat loaf\n")
        self.assertEqual(self.check(self.DRAFT)["sourcing"], "unverified")
        self.research("no source column.csv", "finding,source,confidence\n"
                                              "97% of home bakers give up after one flat loaf,Invented Baking Survey,low\n")
        self.assertEqual(self.check(self.DRAFT)["sourcing"], "unverified")
        self.research("no source column.csv", "finding,source\n97% of home bakers give up after one flat loaf,unknown\n")
        self.assertEqual(self.check(self.DRAFT)["sourcing"], "unverified")

    def test_a_sourced_row_still_passes_and_a_confirmed_source_wins_over_a_rumour(self):
        self.research("rumours.csv", "claim,source,confidence\n"
                                     "\"97% of home bakers give up after one flat loaf\",,unverified\n")
        self.research("survey.csv", "finding,source,confidence\n"
                                    "97% of home bakers give up after one flat loaf,Invented Baking Survey,high\n")
        checked = self.check(self.DRAFT)
        self.assertEqual(checked["sourcing"], "passed", checked["warnings"])
        self.assertTrue(any("Invented Baking Survey" in w for w in checked["warnings"]))

    def test_the_writer_is_not_offered_an_unconfirmed_number_as_a_fact(self):
        self.research("rumours.csv", "claim,source,confidence\n"
                                     "\"97% of home bakers give up after one flat loaf\",,unverified\n")
        built = contract.build_contract(self.brand, "person", "linkedin", self.approved(), "three-tips", "reach")
        self.assertNotIn(97.0, built["facts"]["numbers_you_may_state"])
        self.assertIn("NOT CONFIRMED", built.markdown)
        self.assertIn("The only numbers you may state: none.", built.markdown)


# =============================================================================== 10. claims without digits
BAKERY_EVERYDAY = [
    "We grew up baking.", "Save the date.", "Best before Friday.", "Cut the dough in half before shaping.",
    "Half a cup of flour is enough.", "We bake twice a day.", "Double-check the oven before the loaf goes in.",
    "You won't regret weighing the flour.", "We saved you a seat by the window.", "Bread is best in the first two days.",
    "Rest the dough for five minutes, then fold it.", "The first half hour in the oven matters most.",
    "We grew our starter from rye flour.", "I cut the first slice while it was still warm.",
]
CLINIC_EVERYDAY = [
    "Hold the stretch for a slow count, then rest.", "Book an assessment if the pain keeps coming back.",
    "Most runners skip the warm-up.", "We saved you a spot on Saturday.", "Pain that improved overnight can still return.",
    "Run twice a week before you add a third day.", "I increased the incline a little at a time.",
    "Your calf is not the winner of this argument.",
]
INVENTED = [
    ("We won the regional bakery award.", "won"),
    ("Maple & Main was voted best bakery in town.", "voted"),
    ("We were featured in the county gazette.", "featured in"),
    ("Every loaf comes with a money-back guarantee.", "guarantee"),
    ("We are certified by the national bread board.", "certified"),
    ("We doubled our sales last year.", "doubled"),
    ("Half of our customers come back every week.", "Half of our customers"),
    ("Dozens of cafes order from us.", "Dozens of"),
    ("Two thirds of our regulars bake at home.", "Two thirds of"),
    ("We bake twice as many loaves as last year.", "twice as"),
]


class TestClaimsWithNoDigitsInThem(SourcingCase):
    def test_everyday_sentences_from_a_bakery_and_a_clinic_are_not_claims(self):
        for line in BAKERY_EVERYDAY + CLINIC_EVERYDAY:
            self.assertEqual(grounding.wording_claims(line), [], line)
        ordinary = "Here is how to keep a starter alive.\n\n" + "\n".join(BAKERY_EVERYDAY[:9])
        checked = self.check(ordinary)
        self.assertEqual(checked["sourcing"], "passed", checked["warnings"] + checked["problems"])

    def test_an_invented_achievement_or_result_is_unverified_even_with_a_valid_topic_pointer(self):
        for line, phrase in INVENTED:
            found = grounding.wording_claims(line)
            self.assertEqual(len(found), 1, line)
            self.assertIn(phrase.lower(), found[0]["phrase"].lower(), line)
            checked = self.check(OPENING + line + CLOSING, topic=self.approved())
            self.assertEqual((checked["ok"], checked["sourcing"]), (True, "unverified"), line)
            self.assertTrue(any(found[0]["phrase"] in w and "take it out" in w for w in checked["warnings"]),
                            (line, checked["warnings"]))

    def test_a_number_written_in_words_is_traced_like_a_number_written_in_digits(self):
        self.facts()
        checked = self.check(OPENING + "Our revenue grew eighteen percent." + CLOSING)
        self.assertEqual(checked["sourcing"], "blocked")
        self.assertTrue(any("eighteen percent" in p for p in checked["problems"]), checked["problems"])
        self.assertTrue(self.check(OPENING + "We proof our sourdough for eighteen hours." + CLOSING)["ok"])
        self.assertEqual(self.check(OPENING + "We proof our sourdough for eighteen hours." + CLOSING)["sourcing"], "passed")
        small = grounding.ground_draft("Bake the two loaves for forty minutes. The three of us agree.", self.brand)
        self.assertEqual([n["raw"] for n in small["numbers"]], ["forty"])     # small words describe; they do not claim

    def test_the_brands_own_files_confirm_the_same_claims(self):
        grounding.add_fact(self.brand, "We won the regional bakery award in the spring.", "the certificate by the till")
        grounding.add_fact(self.brand, "50% of our customers come back every week.", "the loyalty card count")
        grounding.add_fact(self.brand, "Sales doubled between our first and second year.", "the accounts")
        for line in ("We won the regional bakery award.", "Half of our customers come back every week.",
                     "We doubled our sales in our second year."):
            checked = self.check(OPENING + line + CLOSING)
            self.assertEqual(checked["sourcing"], "passed", (line, checked["warnings"]))
        other = self.check(OPENING + "We won the national pastry award." + CLOSING)
        self.assertEqual(other["sourcing"], "unverified")                    # a different award is a different claim

    def test_what_the_brand_says_about_itself_and_linked_proof_count_too(self):
        clinic = self.clinic()
        clinic.data["identities"][0]["credential_line"] = "Chartered physiotherapist, certified in sports rehabilitation"
        draft = "Here is how to return to running.\n\nTomas is certified in sports rehabilitation.\n\nStart with a walk."
        topic = self.approved(lane="opinion", source_ref="what Tomas says in the clinic")
        report = contract.validate_draft(draft, clinic, "person", "instagram", topic)
        self.assertEqual(report["sourcing"], "passed", report["warnings"])
        self.add_proof(self.brand, "PRF-0009", "Winner, county bread award", "Best sourdough at the county show.")
        unlinked = self.check(OPENING + "We won the county bread award." + CLOSING)
        self.assertEqual(unlinked["sourcing"], "unverified")
        linked = self.check(OPENING + "We won the county bread award." + CLOSING, proof_ids=["PRF-0009"])
        self.assertEqual(linked["sourcing"], "passed", linked["warnings"])


# =============================================================================== 11. every publishable field
class TestEveryWordThatPublishesIsChecked(SourcingCase):
    def setUp(self):
        super().setUp()
        self.facts()
        self.draft = Path(self.tmp.name) / "draft.txt"
        self.draft.write_text(GOOD_DRAFT, encoding="utf-8")
        topics.add_topics(self.brand, "week-1", [topics.new_topic(
            "Why a loaf comes out flat", source_ref="audience.questions_they_ask[1]")])
        self.topic = topics.load_run(self.brand, "week-1")[0]["topic_id"]
        topics.set_status(self.brand, "week-1", self.topic, "approved")

    def posts(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = batch_cli.main(list(args))
        return code, out.getvalue()

    def add(self, *extra):
        return self.posts("add", "--brand", self.brand.id, "--batch", "week-1", "--identity", "person",
                          "--platform", "linkedin", "--draft", str(self.draft),
                          "--run", "week-1", "--topic", self.topic, *extra)

    def batch(self):
        return P.load_batch(self.brand.path("Output", "batches", "week-1.json"), self.brand.id)[0]

    def test_the_first_comment_and_the_alt_text_are_part_of_the_draft_check(self):
        clean = self.check(GOOD_DRAFT, first_comment="Classes are on Saturdays.", alt_text="A torn sourdough loaf.")
        self.assertEqual(clean["sourcing"], "passed", clean["warnings"])
        for field, said in (("first_comment", "the first comment"), ("alt_text", "the alt text")):
            report = self.check(GOOD_DRAFT, **{field: "We increased revenue by 987%."})
            self.assertEqual((report["ok"], report["sourcing"]), (False, "blocked"), field)
            self.assertTrue(any("987" in p for p in report["problems"]), field)
            self.assertTrue(any(said in p for p in report["problems"]), (field, report["problems"]))
        named = self.check(GOOD_DRAFT, first_comment="We supply Harbour Street Cafe.")
        self.assertTrue(any("never-mention" in p for p in named["problems"]))

    def test_posts_add_refuses_a_claim_hidden_in_the_first_comment(self):
        code, said = self.add("--first-comment", "We increased revenue by 987%.")
        self.assertEqual(code, 1)
        self.assertIn("987", said)
        self.assertIn("Not added", said)
        code, said = self.add("--first-comment", "We increased revenue by 987%.", "--allow-problems")
        self.assertEqual(code, 0)
        self.assertEqual(self.batch()[0].sourcing, "blocked")

    def test_a_clean_first_comment_is_added_as_passed(self):
        code, said = self.add("--first-comment", "Classes are on Saturdays.", "--alt-text", "A torn sourdough loaf.")
        self.assertEqual(code, 0, said)
        self.assertEqual(self.batch()[0].sourcing, "passed")

    def test_the_copy_rules_reach_the_first_comment_and_the_alt_text(self):
        post = P.Post(id="a", brand=self.brand.id, identity="person", platform="linkedin", text="Weigh the flour.",
                      first_comment="We supply Harbour Street Cafe.", alt_text="A loaf #sourdough")
        post.lint(Rules.for_brand(self.brand))
        self.assertTrue(any("never-mention" in e and "first comment" in e for e in post.lint_errors), post.lint_errors)
        self.assertTrue(any("no-tags" in e and "alt text" in e for e in post.lint_errors), post.lint_errors)

    def test_words_changed_after_the_fact_check_lose_their_pass(self):
        self.assertEqual(self.add("--first-comment", "Classes are on Saturdays.")[0], 0)
        path = self.brand.path("Output", "batches", "week-1.json")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(data["posts"][0]["sourcing"], "passed")
        data["posts"][0]["first_comment"] = "We won the regional bakery award."
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        self.posts("check", "--brand", self.brand.id, "--batch", "week-1")
        post = self.batch()[0]
        self.assertEqual(post.sourcing, "unverified")
        self.assertTrue(any("changed after the facts were checked" in w for w in post.lint_warnings), post.lint_warnings)

    def test_a_verdict_cannot_be_carried_onto_different_words(self):
        report = self.check(GOOD_DRAFT)
        post = P.Post(id="a", brand=self.brand.id, identity="person", platform="linkedin", text=GOOD_DRAFT,
                      first_comment="We won the regional bakery award.")
        with self.assertRaises(contract.ContractError):
            contract.apply_to_post(post, report)


# =============================================================================== 12 and 19. pictures
class FakeRenderer(object):
    """Stands in for the browser: writes a small file per slide, or refuses the slide it is told to."""

    def __init__(self, fail_on=None):
        self.refused, self.calls, self.fail_on, self.pages = [], 0, fail_on, []

    def render(self, page_html, out_path, size=(1080, 1350), label="This picture"):
        self.calls += 1
        self.pages.append(page_html)
        if self.calls == self.fail_on:
            raise render.RenderError("%s, headline: this line is too long to fit." % label)
        Path(out_path).write_bytes(("NEW %s" % label).encode("utf-8"))
        return {"shrunk": [], "fonts": []}


class PictureCase(RenderCase):
    def stat_spec(self, **slide):
        card = {"stat": "97%", "headline": "of our class places sell out in a day."}
        card.update(slide)
        return {"format": "stat", "identity": "person", "name": "sell out", "slides": [card]}

    def draw(self, spec, folder="cards", brand=None, **kw):
        return render.render_with_report(brand or self.bakery, spec, self.out / folder, renderer=FakeRenderer(**kw))


class TestWordsInsidePicturesAreChecked(PictureCase):
    def claims(self, report):
        return [c for image in report["picture_claims"] for c in image["checked"]]

    def test_the_report_lists_every_claim_a_picture_makes_and_whether_it_was_confirmed(self):
        _files, report = self.draw(self.stat_spec())
        self.assertEqual([i["file"] for i in report["picture_claims"]], report["files"])
        found = self.claims(report)
        self.assertEqual([(c["phrase"], c["confirmed"]) for c in found], [("97%", False)])
        self.assertTrue(any("97%" in w for w in report["warnings"]))
        saved = json.loads((self.out / "cards" / render.REPORT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(saved["picture_claims"], report["picture_claims"])

    def test_writing_a_source_on_the_card_does_not_make_the_number_true(self):
        _files, report = self.draw(self.stat_spec(source="a survey we read somewhere"))
        self.assertEqual([c["confirmed"] for c in self.claims(report)], [False])
        self.assertTrue(any("a survey we read somewhere" in w and "cannot confirm" in w for w in report["warnings"]),
                        report["warnings"])

    def test_a_pointer_counts_only_when_it_resolves_and_holds_that_number(self):
        other = grounding.add_fact(self.bakery, "We proof our sourdough for 18 hours.", "Ava's recipe card")
        for pointer in ("fact:" + other["id"], "fact:no-such-fact", "proof:PRF-0404"):
            _files, report = self.draw(self.stat_spec(source=pointer), folder="bad " + pointer.replace(":", " "))
            self.assertEqual([c["confirmed"] for c in self.claims(report)], [False], pointer)
        # A fact with that figure, about something else: the card is not confirmed by accident...
        fact = grounding.add_fact(self.bakery, "97% of our bread is sold before noon.", "the till report")
        _files, report = self.draw(self.stat_spec(), folder="no pointer")
        self.assertEqual([c["confirmed"] for c in self.claims(report)], [False])
        # ...and the pointer is what says which fact the number is.
        renderer = FakeRenderer()
        _files, report = render.render_with_report(self.bakery, self.stat_spec(source="fact:" + fact["id"]),
                                                   self.out / "pointer", renderer=renderer)
        self.assertEqual([c["confirmed"] for c in self.claims(report)], [True])
        self.assertEqual(report["warnings"], [])
        self.assertIn("Source: the till report", renderer.pages[0])              # people see the real source...
        self.assertNotIn("fact:", renderer.pages[0])                             # ...never the pointer

    def test_a_number_the_brands_files_already_back_needs_no_pointer(self):
        grounding.add_fact(self.bakery, "97% of our class places sell out within a day.", "class sign-up sheets")
        _files, report = self.draw(self.stat_spec())
        self.assertEqual([c["confirmed"] for c in self.claims(report)], [True])

    def test_claims_with_no_digits_are_found_on_pictures_too(self):
        spec = {"format": "headline", "identity": "person", "slides": [{"headline": "We won the regional bakery award."}]}
        _files, report = self.draw(spec)
        self.assertEqual([c["confirmed"] for c in self.claims(report)], [False])


class TestAttachingPicturesFoldsTheirClaimsIntoThePost(PictureCase):
    def setUp(self):
        super().setUp()
        grounding.add_fact(self.bakery, "We proof our sourdough for 18 hours.", "Ava's recipe card")
        self.path = self.bakery.path("Output", "batches", "week-1.json")
        report = contract.validate_draft(GOOD_DRAFT, self.bakery, "person", "instagram", {"lane": "opinion"})
        self.post = P.Post(id="p1", brand=self.bakery.id, identity="person", platform="instagram", text=GOOD_DRAFT)
        contract.apply_to_post(self.post, contract.validate_draft(
            GOOD_DRAFT, self.bakery, "person", "instagram",
            {"lane": "opinion", "status": "approved", "source_ref": "what Ava says at the counter"}))
        self.assertEqual(self.post.sourcing, "passed", report["warnings"])
        P.save_batch([self.post], self.path)

    def attach(self, *media, replace=False):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = batch_cli.main(["attach", "--brand", self.bakery.id, "--batch", "week-1", "--id", "p1", "--media"]
                                  + [str(m) for m in media] + (["--replace"] if replace else []))
        return code, out.getvalue(), P.load_batch(self.path, self.bakery.id)[0][0]

    def drawn(self, spec, folder):
        files, _report = render.render_with_report(self.bakery, spec, Path(self.bakery.path("Output", "visuals", folder)),
                                                   renderer=FakeRenderer())
        return files

    def test_an_unconfirmed_claim_in_a_picture_makes_the_whole_post_unverified(self):
        files = self.drawn(self.stat_spec(source="a survey we read somewhere"), "stat")
        code, said, post = self.attach(files[0])
        self.assertEqual(code, 0)
        self.assertEqual(post.sourcing, "unverified")
        self.assertIn("97%", said)
        self.assertIn("unverified", said)
        self.assertTrue(any("97%" in w and "picture" in w.lower() for w in post.lint_warnings), post.lint_warnings)

    def test_a_confirmed_picture_keeps_the_pass_and_a_later_fact_clears_the_flag(self):
        files = self.drawn(self.stat_spec(), "stat")
        self.assertEqual(self.attach(files[0])[2].sourcing, "unverified")
        grounding.add_fact(self.bakery, "97% of our class places sell out within a day.", "class sign-up sheets")
        code, said, post = self.attach(files[0], replace=True)                # checked again against today's facts
        self.assertEqual(post.sourcing, "passed", said)
        self.assertFalse(any("97%" in w for w in post.lint_warnings))

    def test_swapping_the_picture_for_a_clean_one_restores_the_pass(self):
        bad = self.drawn(self.stat_spec(), "stat")
        self.assertEqual(self.attach(bad[0])[2].sourcing, "unverified")
        clean = self.drawn({"format": "headline", "identity": "person",
                            "slides": [{"headline": "Weigh the flour. Every time."}]}, "clean")
        self.assertEqual(self.attach(clean[0], replace=True)[2].sourcing, "passed")

    def test_a_picture_the_factory_did_not_draw_gets_one_plain_note_and_keeps_the_pass(self):
        photo = Path(self.bakery.path("Output", "visuals", "from my phone", "loaf.png"))
        photo.parent.mkdir(parents=True)
        photo.write_bytes(b"\x89PNG a photo")
        code, said, post = self.attach(photo)
        self.assertEqual((code, post.sourcing), (0, "passed"))
        self.assertIn("were not checked", said)
        self.assertEqual(sum(1 for w in post.lint_warnings if "were not checked" in w), 1)

    def test_a_blocked_post_stays_blocked_whatever_the_pictures_say(self):
        self.post.sourcing = "blocked"
        self.post.facts_check = dict(self.post.facts_check, words="blocked")
        P.save_batch([self.post], self.path)
        clean = self.drawn({"format": "headline", "identity": "person",
                            "slides": [{"headline": "Weigh the flour. Every time."}]}, "clean")
        self.assertEqual(self.attach(clean[0])[2].sourcing, "blocked")


class TestRedrawingNeverRemovesWhatWasThere(PictureCase):
    def existing(self, folder, names):
        folder.mkdir(parents=True)
        kept = {}
        for name in names:
            (folder / name).write_bytes(("APPROVED " + name).encode("utf-8"))
            kept[name] = (folder / name).read_bytes()
        return kept

    def names(self, spec, count):
        kinds = ["cover", "point", "checklist", "cta"]
        return ["bake-day-%02d-%s.png" % (i + 1, kinds[i]) for i in range(count)]

    def test_a_slide_that_fails_leaves_every_existing_picture_exactly_as_it_was(self):
        folder = self.out / "approved set"
        kept = self.existing(folder, self.names(self.carousel_spec(), 4) + ["notes from Ava.txt"])
        with self.assertRaises(render.RenderError) as cm:
            self.draw(self.carousel_spec(), folder="approved set", fail_on=2)
        self.assertIn("left as they were", str(cm.exception))
        self.assertIn("Slide 2 of 4", str(cm.exception))
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, kept)
        self.assertEqual([p.name for p in self.out.iterdir()], ["approved set"])       # the staging folder is gone

    def test_a_failure_in_a_new_folder_leaves_nothing_behind(self):
        with self.assertRaises(render.RenderError):
            self.draw(self.carousel_spec(), folder="brand new", fail_on=3)
        self.assertEqual(list((self.out / "brand new").glob("*")) if (self.out / "brand new").exists() else [], [])
        self.assertEqual([p.name for p in self.out.iterdir() if p.name.startswith(".")], [])

    def test_a_full_set_replaces_the_old_one_file_by_file_and_keeps_anything_else(self):
        folder = self.out / "approved set"
        self.existing(folder, self.names(self.carousel_spec(), 4) + ["notes from Ava.txt", "bake-day-05-extra.png"])
        files, report = self.draw(self.carousel_spec(), folder="approved set")
        self.assertEqual([f.name for f in files], self.names(self.carousel_spec(), 4))
        for f in files:
            self.assertTrue(f.read_bytes().startswith(b"NEW "), f.name)
        self.assertEqual((folder / "notes from Ava.txt").read_bytes(), b"APPROVED notes from Ava.txt")
        self.assertEqual((folder / "bake-day-05-extra.png").read_bytes(), b"APPROVED bake-day-05-extra.png")
        self.assertTrue((folder / render.REPORT_NAME).is_file())
        self.assertEqual([p.name for p in self.out.iterdir()], ["approved set"])
        self.assertEqual([p.name for p in folder.iterdir() if p.name.startswith(".")], [])

    def blocking(self, basename, both_ways=False):
        """Stand in for a picture another program is holding open. `both_ways` also refuses to let
        the original be put back, which is the one case where it must not be thrown away."""
        real = render.os.replace

        def stubborn(src, dst):
            name, staged = os.path.basename(str(src)), ".staging" in str(dst)
            if name == basename and not staged:
                raise PermissionError("in use")
            if both_ways and name == "kept-" + basename and not staged:
                raise PermissionError("in use")
            return real(src, dst)

        return mock.patch.object(render.os, "replace", stubborn)

    def test_a_picture_that_cannot_be_replaced_puts_everything_back(self):
        folder = self.out / "approved set"
        kept = self.existing(folder, self.names(self.carousel_spec(), 4))
        with self.blocking("bake-day-03-checklist.png"):
            with self.assertRaises(render.RenderError) as cm:
                self.draw(self.carousel_spec(), folder="approved set")
        self.assertIn("left as they were", str(cm.exception))
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, kept)
        self.assertEqual([p.name for p in self.out.iterdir()], ["approved set"])

    def test_an_original_that_cannot_be_put_back_is_kept_safe_and_named(self):
        folder = self.out / "approved set"
        kept = self.existing(folder, self.names(self.carousel_spec(), 4))
        with self.blocking("bake-day-03-checklist.png", both_ways=True):
            with self.assertRaises(render.RenderError) as cm:
                self.draw(self.carousel_spec(), folder="approved set")
        said = str(cm.exception)
        self.assertIn("bake-day-03-checklist.png", said)
        self.assertIn("kept safe", said)
        self.assertNotIn("Traceback", said)
        staging = [p for p in self.out.iterdir() if p.name.startswith(".staging-")]
        self.assertEqual(len(staging), 1, "the only copy of an approved picture must not be thrown away")
        self.assertIn(staging[0].name, said)
        self.assertEqual((staging[0] / "kept-bake-day-03-checklist.png").read_bytes(),
                         kept["bake-day-03-checklist.png"])
        for name, was in kept.items():                          # every other one went back untouched
            if name != "bake-day-03-checklist.png":
                self.assertEqual((folder / name).read_bytes(), was)


if __name__ == "__main__":
    unittest.main(verbosity=2)
