"""Can a ninth grader get started? (plain-reader audit, Oct 23): the five answers a first post needs are marked, the rest
say Optional, skipping a needed one is a smaller button, the finish screen names what's still needed, "How do people find
you today?" is its own question in Make it better, and our own wording is plainer while platform words stay."""
import unittest

from smf.onboarding_page import session as S
from smf.onboarding_page import to_brand as T
from tests.test_onboarding_designs import needs_flask
from tests import test_onboarding_rev13 as R13
from tests.test_onboarding_rev13 import STATIC

NEEDED = ["name", "what_you_do", "audience_who", "identities", "voice_samples"]


def ok(**k):
    return dict({"status": "confirmed", "source": "typed", "origin": "person"}, **k)


def step4_done(intake):
    a = intake["answers"]
    a["identities"] = [ok(id="company", kind="company", name="Green Thumb Gardens", tapped=True)]
    a["make"] = ok(value=["posts"])
    a["platforms"] = ok(by_speaker={"company": ["facebook"]})
    return intake


class TestTheQuestions(unittest.TestCase):
    def test_the_five_needed_answers_are_listed_with_plain_names(self):
        f = S.fields()
        self.assertEqual(f["needed"], NEEDED)
        self.assertEqual(sorted(f["needed_names"]), sorted(NEEDED))
        in_steps = [x for st in f["five_steps"] for x in st["fields"]]
        self.assertTrue(all(x in in_steps for x in NEEDED))

    def test_how_people_find_you_is_its_own_optional_question(self):
        q = next(x for x in S.fields()["extra"] if x["id"] == "acquisition")
        self.assertEqual((q["after"], q["kind"], q["key"], q["prefix"]), ("audience_questions", "items", "acquisition", "acq"))
        self.assertFalse(q["why"].startswith("Optional"))              # the Optional tag says it; not twice
        self.assertNotIn("acquisition", S.CORE_KEYS)                  # never a placeholder

    def test_it_still_reaches_the_brand(self):
        intake = S.blank_intake()
        intake["answers"]["acquisition"] = [ok(id="acq-1", value="Word of mouth"),
                                            dict(ok(id="acq-2", value="Google"), status="unconfirmed")]
        self.assertEqual(T.build(intake)[1]["audience"]["acquisition"], [{"id": "acq-1", "value": "Word of mouth", "source": "typed"}])

    def test_a_draft_of_it_from_material_comes_in_waiting_and_reads_back_from_the_brand(self):
        from unittest import mock
        intake = S.intake_from_draft({"answers": {"acquisition": [
            {"id": "acq-1", "value": "Google Maps", "origin": "website", "refs": ["website: /about"]}]}})
        row = intake["answers"]["acquisition"][0]
        self.assertEqual((row["status"], row["source"]), ("unconfirmed", "draft"))
        self.assertNotIn("acquisition", T.build(intake)[1].get("audience", {}))     # waiting: not in the brand
        brand = mock.Mock(data={"audience": {"acquisition": [{"id": "acq-1", "value": "Word of mouth"}]}})
        brand.path = lambda *parts: "no-such-file-here"
        back = S.answers_from_brand(brand)["acquisition"]
        self.assertEqual((back[0]["value"], back[0]["status"]), ("Word of mouth", "unconfirmed"))
        self.assertEqual(S.validate_answer("acquisition", back), [])

    def test_our_own_wording_is_plainer_and_platform_words_stay(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        handle = next(x for x in S.fields()["core"] if x["id"] == "handle")
        self.assertEqual(handle["parts"][0]["label"], "Website or handle (your @name)")
        self.assertIn("website or handle (your @name)", handle["ask"])
        self.assertIn('{ id: "visuals", label: "Carousels and cards", hint: "swipe-through posts" }', engine)
        self.assertIn('{ id: "none", label: "None of these" }', engine)
        self.assertIn('"Who checks posts before they go out (one per line)"', engine)
        self.assertIn('label: "More inquiries"', engine)
        for gone in ("No regulator", "signs off before", "enquiries", "Skip anything"):
            self.assertNotIn(gone, engine)
        self.assertIn("Five short steps. Five answers get you started; you can skip the rest.", engine)

    def test_question_29_no_longer_holds_how_people_find_you(self):
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertNotIn('fid(field, "acquisition")', engine)
        self.assertNotIn('put("acquisition"', engine)


@needs_flask
class TestThePageRunsIt(unittest.TestCase):
    def probe(self, intake, js):
        return R13.TestTheOrderRunsForReal.order(self, intake, js)

    def test_needed_and_optional_are_said_on_every_question(self):
        html = self.probe(S.blank_intake(), "['name', 'handle', 'rung_main', 'rules', 'influences', 'identities'].map((id) => V2.fieldHTML(V2.fieldById(id)))")
        need, opt = '<p class="tag need">Needed to write your first post</p>', '<p class="tag opt">Optional</p>'
        for i, id_ in enumerate(["name", "handle", "rung_main", "rules", "influences", "identities"]):
            self.assertEqual(need in html[i], id_ in NEEDED, id_)
            self.assertEqual(opt in html[i], id_ not in NEEDED, id_)
        self.assertNotIn("· Optional", "".join(self.probe(S.blank_intake(), "V2.fiveRoute().map((f) => V2.stepLabel(f))")))

    def test_every_question_says_needed_or_optional_exactly_once(self):
        js = ("V2.fields().core.concat(V2.fields().extra, V2.fields().deep).map((f) => [f.id, V2.fieldHTML(f)])")
        need, opt = '<p class="tag need">', '<p class="tag opt">'
        for fid, html in self.probe(S.blank_intake(), js):
            self.assertEqual(html.count(need) + html.count(opt), 1, fid)
            self.assertEqual(need in html, fid in NEEDED, fid)

    def test_skipping_a_needed_answer_is_the_smaller_button(self):
        html = self.probe(S.blank_intake(), "['name', 'handle'].map((id) => V2.fieldHTML(V2.fieldById(id)))")
        self.assertIn('class="quiet" data-act="skip"', html[0])                # design A here (no flow): just quieter
        self.assertNotIn('quiet" data-act="skip"', html[1])

    def test_the_finish_screen_names_what_is_still_needed(self):
        intake = S.blank_intake()
        self.assertEqual(len(self.probe(intake, "V2.neededLeft()")), 5)
        intake["answers"]["name"] = ok(value="Green Thumb Gardens", tapped=True)
        left = self.probe(intake, "V2.neededLeft()")
        self.assertEqual(left[0], "what you do")
        self.assertNotIn("your brand name", left)
        self.assertIn("To write your first post we still need:", self.probe(intake, "V2.neededLeftHTML()"))
        for f in ("steps.html", "one-page.html"):
            self.assertIn("V.neededLeftHTML()", (STATIC / f).read_text(encoding="utf-8"), f)

    def test_how_people_find_you_sits_in_make_it_better_after_the_questions_they_ask(self):
        better = self.probe(S.blank_intake(), "V2.betterFields().map((f) => f.id)")
        self.assertIn("acquisition", better)
        self.assertNotIn("acquisition", self.probe(S.blank_intake(), "V2.fiveRoute().map((f) => f.id)"))
        self.assertEqual(self.probe(S.blank_intake(), "V2.stepLabel(V2.fieldById('acquisition'))"), "Make it better · Audience")
        order = self.probe(S.blank_intake(), "V2.coreOrder().map((f) => f.id)")
        self.assertEqual(order[order.index("audience_questions") + 1], "acquisition")

    def test_a_draft_of_it_waiting_no_longer_holds_step_4_back(self):
        intake = step4_done(S.blank_intake())
        intake["answers"]["acquisition"] = [{"id": "acq-1", "value": "Google", "status": "unconfirmed", "source": "draft",
                                             "origin": "website", "refs": ["website: /about"]}]
        self.assertEqual(self.probe(intake, "V2.stepState(3)"), "ok")
        self.assertEqual(self.probe(intake, "V2.stateOf(V2.fieldById('acquisition'))"), "check")

    def test_its_saved_answers_show_as_done_in_make_it_better(self):
        intake = S.blank_intake()
        intake["answers"]["acquisition"] = [ok(id="acq-1", value="Word of mouth")]
        self.assertEqual(self.probe(intake, "V2.stateOf(V2.fieldById('acquisition'))"), "ok")
        self.assertIn("Word of mouth", self.probe(intake, "V2.fieldHTML(V2.fieldById('acquisition'))"))


if __name__ == "__main__":
    unittest.main()
