"""Onboarding tests: updating a brand safely, the accounts checklist, the proof library, and the onboarding page.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands, checklist, keys                   # noqa: E402
from smf.studio import proof                              # noqa: E402
from tests.test_brands import BAKERY                      # noqa: E402


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="onboard ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class TestUpdateBrand(Case):
    def test_a_change_is_merged_and_saved(self):
        b = brands.update("maple-and-main", {"wants": ["posts", "visuals"], "voice": {"do": ["Give the number"]}})
        self.assertEqual(b.data["wants"], ["posts", "visuals"])
        again = brands.load("maple-and-main")
        self.assertEqual(again.data["voice"]["do"], ["Give the number"])
        self.assertIn("Warm", again.data["voice"]["register"])          # untouched settings survive

    def test_a_change_that_would_break_the_brand_is_refused_and_nothing_is_written(self):
        path = Path(brands.CLIENT_DIR) / "maple-and-main" / brands.MASTER
        before = path.read_text(encoding="utf-8")
        with self.assertRaises(brands.BrandError) as cm:
            brands.update("maple-and-main", {"visual": {"colors": {"accent": "orange"}}})
        self.assertIn("not saved", str(cm.exception))
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_three_new_colours_replace_the_whole_palette(self):
        brands.update("maple-and-main", {"visual": {"colors": {"ground": "#101418", "ink": "#F2F5F7", "accent": "#35C2A0"}}})
        c = brands.load("maple-and-main").colours
        self.assertEqual((c["ground"], c["accent"]), ("#101418", "#35C2A0"))
        self.assertGreater(brands.contrast(c["ground"], c["muted"]), 3.0)   # mixed from the NEW colours

    def test_the_id_cannot_be_changed_by_an_answer(self):
        b = brands.update("maple-and-main", {"id": "someone-else"})
        self.assertEqual(b.data["id"], "maple-and-main")

    def test_unknown_want_is_refused(self):
        with self.assertRaises(brands.BrandError):
            brands.update("maple-and-main", {"wants": ["world-domination"]})


class TestChecklist(Case):
    def build(self, wants, env=None):
        brands.update("maple-and-main", {"wants": wants})
        with mock.patch.dict(os.environ, env or {}, clear=True), mock.patch.object(keys, "KEYS_FILE", "/nonexistent"):
            keys.load(force=True)
            path, services = checklist.build(brands.load("maple-and-main"))
            text = Path(path).read_text(encoding="utf-8")
        return text, [s["name"] for s in services]

    def test_writing_and_visuals_need_no_account(self):
        text, services = self.build(["posts", "visuals", "short-form-scripts"])
        self.assertEqual(services, [])
        self.assertIn("None. Everything you chose works without any outside account.", text)

    def test_only_the_services_their_choices_need_and_the_cost_is_stated(self):
        text, services = self.build(["posts", "clips"])
        self.assertEqual(services, ["ElevenLabs"])
        self.assertIn("22 cents per hour", text)
        self.assertNotIn("Metricool", text)
        self.assertNotIn("Apify", text)

    def test_scheduling_names_the_paid_plan_before_they_sign_up(self):
        text, services = self.build(["scheduling"])
        self.assertEqual(services, ["Metricool"])
        self.assertIn("Advanced plan", text)
        self.assertIn("[TO DO] Metricool", text)

    def test_progress_is_shown_without_showing_a_key(self):
        text, _ = self.build(["scheduling"], env={"METRICOOL_USER_TOKEN": "zzzzzzzzzzzz"})
        self.assertIn("[PARTLY DONE] Metricool", text)
        self.assertIn("METRICOOL_USER_ID", text)
        self.assertNotIn("zzzzzzzzzzzz", text)
        text, _ = self.build(["scheduling"], env={"METRICOOL_USER_TOKEN": "zzzzzzzzzzzz", "METRICOOL_USER_ID": "42"})
        self.assertIn("[DONE] Metricool", text)

    def test_nothing_chosen_yet(self):
        text, services = self.build([])
        self.assertEqual(services, [])
        self.assertIn("need no accounts at all", text)


class TestProof(Case):
    def test_an_empty_library_is_normal_and_is_created_on_first_use(self):
        os.remove(proof.registry_path(self.brand))                # like the example brand, which ships without one
        self.assertEqual(proof.items(self.brand), [])
        self.assertTrue(os.path.isfile(proof.registry_path(self.brand)))

    def test_proof_needs_a_source(self):
        with self.assertRaises(brands.BrandError) as cm:
            proof.add(self.brand, "result", "Classes sold out", source="")
        self.assertIn("a claim, not proof", str(cm.exception))

    def test_something_that_names_a_third_party_cannot_be_published_as_is(self):
        with self.assertRaises(brands.BrandError):
            proof.add(self.brand, "testimonial", "A cafe owner's note", source="email, March", may_publish="yes",
                      names_third_party=True)
        pid = proof.add(self.brand, "testimonial", "A cafe owner's note", source="email, March",
                        may_publish="anonymised", names_third_party=True)
        self.assertEqual(pid, "PRF-0001")

    def test_a_file_is_copied_in_and_the_original_is_left_alone(self):
        outside = Path(self.tmp.name) / "downloads o'clock" / "review screenshot.png"
        outside.parent.mkdir()
        outside.write_bytes(b"pretend image")
        pid = proof.add(self.brand, "screenshot", "A review", source="our listing", file_path=str(outside),
                        may_publish="anonymised")
        self.assertTrue(outside.exists())
        row = [r for r in proof.items(self.brand) if r["proof_id"] == pid][0]
        self.assertEqual(row["file_path"], "Inputs/Proof/review screenshot.png")
        self.assertTrue(os.path.isfile(self.brand.path("Inputs", "Proof", "review screenshot.png")))

    def test_consent_rule_for_media_on_a_post(self):
        f = Path(self.brand.path("Inputs", "Proof", "private.png"))
        f.write_bytes(b"x")
        self.assertIn("no proof item", proof.media_block_reason(self.brand, "Inputs/Proof/private.png"))
        proof.add(self.brand, "screenshot", "Private numbers", source="our till", file_path=str(f), may_publish="no")
        self.assertIn("do not publish", proof.media_block_reason(self.brand, "Inputs/Proof/private.png"))
        g = Path(self.brand.path("Inputs", "Proof", "ok.png"))
        g.write_bytes(b"x")
        proof.add(self.brand, "photo", "Our loaves", source="our camera", file_path=str(g), may_publish="yes")
        self.assertIsNone(proof.media_block_reason(self.brand, "Inputs/Proof/ok.png"))
        self.assertIsNone(proof.media_block_reason(self.brand, "Output/visuals/run/1.png"))
        self.assertIn("outside this brand's folder", proof.media_block_reason(self.brand, str(Path(self.tmp.name) / "x.png")))

    def test_two_brands_libraries_are_separate(self):
        other = brands.create("stride-physio", "Stride Physio")
        proof.add(self.brand, "fact", "Eighteen hour ferment", source="production sheet")
        self.assertEqual(proof.items(other), [])


# ============================================================================= the onboarding page (card F5)
import importlib.util                                      # noqa: E402
import threading                                           # noqa: E402
import urllib.error                                        # noqa: E402
import urllib.request                                      # noqa: E402

from smf.onboarding_page import secrets_check, session as S    # noqa: E402

HAVE_FLASK = importlib.util.find_spec("flask") is not None
needs_flask = unittest.skipUnless(HAVE_FLASK, "Flask is installed by `python factory.py setup`")
FAKE_KEY = "sk-" + "ant-" + "a1B2c3D4e5F6g7H8i9J0kLmN"      # built in pieces so no key-shaped text sits in the repo
DRAFT = {"answers": {"name": {"value": "Maple & Main", "status": "confirmed"},
                     "what_you_do": {"value": "Sourdough and pastry classes in Leeds.", "status": "confirmed"},
                     "colours": {"background": "#FBF6EE", "text": "#2B2118", "accent": "#C2571A", "status": "confirmed"}}}


class PageCase(unittest.TestCase):
    """Every test gets its own Social Media Factory folder, so no session or answers file leaks between them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="page ' é ")
        self.patch = mock.patch.object(S, "ROOT", self.tmp.name)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def start(self, draft=None, port=8652):
        return S.new_session(port, S.intake_from_draft(draft))

    def finish(self, session):
        intake = S.load_intake(session)
        intake["state"] = "complete"
        intake["completed"] = __import__("time").time()
        S.write_json(session["intake"], intake)


