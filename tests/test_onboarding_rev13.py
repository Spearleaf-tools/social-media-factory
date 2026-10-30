"""Onboarding rev 13 (spec smf-spec-onboarding-v2.md, "Version 2"): bring what you have, the inventory,
"What we found" with what's missing first, and the owner's own writing as labelled quotes (M2-M6, M10)."""
import copy
import json
import unittest
from pathlib import Path

from smf.onboarding_page import session as S
from smf.onboarding_page import to_brand as T
from tests.test_onboarding import PageCase
from tests.test_onboarding_designs import needs_flask

STATIC = Path(__file__).resolve().parents[1] / "smf" / "onboarding_page" / "static"
SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "onboard-brand" / "SKILL.md"


def quote(value, ref, excerpt, **more):
    return dict(value=value, status="unconfirmed", source="draft", origin="document", quoted=True, said_by="owner",
                excerpt=excerpt, refs=[ref], generator="claude-from-document", **more)


def sample():
    return {"answers": {
        "what_you_do": {"value": "A sourdough bakery.", "status": "unconfirmed", "source": "draft",
                        "origin": "document", "refs": ["src-1 rev 7f3a p.3"]},
        "positioning": {
            "core_belief": quote("Bread should take two days.", "src-1 rev 7f3a p.12", "Bread should take two days."),
            "non_negotiables": [dict(id="nn-1", **quote("Show real ovens.", "src-1 rev 7f3a p.31", "Show real ovens."))]},
        "inventory": {"made": "2026-10-20T09:30",
                      "sources": [{"id": "src-1", "name": "Two-Day Bread.pdf", "kind": "pdf", "status": "read",
                                   "covered": "pages 1-48 of 52", "revision": "7f3a"},
                                  {"id": "src-2", "name": "staff-notes.docx", "kind": "document",
                                   "status": "not read yet", "dont_use": True}],
                      "fields": {"beliefs": {"coverage": "found"}, "why_started": {"coverage": "your words needed"}}}}}


class TestQuotesOfTheOwnersOwnWriting(unittest.TestCase):
    def test_a_quote_with_every_mark_is_accepted(self):
        intake = S.intake_from_draft(sample())
        self.assertTrue(intake["answers"]["positioning"]["core_belief"]["quoted"])
        self.assertEqual(intake["answers"]["inventory"]["sources"][0]["id"], "src-1")

    def test_a_quote_missing_any_mark_is_refused(self):
        for drop in ("quoted", "said_by", "excerpt", "refs", "generator"):
            d = sample()
            del d["answers"]["positioning"]["core_belief"][drop]
            with self.assertRaises(S.SessionError, msg=drop):
                S.intake_from_draft(d)

    def test_someone_elses_words_are_refused(self):
        d = sample()
        d["answers"]["positioning"]["core_belief"]["said_by"] = "a customer"
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_a_pack_or_description_never_fills_them(self):
        for origin in ("starter-pack", "description"):
            d = sample()
            d["answers"]["positioning"]["non_negotiables"][0]["origin"] = origin
            with self.assertRaises(S.SessionError, msg=origin):
                S.intake_from_draft(d)

    def test_an_unmarked_draft_is_still_refused_when_saved(self):
        bad = {"core_belief": {"value": "x", "status": "unconfirmed", "source": "draft", "origin": "website", "refs": ["website: /about"]}}
        self.assertTrue(S.validate_answer("positioning", bad))
        self.assertEqual(S.validate_answer("positioning", {"core_belief": sample()["answers"]["positioning"]["core_belief"]}), [])


class TestQuotesMatchTheirPassage(unittest.TestCase):
    def test_words_not_in_the_passage_are_refused(self):
        d = sample()
        d["answers"]["positioning"]["core_belief"]["value"] = "We guarantee overnight results."
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_a_close_extract_is_accepted_and_an_added_word_is_not(self):
        passage = "I have always said bread should take two days, not two hours."
        self.assertTrue(S.close_extract("Bread should take two days.", passage))
        self.assertFalse(S.close_extract("Bread should never take two days", passage))
        self.assertFalse(S.close_extract("Two days, bread should take", passage))

    def test_blank_refs_count_as_none(self):
        d = sample()
        d["answers"]["inventory"]["sources"] = []
        d["answers"]["what_you_do"]["refs"] = ["   "]
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_an_empty_inventory_still_checks_the_source(self):
        d = sample()
        d["answers"]["inventory"]["sources"] = []
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)


class TestTheInventory(unittest.TestCase):
    def test_a_document_draft_without_an_inventory_must_still_say_where(self):
        d = sample()
        del d["answers"]["inventory"]
        del d["answers"]["what_you_do"]["refs"]
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_refs_must_name_a_listed_source(self):
        d = sample()
        d["answers"]["what_you_do"]["refs"] = ["src-9 p.3"]
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_nothing_may_come_from_a_dont_use_file(self):
        d = sample()
        d["answers"]["positioning"]["core_belief"]["refs"] = ["src-2 p.2"]
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_a_document_draft_must_say_where(self):
        d = sample()
        del d["answers"]["what_you_do"]["refs"]
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_coverage_only_for_real_questions(self):
        d = sample()
        d["answers"]["inventory"]["fields"]["not_a_question"] = {"coverage": "found"}
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)


class TestTheBrand(unittest.TestCase):
    def test_a_confirmed_quote_reaches_the_brand_as_quoted_without_its_excerpt(self):
        intake = S.intake_from_draft(sample())
        intake["answers"]["positioning"]["core_belief"]["status"] = "confirmed"
        intake["answers"]["positioning"]["core_belief"]["accepted"] = True
        brand = json.dumps(T.build(intake), default=str)
        self.assertIn('"source": "quoted"', brand.replace("'", '"'))
        self.assertIn("src-1 rev 7f3a p.12", brand)
        self.assertNotIn("excerpt", brand)

    def test_an_unconfirmed_quote_never_reaches_the_brand(self):
        brand = json.dumps(T.build(S.intake_from_draft(sample())), default=str)
        self.assertNotIn("Bread should take two days", brand)


class TestThePage(unittest.TestCase):
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.steps = (STATIC / "steps.html").read_text(encoding="utf-8")

    def test_what_we_found_opens_first_with_what_is_missing(self):
        self.assertIn("<h1>What we found</h1>", self.engine)
        self.assertIn('var GROUPS = ["missing", "your words needed", "partly", "found"];', self.engine)
        self.assertIn("if (V.inventory() && (V.inventory().sources || []).length) {", self.steps)
        self.assertIn("V.fiveRoute()", self.steps)
        self.assertIn("esc(stepLabel(field))", self.engine)
        self.assertNotIn(" of 31", self.steps)

    def test_check_the_drafts_first_and_add_more(self):
        self.assertIn("Check the drafts first", self.engine)
        self.assertIn("Add more material", self.engine)
        self.assertIn(r"I\u2019ve added material for my brand; please read it.", self.engine)
        self.assertIn("Start with whatever you have, and add more whenever you like.", self.engine)

    def test_unlisted_questions_are_not_checked_yet_and_each_quote_shows_its_source(self):
        self.assertIn('unchecked: "Not checked yet"', self.engine)
        self.assertIn("function quoteLine(it, yesId)", self.engine)

    def test_quotes_are_labelled_and_kept_as_quotes_only_when_unchanged(self):
        self.assertIn('return "Your own words from " + (names.length === 1 ? names[0] : "your own writing") + ". Please confirm each one.";', self.engine)
        self.assertIn('quote: "Your words, please confirm"', self.engine)
        self.assertIn("Some drafts from your material are waiting in Make it better.", (STATIC / "steps.html").read_text(encoding="utf-8"))
        self.assertIn("if (was.quoted && (cb.value || \"\") === (was.value || \"\")) {", self.engine)
        self.assertIn("if (old && old.quoted) { it.derived_from = derivedFrom(old); }", self.engine)
        self.assertIn('it.source = "typed";', self.engine)

    def test_the_skill_asks_for_material_and_keeps_it_private(self):
        skill = SKILL.read_text(encoding="utf-8")
        for words in ("Start with whatever you have, and add", "onboard-page --material",
                      "Is anything\nhere private, or not for posts?", '"quoted": true, "said_by": "owner"',
                      "onboard-page --keep-answers <id>"):
            self.assertIn(words, skill)


