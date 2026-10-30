"""Onboarding v2 page designs: A, one long page (--layout one-page), and B, one question at a time
(--layout steps). Spec: smf-spec-onboarding-v2.md rev 11 and its A and B documents.

    python -m unittest tests.test_onboarding_designs -v
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf.onboarding_page import cli as page_cli          # noqa: E402
from smf.onboarding_page import session as S             # noqa: E402
from smf.onboarding_page import voice as V               # noqa: E402

STATIC = ROOT / "smf" / "onboarding_page" / "static"
HAVE_FLASK = importlib.util.find_spec("flask") is not None
needs_flask = unittest.skipUnless(HAVE_FLASK, "Flask is installed by `python factory.py setup`")


def schema_answers():
    return json.loads((ROOT / "smf" / "onboarding_page" / "intake.schema.json").read_text(encoding="utf-8"))["properties"]["answers"]["properties"]


class TestTheQuestions(unittest.TestCase):
    """fields.json: the one list both designs ask, so they can never ask different things."""

    def setUp(self):
        self.f = S.fields()

    def test_the_core_is_exactly_31_fields_numbered_in_order(self):
        self.assertEqual([q["n"] for q in self.f["core"]], list(range(1, 32)))

    def test_every_field_has_a_question_a_reason_and_a_known_group(self):
        groups = {g["id"] for g in self.f["groups"]}
        deep_groups = {g["id"] for g in self.f["deep_groups"]}
        ids = [q["id"] for q in self.f["core"] + self.f["deep"]]
        self.assertEqual(len(ids), len(set(ids)), "field ids must be unique")
        for q in self.f["core"]:
            self.assertIn(q["group"], groups, q["id"])
            self.assertTrue(q["ask"] and q["why"], q["id"])
        for q in self.f["deep"]:
            self.assertIn(q["group"], deep_groups, q["id"])
            self.assertEqual(q["key"], "deep", q["id"])

    def test_every_field_saves_into_a_real_answer_and_part(self):
        answers = schema_answers()
        for q in self.f["core"] + self.f["deep"]:
            if q["kind"] == "goal_platforms":
                continue                                 # saves goal, platforms and make
            self.assertIn(q["key"], S.ANSWER_KEYS, q["id"])
            node = answers[q["key"]]
            if q.get("path"):
                self.assertIn(q["path"], node["properties"], q["id"])
                node = node["properties"][q["path"]]
            for part in q.get("parts", []):
                where = answers[part["key"]] if part.get("key") else node
                self.assertIn(part["name"], where["properties"], "%s.%s" % (q["id"], part["name"]))
            if q.get("list") and q["key"] != "show":
                self.assertIn(q["list"], node["properties"], q["id"])

    def test_beliefs_others_us_and_non_negotiables_are_never_drafted(self):
        never = {q["n"] for q in self.f["core"] if q.get("never_draft")}
        self.assertEqual(never, {14, 16, 17})            # F8 B, D and E

    def test_the_strategy_group_is_fields_13_to_19_right_after_how_you_sound(self):
        stand = [q["n"] for q in self.f["core"] if q["group"] == "stand"]
        self.assertEqual(stand, list(range(13, 20)))
        order = [g["id"] for g in self.f["groups"]]
        self.assertEqual(order.index("stand"), order.index("sound") + 1)

    def test_the_name_is_social_media_factory_never_just_the_factory(self):
        for name in ("fields.json", "static/v2-common.js", "static/one-page.html", "static/steps.html"):
            text = (ROOT / "smf" / "onboarding_page" / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(?<!Social Media )\bFactory\b", text), name)


class PageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="page v2 ' é ")
        self.patch = mock.patch.object(S, "ROOT", self.tmp.name)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def open(self, layout):
        if not HAVE_FLASK:
            self.skipTest("Flask is installed by `python factory.py setup`")
        from smf.onboarding_page import server
        self.session = S.new_session(8652, S.intake_from_draft(None), layout=layout)
        self.code = self.session["code"]
        self.client = server.create_app(self.code).test_client()

    def get(self, path=""):
        return self.client.get("/%s/%s" % (self.code, path))


class TestTheTwoDesigns(PageCase):
    def test_each_layout_serves_its_design_with_the_shared_engine_inline(self):
        for layout, marker in (("one-page", "design A: one long page"), ("steps", "design B: one question at a time")):
            self.open(layout)
            r = self.get()
            self.assertEqual(r.status_code, 200)
            page = r.get_data(as_text=True)
            self.assertIn(marker, page, layout)
            self.assertIn("window.V2 = {", page, layout)               # the engine is inline
            self.assertIn("--ink:#111111", page, layout)                # and so is the shared look
            self.assertNotIn("@V2_COMMON", page, layout)                # no marker left behind
            self.assertNotIn("<script src", page, layout)               # nothing loaded from anywhere
            self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])

    def test_without_a_layout_todays_page_runs_unchanged(self):
        self.open(None)
        page = self.get().get_data(as_text=True)
        self.assertIn("Brand basics 0 of 8", page)
        self.assertNotIn("window.V2", page)

    def test_an_unknown_layout_is_refused_before_anything_opens(self):
        with self.assertRaises(S.SessionError):
            S.new_session(8652, S.intake_from_draft(None), layout="carousel")

    def test_the_fields_are_served_to_the_page(self):
        self.open("steps")
        r = self.get("api/fields")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()["core"]), 31)

    def test_a_design_counts_the_whole_core_as_placeholders_until_confirmed(self):
        self.open("one-page")
        view = self.get("api/session").get_json()
        self.assertEqual(view["placeholders"], list(S.CORE_KEYS))
        self.assertFalse(view["consented"])
        r = self.client.post("/%s/api/answer" % self.code, json={"key": "why_started", "answer": {
            "value": "Every class in town was for experts.", "status": "confirmed", "source": "typed", "origin": "person"}})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("why_started", r.get_json()["placeholders"])

    def test_todays_page_still_counts_only_its_eight(self):
        self.open(None)
        self.assertEqual(self.get("api/session").get_json()["placeholders"], list(S.BASICS))

    def test_answers_a_design_sends_are_saved_in_the_shared_shapes(self):
        self.open("one-page")
        post = lambda key, answer: self.client.post("/%s/api/answer" % self.code, json={"key": key, "answer": answer})
        cases = {
            "positioning": {"core_belief": {"value": "Anyone can learn the wheel.", "experience": "300 beginners",
                                            "status": "confirmed", "source": "typed", "origin": "person"},
                            "for": [{"id": "for-1", "value": "beginners", "status": "confirmed", "source": "typed", "origin": "person"}],
                            "story": {"catalyst": "Classes were for experts", "status": "confirmed", "source": "typed", "origin": "person"}},
            "ladder": [{"rung": "free", "name": "Taster night", "status": "confirmed", "source": "typed", "origin": "person"},
                       {"rung": "entry", "none_yet": True, "status": "confirmed", "source": "typed", "origin": "person"}],
            "goal": {"value": "leads", "status": "confirmed", "source": "typed", "origin": "person"},
            "platforms": {"by_speaker": {"person": ["instagram"]}, "status": "confirmed", "source": "typed", "origin": "person"},
            "capacity": {"hours_per_week": 3, "posts_per_week": 4, "status": "confirmed", "source": "typed", "origin": "person"},
            "show": [{"id": "show-1", "value": "Student bowls", "status": "confirmed", "source": "typed", "origin": "person"}],
            "deep": {"journey": {"want": "A studio in every town", "status": "confirmed", "source": "typed", "origin": "person"},
                     "stories": [{"id": "story-origin", "kind": "origin", "text": "I broke 40 bowls.",
                                  "status": "confirmed", "source": "typed", "origin": "person"}]},
        }
        for key, answer in cases.items():
            r = post(key, answer)
            self.assertEqual(r.status_code, 200, "%s: %s" % (key, r.get_json()))
        self.assertEqual(S.load_intake(self.session)["answers"]["goal"]["value"], "leads")

    def test_a_drafted_belief_is_still_refused_whichever_design_sends_it(self):
        self.open("steps")
        r = self.client.post("/%s/api/answer" % self.code, json={"key": "positioning", "answer": {
            "core_belief": {"value": "Drafted belief", "status": "unconfirmed", "source": "draft", "origin": "website"}}})
        self.assertEqual(r.status_code, 400)


class TestWhatTheDraftBrings(PageCase):
    @needs_flask
    def test_follow_up_notes_reach_the_page_one_per_field_and_nothing_else(self):
        draft = {"answers": {}, "followups": {"what_you_do": "Give one example from your own work.",
                                              "not_a_field": "dropped", "audience_who": "x" * 500}}
        self.session = S.new_session(8652, S.intake_from_draft(draft), layout="one-page")
        from smf.onboarding_page import server
        self.code = self.session["code"]
        self.client = server.create_app(self.code).test_client()
        self.assertEqual(self.get("api/session").get_json()["followups"],
                         {"what_you_do": "Give one example from your own work."})

    def test_a_follow_up_that_looks_like_a_key_is_dropped(self):
        fake_key = "sk-" + "ant-" + "a1B2c3D4e5F6g7H8i9J0kLmN"      # built in pieces, as in test_onboarding
        intake = S.intake_from_draft({"answers": {}, "followups": {"what_you_do": "Is it " + fake_key}})
        self.assertEqual(intake["followups"], {})

    def test_the_websites_colours_travel_with_the_draft(self):
        intake = S.intake_from_draft({"answers": {"colours": {"background": "#FAF6F0", "text": "#2A2018", "accent": "#B5532A",
                                                               "found": ["#FAF6F0", "#3E6B4F"], "status": "unconfirmed"}}})
        self.assertEqual(intake["answers"]["colours"]["found"], ["#FAF6F0", "#3E6B4F"])
        self.assertEqual(intake["answers"]["colours"]["status"], "unconfirmed")


class TestVoiceFollowsTheKeyState(PageCase):
    """Rev 11: one key state for status and the page. Voice is on only for a key that is there and not refused."""

    def test_the_page_gets_the_same_state_as_check_my_setup(self):
        self.open("one-page")
        from smf import verify_keys
        for state, available in (("missing", False), ("unverified", True), ("verified", True), ("not_working", False)):
            with mock.patch.object(verify_keys, "key_state", return_value=state):
                got = self.get("api/voice").get_json()
                self.assertEqual((got["available"], got["state"]), (available, state))
                # Rev 12, N8: the price comes from the one price list, shown only when they ask to talk.
                self.assertTrue(got["cost"].startswith("About 22 cents"))

    def test_a_refused_key_is_remembered_and_a_working_one_too(self):
        self.open("one-page")
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn("Say “check my setup” in the chat to fix it.", engine)      # rev 12: shown at the mic, typing goes on
        server_py = (ROOT / "smf" / "onboarding_page" / "server.py").read_text(encoding="utf-8")
        self.assertIn('if getattr(e, "refused", False):', server_py)
        self.assertIn("_remember_key(True, \"\")", server_py)


class TestProofForTheLibrary(unittest.TestCase):
    def test_confirmed_proof_becomes_library_items_with_the_six_parts_and_how_it_is_known(self):
        from smf.onboarding_page import to_brand
        intake = {"answers": {"deep": {"proof": [
            {"id": "proof-new-1", "bank": "credibility", "kind": "result", "title": "Bowls in six weeks",
             "context": "Evening beginners", "outcome": "28 of 30 finished a bowl", "known_from": "document",
             "source_text": "class register, 2026-09", "may_publish": "anonymised", "status": "confirmed"},
            {"id": "proof-new-2", "bank": "interest", "title": "Testing a glaze course", "status": "confirmed"},
            {"id": "proof-new-3", "title": "Not confirmed", "status": "unconfirmed"},
            {"id": "proof-old", "remove": True, "status": "confirmed"}]}}}
        items = to_brand.proof_items(intake)
        self.assertEqual([i["id"] for i in items], ["proof-new-1", "proof-new-2"])
        real, interest = items
        self.assertEqual(real["kind"], "result")
        self.assertEqual(real["detail"], "Context: Evening beginners\nWhat happened: 28 of 30 finished a bowl\n"
                                         "Known from: a document or screenshot they provided")
        self.assertEqual((real["source"], real["may_publish"]), ("class register, 2026-09", "anonymised"))
        # The Interest Bank is never a result, and nothing is publishable unless they said so.
        self.assertEqual((interest["kind"], interest["title"][:9], interest["may_publish"]), ("fact", "Interest:", "no"))


class TestTheCommandOpensADesign(unittest.TestCase):
    @needs_flask
    def test_design_b_is_the_default_and_classic_opens_the_first_page(self):
        # Spec rev 12, N1: one question at a time is the onboarding page.
        with mock.patch("smf.onboarding_page.server.serve", return_value=0) as serve:
            page_cli.cli_onboard_page(["--no-browser"])
            self.assertEqual(serve.call_args.kwargs["layout"], "steps")
            page_cli.cli_onboard_page(["--no-browser", "--layout", "classic"])
            self.assertIsNone(serve.call_args.kwargs["layout"])

    def test_layout_is_an_option_with_the_two_designs(self):
        a = page_cli._parser().parse_args(["--layout", "steps", "--no-browser"])
        self.assertEqual(a.layout, "steps")
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            page_cli._parser().parse_args(["--layout", "carousel"])

    @needs_flask
    def test_the_layout_reaches_the_server(self):
        with mock.patch("smf.onboarding_page.server.serve", return_value=0) as serve:
            self.assertEqual(page_cli.cli_onboard_page(["--layout", "one-page", "--no-browser"]), 0)
        self.assertEqual(serve.call_args.kwargs["layout"], "one-page")


class TestNextMovesOn(unittest.TestCase):
    def test_next_is_its_own_command_not_skip(self):
        for said in ("next", "Next question", "move on"):
            self.assertEqual(V.understand(said), {"kind": "command", "command": "next"}, said)
        self.assertEqual(V.understand("skip"), {"kind": "command", "command": "skip"})

    def test_todays_page_still_treats_next_as_skip(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('if (name === "skip" || name === "next") { return $("skip").click(); }', page)


class TestTheSharedRules(unittest.TestCase):
    """What both designs must do the same way (spec: 'Behaviour both designs must have')."""

    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")

    def test_typing_comes_first_and_the_mic_points_to_the_computers_own_dictation_without_a_key(self):
        # Spec rev 12, N1: no voice question on the first screen and no paid service named mid-onboarding.
        self.assertNotIn("sw-voice", self.engine)
        self.assertNotIn("22 cents", self.engine)
        self.assertIn("if (!voiceAvailable) { return dictationHint(field); }", self.engine)
        self.assertIn("press <b>Windows + H</b>", self.engine)
        self.assertIn("may send your voice to", self.engine)

    def test_people_are_warned_not_to_say_keys_out_loud_before_the_first_recording(self):
        self.assertIn("Don’t say passwords or keys out loud.", self.engine)
        self.assertIn('api("consent", { recording: true })', self.engine)

    def test_a_late_transcription_never_lands_on_another_question_or_over_typing(self):
        self.assertIn("a late answer never lands on another question", self.engine)
        self.assertIn("they typed while it was listening: offer, never overwrite", self.engine)

    def test_read_aloud_finishes_before_the_microphone_opens(self):
        self.assertIn("speak(field.ask).then(function () { return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true", self.engine)

    def test_names_handles_and_rules_need_a_tap_never_a_spoken_yes(self):
        self.assertIn("Names, handles and rules need a tap.", self.engine)

    def test_each_recording_keeps_its_own_state(self):
        # ChatGPT review, Oct 15: a recording still stopping must never hand its words to the next one.
        self.assertIn("var mine = { field: field.id, target: target.id, before: target.value", self.engine)
        self.assertIn("if (rec.cur !== mine) { stream.getTracks()", self.engine)

    def test_saves_run_one_after_another(self):
        self.assertIn("var run = queue.then(function () { return saveNow(field, status, ownWords); });", self.engine)

    def test_confirming_a_shared_answer_warns_about_unchecked_drafts_first(self):
        self.assertIn("Confirming this also confirms the drafted answer to: ", self.engine)
        self.assertIn('(f.kind === "object" || f.kind === "name") && stateOf(f) === "check"', self.engine)

    def test_added_rows_never_reuse_an_id(self):
        self.assertIn('items.setAttribute("data-next", String(n + 1));', self.engine)

    def test_design_b_waits_for_saves_and_keeps_unsaved_text_when_moving_on(self):
        steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        self.assertIn("function show(f) { return V.idle().then(function () { showNow(f); }); }", steps)
        self.assertIn("V.keep(at); }        // leaving a screen never loses what's typed there", steps)
        self.assertIn("V.bringBack(f);", steps)

    def test_design_bs_map_is_a_real_modal(self):
        steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        self.assertIn('["top", "app"].forEach(function (id) { $(id).inert = true; });', steps)

    def test_proof_without_a_title_is_asked_for_never_dropped_later(self):
        self.assertIn("Give each piece of proof a few words in the first box", self.engine)

    def test_a_new_row_never_keeps_the_saved_rows_id(self):
        self.assertIn('copy.setAttribute("data-id", "");', self.engine)

    def test_both_designs_use_the_one_engine_and_start_it_the_same_way(self):
        for name in ("one-page.html", "steps.html"):
            page = (STATIC / name).read_text(encoding="utf-8")
            self.assertIn("/*@V2_COMMON_JS@*/", page, name)
            self.assertIn("/*@V2_COMMON_CSS@*/", page, name)
            self.assertIn("V.start({ mount: mount, saved: saved, next: next, back: back, finished: finished, handoff: handoff, packChanged: packChanged", page, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
