"""Daily shorts tests: any folder is an inbox, a video never borrows another platform's words,
bookings resume after the backlog and never double up, a long video is never planned as a short,
and a shorts batch is sent through exactly the same gates as any other batch.

    python -m unittest discover -s tests -t . -v

Every video here is an invented header with no pictures in it.
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
from smf.posting import send as SEND                                      # noqa: E402
from smf.posting import shorts as SH                                      # noqa: E402
from smf.posting.ledger import Ledger                                     # noqa: E402
from smf.posting.state import StateError                                  # noqa: E402
from smf.studio import posts as P                                         # noqa: E402
from tests.posting_fakes import (SendCase, approve_batch, brand_answers, drop_video, statuses, target,  # noqa: E402
                                 video_bytes)
from tests.test_brands import BAKERY, CLINIC                              # noqa: E402

TODAY = date(2030, 1, 1)
EARLY = datetime(2029, 12, 1, tzinfo=timezone.utc)
VIDEO_TARGETS = [target("person", "instagram", 101), target("person", "tiktok", 101),
                 target("person", "youtube", 101), target("company", "facebook", 102)]
WORDS = {"rye loaf": "Why our rye takes three days.", "class day": "Saturday class, flour everywhere.",
         "oven tour": "A look inside the deck oven.", "crumb shot": "What an open crumb tells you.",
         "scoring": "Four cuts, and why they matter."}


def days_by_account(plan):
    out = {}
    for p in plan["posts"]:
        out.setdefault((p.identity, p.platform), []).append(p.scheduled_time_local[:10])
    return out


class ShortsCase(SendCase):
    BAKERY_ANSWERS = brand_answers(BAKERY, targets=VIDEO_TARGETS)
    CLINIC_ANSWERS = brand_answers(CLINIC, targets=[target("person", "instagram", 555), target("person", "tiktok", 555)])

    def inbox(self, brand=None):
        return (brand or self.bakery).path("Inputs", "Edited")

    def drop(self, *names, brand=None, **kw):
        for name in names:
            drop_video(self.inbox(brand), name + ".mp4", WORDS.get(name, "Words for %s." % name), **kw)

    def plan(self, brand=None, **kw):
        kw.setdefault("today", TODAY)
        return SH.plan_shorts(brand or self.bakery, **kw)


class TestReadingAVideo(unittest.TestCase):
    def probe(self, *args, **kw):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="vidéo ' ") as d:
            path = os.path.join(d, "clip.mp4")
            Path(path).write_bytes(video_bytes(*args, **kw))
            return SH.probe_video(path)

    def test_size_and_length_come_from_the_files_own_header(self):
        self.assertEqual(self.probe(1080, 1920, 42), {"width": 1080, "height": 1920, "seconds": 42.0})

    def test_a_phone_video_stored_sideways_is_read_the_way_it_is_shown(self):
        info = self.probe(1920, 1080, 42, turned=True)
        self.assertEqual((info["width"], info["height"]), (1080, 1920))
        self.assertEqual(SH.classify(info), "short")

    def test_only_wide_and_longer_than_three_minutes_is_long_form(self):
        self.assertEqual(SH.classify(self.probe(1920, 1080, 600)), "long")
        self.assertEqual(SH.classify(self.probe(1920, 1080, 181)), "long")
        self.assertEqual(SH.classify(self.probe(1920, 1080, 180)), "short")      # wide but brief
        self.assertEqual(SH.classify(self.probe(1080, 1920, 600)), "short")      # tall, however long
        self.assertEqual(SH.classify(self.probe(1080, 1080, 600)), "short")      # square

    def test_a_file_that_cannot_be_read_is_unknown_never_a_guess(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for name, blob in (("noise.mp4", b"this is not a video at all"), ("empty.mp4", b""),
                               ("cut-off.mp4", video_bytes(1080, 1920, 42)[:40])):
                Path(d, name).write_bytes(blob)
                self.assertIsNone(SH.probe_video(os.path.join(d, name)), name)
            self.assertIsNone(SH.probe_video(os.path.join(d, "not-there.mp4")))
        self.assertEqual(SH.classify(None), "unknown")


class TestTheInboxIsJustAFolder(ShortsCase):
    def test_videos_are_found_in_folders_with_awkward_names_and_paired_with_their_words(self):
        awkward = os.path.join(self.inbox(), "Ava's été cuts (final)")
        drop_video(awkward, "pain de campagne.mp4", "Trois jours pour un pain.")
        drop_video(self.inbox(), "no words yet.mp4")
        Path(self.inbox(), ".hidden.mp4").write_bytes(video_bytes(1080, 1920, 10))
        Path(self.inbox(), "notes.txt").write_text("not a video", encoding="utf-8")
        found = SH.discover(self.bakery)
        self.assertEqual([c["key"] for c in found["clips"]], ["Ava's été cuts (final)/pain de campagne", "no words yet"])
        plan = self.plan()
        self.assertEqual({p.text for p in plan["posts"]}, {"Trois jours pour un pain."})
        self.assertEqual(plan["needs_description"][0]["clip"], "no words yet")
        self.assertTrue(all(p.media_paths[0].startswith("Inputs/Edited/Ava's été cuts (final)/") for p in plan["posts"]))

    def test_words_written_for_one_platform_are_never_borrowed_for_another(self):
        drop_video(self.inbox(), "rye loaf.mp4", tiktok="Three days. One loaf. #bread")     # tiktok words only
        plan = self.plan()
        self.assertEqual([(p.platform, p.text) for p in plan["posts"]], [("tiktok", "Three days. One loaf. #bread")])
        self.assertEqual(plan["needs_description"], [{"clip": "rye loaf", "platforms": ["facebook", "instagram", "youtube"]}])

    def test_a_platform_file_beats_the_general_one_for_that_platform_only(self):
        drop_video(self.inbox(), "rye loaf.mp4", "Why our rye takes three days.", youtube="Rye bread: the three day method")
        by_platform = {p.platform: p.text for p in self.plan()["posts"]}
        self.assertEqual(by_platform["youtube"], "Rye bread: the three day method")
        self.assertEqual(by_platform["instagram"], "Why our rye takes three days.")

    def test_a_preview_writes_nothing_anywhere(self):
        self.drop("rye loaf", "class day")
        plan = self.plan()
        self.assertEqual((plan["saved"], plan["batch"], len(plan["posts"])), (False, None, 8))
        self.assertEqual(os.listdir(self.bakery.path("Output", "batches")), [])
        self.assertFalse(os.path.exists(SH.state_file(self.bakery).path))
        self.assertEqual(self.service.requests, [])                      # planning is offline

    def test_an_outside_folder_is_copied_in_only_when_the_plan_is_saved(self):
        outside = os.path.join(self.tmp.name, "Cloud Drive", "Ava's finished cuts")
        drop_video(outside, "rye loaf.mp4", WORDS["rye loaf"])
        brands.update("maple-and-main", {"video": {"inbox_folder": outside}})
        bakery = brands.load("maple-and-main")
        original = Path(outside, "rye loaf.mp4").read_bytes()
        self.plan(bakery)
        self.assertFalse(os.path.exists(bakery.path("Inputs", "Edited", "rye loaf.mp4")))
        plan = self.plan(bakery, save=True)
        self.assertEqual({p.media_paths[0] for p in plan["posts"]}, {"Inputs/Edited/rye loaf.mp4"})
        self.assertEqual(Path(bakery.path("Inputs", "Edited", "rye loaf.mp4")).read_bytes(), original)
        self.assertEqual(Path(outside, "rye loaf.mp4").read_bytes(), original)       # the original is untouched
        self.assertEqual(sorted(os.listdir(outside)), ["rye loaf.mp4", "rye loaf.txt"])
        approve_batch(bakery, plan["batch"])                             # and the copy passes the media gate
        report = SEND.schedule_batch(bakery, plan["batch"], self.provider(False), now=EARLY)
        self.assertEqual(report["counts"], {"would-send": 4})

    def test_a_re_exported_video_never_silently_replaces_the_one_brought_in_before(self):
        outside = os.path.join(self.tmp.name, "Cloud Drive")
        drop_video(outside, "rye loaf.mp4", WORDS["rye loaf"])
        brands.update("maple-and-main", {"video": {"inbox_folder": outside}})
        bakery = brands.load("maple-and-main")
        os.makedirs(bakery.path("Inputs", "Edited"), exist_ok=True)
        Path(bakery.path("Inputs", "Edited", "rye loaf.mp4")).write_bytes(b"an older, different cut")
        plan = self.plan(bakery, save=True)
        self.assertEqual(plan["posts"], [])
        self.assertIn("different video with the same name", plan["needs_a_look"][0]["why"])
        self.assertEqual(Path(bakery.path("Inputs", "Edited", "rye loaf.mp4")).read_bytes(), b"an older, different cut")

    def test_another_brands_folder_a_climbing_path_and_a_missing_folder_are_refused(self):
        for bad, words in ((self.clinic.path("Inputs", "Edited"), "another brand"),
                           ("../stride-physio/Inputs/Edited", "climbs out"),
                           (os.path.join(self.tmp.name, "not there"), "could not be found"),
                           ("", "has not said where")):
            brands.update("maple-and-main", {"video": {"inbox_folder": bad}})
            with self.assertRaises(SH.ShortsError) as cm:
                self.plan(brands.load("maple-and-main"))
            self.assertIn(words, str(cm.exception))

    def test_each_brand_only_ever_sees_its_own_videos(self):
        self.drop("rye loaf")
        self.drop("calf raises", brand=self.clinic)
        self.assertEqual({p.topic_id for p in self.plan()["posts"]}, {"rye loaf"})
        clinic = self.plan(self.clinic)
        self.assertEqual({p.topic_id for p in clinic["posts"]}, {"calf raises"})
        self.assertEqual({p.brand for p in clinic["posts"]}, {"stride-physio"})


class TestBooking(ShortsCase):
    def test_one_a_day_per_account_and_a_clip_is_never_on_two_accounts_the_same_day(self):
        self.drop("rye loaf", "class day", "oven tour", "crumb shot")
        plan = self.plan()
        self.assertEqual(len(plan["posts"]), 16)                         # 4 clips x 4 accounts, each exactly once
        for account, days in days_by_account(plan).items():
            self.assertEqual(len(days), len(set(days)), account)         # one a day on every account
            self.assertEqual(min(days), "2030-01-02")                    # starting tomorrow
        clip_days = Counter((p.topic_id, p.scheduled_time_local[:10]) for p in plan["posts"])
        self.assertEqual(max(clip_days.values()), 1)
        self.assertTrue(P.assert_drip(plan["posts"]))
        self.assertEqual({p.media_type for p in plan["posts"] if p.platform in ("instagram", "facebook")}, {"reel"})

    def test_new_videos_are_booked_after_the_backlog_and_nothing_is_booked_twice(self):
        self.drop("rye loaf", "class day", "oven tour")
        first = self.plan(save=True)
        self.assertEqual(len(first["posts"]), 12)
        self.assertEqual(self.plan()["posts"], [])                       # running it again plans nothing new
        self.drop("crumb shot", "scoring")
        second = self.plan(save=True)
        self.assertEqual({p.topic_id for p in second["posts"]}, {"crumb shot", "scoring"})
        before, after = days_by_account(first), days_by_account(second)
        for account in before:
            self.assertGreater(min(after[account]), max(before[account]), account)      # after the backlog
            both = before[account] + after[account]
            self.assertEqual(len(both), len(set(both)), account)                       # never two on one day
        every = first["posts"] + second["posts"]
        self.assertEqual(max(Counter((p.topic_id, p.scheduled_time_local[:10]) for p in every).values()), 1)
        self.assertEqual(len({p.id for p in every}), 20)

    def test_a_gap_left_earlier_is_not_back_filled(self):
        self.drop("rye loaf")
        self.plan(save=True, start="2030-01-10")
        self.drop("class day")
        later = self.plan(save=True)
        self.assertTrue(all(d >= "2030-01-10" for days in days_by_account(later).values() for d in days))

    def test_tiktok_can_take_more_than_one_a_day_and_the_others_stay_at_one(self):
        self.drop("rye loaf", "class day", "oven tour", "crumb shot", "scoring", "proofing", "shaping", "steam")
        plan = self.plan(per_day={"tiktok": 3})
        days = days_by_account(plan)
        self.assertEqual(max(Counter(days[("person", "tiktok")]).values()), 3)
        self.assertLess(max(days[("person", "tiktok")]), max(days[("person", "instagram")]))   # tiktok runs ahead
        clip_days = Counter((p.topic_id, p.scheduled_time_local[:10]) for p in plan["posts"])
        self.assertEqual(max(clip_days.values()), 1)                     # and still never a clip twice in a day
        self.assertEqual(max(Counter(days[("person", "instagram")]).values()), 1)
        tiktok_times = [p.scheduled_time_local for p in plan["posts"] if p.platform == "tiktok"]
        self.assertEqual(len(tiktok_times), len(set(tiktok_times)))      # never two at the same minute
        brands.update("maple-and-main", {"video": {"shorts_per_day": {"tiktok": 2}}})     # or from the settings
        settled = self.plan(brands.load("maple-and-main"))
        self.assertEqual(max(Counter(days_by_account(settled)[("person", "tiktok")]).values()), 2)
        for bad in ({"tiktok": 0}, {"tiktok": 99}, {"tiktok": True}, {"myspace": 2}):
            with self.assertRaises(SH.ShortsError):
                self.plan(per_day=bad)

    def test_only_so_many_days_are_planned_at_once_and_the_rest_wait(self):
        self.drop("rye loaf", "class day", "oven tour", "crumb shot", "scoring")
        plan = self.plan(days=2)
        self.assertTrue(all(len(days) <= 2 for days in days_by_account(plan).values()))
        self.assertGreater(plan["held_for_later"], 0)

    def test_the_posting_record_alone_is_enough_to_resume(self):
        self.drop("rye loaf", "class day")
        first = self.plan(save=True)
        approve_batch(self.bakery, first["batch"])
        SEND.schedule_batch(self.bakery, first["batch"], self.provider(True), confirm=True, now=EARLY)
        os.unlink(SH.state_file(self.bakery).path)                       # the planner's own notes are lost
        os.unlink(first["batch"])
        self.drop("oven tour")
        again = self.plan()
        self.assertEqual({p.topic_id for p in again["posts"]}, {"oven tour"})
        for account, days in days_by_account(again).items():
            self.assertGreater(min(days), max(days_by_account(first)[account]))

    def test_a_short_booked_from_somewhere_else_is_seen_on_the_services_calendar(self):
        self.drop("rye loaf", "class day")
        self.service.calendar["101"] = [
            {"id": 4001, "text": WORDS["rye loaf"], "publicationDate": {"dateTime": "2030-01-04T09:00:00"},
             "providers": [{"network": "instagram", "status": "PENDING"}], "draft": False},
            {"id": 4002, "text": "Nothing to do with any video.", "publicationDate": {"dateTime": "2030-01-05T09:00:00"},
             "providers": [{"network": "instagram", "status": "PENDING"}], "draft": False}]
        plan = self.plan(provider=self.provider(False))
        insta = [(p.topic_id, p.scheduled_time_local[:10]) for p in plan["posts"] if p.platform == "instagram"]
        self.assertEqual(insta, [("class day", "2030-01-05")])           # rye loaf is already there; resume after it
        self.assertIn("rye loaf", {p.topic_id for p in plan["posts"] if p.platform == "tiktok"})
        self.assertEqual(self.writes(), [])
        self.service.calendar_is_down = True
        offline = self.plan(provider=self.provider(False))
        self.assertIn("could not be read", " ".join(offline["notes"]))

    def test_a_turned_down_short_is_not_planned_again_and_frees_its_day(self):
        self.drop("rye loaf")
        first = self.plan(save=True)
        posts, meta = P.load_batch(first["batch"], self.bakery.id)
        turned_down = next(p for p in posts if p.platform == "instagram")
        turned_down.status = "rejected"
        P.save_batch(posts, first["batch"], meta)
        self.drop("class day")
        again = self.plan()
        self.assertNotIn(("rye loaf", "instagram"), {(p.topic_id, p.platform) for p in again["posts"]})
        self.assertEqual(days_by_account(again)[("person", "instagram")], ["2030-01-02"])

    def test_a_damaged_booking_record_stops_planning_and_is_not_overwritten(self):
        self.drop("rye loaf")
        self.plan(save=True)
        path = SH.state_file(self.bakery).path
        Path(path).write_text("{ not json", encoding="utf-8")
        self.drop("class day")
        for save in (False, True):
            with self.assertRaises(StateError) as cm:
                self.plan(save=save)
            self.assertIn("damaged", str(cm.exception))
        self.assertEqual(Path(path).read_text(encoding="utf-8"), "{ not json")
        Path(path).write_text('{"brand": "stride-physio", "bookings": {}}', encoding="utf-8")
        with self.assertRaises(StateError):
            self.plan()

    def test_versions_of_one_clip_are_one_clip_and_each_account_gets_a_different_cut(self):
        for version in ("warm", "fast", "plain"):
            drop_video(self.inbox(), "rye loaf__%s.mp4" % version)
        Path(self.inbox(), "rye loaf.txt").write_text(WORDS["rye loaf"], encoding="utf-8")     # the clip's own words
        plan = self.plan()
        self.assertEqual({p.topic_id for p in plan["posts"]}, {"rye loaf"})
        self.assertEqual(len(plan["posts"]), 4)                          # once per account, not once per file
        self.assertEqual(len({p.media_paths[0] for p in plan["posts"]}), 3)
        self.assertEqual(max(Counter(p.scheduled_time_local[:10] for p in plan["posts"]).values()), 1)

    def test_with_the_loop_on_clips_with_several_versions_are_left_to_it(self):
        brands.update("maple-and-main", {"video": {"test_and_promote": True}})
        bakery = brands.load("maple-and-main")
        for version in ("warm", "fast"):
            drop_video(self.inbox(), "rye loaf__%s.mp4" % version, "Rye, %s." % version)
        self.drop("class day")
        plan = self.plan(bakery)
        self.assertEqual({p.topic_id for p in plan["posts"]}, {"class day"})
        self.assertEqual(plan["left_to_the_loop"], ["rye loaf"])


class TestLongForm(ShortsCase):
    def test_a_long_wide_video_goes_to_youtube_as_a_video_and_nowhere_else(self):
        self.drop("rye loaf")
        drop_video(self.inbox(), "bakery story.mp4", "How we built the bakery.\nA longer description.",
                   width=1920, height=1080, seconds=900)
        plan = self.plan()
        story = [p for p in plan["posts"] if p.topic_id == "bakery story"]
        self.assertEqual([(p.platform, p.media_type, p.shape) for p in story], [("youtube", "video", "long-video")])
        self.assertTrue(story[0].id.startswith("long-"))
        body = self.provider(False).build_body(story[0], ["u"], self.bakery.timezone)
        self.assertEqual(body["youtubeData"]["type"], "video")
        short = next(p for p in plan["posts"] if p.topic_id == "rye loaf" and p.platform == "youtube")
        self.assertEqual(self.provider(False).build_body(short, ["u"], self.bakery.timezone)["youtubeData"]["type"], "short")

    def test_with_no_youtube_account_a_long_video_is_reported_not_squeezed_in_as_a_short(self):
        drop_video(self.inbox(self.clinic), "gait talk.mp4", "Forty minutes on gait.", width=1920, height=1080, seconds=2400)
        plan = self.plan(self.clinic)
        self.assertEqual(plan["posts"], [])
        self.assertIn("only goes to YouTube", plan["needs_a_look"][0]["why"])

    def test_a_video_that_cannot_be_read_is_listed_for_a_person_and_left_out(self):
        Path(self.inbox(), "mystery.mp4").write_bytes(b"not a real video")
        Path(self.inbox(), "mystery.txt").write_text("Words.", encoding="utf-8")
        plan = self.plan()
        self.assertEqual(plan["posts"], [])
        self.assertEqual(plan["needs_a_look"][0]["clip"], "mystery")


class TestSendingAShortsBatch(ShortsCase):
    def test_a_shorts_batch_goes_through_the_same_gates_and_ledger_as_any_other(self):
        self.drop("rye loaf")
        plan = self.plan(save=True)
        self.assertEqual(set(statuses(self.bakery, plan["batch"]).values()), {"lint_pass"})
        waiting = SEND.schedule_batch(self.bakery, plan["batch"], self.provider(True), confirm=True, now=EARLY)
        self.assertEqual(waiting["counts"], {"blocked": 4})              # planned is not approved
        self.assertEqual(self.writes(), [])
        approve_batch(self.bakery, plan["batch"])
        dry = SEND.schedule_batch(self.bakery, plan["batch"], self.provider(False), now=EARLY)
        self.assertEqual((dry["counts"], self.writes()), ({"would-send": 4}, []))
        sent = SEND.schedule_batch(self.bakery, plan["batch"], self.provider(True), confirm=True, now=EARLY)
        self.assertEqual(sent["counts"], {"sent": 4})
        by_account = Counter(acct for acct, _body in self.service.accepted)
        self.assertEqual(by_account, {"101": 3, "102": 1})               # person's three on 101, the company's on 102
        reel = next(body for _a, body in self.service.accepted if body["providers"][0]["network"] == "instagram")
        self.assertEqual(reel["instagramData"]["type"], "REEL")
        self.assertEqual(len(Ledger(self.bakery).all()), 4)
        again = SEND.schedule_batch(self.bakery, plan["batch"], self.provider(True), confirm=True, now=EARLY)
        self.assertEqual((again["counts"], len(self.service.accepted)), ({"skipped": 4}, 4))

    def test_an_edited_description_after_approval_is_stopped_like_any_other_edit(self):
        self.drop("rye loaf")
        plan = self.plan(save=True)
        posts = approve_batch(self.bakery, plan["batch"])
        posts[0].text = "Different words, never approved."
        P.save_batch(posts, plan["batch"])
        report = SEND.schedule_batch(self.bakery, plan["batch"], self.provider(True), confirm=True, now=EARLY)
        self.assertEqual(report["counts"], {"blocked": 1, "sent": 3})

    def test_two_brands_shorts_never_reach_each_others_accounts(self):
        self.drop("rye loaf")
        self.drop("calf raises", brand=self.clinic)
        for brand in (self.bakery, self.clinic):
            plan = self.plan(brand, save=True)
            approve_batch(brand, plan["batch"])
            SEND.schedule_batch(brand, plan["batch"], self.provider(True), confirm=True, now=EARLY)
        where = {(acct, body["text"]) for acct, body in self.service.accepted}
        self.assertEqual({acct for acct, text in where if "rye" in text}, {"101", "102"})
        self.assertEqual({acct for acct, text in where if "calf" in text}, {"555"})

    def test_the_command_previews_by_default_and_never_sends_without_confirm(self):
        self.drop("rye loaf")
        with mock.patch.object(A, "open_provider", lambda brand, allow_writes=False, opener=None: self.provider(allow_writes)):
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(posting_cli.cli_shorts(["--brand", "maple-and-main"]), 0)
            self.assertIn("PREVIEW", out.getvalue())
            self.assertEqual(os.listdir(self.bakery.path("Output", "batches")), [])
            with redirect_stdout(io.StringIO()):
                posting_cli.cli_shorts(["--brand", "maple-and-main", "--save"])
            batch = self.bakery.path("Output", "batches", os.listdir(self.bakery.path("Output", "batches"))[0])
            approve_batch(self.bakery, batch)
            with redirect_stdout(io.StringIO()) as out:
                posting_cli.cli_shorts(["--brand", "maple-and-main", "--send", batch])
            self.assertIn("DRY RUN", out.getvalue())
        self.assertEqual(self.writes(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