class TestAddMoreAnyTime(unittest.TestCase):
    """M5: the brand keeps its answers; reopening starts from them, and new material never replaces them."""
    def setUp(self):
        import os, tempfile
        from unittest import mock
        from smf import brands
        from tests.test_brands import BAKERY
        self.tmp = tempfile.TemporaryDirectory(prefix="reopen ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name),
                        mock.patch.object(S, "ROOT", self.tmp.name)]
        for x in self.patches:
            x.start()
        self.brands = brands
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
        intake = S.intake_from_draft(sample())
        intake["answers"]["positioning"]["core_belief"]["status"] = "confirmed"
        intake["answers"]["positioning"]["core_belief"]["accepted"] = True
        intake["answers"]["name"] = {"value": "Maple & Main", "status": "confirmed", "source": "typed", "origin": "person", "tapped": True}
        intake["state"] = "complete"
        self.intake = intake

    def tearDown(self):
        for x in self.patches:
            x.stop()
        self.tmp.cleanup()

    def test_kept_answers_reopen_as_they_were(self):
        import os
        path, moved = S.keep_answers(self.brand, self.intake)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.exists(self.brand.path("_state", "inventory.json")))
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        self.assertEqual(again["state"], "in_progress")
        self.assertEqual(again["answers"]["positioning"]["core_belief"]["status"], "confirmed")
        self.assertEqual(again["answers"]["what_you_do"]["status"], "unconfirmed")      # waiting stays waiting
        self.assertFalse(again.get("brand_changed"))

    def test_new_material_never_replaces_an_answer_and_comes_first(self):
        S.keep_answers(self.brand, self.intake)
        new = {"answers": {"name": {"value": "Maple and Main Co", "status": "unconfirmed", "source": "draft", "origin": "website", "refs": ["website: /about"]},
                           "why_started": {"value": "Our grandmother's starter.", "status": "unconfirmed", "source": "draft", "origin": "website", "refs": ["website: /about"]}}}
        again = S.reopen_intake(self.brands.load("maple-and-main"), new)
        self.assertEqual(again["answers"]["name"]["value"], "Maple & Main")             # confirmed stays
        self.assertEqual(again["candidates"]["name"]["name"]["alternatives"][0]["answer"]["value"], "Maple and Main Co")     # beside it
        self.assertEqual(again["answers"]["why_started"]["value"], "Our grandmother's starter.")   # an empty one is filled
        self.assertEqual(set(again["new_keys"]), {"name", "why_started"})

    def test_a_brand_changed_since_is_flagged(self):
        S.keep_answers(self.brand, self.intake)
        self.brands.update("maple-and-main", {"wants": ["posts"]})
        self.assertTrue(S.reopen_intake(self.brands.load("maple-and-main")).get("brand_changed"))

    def test_material_moves_into_the_brand_without_overwriting(self):
        import os
        src = os.path.join(S.tmp_dir(), S.MATERIAL_TMP)
        os.makedirs(src)
        open(os.path.join(src, "book.pdf"), "w").write("new")
        dst = S.material_dir(self.brand)
        open(os.path.join(dst, "book.pdf"), "w").write("old")
        _, moved = S.keep_answers(self.brand, self.intake)
        self.assertEqual(moved, 1)
        self.assertEqual(sorted(os.listdir(dst)), ["book (2).pdf", "book.pdf"])
        self.assertEqual(open(os.path.join(dst, "book.pdf")).read(), "old")

    def test_undecided_candidates_survive_keeping_and_reopening(self):
        S.keep_answers(self.brand, self.intake)
        new = {"answers": {"name": {"value": "Maple and Main Co", "status": "unconfirmed", "source": "draft", "origin": "website", "refs": ["website: /about"]}}}
        again = S.reopen_intake(self.brands.load("maple-and-main"), new)
        again["state"] = "complete"
        S.keep_answers(self.brands.load("maple-and-main"), again)
        third = S.reopen_intake(self.brands.load("maple-and-main"))
        self.assertEqual(third["candidates"]["name"]["name"]["alternatives"][0]["answer"]["value"], "Maple and Main Co")
        self.assertIn("name", third["new_keys"])

    def test_a_later_reading_keeps_earlier_sources_and_their_dont_use_mark(self):
        S.keep_answers(self.brand, self.intake)
        new = {"answers": {"inventory": {"sources": [{"id": "src-2", "name": "staff-notes.docx", "status": "read"},
                                                     {"id": "src-3", "name": "interview.docx", "status": "read"}],
                                         "fields": {"story": {"coverage": "partly"}}}}}
        inv = S.reopen_intake(self.brands.load("maple-and-main"), new)["answers"]["inventory"]
        ids = {x["id"]: x for x in inv["sources"]}
        self.assertEqual(set(ids), {"src-1", "src-2", "src-3"})
        self.assertTrue(ids["src-2"]["dont_use"])                                       # the mark stays
        self.assertEqual(inv["fields"]["beliefs"]["coverage"], "found")                 # earlier coverage stays
        self.assertEqual(inv["fields"]["story"]["coverage"], "partly")

    def test_only_the_owners_choice_settles_an_alternative(self):
        intake = {"candidates": {}}
        S.add_candidate(intake["candidates"], "name", {"value": "X"})
        S.add_candidate(intake["candidates"], "name", {"value": "Y"})
        S.add_candidate(intake["candidates"], "name", {"value": "X"})                   # the same words once
        alts = intake["candidates"]["name"]["alternatives"]
        self.assertEqual([x["answer"]["value"] for x in alts], ["X", "Y"])
        self.assertTrue(S.decide_candidate(intake, "name", "", alts[0]["cid"]))
        self.assertEqual([x["answer"]["value"] for x in intake["candidates"]["name"]["alternatives"]], ["Y"])
        self.assertFalse(S.decide_candidate(intake, "name", "", "c-stale"))           # stale or already decided
        self.assertTrue(S.decide_candidate(intake, "name", "", intake["candidates"]["name"]["alternatives"][0]["cid"]))
        self.assertEqual(intake["candidates"], {})

    def test_older_saved_alternatives_get_ids(self):
        c = S.normalize_candidates({"name": {"alternatives": [{"value": "X"}]},
                                    "positioning": {"story": {"alternatives": [{"catalyst": "Z"}]}}})
        self.assertTrue(c["name"]["name"]["alternatives"][0]["cid"].startswith("c-"))     # split to its question
        self.assertEqual(c["name"]["name"]["alternatives"][0]["answer"], {"value": "X"})
        self.assertNotIn("handle", c["name"])
        self.assertEqual(c["positioning"]["story"]["alternatives"][0]["answer"], {"catalyst": "Z"})

    def test_a_shared_key_shows_each_question_only_its_own_part(self):
        answers = {"audience": {"value": "Busy parents", "in_the_way": ["Time"], "status": "confirmed", "source": "typed",
                                "origin": "person"}}
        cands = {}
        S.add_candidate_split(cands, "audience", {"value": "Busy parents", "in_the_way": ["Time", "Cost"],
                                                  "questions": ["Is it gluten free?"], "status": "unconfirmed",
                                                  "source": "draft", "origin": "document", "refs": ["src-1 p.4"]}, answers)
        self.assertEqual(set(cands["audience"]), {"audience_way", "audience_questions"})   # who is the same: not shown
        way = cands["audience"]["audience_way"]["alternatives"][0]["answer"]
        self.assertEqual(way["in_the_way"], ["Time", "Cost"])
        self.assertNotIn("questions", way)                                                  # never a sibling's part
        self.assertEqual(way["refs"], ["src-1 p.4"])                                        # its source comes along
        cid = cands["audience"]["audience_way"]["alternatives"][0]["cid"]
        intake = {"candidates": cands}
        self.assertTrue(S.decide_candidate(intake, "audience", "audience_way", cid))
        self.assertEqual(set(intake["candidates"]["audience"]), {"audience_questions"})     # the other one waits
        lad = {}
        S.add_candidate_split(lad, "ladder", [{"rung": "free", "name": "Taster"}, {"rung": "main", "name": "Course"}], {"ladder": []})
        self.assertEqual(lad["ladder"]["rung_free"]["alternatives"][0]["answer"], [{"rung": "free", "name": "Taster"}])

    def test_a_group_part_is_decided_on_its_own(self):
        intake = {"candidates": {}}
        g = intake["candidates"].setdefault("positioning", {})
        S.add_candidate(g, "core_belief", {"value": "Y"})
        S.add_candidate(g, "story", {"catalyst": "Z"})
        cid = g["core_belief"]["alternatives"][0]["cid"]
        self.assertTrue(S.decide_candidate(intake, "positioning", "core_belief", cid))
        self.assertEqual(list(intake["candidates"]["positioning"]), ["story"])

    def test_saving_an_answer_never_settles_new_material_by_itself(self):
        server = (STATIC.parent / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("settle_candidates", server)
        self.assertIn('@app.post("/<given>/api/candidate")', server)

    def test_the_route_is_fixed_when_the_questions_start(self):
        # Deciding new material never moves a question under the person: new material first, then the order (M5),
        # and Next, Back and "2 of 31" follow that one route (deep review, Oct 21: no bouncing, no skipping).
        steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn("function order() { if (!route) { route = V.fiveRoute(); V.setRoute(route); } return route.concat(", steps)
        self.assertIn("var begin = function () { route = null;", steps)
        self.assertIn('return show(lastField || V.stepIn(route, null, -1) || "finish");', steps)      # Back from Finish
        self.assertIn("return r.concat(oneMore(), betterFields().filter(hasCandidate));", engine)   # new material never hidden
        self.assertIn("var i = stepOf(field);", engine)                         # the step label follows the fixed steps

    def test_an_edited_brand_value_is_the_owners_own(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn('if (old && old.origin === "brand" && String(text || "") !== String(oldText || "")) {', engine)

    def test_proposals_fill_every_part_and_carry_their_source_everywhere(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn('el.value = Array.isArray(x2) ? x2.join("\\n") : (x2 == null ? "" : String(x2));', engine)
        self.assertIn("iparts.forEach(function (p) {", engine)
        self.assertIn("n.tapped = true; carryProposal(field, n, proposalText(field, n));", engine)
        self.assertIn("if (C === \"confirmed\") { carryProposal(field, cc, proposalText(field, cc)); }", engine)
        self.assertIn("var usable = USABLE.indexOf(field.kind) >= 0 && !field.never_draft;", engine)
        self.assertIn("if (usedCand[field.id]) { s.usedCand = clone(usedCand[field.id]); }", engine)

    def test_the_page_offers_use_add_keep_and_cancel(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        for words in ('"Use instead"', '"Add to mine"', ">Keep mine<", "data-cand-cancel>Cancel<",
                      "your answer stays as it is until you choose"):
            self.assertIn(words, engine)
        steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        self.assertIn('function firstOpen() { return V.startAt() || "finish"; }', steps)   # new material first (engine-tested)
        self.assertIn("return five.filter(hasCandidate)[0] || five.filter(needs)[0] ||", engine)

    def test_two_readings_keep_both_alternatives(self):
        S.keep_answers(self.brand, self.intake)
        one = {"answers": {"name": {"value": "First", "status": "unconfirmed", "source": "draft", "origin": "website", "refs": ["website: /about"]}}}
        two = {"answers": {"name": {"value": "Second", "status": "unconfirmed", "source": "draft", "origin": "website", "refs": ["website: /about"]}}}
        a = S.reopen_intake(self.brands.load("maple-and-main"), one)
        a["state"] = "complete"
        S.keep_answers(self.brands.load("maple-and-main"), a)
        b = S.reopen_intake(self.brands.load("maple-and-main"), two)
        self.assertEqual([x["answer"]["value"] for x in b["candidates"]["name"]["name"]["alternatives"]], ["First", "Second"])

    def test_one_brands_answers_are_never_kept_in_another(self):
        self.intake["brand"] = "someone-else"
        with self.assertRaises(S.SessionError):
            S.keep_answers(self.brand, self.intake)

    def test_damaged_saved_answers_stop_and_stay_untouched(self):
        import os
        path = S.brand_answers_path(self.brand)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write("{ not json")
        with self.assertRaises(S.SessionError) as cm:
            S.reopen_intake(self.brands.load("maple-and-main"))
        self.assertIn("Nothing was changed", str(cm.exception))
        self.assertEqual(open(path, encoding="utf-8").read(), "{ not json")

    def test_saved_answers_for_another_brand_stop(self):
        S.keep_answers(self.brand, self.intake)
        path = S.brand_answers_path(self.brand)
        data = json.load(open(path, encoding="utf-8"))
        data["brand"] = "someone-else"
        json.dump(data, open(path, "w", encoding="utf-8"))
        with self.assertRaises(S.SessionError):
            S.reopen_intake(self.brands.load("maple-and-main"))

    def test_an_existing_brand_never_sweeps_the_temporary_folder(self):
        import os
        src = os.path.join(S.tmp_dir(), S.MATERIAL_TMP)
        os.makedirs(src)
        open(os.path.join(src, "someone-elses.pdf"), "w").write("x")
        self.intake["brand"] = "maple-and-main"
        _, moved = S.keep_answers(self.brand, self.intake)
        self.assertEqual(moved, 0)
        self.assertTrue(os.path.exists(os.path.join(src, "someone-elses.pdf")))

    def test_a_retry_never_sweeps_up_later_files(self):
        import os
        src = os.path.join(S.tmp_dir(), S.MATERIAL_TMP)
        os.makedirs(src)
        open(os.path.join(src, "book.pdf"), "w").write("mine")
        _, first = S.keep_answers(self.brand, self.intake)
        self.assertEqual(first, 1)
        os.makedirs(src, exist_ok=True)
        open(os.path.join(src, "later.pdf"), "w").write("not mine")
        kept = json.load(open(S.brand_answers_path(self.brand), encoding="utf-8"))
        self.assertEqual(kept["material_moved_to"], "maple-and-main")
        kept.pop("brand")                                   # even if the brand were unset again
        _, again = S.keep_answers(self.brand, kept)
        self.assertEqual(again, 0)
        self.assertTrue(os.path.exists(os.path.join(src, "later.pdf")))

    def test_an_older_brand_reopens_with_its_settings_to_check(self):
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        a = again["answers"]
        self.assertEqual(a["name"]["value"], "Maple & Main Bakery")
        self.assertEqual((a["name"]["status"], a["name"]["origin"], a["name"]["restored"]), ("unconfirmed", "brand", True))
        self.assertIn("colours", a)
        self.assertNotIn("goal", a)                                 # a default can't be told from a choice
        self.assertEqual(S.validate_intake(again), [])

    def test_restored_answers_change_nothing_until_confirmed(self):
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        again["state"] = "complete"
        _, answers, _, voice = T.build(again, current=self.brands.load("maple-and-main").data)
        self.assertEqual(answers, {})
        self.assertIsNone(voice)

    def test_a_chat_change_wins_and_keeps_the_rest(self):
        S.keep_answers(self.brand, self.intake)
        self.brands.update("maple-and-main", {"business": {"what_we_do": "A bakery and a weekend school for home bakers."}})
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        a = again["answers"]
        self.assertEqual(a["what_you_do"]["value"], "A bakery and a weekend school for home bakers.")
        self.assertTrue(a["what_you_do"]["changed_in_chat"])
        self.assertEqual(a["what_you_do"]["status"], "unconfirmed")
        self.assertEqual(a["positioning"]["core_belief"]["status"], "confirmed")        # untouched
        self.assertIn("what_you_do", again["candidates"])            # the waiting answer, kept beside it
        self.assertTrue(again["brand_changed"])

    def test_one_changed_item_leaves_the_others_confirmed(self):
        base = [S._restored({"id": "m-1", "value": "A"}), S._restored({"id": "m-2", "value": "B"})]
        now = [S._restored({"id": "m-1", "value": "A"}), S._restored({"id": "m-2", "value": "B2"})]
        answers = {"myths": [dict(x, status="confirmed") for x in base]}
        S._reconcile_value(answers, "myths", base, now, {}, "myths")
        got = {x["id"]: x for x in answers["myths"]}
        self.assertEqual((got["m-1"]["value"], got["m-1"]["status"]), ("A", "confirmed"))
        self.assertEqual((got["m-2"]["value"], got["m-2"]["status"]), ("B2", "unconfirmed"))
        self.assertTrue(got["m-2"]["changed_in_chat"])

    def test_a_goal_changed_in_the_chat_is_never_sent_back(self):
        self.intake["answers"]["goal"] = {"value": "leads", "status": "confirmed", "source": "typed", "origin": "person"}
        S.keep_answers(self.brand, self.intake)
        self.brands.update("maple-and-main", {"goal": "authority"})
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        self.assertNotIn("goal", again["answers"])

    def test_the_brand_isnt_built_over_a_newer_chat_change(self):
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        self.brands.update("maple-and-main", {"wants": ["posts"]})
        self.assertTrue(S.brand_changed_since(again, self.brands.load("maple-and-main")))

    def test_voice_samples_never_shrink(self):
        import os
        os.makedirs(self.brand.path("Brand"), exist_ok=True)
        open(self.brand.path("Brand", "voice-samples.md"), "w", encoding="utf-8").write(
            "# Voice samples\n\n## Sample 1 (typed)\n\nFirst one.\n\n## Sample 2 (typed)\n\nSecond one.\n")
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        self.assertEqual([x["text"] for x in again["answers"]["voice_samples"]], ["First one.", "Second one."])
        self.assertIsNone(T.voice_markdown(again))                  # nothing new: the file stays as it is
        again["answers"]["voice_samples"].append({"id": "vs-9", "text": "A new one.", "status": "confirmed", "source": "typed"})
        md = T.voice_markdown(again)
        self.assertEqual([t for t in ("First one.", "Second one.", "A new one.") if t in md], ["First one.", "Second one.", "A new one."])

    def test_a_failed_move_finishes_on_retry_without_later_files(self):
        import os, shutil
        from unittest import mock
        src = os.path.join(S.tmp_dir(), S.MATERIAL_TMP)
        os.makedirs(src)
        for n in ("a.pdf", "b.pdf"):
            open(os.path.join(src, n), "w").write(n)
        saved = {}
        real, calls = shutil.move, []

        def flaky(a, b):
            calls.append(a)
            if len(calls) == 2:
                raise OSError("disk busy")
            return real(a, b)
        with mock.patch("shutil.move", flaky):
            with self.assertRaises(OSError):
                S.keep_answers(self.brand, self.intake, save=lambda x: saved.update(x=json.loads(json.dumps(x))))
        open(os.path.join(src, "later.pdf"), "w").write("not mine")
        retry = saved["x"]
        self.assertNotIn("material_moved_to", retry)
        _, moved = S.keep_answers(self.brand, retry)
        self.assertEqual(moved, 1)
        self.assertEqual(sorted(os.listdir(S.material_dir(self.brand))), ["a.pdf", "b.pdf"])
        self.assertTrue(os.path.exists(os.path.join(src, "later.pdf")))

    def test_samples_deleted_in_the_chat_never_come_back(self):
        import os
        os.makedirs(self.brand.path("Brand"), exist_ok=True)
        f = self.brand.path("Brand", "voice-samples.md")
        open(f, "w", encoding="utf-8").write("# Voice samples\n\n## Sample 1 (typed)\n\nOld one.\n")
        S.keep_answers(self.brand, S.reopen_intake(self.brands.load("maple-and-main")))
        os.remove(f)
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        self.assertNotIn("voice_samples", again["answers"])

    def test_a_sample_starting_with_a_heading_survives_word_for_word(self):
        import os
        os.makedirs(self.brand.path("Brand"), exist_ok=True)
        text = "# Voice samples\n\n## Sample 1 (pasted)\n\n## My heading\nThe rest of it.\n"
        open(self.brand.path("Brand", "voice-samples.md"), "w", encoding="utf-8").write(text)
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        self.assertEqual(again["answers"]["voice_samples"][0]["text"], "## My heading\nThe rest of it.")
        again["answers"]["voice_samples"] = [{"id": "vs-9", "text": "A new one.", "status": "confirmed", "source": "typed"}]
        md = T.voice_markdown(again)                     # even with no restored entries left, the file is kept
        self.assertTrue(md.startswith(text.rstrip()))
        self.assertIn("## Sample 2 (typed on the onboarding page)", md)

    def test_a_sample_with_a_heading_survives_word_for_word(self):
        import os
        os.makedirs(self.brand.path("Brand"), exist_ok=True)
        text = "# Voice samples\n\n## Sample 1 (pasted)\n\nMy recipe\n## Step one\nFeed it.\n"
        open(self.brand.path("Brand", "voice-samples.md"), "w", encoding="utf-8").write(text)
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        again["answers"]["voice_samples"].append({"id": "vs-9", "text": "A new one.", "status": "confirmed", "source": "typed"})
        md = T.voice_markdown(again)
        self.assertTrue(md.startswith(text.rstrip()))
        self.assertIn("A new one.", md)

    def test_a_source_for_one_question_doesnt_count_for_another(self):
        d = {"answers": {"teach": {"steps": [{"id": "s-1", "value": "Feed the starter", "status": "unconfirmed",
                                              "source": "draft", "origin": "website"}]},
                         "provenance": {"myths": {"origin": "website", "refs": ["website: /faq"]}}}}
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_the_page_shows_candidates_and_puts_new_first(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn("Your new material says:", engine)
        self.assertIn("var fresh = (isNew(b) ? 1 : 0) - (isNew(a) ? 1 : 0);", engine)
        self.assertIn("function isNew(field) { return hasCandidate(field); }", engine)




class TestPhaseASourcesAndSafety(unittest.TestCase):
    """#43: website sources required, damaged saved answers stop, material moved only by its own new brand."""
    def test_a_new_website_draft_must_say_which_page(self):
        d = {"answers": {"name": {"value": "Maple", "status": "unconfirmed", "source": "draft", "origin": "website"}}}
        with self.assertRaises(S.SessionError) as cm:
            S.intake_from_draft(d)
        self.assertIn("the page and section", str(cm.exception))
        d["answers"]["name"]["refs"] = ["website: /about"]
        S.intake_from_draft(d)

    def test_a_website_source_in_provenance_counts(self):
        d = {"answers": {"name": {"value": "Maple", "status": "unconfirmed", "source": "draft", "origin": "website"},
                         "provenance": {"name": {"origin": "website", "refs": ["website: / (home page)"]}}}}
        S.intake_from_draft(d)

    def test_blank_and_nested_website_refs_are_refused(self):
        d = {"answers": {"teach": {"myths": [{"id": "m-1", "value": "Sourdough is sour", "status": "unconfirmed",
                                              "source": "draft", "origin": "website", "refs": ["  "]}]}}}
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)

    def test_an_older_website_draft_still_loads_with_source_not_recorded(self):
        intake = S.blank_intake()
        intake["answers"]["name"] = {"value": "Maple", "status": "unconfirmed", "source": "draft", "origin": "website"}
        self.assertEqual(S.validate_intake(intake), [])
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn('"Drafted from your website (source not recorded). Please check it."', engine)

    def test_website_sources_show_their_page(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn('"your website" + (wpage ? " (" + wpage[1].trim() + ")" : "")', engine)


class TestPhaseCWhereWordsCameFrom(unittest.TestCase):
    """#43 gap 11: source marks survive Confirm, Edit and a later reading."""
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")

    def test_confirm_and_edit_keep_the_source_marks(self):
        self.assertIn('var SOURCE_MARKS = ["refs", "generator", "parts", "prompted_by", "excerpt"];', self.engine)
        self.assertIn('if (old && (old.source === "draft" || old.source === "draft-edited")) {', self.engine)

    def test_every_part_counts_when_telling_edited_from_unchanged(self):
        self.assertIn("stamp(it, old, status, itemText(it, parts), old ? itemText(old, parts) : \"\");", self.engine)

    def test_an_edited_quote_is_the_owners_but_remembers_its_file(self):
        self.assertIn("if (was.quoted) { cb.derived_from = derivedFrom(was); }", self.engine)
        q = {"positioning": {"core_belief": {"value": "Mine now", "status": "confirmed", "source": "typed",
                                              "origin": "person", "derived_from": {"origin": "document", "refs": ["src-1 p.2"]}}}}
        intake = S.blank_intake()
        intake["answers"].update(q)
        self.assertEqual(S.validate_intake(intake), [])

    def test_belief_edits_count_the_experience_too(self):
        # Restored brand values keep "from your brand" only when nothing changed, experience included; a quote stays
        # a quote while its quoted words are unchanged (the experience is the owner's own, beside it).
        self.assertIn('var unchanged = (cb.value || "") === (was.value || "") && (cb.experience || "") === (was.experience || "");', self.engine)
        self.assertIn('cb.source = "draft"; cb.quoted_parts = ["value"];', self.engine)
        self.assertIn("qp.every(function (n) { return (it[n] || \"\") === (old[n] || \"\"); });", self.engine)

    def test_grouped_questions_map_to_their_parts(self):
        f = {f["id"]: f for f in S.fields()["core"]}
        self.assertEqual(S.field_parts(f["beliefs"]), ("core_belief", "contrarian"))
        self.assertEqual(S.field_parts(f["for_against"]), ("for", "against"))
        self.assertEqual(S.field_parts(f["home"]), ("home_medium", "stage"))
        self.assertEqual(S.field_parts(f["non_negotiables"]), ("non_negotiables",))

    def test_a_candidate_never_takes_over_a_questions_source(self):
        import os, tempfile
        from unittest import mock
        from smf import brands
        from tests.test_brands import BAKERY
        tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(brands, "CLIENT_DIR", os.path.join(tmp.name, "Client")),                 mock.patch.object(brands, "ROOT", tmp.name), mock.patch.object(S, "ROOT", tmp.name):
            b = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
            intake = S.blank_intake()
            intake["answers"]["what_you_do"] = {"value": "Bread.", "status": "confirmed", "source": "typed", "origin": "person"}
            intake["answers"]["provenance"] = {"what_you_do": {"origin": "person"}}
            intake["state"] = "complete"
            S.keep_answers(b, intake)
            new = {"answers": {"what_you_do": {"value": "Bread and classes.", "status": "unconfirmed", "source": "draft",
                                               "origin": "website", "refs": ["website: /about"]},
                               "why_started": {"value": "Our grandmother.", "status": "unconfirmed", "source": "draft",
                                               "origin": "website", "refs": ["website: /story"]},
                               "provenance": {"what_you_do": {"origin": "website", "refs": ["website: /about"]},
                                              "why_started": {"origin": "website", "refs": ["website: /story"]}}}}
            again = S.reopen_intake(brands.load("maple-and-main"), new)
            prov = again["answers"]["provenance"]
            self.assertEqual(prov["what_you_do"], {"origin": "person"})          # a candidate: the owner's source stays
            self.assertEqual(prov["why_started"]["refs"], ["website: /story"])   # filled: the new source
        tmp.cleanup()



class TestPhaseDOneYesPerQuote(unittest.TestCase):
    """#43 gap 5: each quote is confirmed on its own, for its exact words."""
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")

    def quote(self, **more):
        return dict(sample()["answers"]["positioning"]["core_belief"], **more)

    def test_a_confirmed_quote_needs_its_own_yes(self):
        self.assertTrue(S.validate_answer("positioning", {"core_belief": self.quote(status="confirmed")}))
        self.assertEqual(S.validate_answer("positioning", {"core_belief": self.quote(status="confirmed", accepted=True)}), [])

    def test_a_waiting_quote_needs_no_yes(self):
        self.assertEqual(S.validate_answer("positioning", {"core_belief": self.quote()}), [])

    def test_two_quotes_one_yes(self):
        nn = sample()["answers"]["positioning"]["non_negotiables"][0]
        two = [dict(nn, status="confirmed", accepted=True),
               dict(nn, id="nn-2", value="Show real ovens.", status="unconfirmed")]
        self.assertEqual(S.validate_answer("positioning", {"non_negotiables": two}), [])
        intake = S.intake_from_draft(sample())
        intake["answers"]["positioning"]["non_negotiables"] = two
        brand = json.dumps(T.build(intake), default=str)
        self.assertEqual(brand.count("Show real ovens."), 1)                # only the one with its yes

    def test_a_pair_quotes_only_its_quoted_side(self):
        pair = {"id": "diff-1", "others": "Bake from frozen", "us": "We start two days ahead, by hand",
                "status": "unconfirmed", "source": "draft", "origin": "document", "quoted": True, "said_by": "owner",
                "excerpt": "Others bake from frozen at five in the morning.", "refs": ["src-1 rev 7f3a p.40"],
                "generator": "claude-from-document", "quoted_parts": ["others"]}
        self.assertEqual(S.validate_answer("positioning", {"differentiation": [pair]}), [])
        pair.pop("quoted_parts")
        self.assertTrue(S.validate_answer("positioning", {"differentiation": [pair]}))   # "us" isn't in the passage
        # From Claude, the unsupported side stays empty (M6): only the owner fills it, on the page.
        d = sample()
        d["answers"]["positioning"]["differentiation"] = [dict(pair, quoted_parts=["others"])]
        with self.assertRaises(S.SessionError):
            S.intake_from_draft(d)
        d["answers"]["positioning"]["differentiation"] = [dict(pair, quoted_parts=["others"], us="")]
        S.intake_from_draft(d)

    def test_an_empty_or_blank_quoted_parts_list_is_refused(self):
        for qp in ([], ["us"]):
            bad = self.quote(value="We guarantee overnight results.", status="confirmed", accepted=True, quoted_parts=qp)
            self.assertTrue(S.validate_answer("positioning", {"core_belief": bad}), qp)

    def test_the_page_gives_each_quote_its_own_yes_and_nothing_else_confirms_it(self):
        self.assertIn("Yes, these are my words", self.engine)
        self.assertIn('if (quoteYes(row)) { it.accepted = true; } else { it.status = "unconfirmed"; }', self.engine)
        self.assertIn('if (quoteYes($(fid(field, "core-quote")))) { cb.accepted = true; } else { cb.status = "unconfirmed"; }', self.engine)



class TestPhaseFTypingKept(unittest.TestCase):
    """#43 gap 8: waiting typing is kept as plain values on the server, never page code, never a key."""
    def snap(self, text="Bread goes stale in a day."):
        return {"inputs": {}, "pressed": {}, "dirty": True,
                "lists": {"f-myths-items": {"removed": "", "rows": [{"id": "", "hidden": False, "inputs": {"value": text},
                                                                      "pressed": {}, "marks": {}}]}}}

    def test_plain_values_are_kept(self):
        self.assertEqual(S.typing_problems("myths", self.snap()), "")
        self.assertEqual(S.typing_problems("myths", None), "")

    def test_page_code_a_key_an_unknown_question_or_too_much_are_refused(self):
        self.assertTrue(S.typing_problems("myths", self.snap('<img src=x onerror="alert(1)">')))
        self.assertIn("key", S.typing_problems("myths", self.snap("sk-ant-api03-" + "Ab9xQ2" * 8)))
        self.assertTrue(S.typing_problems("not-a-question", self.snap()))
        self.assertTrue(S.typing_problems("myths", self.snap("x" * (S.TYPING_MAX + 10))))
        self.assertTrue(S.typing_problems("myths", {"html": "<b>x</b>"}))
        self.assertTrue(S.typing_problems("myths", {"inputs": {"f-other-value": "x"}}))

    def test_every_nested_part_is_checked(self):
        bad = [{"inputs": 7}, {"pressed": {"f-other-x": ["a"]}}, {"lists": {"f-other-items": {"rows": []}}},
               {"lists": {"f-myths-items": {"rows": [{"id": "BAD ID"}]}}},
               {"lists": {"f-myths-items": {"rows": [{"marks": {"onclick": "x"}}]}}},
               {"usedCand": {"snap": {"inputs": {"f-other-v": "x"}}}}]
        for snap in bad:
            self.assertTrue(S.typing_problems("myths", snap), snap)

    def test_ordinary_writing_with_a_less_than_sign_is_kept(self):
        # Gemini review (Oct 22): "price <$50" was refused as page code, and Finish then waited for ever.
        snap = lambda t: {"inputs": {"f-why_started-value": t}, "pressed": {}, "lists": {}, "dirty": True}
        for ok in ("Our classes cost <$50", "for clients <age 18", "a <b and c", "3<5"):
            self.assertEqual(S.typing_problems("why_started", snap(ok)), "", ok)
        for bad in ("<script>alert(1)</script>", "<b>bold</b>", "<img src=x onerror=y>", "<!-- note -->", "<br/>",
                    "<img src=x/>", "<br />"):
            self.assertTrue(S.typing_problems("why_started", snap(bad)), bad)
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn("} else if (e.status && e.status < 500) {", engine)        # a refusal never makes Finish wait
        one = (STATIC / "one-page.html").read_text(encoding="utf-8")
        self.assertIn("V.stepIn(l, f, 1)", one)                                  # design A passes over a set-aside strategy

    def test_the_page_never_keeps_page_code(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        a = engine.index("  function capture(field) {")
        b = engine.index("  function loadTyped()")
        self.assertNotIn("innerHTML", engine[a:b])
        self.assertIn("return typingQueue.then(function () {\n      if (Object.keys(failedTyping).length) {", engine)
        self.assertIn("failedTyping[field.id] = true;", engine)             # a failed save is said and tried again

    def test_typing_survives_keep_and_reopen_and_new_material_goes_beside_it(self):
        import os, tempfile
        from unittest import mock
        from smf import brands
        from tests.test_brands import BAKERY
        tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(brands, "CLIENT_DIR", os.path.join(tmp.name, "Client")), \
                mock.patch.object(brands, "ROOT", tmp.name), mock.patch.object(S, "ROOT", tmp.name):
            b = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
            intake = S.blank_intake()
            intake["typing"] = {"why_started": {"inputs": {"f-why_started-value": "My grandmother"}, "pressed": {}, "lists": {}, "dirty": True}}
            intake["state"] = "complete"
            S.keep_answers(b, intake)
            new = {"answers": {"why_started": {"value": "Our grandmother's starter.", "status": "unconfirmed",
                                               "source": "draft", "origin": "website", "refs": ["website: /story"]}}}
            again = S.reopen_intake(brands.load("maple-and-main"), new)
            self.assertIn("why_started", again["typing"])
            self.assertNotIn("why_started", again["answers"])             # the typing isn't replaced
            self.assertIn("why_started", again["candidates"])             # the new words wait beside it
            self.assertEqual(T.build(dict(again, state="complete"))[1].get("person"), None)   # never in the brand
        tmp.cleanup()



class TestTheAnswerRouteGuards(PageCase):
    """Deep review (Oct 21): a brand changed in the chat while the page is open, and a file marked "don't use"
    since the page loaded, never let a stale screen confirm or save over them."""
    @needs_flask
    def test_a_brand_changed_in_the_chat_is_asked_about_before_confirming(self):
        import os
        from unittest import mock
        from smf import brands
        from smf.onboarding_page import server
        from tests.test_brands import BAKERY
        with mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")), \
                mock.patch.object(brands, "ROOT", self.tmp.name):
            b = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
            intake = S.blank_intake("maple-and-main")
            intake["opened_fingerprint"] = S.brand_fingerprint(b)
            session = S.new_session(8652, intake, layout="steps")
            c = server.create_app(session["code"]).test_client()
            url = "/%s/api/answer" % session["code"]
            ok = {"value": "We bake slowly.", "status": "confirmed", "source": "typed", "origin": "person"}
            self.assertEqual(c.post(url, json={"key": "what_you_do", "answer": ok}).status_code, 200)
            brands.update("maple-and-main", {"what_you_do": "Changed in the chat."})
            r = c.post(url, json={"key": "what_you_do", "answer": dict(ok, value="Again")})
            self.assertEqual(r.status_code, 409)
            self.assertIn("changed in the chat", r.get_json()["error"])
            self.assertEqual(S.load_intake(S.load_session())["answers"]["what_you_do"]["value"], "We bake slowly.")

    @needs_flask
    def test_nothing_from_a_dont_use_file_is_saved_back(self):
        from smf.onboarding_page import server
        intake = S.intake_from_draft(sample())
        session = S.new_session(8652, intake, layout="steps")
        c = server.create_app(session["code"]).test_client()
        url = "/%s/api/answer" % session["code"]
        stale = {"value": "Staff only.", "status": "confirmed", "source": "draft", "origin": "document", "refs": ["src-2 p.1"]}
        r = c.post(url, json={"key": "what_you_do", "answer": stale})
        self.assertEqual(r.status_code, 409)
        self.assertNotIn("Staff only.", json.dumps(S.load_intake(S.load_session())["answers"]))

    def test_the_chat_answers_file_refuses_a_key(self):
        import io, os, contextlib, tempfile
        from smf.onboarding_page import cli
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "chat-answers.json")
            bad = S.intake_from_draft(sample())
            bad["state"] = "complete"
            bad["answers"]["what_you_do"] = {"value": "sk-ant-api03-" + "Ab9xQ2" * 8, "status": "confirmed",
                                             "source": "typed", "origin": "person"}
            S.write_json(src, bad)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = cli.cli_onboard_page(["--brand-answers", os.path.join(d, "o.json"), "--answers-file", src])
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(os.path.join(d, "o.json")))
            self.assertNotIn("Ab9xQ2", buf.getvalue())                     # never echoed
            named = S.intake_from_draft(sample())
            named["state"] = "complete"
            named["answers"]["sk-ant-api03-" + "Ab9xQ2" * 8] = {"value": "x"}   # a key pasted as a name
            S.write_json(src, named)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = cli.cli_onboard_page(["--brand-answers", os.path.join(d, "o.json"), "--answers-file", src])
            self.assertNotEqual(code, 0)
            self.assertNotIn("Ab9xQ2", buf.getvalue())


class TestTheTypingRoute(PageCase):
    """POST /api/typing: kept as plain values, a key refused and the earlier copy removed, older saves ignored."""
    @needs_flask
    def test_save_refuse_and_order(self):
        from smf.onboarding_page import server
        session = S.new_session(8652, S.blank_intake(), layout="steps")
        c = server.create_app(session["code"]).test_client()
        url = "/%s/api/typing" % session["code"]
        ok = {"inputs": {"f-why_started-value": "My grandmother baked."}, "pressed": {}, "lists": {}, "dirty": True}
        self.assertEqual(c.post(url, json={"field": "why_started", "snap": ok, "rev": 1}).status_code, 200)
        self.assertIn("why_started", S.load_intake(S.load_session())["typing"])
        bad = {"inputs": {"f-why_started-value": "sk-ant-api03-" + "Ab9xQ2" * 8}, "pressed": {}, "lists": {}, "dirty": True}
        self.assertEqual(c.post(url, json={"field": "why_started", "snap": bad, "rev": 2}).status_code, 422)
        self.assertNotIn("why_started", S.load_intake(S.load_session())["typing"])     # the earlier copy went too
        late = c.post(url, json={"field": "why_started", "snap": ok, "rev": 1})        # an older save arriving late
        self.assertTrue(late.get_json().get("stale"))
        self.assertNotIn("why_started", S.load_intake(S.load_session())["typing"])
        self.assertEqual(c.post(url, json={"field": "why_started", "snap": ok}).status_code, 400)   # no number
        for fid in ([], {}, 7):
            self.assertEqual(c.post(url, json={"field": fid, "snap": ok, "rev": 9}).status_code, 400)



class TestPhaseGDontUseLater(unittest.TestCase):
    """#43 gap 2: a file marked "don't use" after reading is taken out at once: answers, brand, brand files."""
    def setUp(self):
        import os, tempfile
        from unittest import mock
        from smf import brands
        from tests.test_brands import BAKERY
        self.tmp = tempfile.TemporaryDirectory(prefix="dontuse ' e ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name), mock.patch.object(S, "ROOT", self.tmp.name)]
        for x in self.patches:
            x.start()
        self.brands = brands
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
        intake = S.intake_from_draft(sample())
        pos = intake["answers"]["positioning"]
        pos["core_belief"].update(status="confirmed", accepted=True)
        pos["non_negotiables"][0].update(status="confirmed", accepted=True)
        intake["answers"]["provenance"] = {"what_you_do": {"origin": "document", "refs": ["src-1 rev 7f3a p.3"]}}
        intake["typing"] = {"myths": {"inputs": {}, "pressed": {}, "dirty": True, "lists": {"f-myths-items": {"removed": "", "rows": [
            {"id": "", "hidden": False, "inputs": {"value": "x"}, "pressed": {}, "marks": {"cand": json.dumps({"refs": ["src-1 p.9"]})}}]}}}}
        intake["state"] = "complete"
        intake["brand"] = "maple-and-main"
        _, answers, _, _ = T.build(intake, current=self.brand.data)
        brands.update("maple-and-main", answers)
        brands.sync(brands.load("maple-and-main"))
        S.keep_answers(brands.load("maple-and-main"), intake)

    def tearDown(self):
        for x in self.patches:
            x.stop()
        self.tmp.cleanup()

    def run_cli(self, *args):
        import io, contextlib
        from smf.onboarding_page import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.cli_onboard_page(list(args))
        return code, out.getvalue()

    def brand_text(self):
        import glob
        b = self.brands.load("maple-and-main")
        text = ""
        for f in [b.path("brand-master.json")] + glob.glob(b.path("Brand", "*.md")):
            with open(f, encoding="utf-8") as fh:
                text += fh.read()
        return text

    def test_the_brand_had_the_quote_before(self):
        self.assertIn("Bread should take two days.", self.brand_text())

    def test_everything_from_that_file_goes_at_once(self):
        code, out = self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main")
        self.assertEqual(code, 0, out)
        self.assertIn("Done: nothing from that file is left", out)
        self.assertNotIn("Bread should take two days.", out)              # the old words are never printed
        text = self.brand_text()
        self.assertNotIn("Bread should take two days.", text)
        self.assertNotIn("Show real ovens.", text)
        kept = S.read_json(S.brand_answers_path(self.brands.load("maple-and-main")))
        a = kept["answers"]
        self.assertNotIn("core_belief", a["positioning"])                 # the question is empty again
        self.assertNotIn("what_you_do", a)                                 # the waiting draft is withdrawn
        self.assertNotIn("what_you_do", a.get("provenance", {}))
        self.assertNotIn("myths", kept.get("typing", {}))
        self.assertTrue(kept["restricted"]["src-1"])                       # excerpts kept only here
        self.assertEqual(kept["withdrawals"]["src-1"]["status"], "done")
        self.assertTrue(any(x.get("dont_use") for x in a["inventory"]["sources"] if x["id"] == "src-1"))
        again = S.reopen_intake(self.brands.load("maple-and-main"))
        self.assertEqual(S.validate_intake(again), [])
        self.assertNotIn("Bread should take two days.", json.dumps(again["answers"]))

    def test_a_failed_brand_change_stays_pending_and_a_retry_finishes_it(self):
        from unittest import mock
        real = self.brands.update
        with mock.patch.object(self.brands, "update", side_effect=self.brands.BrandError("disk busy")):
            code, out = self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main")
        self.assertEqual(code, 1)
        self.assertIn("stays pending", out)
        self.assertIn("Bread should take two days.", self.brand_text())   # nothing changed yet
        code, out = self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main")
        self.assertEqual(code, 0, out)                                      # the kept plan finished the job
        self.assertNotIn("Bread should take two days.", self.brand_text())

    def test_an_open_pages_own_answer_from_that_file_survives_a_failed_update_and_a_retry(self):
        from unittest import mock
        live = S.intake_from_draft(sample())
        live["brand"] = "maple-and-main"
        live["answers"]["positioning"]["non_negotiables"][0].update(id="nn-7", status="confirmed", accepted=True)
        session = S.new_session(8652, live, "maple-and-main", layout="steps")
        b = self.brands.load("maple-and-main")
        self.brands.update("maple-and-main", {"positioning": {"non_negotiables": [{"id": "nn-7", "value": "Show real ovens."}]}})
        with mock.patch.object(self.brands, "update", side_effect=self.brands.BrandError("disk busy")):
            code, _ = self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main")
        self.assertEqual(code, 1)
        code, out = self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main")
        self.assertEqual(code, 0, out)
        ids = [x.get("id") for x in self.brands.load("maple-and-main").data["positioning"].get("non_negotiables", [])]
        self.assertNotIn("nn-7", ids)
        self.assertNotIn("Show real ovens.", json.dumps(S.load_intake(S.load_session())["answers"]))

    def test_settling_covers_only_what_was_listed(self):
        b = self.brands.load("maple-and-main")
        S.record_proof(b, "pr-1", "PRF-001", {"origin": "document", "refs": ["src-1 p.20"]})
        self.assertEqual(self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main", "--settled")[0], 0)
        S.record_proof(b, "pr-2", "PRF-002", {"origin": "document", "refs": ["src-1 p.21"]})
        code, out = self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main")
        self.assertEqual(code, 1)                                           # a new item asks again
        self.assertIn("PRF-002", out)

    def test_things_for_the_chat_keep_it_pending_until_settled(self):
        b = self.brands.load("maple-and-main")
        S.record_proof(b, "pr-1", "PRF-001", {"origin": "document", "refs": ["src-1 p.20"]})
        code, out = self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main")
        self.assertEqual(code, 1)
        self.assertIn("PRF-001", out)
        self.assertIn("--settled", out)
        code, out = self.run_cli("--dont-use", "src-1", "--brand", "maple-and-main", "--settled")
        self.assertEqual(code, 0, out)

    def test_an_answer_known_only_by_its_questions_source_is_taken_out_too(self):
        intake = S.intake_from_draft(sample())
        a = intake["answers"]
        a["what_you_do"] = {"value": "Slow bread for busy towns", "status": "confirmed", "source": "draft", "origin": "document"}
        a["provenance"] = {"what_you_do": {"origin": "document", "refs": ["src-1 p.3"]}}
        out = S.withdraw_source(intake, "src-1")
        self.assertNotIn("what_you_do", a)
        self.assertIn("Slow bread for busy towns", out["texts"])
        typed = S.intake_from_draft(sample())
        typed["answers"]["what_you_do"] = {"value": "My own words", "status": "confirmed", "source": "typed", "origin": "person"}
        typed["answers"]["provenance"] = {"what_you_do": {"origin": "document", "refs": ["src-1 p.3"]}}
        S.withdraw_source(typed, "src-1")
        self.assertIn("what_you_do", typed["answers"])          # what the owner typed is their own

    def test_a_questions_source_reaches_only_that_questions_own_answers(self):
        intake = S.intake_from_draft(sample())
        a = intake["answers"]
        d = {"status": "unconfirmed", "source": "draft", "origin": "document"}
        a["ladder"] = [dict(d, rung="free", name="Free starter loaf class"), dict(d, rung="main", name="Weekend bread course")]
        a["deep"] = {"stories": [dict(d, id="st-1", kind="origin", title="How the bakery began"),
                                 dict(d, id="st-2", kind="failure", title="The burnt batch week")],
                     "proof": [dict(d, id="pr-1", title="Two hundred loaves a day")]}
        a["provenance"] = {"rung_free": {"origin": "document", "refs": ["src-1 p.2"]},
                           "d_story_origin": {"origin": "document", "refs": ["src-1 p.4"]},
                           "d_proof": {"origin": "document", "refs": ["src-1 p.20"]}}
        S.withdraw_source(intake, "src-1")
        self.assertEqual([x["rung"] for x in a["ladder"]], ["main"])            # the other offer stays
        self.assertEqual([x["kind"] for x in a["deep"]["stories"]], ["failure"])  # the other story stays
        self.assertEqual(a["deep"]["proof"], [])

    def test_voice_samples_keep_their_source_when_the_page_reopens(self):
        b = self.brands.load("maple-and-main")
        with open(b.path("Brand", "voice-samples.md"), "w", encoding="utf-8") as fh:
            fh.write("# Voice samples\n\n## Sample 1 (from the book)\n\nWe let the dough take its time.\n")
        kept = S.read_json(S.brand_answers_path(b))
        vs = S.brand_samples(b)
        self.assertTrue(vs)
        kept["answers"]["voice_samples"] = [dict(vs[0], refs=["src-1 p.5"], origin="document")]
        S.write_json(S.brand_answers_path(b), kept)
        again = S.reopen_intake(b)
        first = [x for x in again["answers"]["voice_samples"] if x["text"] == vs[0]["text"]][0]
        self.assertEqual(first["refs"], ["src-1 p.5"])

    def test_a_new_reading_cant_quietly_mark_a_file(self):
        new = {"answers": {"inventory": {"sources": [{"id": "src-1", "name": "Two-Day Bread.pdf", "status": "read", "dont_use": True}]}}}
        with self.assertRaises(S.SessionError) as cm:
            S.reopen_intake(self.brands.load("maple-and-main"), new)
        self.assertIn("--dont-use src-1", str(cm.exception))

    def test_an_unknown_source_is_refused_and_nothing_changes(self):
        before = self.brand_text()
        code, out = self.run_cli("--dont-use", "src-9", "--brand", "maple-and-main")
        self.assertEqual(code, 1)
        self.assertEqual(self.brand_text(), before)

    def test_proof_says_its_file_and_page_and_is_never_added_twice(self):
        intake = S.intake_from_draft(sample())
        intake["answers"]["deep"] = {"proof": [{"id": "pr-1", "title": "Two hundred loaves a day", "status": "confirmed",
                                                "source": "draft", "origin": "document", "refs": ["src-1 rev 7f3a p.20"]}]}
        items = T.proof_items(intake)
        self.assertIn("Known from: their own material, Two-Day Bread, page 20 (not independently checked)", items[0]["detail"])
        self.assertEqual(items[0]["provenance"]["refs"], ["src-1 rev 7f3a p.20"])
        b = self.brands.load("maple-and-main")
        S.record_proof(b, "pr-1", "PRF-001", items[0]["provenance"])
        self.assertEqual(S.recorded_proof_ids(b), {"pr-1": "PRF-001"})
        self.assertEqual(S.proof_from_source(b, "src-1"), ["PRF-001"])

    def test_a_new_brands_retried_build_lists_its_proof_once(self):
        import io, os, contextlib
        from smf.onboarding_page import cli
        intake = S.intake_from_draft(sample())
        intake["answers"]["deep"] = {"proof": [{"id": "pr-1", "title": "Two hundred loaves a day", "status": "confirmed",
                                                "source": "draft", "origin": "document", "refs": ["src-1 rev 7f3a p.20"]}]}
        intake["state"] = "complete"
        live = os.path.join(self.tmp.name, "live.json")
        S.keep_answers(self.brands.load("maple-and-main"), intake, save=lambda x: S.write_json(live, x))
        self.assertEqual(S.read_json(live)["kept_as"], "maple-and-main")
        S.record_proof(self.brands.load("maple-and-main"), "pr-1", "PRF-001", {"origin": "document", "refs": ["src-1 p.20"]})
        out = os.path.join(self.tmp.name, "brand-answers.json")
        sidecar = os.path.splitext(out)[0] + "-proof.json"
        S.write_json(sidecar, [{"id": "pr-1"}])                                         # left by the first run
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cli_onboard_page(["--brand-answers", out, "--answers-file", live])
        self.assertFalse(os.path.exists(sidecar))                                        # already in the library

    def test_an_objection_inside_the_audience_answer_is_taken_out(self):
        intake = S.intake_from_draft(sample())
        intake["answers"]["audience"] = {"value": "Busy parents", "status": "confirmed", "source": "typed", "origin": "person",
                                         "objections": [{"id": "obj-1", "value": "Too dear", "reply": "Two days of work",
                                                         "status": "confirmed", "source": "draft", "origin": "document",
                                                         "refs": ["src-1 p.2"]},
                                                        {"id": "obj-2", "value": "Too far", "status": "confirmed",
                                                         "source": "typed", "origin": "person"}]}
        out = S.withdraw_source(intake, "src-1")
        objs = intake["answers"]["audience"]["objections"]
        self.assertEqual([x["id"] for x in objs], ["obj-1", "obj-2"])
        self.assertTrue(objs[0]["remove"])                                               # sent to the brand as a removal
        self.assertEqual(out["removals"]["audience"]["objections"], [{"id": "obj-1", "remove": True}])
        self.assertEqual(intake["answers"]["audience"]["value"], "Busy parents")          # the owner's own words stay
        self.assertIn("Too dear", out["texts"])

    def test_a_drafted_answer_from_the_file_never_takes_the_owners_own_items_with_it(self):
        # Gemini review (Oct 22): the drafted audience came from the file; the owner's own objection must stay.
        intake = S.intake_from_draft(sample())
        intake["answers"]["audience"] = {"value": "Busy parents", "status": "confirmed", "source": "draft", "origin": "document",
                                         "refs": ["src-1 p.2"],
                                         "objections": [{"id": "obj-2", "value": "Too far", "status": "confirmed",
                                                         "source": "typed", "origin": "person"}]}
        S.withdraw_source(intake, "src-1")
        a = intake["answers"]["audience"]
        self.assertNotIn("value", a)                                                     # the drafted part is gone
        self.assertEqual([x["value"] for x in a["objections"]], ["Too far"])             # the owner's item stays
        self.assertEqual(S.validate_intake(dict(intake, state="in_progress")), [])       # and the file still opens
        self.assertIn("audience", S.placeholders(intake))                                # the question is empty again
        _, answers, _, _ = T.build(dict(intake, state="complete"))
        self.assertNotIn("Busy parents", json.dumps(answers))



class TestPhaseHTheEndAndTheSmallItems(unittest.TestCase):
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")

    def test_both_designs_end_with_the_last_tap(self):
        self.assertIn("Write my first post", self.engine)
        self.assertIn('api("closing", { choice: k === "first" ? "first-post" : "done" })', self.engine)
        self.assertIn('if (!r.ok) { return', self.engine)                      # a failed build shows no success buttons
        for page in ("steps.html", "one-page.html"):
            text = (STATIC / page).read_text(encoding="utf-8")
            self.assertIn('<div id="closing"></div>', text, page)
            self.assertIn("V.wireClosing(handoff);", text, page)

    def test_no_material_says_starting_from_scratch(self):
        self.assertIn("You\\u2019re starting from scratch: that\\u2019s fine. ", self.engine)
        steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        self.assertIn("if (V.inventory() && (V.inventory().sources || []).length) {", steps)

    def test_add_more_opens_this_sessions_own_folder(self):
        server = (STATIC.parent / "server.py").read_text(encoding="utf-8")
        self.assertIn('@app.post("/<given>/api/open-material")', server)
        self.assertIn('api("open-material", {})', self.engine)

    def test_cards_name_paid_services_and_keep_their_safeguards(self):
        from smf.onboarding_page import whats_next as W
        self.assertEqual([n for n, _ in W.paid_services(["make-clips"])], ["ElevenLabs"])
        self.assertEqual(W.paid_services(["write-posts"]), [])
        self.assertIn("Tell me any cost before it runs.", W.STARTS[1][2])
        self.assertIn("Agree the script with me before anything is made.", W.IDEA_REQUEST)

    def test_the_catalogue_names_only_services_its_features_use(self):
        cat = json.loads((STATIC.parents[1] / "content_catalogue.json").read_text(encoding="utf-8"))
        feats = {f["id"]: f for f in json.loads((STATIC.parents[1] / "features.json").read_text(encoding="utf-8"))["features"]}
        svcs = json.loads((STATIC.parents[1] / "services.json").read_text(encoding="utf-8"))["services"]
        for it in cat["items"]:
            text = " ".join(str(it.get(k, "")) for k in ("note", "output", "needs", "gives", "work", "input")).lower()
            for svc in svcs:
                if not svc["keys"] or svc["id"] not in text:
                    continue
                used = set()
                for f in it["implements"] + it.get("also", []):
                    nd = feats[f].get("needs", {})
                    used |= set(nd.get("keys", [])) | set(nd.get("any_key", [])) | set((nd.get("optional_keys") or {}))
                self.assertTrue(set(svc["keys"]) & used, "%s names %s but relies on no feature that uses it" % (it["id"], svc["id"]))

    def test_the_catalogue_matches_the_reviewed_table(self):
        # Reviewed one line per route (Oct 20): what each kind of option relies on.
        reviewed = {"Clips": ["make-clips"], "Two cameras": ["two-camera"], "Film": ["narrated-film"], "Scripts": ["write-scripts"],
                    "Scripts / YouTube": ["write-scripts", "youtube-video"], "YouTube": ["youtube-video"],
                    "YouTube visuals": ["youtube-video", "make-visuals"], "Visuals": ["make-visuals"],
                    "Visuals / Posts": ["make-visuals", "write-posts"], "Visuals + OpenAI": ["ai-pictures"], "Posts": ["write-posts"],
                    "Research": ["research"], "Planning": ["plan-content"], "Talking points": ["talking-points"],
                    "Onboarding": ["onboard-brand"], "Review": ["review"], "Results": ["check-results"]}
        by_id = {"V02": ["make-clips", "clip-versions"], "V03": ["make-clips", "clip-versions"], "W06": ["clip-versions"],
                 "O02": ["export-folder"], "O03": ["schedule-posts"], "O04": ["daily-shorts"], "O05": ["tiktok-test-promote"], "O07": []}
        cat = json.loads((STATIC.parents[1] / "content_catalogue.json").read_text(encoding="utf-8"))
        for it in cat["items"]:
            self.assertEqual(it["implements"], by_id.get(it["id"], reviewed.get(it["route"])), it["id"])

    def test_the_summary_says_what_you_stand_for_is_saved(self):
        text = (STATIC.parent / "summary.py").read_text(encoding="utf-8")
        self.assertIn("<h2>What you stand for</h2>", text)

    def test_the_skill_brings_material_first_and_opens_the_summary(self):
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("**Then one question, only if the material didn't answer it**", skill)
        self.assertIn("open the summary page it prints for them", skill)
        self.assertIn('"claude-from-answers"', skill)
        self.assertIn("--dont-use <source id> --brand", skill)
        self.assertIn("--proof-added", skill)



class TestPhaseIParity(unittest.TestCase):
    """#43 phase I: design A matches design B; question 29's parts each need their own yes; the chat route."""
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.one = (STATIC / "one-page.html").read_text(encoding="utf-8")

    def test_design_a_opens_on_what_we_found_and_uses_the_same_order(self):
        self.assertIn("V.foundHTML()", self.one)
        self.assertIn("V.wireFound(page)", self.one)
        self.assertIn("V.fiveRoute()", self.one)
        self.assertIn("V.hasCandidate(f)", self.one)

    def test_question_29_parts_each_have_their_own_yes(self):
        for part in ("goal", "platforms", "make"):
            self.assertIn('partState(field, "%s"' % part, self.engine)
        self.assertIn('partYes(field, "platforms")', self.engine)
        self.assertIn('partYes(field, "make")', self.engine)
        # Oct 23: how people find you is its own question in Make it better, so question 29 never touches it.
        self.assertNotIn('partYes(field, "acquisition")', self.engine)
        self.assertIn('!partYes(field, "goal")', self.engine)

    def test_the_skill_asks_the_five_steps_and_uses_the_answers_file(self):
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("the same five steps as the page", skill)
        self.assertIn("never as more\nrequired questions", skill)
        self.assertIn("--answers-file .factory/tmp/chat-answers.json", skill)
        self.assertNotIn("The eight answers every brand needs", skill)

    def test_the_chat_answers_file_builds_the_same_way(self):
        import io, os, contextlib, tempfile
        from smf.onboarding_page import cli
        with tempfile.TemporaryDirectory(prefix="chat ' a ") as d:
            src, out = os.path.join(d, "chat-answers.json"), os.path.join(d, "brand-answers.json")
            S.write_json(src, dict(S.intake_from_draft(sample()), state="in_progress"))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.cli_onboard_page(["--brand-answers", out, "--answers-file", src])
            self.assertNotEqual(code, 0)                              # not finished: nothing is built yet
            self.assertFalse(os.path.exists(out))
            S.write_json(src, dict(S.intake_from_draft(sample()), state="complete"))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.cli_onboard_page(["--brand-answers", out, "--answers-file", src])
            self.assertEqual(code, 0, buf.getvalue())
            self.assertTrue(os.path.exists(out))

    def test_a_part_yes_survives_leaving_the_question_and_is_checked(self):
        self.assertIn("snap.partYes[b.getAttribute(\"data-part-yes\")]", self.engine)
        self.assertEqual(S._typing_shape("goal_platforms", {"inputs": {}, "partYes": {"make": True}}), "")
        self.assertNotEqual(S._typing_shape("goal_platforms", {"partYes": {"name": True}}), "")
        self.assertNotEqual(S._typing_shape("myths", {"partYes": {"make": True}}), "")
        self.assertNotEqual(S._typing_shape("goal_platforms", {"partYes": {"make": "yes"}}), "")

    def test_a_kept_draft_part_keeps_its_source_and_the_long_page_shows_plain_numbers(self):
        self.assertIn('if (!mkChanged && oldMk.status) { make = stamp(make, oldMk, C, "same", "same"); }', self.engine)
        self.assertNotIn("function placeInOrder", self.engine)                  # rev 14: step labels, no "of 31"

    def test_design_a_keeps_the_filming_question_in_its_order(self):
        self.assertIn("if (!route) { route = V.fiveRoute(); }", self.one)          # the same route as design B
        skill = SKILL.read_text(encoding="utf-8")
        self.assertLess(skill.index("--keep-answers <id> --answers-file"), skill.index("Only then add any proof"))

    def test_a_bad_chat_answers_file_is_refused(self):
        import io, os, contextlib, tempfile
        from smf.onboarding_page import cli
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "chat-answers.json")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write('{"answers": 5}')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = cli.cli_onboard_page(["--brand-answers", os.path.join(d, "o.json"), "--answers-file", src])
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(os.path.join(d, "o.json")))


ORDER_HARNESS = r"""
const fs = require("fs");
const [engine, fieldsPath, viewPath, probePath] = process.argv.slice(2);
const F = JSON.parse(fs.readFileSync(fieldsPath, "utf8")), V = JSON.parse(fs.readFileSync(viewPath, "utf8"));
global.location = { pathname: "/code/" };
global.window = { addEventListener() {} };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.document = { getElementById() { return null; }, querySelector() { return null; }, querySelectorAll() { return []; }, body: {} };
global.fetch = (url) => {
  const p = url.split("/api/")[1], body = p === "fields" ? F : p === "session" ? V : p === "packs" ? { packs: [] } : {};
  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
};
eval(fs.readFileSync(engine, "utf8"));
window.V2.start({ mount() {
  const V2 = window.V2;
  const out = probePath ? eval(fs.readFileSync(probePath, "utf8")) : V2.flowOrder().filter((f) => f.n).map((f) => f.id);
  console.log(JSON.stringify(out));
} });
"""


@needs_flask                                      # it builds the page's session view with the server module
class TestTheOrderRunsForReal(unittest.TestCase):
    """M10: the page's own order code, run (not read): missing, your words needed, partly, found; and after new
    material, the questions with new candidates first."""
    def order(self, intake, probe=None):
        import os, shutil, subprocess, tempfile
        from smf.onboarding_page import server
        node = shutil.which("node")
        if not node:
            self.skipTest("Node isn't installed here")
        with tempfile.TemporaryDirectory() as d:
            paths = {k: os.path.join(d, k) for k in ("run.js", "fields.json", "view.json")}
            with open(paths["run.js"], "w", encoding="utf-8") as fh:
                fh.write(ORDER_HARNESS)
            S.write_json(paths["fields.json"], S.fields())
            S.write_json(paths["view.json"], server.view({"layout": "steps"}, intake))
            args = [node, paths["run.js"], str(STATIC / "v2-common.js"), paths["fields.json"], paths["view.json"]]
            if probe:
                args.append(os.path.join(d, "probe.js"))
                with open(args[-1], "w", encoding="utf-8") as fh:
                    fh.write(probe)
            out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def intake(self):
        intake = S.blank_intake()
        intake["answers"]["inventory"] = {"made": "2026-10-21T08:00", "sources": [{"id": "src-1", "name": "Book.pdf", "kind": "pdf", "status": "read"}],
                                          "fields": {f["id"]: {"coverage": "found"} for f in S.fields()["core"]}}
        cov = intake["answers"]["inventory"]["fields"]
        cov["why_started"] = {"coverage": "your words needed"}
        cov["what_you_do"] = {"coverage": "partly"}
        cov["handle"] = {"coverage": "missing"}
        cov["voice"] = {"coverage": "missing"}
        return intake

    def test_the_first_time_missing_first(self):
        o = self.order(self.intake())
        self.assertEqual(o[:4], ["handle", "voice", "why_started", "what_you_do"])
        self.assertEqual(len(o), 31)

    def test_next_and_back_pass_over_a_set_aside_strategy_wherever_the_order_puts_it(self):
        # Deep review (Oct 21): with "what you stand for" set aside and the order putting those questions after
        # question 20, Next from 20 used to bounce back to 20 for ever.
        intake = self.intake()
        cov = intake["answers"]["inventory"]["fields"]
        for f in S.fields()["core"]:
            if f.get("group") == "stand":
                cov[f["id"]] = {"coverage": "partly"}
        q20 = [f["id"] for f in S.fields()["core"] if f.get("n") == 20][0]
        cov[q20] = {"coverage": "missing"}
        intake["answers"]["positioning"] = {"parked": True}
        probe = """
          const route = V2.flowOrder(), f = V2.fieldById(%r);
          const seen = [], ids = new Set(); let at = f;
          for (let k = 0; k < 40 && at; k++) { seen.push(at.id); if (ids.has(at.id)) break; ids.add(at.id); at = V2.stepIn(route, at, 1); }
          ({ seen, stand: route.filter((x) => x.group === "stand").map((x) => x.id),
             back: (V2.stepIn(route, route.filter((x) => x.group === "stand").slice(-1)[0], 1) || {}).id || null })
        """ % q20
        r = self.order(intake, probe)
        self.assertEqual(len(r["seen"]), len(set(r["seen"])), r["seen"])          # never the same question twice
        self.assertFalse(set(r["seen"]) & set(r["stand"]))                        # never a set-aside question
        for f in S.fields()["core"]:                                             # now the set-aside ones come last
            cov[f["id"]] = {"coverage": "found" if f.get("group") == "stand" else "missing"}
        r = self.order(intake, "({ end: V2.flowOrder().filter((x) => x.n).slice(-1)[0].group,"
                               "  back: (V2.stepIn(V2.flowOrder(), null, -1) || {}).group || null })")
        self.assertEqual(r["end"], "stand")
        self.assertNotEqual(r["back"], "stand")                                   # Back from "go deeper?" too

    def test_after_new_material_its_questions_come_first(self):
        intake = self.intake()
        intake["candidates"] = {"name": {"name": {"alternatives": [{"cid": "c1", "answer": {
            "value": "Maple and Main", "status": "unconfirmed", "source": "draft", "origin": "document", "refs": ["src-1 p.2"]}}]}}}
        o = self.order(intake)
        self.assertEqual(o[:3], ["name", "handle", "voice"])


@needs_flask
class TestFiveSteps(unittest.TestCase):
    """Rev 14 (design review, Oct 22): five steps, then "one more thing"; everything else is Make it better. Run, not read."""
    FIVE = ["name", "what_you_do", "handle", "audience_who", "audience_way", "audience_questions", "rung_main", "identities",
            "goal_platforms", "voice_samples"]

    def probe(self, intake, js):
        return TestTheOrderRunsForReal.order(self, intake, js)

    def test_the_route_is_the_five_steps_then_the_rules(self):
        r = self.probe(S.blank_intake(), "V2.fiveRoute().map((f) => f.id)")
        self.assertEqual(r, self.FIVE + ["rules"])
        labels = self.probe(S.blank_intake(), "V2.fiveRoute().map((f) => V2.stepLabel(f))")
        self.assertEqual(labels[0], "Step 1 of 5 · Your business")
        self.assertEqual(labels[-1], "One more thing")
        self.assertEqual(self.probe(S.blank_intake(), "V2.stepLabel(V2.fieldById('beliefs'))"), "Make it better · What you stand for")

    def test_new_material_in_make_it_better_still_joins_the_route(self):
        intake = S.blank_intake()
        intake["candidates"] = {"why_started": {"alternatives": [{"cid": "c1", "answer": {
            "value": "My grandmother's starter.", "status": "unconfirmed", "source": "draft", "origin": "website", "refs": ["website: /story"]}}]}}
        r = self.probe(intake, "V2.fiveRoute().map((f) => f.id)")
        self.assertEqual(r[-1], "why_started")

    def test_a_step_is_done_only_when_its_answers_are_confirmed(self):
        c = lambda v, **k: dict({"value": v, "status": "confirmed", "source": "typed", "origin": "person"}, **k)
        intake = S.blank_intake()
        a = intake["answers"]
        a["name"] = c("Maple & Main", tapped=True)
        a["what_you_do"] = c("A sourdough bakery for busy families.")
        js = "[0, 1, 2, 3, 4].map((i) => V2.stepState(i))"
        self.assertEqual(self.probe(intake, js)[0], "ok")                          # the handle is optional
        a["what_you_do"] = dict(a["what_you_do"], status="unconfirmed", source="draft", origin="website", refs=["website: /about"])
        self.assertEqual(self.probe(intake, js)[0], "check")                       # a draft waiting: not done
        a["make"] = c(["posts"])
        self.assertEqual(self.probe(intake, js)[3], "")                            # platforms still to come
        a["platforms"] = {"by_speaker": {"company": ["instagram"]}, "status": "confirmed", "source": "typed", "origin": "person"}
        a["identities"] = [{"id": "company", "kind": "company", "name": "Maple & Main", "status": "confirmed", "source": "typed",
                            "origin": "person", "tapped": True}]
        self.assertEqual(self.probe(intake, js)[3], "ok")                          # no goal needed (A3)
        a["make"] = c([])
        self.assertEqual(self.probe(intake, js)[3], "")                            # emptied: not done
        a["make"] = c(["posts"])
        a["identities"] = [{"id": "company", "remove": True, "status": "confirmed"},
                           {"id": "person", "kind": "person", "name": "Ava", "status": "confirmed", "source": "typed", "origin": "person", "tapped": True}]
        self.assertEqual(self.probe(intake, js)[3], "")                            # the company's platforms no longer count
        a["identities"] = [{"id": "company", "kind": "company", "name": "Maple & Main", "status": "confirmed", "source": "typed",
                            "origin": "person", "tapped": True}]
        a["goal"] = {"value": "leads", "status": "unconfirmed", "source": "draft", "origin": "website", "refs": ["website: /"]}
        self.assertEqual(self.probe(intake, js)[3], "check")                       # but a drafted goal still asks
        intake["candidates"] = {"name": {"name": {"alternatives": [{"cid": "c1", "answer": {
            "value": "Maple and Main Co", "status": "unconfirmed", "source": "draft", "origin": "document", "refs": ["src-1 p.2"]}}]}}}
        a["what_you_do"] = c("A sourdough bakery for busy families.")
        self.assertEqual(self.probe(intake, js)[0], "check")                       # new material waiting: not Done

    def test_reopening_with_the_five_done_shows_the_status(self):
        c = lambda v, **k: dict({"value": v, "status": "confirmed", "source": "typed", "origin": "person"}, **k)
        intake = S.blank_intake()
        a = intake["answers"]
        a["name"] = c("Maple & Main", tapped=True)
        a["what_you_do"] = c("A sourdough bakery for busy families.")
        a["audience"] = c("Busy parents nearby.")
        a["ladder"] = [{"id": "o-main", "rung": "main", "name": "Weekend loaves", "status": "confirmed", "source": "typed", "origin": "person"}]
        a["identities"] = [{"id": "company", "kind": "company", "name": "Maple & Main", "status": "confirmed", "source": "typed",
                            "origin": "person", "tapped": True}]
        a["make"] = c(["posts"])
        a["platforms"] = {"by_speaker": {"company": ["instagram"]}, "status": "confirmed", "source": "typed", "origin": "person"}
        a["voice_samples"] = [{"text": "We bake slowly.", "source": "typed", "verbatim": True, "status": "confirmed", "origin": "person"}]
        a["rules"] = {"industry": "none", "status": "confirmed", "source": "typed", "origin": "person", "tapped": True}
        self.assertEqual(self.probe(intake, "[0,1,2,3,4].map((i) => V2.stepState(i))"), ["ok"] * 5)
        self.assertIsNone(self.probe(intake, "V2.startAt() && V2.startAt().id"))   # optional handle blank: the status
        a["name"] = dict(a["name"], handle="@maple", status="unconfirmed", source="draft", origin="website", refs=["website: /"])
        self.assertEqual(self.probe(intake, "V2.startAt() && V2.startAt().id"), "name")   # a draft waiting: there

    def test_the_ux_audit_changes(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        # Q29: platforms only for someone confirmed in "Who speaks"; never a silent "You" (rev 14, A4).
        self.assertIn('filter(function (x) { return x.name && x.status === "confirmed" && !x.remove; });', engine)
        self.assertNotIn('speakers = [{ id: "you", kind: "person", name: "You" }]', engine)
        self.assertIn("First tell us who speaks in your posts", engine)
        q29 = [f for f in S.fields()["core"] if f["id"] == "goal_platforms"][0]
        self.assertEqual(q29["ask"], "What do you want to make, and where will you post?")
        # Oct 23: every question says Needed or Optional in the same visible place (not in the small step label).
        self.assertIn('<p class="tag need">Needed to write your first post</p>', engine)
        self.assertIn('<p class="tag opt">Optional</p>', engine)
        self.assertIn('<div class="actions more">', engine)                      # two main actions, the rest quieter
        self.assertIn('id="settings-pack"', steps)                               # the business type is in Settings

    def test_the_rules_question_shows_every_word_it_confirms(self):
        # Round 2 of the build review: the words you never use are stored with the rules; "one more thing" shows them.
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn('textInput(fid(field, "hated_words"), "Words you never use (one per line)", ru.hated_words, "lines")', engine)
        self.assertIn('["never_claim", "never_name", "hated_words", "sign_off"].forEach(', engine)

    def test_next_and_back_remember_where_a_question_was_opened(self):
        steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        one = (STATIC / "one-page.html").read_text(encoding="utf-8")
        self.assertIn('if (ctx === "better" && better().indexOf(f) >= 0) { return better(); }', steps)
        self.assertIn('ctx = b.hasAttribute("data-better") ? "better" : "route";', steps)
        self.assertIn('if (ctx === "better" && V.betterFields().indexOf(f) >= 0) { return V.betterFields(); }', one)
        self.assertIn("if (steering) { return; }", one)                          # Next/Back keep their list
        self.assertIn('if (e.target.closest && e.target.closest("[data-act]")) { return; }', one)   # Skip keeps the list too
        self.assertIn('if (f && $("better").contains(card) && V.betterFields().indexOf(f) >= 0) { ctx = "better"; }', one)
        phrases = [f for f in S.fields()["core"] if f["id"] == "phrases"][0]
        self.assertEqual([p["name"] for p in phrases["parts"]], ["signature_phrases"])   # one editor for the words you never use

    def test_everything_a_confirm_carries_is_on_screen_in_its_step(self):
        # Deep review of rev 14: questions 4-6 share one stored answer, so confirming 4 carries 5 and 6; all three are in
        # step 2 (5 and 6 optional), never hidden in Make it better.
        steps = {s["id"]: s for s in S.fields()["five_steps"]}
        self.assertEqual(steps["customer"]["fields"], ["audience_who", "audience_way", "audience_questions"])
        self.assertEqual(steps["customer"]["optional"], ["audience_way", "audience_questions"])

    def test_both_designs_show_no_colour_coding_or_counts_of_31(self):
        steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        one = (STATIC / "one-page.html").read_text(encoding="utf-8")
        for page in (steps, one):
            self.assertNotIn("of 31", page)
            self.assertNotIn("V.chipKey()", page)
            self.assertNotIn("V.coverageTag(", page)
            self.assertIn("Make it better", page)
        self.assertIn("of 5 steps done", steps)
        self.assertIn("V.fiveRoute()", one)
        self.assertNotIn('id="found-drafts"', (STATIC / "v2-common.js").read_text(encoding="utf-8"))   # one main action

    def test_the_five_steps_live_in_one_place(self):
        f = S.fields()
        ids = [x for s in f["five_steps"] for x in s["fields"]]
        self.assertEqual(ids, self.FIVE)
        self.assertEqual(f["one_more"], ["rules"])
        every = {x["id"] for x in f["core"]}
        self.assertTrue(set(ids) <= every)
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("the same five steps as the page", skill)
        self.assertIn("otherwise the default colours", skill)                    # A5: no promise of their colours


class TestM10Leftovers(unittest.TestCase):
    def test_both_material_folders_are_git_ignored(self):
        import shutil, subprocess
        git = shutil.which("git")
        if not git:
            self.skipTest("git isn't installed here")
        root = STATIC.parents[2]
        for p in (".factory/tmp/onboarding-material/book.pdf", "Client/maple-and-main/Inputs/Material/book.pdf",
                  "Client/example-company/Inputs/Material/book.pdf", "Client/example-person/Inputs/Material/book.pdf",
                  "Client/some-new-brand/Inputs/Material/book.pdf", "Client/maple-and-main/_state/inventory.json",
                  "Client/maple-and-main/_state/onboarding-answers.json"):
            r = subprocess.run([git, "check-ignore", "-q", p], cwd=str(root))
            self.assertEqual(r.returncode, 0, "%s would go to GitHub" % p)

    def test_finishing_twice_gives_the_same_brand(self):
        import os, tempfile
        from unittest import mock
        from smf import brands
        from tests.test_brands import BAKERY
        with tempfile.TemporaryDirectory() as d, mock.patch.object(brands, "CLIENT_DIR", os.path.join(d, "Client")), \
                mock.patch.object(brands, "ROOT", d), mock.patch.object(S, "ROOT", d):
            brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
            intake = S.intake_from_draft(sample())
            intake.update(state="complete", brand="maple-and-main")
            seen = []
            for _ in range(2):
                b = brands.load("maple-and-main")
                _, answers, _, _ = T.build(intake, current=b.data)
                brands.update("maple-and-main", answers)
                seen.append(json.dumps(brands.load("maple-and-main").data, sort_keys=True))
            self.assertEqual(seen[0], seen[1])


class TestTheKeyCheckCatchesRealKeyShapes(unittest.TestCase):
    """Found while building #43: sk-ant-api03-… (the shape of a real Anthropic key) slipped past the check."""
    def test_real_shapes_are_caught_and_ordinary_words_arent(self):
        from smf.onboarding_page import secrets_check as K
        for t in ("sk-ant-api03-" + "Ab9xQ2" * 8, "my key is sk-ant-api03-" + "A" * 40, "sk-svcacct-" + "aB3_" * 8,
                  "sk-ant-admin01-" + "x9" * 12, "sk-proj-" + "aB3" * 16):
            self.assertTrue(K.looks_secret(t), t)
        for t in ("Ask-me-anything-about sourdough baking every single day", "a sk-test-run of the oven"):
            self.assertFalse(K.looks_secret(t), t)


class TestTheDemo(unittest.TestCase):
    def test_the_demo_bakery_loads_with_its_book(self):
        path = Path(S.__file__).parent / "demo_draft.json"
        intake = S.intake_from_draft(json.loads(path.read_text(encoding="utf-8")))
        self.assertTrue(intake["answers"]["positioning"]["core_belief"]["quoted"])
        self.assertTrue(any(x.get("dont_use") for x in intake["answers"]["inventory"]["sources"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
