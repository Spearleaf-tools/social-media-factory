"""Test-and-promote tests: the loop does nothing unless the brand turned it on, a test wave is
every version of one clip on ONE account, results are tied to versions by the service's post id
and never by similar words, nothing below the floor is promoted, and each winner is promoted once.

    python -m unittest discover -s tests -t . -v

Every account, id, view count and response here is invented.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from collections import Counter
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                    # noqa: E402
from smf.posting import accounts as A                                     # noqa: E402
from smf.posting import posting_cli                                       # noqa: E402
from smf.posting import promote as PR                                     # noqa: E402
from smf.posting import results as R                                      # noqa: E402
from smf.posting import shorts as SH                                      # noqa: E402
from smf.posting import state as S                                        # noqa: E402
from smf.studio import posts as P                                         # noqa: E402
from tests.posting_fakes import SendCase, approve_batch, brand_answers, drop_video, target    # noqa: E402
from tests.test_brands import BAKERY, CLINIC                              # noqa: E402

TODAY = date(2030, 1, 1)
EARLY = datetime(2029, 12, 1, tzinfo=timezone.utc)
TWO_DAYS_ON = datetime(2030, 1, 4, 17, 0, tzinfo=timezone.utc)
TARGETS = [target("person", "tiktok", 101), target("person", "instagram", 101), target("person", "youtube", 101),
           target("company", "facebook", 102)]
VERSIONS = {"warm": "Three days for one rye loaf. Here is day one.",
            "fast": "Our rye takes three days. Most of it is waiting.",
            "plain": "Rye, water, salt, and seventy two hours."}


def tiktok_row(network_id, words, views, created="2030-01-02T12:00:05+0000", shares=0):
    return {"videoId": network_id, "createTime": created, "shareUrl": "https://example.com/v/%s" % network_id,
            "videoDescription": words, "viewCount": views, "likeCount": 5, "commentCount": 1, "shareCount": shares}


class LoopCase(SendCase):
    BAKERY_ANSWERS = brand_answers(BAKERY, targets=TARGETS, video={"inbox_folder": "Inputs/Edited",
                                                                    "test_and_promote": True})
    CLINIC_ANSWERS = brand_answers(CLINIC, targets=[target("person", "tiktok", 555), target("person", "instagram", 555)])

    def drop_clip(self, clip="rye loaf", versions=None, brand=None):
        brand = brand or self.bakery
        for version, words in (versions or VERSIONS).items():
            drop_video(brand.path("Inputs", "Edited"), "%s__%s.mp4" % (clip, version), words)

    def run_the_test_wave(self, clip="rye loaf"):
        """Plan, approve and really send the wave for one clip. Returns {version: post id}."""
        plan = PR.plan_test_wave(self.bakery, save=True, today=TODAY)
        approve_batch(self.bakery, plan["batch"])
        report = PR.send(self.bakery, plan["batch"], self.provider(True), confirm=True)
        self.assertEqual(report["counts"], {"sent": len(plan["posts"])})
        record = PR.state_file(self.bakery).read()["clips"][clip]["test"]["posts"]
        return {v["version"]: post_id for post_id, v in record.items()}

    def results_arrive(self, views, created=None, words=None, now=TWO_DAYS_ON):
        created = created or {}
        rows = [tiktok_row("TT-%s" % version, (words or VERSIONS)[version], n,
                           created.get(version, "2030-01-02T12:00:05+0000"))
                for version, n in views.items()]
        self.service.results[("101", "tiktok")] = rows
        return R.harvest_metrics(self.bakery, self.provider(False), 30, now=now)


class TestOffMeansOff(LoopCase):
    """The clinic has the same kinds of accounts and the same kinds of files. It never said yes."""

    def test_every_step_does_nothing_and_says_how_to_turn_it_on(self):
        self.drop_clip(brand=self.clinic)
        for answer in (PR.plan_test_wave(self.clinic, save=True, today=TODAY), PR.read_results(self.clinic),
                       PR.pick_winner(self.clinic, "rye loaf"), PR.plan_promotion(self.clinic, save=True, today=TODAY),
                       PR.status(self.clinic)):
            self.assertIs(answer["enabled"], False)
            self.assertIn("test_and_promote", answer["message"])
        self.assertEqual(os.listdir(self.clinic.path("Output", "batches")), [])
        self.assertFalse(os.path.exists(PR.state_file(self.clinic).path))
        self.assertEqual(self.service.requests, [])

    def test_it_will_not_even_send_a_batch_someone_prepared_by_hand(self):
        path = self.batch(self.clinic, [self.post(self.clinic, "test-abc-def-person-tiktok", platform="tiktok")])
        answer = PR.send(self.clinic, path, self.provider(True), confirm=True)
        self.assertIs(answer["enabled"], False)
        self.assertEqual(self.service.requests, [])

    def test_only_the_exact_setting_turns_it_on(self):
        import copy
        for almost in ("true", 1, "yes", None, [True]):                  # a hand-edited file could say any of these
            data = copy.deepcopy(self.clinic.data)
            data["video"]["test_and_promote"] = almost
            self.assertIs(PR.is_on(brands.Brand(self.clinic.id, self.clinic.home, data)), False)
        with self.assertRaises(brands.BrandError):                       # and the settings refuse to save them
            brands.update("stride-physio", {"video": {"test_and_promote": "true"}})
        brands.update("stride-physio", {"video": {"test_and_promote": True}})
        self.assertIs(PR.is_on(brands.load("stride-physio")), True)

    def test_the_command_says_it_is_off_and_touches_nothing(self):
        with redirect_stdout(io.StringIO()) as out:
            rc = posting_cli.cli_promote(["--brand", "stride-physio", "--step", "test", "--save"])
        self.assertEqual(rc, 0)
        self.assertIn("is off", out.getvalue())
        self.assertEqual(self.service.requests, [])


class TestTheTestWave(LoopCase):
    def test_every_version_of_one_clip_goes_to_tiktok_on_one_day_spread_through_the_day(self):
        self.drop_clip()
        plan = PR.plan_test_wave(self.bakery, today=TODAY)
        self.assertIn("several times on purpose", plan["warning"])
        self.assertEqual({(p.identity, p.platform) for p in plan["posts"]}, {("person", "tiktok")})
        self.assertEqual({p.scheduled_time_local[:10] for p in plan["posts"]}, {"2030-01-02"})
        times = sorted(p.scheduled_time_local[-5:] for p in plan["posts"])
        self.assertEqual(times, ["06:30", "12:00", "18:00"])             # first, middle and last of the brand's windows
        self.assertEqual({p.text for p in plan["posts"]}, set(VERSIONS.values()))
        self.assertEqual(len({p.media_paths[0] for p in plan["posts"]}), 3)
        self.assertEqual((plan["saved"], os.listdir(self.bakery.path("Output", "batches"))), (False, []))

    def test_one_clip_a_day_the_slots_rotate_and_a_second_plan_adds_nothing(self):
        self.drop_clip("rye loaf")
        self.drop_clip("seeded loaf", {v: "Seeded. " + w for v, w in VERSIONS.items()})
        plan = PR.plan_test_wave(self.bakery, save=True, today=TODAY)
        self.assertEqual([w["day"] for w in plan["waves"]], ["2030-01-02", "2030-01-03"])
        first_slot = {w["clip"]: min(w["posts"], key=lambda p: p["time"])["video"] for w in plan["waves"]}
        self.assertNotEqual(first_slot["rye loaf"].split("__")[1], first_slot["seeded loaf"].split("__")[1])
        again = PR.plan_test_wave(self.bakery, save=True, today=TODAY)
        self.assertEqual((again["posts"], again["waves"]), ([], []))
        self.drop_clip("walnut loaf", {v: "Walnut. " + w for v, w in VERSIONS.items()})
        third = PR.plan_test_wave(self.bakery, save=True, today=TODAY)
        self.assertEqual([w["day"] for w in third["waves"]], ["2030-01-04"])    # after the days already taken

    def test_a_clip_that_is_not_ready_takes_no_day(self):
        self.drop_clip("a same words", {"one": "The very same words.", "two": "The very same words."})
        drop_video(self.bakery.path("Inputs", "Edited"), "b no words__one.mp4", "Only this one has words.")
        drop_video(self.bakery.path("Inputs", "Edited"), "b no words__two.mp4")
        self.drop_clip("rye loaf")
        plan = PR.plan_test_wave(self.bakery, today=TODAY)
        self.assertEqual([(w["clip"], w["day"]) for w in plan["waves"]], [("rye loaf", "2030-01-02")])
        why = {d["clip"]: d["why"] for d in plan["deferred"]}
        self.assertIn("same words", why["a same words"])
        self.assertIn("no description", why["b no words"])

    def test_a_single_video_is_not_a_test_and_the_daily_planner_keeps_it(self):
        drop_video(self.bakery.path("Inputs", "Edited"), "class day.mp4", "Saturday class, flour everywhere.")
        self.assertEqual(PR.plan_test_wave(self.bakery, today=TODAY)["posts"], [])
        self.assertEqual({p.topic_id for p in SH.plan_shorts(self.bakery, today=TODAY)["posts"]}, {"class day"})

    def test_with_two_tiktok_accounts_the_test_account_must_be_named(self):
        brands.update("maple-and-main", {"accounts": {"targets": TARGETS + [target("company", "tiktok", 102)]}})
        bakery = brands.load("maple-and-main")
        self.drop_clip()
        with self.assertRaises(PR.PromoteError) as cm:
            PR.plan_test_wave(bakery, today=TODAY)
        self.assertIn("Say which one", str(cm.exception))
        plan = PR.plan_test_wave(bakery, identity="company", today=TODAY)
        self.assertEqual({p.identity for p in plan["posts"]}, {"company"})
        with self.assertRaises(PR.PromoteError):
            PR.plan_test_wave(bakery, identity="baker", today=TODAY)

    def test_the_wave_is_sent_through_the_same_gates_and_only_with_confirm(self):
        self.drop_clip()
        plan = PR.plan_test_wave(self.bakery, save=True, today=TODAY)
        not_yet = PR.send(self.bakery, plan["batch"], self.provider(True), confirm=True)
        self.assertEqual((not_yet["counts"], self.writes()), ({"blocked": 3}, []))      # planned is not approved
        approve_batch(self.bakery, plan["batch"])
        dry = PR.send(self.bakery, plan["batch"], self.provider(False))
        self.assertEqual((dry["counts"], self.writes()), ({"would-send": 3}, []))
        real = PR.send(self.bakery, plan["batch"], self.provider(True), confirm=True)
        self.assertEqual(real["counts"], {"sent": 3})
        self.assertEqual(self.service.accounts_posted_to(), ["101"])
        self.assertEqual({b["providers"][0]["network"] for _a, b in self.service.accepted}, {"tiktok"})


class TestPickingAWinner(LoopCase):
    def test_results_are_tied_to_versions_by_the_services_post_id_and_the_rule_shows_its_numbers(self):
        self.drop_clip()
        sent = self.run_the_test_wave()
        self.assertEqual(self.results_arrive({"warm": 900, "fast": 2400, "plain": 60})["linked"], 3)
        rows = {r["post_id"]: r for r in R.load_archive(self.bakery)[0]}
        self.assertEqual(rows["TT-fast"]["post_id"], "TT-fast")          # the network's own number for the video...
        self.assertTrue(rows["TT-fast"]["provider_post_id"].startswith("90"))     # ...and the service's, used to join
        read = PR.read_results(self.bakery)["clips"][0]
        by_version = {v["version"]: v for v in read["versions"]}
        self.assertEqual([by_version[v]["views"] for v in ("warm", "fast", "plain")], [900, 2400, 60])
        answer = PR.pick_winner(self.bakery, "rye loaf")
        self.assertEqual(answer["winner"], sent["fast"])
        self.assertIn("views per hour", answer["reason"])
        self.assertIn("at least 100 views", answer["rule"])
        shown = PR.describe_numbers(answer)
        for number in ("2400 views", "900 views", "60 views", "WINNER fast"):
            self.assertIn(number, shown)
        logged, _bad = S.read_lines(os.path.join(self.bakery.state_dir, PR.DECISIONS_FILE))
        self.assertEqual([(d["clip"], d["winner"]) for d in logged], [("rye loaf", sent["fast"])])
        self.assertEqual(len(logged[0]["numbers"]), 3)                   # the decision is kept with its evidence
        self.assertEqual(PR.pick_winner(self.bakery, "rye loaf")["reason"], "a winner was already picked for this clip")
        self.assertEqual(len(S.read_lines(os.path.join(self.bakery.state_dir, PR.DECISIONS_FILE))[0]), 1)

    def test_views_per_hour_beats_raw_views(self):
        self.drop_clip()
        sent = self.run_the_test_wave()
        self.results_arrive({"warm": 1000, "fast": 900, "plain": 400},
                            created={"warm": "2030-01-02T11:30:00+0000", "fast": "2030-01-03T16:30:00+0000"})
        answer = PR.pick_winner(self.bakery, "rye loaf")                 # fast has been out half as long
        self.assertEqual(answer["winner"], sent["fast"])

    def test_nothing_below_the_floor_is_ever_promoted(self):
        self.drop_clip()
        self.run_the_test_wave()
        self.results_arrive({"warm": 99, "fast": 40, "plain": 12})
        answer = PR.pick_winner(self.bakery, "rye loaf")
        self.assertIsNone(answer["winner"])
        self.assertIn("no version reached 100 views", answer["reason"])
        self.assertEqual(PR.plan_promotion(self.bakery, save=True, today=TODAY)["posts"], [])
        self.assertEqual(S.read_lines(os.path.join(self.bakery.state_dir, PR.DECISIONS_FILE))[0], [])
        brands.update("maple-and-main", {"video": {"promote_min_views": 50}})           # the brand may move the floor
        self.assertIsNotNone(PR.pick_winner(brands.load("maple-and-main"), "rye loaf")["winner"])

    def test_a_version_under_the_floor_cannot_win_on_speed(self):
        self.drop_clip()
        sent = self.run_the_test_wave()
        self.results_arrive({"warm": 300, "fast": 90, "plain": 250}, created={"fast": "2030-01-03T16:00:00+0000"})
        self.assertEqual(PR.pick_winner(self.bakery, "rye loaf")["winner"], sent["warm"])

    def test_it_waits_for_a_full_day_of_results(self):
        self.drop_clip()
        self.run_the_test_wave()
        self.results_arrive({"warm": 900, "fast": 2400, "plain": 600}, now=datetime(2030, 1, 2, 22, 0, tzinfo=timezone.utc))
        answer = PR.pick_winner(self.bakery, "rye loaf")
        self.assertIsNone(answer["winner"])
        self.assertIn("hours of results", answer["reason"])

    def test_a_dead_heat_declares_no_winner(self):
        self.drop_clip()
        self.run_the_test_wave()
        self.results_arrive({"warm": 800, "fast": 800, "plain": 200})
        answer = PR.pick_winner(self.bakery, "rye loaf")
        self.assertIsNone(answer["winner"])
        self.assertIn("level", answer["reason"])

    def test_shares_break_a_tie_on_speed(self):
        self.drop_clip()
        sent = self.run_the_test_wave()
        self.service.results[("101", "tiktok")] = [tiktok_row("TT-warm", VERSIONS["warm"], 800, shares=2),
                                                   tiktok_row("TT-fast", VERSIONS["fast"], 800, shares=9),
                                                   tiktok_row("TT-plain", VERSIONS["plain"], 200)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=TWO_DAYS_ON)
        self.assertEqual(PR.pick_winner(self.bakery, "rye loaf")["winner"], sent["fast"])

    def test_similar_words_never_count_as_a_match(self):
        self.drop_clip()
        self.run_the_test_wave()
        almost = dict(VERSIONS, fast=VERSIONS["fast"] + " #bread")       # the network shows slightly different words
        self.assertEqual(self.results_arrive({"warm": 900, "fast": 2400, "plain": 600}, words=almost)["linked"], 2)
        read = {v["version"]: v for v in PR.read_results(self.bakery)["clips"][0]["versions"]}
        self.assertEqual((read["fast"]["measured"], read["fast"]["views"]), (False, 0))
        waiting = PR.pick_winner(self.bakery, "rye loaf")
        self.assertIsNone(waiting["winner"])
        self.assertIn("1 of 3 versions have no results yet", waiting["reason"])
        forced = PR.pick_winner(self.bakery, "rye loaf", allow_partial=True)      # a person may decide with what there is
        self.assertEqual(forced["numbers"][0]["views"] >= 0, True)
        self.assertIsNotNone(forced["winner"])

    def test_a_version_that_was_never_scheduled_holds_the_decision(self):
        self.drop_clip()
        plan = PR.plan_test_wave(self.bakery, save=True, today=TODAY)
        approve_batch(self.bakery, plan["batch"])
        PR.send(self.bakery, plan["batch"], self.provider(True), confirm=True, limit=2)
        self.results_arrive({"warm": 900, "fast": 2400, "plain": 600})
        answer = PR.pick_winner(self.bakery, "rye loaf")
        self.assertIsNone(answer["winner"])
        self.assertIn("have not been scheduled yet", answer["reason"])

    def test_another_brands_results_cannot_decide_this_brands_winner(self):
        self.drop_clip()
        self.run_the_test_wave()
        self.service.results[("555", "tiktok")] = [tiktok_row("TT-x", VERSIONS["fast"], 99999)]
        brands.update("stride-physio", {"video": {"test_and_promote": True}})
        R.harvest_metrics(brands.load("stride-physio"), self.provider(False), 30, now=TWO_DAYS_ON)
        self.assertEqual([v["measured"] for v in PR.read_results(self.bakery)["clips"][0]["versions"]], [False] * 3)


class TestPromotingTheWinner(LoopCase):
    def decided(self):
        self.drop_clip()
        sent = self.run_the_test_wave()
        self.results_arrive({"warm": 900, "fast": 2400, "plain": 60})
        PR.pick_winner(self.bakery, "rye loaf")
        return sent

    def test_the_winner_goes_to_the_other_platforms_never_back_to_tiktok(self):
        self.decided()
        plan = PR.plan_promotion(self.bakery, today=TODAY)
        self.assertEqual(sorted((p.identity, p.platform) for p in plan["posts"]),
                         [("company", "facebook"), ("person", "instagram"), ("person", "youtube")])
        self.assertEqual({p.media_paths[0] for p in plan["posts"]}, {"Inputs/Edited/rye loaf__fast.mp4"})
        self.assertEqual({p.text for p in plan["posts"]}, {VERSIONS["fast"]})
        days = [p.scheduled_time_local[:10] for p in plan["posts"]]
        self.assertEqual(len(days), len(set(days)))                      # never on two accounts the same day
        self.assertTrue(P.assert_drip(plan["posts"]))
        self.assertEqual(plan["saved"], False)

    def test_each_winner_is_promoted_once(self):
        self.decided()
        first = PR.plan_promotion(self.bakery, save=True, today=TODAY)
        self.assertEqual(len(first["posts"]), 3)
        self.assertEqual(PR.plan_promotion(self.bakery, save=True, today=TODAY)["posts"], [])     # planned: not again
        approve_batch(self.bakery, first["batch"])
        before = len(self.service.accepted)
        report = PR.send(self.bakery, first["batch"], self.provider(True), confirm=True)
        self.assertEqual(report["counts"], {"sent": 3})
        self.assertEqual(PR.plan_promotion(self.bakery, save=True, today=TODAY)["posts"], [])     # sent: not again
        PR.send(self.bakery, first["batch"], self.provider(True), confirm=True)
        self.assertEqual(len(self.service.accepted), before + 3)
        by_network = Counter(b["providers"][0]["network"] for _a, b in self.service.accepted[before:])
        self.assertEqual(by_network, {"instagram": 1, "youtube": 1, "facebook": 1})
        self.assertTrue(PR.read_results(self.bakery)["clips"][0]["promoted"])

    def test_promotions_share_the_daily_shorts_calendar(self):
        drop_video(self.bakery.path("Inputs", "Edited"), "class day.mp4", "Saturday class, flour everywhere.")
        daily = SH.plan_shorts(self.bakery, save=True, today=TODAY)
        taken = {(p.identity, p.platform): p.scheduled_time_local[:10] for p in daily["posts"]}
        self.decided()
        plan = PR.plan_promotion(self.bakery, save=True, today=TODAY)
        for p in plan["posts"]:
            self.assertGreater(p.scheduled_time_local[:10], taken[(p.identity, p.platform)])      # after the backlog

    def test_a_platform_with_no_words_for_the_winner_is_left_out_and_said(self):
        self.drop_clip()
        self.run_the_test_wave()
        self.results_arrive({"warm": 900, "fast": 2400, "plain": 60})
        PR.pick_winner(self.bakery, "rye loaf")
        inbox = self.bakery.path("Inputs", "Edited")
        os.replace(os.path.join(inbox, "rye loaf__fast.txt"), os.path.join(inbox, "rye loaf__fast.tiktok.txt"))
        plan = PR.plan_promotion(self.bakery, today=TODAY)               # the only words left were written for tiktok
        self.assertEqual(plan["posts"], [])
        self.assertEqual(sorted(n["platform"] for n in plan["needs_description"]), ["facebook", "instagram", "youtube"])

    def test_the_command_warns_and_previews_by_default(self):
        self.decided()
        with mock.patch.object(A, "open_provider", lambda brand, allow_writes=False, opener=None: self.provider(allow_writes)):
            writes = len(self.writes())
            with redirect_stdout(io.StringIO()) as out:
                rc = posting_cli.cli_promote(["--brand", "maple-and-main", "--step", "winners"])
            self.assertEqual(rc, 0)
            self.assertIn("several times on purpose", out.getvalue())
            self.assertIn("PREVIEW", out.getvalue())
            self.assertEqual(len(self.writes()), writes)
            with redirect_stdout(io.StringIO()) as out:
                posting_cli.cli_promote(["--brand", "maple-and-main"])
            self.assertIn("winner picked", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
