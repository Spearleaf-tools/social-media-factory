"""Writing-engine tests: the copy checker, batches, and the drip schedule.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                        # noqa: E402
from smf.studio import posts as P                             # noqa: E402
from smf.studio.lint import Rules, lint_caption, is_clean     # noqa: E402
from tests.test_brands import BAKERY, CLINIC                  # noqa: E402

FOUR = {"accounts": {"provider": "metricool", "targets": [
    {"identity": "person", "platform": pf, "provider_brand_id": 101, "connected": True}
    for pf in ("linkedin", "instagram", "facebook", "twitter")] + [
    {"identity": "company", "platform": pf, "provider_brand_id": 102, "connected": True}
    for pf in ("linkedin", "instagram", "facebook")]}}


class StudioCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        answers = json.loads(json.dumps(BAKERY))
        answers.update(json.loads(json.dumps(FOUR)))
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", answers)
        self.rules = Rules.for_brand(self.brand)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def post(self, pid, platform="linkedin", identity="person", topic="t1", text="Bake day is Saturday.", **kw):
        return P.Post(id=pid, brand=self.brand.id, identity=identity, platform=platform, text=text,
                      topic_id=topic, **kw)


def rules_of(findings):
    return {(f.severity, f.rule) for f in findings}


class TestLintNeedsABrand(StudioCase):
    def test_there_is_no_default_brand(self):
        with self.assertRaises(TypeError):
            lint_caption("hello", "linkedin", None)

    def test_clean_copy_is_clean(self):
        text = "We proof the dough for eighteen hours.\n\nThat is why the crust cracks when you press it."
        self.assertEqual(lint_caption(text, "linkedin", self.rules), [])


class TestUniversalRules(StudioCase):
    def test_platform_character_limits(self):
        self.assertIn(("ERROR", "char-limit"), rules_of(lint_caption("x" * 281, "twitter", self.rules)))
        self.assertNotIn(("ERROR", "char-limit"), rules_of(lint_caption("x" * 281, "linkedin", self.rules)))

    def test_thread_only_on_x_and_every_tweet_is_checked(self):
        p = self.post("a", platform="linkedin", thread=["second"])
        self.assertIn(("ERROR", "thread-platform"), rules_of(p.lint(self.rules)))
        q = self.post("b", platform="twitter", thread=["fine", "y" * 300])
        errs = q.lint(self.rules)
        self.assertTrue(any(f.rule == "char-limit" and "[tweet 3]" in f.detail for f in errs))


class TestBrandRules(StudioCase):
    def test_never_mention_full_name_and_distinctive_first_word(self):
        self.assertIn(("ERROR", "never-mention"), rules_of(lint_caption("We supply Harbour Street Cafe.", "instagram", self.rules)))
        self.assertIn(("ERROR", "never-mention"), rules_of(lint_caption("Ask the team at Harbour.", "instagram", self.rules)))
        self.assertTrue(is_clean("A street cafe near the harbourside.", "instagram", self.rules))

    def test_own_brand_is_never_flagged_even_if_listed_by_mistake(self):
        r = Rules(never_mention=["Maple & Main"], own_brands=["Maple & Main"]).compile()
        self.assertTrue(is_clean("Maple & Main opens at seven.", "instagram", r))

    def test_generic_first_words_do_not_become_bans(self):
        r = Rules(never_mention=["First Dental Group"]).compile()
        self.assertTrue(is_clean("The first loaf sold out.", "instagram", r))

    def test_tags_are_a_brand_choice_per_platform(self):
        self.assertIn(("ERROR", "no-tags"), rules_of(lint_caption("New loaf #sourdough", "linkedin", self.rules)))
        self.assertTrue(is_clean("New loaf #sourdough", "instagram", self.rules))
        self.assertTrue(is_clean("We are #1 for rye.", "linkedin", self.rules))          # "#1" is not a hashtag
        relaxed = Rules(no_tags_on=()).compile()
        self.assertTrue(is_clean("New loaf #sourdough", "linkedin", relaxed))

    def test_long_dashes_are_a_brand_choice(self):
        self.assertIn(("ERROR", "em-dash"), rules_of(lint_caption("Bread — slowly.", "instagram", self.rules)))
        self.assertTrue(is_clean("Bread — slowly.", "instagram", Rules(no_em_dashes=False).compile()))

    def test_plain_language_pack_can_be_switched_off_and_extended(self):
        self.assertIn(("ERROR", "banned-word"), rules_of(lint_caption("An innovative loaf.", "instagram", self.rules)))
        self.assertIn(("ERROR", "banned-phrase"), rules_of(lint_caption("Let's dive in to rye.", "instagram", self.rules)))
        off = Rules(plain_language_pack=False, banned_words=["artisanal"]).compile()
        self.assertTrue(is_clean("An innovative loaf.", "instagram", off))
        self.assertIn(("ERROR", "banned-word"), rules_of(lint_caption("An artisanal loaf.", "instagram", off)))

    def test_length_rules_warn_and_lists_are_exempt_from_paragraph_caps(self):
        long_sentence = " ".join(["word"] * 30) + "."
        self.assertIn(("WARN", "sentence-words"), rules_of(lint_caption(long_sentence, "linkedin", self.rules)))
        steps = "My first checks:\n1. Flour weight.\n2. Water temperature.\n3. Starter age.\n4. Room temperature.\n5. Time."
        self.assertEqual(lint_caption(steps, "linkedin", self.rules), [])

    def test_overpromises_warn(self):
        self.assertIn(("WARN", "overpromise"), rules_of(lint_caption("This will fix your starter.", "instagram", self.rules)))

    def test_regulated_terms_come_from_the_brand(self):
        with mock.patch.object(brands, "CLIENT_DIR", brands.CLIENT_DIR):
            answers = json.loads(json.dumps(CLINIC))
            answers["compliance"] = {"pack": "health", "drop_terms": ["cures plantar fasciitis"],
                                     "hold_terms": ["shockwave therapy"]}
            clinic = brands.create("stride-physio", "Stride Physio", answers)
        r = Rules.for_brand(clinic)
        got = rules_of(lint_caption("Our plan cures plantar fasciitis. We also offer shockwave therapy.", "instagram", r))
        self.assertIn(("ERROR", "never-publish"), got)
        self.assertIn(("WARN", "needs-sign-off"), got)
        self.assertTrue(is_clean("Our plan cures plantar fasciitis.", "instagram", self.rules))   # the bakery has no such rule


class TestBatches(StudioCase):
    def test_round_trip_and_atomic_write(self):
        path = self.brand.path("Output", "batches", "week 1's batch.json")
        P.save_batch([self.post("a"), self.post("b", platform="instagram", media_paths=["x.png"])], path, {"note": "w1"})
        loaded, meta = P.load_batch(path, self.brand.id)
        self.assertEqual([p.id for p in loaded], ["a", "b"])
        self.assertEqual(meta["brand"], "maple-and-main")
        self.assertEqual([f for f in os.listdir(os.path.dirname(path)) if f.startswith(".tmp-")], [])

    def test_a_batch_cannot_mix_brands_or_be_opened_as_another_brand(self):
        other = P.Post(id="z", brand="stride-physio", identity="person", platform="instagram", text="x")
        with self.assertRaises(ValueError):
            P.save_batch([self.post("a"), other], self.brand.path("Output", "batches", "mixed.json"))
        path = self.brand.path("Output", "batches", "b.json")
        P.save_batch([self.post("a")], path)
        with self.assertRaises(ValueError) as cm:
            P.load_batch(path, "stride-physio")
        self.assertIn("belongs to maple-and-main", str(cm.exception))

    def test_unknown_keys_from_a_newer_file_are_ignored(self):
        path = self.brand.path("Output", "batches", "b.json")
        P.save_batch([self.post("a")], path)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["posts"][0]["field_from_the_future"] = 1
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(P.load_batch(path, self.brand.id)[0][0].id, "a")

    def test_check_batch_sets_status_and_leaves_decided_posts_alone(self):
        good = self.post("good")
        bad = self.post("bad", text="An innovative loaf.")
        insta = self.post("ig", platform="instagram")
        decided = self.post("done", text="An innovative loaf.", status="approved")
        rep = P.check_batch([good, bad, insta, decided], self.brand)
        self.assertEqual((good.status, bad.status, insta.status, decided.status),
                         ("lint_pass", "draft", "draft", "approved"))
        self.assertTrue(any("media-required" in e for e in insta.lint_errors))
        self.assertEqual(rep, {"total": 4, "clean": 1, "blocked": 2})

    def test_a_post_for_an_identity_the_brand_lacks_is_an_error(self):
        with self.assertRaises(brands.BrandError):
            P.check_batch([self.post("a", identity="doctor")], self.brand)

    def test_sourcing_is_never_passed_by_default(self):
        self.assertEqual(self.post("a").sourcing, "unverified")

    def test_future_time(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        p = self.post("a")
        self.assertIn("no scheduled time", P.future_time_problem(p, now=now))
        p.scheduled_time_iso = "2026-09-01T11:00:00Z"
        self.assertIn("past", P.future_time_problem(p, now=now))
        p.scheduled_time_iso = "2026-09-01T12:10:00Z"
        self.assertIn("less than 30", P.future_time_problem(p, now=now))
        p.scheduled_time_iso = "2026-09-02T12:10:00Z"
        self.assertIsNone(P.future_time_problem(p, now=now))


class TestDrip(StudioCase):
    def week(self, topics=("t1", "t2", "t3"), identities=("person",)):
        out = []
        for ident in identities:
            for t in topics:
                for pf in self.brand.platforms_for(ident):
                    out.append(self.post("%s-%s-%s" % (ident, t, pf), platform=pf, identity=ident, topic=t))
        return out

    def days(self, posts):
        return {(p.identity, p.platform, p.topic_id): p.scheduled_time_local[:10] for p in posts}

    def test_each_topic_is_on_one_account_per_day_and_rotates(self):
        posts = self.week()
        cal = P.assign_drip_slots(posts, self.brand, start_date="2026-10-05")
        self.assertEqual(cal["span_days"], 4)
        self.assertTrue(P.assert_drip(posts))
        per_day = {}
        for p in posts:
            per_day.setdefault((p.scheduled_time_local[:10], p.topic_id), []).append(p.platform)
        self.assertTrue(all(len(v) == 1 for v in per_day.values()))
        # and no account gets two evergreen posts on one day
        per_account_day = {}
        for p in posts:
            per_account_day.setdefault((p.platform, p.scheduled_time_local[:10]), []).append(p.id)
        self.assertTrue(all(len(v) == 1 for v in per_account_day.values()))

    def test_two_identities_never_run_the_same_topic_the_same_day(self):
        posts = self.week(topics=("t1", "t2"), identities=("person", "company"))
        P.assign_drip_slots(posts, self.brand, start_date="2026-10-05")
        self.assertTrue(P.assert_drip(posts))

    def test_more_topics_than_platforms_spills_to_later_days_without_collisions(self):
        posts = self.week(topics=tuple("t%d" % i for i in range(1, 8)))
        cal = P.assign_drip_slots(posts, self.brand, start_date="2026-10-05", days=7)
        self.assertTrue(P.assert_drip(posts))
        self.assertGreater(cal["span_days"], 4)

    def test_news_goes_out_on_day_zero_and_is_exempt_from_the_guard(self):
        posts = [self.post("n-%s" % pf, platform=pf, topic="breaking", lane="news")
                 for pf in ("linkedin", "instagram", "facebook")]
        P.assign_drip_slots(posts, self.brand, start_date="2026-10-05")
        self.assertEqual({p.scheduled_time_local[:10] for p in posts}, {"2026-10-05"})
        self.assertTrue(P.assert_drip(posts))

    def test_the_guard_refuses_a_hand_made_broadcast(self):
        posts = [self.post("x-%s" % pf, platform=pf, topic="t1", scheduled_time_local="2026-10-05 10:00")
                 for pf in ("linkedin", "instagram")]
        with self.assertRaises(P.DripError) as cm:
            P.assert_drip(posts)
        self.assertIn("all on 2026-10-05", str(cm.exception))

    def test_a_platform_the_identity_does_not_have_is_an_error_not_day_zero(self):
        with self.assertRaises(ValueError) as cm:
            P.assign_drip_slots([self.post("a", platform="twitter", identity="company")], self.brand)
        self.assertIn("does not post on twitter", str(cm.exception))

    def test_start_defaults_to_tomorrow_and_times_use_the_brands_windows_and_timezone(self):
        posts = self.week(topics=("t1",))
        P.assign_drip_slots(posts, self.brand)
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(min(p.scheduled_time_local[:10] for p in posts), tomorrow)
        self.assertTrue(all(p.scheduled_time_local[-5:] in self.brand.posting_windows for p in posts))
        p = posts[0]
        local = datetime.strptime(p.scheduled_time_local, "%Y-%m-%d %H:%M")
        utc = datetime.strptime(p.scheduled_time_iso, "%Y-%m-%dT%H:%M:%SZ")
        self.assertIn((utc - local).total_seconds() / 3600, (4.0, 5.0))        # New York, summer or winter

    def test_same_input_same_schedule(self):
        a, b = self.week(), self.week()
        P.assign_drip_slots(a, self.brand, start_date="2026-10-05")
        P.assign_drip_slots(b, self.brand, start_date="2026-10-05")
        self.assertEqual(self.days(a), self.days(b))

    def test_topic_order_is_the_callers_priority_and_makes_input_order_irrelevant(self):
        """Without topic_order, the first topic seen gets the first slot (the planner's order is
        the priority). With it, shuffled input gives the same calendar."""
        a, b = self.week(), self.week()
        order = ["t1", "t2", "t3"]
        P.assign_drip_slots(a, self.brand, start_date="2026-10-05", topic_order=order)
        P.assign_drip_slots(list(reversed(b)), self.brand, start_date="2026-10-05", topic_order=order)
        self.assertEqual(self.days(a), self.days(b))

    def test_posts_in_one_window_are_staggered(self):
        posts = [self.post("p%d" % i, platform="facebook", topic="n%d" % i, lane="news") for i in range(8)]
        P.assign_drip_slots(posts, self.brand, start_date="2026-10-05")
        times = [p.scheduled_time_local for p in posts]
        self.assertEqual(len(times), len(set(times)))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestDripStartsOnTheStartDate(StudioCase):
    def test_the_first_post_goes_out_on_the_start_date_not_after_an_empty_day(self):
        posts = [self.post("a", platform="twitter", topic="t1"), self.post("b", platform="facebook", topic="t2")]
        P.assign_drip_slots(posts, self.brand, start_date="2026-10-05")
        self.assertEqual(min(p.scheduled_time_local[:10] for p in posts), "2026-10-05")
        self.assertTrue(P.assert_drip(posts))


class TestPlannerOnlyPlansWhatCanBeDrawn(StudioCase):
    def test_a_brand_with_no_photos_is_never_given_a_photo_or_screenshot_slot(self):
        from smf.studio import plan
        for job in ("reach", "trust", "lead_gen"):
            ids = {f["id"] for f in plan.formats_for(self.brand, job)}
            self.assertTrue(ids <= set(plan.DRAWS_AS), (job, ids))

    def test_once_the_brand_has_its_own_photos_those_kinds_are_offered(self):
        from smf.studio import plan
        Path(self.brand.path("Brand", "brand-kit", "photos", "bench.jpg")).write_bytes(b"x")
        ids = {f["id"] for f in plan.formats_for(self.brand, "trust")}
        self.assertIn("real-photo-or-video", ids)

    def test_the_planners_table_matches_the_renderers(self):
        from smf.studio import plan
        try:
            from smf.studio.render.spec import FORMATS_FOR_PLANNED_VISUAL, NO_KEY_FORMATS
        except ImportError:
            self.skipTest("the renderer package is not importable here")
        self.assertEqual(plan.DRAWS_AS, FORMATS_FOR_PLANNED_VISUAL)
        for formats in plan.DRAWS_AS.values():
            self.assertTrue(set(formats) <= set(NO_KEY_FORMATS))
