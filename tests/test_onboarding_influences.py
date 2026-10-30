"""Who inspires you? (spec smf-spec-influences.md): an optional question in Make it better, only ever the owner's own
answers or quotes of their own writing, kept in the brand as `influences` for Planning and writing (#49)."""
import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from smf import brands
from smf.onboarding_page import session as S
from smf.onboarding_page import summary
from smf.onboarding_page import to_brand as T
from tests.test_onboarding_designs import needs_flask
from tests import test_onboarding_rev13 as R13


def typed(rid, name, why=None, status="confirmed"):
    row = {"id": rid, "name": name, "status": status, "source": "typed", "origin": "person"}
    if why:
        row["why"] = why
    return row


def quoted(rid, name, excerpt, ref="src-1 rev 7f3a p.4", **more):
    return dict({"id": rid, "name": name, "status": "unconfirmed", "source": "draft", "origin": "document", "quoted": True,
                 "said_by": "owner", "excerpt": excerpt, "refs": [ref], "generator": "claude-from-document"}, **more)


def intake_with(answer):
    intake = S.blank_intake()
    intake["answers"]["influences"] = answer
    return intake


def exported(answer):
    _, answers, _, _ = T.build(intake_with(answer))
    return answers.get("influences", "NOTHING")


class TestTheQuestion(unittest.TestCase):
    def test_it_is_an_optional_extra_after_signature_phrases(self):
        f = next(x for x in S.fields()["extra"] if x["id"] == "influences")
        self.assertEqual((f["after"], f["group"], f["kind"], f["list"]), ("phrases", "sound", "items", "items"))
        self.assertTrue(f["never_draft"] and f["own_status"])
        self.assertEqual([p["name"] for p in f["item_parts"]], ["name", "why"])
        self.assertIn("influences", S.EXTRA_KEYS)
        self.assertNotIn("influences", S.CORE_KEYS)

    def test_skipping_it_is_never_a_placeholder(self):
        self.assertNotIn("influences", S.placeholders(S.blank_intake(), keys=S.CORE_KEYS))
        self.assertNotIn("influences", S.placeholders(intake_with({"status": "skipped", "items": []}), keys=S.CORE_KEYS))


class TestWhatTheBrandGets(unittest.TestCase):
    """The export table: the brand's list is replaced whole, and only when the question itself is confirmed."""
    def test_confirmed_rows_reach_the_brand_with_and_without_why(self):
        got = exported({"status": "confirmed", "items": [typed("influence-1", "Rick Rubin", "how he strips things back"),
                                                         typed("influence-2", "Naval Ravikant")]})
        self.assertEqual(got, [{"id": "influence-1", "name": "Rick Rubin", "why": "how he strips things back", "source": "typed"},
                               {"id": "influence-2", "name": "Naval Ravikant", "source": "typed"}])

    def test_each_case_of_the_table(self):
        waiting = quoted("influence-3", "Rick Rubin", "I learn most from Rick Rubin.")
        cases = [
            ({"status": "confirmed", "items": []}, []),                                               # confirmed empty
            ({"status": "confirmed", "items": [{"id": "influence-1", "remove": True, "status": "confirmed"}]}, []),
            ({"status": "confirmed", "items": [waiting]}, "NOTHING"),                                 # only quotes waiting
            ({"status": "confirmed", "items": [typed("influence-1", "Ava"), waiting]},
             [{"id": "influence-1", "name": "Ava", "source": "typed"}]),                              # mixed: kept only
            # Skipped later, after rows were confirmed: those yeses stand, as on every list question (the page shows Done).
            ({"status": "skipped", "items": [typed("influence-1", "Ava")]}, [{"id": "influence-1", "name": "Ava", "source": "typed"}]),
            ({"status": "skipped", "items": []}, "NOTHING"),                                         # skipped never clears
            ({"status": "skipped", "items": [{"id": "influence-1", "remove": True, "status": "confirmed"}]}, "NOTHING"),
            ({"status": "unconfirmed", "items": [typed("influence-1", "Ava", status="unconfirmed")]}, "NOTHING"),
        ]
        for answer, want in cases:
            self.assertEqual(exported(answer), want, answer)
        self.assertEqual(T.build(S.blank_intake())[1].get("influences", "NOTHING"), "NOTHING")   # never answered

    def test_no_remove_marker_ever_reaches_the_brand(self):
        got = exported({"status": "confirmed", "items": [typed("influence-2", "Ava"),
                                                         {"id": "influence-1", "remove": True, "status": "confirmed"}]})
        self.assertNotIn("remove", json.dumps(got))
        _, answers, _, _ = T.build(intake_with({"status": "confirmed", "items": [{"id": "influence-1", "remove": True,
                                                                                    "status": "confirmed"}]}),
                                   current={"influences": [{"id": "influence-1", "name": "Ava"}]})
        self.assertEqual(answers["influences"], [])

    def test_a_confirmed_quote_is_kept_as_quoted(self):
        q = quoted("influence-1", "Rick Rubin", "I learn most from Rick Rubin.", status="confirmed", accepted=True)
        got = exported({"status": "confirmed", "items": [q]})
        self.assertEqual(got[0]["source"], "quoted")
        self.assertNotIn("excerpt", json.dumps(got))

    def test_the_shape_planning_reads(self):
        # Planning's topics.influences() reads "name" and "why" from each item, or a plain name.
        for item in exported({"status": "confirmed", "items": [typed("influence-1", "Rick Rubin", "pace")]}):
            self.assertTrue(item["name"].strip())
            self.assertIsInstance(item.get("why", ""), str)


