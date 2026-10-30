"""Onboarding rev 12 (spec smf-spec-onboarding-v2.md, "Next phase"): the next round of the onboarding page.

Design B (one question at a time) is the page; typing comes first and the mic points to the computer's own
dictation when there's no voice key. The first screen asks what the business is and where. Starter packs suggest
what's general to a trade, only for the allowlisted questions, and only ever as "Suggested, please check": the
questions customers really ask, the objections the owner hears and the owner's own steps get ideas, never
answers. Where suggested words came from is kept from the page to the brand.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                  # noqa: E402
from smf.onboarding_page import session as S, to_brand                  # noqa: E402
from tests.test_onboarding import BrandCase, PageCase                   # noqa: E402
from tests.test_onboarding_v2 import V2, copy, ok                      # noqa: E402
from tests.test_onboarding_designs import needs_flask                 # noqa: E402

STATIC = ROOT / "smf" / "onboarding_page" / "static"
PACK = {"origin": "starter-pack", "generator": "pack:auto-repair@1"}


def suggested(**fields):
    return dict(fields, status="confirmed", source="draft", **PACK)


def lum(hex_colour):
    c = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    x, y = lum(a), lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


class TestStarterPacks(unittest.TestCase):
    def setUp(self):
        self.p = S.starter_packs()

    def test_packs_only_suggest_the_allowlisted_questions(self):
        self.assertEqual(self.p["allowlist"], ["audience_who", "audience_way", "myths", "mistakes", "rules", "platforms"])
        for pack in self.p["packs"]:
            self.assertLessEqual(set(pack["suggestions"]), set(self.p["allowlist"]), pack["id"])
            self.assertLessEqual(set(pack["topic_ideas"]), {"audience_questions", "objections", "steps"}, pack["id"])

    def test_packs_hold_no_numbers_prices_or_results(self):
        # General to a trade, never a statistic or a promise (N3: "No statistics, prices or results claims").
        for pack in self.p["packs"]:
            # Rules are left out: they name what never to promise ("never guarantee it").
            sugg = {k: v for k, v in pack["suggestions"].items() if k != "rules"}
            words = json.dumps([sugg, pack["topic_ideas"], pack["video_ideas"]], ensure_ascii=False)
            self.assertIsNone(re.search(r"\d|%|\$|£|€|guarantee", words), pack["id"])

    def test_suggested_palettes_are_readable(self):
        for pack in self.p["packs"]:
            for pal in pack["palettes"]:
                self.assertGreaterEqual(contrast(pal["background"], pal["text"]), 7, pack["id"])
                self.assertGreaterEqual(contrast(pal["background"], pal["accent"]), 3, pack["id"])

    def test_a_type_of_business_finds_its_pack_by_whole_words(self):
        self.assertEqual(S.match_pack("Auto repair")["id"], "auto-repair")
        self.assertEqual(S.match_pack("Breathwork coaching")["id"], "wellness")
        self.assertEqual(S.match_pack("HVAC and plumbing, Long Beach")["id"], "home-services")
        self.assertIsNone(S.match_pack("Underwater basket weaving"))
        self.assertIsNone(S.match_pack("garages"[:0]))

    def test_health_rules_are_only_ever_suggested(self):
        # A type of business never switches compliance on by itself; the owner taps it (N3).
        engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.assertIn("This applies to my business", engine)
        self.assertIn("Not reviewed by a lawyer: check with someone qualified if your industry is regulated.", engine)
        self.assertIn("These are starting points, not a full compliance check.", engine)


class TestSuggestedWordsOnlyGoWhereAllowed(PageCase):
    def check(self, key, answer):
        return S.validate_answer(key, answer)

    def test_a_whole_audience_or_teach_answer_is_never_marked_as_suggested(self):
        # Customer questions live inside the audience answer, so suggestions are kept question by question.
        self.assertTrue(self.check("audience", dict(ok(value="Local drivers who want an honest shop"), origin="starter-pack")))
        self.assertTrue(self.check("teach", dict(myths=[], status="confirmed", origin="description")))

    def test_kept_pack_myths_and_mistakes_are_fine(self):
        self.assertEqual(self.check("teach", {"myths": [suggested(id="myth-1", value="Warning lights can wait")]}), [])

    def test_steps_objections_and_what_you_do_are_only_ever_the_owners_words(self):
        self.assertTrue(self.check("teach", {"steps": [suggested(id="step-1", value="Diagnose first")]}))
        self.assertTrue(self.check("audience", ok(value="Local drivers who want an honest shop",
                                                  objections=[suggested(id="obj-1", value="Too expensive")])))
        self.assertTrue(self.check("what_you_do", suggested(value="We fix cars")))
        self.assertTrue(self.check("why_started", dict(ok(value="Because"), origin="description")))

    def test_where_words_came_from_is_refused_for_questions_only_the_owner_can_answer(self):
        self.assertEqual(self.check("provenance", {"audience_who": dict(PACK)}), [])
        self.assertTrue(self.check("provenance", {"audience_questions": dict(PACK)}))
        self.assertTrue(self.check("provenance", {"objections": {"origin": "description",
                                                                 "generator": "claude-from-description"}}))
        # An owner's own answer, prompted by an idea, is theirs (and says what prompted it).
        self.assertEqual(self.check("provenance", {"audience_questions": {
            "origin": "person", "prompted_by": {"generator": "pack:auto-repair@1", "idea": "Why is my light on?"}}}), [])

    def test_a_draft_that_fills_a_not_allowed_question_is_refused_before_the_page_opens(self):
        with self.assertRaises(S.SessionError):
            S.intake_from_draft({"answers": {"what_you_do": dict(ok(value="We fix cars properly"), origin="starter-pack")}})

    def test_the_chats_draft_with_the_first_screen_and_its_own_suggestions_opens_the_page(self):
        # The onboard-brand skill's shape (N2, N3): what and where from the chat, a custom pack only for the
        # allowlisted questions, website drafts with the page they came from.
        intake = S.intake_from_draft({"answers": {
            "business_start": {"what": "Mobile dog grooming", "where": "Austin", "source": "draft", "origin": "chat"},
            "starter_pack": {"id": "custom", "suggestions": {"suggestions": {"audience_who": "Busy dog owners nearby"},
                                                              "topic_ideas": {"steps": ["What a groom includes"]}}},
            "what_you_do": {"value": "We groom dogs at your door.", "origin": "website", "refs": ["About page"]},
        }})
        self.assertEqual(intake["answers"]["business_start"]["status"], "unconfirmed")
        self.assertEqual(intake["answers"]["starter_pack"]["id"], "custom")
        self.assertEqual(intake["answers"]["what_you_do"]["refs"], ["About page"])

    def test_the_first_screen_pack_ideas_and_the_rest_fit_the_answers_file(self):
        intake = S.blank_intake()
        intake["answers"].update({
            "business_start": ok(what="Auto repair", where="Hermosa Beach", website="example.com"),
            "starter_pack": dict(ok(id="auto-repair", version=1), status="unconfirmed"),
            "topic_ideas": [suggested(id="idea-1", field="audience_questions", text="Why is my light on?")],
            "platform_candidates": [dict(suggested(platform="instagram"), status="unconfirmed")],
            "acquisition": [ok(id="acq-1", value="Word of mouth")],
            "filming": ok(speakers=[ok(id="person", mode="on_camera")], where="The shop"),
            "fonts": suggested(heading="Arial Black", body="Arial"),
            "provenance": {"audience_who": dict(PACK)},
        })
        self.assertEqual(S.validate_intake(intake), [])


class TestRev12ReachesTheBrand(BrandCase):
    def answers(self):
        a = copy()
        a["business_start"] = ok(what="Physio for runners", where="Bristol", website="stride.example")
        a["starter_pack"] = ok(id="fitness", version=1)
        a["audience"]["type"], a["audience"]["where"] = "retail", "both"
        a["teach"]["myths"].append(dict(suggested(id="myth-3", value="Soreness means it worked"),
                                        generator="pack:fitness@1"))
        a["acquisition"] = [ok(id="acq-1", value="Club referrals")]
        a["filming"] = ok(speakers=[ok(id="person", mode="on_camera"), ok(id="company", mode="voice_over")],
                          where="The clinic")
        a["fonts"] = ok(heading="Georgia", body="Verdana")
        a["topic_ideas"] = [suggested(id="idea-1", field="steps", text="How a first session works")]
        a["provenance"] = {"audience_who": {"origin": "starter-pack", "generator": "pack:fitness@1"}}
        return a

    def test_everything_new_lands_where_the_spec_says_and_the_brand_stays_sound(self):
        b, notes = self.build_brand(self.answers())
        d = brands.load(b.id).data
        self.assertEqual(brands.validate(d)[0], [])
        self.assertEqual(d["business"]["location"], "Bristol")
        self.assertEqual(d["business"]["starter_pack"], {"id": "fitness", "version": 1})
        self.assertEqual((d["audience"]["type"], d["audience"]["where"]), ("retail", "both"))
        self.assertEqual(d["audience"]["acquisition"], [{"id": "acq-1", "value": "Club referrals", "source": "typed"}])
        self.assertEqual(d["filming"], {"speakers": [{"id": "person", "mode": "on_camera"},
                                                     {"id": "company", "mode": "voice_over"}], "where": "The clinic"})
        self.assertEqual(d["topic_ideas"][0]["text"], "How a first session works")
        self.assertEqual(d["_provenance"]["audience.who"]["generator"], "pack:fitness@1")   # keyed by the setting
        kept = [m for m in d["myths"] if m["id"] == "myth-3"][0]
        self.assertEqual((kept["source"], kept["provenance"]["origin"]), ("drafted", "starter-pack"))

    def test_fonts_are_a_preference_and_never_change_what_the_pictures_draw_with(self):
        b, notes = self.build_brand(self.answers())
        d = brands.load(b.id).data
        self.assertEqual(d["visual"]["font_preference"], {"heading": "Georgia", "body": "Verdana"})
        self.assertNotEqual(d["visual"].get("fonts", {}).get("display"), "Georgia")
        self.assertTrue(any("Georgia for headings" in n for n in notes))

    def test_an_auto_matched_pack_reaches_the_brand_only_once_something_from_it_was_kept(self):
        a = self.answers()
        a["starter_pack"] = dict(ok(id="fitness", version=1), status="unconfirmed")
        a["teach"]["myths"] = [m for m in a["teach"]["myths"] if not m.get("generator")]
        a["provenance"], a["fonts"], a["topic_ideas"] = {}, ok(heading="Georgia"), []
        intake = S.blank_intake()
        intake["answers"] = a
        _, answers, _, _ = to_brand.build(intake)
        self.assertNotIn("starter_pack", answers.get("business", {}))
        a["teach"]["myths"].append(dict(suggested(id="myth-9", value="Soreness means it worked"), generator="pack:fitness@1"))
        _, answers, _, _ = to_brand.build(intake)
        self.assertEqual(answers["business"]["starter_pack"]["id"], "fitness")

    def test_a_pack_only_counts_as_used_from_confirmed_kept_answers(self):
        # Pending platform ideas or an unconfirmed myth never make an auto-matched pack a brand setting.
        a = self.answers()
        a["starter_pack"] = dict(ok(id="fitness", version=1), status="unconfirmed")
        a["teach"]["myths"] = [dict(suggested(id="myth-9", value="Soreness means it worked"), generator="pack:fitness@1",
                                    status="unconfirmed")]
        a["platform_candidates"] = [dict(suggested(platform="instagram"), generator="pack:fitness@1", status="unconfirmed")]
        a["provenance"], a["fonts"], a["topic_ideas"] = {}, ok(heading="Georgia"), []
        intake = S.blank_intake()
        intake["answers"] = a
        _, answers, _, _ = to_brand.build(intake)
        self.assertNotIn("starter_pack", answers.get("business", {}))

    def test_an_owners_own_answer_keeps_what_prompted_it_and_mixed_parts(self):
        got = to_brand._provenance({"origin": "person", "prompted_by": {"generator": "pack:fitness@1", "idea": "x"}})
        self.assertEqual(got["prompted_by"]["idea"], "x")
        self.assertIsNone(to_brand._provenance({"origin": "person", "source": "typed"}))

    def test_unconfirmed_first_screen_answers_and_skipped_packs_stay_out(self):
        a = self.answers()
        a["business_start"]["status"] = "unconfirmed"
        a["starter_pack"] = {"status": "skipped", "source": "typed", "origin": "person"}
        intake = S.blank_intake()
        intake["answers"] = a
        _, answers, _, _ = to_brand.build(intake)
        self.assertNotIn("location", answers.get("business", {}))
        self.assertNotIn("starter_pack", answers.get("business", {}))


class TestThePageItself(unittest.TestCase):
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        self.one = (STATIC / "one-page.html").read_text(encoding="utf-8")

    def test_the_first_screen_asks_what_and_where_with_one_button_and_no_voice_question(self):
        for want in ('id="start-what"', 'id="start-where"', 'id="start-web"', 'id="start"'):
            self.assertIn(want, self.engine)
        self.assertNotIn("sw-voice", self.engine)
        self.assertIn("Without the chat you\\'ll get suggestions for your type of business only.", self.engine)

    def test_status_chips_use_plain_words_and_have_a_key(self):
        self.assertIn('var LABEL = { wait: "Not answered yet", check: "Suggested, please check", quote: "Your words, please '
                      'confirm", ok: "Done", skipped: "Skipped", chat: "For the chat", typed: "Not confirmed yet" };', self.engine)
        # Rev 14 (design review): no colour key and no colour coding; a done question shows a quiet check mark.
        self.assertIn('function chipKey() { return ""; }', self.engine)
        self.assertIn(".chip .dot { display:none; }", (STATIC / "v2-common.css").read_text(encoding="utf-8"))

    def test_suggestions_never_confirm_or_overwrite_and_myths_ask_first(self):
        self.assertIn("Nothing is saved until you tap Confirm.", self.engine)
        self.assertIn("Have you heard customers believe this?", self.engine)
        self.assertIn("Have you seen customers make this mistake?", self.engine)
        self.assertIn("Add to mine", self.engine)
        self.assertIn("Use instead", self.engine)
        # Questions only the owner can answer get ideas, and an idea becomes an answer only in their own words.
        self.assertIn("Ideas only. This question needs your own words", self.engine)
        self.assertIn("prompted_by: prompted[field.id]", self.engine)

    def test_nothing_is_loaded_from_the_internet(self):
        for name, text in (("v2-common.js", self.engine), ("steps.html", self.steps), ("one-page.html", self.one),
                           ("v2-common.css", (STATIC / "v2-common.css").read_text(encoding="utf-8"))):
            self.assertIsNone(re.search(r"(https?:)?//[a-z0-9.-]+\.[a-z]{2,}/", text, re.I), name)
            self.assertNotIn("@import", text, name)

    def test_the_optional_filming_question_follows_who_speaks_and_is_never_counted(self):
        f = S.fields()
        self.assertEqual(len(f["core"]), 31)
        self.assertEqual([(x["id"], x["after"]) for x in f["extra"]], [("filming", "identities"), ("acquisition", "audience_questions"),
                                                                        ("influences", "phrases")])
        self.assertIn("V.fiveRoute()", self.steps)          # rev 14: the five steps (filming is in Make it better)
        self.assertIn("(F.extra || []).forEach(function (x) { if (x.after === f.id) { out.push(x); } });", self.engine)
        self.assertIn("V.coreOrder()", self.one)

    def test_question_29_counts_once_the_goal_is_answered_and_skip_only_skips_the_goal(self):
        self.assertIn('case "goal_platforms": obj(answer("goal"), ["value"]); break;', self.engine)
        self.assertIn('if (C === "skipped") { put("goal", { status: "skipped", source: "typed", origin: "person" }); break; }', self.engine)

    def test_switching_packs_keeps_platforms_the_owner_acted_on_and_voice_shows_its_cost_when_asked(self):
        self.assertIn('filter(function (c) { return c.status !== "unconfirmed"; })', self.engine)
        self.assertIn("It uses your ElevenLabs account: ", self.engine)
        # Platform suggestions wait behind "Draft this for me" like every other suggestion (N4).
        self.assertIn("panel.innerHTML = platformSuggestHTML(field, sp2)", self.engine)
        self.assertNotIn("platformSuggestHTML(field, speakers) +", self.engine)
        # Removing a speaker who's in the filming answer asks first.
        self.assertIn("also takes them out of your videos", self.engine)



class TestTheServerHandsOverThePacks(PageCase):
    @needs_flask
    def test_the_server_hands_the_page_the_bundled_packs(self):
        from smf.onboarding_page import server
        session = S.new_session(8652, S.blank_intake(), layout="steps")
        client = server.create_app(session["code"]).test_client()
        r = client.get("/%s/api/packs" % session["code"])
        self.assertEqual(r.status_code, 200)
        self.assertIn("auto-repair", [p["id"] for p in r.get_json()["packs"]])
        self.assertEqual(client.get("/wrong-code/api/packs").status_code, 404)


if __name__ == "__main__":
    unittest.main()