class TestTheAnswersFile(PageCase):
    def test_a_blank_file_is_sound_and_everything_is_a_placeholder(self):
        intake = S.blank_intake()
        self.assertEqual(S.validate_intake(intake), [])
        self.assertEqual(S.placeholders(intake), list(S.BASICS))

    def test_website_drafts_always_arrive_as_please_check_whatever_the_draft_says(self):
        intake = S.intake_from_draft(DRAFT)
        for key in ("name", "what_you_do", "colours"):
            self.assertEqual(intake["answers"][key]["status"], "unconfirmed", key)
            self.assertEqual(intake["answers"][key]["source"], "draft", key)
        self.assertEqual(S.placeholders(intake), list(S.BASICS))     # a draft is a guess, not an answer

    def test_only_confirmed_answers_stop_being_placeholders(self):
        intake = S.blank_intake()
        intake["answers"]["name"] = {"value": "Maple & Main", "status": "confirmed"}
        intake["answers"]["make"] = {"value": ["posts"], "status": "skipped"}
        intake["answers"]["rules"] = {"status": "for_chat"}
        intake["answers"]["voice_samples"] = [{"text": "Proof slow.", "status": "unconfirmed"}]
        left = S.placeholders(intake)
        self.assertNotIn("name", left)
        for key in ("make", "rules", "voice_samples", "audience"):
            self.assertIn(key, left)

    def test_bad_files_are_named_in_plain_words(self):
        bad = S.blank_intake()
        bad["state"] = "done"
        bad["answers"]["name"] = {"value": "X", "status": "maybe"}
        bad["answers"]["favourite_food"] = {"status": "confirmed"}
        bad["answers"]["colours"] = {"accent": "orange", "status": "confirmed"}
        problems = " | ".join(S.validate_intake(bad))
        for words in ("state must be one of", "answers.name.status", "favourite_food", "answers.colours.accent"):
            self.assertIn(words, problems)

    def test_a_draft_with_an_answer_the_page_does_not_ask_is_refused(self):
        with self.assertRaises(S.SessionError):
            S.intake_from_draft({"answers": {"shoe_size": {"status": "confirmed"}}})

    def test_a_drafted_answer_that_looks_like_a_key_never_reaches_the_page(self):
        intake = S.intake_from_draft({"answers": {"name": {"value": FAKE_KEY}, "what_you_do": {"value": "Bread."}}})
        self.assertNotIn("name", intake["answers"])
        self.assertIn("what_you_do", intake["answers"])


class TestTheKeyCheck(unittest.TestCase):
    def test_keys_tokens_and_stated_passwords_are_caught(self):
        for text in (FAKE_KEY, "my key is " + FAKE_KEY, "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2", "AKIA" + "ABCDEFGHIJKLMNOP",
                     "Password is hunter2", "pw: s3cret!", "api key = 12345", "ASIA" + "IOSFODNN7EXAMPLE",
                     "The password for payroll is hunter2.", "API token: aB3dE5fG7hJ9kL2m",  # gitleaks:allow (a made-up value the test needs)
                     "x" * 4 + "Zq8Lp2Vr7Tn4Kw9Ms1Hd6Fb3"):
            self.assertTrue(secrets_check.looks_secret(text), text)

    def test_ordinary_answers_are_left_alone(self):
        for text in ("Maple & Main", "Our secret is an eighteen hour ferment.", "#C2571A",
                     "https://www.maple-and-main.example/classes/sourdough-for-beginners",
                     "Ava Lindqvist, Head Baker", "Never say 'cures anxiety'.", "@mapleandmain",
                     "https://example.dev/2026/CustomerRelationshipManagement", "CustomerRelationshipManagement"):
            self.assertFalse(secrets_check.looks_secret(text), text)

    def test_it_looks_inside_lists_and_groups(self):
        self.assertTrue(secrets_check.any_secret({"value": ["fine", {"deep": FAKE_KEY}]}))
        self.assertFalse(secrets_check.any_secret({"value": ["fine", {"deep": "also fine"}], "n": 3}))


class TestTheHandOff(PageCase):
    """The agent waits on the page with --wait; the page learns from the session file that it was picked up."""

    def test_wait_returns_complete_the_moment_the_person_finishes_and_records_the_pick_up(self):
        session = self.start()
        ticks = []

        def sleep(_s):
            ticks.append(1)
            if len(ticks) == 3:
                self.finish(session)

        with mock.patch.object(S, "server_answers", return_value=True):
            state, got = S.wait(limit=60, poll=0, sleep=sleep)
        self.assertEqual(state, "complete")
        self.assertEqual(len(ticks), 3)
        self.assertIsNotNone(S.load_session()["picked_up"])

    def test_wait_says_still_answering_at_its_time_limit(self):
        self.start()
        clock = iter(range(0, 10000, 100))
        with mock.patch.object(S, "server_answers", return_value=True):
            state, _ = S.wait(limit=540, poll=0, clock=lambda: next(clock), sleep=lambda s: None)
        self.assertEqual(state, "still answering")
        self.assertIsNone(S.load_session()["picked_up"])

    def test_wait_with_no_page_or_a_closed_page_says_so(self):
        self.assertEqual(S.wait(limit=1)[0], "no page")
        self.start()
        with mock.patch.object(S, "server_answers", return_value=False):
            self.assertEqual(S.wait(limit=60, sleep=lambda s: None)[0], "stopped")

    def test_status_moves_in_progress_complete_finished_and_never_shows_the_answers(self):
        self.assertEqual(S.status()["state"], "no page")
        session = self.start(DRAFT)
        with mock.patch.object(S, "server_answers", return_value=True):
            st = S.status()
            self.assertEqual(st["state"], "in progress")
            self.assertNotIn("Maple", json.dumps(st))
            self.finish(session)
            self.assertEqual(S.status()["state"], "complete")
            S.set_result({"version": 1, "ok": True, "message": "Your brand is ready."})
            self.assertEqual(S.status()["state"], "finished")
            S.request_stop()
            self.assertEqual(S.status()["state"], "stopped")

    def test_a_result_is_refused_before_the_person_finishes_or_when_it_is_malformed(self):
        session = self.start()
        with self.assertRaises(S.SessionError) as cm:
            S.set_result({"version": 1, "ok": True, "message": "Ready."})
        self.assertIn("not finished", str(cm.exception))
        self.finish(session)
        for bad in ({"ok": True, "message": "x"}, {"version": 1, "ok": "yes", "message": "x"}, ["no"],
                    {"version": 1, "ok": True, "message": "Ready " + FAKE_KEY}):
            with self.assertRaises(S.SessionError):
                S.set_result(bad)
        self.assertIsNone(S.load_session()["result"])

    def test_only_the_fields_the_page_shows_are_kept_from_a_result(self):
        session = self.start()
        self.finish(session)
        S.set_result({"version": 1, "ok": True, "message": "Ready.", "brand": "maple-and-main",
                      "steps": {"saved": True}, "traceback": "Error in line 4", "keys_file": "keys.env"})
        kept = S.load_session()["result"]
        self.assertNotIn("traceback", kept)
        self.assertNotIn("keys_file", kept)

    def test_a_new_session_replaces_the_old_one(self):
        first = self.start()
        second = self.start()
        self.assertNotEqual(first["code"], second["code"])
        self.assertEqual(S.load_session()["code"], second["code"])

    def test_the_command_reports_no_page_plainly(self):
        from smf.onboarding_page import cli
        out = __import__("io").StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(cli.cli_onboard_page(["--status"]), 0)
            self.assertEqual(cli.cli_onboard_page(["--wait", "--timeout", "1"]), 1)
        self.assertIn("no page", out.getvalue())


