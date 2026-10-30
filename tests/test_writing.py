"""Writing-contract tests: platform rules, topics, the planner, calls to action, grounding, the
library of written posts, the takeaway gate, the contract and the draft check.

Everything runs in a throwaway folder whose name has a space, an apostrophe and an accent in it.
No network. The two brands are invented.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                    # noqa: E402
from smf.brands import BrandError                                         # noqa: E402
from smf.studio import contract, cta, dedup, grounding, journal, plan, platforms, quality, topics, writing_cli   # noqa: E402
from smf.studio.files import StudioError, as_brand, inside, own_lines     # noqa: E402
from smf.studio.posts import Post                                         # noqa: E402
from tests.test_brands import BAKERY, CLINIC                              # noqa: E402

FOUR = {"accounts": {"provider": "metricool", "targets": [
    {"identity": "person", "platform": pf, "provider_brand_id": 101, "connected": True}
    for pf in ("linkedin", "instagram", "facebook", "twitter")] + [
    {"identity": "company", "platform": pf, "provider_brand_id": 102, "connected": True}
    for pf in ("linkedin", "instagram", "facebook")]}}

BAKERY_DETAIL = {
    "pillars": [{"id": "sourdough-at-home", "name": "Sourdough at home", "about": "Starters, proofing and crust for home bakers."},
                {"id": "behind-the-counter", "name": "Behind the counter", "about": "How a small bakery really runs."}],
    "offers": [{"id": "weekend-class", "name": "Weekend Baking Class", "what": "A Saturday morning sourdough class for beginners.",
                "call_to_action": "Book a Saturday class at the counter or on our website.",
                "link": "https://mapleandmain.example/classes"},
               {"id": "bread-club", "name": "Bread Club", "what": "A weekly loaf subscription, collected on Fridays.",
                "call_to_action": "Join the Bread Club at the counter."}],
    "audience": {"who": "People within a few miles who care about good bread and want to learn to bake it.",
                 "problems": ["My starter keeps dying.", "My loaf comes out flat."],
                 "questions_they_ask": ["How long should dough proof?", "Why is my loaf flat?"],
                 "by_platform": {"linkedin": "Local business owners who order for their teams."}},
    "voice": {"register": "Warm, plain and specific. Talks like a baker at the counter, not a brochure.",
              "do": ["Give exact times and weights."], "dont": ["Talk down to beginners."],
              "signature_phrases": ["Trust the dough."], "sources": ["Brand/voice-samples.md"],
              "by_identity": {"company": {"register": "Friendly and brief. The shop talking, not Ava.",
                                          "note": "Says we, never I."}}},
}

GOOD_DRAFT = ("Here is why your loaf comes out flat.\n\n"
              "We proof our sourdough for 18 hours.\n\n"
              "Weigh the flour instead of scooping it.")
OPINION_DRAFT = ("Here is why a home baker should start with one loaf.\n\n"
                 "Pick one recipe and bake it every week.\n\n"
                 "Change one thing at a time, and write down what happened.")


def platform_rules(last_researched):
    def block(limit):
        return {"max_len": limit, "target_len": {"min": 100, "max": min(limit, 900)},
                "opening_line_pattern": "Open on the point, in one line.",
                "structure_template": ["OPENING: the point", "SUBSTANCE: three short lines", "CLOSE: one line"],
                "cta_policy": "One ask at most.", "hashtag_policy": "None needed.",
                "preferred_formats": ["single image"], "do": ["Be specific."], "dont": ["Do not bait for comments."]}
    out = {"_meta": {"universal_rules": ["One post, one idea."]},
           "linkedin": block(3000), "facebook": block(63206), "twitter": block(280), "instagram": block(2200)}
    if last_researched is not None:
        out["_meta"]["last_researched"] = last_researched
    return out


class WritingCase(unittest.TestCase):
    ANSWERS = (BAKERY, FOUR, BAKERY_DETAIL)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="writing ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.write_rules((date.today() - timedelta(days=10)).strftime("%Y-%m-%d"))
        answers = {}
        for part in self.ANSWERS:
            brands._deep_update(answers, json.loads(json.dumps(part)))
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", answers)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    # fixtures ------------------------------------------------------------------------------
    def write_rules(self, last_researched):
        path = Path(self.tmp.name, "playbooks", "profiles.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(platform_rules(last_researched)), encoding="utf-8")

    def clinic(self):
        return brands.create("stride-physio", "Stride Physio", json.loads(json.dumps(CLINIC)))

    def add_proof(self, brand, proof_id, title, detail="", may_publish="yes", kind="result", third_party=0):
        con = sqlite3.connect(brand.path("Studio", "registry.db"))
        con.execute("INSERT INTO proof (proof_id, kind, title, detail, source, file_path, may_publish, "
                    "names_third_party, added_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (proof_id, kind, title, detail, "class sign-up sheets", "", may_publish, third_party,
                     "2026-05-01 09:00:00"))
        con.commit()
        con.close()

    def approved(self, title="Why a loaf comes out flat", source_ref="audience.questions_they_ask[1]", **kw):
        return topics.new_topic(title, source_ref=source_ref, status="approved", **kw)

    def facts(self):
        grounding.add_fact(self.brand, "We proof our sourdough for 18 hours.", "Ava's recipe card")
        grounding.add_fact(self.brand, "We have taught 240 people to bake since 2021.", "class sign-up sheets")


# =============================================================================== the brand is explicit
class TestABrandIsAlwaysNamed(WritingCase):
    def test_nothing_in_place_of_a_brand_is_an_error_that_lists_what_exists(self):
        for nothing in (None, "", 0, {}):
            with self.assertRaises(BrandError) as cm:
                as_brand(nothing)
            self.assertIn("maple-and-main", str(cm.exception))

    def test_a_brand_id_works_as_well_as_a_brand(self):
        self.assertEqual(as_brand("maple-and-main").name, "Maple & Main Bakery")

    def test_an_unknown_brand_raises_everywhere(self):
        topic = self.approved()
        calls = [lambda: plan.plan_week("no-such-brand", "person"),
                 lambda: topics.planning_inputs("no-such-brand"),
                 lambda: cta.load_library("no-such-brand"),
                 lambda: grounding.ground_draft("Plain words.", "no-such-brand"),
                 lambda: dedup.similar_posts("Plain words.", "no-such-brand"),
                 lambda: quality.takeaway_prescreen("Plain words.", "no-such-brand"),
                 lambda: contract.build_contract("no-such-brand", "person", "linkedin", topic, "three-tips", "reach"),
                 lambda: contract.validate_draft("Plain words.", "no-such-brand", "person", "linkedin", topic)]
        for call in calls:
            with self.assertRaises(BrandError):
                call()

    def test_an_unknown_identity_raises_everywhere(self):
        topic = self.approved()
        calls = [lambda: plan.plan_week(self.brand, "doctor"),
                 lambda: plan.plan_topic(topic, self.brand, "doctor", "reach"),
                 lambda: dedup.similar_posts("Plain words.", self.brand, identity="doctor"),
                 lambda: dedup.record_post(self.brand, "p1", "linkedin", "doctor", "Plain words."),
                 lambda: dedup.candidates(self.brand, "doctor"),
                 lambda: contract.build_contract(self.brand, "doctor", "linkedin", topic, "three-tips", "reach"),
                 lambda: contract.validate_draft("Plain words.", self.brand, "doctor", "linkedin", topic)]
        for call in calls:
            with self.assertRaises(BrandError) as cm:
                call()
            self.assertIn("person", str(cm.exception))            # it says who the brand does have


# =============================================================================== platform rules
class TestPlatformRules(WritingCase):
    def test_loads_every_platform_and_the_rules_that_hold_everywhere(self):
        rules = platforms.load()
        self.assertEqual(rules.platforms, ["facebook", "instagram", "linkedin", "twitter"])
        self.assertEqual(rules.get("twitter")["max_len"], 280)
        self.assertEqual(rules.universal_rules, ["One post, one idea."])
        self.assertFalse(rules.is_stale())
        self.assertIsNone(rules.warning())
        self.assertEqual(rules.age_days(), 10)

    def test_old_rules_are_a_warning_the_caller_can_show_not_a_refusal(self):
        self.write_rules("2026-01-01")
        rules = platforms.load()
        today = date(2026, 9, 1)
        self.assertEqual(rules.age_days(today), 243)
        self.assertTrue(rules.is_stale(today))
        self.assertIn("243 days old", rules.warning(today))
        self.assertIn("refresh the playbooks", rules.warning(today))
        self.assertEqual(rules.get("linkedin")["max_len"], 3000)             # and it still works
        self.assertTrue(platforms.is_stale(today=today))
        self.assertEqual(platforms.age_days(today=today), 243)

    def test_exactly_at_the_limit_is_still_fresh(self):
        self.write_rules("2026-01-01")
        rules = platforms.load()
        self.assertFalse(rules.is_stale(date(2026, 1, 1) + timedelta(days=platforms.MAX_AGE_DAYS)))
        self.assertTrue(rules.is_stale(date(2026, 1, 1) + timedelta(days=platforms.MAX_AGE_DAYS + 1)))

    def test_rules_with_no_date_or_a_garbled_date_count_as_stale(self):
        for bad in (None, "last spring"):
            self.write_rules(bad)
            rules = platforms.load()
            self.assertIsNone(rules.age_days())
            self.assertTrue(rules.is_stale())
            self.assertIn("no date", rules.warning())

    def test_a_missing_file_is_a_plain_error_that_names_it(self):
        os.remove(os.path.join(self.tmp.name, "playbooks", "profiles.json"))
        with self.assertRaises(platforms.PlatformRulesError) as cm:
            platforms.load()
        self.assertIn("playbooks/profiles.json", str(cm.exception))
        self.assertNotIn(self.tmp.name, str(cm.exception))                   # no absolute path in a message

    def test_a_damaged_file_says_so(self):
        Path(self.tmp.name, "playbooks", "profiles.json").write_text("{ not json", encoding="utf-8")
        with self.assertRaises(StudioError) as cm:
            platforms.load()
        self.assertIn("damaged", str(cm.exception))

    def test_a_platform_without_a_rulebook(self):
        rules = platforms.load()
        with self.assertRaises(platforms.PlatformRulesError) as cm:
            rules.get("tiktok")
        self.assertIn("linkedin", str(cm.exception))
        fallback = rules.mechanics_for("tiktok")
        self.assertFalse(fallback["known"])
        self.assertEqual(fallback["max_len"], 2200)


# =============================================================================== topics
class TestPlanningInputsComeFromTheBrand(WritingCase):
    def test_gathers_pillars_audience_offers_and_the_brands_own_files(self):
        Path(self.brand.path("Brand", "audience.md")).write_text(
            "# Maple & Main Bakery: who we talk to\n\n## Questions they really ask\n"
            "Can I freeze sourdough?\nWhat flour do you use?\n", encoding="utf-8")
        Path(self.brand.path("Inputs", "Questions", "from the counter's notebook.txt")).write_text(
            "Do you sell starter?\n", encoding="utf-8")
        got = topics.planning_inputs(self.brand)
        self.assertEqual([p["id"] for p in got["pillars"]], ["sourdough-at-home", "behind-the-counter"])
        self.assertIn("Why is my loaf flat?", got["audience"]["questions_they_ask"])
        self.assertEqual([o["id"] for o in got["offers"]], ["weekend-class", "bread-club"])
        files = {m["file"]: m["text"] for m in got["material"]}
        self.assertIn("Can I freeze sourdough?", files["Brand/audience.md"])
        self.assertIn("Do you sell starter?", files["Inputs/Questions/from the counter's notebook.txt"])
        self.assertIn("Propose topics only from", got["rule"])

    def test_untouched_templates_are_not_material(self):
        got = topics.planning_inputs(self.brand)
        self.assertEqual(got["material"], [])                       # every Brand/ file is still the blank template
        self.assertTrue(any("blank templates" in g for g in got["gaps"]))

    def test_own_lines_strips_headings_guidance_and_table_rules(self):
        text = Path(self.brand.path("Brand", "business-profile.md")).read_text(encoding="utf-8")
        self.assertEqual(own_lines(self.brand, "Brand/business-profile.md", text), [])
        text += "\n| We open at seven | The sign on the door |\n"
        self.assertEqual(own_lines(self.brand, "Brand/business-profile.md", text),
                         ["| We open at seven | The sign on the door |"])

    def test_the_brief_is_readable_and_gives_every_item_a_pointer(self):
        brief = topics.planning_brief(self.brand)
        self.assertIn("pillar:sourdough-at-home", brief)
        self.assertIn("audience.questions_they_ask[1]  Why is my loaf flat?", brief)
        self.assertIn("offer:weekend-class", brief)

    def test_an_empty_brand_gets_gaps_not_invented_subjects(self):
        blank = brands.create("blank-brand", "Blank Brand")
        got = topics.planning_inputs(blank)
        self.assertEqual((got["pillars"], got["offers"], got["material"], got["existing_topics"]), ([], [], [], []))
        self.assertGreaterEqual(len(got["gaps"]), 4)


class TestTopicDecisions(WritingCase):
    def test_round_trip_and_unique_ids(self):
        a = topics.new_topic("Why a loaf comes out flat", source_ref="audience.questions_they_ask[1]")
        b = topics.new_topic("Why a loaf comes out flat", source_ref="a customer asked at the counter on Friday")
        added, warnings = topics.add_topics(self.brand, "week 1 run", [a, b])
        self.assertEqual(added, ["why-a-loaf-comes-out-flat", "why-a-loaf-comes-out-flat-2"])
        self.assertEqual(warnings, [])
        self.assertEqual([t["source_ref"] for t in topics.load_run(self.brand, "week 1 run")],
                         ["audience.questions_they_ask[1]", "a customer asked at the counter on Friday"])
        self.assertEqual(topics.load_run(self.brand, "week 2 run"), [])      # a different run is a different file
        self.assertEqual(topics.list_runs(self.brand), ["week 1 run"])

    def test_run_names_with_an_apostrophe_are_refused_and_so_is_a_path(self):
        for bad in ("week 1's run", "../escape", "a/b", "..", "", "x" * 80):
            with self.assertRaises(topics.TopicError):
                topics.run_path(self.brand, bad)
        self.assertTrue(topics.run_path(self.brand, "week of june 9").endswith("topics.json"))

    def test_approving_a_topic_with_no_source_is_refused(self):
        topics.add_topics(self.brand, "week-1", [topics.new_topic("Rye for beginners")])
        with self.assertRaises(topics.TopicError) as cm:
            topics.set_status(self.brand, "week-1", "rye-for-beginners", "approved")
        self.assertIn("where in Maple & Main Bakery's own material", str(cm.exception))
        self.assertEqual(topics.load_run(self.brand, "week-1")[0]["status"], "proposed")     # nothing changed
        topic, _w = topics.set_status(self.brand, "week-1", "rye-for-beginners", "approved", source_ref="pillar:sourdough-at-home")
        self.assertEqual(topic["status"], "approved")

    def test_a_hand_edited_file_with_an_unsourced_approval_is_caught_before_writing(self):
        topics.add_topics(self.brand, "week-1", [topics.new_topic("Rye for beginners")])
        path = topics.run_path(self.brand, "week-1")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["topics"][0]["status"] = "approved"
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(topics.TopicError):
            topics.approved_topics(self.brand, "week-1")
        with self.assertRaises(topics.TopicError):
            topics.save_run(self.brand, "week-1", data["topics"])
        with self.assertRaises(topics.TopicError):
            plan.plan_run(self.brand, "week-1", "person")

    def test_only_approved_topics_come_out(self):
        rows = [self.approved("One"), topics.new_topic("Two", source_ref="pillar:behind-the-counter"),
                topics.new_topic("Three", source_ref="x", status="cut")]
        topics.save_run(self.brand, "week-1", rows)
        self.assertEqual([t["title"] for t in topics.approved_topics(self.brand, "week-1")], ["One"])

    def test_pointers_are_checked_and_free_text_is_allowed(self):
        self.add_proof(self.brand, "PRF-0001", "240 people taught since 2021")
        self.facts()
        ok = ["audience.questions_they_ask[1]", "audience.problems[0]", "pillar:sourdough-at-home", "offer:bread-club",
              "proof:PRF-0001", "fact:fact-1", "Brand/audience.md#Questions", "a call with a customer on 3 June"]
        for ref in ok:
            self.assertTrue(topics.resolve_source_ref(self.brand, ref)["ok"], ref)
        bad = ["audience.questions_they_ask[9]", "pillar:croissants", "offer:nope", "proof:PRF-0099", "fact:nope",
               "Brand/missing.md", "../../secrets.txt", "Inputs/Questions/../../../x.md"]
        for ref in bad:
            self.assertFalse(topics.resolve_source_ref(self.brand, ref)["ok"], ref)
        _problems, warnings = topics.check_topics(self.brand, [self.approved(source_ref="pillar:croissants")])
        self.assertTrue(any("croissants" in w for w in warnings))   # a warning; the person may know better

    def test_bad_status_lane_and_duplicate_ids_stop_a_save(self):
        rows = [topics.new_topic("One", source_ref="x", status="maybe"), topics.new_topic("One", source_ref="x", lane="viral")]
        problems, _w = topics.check_topics(self.brand, rows)
        self.assertEqual(len(problems), 3)                                  # the status, the lane, the shared id
        with self.assertRaises(topics.TopicError):
            topics.save_bank(self.brand, rows)

    def test_topics_written_for_another_brand_are_refused(self):
        clinic = self.clinic()
        topics.save_run(clinic, "week-1", [topics.new_topic("Runner's knee", source_ref="a note")])
        target = topics.run_path(self.brand, "week-1")
        os.makedirs(os.path.dirname(target))
        Path(target).write_text(Path(topics.run_path(clinic, "week-1")).read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(topics.TopicError) as cm:
            topics.load_run(self.brand, "week-1")
        self.assertIn("belong to stride-physio", str(cm.exception))

    def test_the_bank_keeps_ideas_across_runs_and_no_temp_files_are_left(self):
        kept = topics.keep_in_bank(self.brand, [topics.new_topic("Rye for beginners", source_ref="pillar:sourdough-at-home")])
        self.assertEqual(kept, ["rye-for-beginners"])
        self.assertEqual(topics.keep_in_bank(self.brand, [topics.new_topic("Rye for beginners")]), [])
        self.assertEqual([t["title"] for t in topics.planning_inputs(self.brand)["existing_topics"]], ["Rye for beginners"])
        self.assertEqual([f for f in os.listdir(self.brand.path("Studio")) if f.startswith(".tmp-")], [])

    def test_a_title_in_any_alphabet_still_gets_an_id(self):
        self.assertEqual(topics.slug("Crème brûlée, s'il vous plaît!"), "creme-brulee-s-il-vous-plait")
        self.assertEqual(topics.slug("!!!"), "topic")


# =============================================================================== the planner
class TestJobs(WritingCase):
    def test_ten_posts_are_four_reach_three_lead_gen_three_trust(self):
        jobs = plan.job_sequence(10)
        self.assertEqual({j: jobs.count(j) for j in set(jobs)}, {"reach": 4, "lead_gen": 3, "trust": 3})
        warm = plan.job_sequence(10, warmed=True)
        self.assertEqual({j: warm.count(j) for j in set(warm)}, {"reach": 3, "lead_gen": 4, "trust": 3})

    def test_never_three_lead_gen_in_a_row_at_any_size(self):
        for warmed in (False, True):
            for count in range(1, 121):
                jobs = plan.job_sequence(count, warmed=warmed)
                self.assertEqual(len(jobs), count)
                run = 0
                for j in jobs:
                    run = run + 1 if j == "lead_gen" else 0
                    self.assertLessEqual(run, 2, "count=%d warmed=%s" % (count, warmed))

    def test_a_silly_count_is_a_plain_error(self):
        for bad in (0, -3, 1000, "ten", True):
            with self.assertRaises(plan.PlanError):
                plan.job_sequence(bad)

    def test_same_input_same_plan(self):
        self.assertEqual(plan.plan_week(self.brand, "person", count=10), plan.plan_week(self.brand, "person", count=10))


class TestPlanWeek(WritingCase):
    def test_every_slot_has_a_job_an_opening_a_template_a_visual_and_an_ending(self):
        slots = plan.plan_week(self.brand, "person", count=10)
        self.assertEqual(len(slots), 10)
        for s in slots:
            self.assertIn(s["job"], plan.JOBS)
            self.assertEqual(next(h for h in plan.HOOK_FAMILIES if h["id"] == s["hook_family"]["id"])["job"], s["job"])
            self.assertEqual(next(t for t in plan.TEMPLATES if t["id"] == s["template"]["id"])["job"], s["job"])
            self.assertIn(s["job"], next(f for f in plan.VISUAL_FORMATS if f["id"] == s["visual_format"]["id"])["jobs"])
            self.assertEqual(s["platforms"], ["linkedin", "instagram", "facebook", "twitter"])
        self.assertEqual(plan.check_plan(slots), [])

    def test_offers_only_ever_land_on_lead_gen_slots_and_they_rotate(self):
        slots = plan.plan_week(self.brand, "person", count=10)
        for s in slots:
            if s["job"] == "lead_gen":
                self.assertEqual(s["cta_kind"], "offer")
                self.assertIn(s["cta_text"], [o["call_to_action"] for o in BAKERY_DETAIL["offers"]])
            else:
                self.assertIn(s["cta_kind"], ("reach", "soft", "none"))
        self.assertEqual([s["cta_id"] for s in slots if s["job"] == "lead_gen"],
                         ["offer-weekend-class", "offer-bread-club", "offer-weekend-class"])
        self.assertEqual([s["cta_id"] for s in slots if s["job"] == "reach"], ["save", "share", "follow", "save"])
        self.assertEqual([s["cta_id"] for s in slots if s["job"] == "trust"], ["soft", "none", "soft"])

    def test_the_visuals_span_polished_to_raw_and_the_topical_format_appears_once_at_most(self):
        for count in (2, 3, 5, 10, 24):
            slots = plan.plan_week(self.brand, "person", count=count)
            tiers = {s["visual_format"]["tier"] for s in slots}
            self.assertTrue({"polished", "raw"} <= tiers, count)
            self.assertLessEqual(sum(1 for s in slots if s["visual_format"]["id"] == "topical"), 1)
            looks = [s["visual_format"]["id"] for s in slots]
            self.assertFalse(any(a == b for a, b in zip(looks, looks[1:])), looks)     # never the same look twice running

    def test_the_brands_own_choice_of_formats_is_respected(self):
        self.brand.data["visual"]["formats_enabled"] = ["carousel", "bold-text", "brand-card"]
        used = {s["visual_format"]["id"] for s in plan.plan_week(self.brand, "person", count=10)}
        self.assertTrue(used <= {"carousel", "bold-text", "brand-card"}, used)

    def test_platforms_come_from_the_brand_per_identity(self):
        self.assertEqual(plan.plan_week(self.brand, "company", count=1)[0]["platforms"], ["linkedin", "instagram", "facebook"])
        self.assertEqual(plan.plan_week(self.brand, "person", count=1, platforms=["Twitter", "linkedin"])[0]["platforms"],
                         ["twitter", "linkedin"])
        with self.assertRaises(plan.PlanError) as cm:
            plan.plan_week(self.brand, "company", count=1, platforms=["twitter"])
        self.assertIn("does not post on twitter as 'company'", str(cm.exception))

    def test_topics_bind_one_per_slot_in_order(self):
        rows = [self.approved("One"), self.approved("Two"), self.approved("Three")]
        slots = plan.plan_week(self.brand, "person", topics=rows)
        self.assertEqual([s["topic_title"] for s in slots], ["One", "Two", "Three"])
        more = plan.plan_week(self.brand, "person", count=5, topics=rows)
        self.assertEqual([s["topic_title"] for s in more][3:], [None, None])


class TestPlanTopic(WritingCase):
    def shapes_of(self, record, identity="person"):
        return {p: v["shape"] for p, v in record["plans"][identity]["platform_shapes"].items()}

    def test_a_topic_gets_a_different_shape_on_every_platform(self):
        for job in plan.JOBS:
            shapes = self.shapes_of(plan.plan_topic(self.approved(), self.brand, "person", job))
            self.assertEqual(sorted(shapes), ["facebook", "instagram", "linkedin", "twitter"])
            self.assertEqual(len(set(shapes.values())), 4, shapes)

    def test_nothing_on_the_record_is_lost(self):
        topic = self.approved(proof_ids=["PRF-0001"], note="Ava wants this one first", pillar="sourdough-at-home")
        record = plan.plan_topic(topic, self.brand, "person", "trust")
        for key in ("topic_id", "title", "status", "lane", "pillar", "source_ref", "proof_ids", "note"):
            self.assertEqual(record[key], topic[key])
        self.assertEqual(record["plans"]["person"]["job"], "trust")
        self.assertNotIn("plans", topic)                                    # the caller's record is not changed

    def test_a_shape_chosen_by_a_person_is_kept(self):
        topic = self.approved(platform_shapes={"linkedin": "five-questions"})
        shapes = self.shapes_of(plan.plan_topic(topic, self.brand, "person", "reach"))
        self.assertEqual(shapes["linkedin"], "five-questions")
        self.assertEqual(len(set(shapes.values())), 4)
        with self.assertRaises(plan.PlanError):
            plan.plan_topic(self.approved(platform_shapes={"linkedin": "haiku"}), self.brand, "person", "reach")

    def test_a_person_only_shape_is_never_given_to_a_company(self):
        for job in plan.JOBS:
            shapes = self.shapes_of(plan.plan_topic(self.approved(), self.brand, "company", job), "company")
            self.assertNotIn("before-after-story", shapes.values())

    def test_a_second_identity_avoids_the_first_ones_shapes(self):
        """Where a shape that suits the platform is still free. Fit to the platform comes first."""
        alone = self.shapes_of(plan.plan_topic(self.approved(), self.brand, "company", "reach"), "company")
        first = plan.plan_topic(self.approved(), self.brand, "person", "reach")
        both = plan.plan_topic(first, self.brand, "company", "reach")
        self.assertEqual(set(both["plans"]), {"person", "company"})
        person, company = self.shapes_of(both, "person"), self.shapes_of(both, "company")
        self.assertLess(len(set(company.values()) & set(person.values())), len(set(alone.values()) & set(person.values())))
        for p in ("linkedin", "facebook"):                                   # plenty of shapes suit these two
            self.assertNotIn(company[p], person.values())

    def test_the_playbooks_shape_index_is_used_when_it_is_there(self):
        index = {"shapes": [{"id": "counter-note", "name": "A note from the counter", "best_for": ["linkedin"],
                             "length": "short", "identity": "any", "when": "One thing seen today."},
                            {"id": "recipe-card", "name": "Recipe card", "best_for": ["instagram"], "length": "short",
                             "identity": "any", "when": "A method in steps."}]}
        path = Path(self.tmp.name, "playbooks", "shapes", "index.json")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(index), encoding="utf-8")
        self.assertEqual(plan.load_shapes()[1], "playbooks/shapes/index.json")
        record = plan.plan_topic(self.approved(), self.brand, "person", "reach", platforms=["linkedin", "instagram"])
        self.assertEqual(self.shapes_of(record), {"linkedin": "counter-note", "instagram": "recipe-card"})
        four = plan.plan_topic(self.approved(), self.brand, "person", "reach")      # two shapes, four platforms
        self.assertEqual(len(four["plans"]["person"]["shape_repeats"]), 2)           # it says so rather than hiding it

    def test_a_missing_or_broken_index_falls_back_to_the_built_in_shapes(self):
        self.assertEqual(plan.load_shapes()[1], "built-in list")
        path = Path(self.tmp.name, "playbooks", "shapes", "index.json")
        path.parent.mkdir(parents=True)
        path.write_text("{ nope", encoding="utf-8")
        shapes, source = plan.load_shapes()
        self.assertEqual(source, "built-in list")
        self.assertEqual([s["id"] for s in shapes], ["three-tips", "myth-vs-reality", "problem-agitate-solve",
                                                     "three-objections", "five-lessons", "bullet-insight",
                                                     "five-questions", "before-after-story"])

    def test_plan_run_plans_the_approved_topics_and_saves_them(self):
        rows = [self.approved("One"), self.approved("Two"), topics.new_topic("Three", source_ref="x")]
        topics.save_run(self.brand, "week-1", rows)
        result = plan.plan_run(self.brand, "week-1", "person")
        self.assertEqual([s["topic_title"] for s in result["slots"]], ["One", "Two"])
        saved = {t["title"]: t for t in topics.load_run(self.brand, "week-1")}
        self.assertIn("person", saved["One"]["plans"])
        self.assertNotIn("plans", saved["Three"])                          # not approved, not planned
        self.assertTrue(os.path.isfile(self.brand.path("Studio", "runs", "week-1", "plan-person.json")))
        with self.assertRaises(plan.PlanError):
            plan.plan_run(self.brand, "an-empty-run", "person")


# =============================================================================== calls to action
class TestCallsToAction(WritingCase):
    def test_the_library_is_seeded_from_the_brands_offers_in_its_own_words(self):
        lib = cta.load_library(self.brand)
        self.assertFalse(lib["saved"])                                     # reading never writes
        self.assertEqual([c["text"] for c in lib["ctas"]], [o["call_to_action"] for o in BAKERY_DETAIL["offers"]])
        report = cta.seed_library(self.brand)
        self.assertEqual(report["added"], ["offer-weekend-class", "offer-bread-club"])
        self.assertTrue(cta.load_library(self.brand)["saved"])

    def test_seeding_again_keeps_hand_edits_adds_new_offers_and_switches_off_removed_ones(self):
        cta.seed_library(self.brand)
        path = cta.library_path(self.brand)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["ctas"][0]["text"] = "Saturday class. Ask at the counter."
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        self.brand.data["offers"] = [self.brand.data["offers"][0],
                                     {"id": "rye-day", "name": "Rye Day", "call_to_action": "Order a rye loaf for Thursday."}]
        report = cta.seed_library(self.brand)
        self.assertEqual((report["added"], report["switched_off"]), (["offer-rye-day"], ["offer-bread-club"]))
        entries = {c["id"]: c for c in cta.load_library(self.brand)["ctas"]}
        self.assertEqual(entries["offer-weekend-class"]["text"], "Saturday class. Ask at the counter.")
        self.assertFalse(entries["offer-bread-club"]["active"])

    def test_a_brand_with_no_offers_gets_a_soft_close_and_is_told_why(self):
        blank = brands.create("blank-brand", "Blank Brand")
        choice = cta.select_cta(blank, "lead_gen", "linkedin", {})
        self.assertEqual((choice["cta_id"], choice["kind"], choice["text"]), (None, "none", None))
        self.assertIn("Add an offer", choice["note"])

    def test_a_keyword_is_only_used_once_the_brand_says_its_reply_is_set_up(self):
        lib = {"ctas": [{"id": "kw-starter", "kind": "keyword", "keyword": "STARTER", "delivers": "the feeding card",
                         "text": "Comment STARTER and I will send you our feeding card.", "platforms": ["instagram"],
                         "active": True, "ready": False}]}
        self.assertEqual(cta.select_cta(self.brand, "lead_gen", "instagram", {}, library=lib)["kind"], "none")
        lib["ctas"][0]["ready"] = True
        self.assertEqual(cta.select_cta(self.brand, "lead_gen", "instagram", {}, library=lib)["keyword"], "STARTER")
        self.assertEqual(cta.select_cta(self.brand, "lead_gen", "linkedin", {}, library=lib)["kind"], "none")   # wrong platform
        for job in ("reach", "trust"):
            for _ in range(6):
                self.assertNotIn(cta.select_cta(self.brand, job, "instagram", {}, library=lib)["kind"], ("keyword", "offer"))

    def test_the_brands_own_wording_for_a_save_wins_over_the_instruction(self):
        lib = {"ctas": [{"id": "save", "kind": "reach", "text": "Save this for bake day."}]}
        self.assertEqual(cta.select_cta(self.brand, "reach", "instagram", {}, library=lib)["text"], "Save this for bake day.")
        self.assertIsNone(cta.select_cta(self.brand, "reach", "instagram", {})["text"])

    def test_an_unknown_job_is_an_error(self):
        with self.assertRaises(cta.CtaError):
            cta.select_cta(self.brand, "viral", "linkedin", {})

    def test_a_library_that_belongs_to_another_brand_is_refused(self):
        Path(cta.library_path(self.brand)).write_text(json.dumps({"brand": "stride-physio", "ctas": []}), encoding="utf-8")
        with self.assertRaises(cta.CtaError) as cm:
            cta.load_library(self.brand)
        self.assertIn("belongs to stride-physio", str(cm.exception))

    def test_a_draft_may_not_invent_a_keyword_or_sell_on_a_reach_post(self):
        self.assertTrue(cta.check_cta("Tell me what you bake. Comment below.", self.brand, "instagram", job="reach")["valid"])
        invented = cta.check_cta("Comment LOAF and I will send the recipe.", self.brand, "instagram", job="lead_gen")
        self.assertFalse(invented["valid"])
        self.assertIn("LOAF", invented["issues"][0])
        selling = cta.check_cta("Good bread takes time. Book a Saturday class at the counter or on our website.",
                                self.brand, "linkedin", job="reach")
        self.assertEqual(selling["offers_found"], ["offer-weekend-class"])
        self.assertIn("should not end on an offer", selling["issues"][0])
        self.assertTrue(cta.check_cta("Book a Saturday class at the counter or on our website.", self.brand, "linkedin",
                                      job="lead_gen")["valid"])


# =============================================================================== grounding
class TestNumbersInText(unittest.TestCase):
    def values(self, text):
        return [(n["raw"], n["value"], n["structural"]) for n in grounding.extract_numbers(text)]

    def test_the_ways_people_write_numbers(self):
        self.assertEqual(self.values("4,420 views, 4.4K saves, 0.6 seconds, $1,200, 35% and position 35."),
                         [("4,420", 4420.0, False), ("4.4K", 4400.0, False), ("0.6", 0.6, False),
                          ("$1,200", 1200.0, False), ("35", 35.0, False), ("35", 35.0, False)])
        self.assertEqual(self.values("We open at 7am on the 1st."), [])     # not free-standing numbers

    def test_list_markers_labels_and_counts_of_the_posts_own_parts_are_structure(self):
        text = "3 checks before bake day.\n1. Flour weight.\n2) Water.\nStep 3: wait 18 hours."
        self.assertEqual(self.values(text), [("3", 3.0, True), ("1", 1.0, True), ("2", 2.0, True), ("3", 3.0, True),
                                             ("18", 18.0, False)])

    def test_a_ranking_claim_and_a_count_of_real_things_are_not_structure(self):
        self.assertEqual(self.values("We are #1 for rye."), [("1", 1.0, False)])
        self.assertEqual(self.values("We run 3 shops."), [("3", 3.0, False)])


class TestGrounding(WritingCase):
    def test_an_empty_brand_with_no_numbers_is_fine(self):
        blank = brands.create("blank-brand", "Blank Brand")
        report = grounding.ground_draft("Bread rewards patience.\n1. Mix.\n2. Wait.", blank)
        self.assertTrue(report["ok"])
        self.assertEqual((report["ungrounded"], report["corpus_size"]), ([], 0))

    def test_an_empty_brand_with_numbers_is_told_how_to_add_a_fact(self):
        blank = brands.create("blank-brand", "Blank Brand")
        report = grounding.ground_draft("We have baked for 12 years and sold 5,000 loaves.", blank)
        self.assertFalse(report["ok"])
        self.assertEqual(report["ungrounded"], ["12", "5,000"])
        self.assertIn("Blank Brand has no facts, research stats or linked proof yet", report["explanation"])
        self.assertIn("add a fact", report["explanation"])
        self.assertIn("Studio/facts.json", report["explanation"])

    def test_a_missing_library_file_is_the_same_as_an_empty_one(self):
        os.remove(self.brand.path("Studio", "registry.db"))
        self.assertEqual(grounding.list_proof(self.brand), [])
        self.assertTrue(grounding.ground_draft("No numbers here.", self.brand)["ok"])
        self.assertFalse(os.path.exists(self.brand.path("Studio", "registry.db")))      # reading never creates it

    def test_numbers_trace_to_the_brands_facts_and_say_where_they_came_from(self):
        self.facts()
        report = grounding.ground_draft("We proof for 18 hours. 240 people have learned with us since 2021.", self.brand)
        self.assertTrue(report["ok"], report)
        first = report["numbers"][0]["provenance"][0]
        self.assertEqual((first["kind"], first["source"], first["ref"]), ("brand_fact", "Ava's recipe card", "fact-1"))
        self.assertEqual(report["sources_used"], ["Ava's recipe card", "class sign-up sheets"])

    def test_an_invented_number_is_caught_even_beside_real_ones(self):
        self.facts()
        report = grounding.ground_draft("We proof for 18 hours and have 9,000 regulars.", self.brand)
        self.assertFalse(report["ok"])
        self.assertEqual(report["ungrounded"], ["9,000"])

    def test_a_fact_without_a_source_backs_nothing(self):
        Path(grounding.facts_path(self.brand)).write_text(json.dumps({"facts": [
            {"id": "f1", "claim": "We sell 300 loaves a day."}, {"id": "f2", "source": "nobody"}]}), encoding="utf-8")
        report = grounding.ground_draft("We sell 300 loaves a day.", self.brand)
        self.assertEqual(report["ungrounded"], ["300"])
        self.assertTrue(any("has no source" in n for n in report["notes"]))
        with self.assertRaises(grounding.GroundingError):
            grounding.add_fact(self.brand, "We sell 300 loaves a day.", "")

    def test_an_explicit_value_counts_as_well_as_the_words(self):
        grounding.add_fact(self.brand, "We have taught two hundred and forty people.", "class sign-up sheets", values=240)
        self.assertTrue(grounding.ground_draft("240 people have baked with us.", self.brand)["ok"])

    def test_the_facts_file_may_state_values_as_text_numbers_a_list_or_a_single_value(self):
        Path(grounding.facts_path(self.brand)).write_text(json.dumps({"_meta": {"what": "kept"}, "facts": [
            {"id": "class-size", "claim": "A class takes eight people and lasts four hours", "values": ["8", "4"],
             "source": "the booking page"},
            {"id": "ovens", "claim": "We run two deck ovens", "value": 2, "source": "the kitchen"},
            {"id": "sales", "claim": "We sold 1,200 loaves in May", "values": [True], "source": "the till"}]}),
            encoding="utf-8")
        self.assertTrue(grounding.ground_draft("8 people, 4 hours, 2 ovens, 1,200 loaves.", self.brand)["ok"])
        grounding.add_fact(self.brand, "We open at 7:30", "the sign on the door")
        saved = json.loads(Path(grounding.facts_path(self.brand)).read_text(encoding="utf-8"))
        self.assertEqual(saved["_meta"], {"what": "kept"})                  # what was already there is untouched
        self.assertEqual(saved["facts"][-1]["values"], ["7", "30"])

    def test_research_files_with_different_headings_all_work_and_give_credit(self):
        folder = Path(self.brand.path("Inputs", "Research", "home baking's stats é"))
        folder.mkdir(parents=True)
        (folder / "survey.csv").write_text(
            "Finding,Source,URL,Confidence\n"
            "\"41% of home bakers say their first loaf failed\",Invented Home Baking Survey,https://example.org/survey,high\n",
            encoding="utf-8")
        (folder / "notes.csv").write_text("Link,Key stat,Who says so\nhttps://example.org/b,Starters peak after 6 hours,"
                                          "Example Flour Board\n", encoding="utf-8")
        (folder / "no headings.csv").write_text("a,b\nx,A long sentence saying 72 percent of loaves are under-proofed\n",
                                                encoding="utf-8")
        report = grounding.ground_draft("41% of first loaves fail. Starters peak after 6 hours. 72 percent are under-proofed.",
                                        self.brand)
        self.assertTrue(report["ok"], report["ungrounded"])
        self.assertEqual(report["attributions"][0],
                         "Invented Home Baking Survey (high confidence): 41% of home bakers say their first loaf failed")
        by_raw = {n["raw"]: n["provenance"][0] for n in report["numbers"]}
        self.assertEqual(by_raw["41"]["url"], "https://example.org/survey")
        self.assertEqual((by_raw["6"]["source"], by_raw["6"]["url"]), ("Example Flour Board", "https://example.org/b"))
        self.assertEqual(by_raw["72"]["source"], "Inputs/Research/home baking's stats é/no headings.csv")

    def test_a_spreadsheet_saved_on_windows_and_a_broken_file_do_not_stop_the_run(self):
        folder = Path(self.brand.path("Inputs", "Research"))
        (folder / "windows.csv").write_bytes("Finding,Source\n\"Caf\xe9 owners bake 55 loaves\",Invented Trade Note\n".encode("cp1252"))
        (folder / "broken.csv").write_bytes(b"\x00\x01\x02,\"unclosed\n\x00")
        report = grounding.ground_draft("Owners bake 55 loaves.", self.brand)
        self.assertTrue(report["ok"], report)

    def test_only_linked_proof_counts_and_unlinked_proof_gets_a_hint(self):
        self.add_proof(self.brand, "PRF-0001", "Class of 27 sold out in a day", "Every one of the 27 places went in 24 hours.")
        unlinked = grounding.ground_draft("All 27 places went.", self.brand)
        self.assertEqual(unlinked["ungrounded"], ["27"])
        self.assertIn("PRF-0001", unlinked["hints"][0])
        linked = grounding.ground_draft("All 27 places went.", self.brand, proof_ids=["PRF-0001"])
        self.assertTrue(linked["ok"])
        self.assertEqual(linked["numbers"][0]["provenance"][0]["ref"], "PRF-0001")

    def test_linking_proof_that_does_not_exist_is_never_ok(self):
        report = grounding.ground_draft("No numbers at all.", self.brand, proof_ids=["PRF-0404"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["unknown_proof_ids"], ["PRF-0404"])

    def test_one_brands_facts_never_back_another_brands_draft(self):
        self.facts()
        clinic = self.clinic()
        self.assertEqual(grounding.ground_draft("We proof for 18 hours.", clinic)["ungrounded"], ["18"])


# =============================================================================== the library of written posts
class TestHasThisBeenSaid(WritingCase):
    TEXT = "We proof the dough for eighteen hours and that is why the crust cracks when you press it gently."

    def test_an_empty_library_has_nothing_to_compare(self):
        result = dedup.similar_posts(self.TEXT, self.brand, identity="person")
        self.assertEqual((result.is_duplicate, result.exempt, result.matches, result.compared), (False, False, [], 0))
        self.assertEqual(dedup.candidates(self.brand, "person"), [])
        self.assertFalse(dedup.on_cooldown(self.brand, "t1", "three-tips"))

    def test_a_missing_file_a_missing_table_and_a_file_that_is_not_a_database_are_all_just_empty(self):
        db = self.brand.path("Studio", "registry.db")
        con = sqlite3.connect(db)
        con.execute("DROP TABLE posts_written")
        con.commit()
        con.close()
        self.assertEqual(dedup.similar_posts(self.TEXT, self.brand).matches, [])
        Path(db).write_text("this is not a database", encoding="utf-8")
        self.assertEqual(dedup.similar_posts(self.TEXT, self.brand).matches, [])
        os.remove(db)
        self.assertEqual(dedup.similar_posts(self.TEXT, self.brand).matches, [])
        self.assertFalse(os.path.exists(db))                               # a read never creates the file

    def test_recording_creates_the_library_when_it_is_missing(self):
        os.remove(self.brand.path("Studio", "registry.db"))
        dedup.record_post(self.brand, "w1-li-01", "linkedin", "person", self.TEXT, topic_id="crust", shape="three-tips")
        self.assertEqual([r["post_id"] for r in dedup.written_posts(self.brand)], ["w1-li-01"])

    def test_a_near_copy_is_caught_and_a_fresh_post_is_not(self):
        dedup.record_post(self.brand, "w1-li-01", "linkedin", "person", self.TEXT)
        again = dedup.similar_posts(self.TEXT.replace("gently", "softly"), self.brand, identity="person")
        self.assertTrue(again.is_duplicate)
        self.assertEqual(again.matches[0]["post_id"], "w1-li-01")
        self.assertGreater(again.matches[0]["similarity"], 0.6)
        fresh = dedup.similar_posts("Rye wants a wetter dough than wheat, so add water a spoon at a time.", self.brand,
                                    identity="person")
        self.assertFalse(fresh.is_duplicate)

    def test_punctuation_and_capitals_do_not_hide_a_copy(self):
        dedup.record_post(self.brand, "w1-li-01", "linkedin", "person", self.TEXT)
        self.assertTrue(dedup.similar_posts(self.TEXT.upper().replace(" AND", ", AND"), self.brand, identity="person").is_duplicate)

    def test_the_same_words_under_the_brands_other_identity_is_a_mirror_only_when_we_know_who_is_posting(self):
        dedup.record_post(self.brand, "w1-li-01", "linkedin", "person", self.TEXT)
        mirror = dedup.similar_posts(self.TEXT, self.brand, identity="company")
        self.assertEqual((mirror.is_duplicate, mirror.exempt), (False, True))
        unknown = dedup.similar_posts(self.TEXT, self.brand)
        self.assertEqual((unknown.is_duplicate, unknown.exempt), (True, False))

    def test_checking_a_post_against_itself_is_not_a_repeat(self):
        dedup.record_post(self.brand, "w1-li-01", "linkedin", "person", self.TEXT)
        self.assertFalse(dedup.similar_posts(self.TEXT, self.brand, identity="person", exclude_ids=["w1-li-01"]).is_duplicate)

    def test_two_brands_never_see_each_others_posts(self):
        clinic = self.clinic()
        dedup.record_post(self.brand, "w1-li-01", "linkedin", "person", self.TEXT, topic_id="crust", shape="three-tips")
        dedup.mark_used(self.brand, "w1-li-01")
        self.assertEqual(dedup.similar_posts(self.TEXT, clinic, identity="person").matches, [])
        self.assertEqual(dedup.written_posts(clinic), [])
        self.assertEqual(dedup.candidates(clinic, "person"), [])
        self.assertFalse(dedup.on_cooldown(clinic, "crust", "three-tips"))
        self.assertFalse(dedup.mark_used(clinic, "w1-li-01"))
        self.assertTrue(dedup.similar_posts(self.TEXT, self.brand, identity="person").is_duplicate)

    def test_a_post_object_from_another_brand_is_refused(self):
        stray = Post(id="z", brand="stride-physio", identity="person", platform="instagram", text=self.TEXT)
        with self.assertRaises(dedup.LibraryError):
            dedup.record(self.brand, stray)
        mine = Post(id="a", brand=self.brand.id, identity="person", platform="instagram", text=self.TEXT,
                    topic_id="crust", shape="three-tips", proof_ids=["PRF-0001"])
        dedup.record(self.brand, mine)
        self.assertEqual(dedup.written_posts(self.brand)[0]["proof_ids"], ["PRF-0001"])


class TestBringingAPostBack(WritingCase):
    NOW = datetime(2026, 9, 1, 12, 0)

    def write(self, pid, topic="crust", shape="three-tips", platform="instagram", identity="person", proof=()):
        dedup.record_post(self.brand, pid, platform, identity, "Post %s about %s." % (pid, topic), topic_id=topic,
                          shape=shape, proof_ids=proof, now=self.NOW - timedelta(days=90))

    def ids(self, **kw):
        return [r["post_id"] for r in dedup.candidates(self.brand, "person", now=self.NOW, **kw)]

    def test_the_same_post_rests_for_fourteen_days_even_when_it_has_been_given_a_new_shape(self):
        self.write("a")
        dedup.mark_used(self.brand, "a", when=self.NOW - timedelta(days=13))
        self.write("a", shape="myth-vs-reality")                            # re-angled, but it only just went out
        self.assertEqual(self.ids(), [])
        self.write("b", topic="rye")
        dedup.mark_used(self.brand, "b", when=self.NOW - timedelta(days=15))
        self.assertEqual(self.ids(), [])                                    # unchanged: the thirty-day rule holds it
        self.write("b", topic="rye", shape="five-lessons")
        self.assertEqual(self.ids(), ["b"])                                 # a new shape, and fourteen days have passed

    def test_the_same_topic_shape_and_proof_rests_for_thirty_days_even_as_a_different_post(self):
        self.write("a")
        self.write("a-again")                                               # same topic + shape + proof
        self.write("a-new-shape", shape="myth-vs-reality")
        self.write("a-new-proof", proof=["PRF-0002"])
        dedup.mark_used(self.brand, "a", when=self.NOW - timedelta(days=20))
        self.assertTrue(dedup.on_cooldown(self.brand, "crust", "three-tips", now=self.NOW))
        self.assertFalse(dedup.on_cooldown(self.brand, "crust", "myth-vs-reality", now=self.NOW))
        self.assertEqual(sorted(self.ids()), ["a-new-proof", "a-new-shape"])
        later = self.NOW + timedelta(days=11)
        self.assertFalse(dedup.on_cooldown(self.brand, "crust", "three-tips", now=later))
        self.assertIn("a-again", [r["post_id"] for r in dedup.candidates(self.brand, "person", now=later)])

    def test_least_used_first_then_longest_rested(self):
        for pid, topic in (("often", "t1"), ("once-recent", "t2"), ("once-older", "t3"), ("never", "t4")):
            self.write(pid, topic=topic)
        for days in (80, 70, 60):
            dedup.mark_used(self.brand, "often", when=self.NOW - timedelta(days=days))
        dedup.mark_used(self.brand, "once-recent", when=self.NOW - timedelta(days=40))
        dedup.mark_used(self.brand, "once-older", when=self.NOW - timedelta(days=50))
        self.assertEqual(self.ids(), ["never", "once-older", "once-recent", "often"])
        rows = {r["post_id"]: r for r in dedup.written_posts(self.brand)}
        self.assertEqual((rows["often"]["times_used"], rows["never"]["times_used"]), (3, 0))

    def test_filters_and_the_identity_wall(self):
        self.write("ig")
        self.write("li", topic="rye", platform="linkedin")
        self.write("co", topic="oven", identity="company")
        self.assertEqual(self.ids(platform="linkedin"), ["li"])
        self.assertEqual(self.ids(topic_id="crust"), ["ig"])
        self.assertEqual(sorted(self.ids(exclude_ids=["ig"])), ["li"])
        self.assertEqual([r["post_id"] for r in dedup.candidates(self.brand, "company", now=self.NOW)], ["co"])

    def test_recording_again_updates_the_words_and_keeps_the_history(self):
        self.write("a")
        dedup.mark_used(self.brand, "a", when=self.NOW - timedelta(days=60))
        dedup.record_post(self.brand, "a", "instagram", "person", "Reworded.", topic_id="crust", shape="three-tips")
        row = dedup.written_posts(self.brand)[0]
        self.assertEqual((row["text"], row["times_used"]), ("Reworded.", 1))
        self.assertFalse(dedup.mark_used(self.brand, "no-such-post"))


# =============================================================================== the takeaway gate
class TestTakeawayGate(WritingCase):
    def test_a_concrete_move_can_be_an_instruction_a_list_a_script_or_the_brands_own_terms(self):
        vocab = quality.brand_vocabulary(self.brand)
        self.assertIn("weekend baking class", vocab["names"])
        self.assertIn("sourdough", vocab["words"])
        self.assertTrue(quality.concrete_move("Bread is slow. Weigh the flour.", vocab)["instruction"])
        self.assertTrue(quality.concrete_move("Bread is slow.\n- flour\n- water", vocab)["list"])
        self.assertTrue(quality.concrete_move("Say this: \"Could I book two places for Saturday, please?\"", vocab)["script"])
        terms = quality.concrete_move("Our sourdough starters behave differently in winter.", vocab)
        self.assertEqual((terms["brand_terms"], terms["ok"]), (["sourdough", "starters"], True))
        self.assertFalse(quality.concrete_move("Good things come to those who care about quality.", vocab)["ok"])

    def test_the_vocabulary_is_the_brands_not_a_built_in_list(self):
        clinic = brands.create("stride-physio", "Stride Physio", dict(
            json.loads(json.dumps(CLINIC)), pillars=[{"id": "knees", "name": "Runner's knee", "about": "Cadence and tendon load."}]))
        text = "Cadence and tendon load matter more than mileage."
        self.assertTrue(quality.takeaway_prescreen(text, clinic, lane="opinion")["concrete_move"]["ok"])
        self.assertFalse(quality.takeaway_prescreen(text, self.brand, lane="opinion")["concrete_move"]["ok"])

    def test_the_first_line_has_to_promise_something(self):
        for hook in ("3 checks before you bake tomorrow.", "Here is how we shape a loaf.", "Why your starter smells of nail polish.",
                     "Our dough rests for 18 hours.", "Five signs your starter is ready."):
            self.assertTrue(quality.hook_promise(hook + "\n\nBody.")["made"], hook)
        for hook in ("Is your bread boring?", "You won't believe this trick.", "Bread is life."):
            self.assertFalse(quality.hook_promise(hook + "\n\nBody.")["made"], hook)
        self.assertTrue(quality.hook_promise("Which of these 3 mistakes are you making?")["made"])

    def test_an_evergreen_post_needs_a_receipt_proof_or_an_honest_opinion_label(self):
        text = "Here is how we shape a loaf.\n\nFold the dough toward you."
        self.assertTrue(any("receipt" in h for h in quality.takeaway_prescreen(text, self.brand)["holds"]))
        self.assertEqual(quality.takeaway_prescreen(text, self.brand, has_proof=True)["holds"], [])
        self.assertEqual(quality.takeaway_prescreen(text, self.brand, lane="opinion")["holds"], [])
        self.assertEqual(quality.takeaway_prescreen(text, self.brand, lane="news")["holds"], [])
        self.assertEqual(quality.takeaway_prescreen(text + "\n\nIt rests for 18 hours.", self.brand)["holds"], [])
        self.assertFalse(quality.has_receipt("3 quick tips.\n1. Weigh.\n2. Wait."))

    def test_value_and_promise_kept_must_score_four_or_more(self):
        text = GOOD_DRAFT
        self.assertTrue(quality.takeaway_gate(text, self.brand)["passed"])
        self.assertTrue(quality.takeaway_gate(text, self.brand, rubric=quality.RubricScore(value=4, promise_kept=5))["passed"])
        held = quality.takeaway_gate(text, self.brand, rubric=quality.RubricScore(value=3, promise_kept=5, route=1))
        self.assertFalse(held["passed"])
        self.assertEqual(len(held["holds"]), 1)                              # route is scored, but it is not a floor
        self.assertIn("value", held["holds"][0])

    def test_the_craft_rubric_needs_every_score_and_a_total(self):
        self.assertIsNone(quality.RubricScore(on_voice=5).craft_passed())
        all_fours = quality.RubricScore(**{c: 4 for c in quality.CRAFT_CRITERIA})
        self.assertTrue(all_fours.craft_passed())
        one_weak = quality.RubricScore(**dict({c: 5 for c in quality.CRAFT_CRITERIA}, proof=2))
        self.assertFalse(one_weak.craft_passed())

    def test_style_notes_are_context_aware_and_never_block(self):
        signals = lambda t: [n["signal"] for n in quality.style_notes(t)]          # noqa: E731
        self.assertIn("sales-promise-verb", signals("This class will transform your baking."))
        self.assertEqual(signals("Last year we rebuilt the oven to transform how evenly it bakes."), [])
        self.assertIn("rhythm-of-three", signals("Our bread is honest, simple and warm."))
        self.assertEqual(signals("Bring flour, water and 2 jars."), [])
        self.assertEqual(signals(GOOD_DRAFT), [])


# =============================================================================== the contract
class TestContract(WritingCase):
    def build(self, identity="person", platform="linkedin", topic=None, shape="three-tips", job="reach", **kw):
        return contract.build_contract(self.brand, identity, platform, topic or self.approved(), shape, job, **kw)

    def test_it_carries_everything_the_writer_is_allowed_to_use(self):
        self.facts()
        Path(self.brand.path("Brand", "voice-samples.md")).write_text(
            "# Maple & Main Bakery: real samples of how we talk\n\n---\n\nMorning all. The rye sold out by nine, so we made more.\n",
            encoding="utf-8")
        c = self.build(job="lead_gen")
        self.assertEqual(c["speaker"]["display_name"], "Ava Lindqvist")
        self.assertIn("Write as \"I\"", c["speaker"]["person_or_company"])
        self.assertEqual(c["speaker"]["voice"]["signature_phrases"], ["Trust the dough."])
        self.assertEqual(c["speaker"]["own_words"][0]["text"], "Morning all. The rye sold out by nine, so we made more.")
        self.assertEqual(c["audience"]["on_this_platform"], "Local business owners who order for their teams.")
        self.assertEqual(c["platform"]["mechanics"]["max_len"], 3000)
        self.assertEqual(c["topic"]["source"]["detail"], "Why is my loaf flat?")
        self.assertEqual(c["shape"]["id"], "three-tips")
        self.assertEqual(c["cta"]["text"], "Book a Saturday class at the counter or on our website.")
        self.assertEqual(c["rules"]["never_mention"], ["Harbour Street Cafe"])
        self.assertTrue(c["rules"]["no_tags_here"])
        self.assertEqual(c["facts"]["numbers_you_may_state"], [18.0, 240.0, 2021.0])
        self.assertIn("Never invent a fact, a number, a quote or a customer", c["hard_rule"])
        page = c.markdown
        for needle in ("Ava Lindqvist", "Trust the dough.", "The rye sold out by nine", "Harbour Street Cafe",
                       "We proof our sourdough for 18 hours.  (source: Ava's recipe card)", "18, 240, 2021",
                       "Book a Saturday class", "Hard limit: 3000", "One post, one idea.", "Never invent a fact"):
            self.assertIn(needle, page)
        json.loads(c.to_json())                                             # and it is plain data

    def test_the_company_identity_gets_its_own_voice(self):
        c = self.build(identity="company")
        self.assertEqual(c["speaker"]["voice"]["register"], "Friendly and brief. The shop talking, not Ava.")
        self.assertEqual(c["speaker"]["voice"]["identity_note"], "Says we, never I.")
        self.brand.data["voice"]["by_identity"]["person"] = {"pov": "I", "note": "Ava speaks from her own bench."}
        page = self.build(identity="person").markdown
        self.assertIn("Point of view the brand chose for this identity: I", page)
        self.assertIn("For this identity: Ava speaks from her own bench.", page)
        self.assertEqual(c["speaker"]["voice"]["do"], ["Give exact times and weights."])        # not overridden, so inherited
        self.assertIn("Never \"I\"", c["speaker"]["person_or_company"])

    def test_with_no_facts_it_says_to_state_none_and_with_no_samples_it_says_not_to_imitate(self):
        c = self.build()
        self.assertTrue(c["facts"]["none"])
        self.assertEqual(c["speaker"]["own_words"], [])
        self.assertIn("State NO numbers", c.markdown)
        self.assertIn("do not imitate a voice you have not been shown", c.markdown)

    def test_a_reach_post_never_carries_the_offer(self):
        for job in ("reach", "trust"):
            c = self.build(job=job)
            self.assertNotIn(c["cta"]["kind"], ("offer", "keyword"))
            self.assertNotIn("Book a Saturday class", c.markdown)

    def test_the_planned_call_to_action_is_the_one_that_is_used(self):
        record = plan.plan_topic(self.approved(), self.brand, "person", "lead_gen")
        record["plans"]["person"]["platform_shapes"]["linkedin"]["cta_id"] = "offer-bread-club"
        self.assertEqual(self.build(topic=record, job="lead_gen")["cta"]["cta_id"], "offer-bread-club")

    def test_a_voice_source_outside_the_brand_folder_is_not_read(self):
        secret = Path(self.tmp.name, "someone elses notes.md")
        secret.write_text("Private words from another company.", encoding="utf-8")
        self.brand.data["voice"]["sources"] = ["../../someone elses notes.md", str(secret), "Brand/voice-samples.md"]
        c = self.build()
        self.assertNotIn("Private words", c.markdown)
        self.assertEqual(len([w for w in c["warnings"] if "outside the brand's folder" in w]), 2)
        self.assertIsNone(inside(self.brand, "../x"))
        self.assertIsNone(inside(self.brand, "C:\\Users\\x"))
        self.assertIsNotNone(inside(self.brand, "Brand/voice-samples.md"))

    def test_a_long_file_of_their_words_is_cut_to_a_readable_length(self):
        Path(self.brand.path("Brand", "voice-samples.md")).write_text("\n".join("Line %d of real talk." % i for i in range(3000)),
                                                                      encoding="utf-8")
        chunks, _notes = contract.load_own_words(self.brand)
        self.assertEqual(len(chunks[0]["text"]), contract.OWN_WORDS_BUDGET)
        self.assertTrue(chunks[0]["shortened"])

    def test_a_shapes_page_gives_its_structure_but_never_its_invented_example(self):
        folder = Path(self.tmp.name, "playbooks", "shapes")
        folder.mkdir(parents=True)
        (folder / "three-tips.md").write_text(
            "# Shape: Three tips\n\n> meta line\n\n## The structure\n1. The promise.\n2. Three moves.\n\n"
            "## Worked example (invented)\n\nOur toast loaf sold out for 6 Saturdays running.\n", encoding="utf-8")
        c = self.build()
        self.assertIn("#### The structure", c.markdown)
        self.assertIn("2. Three moves.", c.markdown)
        self.assertNotIn("6 Saturdays", c.markdown)
        self.assertNotIn("meta line", c.markdown)
        self.assertIn("It is invented, so it is left out here", c.markdown)

    def test_old_platform_rules_show_up_as_a_warning_on_the_contract(self):
        self.write_rules("2025-01-01")
        c = self.build()
        self.assertTrue(c["platform"]["rules_are_old"])
        self.assertTrue(any("refresh the playbooks" in w for w in c["warnings"]))
        self.assertIn("## Before you start", c.markdown)

    def test_private_proof_is_background_only(self):
        self.add_proof(self.brand, "PRF-0001", "Cafe order of 60 loaves a week", may_publish="no")
        self.add_proof(self.brand, "PRF-0002", "A student baked 12 loaves in her first month", may_publish="anonymised", third_party=1)
        c = self.build(topic=self.approved(proof_ids=["PRF-0001", "PRF-0002", "PRF-0404"]))
        self.assertEqual([p["proof_id"] for p in c["facts"]["proof"]], ["PRF-0002"])
        self.assertEqual([p["proof_id"] for p in c["facts"]["private_proof"]], ["PRF-0001"])
        self.assertEqual(c["facts"]["numbers_you_may_state"], [12.0])
        self.assertIn("NOT for publication", c.markdown)
        self.assertIn("Remove names", c.markdown)
        self.assertTrue(any("PRF-0404" in w for w in c["warnings"]))

    def test_regulated_brands_get_their_terms_and_a_caution(self):
        answers = json.loads(json.dumps(CLINIC))
        answers["compliance"] = {"pack": "health", "drop_terms": ["cures plantar fasciitis"], "hold_terms": ["shockwave therapy"],
                                 "disclaimer": "This is general information, not medical advice.", "sign_off_by": "Tomas Okafor"}
        clinic = brands.create("stride-physio", "Stride Physio", answers)
        topic = topics.new_topic("Why the same injury comes back", source_ref="a note from clinic", status="approved")
        page = contract.build_contract(clinic, "person", "instagram", topic, "myth-vs-reality", "trust").markdown
        for needle in ("cures plantar fasciitis", "shockwave therapy", "sign-off from Tomas Okafor", "not medical advice",
                       "regulated field (health)"):
            self.assertIn(needle, page)

    def test_what_it_refuses(self):
        with self.assertRaises(contract.ContractError) as cm:
            self.build(topic=topics.new_topic("Rye", source_ref="pillar:sourdough-at-home"))
        self.assertIn("has not been approved", str(cm.exception))
        with self.assertRaises(contract.ContractError) as cm:
            self.build(topic=dict(self.approved(), source_ref=""))
        self.assertIn("own material", str(cm.exception))
        with self.assertRaises(contract.ContractError) as cm:
            self.build(identity="company", platform="twitter")
        self.assertIn("does not post on twitter", str(cm.exception))
        with self.assertRaises(plan.PlanError):
            self.build(shape="haiku")
        with self.assertRaises(contract.ContractError):
            self.build(job="viral")
        os.remove(os.path.join(self.tmp.name, "playbooks", "profiles.json"))
        with self.assertRaises(platforms.PlatformRulesError):
            self.build()


# =============================================================================== checking a draft
class TestValidateDraft(WritingCase):
    def check(self, text, topic=None, identity="person", platform="linkedin", **kw):
        return contract.validate_draft(text, self.brand, identity, platform, topic or self.approved(), **kw)

    def test_a_sourced_clean_draft_passes(self):
        self.facts()
        report = self.check(GOOD_DRAFT)
        self.assertEqual((report["ok"], report["sourcing"], report["problems"]), (True, "passed", []))
        self.assertIn("Ready for review", report["summary"])

    def test_an_invented_number_blocks_the_draft_and_says_how_to_fix_it(self):
        self.facts()
        report = self.check(GOOD_DRAFT + "\n\nMore than 9,000 regulars agree.")
        self.assertEqual((report["ok"], report["sourcing"]), (False, "blocked"))
        self.assertTrue(any("9,000" in p and "add a fact" in p for p in report["problems"]))
        self.assertIn("To fix:", contract.format_report(report))

    def test_missing_evidence_is_unverified_never_passed(self):
        self.facts()
        no_source = self.check(GOOD_DRAFT, topic=dict(self.approved(), source_ref=""))
        self.assertEqual((no_source["ok"], no_source["sourcing"]), (True, "unverified"))
        lost_pointer = self.check(GOOD_DRAFT, topic=self.approved(source_ref="Brand/missing-file.md"))
        self.assertEqual(lost_pointer["sourcing"], "unverified")
        lost_proof = self.check(GOOD_DRAFT, proof_ids=["PRF-0404"])
        self.assertNotEqual(lost_proof["sourcing"], "passed")
        story = self.check(GOOD_DRAFT + "\n\nA customer came in last week and said it changed her baking.")
        self.assertEqual(story["sourcing"], "unverified")
        self.assertTrue(any("cannot be" in w and "confirmed" in w for w in story["warnings"]))
        no_topic = contract.validate_draft(GOOD_DRAFT, self.brand, "person", "linkedin", {})
        self.assertEqual(no_topic["sourcing"], "unverified")

    def test_a_story_with_publishable_proof_linked_passes_with_a_note_to_check_it(self):
        self.facts()
        self.add_proof(self.brand, "PRF-0001", "A student wrote to say her loaf finally rose", kind="testimonial",
                       may_publish="anonymised")
        report = self.check(GOOD_DRAFT + "\n\nOne of our students finished her first loaf.", proof_ids=["PRF-0001"])
        self.assertEqual(report["sourcing"], "passed")
        self.assertTrue(any("Check by eye" in w for w in report["warnings"]))

    def test_a_figure_that_only_private_proof_shows_is_blocked(self):
        self.add_proof(self.brand, "PRF-0001", "Cafe order of 60 loaves a week", may_publish="no")
        report = self.check("Here is what a standing order looks like.\n\nWe bake 60 loaves a week for one cafe.\n\n"
                            "Plan your oven time first.", proof_ids=["PRF-0001"])
        self.assertEqual(report["sourcing"], "blocked")
        self.assertTrue(any("not for publishing" in p for p in report["problems"]))

    def test_the_brands_own_rules_block(self):
        self.facts()
        named = self.check(GOOD_DRAFT + "\n\nWe supply Harbour Street Cafe.")
        self.assertFalse(named["ok"])
        self.assertTrue(any("never-mention" in p for p in named["problems"]))
        tagged = self.check(GOOD_DRAFT + "\n\n#sourdough")
        self.assertTrue(any("hashtags" in p for p in tagged["problems"]))
        self.assertTrue(self.check(GOOD_DRAFT + "\n\n#sourdough", platform="instagram")["ok"])

    def test_another_brands_name_in_the_draft_is_a_problem_unless_this_brand_allows_it(self):
        self.facts()
        self.clinic()
        report = self.check(GOOD_DRAFT + "\n\nOur neighbours at Stride Physio agree.")
        self.assertEqual(report["other_brands_named"], ["Stride Physio"])
        self.assertFalse(report["ok"])
        self.brand.data["own_brands"].append("Stride Physio")
        self.assertTrue(self.check(GOOD_DRAFT + "\n\nOur neighbours at Stride Physio agree.")["ok"])

    def test_a_repeat_is_caught_a_mirror_is_allowed_and_a_recheck_does_not_match_itself(self):
        self.facts()
        dedup.record_post(self.brand, "w1-li-01", "linkedin", "person", GOOD_DRAFT)
        repeat = self.check(GOOD_DRAFT, platform="facebook")
        self.assertFalse(repeat["ok"])
        self.assertTrue(any("already written" in p for p in repeat["problems"]))
        self.assertTrue(self.check(GOOD_DRAFT, post_id="w1-li-01")["ok"])
        mirror = self.check(GOOD_DRAFT, identity="company")
        self.assertTrue(mirror["ok"])
        self.assertTrue(any("deliberate mirror" in w for w in mirror["warnings"]))

    def test_the_ending_has_to_suit_the_job(self):
        self.facts()
        selling = GOOD_DRAFT + "\n\nBook a Saturday class at the counter or on our website."
        self.assertFalse(self.check(selling, job="reach")["ok"])
        self.assertTrue(self.check(selling, job="lead_gen")["ok"])
        planned = plan.plan_topic(self.approved(), self.brand, "person", "trust")
        self.assertFalse(self.check(selling, topic=planned)["ok"])                  # the job comes from the plan

    def test_the_takeaway_pre_screens_advise_by_default_and_block_when_the_brand_asks(self):
        empty = "Is your bread boring?\n\nGood things come to those who care."
        report = self.check(empty, topic=self.approved(lane="opinion"))
        self.assertTrue(report["ok"])                                               # craft advice does not block
        self.assertEqual(len(report["takeaway"]["holds"]), 2)
        self.assertEqual(sum(1 for w in report["warnings"] if w.startswith("Craft note:")), 2)
        self.assertEqual(report["sourcing"], "passed")                              # nothing false; it is just empty
        self.brand.data.setdefault("style", {})["strict_craft_checks"] = True
        strict = self.check(empty, topic=self.approved(lane="opinion"))
        self.assertFalse(strict["ok"])                                              # ...unless the brand wants it strict

    def test_every_tweet_in_a_thread_is_checked(self):
        self.facts()
        report = self.check("Here is why your loaf comes out flat.", platform="twitter",
                            thread=["Weigh the flour.", "We have 9,000 regulars."], topic=self.approved(lane="opinion"))
        self.assertEqual(report["sourcing"], "blocked")
        long_tweet = self.check("Here is why your loaf comes out flat.", platform="twitter", thread=["Weigh it. " * 40],
                                topic=self.approved(lane="opinion"))
        self.assertTrue(any("280" in p for p in long_tweet["problems"]))

    def test_a_platform_the_identity_does_not_have_is_a_problem(self):
        report = self.check(OPINION_DRAFT, identity="company", platform="twitter", topic=self.approved(lane="opinion"))
        self.assertTrue(any("does not post on twitter" in p for p in report["problems"]))

    def test_research_used_in_a_draft_comes_back_as_a_credit_line(self):
        Path(self.brand.path("Inputs", "Research", "survey.csv")).write_text(
            "Finding,Source\n\"41% of home bakers say their first loaf failed\",Invented Home Baking Survey\n", encoding="utf-8")
        report = self.check("Here is why 41% of first loaves fail.\n\nWeigh the flour.")
        self.assertEqual(report["sourcing"], "passed")
        self.assertTrue(any("Invented Home Baking Survey" in w for w in report["warnings"]))

    def test_the_verdict_travels_onto_the_post(self):
        self.facts()
        post = Post(id="a", brand=self.brand.id, identity="person", platform="linkedin", text=GOOD_DRAFT)
        self.assertEqual(post.sourcing, "unverified")
        contract.apply_to_post(post, self.check(GOOD_DRAFT))
        self.assertEqual(post.sourcing, "passed")
        stray = Post(id="z", brand="stride-physio", identity="person", platform="instagram", text="x")
        with self.assertRaises(contract.ContractError):
            contract.apply_to_post(stray, self.check(GOOD_DRAFT))


# =============================================================================== an empty brand, end to end
class TestAnEmptyBrandWorksEndToEnd(WritingCase):
    def test_from_nothing_to_a_checked_draft(self):
        blank = brands.create("blank-brand", "Blank Brand")
        self.assertGreaterEqual(len(topics.planning_inputs(blank)["gaps"]), 4)
        slots = plan.plan_week(blank, "company", count=10)
        self.assertEqual(plan.check_plan(slots), [])
        self.assertEqual(slots[0]["platforms"], ["linkedin", "instagram", "facebook"])
        self.assertTrue(all(s["cta_kind"] == "none" for s in slots if s["job"] == "lead_gen"))

        topics.add_topics(blank, "first-week", [topics.new_topic("Why we started", lane="opinion")])
        with self.assertRaises(topics.TopicError):
            topics.set_status(blank, "first-week", "why-we-started", "approved")
        topics.set_status(blank, "first-week", "why-we-started", "approved", source_ref="the owner said so on a call, 2 June")
        result = plan.plan_run(blank, "first-week", "company")
        topic = topics.get_topic(blank, "first-week", "why-we-started")
        shapes = topic["plans"]["company"]["platform_shapes"]
        self.assertEqual(len({v["shape"] for v in shapes.values()}), 3)
        self.assertEqual(result["problems"], [])

        built = contract.build_contract(blank, "company", "linkedin", topic, shapes["linkedin"]["shape"],
                                        topic["plans"]["company"]["job"])
        self.assertIn("State NO numbers", built.markdown)
        self.assertTrue(built["facts"]["none"])

        good = contract.validate_draft(OPINION_DRAFT, blank, "company", "linkedin", topic)
        self.assertEqual((good["ok"], good["sourcing"], good["problems"]), (True, "passed", []))
        numbers = contract.validate_draft(OPINION_DRAFT + "\n\nWe have done this for 12 years.", blank, "company",
                                          "linkedin", topic)
        self.assertEqual((numbers["ok"], numbers["sourcing"]), (False, "blocked"))
        self.assertTrue(any("add a fact" in p for p in numbers["problems"]))

        dedup.record_post(blank, "fw-li-01", "linkedin", "company", OPINION_DRAFT, topic_id=topic["topic_id"],
                          shape=shapes["linkedin"]["shape"])
        again = contract.validate_draft(OPINION_DRAFT, blank, "company", "facebook", topic)
        self.assertFalse(again["ok"])


# =============================================================================== the verbs
class TestVerbs(WritingCase):
    def run_verb(self, func, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = func(list(args))
        return code, out.getvalue()

    def test_every_verb_needs_a_brand_and_says_which_exist(self):
        for func, args in ((writing_cli.cli_plan, []), (writing_cli.cli_topics, ["inputs"]),
                           (writing_cli.cli_facts, ["list"]),
                           (writing_cli.cli_contract, ["--platform", "linkedin", "--run", "r", "--topic", "t"]),
                           (writing_cli.cli_validate, ["--platform", "linkedin", "--run", "r", "--topic", "t", "--draft", "-"])):
            code, out = self.run_verb(func, *args)
            self.assertEqual(code, 2, out)
            self.assertIn("--brand", out)
            self.assertIn("maple-and-main", out)
            self.assertNotIn("Traceback", out)

    def test_an_unknown_brand_or_identity_is_a_sentence_and_exit_code_one(self):
        code, out = self.run_verb(writing_cli.cli_plan, "--brand", "no-such-brand")
        self.assertEqual(code, 1)
        self.assertIn("there is no brand called 'no-such-brand'", out)
        code, out = self.run_verb(writing_cli.cli_plan, "--brand", "maple-and-main", "--identity", "doctor")
        self.assertEqual(code, 1)
        code, out = self.run_verb(writing_cli.cli_plan, "--brand", "maple-and-main")
        self.assertEqual(code, 1)
        self.assertIn("more than one identity", out)                       # who speaks is never a guess

    def test_a_brand_with_one_identity_does_not_need_to_be_asked(self):
        self.clinic()
        code, out = self.run_verb(writing_cli.cli_plan, "--brand", "stride-physio", "--count", "3")
        self.assertEqual(code, 0, out)
        self.assertIn("speaking as 'person'", out)

    def test_the_whole_flow_from_the_command_line(self):
        self.facts()
        b = ["--brand", "maple-and-main"]
        code, out = self.run_verb(writing_cli.cli_topics, "inputs", *b)
        self.assertEqual(code, 0)
        self.assertIn("pillar:sourdough-at-home", out)
        code, out = self.run_verb(writing_cli.cli_topics, "add", *b, "--run", "week-1", "--title", "Why a loaf comes out flat")
        self.assertIn("cannot be approved until", out)
        code, out = self.run_verb(writing_cli.cli_topics, "approve", *b, "--run", "week-1", "--id", "why-a-loaf-comes-out-flat")
        self.assertEqual(code, 1)
        self.assertIn("own material", out)
        code, out = self.run_verb(writing_cli.cli_topics, "approve", *b, "--run", "week-1", "--id", "why-a-loaf-comes-out-flat",
                                  "--source-ref", "audience.questions_they_ask[1]")
        self.assertEqual(code, 0, out)
        code, out = self.run_verb(writing_cli.cli_topics, "check", *b, "--run", "week-1")
        self.assertEqual(code, 0)

        code, out = self.run_verb(writing_cli.cli_contract, *b, "--identity", "person", "--platform", "linkedin",
                                  "--run", "week-1", "--topic", "why-a-loaf-comes-out-flat")
        self.assertEqual(code, 1)
        self.assertIn("has not been planned", out)
        code, out = self.run_verb(writing_cli.cli_plan, *b, "--identity", "person", "--run", "week-1")
        self.assertEqual(code, 0, out)
        self.assertIn("linkedin as ", out)
        code, out = self.run_verb(writing_cli.cli_contract, *b, "--identity", "person", "--platform", "linkedin",
                                  "--run", "week-1", "--topic", "why-a-loaf-comes-out-flat")
        self.assertEqual(code, 0, out)
        self.assertIn("# Write one linkedin post for Maple & Main Bakery", out)

        draft = Path(self.tmp.name, "the draft's file é.txt")
        draft.write_text(GOOD_DRAFT, encoding="utf-8")
        check = ["--identity", "person", "--platform", "linkedin", "--run", "week-1", "--topic", "why-a-loaf-comes-out-flat",
                 "--draft", str(draft), "--job", "reach"]
        code, out = self.run_verb(writing_cli.cli_validate, *b, *check)
        self.assertEqual(code, 0, out)
        self.assertIn("Sourcing: passed.", out)
        draft.write_text(GOOD_DRAFT + "\n\nWe have 9,000 regulars.", encoding="utf-8")
        code, out = self.run_verb(writing_cli.cli_validate, *b, *check)
        self.assertEqual(code, 1)
        self.assertIn("Sourcing: blocked.", out)
        code, out = self.run_verb(writing_cli.cli_validate, *b, *check, "--json")
        self.assertEqual(json.loads(out)["sourcing"], "blocked")
        code, out = self.run_verb(writing_cli.cli_validate, *b, *(check[:-4] + ["--draft", str(draft) + ".missing"]))
        self.assertEqual(code, 1)
        self.assertIn("could not be opened", out)

    def test_plan_prints_a_table_and_says_nothing_was_saved(self):
        code, out = self.run_verb(writing_cli.cli_plan, "--brand", "maple-and-main", "--identity", "person")
        self.assertEqual(code, 0, out)
        self.assertIn("Mix: ", out)
        self.assertIn("Nothing was saved", out)
        code, out = self.run_verb(writing_cli.cli_plan, "--brand", "maple-and-main", "--identity", "company",
                                  "--platforms", "twitter")
        self.assertEqual(code, 1)
        self.assertIn("does not post on twitter", out)

    def test_a_fact_can_be_added_from_the_command_line_and_then_backs_a_draft(self):
        b = ["--brand", "maple-and-main"]
        code, out = self.run_verb(writing_cli.cli_facts, "list", *b)
        self.assertEqual(code, 0)
        self.assertIn("No verified facts yet", out)
        self.assertFalse(grounding.ground_draft("We bake 12 rye loaves on a Friday.", self.brand)["ok"])
        code, out = self.run_verb(writing_cli.cli_facts, "add", *b, "--claim", "We bake 12 rye loaves on a Friday.",
                                  "--source", "the production sheet")
        self.assertEqual(code, 0, out)
        self.assertIn("may now state: 12", out)
        self.assertTrue(grounding.ground_draft("We bake 12 rye loaves on a Friday.", self.brand)["ok"])
        code, out = self.run_verb(writing_cli.cli_facts, "add", *b, "--claim", "We sell 300 loaves a day.", "--source", " ")
        self.assertEqual(code, 1)
        self.assertIn("needs a source", out)
        code, out = self.run_verb(writing_cli.cli_facts, "list", *b)
        self.assertIn("the production sheet", out)

    def test_help_does_not_end_the_program(self):
        code, out = self.run_verb(writing_cli.cli_topics, "--help")
        self.assertEqual(code, 0)
        self.assertIn("approve", out)


# =============================================================================== the thinking journal
ROUGH = "ok so  the thing about starters is\nthey're alive?? feed it like a pet, not a recipe"
SECRET = "My landlord is selling the building next spring and I have not told the staff yet."


class TestJournal(WritingCase):
    def test_their_words_are_saved_exactly_and_dated(self):
        entry = journal.add(self.brand, ROUGH, when=date(2026, 10, 23))
        self.assertEqual((entry["id"], entry["kind"], entry["private"]), ("2026-10-23-1", "owner", False))
        again = journal.add(self.brand, "second thought", when=date(2026, 10, 23))
        self.assertEqual(again["id"], "2026-10-23-2")
        saved = journal.load(self.brand)["entries"]
        self.assertEqual(saved[0]["text"], ROUGH)                       # not tidied: the double space and "??" stay
        self.assertEqual(saved[0]["date"], "2026-10-23")
        self.assertIn(ROUGH, Path(self.brand.path("Brand", "journal.md")).read_text(encoding="utf-8"))

    def test_nothing_empty_and_nothing_that_would_break_the_file(self):
        for bad in ("", "   \n  "):
            with self.assertRaises(StudioError):
                journal.add(self.brand, bad)
        with self.assertRaises(StudioError):
            journal.add(self.brand, "line one\n### entry 2026-01-01-1 · owner's words\nline three")

    def test_claudes_notes_are_never_the_owners_words(self):
        journal.add(self.brand, "Today's question: what do new bakers get wrong first?", kind="claude",
                    when=date(2026, 10, 23))
        journal.add(self.brand, ROUGH, asked="What do new bakers get wrong first?", when=date(2026, 10, 23))
        entries = journal.load(self.brand)["entries"]
        self.assertEqual([e["kind"] for e in entries], ["claude", "owner"])
        self.assertEqual(entries[1]["asked"], "What do new bakers get wrong first?")
        self.assertEqual(entries[1]["text"], ROUGH)                     # the question is not part of their words
        self.assertEqual(journal.owner_words(self.brand), ROUGH)
        with self.assertRaises(StudioError):
            journal.add(self.brand, "x", kind="ai")

    def test_planning_cites_entries_and_never_sees_private_ones(self):
        journal.add(self.brand, ROUGH, when=date(2026, 10, 23))
        journal.add(self.brand, SECRET, private=True, when=date(2026, 10, 23))
        inputs = topics.planning_inputs(self.brand)
        ids = [e["id"] for e in inputs["journal"]["entries"]]
        self.assertEqual(ids, ["2026-10-23-1"])
        self.assertEqual(inputs["journal"]["private_left_out"], 1)
        page = topics.planning_brief(self.brand)
        self.assertIn("journal:2026-10-23-1", page)
        self.assertIn("they're alive??", page)
        self.assertNotIn("landlord", page)
        self.assertNotIn("landlord", json.dumps(inputs))
        self.assertTrue(topics.resolve_source_ref(self.brand, "journal:2026-10-23-1")["ok"])
        private = topics.resolve_source_ref(self.brand, "journal:2026-10-23-2")
        self.assertFalse(private["ok"])
        self.assertIn("private", private["detail"])
        self.assertFalse(topics.resolve_source_ref(self.brand, "journal:2026-10-23-9")["ok"])

    def test_a_hand_written_journal_still_works_and_private_sections_stay_out(self):
        Path(self.brand.path("Brand", "journal.md")).write_text(
            "# My journal\n\n## 2026-10-01\n\nCrust matters more than crumb.\n\n### PRIVATE: money\n"
            "We are behind on rent.\n\n### Ideas\nA class for kids. PRIVATE ask Sam first\nA rye week.\n",
            encoding="utf-8")
        journal.add(self.brand, "new thought", when=date(2026, 10, 23))
        older = "\n".join(journal.load(self.brand)["older"])
        self.assertIn("Crust matters more than crumb.", older)
        self.assertIn("A rye week.", older)
        self.assertNotIn("rent", older)
        self.assertNotIn("Sam", older)
        self.assertNotIn("rent", topics.planning_brief(self.brand))

    def test_an_entry_can_be_made_private_and_public_again(self):
        journal.add(self.brand, SECRET, when=date(2026, 10, 23))
        journal.set_private(self.brand, "2026-10-23-1", True)
        self.assertTrue(journal.get(self.brand, "2026-10-23-1")["private"])
        self.assertEqual(journal.get(self.brand, "2026-10-23-1")["text"], SECRET)
        journal.set_private(self.brand, "2026-10-23-1", False)
        self.assertFalse(journal.get(self.brand, "2026-10-23-1")["private"])
        with self.assertRaises(StudioError):
            journal.set_private(self.brand, "2026-10-23-7", True)

    def test_a_private_entry_cannot_become_a_post(self):
        journal.add(self.brand, SECRET, private=True, when=date(2026, 10, 23))
        topic = self.approved(source_ref="journal:2026-10-23-1")
        problems, _warnings = topics.check_topics(self.brand, [topic])
        self.assertTrue(any("private" in p for p in problems))
        with self.assertRaises(StudioError):
            contract.build_contract(self.brand, "person", "linkedin", topic, "three-tips", "reach")
        self.facts()
        report = contract.validate_draft(GOOD_DRAFT + "\n\nMy landlord is selling the building next spring, by the way.",
                                         self.brand, "person", "linkedin", self.approved())
        self.assertFalse(report["ok"])
        self.assertTrue(any("private journal entry" in p for p in report["problems"]))

    def test_the_writer_gets_the_entry_and_the_voice_gets_only_public_owner_words(self):
        journal.add(self.brand, ROUGH, when=date(2026, 10, 23))
        journal.add(self.brand, SECRET, private=True, when=date(2026, 10, 23))
        journal.add(self.brand, "A note Claude wrote.", kind="claude", when=date(2026, 10, 23))
        self.brand.data.setdefault("voice", {})["sources"] = ["Brand/journal.md"]
        c = contract.build_contract(self.brand, "person", "linkedin", self.approved(source_ref="journal:2026-10-23-1"),
                                    "three-tips", "reach")
        self.assertEqual(c["topic"]["source"]["kind"], "journal")
        self.assertIn("they're alive??", c["topic"]["source"]["excerpt"])
        voice = " ".join(chunk["text"] for chunk in c["speaker"]["own_words"])
        self.assertIn("they're alive??", voice)
        self.assertNotIn("landlord", voice)
        self.assertNotIn("Claude wrote", voice)
        self.assertNotIn("landlord", c.markdown)

    def test_the_verb(self):
        run = TestVerbs.run_verb
        b = ["--brand", "maple-and-main"]
        code, out = run(self, writing_cli.cli_journal, "add", "--text", ROUGH)
        self.assertEqual(code, 2)
        self.assertIn("--brand", out)
        code, out = run(self, writing_cli.cli_journal, "add", *b, "--text", ROUGH, "--date", "2026-10-23")
        self.assertEqual(code, 0, out)
        self.assertIn("2026-10-23-1", out)
        words = Path(self.tmp.name, "their words é.txt")
        words.write_text(SECRET, encoding="utf-8")
        code, out = run(self, writing_cli.cli_journal, "add", *b, "--text-file", str(words), "--private",
                        "--date", "2026-10-23")
        self.assertEqual(code, 0, out)
        self.assertIn("private", out)
        code, out = run(self, writing_cli.cli_journal, "list", *b)
        self.assertEqual(code, 0)
        self.assertIn("2026-10-23-2", out)
        code, out = run(self, writing_cli.cli_journal, "public", *b, "--id", "2026-10-23-2")
        self.assertEqual(code, 0, out)
        self.assertFalse(journal.get(self.brand, "2026-10-23-2")["private"])


# =============================================================================== influences
class TestInfluences(WritingCase):
    def setUp(self):
        super().setUp()
        self.brand.data["influences"] = [{"name": "Rick Rubin", "why": "how he strips things back"}, "Naval Ravikant"]

    def test_planning_shows_them_as_reference_for_structure_only(self):
        self.assertEqual([i["name"] for i in topics.influences(self.brand)], ["Rick Rubin", "Naval Ravikant"])
        page = topics.planning_brief(self.brand)
        self.assertIn("Rick Rubin", page)
        self.assertIn("structure and format only", page)

    def test_the_writer_is_told_never_to_copy_them(self):
        c = contract.build_contract(self.brand, "person", "linkedin", self.approved(), "three-tips", "reach")
        self.assertEqual([i["name"] for i in c["influences"]["people"]], ["Rick Rubin", "Naval Ravikant"])
        self.assertIn("Never copy", c.markdown)
        self.assertIn("Naval Ravikant", c.markdown)

    def test_naming_one_in_a_draft_is_flagged(self):
        self.facts()
        report = contract.validate_draft(GOOD_DRAFT + "\n\nAs Rick Rubin says, less is more.", self.brand, "person",
                                         "linkedin", self.approved())
        self.assertTrue(any("Rick Rubin" in w and "inspire" in w for w in report["warnings"]))

    def test_a_brand_with_none_is_unchanged(self):
        self.brand.data.pop("influences")
        self.assertEqual(topics.influences(self.brand), [])
        self.assertNotIn("structure and format only", topics.planning_brief(self.brand))


if __name__ == "__main__":
    unittest.main(verbosity=2)
