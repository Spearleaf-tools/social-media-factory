"""Onboarding v2, piece 1b: the answers file holds every core and deeper answer (spec rev 10, "Storage").

The page and the agent share one answers file. Version 2 adds the rest of the core (why you started, how you
sound, what you stand for, what you teach, the offer ladder, the goal, platforms, capacity, what you can show)
and the deeper answers. Every item keeps its own status, how it was entered (`source`) and where it came from
(`origin`); list items keep their ids. The core belief, the others/us rows and the non-negotiables (F8 B, D, E)
are never drafted. An update merges list items by id and only removes one when the person removed it.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                  # noqa: E402
from smf.onboarding_page import session as S, to_brand                  # noqa: E402
from tests.test_onboarding import FULL, BrandCase, PageCase             # noqa: E402


def ok(**fields):
    return dict(fields, status="confirmed", source="typed", origin="person")


V2 = dict(json.loads(json.dumps(FULL)), **{
    "why_started": ok(value="I kept seeing runners rest for months when two weeks of the right loading would do."),
    "voice": ok(register="Calm, plain and a little dry; we explain the why.", do=["Give the number"],
                dont=["Promise a cure"], signature_phrases=["Rest is training too."]),
    "positioning": {
        "known_for": ok(value="Getting runners back without months off"),
        "core_belief": ok(value="Most running injuries need load, not rest.",
                          experience="Fifteen years of club runners who came back faster when they kept moving."),
        "contrarian": [ok(id="belief-1", value="New shoes rarely fix knee pain.", experience="Gait clinics since 2015.")],
        "for": [ok(id="for-1", value="Strength work for every runner", experience="Our own return-to-run plan.")],
        "against": [ok(id="against-1", value="Six weeks of rest by default", experience="Watched it fail for years.")],
        "differentiation": [ok(id="diff-1", others="Tell you to stop running", us="Change how you run this week")],
        "non_negotiables": [ok(id="nn-1", value="A real runner in every piece")],
        "story": ok(catalyst="Saw rested runners come back weaker", core_truth="Load heals",
                    proof=[ok(id="proof-1", value="Two hundred runners back within a month")]),
        "home_medium": ok(value="video"),
        "stage": ok(value="under_100k"),
    },
    "teach": {"myths": [ok(id="myth-1", value="Rest fixes everything"), ok(id="myth-2", value="Ice heals")],
              "mistakes": [ok(id="mistake-1", value="Running through sharp pain")],
              "steps": [ok(id="step-1", value="Find the load you can take"), ok(id="step-2", value="Build it weekly")]},
    "ladder": [ok(rung="free", name="Knee check guide", line="One page of tests to do at home",
                  keyword="knee", keyword_ready=False),
               ok(rung="entry", name="Assessment", line="One hour with Sam", price="£60",
                  call_to_action="Book an assessment on our website"),
               ok(rung="main", none_yet=True),
               ok(rung="premium", name="Return to run", line="Eight weeks, start to race")],
    "goal": ok(value="leads"),
    "platforms": ok(by_speaker={"person": ["instagram", "youtube"], "company": ["facebook"]}, other="A newsletter"),
    "capacity": ok(hours_per_week=3, helpers="Our receptionist films", posts_per_week=4),
    "show": [ok(id="show-1", value="Before and after hop tests")],
    "deep": {
        "alternatives": ok(value=["A GP and a leaflet", "Rest and hope"]),
        "journey": ok(want="Every club in Bristol sends us runners", known_for="Fast returns", do="Weekly videos",
                      learn="Better filming"),
        "compliments": ok(value=["You explain it so it sticks"]),
        "formats": ok(repeatable=["One test, one fix", "Runner Q&A"], enjoyable="Clinic walk-throughs"),
        "adjacent_topics": ok(value=["Strength training", "Race prep"]),
        "world": ok(people=["Coach Dee"], places=["The Downs"], interests=["Trail running"], enemy="Rest by default"),
        "person": ok(values=["Honesty"], timeline=["2010 qualified", "2016 opened Stride"], beliefs=["Movement heals"],
                     never_compromise=["Telling the truth about recovery times"], early_signs=["Clubs refer us"],
                     ambitions="A second clinic"),
        "stories": [ok(id="story-1", kind="failure", text="I once told a runner to rest six weeks. She quit."),
                    ok(id="story-2", kind="origin", text="I started after my own knee.")],
        "audience": ok(type="retail", where="both", hangouts=["Parkrun"], trust_triggers=["Seeing real runners"]),
        "offers": ok(customer_journey="Guide, then assessment, then the plan", dream_result="Racing again, pain free",
                     dm_tool="ManyChat"),
        "voice": ok(by_platform={"linkedin": "a little more formal"}, analogies=["A tendon is a rope"],
                    examples=["Rest is training too, until it isn't."]),
        "vocabulary": [ok(id="word-1", value="Load ladder")],
        "content_source": ok(value="A weekly clinic video"),
        "baseline": ok(platforms={"instagram": {"followers": 1200, "typical_views": 400, "date": "2026-10-01"}}),
        "look": ok(fonts={"display": "Inter"}, extra_colors=["#F2B134"], identity_line="Physio for runners",
                   likes=["Clean white pages"], dislikes=["Stock photos"]),
        "proof": [ok(id="proof-new-1", bank="credibility", kind="result", title="Back racing in four weeks",
                     context="Club runner, 10k PB attempt", outcome="Raced in week four", known_from="own_account",
                     may_publish="no")],
    },
})
V2["identities"][0]["id"], V2["identities"][1]["id"] = "person", "company"
V2["name"]["handle"] = "stridephysio.example"
V2["audience"]["in_the_way"] = ["Fear of making it worse"]
V2["audience"]["objections"] = [ok(id="obj-1", value="Physio is expensive", reply="One visit often saves months")]


def copy(answers=None):
    return json.loads(json.dumps(V2 if answers is None else answers))


# ----------------------------------------------------------------------------- the answers file
class TestTheAnswersFileVersionTwo(PageCase):
    def test_a_blank_file_is_version_two_and_only_the_core_is_a_placeholder(self):
        intake = S.blank_intake()
        self.assertEqual(intake["version"], 2)
        self.assertEqual(S.validate_intake(intake), [])
        self.assertEqual(S.placeholders(intake, S.CORE_KEYS), list(S.CORE_KEYS))
        self.assertNotIn("deep", S.placeholders(intake))                    # going deeper is never owed
        self.assertEqual(S.placeholders(intake), list(S.BASICS))            # today's page asks the basics only

    def test_an_answers_file_from_version_one_still_reads(self):
        old = S.blank_intake()
        old["version"] = 1
        old["answers"] = json.loads(json.dumps(FULL))
        self.assertEqual(S.validate_intake(old), [])

    def test_every_core_and_deeper_answer_fits(self):
        intake = S.blank_intake()
        intake["answers"] = copy()
        self.assertEqual(S.validate_intake(intake), [])
        self.assertEqual(S.placeholders(intake, S.CORE_KEYS), [])

    def test_what_they_stand_for_has_the_specs_limits(self):
        intake = S.blank_intake()
        intake["answers"]["positioning"] = {
            "contrarian": [ok(id="b-%d" % n, value="x") for n in range(4)],
            "for": [ok(id="f-%d" % n, value="x") for n in range(3)],
            "differentiation": [ok(id="d-%d" % n, others="a", us="b") for n in range(5)],
            "non_negotiables": [ok(id="n-%d" % n, value="x") for n in range(6)]}
        problems = " | ".join(S.validate_intake(intake))
        for words in ("contrarian has more than 3", "for has more than 2", "differentiation has more than 4",
                      "non_negotiables has more than 5"):
            self.assertIn(words, problems)

    def test_list_items_need_their_own_id_and_where_it_came_from_is_checked(self):
        intake = S.blank_intake()
        intake["answers"]["teach"] = {"myths": [{"value": "Rest fixes everything", "status": "confirmed"}]}
        intake["answers"]["why_started"] = {"value": "x", "status": "confirmed", "origin": "a dream"}
        problems = " | ".join(S.validate_intake(intake))
        self.assertIn("answers.teach.myths[1].id is missing", problems)
        self.assertIn("answers.why_started.origin must be one of", problems)

    def test_a_group_counts_once_any_part_of_it_is_confirmed(self):
        intake = S.blank_intake()
        intake["answers"]["positioning"] = {"known_for": ok(value="Fast returns"),
                                            "core_belief": {"value": "x", "status": "skipped"}}
        intake["answers"]["teach"] = {"myths": [dict(ok(id="myth-1", value="Ice heals"), status="unconfirmed")]}
        left = S.placeholders(intake, S.CORE_KEYS)
        self.assertNotIn("positioning", left)
        self.assertIn("teach", left)

    def test_an_answer_outside_the_page_is_still_refused(self):
        intake = S.blank_intake()
        intake["answers"]["shoe_size"] = {"status": "confirmed"}
        self.assertIn("shoe_size", " ".join(S.validate_intake(intake)))
        self.assertTrue(S.validate_answer("shoe_size", {"status": "confirmed"}))


class TestTheseAreNeverDrafted(PageCase):
    """F8 B, D and E: what they believe, what others do and what they do instead, and their non-negotiables
    come only from the person. A draft of any of them is refused, on the way in and on the page."""

    NEVER = {"core_belief": ok(value="Load, not rest"),
             "contrarian": [ok(id="belief-1", value="Shoes rarely help")],
             "differentiation": [ok(id="diff-1", others="Rest", us="Load")],
             "non_negotiables": [ok(id="nn-1", value="A real runner")]}

    def test_a_website_draft_of_any_of_them_is_refused_and_named(self):
        for part, value in self.NEVER.items():
            with self.assertRaises(S.SessionError) as cm:
                S.intake_from_draft({"answers": {"positioning": {part: value}}})
            self.assertIn(S.NEVER_DRAFTED_WORDS[part], str(cm.exception), part)

    def test_the_rest_of_what_they_stand_for_may_be_drafted_and_arrives_as_please_check(self):
        intake = S.intake_from_draft({"answers": {"positioning": {"known_for": ok(value="Fast returns"),
                                                                  "for": [ok(id="for-1", value="Strength")]}}})
        known = intake["answers"]["positioning"]["known_for"]
        self.assertEqual((known["status"], known["source"]), ("unconfirmed", "draft"))
        item = intake["answers"]["positioning"]["for"][0]
        self.assertEqual((item["id"], item["status"], item["source"]), ("for-1", "unconfirmed", "draft"))

    def test_the_page_refuses_a_drafted_one_but_takes_the_persons_own_words(self):
        for source in ("draft", "draft-edited"):
            bad = {"core_belief": dict(ok(value="Load"), source=source)}
            self.assertIn(S.NEVER_DRAFTED_WORDS["core_belief"], " ".join(S.validate_answer("positioning", bad)))
            bad = {"differentiation": [dict(ok(id="diff-1", others="a", us="b"), source=source)]}
            self.assertTrue(S.validate_answer("positioning", bad))
        self.assertEqual(S.validate_answer("positioning", {"core_belief": ok(value="Load, not rest")}), [])

    def test_a_whole_answers_file_with_a_drafted_one_is_not_sound(self):
        intake = S.blank_intake()
        intake["answers"]["positioning"] = {"non_negotiables": [dict(ok(id="nn-1", value="x"), source="draft")]}
        self.assertIn(S.NEVER_DRAFTED_WORDS["non_negotiables"], " ".join(S.validate_intake(intake)))


class TestDraftsInsideGroups(PageCase):
    def test_every_drafted_part_and_item_arrives_unconfirmed_with_its_id(self):
        intake = S.intake_from_draft({"answers": {
            "teach": {"myths": [ok(id="myth-1", value="Ice heals")]},
            "ladder": [ok(rung="free", name="Guide")],
            "deep": {"journey": ok(want="More clubs"), "stories": [ok(id="story-1", kind="origin", text="My knee")]}}})
        a = intake["answers"]
        for got in (a["teach"]["myths"][0], a["ladder"][0], a["deep"]["journey"], a["deep"]["stories"][0]):
            self.assertEqual((got["status"], got["source"]), ("unconfirmed", "draft"))
        self.assertEqual(a["teach"]["myths"][0]["id"], "myth-1")

    def test_a_drafted_part_that_looks_like_a_key_is_dropped_on_its_own(self):
        from tests.test_onboarding import FAKE_KEY
        intake = S.intake_from_draft({"answers": {"positioning": {"known_for": ok(value=FAKE_KEY),
                                                                  "for": [ok(id="for-1", value="Strength")]}}})
        self.assertNotIn("known_for", intake["answers"]["positioning"])
        self.assertIn("for", intake["answers"]["positioning"])


# ----------------------------------------------------------------------------- to the brand
class TestEveryAnswerReachesTheBrand(BrandCase):
    def test_a_full_version_two_onboarding_builds_a_sound_brand(self):
        b, notes = self.build_brand(copy())
        d = brands.load(b.id).data
        self.assertEqual(brands.validate(d)[0], [])
        self.assertEqual(d["person"]["why_started"][:23], "I kept seeing runners r")
        self.assertEqual(d["voice"]["register"], "Calm, plain and a little dry; we explain the why.")
        self.assertEqual(d["voice"]["signature_phrases"], ["Rest is training too."])
        self.assertEqual(d["visual"]["handle"], "stridephysio.example")
        self.assertEqual(d["audience"]["problems"], ["Fear of making it worse"])
        self.assertEqual(d["audience"]["objections"], [{"id": "obj-1", "value": "Physio is expensive",
                                                        "reply": "One visit often saves months", "source": "typed"}])
        self.assertEqual(d["goal"], "leads")
        self.assertEqual(d["intended_platforms"], {"by_speaker": {"person": ["instagram", "youtube"],
                                                                  "company": ["facebook"]}, "other": "A newsletter"})
        self.assertEqual(d["capacity"], {"hours_per_week": 3, "helpers": "Our receptionist films", "posts_per_week": 4})
        self.assertEqual(d["proof_summary"], [{"id": "show-1", "text": "Before and after hop tests"}])
        self.assertEqual([m["id"] for m in d["myths"]], ["myth-1", "myth-2"])
        self.assertEqual(d["steps_to_result"][1], {"id": "step-2", "value": "Build it weekly", "source": "typed"})
        self.assertEqual([n for n in notes if not n.startswith("Sign-off rules")], [])

    def test_what_they_stand_for_keeps_ids_experience_and_how_it_was_given(self):
        b, _ = self.build_brand(copy())
        p = brands.load(b.id).data["positioning"]
        self.assertEqual(p["core_belief"]["value"], "Most running injuries need load, not rest.")
        self.assertIn("Fifteen years", p["core_belief"]["experience"])
        self.assertEqual(p["contrarian"][0], {"id": "belief-1", "value": "New shoes rarely fix knee pain.",
                                              "experience": "Gait clinics since 2015.", "source": "typed"})
        self.assertEqual(p["differentiation"][0]["us"], "Change how you run this week")
        self.assertEqual(p["story"]["proof"], [{"id": "proof-1", "value": "Two hundred runners back within a month",
                                                "source": "typed"}])
        self.assertEqual((p["home_medium"], p["stage"]), ("video", "under_100k"))
        self.assertEqual(p["formats"]["enjoyable"], "Clinic walk-throughs")
        self.assertEqual(p["world"]["enemy"], "Rest by default")

    def test_the_strategy_file_shows_the_experience_behind_the_core_belief(self):
        b, _ = self.build_brand(copy())
        brands.sync(brands.load(b.id))
        text = Path(b.path("Brand", "brand-strategy.md")).read_text(encoding="utf-8")
        self.assertIn("Most running injuries need load, not rest.", text)
        self.assertIn("_From experience:_ Fifteen years of club runners", text)

    def test_the_deeper_answers_land_where_the_spec_says(self):
        b, _ = self.build_brand(copy())
        d = brands.load(b.id).data
        self.assertEqual(d["audience"]["alternatives"], ["A GP and a leaflet", "Rest and hope"])
        self.assertEqual((d["audience"]["type"], d["audience"]["where"]), ("retail", "both"))
        self.assertEqual(d["person"]["ambitions"], "A second clinic")
        self.assertEqual([s["kind"] for s in d["person"]["stories"]], ["failure", "origin"])
        self.assertEqual(d["customer_journey"], "Guide, then assessment, then the plan")
        self.assertEqual(d["dm_tool"], "ManyChat")
        self.assertEqual(d["voice"]["analogies"], ["A tendon is a rope"])
        self.assertEqual(d["vocabulary"], [{"id": "word-1", "value": "Load ladder", "source": "typed"}])
        self.assertEqual(d["content_source"], "A weekly clinic video")
        self.assertEqual(d["baseline"]["instagram"]["followers"], 1200)
        self.assertEqual(d["visual"]["identity_line"], "Physio for runners")
        self.assertEqual(d["visual"]["extra_colors"], ["#F2B134"])

    def test_proof_waits_for_the_proof_library_and_never_enters_the_settings(self):
        _name, answers, _notes, _voice = to_brand.build(self.intake(copy()))
        self.assertNotIn("proof", answers)
        self.assertNotIn("Back racing in four weeks", json.dumps(answers))

    def test_only_confirmed_parts_are_carried_over(self):
        answers = copy()
        answers["teach"]["myths"][1]["status"] = "unconfirmed"
        answers["positioning"]["core_belief"]["status"] = "skipped"
        answers["deep"]["journey"]["status"] = "for_chat"
        _name, out, notes, _voice = to_brand.build(self.intake(answers))
        self.assertEqual([m["id"] for m in out["myths"]], ["myth-1"])
        self.assertNotIn("core_belief", out["positioning"])
        self.assertNotIn("journey", out["positioning"])
        self.assertTrue(any("deep.journey" in n for n in notes))

    def test_how_it_was_given_follows_source_and_origin(self):
        answers = copy()
        answers["teach"]["myths"][0].update(source="draft-edited", origin="website")
        answers["teach"]["myths"][1].update(source="draft", origin="document")
        _name, out, _notes, _voice = to_brand.build(self.intake(answers))
        self.assertEqual(out["myths"][0]["source"], "drafted-from-website")
        self.assertNotIn("source", out["myths"][1])         # drafted from a document: no brand word for it, so none

    def test_the_ladder_becomes_offers_with_ids_and_none_yet_makes_none(self):
        _name, out, _notes, _voice = to_brand.build(self.intake(copy()))
        offers = {o["rung"]: o for o in out["offers"]}
        self.assertEqual(sorted(offers), ["entry", "free", "premium"])
        self.assertEqual(offers["free"], {"id": "knee-check-guide", "name": "Knee check guide", "rung": "free",
                                          "what": "One page of tests to do at home", "keyword": "KNEE",
                                          "keyword_ready": False})
        self.assertEqual(offers["entry"]["price"], "£60")

    def test_a_call_to_action_asking_for_a_keyword_is_held_back_with_a_reason(self):
        answers = copy()
        answers["ladder"][1]["call_to_action"] = "Comment ASSESS and I'll send the link"
        b, notes = self.build_brand(answers)
        entry = next(o for o in brands.load(b.id).data["offers"] if o.get("rung") == "entry")
        self.assertNotIn("call_to_action", entry)
        self.assertTrue(any("comment" in n.lower() and "Assessment" in n for n in notes))

    def test_a_keyword_that_is_not_one_short_word_is_held_back(self):
        answers = copy()
        answers["ladder"][0]["keyword"] = "knee pain"
        _name, out, notes, _voice = to_brand.build(self.intake(answers))
        self.assertNotIn("keyword", next(o for o in out["offers"] if o["rung"] == "free"))
        self.assertTrue(any("knee pain" in n for n in notes))

    def test_a_story_proof_item_not_confirmed_is_left_out(self):
        answers = copy()
        answers["positioning"]["story"]["proof"].append(
            dict(ok(id="proof-2", value="An unchecked claim"), status="unconfirmed"))
        _name, out, _notes, _voice = to_brand.build(self.intake(answers))
        self.assertEqual([p["id"] for p in out["positioning"]["story"]["proof"]], ["proof-1"])

    def test_odd_shapes_in_the_answers_file_are_refused_plainly_never_a_crash(self):
        for odd in ({"positioning": ["oops"]}, {"teach": "oops"}, {"deep": 3}, {"ladder": {"rung": "free"}},
                    {"positioning": {"story": ok(proof="x")}},
                    {"ladder": [ok(rung="top", name="x")]}, {"voice": ok(register=["x"])}):
            with self.assertRaises(S.SessionError, msg=odd) as cm:
                to_brand.build(self.intake(odd))
            self.assertIn("not in the shape", str(cm.exception))
        _name, _out, notes, _voice = to_brand.build(self.intake({"identities": [ok(kind="person", name=None)]}))
        self.assertTrue(any("without a name" in n for n in notes))     # empty is "not given": a note, not a crash
        for odd in ({"answers": "oops"}, {"answers": {"name": ok(value=["x"])}}, {"version": 2}):
            with self.assertRaises(S.SessionError):
                to_brand.build(dict({"version": 2, "state": "complete"}, **odd))

    def test_the_command_refuses_a_damaged_answers_file(self):
        from smf.onboarding_page import cli
        session = self.start()
        intake = S.load_intake(session)
        intake["state"] = "complete"
        out = Path(self.tmp.name) / "answers.json"
        for damage in ({"answers": dict(intake["answers"], positioning=["oops"])}, {"brand": ["maple"]}, {"brand": 7}):
            S.write_json(session["intake"], dict(intake, **damage))
            with self.assertRaises(S.SessionError, msg=damage) as cm:
                cli._brand_answers(str(out))
            self.assertIn("not in the shape", str(cm.exception))
            self.assertFalse(out.exists())

    def test_parking_the_strategy_part_writes_none_of_it_and_says_so(self):
        answers = copy()
        answers["positioning"]["parked"] = True
        _name, out, notes, _voice = to_brand.build(self.intake(answers))
        self.assertNotIn("positioning", out)
        self.assertTrue(any("answer later" in n for n in notes))

    def test_no_goal_means_no_goal_is_written(self):
        answers = copy()
        del answers["goal"]
        _name, out, _notes, _voice = to_brand.build(self.intake(answers))
        self.assertNotIn("goal", out)

    def test_platforms_for_a_speaker_nobody_confirmed_are_held_back(self):
        answers = copy()
        answers["platforms"]["by_speaker"]["person-9"] = ["tiktok"]
        _name, out, notes, _voice = to_brand.build(self.intake(answers))
        self.assertNotIn("person-9", out["intended_platforms"]["by_speaker"])
        self.assertTrue(any("person-9" in n for n in notes))


# ----------------------------------------------------------------------------- updates merge by id
class TestUpdatesMergeListsById(BrandCase):
    def setUp(self):
        super().setUp()
        self.brand, _ = self.build_brand(copy())

    def update(self, answers, current=True):
        intake = self.intake(answers)
        intake["brand"] = self.brand.id
        cur = brands.load(self.brand.id).data if current else None
        _name, ans, notes, _voice = to_brand.build(intake, current=cur)
        brands.update(self.brand.id, ans)
        self.notes = notes
        return brands.load(self.brand.id).data

    def test_editing_one_item_keeps_its_id_its_place_and_the_others(self):
        d = self.update({"teach": {"myths": [ok(id="myth-1", value="Rest fixes every injury")]}})
        self.assertEqual([(m["id"], m["value"]) for m in d["myths"]],
                         [("myth-1", "Rest fixes every injury"), ("myth-2", "Ice heals")])

    def test_a_new_item_is_added_and_a_missing_one_is_never_removed(self):
        d = self.update({"teach": {"myths": [ok(id="myth-3", value="Stretching prevents injury")]}})
        self.assertEqual([m["id"] for m in d["myths"]], ["myth-1", "myth-2", "myth-3"])
        d = self.update({"teach": {"myths": []}})
        self.assertEqual([m["id"] for m in d["myths"]], ["myth-1", "myth-2", "myth-3"])

    def test_an_item_the_person_removed_and_confirmed_is_removed(self):
        d = self.update({"teach": {"myths": [ok(id="myth-2", value="Ice heals", remove=True)]}})
        self.assertEqual([m["id"] for m in d["myths"]], ["myth-1"])
        d = self.update({"positioning": {"for": [ok(id="for-1", remove=True)]}})
        self.assertEqual(d["positioning"]["for"], [])

    def test_a_removal_not_confirmed_removes_nothing(self):
        d = self.update({"teach": {"myths": [dict(ok(id="myth-2", remove=True), status="unconfirmed")]}})
        self.assertEqual([m["id"] for m in d["myths"]], ["myth-1", "myth-2"])

    def test_an_update_naming_only_one_speaker_keeps_the_others(self):
        answers = {"identities": [dict(FULL["identities"][0], id="person", role="Clinic lead")]}
        d = self.update(answers)
        self.assertEqual([(i["id"], i.get("role")) for i in d["identities"]],
                         [("person", "Clinic lead"), ("company", None)])

    def test_a_speaker_or_an_offer_cannot_be_removed_by_an_update(self):
        for answers in ({"identities": [{"id": "company", "remove": True}]},
                        {"offers": [{"id": "assessment", "remove": True}]}):
            with self.assertRaises(brands.BrandError) as cm:
                brands.update(self.brand.id, answers)
            self.assertIn("in the chat", str(cm.exception))
        d = brands.load(self.brand.id).data
        self.assertEqual(len(d["identities"]), 2)
        self.assertIn("assessment", [o["id"] for o in d["offers"]])

    def test_a_speaker_without_an_id_is_matched_by_name_not_added_twice(self):
        person = dict(FULL["identities"][0], role="Clinic lead")
        person.pop("id", None)
        d = self.update({"identities": [person]})
        self.assertEqual([i["id"] for i in d["identities"]], ["person", "company"])
        self.assertEqual(d["identities"][0]["role"], "Clinic lead")

    def test_moving_an_offer_to_another_rung_keeps_its_id(self):
        d = self.update({"ladder": [ok(rung="main", id="assessment", name="Assessment")]})
        rungs = {o["id"]: o.get("rung") for o in d["offers"]}
        self.assertEqual(rungs["assessment"], "main")
        self.assertEqual(brands.validate(d)[0], [])

    def test_none_yet_only_takes_the_rung_away_and_never_deletes_the_offer(self):
        d = self.update({"ladder": [ok(rung="entry", none_yet=True)]})
        assessment = next(o for o in d["offers"] if o["id"] == "assessment")
        self.assertNotIn("rung", assessment)
        self.assertEqual(assessment["name"], "Assessment")

    def test_a_new_offer_on_a_taken_rung_moves_the_old_one_to_your_other_offers(self):
        d = self.update({"ladder": [ok(rung="entry", name="Assessment Plus")]})     # a different offer on the rung
        rungs = {o["id"]: o.get("rung") for o in d["offers"]}
        self.assertEqual((rungs["assessment"], rungs["assessment-plus"]), (None, "entry"))
        self.assertEqual(brands.validate(d)[0], [])

    def test_a_new_offer_never_takes_an_id_already_used(self):
        brands.update(self.brand.id, {"offers": [{"id": "assessment-plus", "name": "Old thing"}]})
        d = self.update({"ladder": [ok(rung="entry", name="Assessment Plus")]})
        self.assertEqual({o["id"]: o.get("rung") for o in d["offers"]}["assessment-plus-2"], "entry")

    def test_the_same_offer_answered_again_keeps_its_id(self):
        d = self.update({"ladder": [ok(rung="entry", name="assessment", price="£65")]})
        entry = [o for o in d["offers"] if o.get("rung") == "entry"]
        self.assertEqual([(o["id"], o["price"]) for o in entry], [("assessment", "£65")])

    def test_applying_the_same_answers_twice_gives_the_same_brand(self):
        answers = copy()
        once = self.update(answers)
        twice = self.update(answers)
        self.assertEqual(once, twice)

    def test_a_confirmed_blank_clears_the_old_answer(self):
        d = self.update({"positioning": {"core_belief": ok(value=""),
                                         "story": ok(catalyst="")}})
        self.assertEqual(d["positioning"]["core_belief"]["value"], "")
        self.assertEqual(d["positioning"]["story"]["catalyst"]["value"], "")
        self.assertEqual(d["positioning"]["story"]["core_truth"]["value"], "Load heals")   # not given: kept
        self.assertNotIn("Most running injuries", brands.strategy_markdown("Stride", d["positioning"]))

    def test_clearing_a_keyword_takes_it_away(self):
        d = self.update({"ladder": [ok(rung="free", name="Knee check guide", keyword="")]})
        free = next(o for o in d["offers"] if o.get("rung") == "free")
        self.assertNotIn("keyword", free)

    def test_objections_merge_by_id_and_questions_left_out_are_kept(self):
        audience = {"value": FULL["audience"]["value"], "status": "confirmed",
                    "objections": [ok(id="obj-2", value="I'll just rest")]}
        d = self.update({"audience": audience})
        self.assertEqual([o["id"] for o in d["audience"]["objections"]], ["obj-1", "obj-2"])
        self.assertEqual(d["audience"]["questions_they_ask"], FULL["audience"]["questions"])

    def test_onboarding_never_touches_linked_accounts(self):
        targets = [{"identity": "person", "platform": "instagram", "provider_brand_id": 555},
                   {"identity": "company", "platform": "facebook", "provider_brand_id": 556}]
        brands.update(self.brand.id, {"accounts": {"targets": targets}})
        d = self.update(copy())
        self.assertEqual(d["accounts"]["targets"], targets)

    def test_lists_of_plain_words_are_still_replaced(self):
        d = self.update({"voice": ok(register="Calm, plain and a little dry; we explain the why.", do=["Show it"])})
        self.assertEqual(d["voice"]["do"], ["Show it"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