@needs_flask
class TestThePage(PageCase):
    def setUp(self):
        super().setUp()
        from smf.onboarding_page import server
        self.server = server
        self.session = self.start(DRAFT)
        self.code = self.session["code"]
        self.client = server.create_app(self.code).test_client()

    def url(self, path=""):
        return "/%s/%s" % (self.code, path)

    def post(self, path, data, **kw):
        return self.client.post(self.url(path), json=data, **kw)

    def test_the_page_is_locked_down_and_needs_the_private_code(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(self.client.get("/wrong-code/").status_code, 404)
        self.assertEqual(self.client.get("/wrong-code/api/session").status_code, 404)
        self.assertEqual(self.client.get("/").status_code, 404)

    def test_other_web_pages_and_odd_requests_are_turned_away(self):
        self.assertEqual(self.client.get(self.url("api/session"), headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.post("api/finish", {}, headers={"Origin": "https://evil.example"}).status_code, 403)
        r = self.client.post(self.url("api/finish"), data="via=page", content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 415)
        self.assertEqual(S.load_intake(self.session)["state"], "in_progress")

    def test_drafts_show_as_please_check_until_confirmed_then_are_saved(self):
        s = self.client.get(self.url("api/session")).get_json()
        self.assertEqual(s["answers"]["name"]["status"], "unconfirmed")
        r = self.post("api/answer", {"key": "name", "answer": {"value": "Maple & Main", "spelled": "M-A-P-L-E & M-A-I-N",
                                                                "status": "confirmed", "source": "typed",
                                                                "tapped": True, "own_words": True}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(S.load_intake(self.session)["answers"]["name"]["status"], "confirmed")
        self.assertNotIn("name", r.get_json()["placeholders"])

    def test_a_typed_key_is_thrown_away_and_never_written(self):
        before = Path(self.session["intake"]).read_text(encoding="utf-8")
        r = self.post("api/answer", {"key": "name", "answer": {"value": FAKE_KEY, "status": "confirmed"}})
        self.assertEqual(r.status_code, 422)
        self.assertIn("I've deleted it", r.get_json()["error"])
        self.assertNotIn(FAKE_KEY, json.dumps(r.get_json()))
        self.assertEqual(Path(self.session["intake"]).read_text(encoding="utf-8"), before)
        for p in Path(self.tmp.name).rglob("*"):
            if p.is_file():
                self.assertNotIn(FAKE_KEY, p.read_text(encoding="utf-8", errors="replace"), p.name)

    def test_answers_that_do_not_fit_are_refused(self):
        self.assertEqual(self.post("api/answer", {"key": "shoe_size", "answer": {"status": "confirmed"}}).status_code, 400)
        self.assertEqual(self.post("api/answer", {"key": "name", "answer": {"status": "sure"}}).status_code, 400)

    def test_a_skip_is_recorded_and_stays_a_placeholder(self):
        r = self.post("api/answer", {"key": "name", "answer": {"status": "skipped"}}).get_json()
        self.assertIn("name", r["skipped"])
        self.assertIn("name", r["placeholders"])

    def test_finish_marks_the_answers_complete_and_locks_them(self):
        r = self.post("api/finish", {"via": "page"}).get_json()
        self.assertEqual(r["state"], "complete")
        self.assertEqual(r["handoff"], "waiting")
        self.assertEqual(S.load_intake(self.session)["state"], "complete")
        late = self.post("api/answer", {"key": "name", "answer": {"value": "Other", "status": "confirmed", "tapped": True}})
        self.assertEqual(late.status_code, 409)

    def test_finish_in_chat_keeps_every_confirmed_answer(self):
        self.post("api/answer", {"key": "name", "answer": {"value": "Maple & Main", "status": "confirmed",
                                                          "tapped": True, "own_words": True}})
        r = self.post("api/finish", {"via": "chat"}).get_json()
        self.assertEqual(r["via"], "chat")
        self.assertEqual(S.load_intake(self.session)["answers"]["name"]["value"], "Maple & Main")

    def test_the_page_tells_the_truth_at_every_stage_of_the_hand_off(self):
        self.post("api/finish", {"via": "page"})
        t0 = S.load_intake(self.session)["completed"]
        with mock.patch.object(self.server.time, "time", return_value=t0 + 30):
            self.assertEqual(self.client.get(self.url("api/session")).get_json()["handoff"], "waiting")
        with mock.patch.object(self.server.time, "time", return_value=t0 + S.PICKUP_BACKSTOP + 1):
            self.assertEqual(self.client.get(self.url("api/session")).get_json()["handoff"], "backstop")
        session = S.load_session()
        session["picked_up"] = t0 + 5
        S.save_session(session)
        with mock.patch.object(self.server.time, "time", return_value=t0 + 120):
            s = self.client.get(self.url("api/session")).get_json()
            self.assertEqual(s["handoff"], "building")
            self.assertIsNone(s["result"])                         # nothing says "saved" before the result
        with mock.patch.object(self.server.time, "time", return_value=t0 + 5 + S.BUILD_TIMEOUT + 1):
            self.assertEqual(self.client.get(self.url("api/session")).get_json()["handoff"], "trouble")
        S.set_result({"version": 1, "ok": True, "message": "Your brand is ready.", "steps": {"saved": True}})
        s = self.client.get(self.url("api/session")).get_json()
        self.assertEqual(s["handoff"], "finished")
        self.assertEqual(s["result"]["message"], "Your brand is ready.")

    def test_a_replaced_session_stops_answering(self):
        self.start()
        self.assertEqual(self.client.get(self.url("api/session")).status_code, 410)

    def test_the_page_never_learns_a_file_path_or_the_code(self):
        body = json.dumps(self.client.get(self.url("api/session")).get_json())
        self.assertNotIn(self.tmp.name.replace("\\", "\\\\"), body)
        self.assertNotIn("onboarding-intake", body)
        self.assertNotIn(self.code, body)


@needs_flask
class TestTheWholeHandOffOnARealServer(PageCase):
    """Start the real server, wait on it like an agent, click Finish like a person, hand back a result, stop it."""

    def call(self, url, data=None):
        req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_finish_to_brand_ready_with_nothing_typed_in_the_chat(self):
        from smf.onboarding_page import server
        out = __import__("io").StringIO()
        with mock.patch("sys.stdout", out):
            runner = threading.Thread(target=server.serve, kwargs={"draft": DRAFT, "open_browser": False}, daemon=True)
            runner.start()
            for _ in range(100):
                session = S.load_session()
                if session and S.server_answers(session):
                    break
                __import__("time").sleep(0.05)
            self.assertIsNotNone(session, "the page never started")
            self.assertTrue(session["url"].startswith("http://127.0.0.1:"))

            waited = {}
            agent = threading.Thread(target=lambda: waited.update(state=S.wait(limit=20, poll=0.05)[0]), daemon=True)
            agent.start()
            self.call(session["url"] + "api/answer", {"key": "name", "answer": {"value": "Maple & Main", "status": "confirmed",
                                                                                 "tapped": True, "own_words": True}})
            self.call(session["url"] + "api/finish", {"via": "page"})
            agent.join(10)
            self.assertEqual(waited.get("state"), "complete")
            self.assertEqual(self.call(session["url"] + "api/session")["handoff"], "building")

            S.set_result({"version": 1, "ok": True, "message": "Your brand is ready."})
            self.assertEqual(self.call(session["url"] + "api/session")["result"]["message"], "Your brand is ready.")

            S.request_stop()
            runner.join(10)
        self.assertFalse(runner.is_alive(), "the page did not stop when asked")
        self.assertEqual(S.status()["state"], "stopped")
        self.assertIn("The onboarding page is open at http://127.0.0.1:", out.getvalue())


class TestTheEightQuestions(PageCase):
    """Step F5.2: the page asks exactly the skill's eight, in its order, and holds the line on taps and examples."""

    def test_the_page_asks_the_skills_eight_in_the_skills_order(self):
        keys = [q["key"] for q in S.questions()]
        self.assertEqual(keys, list(S.BASICS))
        # Since #43 the chat asks the v2 page's 31 (fields.json), not the classic page's eight.
        skill = (ROOT / ".claude" / "skills" / "onboard-brand" / "SKILL.md").read_text(encoding="utf-8")
        step1 = skill.split("## Step 1", 1)[1].split("## Step 2", 1)[0]
        self.assertIn("smf/onboarding_page/fields.json", step1)

    def test_what_to_make_offers_exactly_what_a_brand_can_want(self):
        schema = json.loads((ROOT / "smf" / "brand.schema.json").read_text(encoding="utf-8"))
        wants = schema["properties"]["wants"]["items"]["enum"]
        make = next(q for q in S.questions() if q["key"] == "make")
        self.assertEqual([c["id"] for c in make["choices"]], wants)

    def test_names_and_rules_cannot_be_confirmed_without_a_tap(self):
        for key, answer in (("name", {"value": "Stride Physio", "status": "confirmed"}),
                            ("identities", [{"kind": "person", "name": "Ava", "status": "confirmed"}]),
                            ("rules", {"industry": "none", "never_name": ["Acme"], "status": "confirmed"})):
            self.assertTrue(S.confirmed_without_tap(key, answer), key)
            tapped = [dict(a, tapped=True) for a in answer] if isinstance(answer, list) else dict(answer, tapped=True)
            self.assertFalse(S.confirmed_without_tap(key, tapped), key)
        self.assertFalse(S.confirmed_without_tap("what_you_do", {"value": "Physio", "status": "confirmed"}))
        self.assertFalse(S.confirmed_without_tap("name", {"value": "Draft", "status": "unconfirmed"}))

    def test_an_answer_that_reads_like_the_example_is_questioned(self):
        example = next(q for q in S.questions() if q["key"] == "what_you_do")["example_text"]
        copied = {"value": example, "status": "confirmed", "source": "typed"}
        self.assertTrue(S.reads_like_example("what_you_do", copied))
        self.assertTrue(S.reads_like_example("what_you_do", dict(copied, value=example.replace("small", "little"))))
        self.assertFalse(S.reads_like_example("what_you_do", dict(copied, own_words=True)))
        self.assertFalse(S.reads_like_example("what_you_do", dict(copied, source="draft")))
        self.assertFalse(S.reads_like_example("what_you_do", {"value": "Physiotherapy for runners in Bristol.",
                                                              "status": "confirmed", "source": "typed"}))

    def test_no_example_is_ever_written_into_the_page_itself(self):
        page = (ROOT / "smf" / "onboarding_page" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("example_text", page)
        for q in S.questions():
            if q.get("example_text"):
                self.assertNotIn(q["example_text"], page)

    def test_the_page_draws_every_question_and_loads_nothing_from_elsewhere(self):
        page = (ROOT / "smf" / "onboarding_page" / "static" / "index.html").read_text(encoding="utf-8")
        for key in S.BASICS:
            self.assertIn("RENDER.%s = function" % key, page)
        self.assertNotRegex(page, r"""(src|href)=["']?https?:""")
        self.assertNotIn("fonts.googleapis", page)
        for words in ("Brand basics", "Skipped one? Fill it in", "Finish in chat", "Read the guide first"):
            self.assertIn(words, page)


@needs_flask
class TestThePageHoldsTheLine(PageCase):
    def setUp(self):
        super().setUp()
        from smf.onboarding_page import server
        self.session = self.start()
        self.code = self.session["code"]
        self.client = server.create_app(self.code).test_client()

    def post(self, key, answer):
        return self.client.post("/%s/api/answer" % self.code, json={"key": key, "answer": answer})

    def test_the_questions_are_served_to_the_page(self):
        r = self.client.get("/%s/api/questions" % self.code).get_json()
        self.assertEqual([q["key"] for q in r["questions"]], list(S.BASICS))

    def test_an_untapped_name_or_rule_is_refused_and_nothing_is_written(self):
        before = Path(self.session["intake"]).read_text(encoding="utf-8")
        r = self.post("rules", {"industry": "health", "never_claim": ["cures anxiety"], "status": "confirmed"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("tap", r.get_json()["error"])
        r = self.post("identities", [{"kind": "person", "name": "Ava Lindqvist", "status": "confirmed"}])
        self.assertEqual(r.status_code, 422)
        self.assertEqual(Path(self.session["intake"]).read_text(encoding="utf-8"), before)

    def test_a_copied_example_needs_the_person_to_say_it_is_theirs(self):
        example = next(q for q in S.questions() if q["key"] == "what_you_do")["example_text"]
        r = self.post("what_you_do", {"value": example, "status": "confirmed", "source": "typed"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("example", r.get_json()["error"])
        self.assertNotIn("what_you_do", S.load_intake(self.session)["answers"])
        r = self.post("what_you_do", {"value": example, "status": "confirmed", "source": "typed", "own_words": True})
        self.assertEqual(r.status_code, 200)

    def test_skipping_a_list_answer_is_recorded_as_a_skip(self):
        r = self.post("voice_samples", []).get_json()
        self.assertIn("voice_samples", r["skipped"])
        self.assertIn("voice_samples", r["placeholders"])

    def test_all_eight_answered_leave_no_placeholders(self):
        answers = {
            "name": {"value": "Stride Physio", "spelled": "S-T-R-I-D-E  P-H-Y-S-I-O", "status": "confirmed",
                     "tapped": True, "source": "typed"},
            "what_you_do": {"value": "Physiotherapy for runners in Bristol.", "status": "confirmed", "source": "typed"},
            "audience": {"value": "Club runners with nagging knee pain.", "questions": ["Should I run through it?"],
                         "status": "confirmed", "source": "typed"},
            "identities": [{"kind": "company", "name": "Stride Physio", "spelled": "S-T-R-I-D-E", "status": "confirmed",
                            "tapped": True}],
            "voice_samples": [{"text": "Rest is training too.", "source": "pasted", "verbatim": True, "status": "confirmed"}],
            "colours": {"background": "#FFFFFF", "text": "#102030", "accent": "#0A7C66", "status": "confirmed"},
            "rules": {"industry": "health", "never_claim": ["cures"], "sign_off": ["Lead physio"], "never_name": [],
                      "hated_words": ["hack"], "status": "confirmed", "tapped": True},
            "make": {"value": ["posts", "visuals"], "status": "confirmed"},
        }
        for key, answer in answers.items():
            r = self.post(key, answer)
            self.assertEqual(r.status_code, 200, "%s: %s" % (key, r.get_json()))
        self.assertEqual(r.get_json()["placeholders"], [])
        self.assertEqual(S.validate_intake(S.load_intake(self.session)), [])

    def test_a_make_choice_the_factory_does_not_offer_is_refused(self):
        self.assertEqual(self.post("make", {"value": ["podcasts"], "status": "confirmed"}).status_code, 400)
        self.assertEqual(self.post("make", {"value": [], "other": "Podcasts", "status": "confirmed"}).status_code, 200)


# ----------------------------------------------------------------------------- step F5.3: the ending
FULL = {
    "name": {"value": "Stride Physio", "spelled": "S-T-R-I-D-E  P-H-Y-S-I-O", "status": "confirmed", "tapped": True, "source": "typed"},
    "what_you_do": {"value": "Physiotherapy for runners in Bristol.", "status": "confirmed", "source": "typed"},
    "audience": {"value": "Club runners with nagging knee pain.", "questions": ["Should I run through it?", "Do I need new shoes?"],
                 "status": "confirmed", "source": "typed"},
    "identities": [{"kind": "person", "name": "Sam Okafor", "spelled": "S-A-M", "role": "Lead physio", "video_line": "Sam Okafor, Lead Physio",
                    "status": "confirmed", "tapped": True},
                   {"kind": "company", "name": "Stride Physio", "spelled": "S-T-R-I-D-E", "handle": "@stridephysio.example",
                    "status": "confirmed", "tapped": True}],
    "voice_samples": [{"text": "rest is training too. honestly.", "source": "pasted", "verbatim": True, "status": "confirmed"},
                      {"text": "Ice? Mostly a comfort, not a cure.", "source": "typed", "verbatim": True, "status": "confirmed"}],
    "colours": {"background": "#FFFFFF", "text": "#102030", "accent": "#0A7C66", "status": "confirmed"},
    "rules": {"industry": "health", "never_claim": ["cures arthritis"], "sign_off": ["Any injury advice: Sam Okafor"],
              "never_name": ["Bristol Harriers"], "hated_words": ["hack"], "status": "confirmed", "tapped": True},
    "make": {"value": ["posts", "visuals", "scheduling"], "status": "confirmed"},
}


class BrandCase(PageCase):
    """A page session plus a private Client folder, so brands can really be built."""

    def setUp(self):
        super().setUp()
        self.brand_patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                              mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.brand_patches:
            p.start()

    def tearDown(self):
        for p in self.brand_patches:
            p.stop()
        super().tearDown()

    def intake(self, answers=None):
        intake = S.blank_intake()
        intake["answers"] = json.loads(json.dumps(answers if answers is not None else FULL))
        intake["state"] = "complete"
        return intake

    def build_brand(self, answers=None):
        from smf.onboarding_page import to_brand
        name, ans, notes, voice = to_brand.build(self.intake(answers))
        b = brands.create(brands.slugify(name or "unnamed brand"), name or "Unnamed brand", ans)
        if voice:
            Path(b.path("Brand", "voice-samples.md")).write_text(voice, encoding="utf-8")
        return b, notes


class TestFromThePageToABrand(BrandCase):
    def test_a_page_onboarding_builds_a_brand_that_passes_the_brand_check(self):
        b, _notes = self.build_brand()
        problems, _warnings = brands.validate(brands.load(b.id).data)
        self.assertEqual(problems, [])
        d = brands.load(b.id).data
        self.assertEqual(d["business"]["what_we_do"], "Physiotherapy for runners in Bristol.")
        self.assertEqual(d["audience"]["questions_they_ask"], ["Should I run through it?", "Do I need new shoes?"])
        self.assertEqual([i["display_name"] for i in d["identities"]], ["Sam Okafor", "Stride Physio"])
        self.assertEqual(d["identities"][0]["credential_line"], "Sam Okafor, Lead Physio")
        self.assertEqual(d["visual"]["colors"]["accent"], "#0A7C66")
        self.assertEqual(d["compliance"]["pack"], "health")
        self.assertEqual(d["compliance"]["drop_terms"], ["cures arthritis"])
        self.assertEqual(d["never_mention"], ["Bristol Harriers"])
        self.assertEqual(d["style"]["banned_words"], ["hack"])
        self.assertEqual(d["wants"], ["posts", "visuals", "scheduling"])

    def test_it_matches_the_brand_the_chat_makes_from_the_same_answers(self):
        page_brand, _ = self.build_brand()
        chat_answers = {
            "business": {"what_we_do": "Physiotherapy for runners in Bristol.", "regulated": "health"},
            "audience": {"who": "Club runners with nagging knee pain.",
                         "questions_they_ask": ["Should I run through it?", "Do I need new shoes?"]},
            "identities": [{"id": "person", "kind": "person", "display_name": "Sam Okafor", "role": "Lead physio",
                            "credential_line": "Sam Okafor, Lead Physio"},
                           {"id": "company", "kind": "company", "display_name": "Stride Physio", "handle": "@stridephysio.example"}],
            "visual": {"wordmark": "Stride Physio", "handle": "stridephysio.example",
                       "colors": {"ground": "#FFFFFF", "ink": "#102030", "accent": "#0A7C66"}},
            "own_brands": ["Stride Physio", "Sam Okafor"],
            "compliance": {"pack": "health", "drop_terms": ["cures arthritis"]},
            "never_mention": ["Bristol Harriers"], "style": {"banned_words": ["hack"]},
            "wants": ["posts", "visuals", "scheduling"],
        }
        chat_brand = brands.create("stride-physio-chat", "Stride Physio", chat_answers)
        a, b = dict(brands.load(page_brand.id).data), dict(brands.load(chat_brand.id).data)
        a.pop("id"), b.pop("id")
        self.assertEqual(a, b)

    def test_unconfirmed_and_skipped_answers_stay_placeholders_never_guesses(self):
        answers = json.loads(json.dumps(FULL))
        answers["what_you_do"]["status"] = "unconfirmed"            # a website draft nobody confirmed
        answers["audience"] = {"status": "skipped"}
        answers["colours"]["status"] = "for_chat"
        b, notes = self.build_brand(answers)
        d = brands.load(b.id).data
        self.assertIn("TODO", d["business"]["what_we_do"])
        self.assertIn("TODO", d["audience"]["who"])
        self.assertEqual(d["visual"]["colors"]["ground"], "#FFFFFF")            # the blank brand's, not a guess
        self.assertTrue(any("colours" in n for n in notes))

    def test_voice_samples_are_kept_word_for_word_with_where_they_came_from(self):
        b, _ = self.build_brand()
        text = Path(b.path("Brand", "voice-samples.md")).read_text(encoding="utf-8")
        self.assertIn("rest is training too. honestly.", text)
        self.assertIn("Ice? Mostly a comfort, not a cure.", text)
        self.assertIn("pasted on the onboarding page", text)
        self.assertIn("typed on the onboarding page", text)

    def test_what_the_settings_cannot_hold_comes_back_to_settle_in_the_chat(self):
        _b, notes = self.build_brand()
        self.assertTrue(any("Sam Okafor" in n and "sign" in n.lower() for n in notes))


class TestAnUpdateCanClearWhatWasSaid(BrandCase):
    """Updating a brand from the page merges the answers in. A list the person emptied on the page
    must reach the brand as empty, or the old never-name, banned-word and never-claim rules stay."""

    def update_from_page(self, answers):
        from smf.onboarding_page import to_brand
        _name, ans, _notes, _voice = to_brand.build(self.intake(answers))
        brands.update(self.brand.id, ans)
        return brands.load(self.brand.id).data             # reloaded from disk, not the copy in memory

    def setUp(self):
        super().setUp()
        self.brand, _ = self.build_brand()
        self.brand.data["style"]["tone_words"] = ["warm"]   # an unrelated setting the update must not touch
        brands.update(self.brand.id, {"style": {"tone_words": ["warm"]}})

    def page(self, **rules):
        answers = json.loads(json.dumps(FULL))
        answers["rules"].update(rules)
        return answers

    def test_emptied_lists_clear_the_old_rules(self):
        d = self.update_from_page(self.page(never_name=[], hated_words=[], never_claim=[]))
        self.assertEqual(d["never_mention"], [])
        self.assertEqual(d["style"]["banned_words"], [])
        self.assertEqual(d["compliance"]["drop_terms"], [])
        self.assertEqual(d["style"]["tone_words"], ["warm"])
        self.assertEqual(d["compliance"]["pack"], "health")

    def test_lists_the_answer_leaves_out_are_kept(self):
        answers = self.page()
        for key in ("never_name", "hated_words", "never_claim"):
            del answers["rules"][key]
        d = self.update_from_page(answers)
        self.assertEqual(d["never_mention"], ["Bristol Harriers"])
        self.assertEqual(d["style"]["banned_words"], ["hack"])
        self.assertEqual(d["compliance"]["drop_terms"], ["cures arthritis"])

    def test_rules_not_confirmed_change_nothing(self):
        for status in ("skipped", "for_chat", "unconfirmed"):
            d = self.update_from_page(self.page(never_name=[], hated_words=[], never_claim=[], status=status))
            self.assertEqual(d["never_mention"], ["Bristol Harriers"], status)
            self.assertEqual(d["style"]["banned_words"], ["hack"], status)
            self.assertEqual(d["compliance"]["drop_terms"], ["cures arthritis"], status)

    def test_clearing_the_company_handle_clears_it_on_the_pictures(self):
        self.assertEqual(brands.load(self.brand.id).data["visual"]["handle"], "stridephysio.example")
        answers = json.loads(json.dumps(FULL))
        answers["identities"][1]["handle"] = ""
        self.assertEqual(self.update_from_page(answers)["visual"]["handle"], "")

    def test_confirming_only_a_person_leaves_the_picture_handle_alone(self):
        answers = json.loads(json.dumps(FULL))
        answers["identities"] = [answers["identities"][0]]                  # the person only
        self.assertEqual(self.update_from_page(answers)["visual"]["handle"], "stridephysio.example")
        answers = json.loads(json.dumps(FULL))
        answers["identities"][1]["status"] = "for_chat"                     # the company handed to the chat
        self.assertEqual(self.update_from_page(answers)["visual"]["handle"], "stridephysio.example")

    def test_a_new_brand_with_empty_lists_passes_the_brand_check(self):
        answers = self.page(never_name=[], hated_words=[], never_claim=[])
        answers["name"]["value"] = "Stride Physio Two"
        b, _ = self.build_brand(answers)
        self.assertEqual(brands.validate(brands.load(b.id).data)[0], [])


class TestTheOnePageSummary(BrandCase):
    def test_it_has_every_field_in_order_and_marks_the_rules_private(self):
        from smf.onboarding_page import summary
        b, _ = self.build_brand()
        html_text = Path(summary.build(b.id, placeholders=["voice_samples"], when="7 October 2026")).read_text(encoding="utf-8")
        order = ["Stride Physio", "Set up 7 October 2026", "What you do", "Who you reach", "Should I run through it?",
                 "Who speaks", "Sam Okafor", "How you sound", "rest is training too. honestly.", "Colours",
                 "Rules", "Private: don't share this page", "cures arthritis", "Bristol Harriers", "hack",
                 "What you chose to make", "Still open", "voice samples (skipped or not confirmed on the page)",
                 "Next steps", "Write my first post", "Metricool"]
        at = -1
        for words in order:
            here = html_text.find(words, at + 1)
            self.assertGreater(here, at, "missing or out of order: %s" % words)
            at = here
        self.assertNotIn("http://", html_text.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", html_text)

    def test_it_never_holds_a_key(self):
        from smf.onboarding_page import summary
        b, _ = self.build_brand()
        Path(b.path("Brand", "voice-samples.md")).write_text(
            "# Voice samples\n\n## Sample 1 (pasted on the onboarding page)\n\n" + FAKE_KEY + "\n", encoding="utf-8")
        page = Path(summary.build(b.id)).read_text(encoding="utf-8")
        self.assertNotIn(FAKE_KEY, page)

    def test_colours_get_plain_names(self):
        from smf.onboarding_page import summary
        self.assertEqual(summary.colour_name("#FBF7F0"), "Cream")
        self.assertEqual(summary.colour_name("#2B1D14"), "Dark brown")
        self.assertEqual(summary.colour_name("#C2571A"), "Orange")
        self.assertEqual(summary.colour_name("#FFFFFF"), "White")


@needs_flask
class TestTheEnding(BrandCase):
    def setUp(self):
        super().setUp()
        from smf.onboarding_page import server
        self.server = server
        self.session = self.start()
        self.code = self.session["code"]
        self.client = server.create_app(self.code).test_client()
        self.brand, _ = self.build_brand()
        self.other = brands.create("someone-else", "Someone Else")

    def url(self, path):
        return "/%s/%s" % (self.code, path)

    def built(self, **extra):
        self.finish(self.session)
        result = {"version": 1, "ok": True, "brand": self.brand.id, "message": "Your brand is ready.",
                  "steps": {"saved": True, "checked": True, "sample": True}}
        result.update(extra)
        S.set_result(result)

    def test_open_my_brand_folder_opens_only_this_sessions_brand(self):
        with mock.patch.object(self.server, "open_folder", return_value=True) as opener:
            self.assertEqual(self.client.post(self.url("api/open-folder"), json={}).status_code, 409)   # not built yet
            self.built()
            r = self.client.post(self.url("api/open-folder"), json={"path": self.other.home, "brand": "someone-else"})
            self.assertEqual(r.status_code, 200)
            opener.assert_called_once_with(os.path.realpath(self.brand.home))
            self.assertEqual(self.client.post("/wrong-code/api/open-folder", json={}).status_code, 404)
            self.assertEqual(self.client.post(self.url("api/open-folder"), json={},
                                              headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(opener.call_count, 1)

    def test_when_the_folder_cannot_open_the_page_says_where_it_is_in_plain_words(self):
        self.built()
        with mock.patch.object(self.server, "open_folder", return_value=False):
            r = self.client.post(self.url("api/open-folder"), json={}).get_json()
        self.assertFalse(r["opened"])
        self.assertTrue(r["where"].endswith("Client › Stride Physio"))
        self.assertNotIn(self.tmp.name, r["where"])

    def test_the_sample_picture_is_served_only_from_inside_the_brand(self):
        pic = Path(self.brand.path("Output", "demo-01.png"))
        pic.parent.mkdir(parents=True, exist_ok=True)
        pic.write_bytes(b"\x89PNG\r\n\x1a\n")
        rel = os.path.relpath(str(pic), self.tmp.name)
        self.built(demo_image=rel)
        r = self.client.get(self.url("sample"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "image/png")
        session = S.load_session()
        for bad in (os.path.join("..", "outside.png"), os.path.relpath(self.other.path("x.png"), self.tmp.name), "keys.env"):
            session["result"]["demo_image"] = bad
            S.save_session(session)
            self.assertEqual(self.client.get(self.url("sample")).status_code, 404, bad)

    def test_the_summary_is_served_once_it_exists(self):
        from smf.onboarding_page import summary
        self.built(summary="x")
        self.assertEqual(self.client.get(self.url("summary")).status_code, 404)
        summary.build(self.brand.id)
        r = self.client.get(self.url("summary"))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Stride Physio", r.data)

    def test_the_last_tap_is_handed_to_the_agent_by_wait(self):
        self.built()
        with mock.patch.object(S, "server_answers", return_value=True):
            state, _ = S.wait(limit=0, poll=0, sleep=lambda s: None)
            self.assertEqual(state, "still looking")
            self.assertEqual(self.client.post(self.url("api/closing"), json={"choice": "first-post"}).status_code, 200)
            self.assertEqual(S.wait(limit=5, poll=0, sleep=lambda s: None)[0], "first-post")
        self.assertEqual(self.client.post(self.url("api/closing"), json={"choice": "publish"}).status_code, 400)

    def test_the_closing_question_is_saved_on_this_computer_and_refuses_a_key(self):
        self.built()
        r = self.client.post(self.url("api/reflection"), json={"question": "What surprised you?", "answer": "How fast it was."})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(S.load_intake(self.session)["reflection"]["answer"], "How fast it was.")
        r = self.client.post(self.url("api/reflection"), json={"question": "What surprised you?", "answer": FAKE_KEY})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn(FAKE_KEY, Path(self.session["intake"]).read_text(encoding="utf-8"))
        self.assertEqual(self.client.post(self.url("api/reflection"), json={"question": "Tell me your password",
                                                                            "answer": "x"}).status_code, 400)

    def test_nothing_says_saved_to_your_brand_before_a_successful_result(self):
        self.finish(self.session)
        s = self.client.get(self.url("api/session")).get_json()
        self.assertIsNone(s["result"])
        page = (ROOT / "smf" / "onboarding_page" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("s.result.ok && S.result.steps && S.result.steps.saved".replace("s.result", "S.result"), page)


class TestTheCommandBuildsTheBrandAnswers(BrandCase):
    def test_brand_answers_and_voice_samples_are_written_and_placeholders_named(self):
        from smf.onboarding_page import cli
        session = self.start()
        answers = json.loads(json.dumps(FULL))
        answers["audience"] = {"status": "skipped"}
        intake = self.intake(answers)
        S.write_json(session["intake"], intake)
        out = Path(self.tmp.name) / "brand-answers.json"
        buf = __import__("io").StringIO()
        with mock.patch("sys.stdout", buf):
            self.assertEqual(cli.cli_onboard_page(["--brand-answers", str(out)]), 0)
        printed = buf.getvalue()
        self.assertIn("Name: Stride Physio", printed)
        self.assertIn("Placeholders (not confirmed; never fill them in yourself): audience", printed)
        self.assertNotIn("audience", json.loads(out.read_text(encoding="utf-8")))
        self.assertIn("rest is training too.", (Path(self.tmp.name) / "brand-answers-voice-samples.md").read_text(encoding="utf-8"))


# ============================================================================= talking instead of typing (card F6)
from smf.onboarding_page import voice as V          # noqa: E402

FAKE_AUDIO = b"\x1aE\xdf\xa3" + b"\x00" * 2048       # a webm header and silence; never a real recording


class FakeElevenLabs:
    """Stands in for ElevenLabs speech-to-text: records what it was sent and answers with set words."""

    def __init__(self, text="Sourdough classes for home bakers in Leeds.", status=200):
        self.text, self.status, self.calls = text, status, []

    def __call__(self, audio, mime, api_key):
        self.calls.append({"bytes": len(audio), "mime": mime, "key_given": bool(api_key)})
        fake = self

        class R:
            status_code = fake.status

            def json(self):
                return {"text": fake.text}
        return R()


class VoiceCase(PageCase):
    def setUp(self):
        super().setUp()
        self.key = mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "el_" + "test" * 8})
        self.key.start()
        self.loaded = mock.patch.object(V.keys, "load", return_value={})
        self.loaded.start()

    def tearDown(self):
        self.loaded.stop()
        self.key.stop()
        super().tearDown()


class TestListening(VoiceCase):
    def test_words_come_back_from_the_service_in_memory(self):
        fake = FakeElevenLabs("We bake sourdough.  (laughs) ")
        self.assertEqual(V.transcribe_bytes(FAKE_AUDIO, "audio/webm;codecs=opus", post=fake), "We bake sourdough.")
        self.assertEqual(fake.calls[0]["mime"], "audio/webm")
        self.assertTrue(fake.calls[0]["key_given"])

    def test_no_key_means_type_instead_and_nothing_is_sent(self):
        fake = FakeElevenLabs()
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}):
            self.assertFalse(V.available())
            with self.assertRaises(V.VoiceError) as cm:
                V.transcribe_bytes(FAKE_AUDIO, "audio/webm", post=fake)
        self.assertIn("type instead", str(cm.exception))
        self.assertEqual(fake.calls, [])

    def test_service_errors_become_one_plain_sentence(self):
        for status in (401, 500):
            with self.assertRaises(V.VoiceError) as cm:
                V.transcribe_bytes(FAKE_AUDIO, "audio/webm", post=FakeElevenLabs(status=status))
            self.assertNotIn("Traceback", str(cm.exception))
        with self.assertRaises(V.VoiceError):
            V.transcribe_bytes(FAKE_AUDIO, "text/plain", post=FakeElevenLabs())
        with self.assertRaises(V.VoiceError):
            V.transcribe_bytes(b"", "audio/webm", post=FakeElevenLabs())

    def test_no_audio_is_ever_written_to_disk(self):
        # Every way Python makes a file is blocked while transcribing (the system temp folder is
        # covered by these guards, not by scanning it: other programs write there all the time),
        # and the Social Media Factory's own folder is compared before and after.
        before = {p for p in Path(self.tmp.name).rglob("*") if p.is_file()}
        real_open = open

        def guarded_open(file, mode="r", *a, **k):
            if any(c in mode for c in "wax+"):
                raise AssertionError("something tried to write a file during transcription: %s" % file)
            return real_open(file, mode, *a, **k)
        no_temp = AssertionError("something tried to make a temporary file during transcription")
        with mock.patch("builtins.open", guarded_open), \
                mock.patch.object(tempfile, "mkstemp", side_effect=no_temp), \
                mock.patch.object(tempfile, "NamedTemporaryFile", side_effect=no_temp), \
                mock.patch.object(tempfile, "TemporaryFile", side_effect=no_temp), \
                mock.patch.object(tempfile, "SpooledTemporaryFile", side_effect=no_temp), \
                mock.patch.object(os, "open", side_effect=no_temp):
            V.transcribe_bytes(FAKE_AUDIO, "audio/webm", post=FakeElevenLabs())
        after = {p for p in Path(self.tmp.name).rglob("*") if p.is_file()}
        self.assertEqual(after - before, set())

    def test_the_voice_helper_reuses_videos_settings_without_editing_them(self):
        from smf.video import transcribe
        self.assertEqual((V.ENDPOINT, V.MODEL, V.KEY_NAME), (transcribe.ENDPOINT, transcribe.MODEL, transcribe.KEY_NAME))
        self.assertLess(V.cost_estimate(15 * 60), 0.10)          # a long onboarding stays under ten cents


class TestUnderstanding(unittest.TestCase):
    def test_every_spoken_command_is_recognised(self):
        for said, cmd in (("Go back.", "back"), ("skip", "skip"), ("I'm not sure", "skip"), ("Hang on", "pause"),
                          ("give me a second", "pause"), ("type instead", "type"), ("Undo that", "undo"),
                          ("don't save that", "undo"), ("delete my last answer", "undo"),
                          ("repeat the question", "repeat"), ("ask me that differently", "repeat"),
                          ("explain that", "explain"), ("Can you give me an example?", "explain"),
                          ("start over", "start_over"), ("finish in chat", "finish_chat"), ("continue", "continue")):
            self.assertEqual(V.understand(said), {"kind": "command", "command": cmd}, said)

    def test_yes_try_again_and_save_them_are_spoken_commands(self):
        for said, cmd in (("yes", "confirm"), ("Yes, that's right.", "confirm"), ("use that", "confirm"),
                          ("try again", "retry"), ("No.", "retry"), ("save them", "save"), ("That's all", "save")):
            self.assertEqual(V.understand(said, "what_you_do"), {"kind": "command", "command": cmd}, said)
        self.assertEqual(V.understand("No, that's wrong", "what_you_do")["kind"], "for_chat")

    def test_the_page_never_records_over_novas_voice(self):
        page = (ROOT / "smf" / "onboarding_page" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function hush()", page)                        # Nova is silenced before recording
        self.assertIn('if (recState === "recording") { return; }', page)   # and never speaks over the microphone
        self.assertIn("echoCancellation: true", page)
        self.assertIn("You can say:", page)

    def test_off_script_speech_goes_to_the_chat_never_into_an_answer(self):
        for said in ("What did I say before?", "I don't understand the question", "I have two businesses",
                     "I changed my mind", "No, that's wrong", "Why do you need this?", "go back two questions?"):
            self.assertEqual(V.understand(said)["kind"], "for_chat", said)

    def test_a_long_answer_that_contains_a_command_word_is_still_an_answer(self):
        r = V.understand("I'd like to go back to basics: we bake bread and teach people to skip the shortcuts")
        self.assertEqual(r["kind"], "answer")

    def test_a_spoken_key_is_thrown_away_and_says_replace_it(self):
        r = V.understand("my api key is " + FAKE_KEY)
        self.assertEqual(r["kind"], "secret")
        self.assertIn("replace that key", r["message"])
        self.assertNotIn(FAKE_KEY, json.dumps(r))

    def test_customers_questions_said_aloud_are_answers_on_who_you_reach(self):
        said = "Should I run through the pain?"
        self.assertEqual(V.understand(said, "audience")["kind"], "answer")
        self.assertEqual(V.understand(said, "name")["kind"], "for_chat")
        self.assertEqual(V.understand("I don't understand the question", "audience")["kind"], "for_chat")

    def test_a_long_answer_in_another_alphabet_is_never_a_command(self):
        said = "skip " + " ".join(["хлеб"] * 12)
        self.assertEqual(V.understand(said, "what_you_do")["kind"], "answer")

    def test_talking_to_the_assistant_goes_to_the_chat(self):
        for said in ("Tell me a joke", "Hey Nova, are you there", "Who are you"):
            self.assertEqual(V.understand(said, "what_you_do")["kind"], "for_chat", said)

    def test_a_hated_words_answer_that_quotes_the_phrases_is_an_answer(self):
        self.assertEqual(V.understand('We hate "artisanal" and "mouthwatering"')["kind"], "answer")


@needs_flask
class TestThePageListens(VoiceCase):
    def setUp(self):
        super().setUp()
        from smf.onboarding_page import server
        self.session = self.start()
        self.code = self.session["code"]
        self.app = server.create_app(self.code)
        self.fake = FakeElevenLabs("Sourdough classes for home bakers in Leeds.")
        self.app.config["VOICE_POST"] = self.fake
        self.client = self.app.test_client()

    def url(self, path):
        return "/%s/%s" % (self.code, path)

    def listen(self, audio=FAKE_AUDIO, kind="audio/webm", q="what_you_do"):
        return self.client.post(self.url("api/listen?q=" + q), data=audio, content_type=kind)

    def test_another_local_page_on_a_different_port_is_turned_away(self):
        self.client.post(self.url("api/consent"), json={"recording": True},
                         headers={"Host": "127.0.0.1:8652", "Origin": "http://127.0.0.1:8652"})
        r = self.client.post(self.url("api/listen"), data=FAKE_AUDIO, content_type="audio/webm",
                             headers={"Host": "127.0.0.1:8652", "Origin": "http://127.0.0.1:9999"})
        self.assertEqual(r.status_code, 403)
        ok = self.client.post(self.url("api/consent"), json={"recording": True},
                              headers={"Host": "127.0.0.1:8652", "Origin": "http://127.0.0.1:8652"})
        self.assertEqual(ok.status_code, 200)

    def test_nothing_is_heard_before_consent(self):
        r = self.listen()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.fake.calls, [])

    def test_after_consent_the_words_come_back_to_check_and_nothing_is_saved(self):
        self.assertEqual(self.client.post(self.url("api/consent"), json={"recording": True}).status_code, 200)
        self.assertTrue(S.load_intake(self.session)["consent"]["recording"])
        r = self.listen().get_json()
        self.assertEqual(r, {"kind": "answer", "text": "Sourdough classes for home bakers in Leeds."})
        self.assertNotIn("what_you_do", S.load_intake(self.session)["answers"])      # speech never saves

    def test_only_audio_is_accepted_and_other_pages_are_turned_away(self):
        self.client.post(self.url("api/consent"), json={"recording": True})
        self.assertEqual(self.listen(kind="text/plain").status_code, 415)
        r = self.client.post(self.url("api/listen"), data=FAKE_AUDIO, content_type="audio/webm",
                             headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post("/wrong/api/listen", data=FAKE_AUDIO, content_type="audio/webm").status_code, 404)

    def test_a_spoken_key_never_reaches_any_file(self):
        self.client.post(self.url("api/consent"), json={"recording": True})
        self.fake.text = "the password is " + FAKE_KEY
        r = self.listen().get_json()
        self.assertEqual(r["kind"], "secret")
        for p in Path(self.tmp.name).rglob("*"):
            if p.is_file():
                self.assertNotIn(FAKE_KEY, p.read_text(encoding="utf-8", errors="replace"))

    def test_a_failed_transcription_says_try_again_or_type(self):
        self.client.post(self.url("api/consent"), json={"recording": True})
        self.fake.status = 500
        r = self.listen()
        self.assertEqual(r.status_code, 422)
        self.assertIn("type it", r.get_json()["error"])

    def test_the_microphone_check_is_reported_by_status(self):
        self.assertEqual(self.client.post(self.url("api/microphone"), json={"state": "denied"}).status_code, 200)
        with mock.patch.object(S, "server_answers", return_value=True):
            self.assertEqual(S.status()["microphone"], "denied")
        self.assertEqual(self.client.post(self.url("api/microphone"), json={"state": "on fire"}).status_code, 400)

    def test_the_page_knows_whether_talking_is_available(self):
        self.assertTrue(self.client.get(self.url("api/voice")).get_json()["available"])
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}):
            self.assertFalse(self.client.get(self.url("api/voice")).get_json()["available"])

    def test_the_page_has_talk_or_type_consent_and_a_truthful_microphone(self):
        page = (ROOT / "smf" / "onboarding_page" / "static" / "index.html").read_text(encoding="utf-8")
        for words in ("Your voice is sent securely to our speech-to-text service so I can turn it into words. "
                      "The Social Media Factory keeps the words, not the recording.", "Tap to talk",
                      "Recording now · tap when finished", "Microphone off.", "Type instead", "Speak aloud",
                      "Change voice", "Try again", "I heard"):
            self.assertIn(words, page)
        self.assertNotIn("Listening", page)            # "listening" is never used to mean recording
        self.assertNotIn("localStorage.setItem(\"smf-onboarding-voice\", JSON.stringify(blob", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