class TestOnlyTheOwnersOwn(unittest.TestCase):
    def test_suggested_words_are_refused(self):
        for origin, gen in (("starter-pack", "pack:bakery@1"), ("description", "claude-from-description")):
            row = dict(typed("influence-1", "Rick Rubin", status="unconfirmed"), source="draft", origin=origin, generator=gen)
            self.assertTrue(S.validate_answer("influences", {"status": "unconfirmed", "items": [row]}), origin)

    def test_a_draft_that_isnt_a_quote_is_refused(self):
        row = dict(typed("influence-1", "Rick Rubin", status="unconfirmed"), source="draft", origin="website")
        self.assertTrue(S.validate_answer("influences", {"status": "unconfirmed", "items": [row]}))
        with self.assertRaises(S.SessionError):
            S.intake_from_draft({"answers": {"influences": {"status": "unconfirmed", "items": [row]}}})

    def test_a_made_up_why_beside_a_quoted_name_is_refused(self):
        row = quoted("influence-1", "Rick Rubin", "I learn most from Rick Rubin.", why="the way he edits", quoted_parts=["name"])
        with self.assertRaises(S.SessionError):
            S.intake_from_draft({"answers": {"influences": {"status": "unconfirmed", "items": [row]}}})

    def test_the_owner_may_add_their_own_why_beside_a_quoted_name(self):
        # As with the others/us rows: what the owner types beside a quote is theirs and doesn't undo it.
        row = quoted("influence-1", "Rick Rubin", "I learn most from Rick Rubin.", why="the way he edits",
                     quoted_parts=["name"], status="confirmed", accepted=True)
        self.assertEqual(S.validate_answer("influences", {"status": "confirmed", "items": [row]}), [])
        row["name"] = "Brian Eno"                                   # a quoted part that isn't in the passage
        self.assertTrue(S.validate_answer("influences", {"status": "confirmed", "items": [row]}))

    def test_a_quote_needs_its_own_yes(self):
        row = quoted("influence-1", "Rick Rubin", "I learn most from Rick Rubin.", status="confirmed")
        self.assertTrue(S.validate_answer("influences", {"status": "confirmed", "items": [row]}))
        row["accepted"] = True
        self.assertEqual(S.validate_answer("influences", {"status": "confirmed", "items": [row]}), [])

    def test_a_good_quote_comes_in_as_a_draft_waiting(self):
        row = quoted("influence-1", "Rick Rubin", "I learn most from Rick Rubin.", status="confirmed", accepted=True)
        intake = S.intake_from_draft({"answers": {"influences": {"status": "confirmed", "items": [row]}}})
        got = intake["answers"]["influences"]
        self.assertEqual(got["status"], "unconfirmed")
        self.assertEqual(got["items"][0]["status"], "unconfirmed")      # whatever the draft said
        self.assertEqual(exported(got), "NOTHING")


class TestTheBrandSettings(unittest.TestCase):
    def setUp(self):
        from tests.test_brands import BAKERY
        self.tmp = tempfile.TemporaryDirectory(prefix="influences ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name), mock.patch.object(S, "ROOT", self.tmp.name)]
        for x in self.patches:
            x.start()
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", copy.deepcopy(BAKERY))

    def tearDown(self):
        for x in self.patches:
            x.stop()
        self.tmp.cleanup()

    def test_validate_takes_names_and_rows_only(self):
        good = [{"id": "influence-1", "name": "Rick Rubin", "why": "pace", "source": "typed"}, "Naval Ravikant"]
        self.assertEqual(brands._influence_problems(good), [])
        for bad in (3, "  ", {"why": "pace"}, {"name": " "}, {"name": "Ava", "why": 4},
                    {"name": "Ava", "source": "drafted"}, {"name": "Ava", "source": "mixed"}):
            self.assertTrue(brands._influence_problems([bad]), bad)
        self.assertTrue(brands._influence_problems("Rick Rubin"))
        # And through the brand's own check, which every save runs.
        data = copy.deepcopy(self.brand.data)
        data["influences"] = good
        self.assertEqual(brands.validate(data)[0], [])
        data["influences"] = [{"name": "Ava", "source": "drafted"}]
        self.assertTrue(any("influences[1]" in p for p in brands.validate(data)[0]))

    def test_replaced_whole_on_update(self):
        brands.update("maple-and-main", {"influences": [{"id": "influence-1", "name": "Rick Rubin", "why": "pace"},
                                                        {"id": "influence-2", "name": "Ava"}]})
        brands.update("maple-and-main", {"influences": [{"id": "influence-1", "name": "Rick Rubin"}]})   # why cleared, Ava removed
        self.assertEqual(brands.load("maple-and-main").data["influences"], [{"id": "influence-1", "name": "Rick Rubin"}])
        brands.update("maple-and-main", {"influences": []})
        self.assertEqual(brands.load("maple-and-main").data["influences"], [])
        with self.assertRaises(brands.BrandError):
            brands.update("maple-and-main", {"influences": [{"name": "Ava", "source": "drafted"}]})

    def test_check_again_reads_them_back_including_names_written_by_hand(self):
        brands.update("maple-and-main", {"influences": ["Naval Ravikant", {"id": "influence-1", "name": "Rick Rubin", "why": "pace"},
                                                        {"name": "Ava"}]})
        a = S.answers_from_brand(brands.load("maple-and-main"))["influences"]
        self.assertEqual(a["status"], "unconfirmed")
        rows = a["items"]
        self.assertEqual([r["name"] for r in rows], ["Naval Ravikant", "Rick Rubin", "Ava"])
        self.assertEqual(len({r["id"] for r in rows}), 3)
        self.assertTrue(all(r["restored"] and r["status"] == "unconfirmed" for r in rows))
        self.assertEqual(S.validate_answer("influences", a), [])
        # The owner removes the hand-written name and confirms: the brand's list is replaced, nothing duplicated.
        rows[0] = {"id": rows[0]["id"], "remove": True, "status": "confirmed"}
        for r in rows[1:]:
            r["status"] = "confirmed"
        _, answers, _, _ = T.build(intake_with({"status": "confirmed", "items": rows}), current=brands.load("maple-and-main").data)
        brands.update("maple-and-main", answers)
        self.assertEqual([x["name"] for x in brands.load("maple-and-main").data["influences"]], ["Rick Rubin", "Ava"])

    def test_a_quote_saved_read_back_and_then_its_file_marked_dont_use_is_still_found(self):
        q = quoted("influence-1", "Rick Rubin", "I learn most from Rick Rubin.", status="confirmed", accepted=True)
        _, answers, _, _ = T.build(intake_with({"status": "confirmed", "items": [q, typed("influence-2", "Ava")]}),
                                   current=self.brand.data)
        brands.update("maple-and-main", answers)
        back = {"answers": S.answers_from_brand(brands.load("maple-and-main"))}
        self.assertEqual(S.validate_answer("influences", back["answers"]["influences"]), [])
        out = S.withdraw_source(back, "src-1")
        self.assertEqual([x["name"] for x in out["removals"]["influences"]], ["Ava"])

    def test_the_summary_shows_them_escaped_and_nothing_when_none(self):
        path = summary.build("maple-and-main")
        with open(path, encoding="utf-8") as fh:
            self.assertNotIn("Who inspires you", fh.read())
        brands.update("maple-and-main", {"influences": [{"id": "influence-1", "name": "<b>Rick</b>", "why": "pace & space"},
                                                        "Naval Ravikant"]})
        with open(summary.build("maple-and-main"), encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("Who inspires you", page)
        self.assertIn("&lt;b&gt;Rick&lt;/b&gt;: pace &amp; space", page)
        self.assertIn("<li>Naval Ravikant</li>", page)


class TestDontUseLater(unittest.TestCase):
    def test_only_the_quote_from_that_file_goes_and_the_rest_reaches_the_brand_whole(self):
        intake = intake_with({"status": "confirmed", "items": [
            quoted("influence-1", "Rick Rubin", "I learn most from Rick Rubin.", status="confirmed", accepted=True),
            typed("influence-2", "Ava", "her openings")]})
        out = S.withdraw_source(intake, "src-1")
        self.assertEqual(out["removals"], {"influences": [{"id": "influence-2", "name": "Ava", "why": "her openings",
                                                           "source": "typed"}]})
        self.assertNotIn("Rick Rubin", json.dumps(out["removals"]))
        self.assertEqual(exported(intake["answers"]["influences"]), [{"id": "influence-2", "name": "Ava", "why": "her openings",
                                                                      "source": "typed"}])

    def test_a_quote_whose_source_is_only_on_the_question_is_found(self):
        q = quoted("influence-1", "Rick Rubin", "I learn most from Rick Rubin.", status="confirmed", accepted=True)
        del q["refs"]
        intake = intake_with({"status": "confirmed", "items": [q]})
        intake["answers"]["provenance"] = {"influences": {"origin": "document", "refs": ["src-1 rev 7f3a p.4"]}}
        out = S.withdraw_source(intake, "src-1")
        self.assertEqual(out["removals"], {"influences": []})

    def test_a_file_that_gave_none_changes_nothing(self):
        intake = intake_with({"status": "confirmed", "items": [typed("influence-2", "Ava")]})
        self.assertNotIn("influences", S.withdraw_source(intake, "src-1")["removals"])


@needs_flask
class TestThePageRunsIt(unittest.TestCase):
    """The page's own code, run in Node: where it sits, and how it shows done, skipped and waiting."""
    def probe(self, intake, js):
        return R13.TestTheOrderRunsForReal.order(self, intake, js)

    def test_it_sits_in_make_it_better_right_after_phrases_and_not_in_the_five_steps(self):
        ids = self.probe(S.blank_intake(), "V2.betterFields().map((f) => f.id)")
        self.assertEqual(ids[ids.index("phrases") + 1], "influences")
        self.assertNotIn("influences", self.probe(S.blank_intake(), "V2.fiveRoute().map((f) => f.id)"))
        self.assertEqual(self.probe(S.blank_intake(), "V2.stepLabel(V2.fieldById('influences'))"), "Make it better · How you sound")
        self.assertEqual(self.probe(S.blank_intake(), "V2.steps().length"), 5)

    def test_done_skipped_and_waiting_after_reopening(self):
        js = "V2.stateOf(V2.fieldById('influences'))"
        ok = self.probe(intake_with({"status": "confirmed", "items": [typed("influence-1", "Ava")]}), js)
        self.assertEqual(self.probe(intake_with({"status": "confirmed", "items": []}), js), ok)        # confirmed empty: done
        skip = self.probe(intake_with({"status": "skipped", "items": []}), js)
        self.assertNotIn(skip, (ok, ""))
        wait = self.probe(intake_with({"status": "confirmed", "items": [quoted("influence-1", "Rick Rubin", "Rick Rubin.")]}), js)
        self.assertNotIn(wait, (ok, skip))
        # Never answered: the same as any other unanswered list question.
        self.assertEqual(self.probe(S.blank_intake(), js), self.probe(S.blank_intake(), "V2.stateOf(V2.fieldById('myths'))"))
        self.assertNotEqual(self.probe(S.blank_intake(), js), ok)

    def test_the_new_flag_leaves_the_customer_questions_alone(self):
        intake = S.blank_intake()
        intake["answers"]["audience"] = {"value": "Busy families nearby.", "status": "confirmed", "source": "typed", "origin": "person",
                                         "objections": []}
        before = self.probe(intake, "V2.stateOf(V2.fieldById('objections'))")
        self.assertEqual(before, self.probe(S.blank_intake(), "V2.stateOf(V2.fieldById('objections'))"))

    def test_no_pack_can_suggest_names(self):
        f = next(x for x in S.fields()["extra"] if x["id"] == "influences")
        self.assertTrue(f["never_draft"])
        for p in S.starter_packs()["packs"]:
            self.assertNotIn("influences", p.get("suggestions") or {})
        self.assertNotIn("influences", S.starter_packs().get("allowlist") or [])
        # Even a custom pack (Claude, from the owner's description) that lists names can't offer them.
        intake = S.blank_intake()
        intake["answers"]["starter_pack"] = {"id": "custom", "status": "confirmed", "suggestions": {"influences": ["Rick Rubin"]}}
        js = "[V2.fieldById('influences')].map((f) => !!(f.never_draft))[0]"
        self.assertTrue(self.probe(intake, js))


if __name__ == "__main__":
    unittest.main()
