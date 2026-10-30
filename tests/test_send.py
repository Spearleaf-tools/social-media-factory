"""Sending tests: a dry run writes nothing, every gate blocks with its reason, a crash or an
unclear answer can never become a double post, and one brand's words can never reach another
brand's account.

    python -m unittest discover -s tests -t . -v

Every account, id, response and number here is invented.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                    # noqa: E402
from smf.brands import BrandError                                         # noqa: E402
from smf.posting import accounts as A                                     # noqa: E402
from smf.posting import hand_posted as H                                  # noqa: E402
from smf.posting import posting_cli                                       # noqa: E402
from smf.posting import results as R                                      # noqa: E402
from smf.posting import send as SEND                                      # noqa: E402
from smf.posting import state as S                                        # noqa: E402
from smf.posting import ledger as LEDGER                                  # noqa: E402
from smf.posting.ledger import Ledger, LedgerError, operation_key         # noqa: E402
from smf.studio import posts as P                                         # noqa: E402
from smf.studio import proof                                              # noqa: E402
from tests.posting_fakes import (SendCase, Service, approve, brand_answers, http_error, statuses,  # noqa: E402
                                 target)
from tests.test_brands import BAKERY                                      # noqa: E402


def outcome(report, post_id):
    return next(r for r in report["posts"] if r["id"] == post_id)


def AFTER_THE_WAIT():
    """A moment far enough past a send that an empty calendar really does mean it never arrived.
    Sooner than this, a calendar that has not caught up yet is not evidence of anything."""
    return time.time() + LEDGER.NOT_FOUND_AFTER_SECONDS + 60


class TestADryRunIsDry(SendCase):
    def test_a_whole_batch_is_described_exactly_and_nothing_leaves_the_computer(self):
        posts = [self.post(self.bakery, "p1"),
                 self.post(self.bakery, "p2", text="Seeded loaves sell out by ten.", when="2030-01-06T15:00:00Z"),
                 self.post(self.bakery, "p3", text="Class places open on Friday.", when="2030-01-07T15:00:00Z")]
        path = self.batch(self.bakery, posts)
        before = Path(path).read_bytes()
        provider = self.provider(allow_writes=False)
        report = SEND.schedule_batch(self.bakery, path, provider)
        self.assertEqual(self.writes(), [])                              # not one upload, draft or schedule call
        self.assertEqual(provider.transport.writes, 0)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["counts"], {"would-send": 3})
        row = outcome(report, "p1")
        self.assertEqual((row["identity"], row["platform"], row["provider_brand_id"]), ("person", "instagram", 101))
        self.assertEqual(row["when"], "2030-01-05 10:00")               # shown on the brand's own clock
        self.assertEqual(row["request"]["text"], "Rye is out at seven.")
        self.assertIs(row["request"]["draft"], False)
        self.assertEqual(row["media"], ["card.png"])
        self.assertEqual(Path(path).read_bytes(), before)                # the batch file was not touched
        self.assertEqual(Ledger(self.bakery).all(), {})                  # and nothing was reserved
        self.assertIn("DRY RUN", SEND.describe(report))

    def test_without_confirm_nothing_is_sent_even_by_a_connection_that_could_write(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        SEND.schedule_batch(self.bakery, path, self.provider(allow_writes=True))
        self.assertEqual(self.writes(), [])

    def test_a_dry_run_works_with_no_connection_at_all(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        report = SEND.schedule_batch(self.bakery, path, None)
        self.assertEqual(report["counts"], {"would-send": 1})
        self.assertEqual(self.service.requests, [])

    def test_confirm_with_a_connection_that_cannot_write_stops_before_reserving_anything(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        with self.assertRaises(SEND.SendError) as cm:
            SEND.schedule_batch(self.bakery, path, self.provider(allow_writes=False), confirm=True)
        self.assertIn("dry run", str(cm.exception))
        self.assertEqual(self.writes(), [])
        self.assertEqual(Ledger(self.bakery).all(), {})

    def test_the_command_is_a_dry_run_unless_confirm_is_typed(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        made = []

        def fake_open(brand, allow_writes=False, opener=None):
            made.append(allow_writes)
            return self.provider(allow_writes)

        with mock.patch.object(A, "open_provider", fake_open), redirect_stdout(io.StringIO()) as out:
            rc = posting_cli.cli_schedule(["--brand", "maple-and-main", "--batch", path])
        self.assertEqual((rc, made, self.writes()), (0, [False], []))
        self.assertIn("Nothing was sent", out.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            posting_cli.cli_schedule(["--batch", path])                  # no brand named: refused, never guessed


class TestEveryGateBlocksWithItsReason(SendCase):
    def blocked(self, post, gate_name, *words, brand=None):
        brand = brand or self.bakery
        path = self.batch(brand, [post])
        report = SEND.schedule_batch(brand, path, self.provider(True), confirm=True)
        row = outcome(report, post.id)
        self.assertEqual(row["outcome"], "blocked", row)
        self.assertIn(gate_name, row["gates"])
        for w in words:
            self.assertIn(w, " ".join(row["reasons"]))
        self.assertEqual(self.writes(), [])                              # a blocked post sends nothing
        self.assertEqual(Ledger(brand).all(), {})                        # and reserves nothing
        self.assertEqual(statuses(brand, path)[post.id], post.status)    # and is left exactly as it was
        return row

    def test_status_only_approved_posts_go(self):
        for status in ("draft", "lint_pass", "rejected", "regen_queued", "blocked"):
            p = self.post(self.bakery, "p-" + status, approved=False)
            p.status = status
            row = self.blocked(p, "status", "not been approved")
            self.assertEqual(row["gates"], ["status"])

    def test_approval_an_edit_to_the_words_after_approval_voids_it(self):
        p = self.post(self.bakery)
        p.text = "Rye is out at six."                                    # changed after the person said yes
        self.blocked(p, "approval", "changed after it was approved")

    def test_approval_swapping_the_picture_after_approval_voids_it_too(self):
        p = self.post(self.bakery)
        p.media_paths = [self.card(self.bakery, "another.png")]
        self.blocked(p, "approval", "changed after it was approved")

    def test_approval_a_thread_first_comment_or_link_change_counts_as_an_edit(self):
        for change in ({"first_comment": "new link"}, {"link": "https://example.com/new"}, {"alt_text": "new"}):
            p = self.post(self.bakery)
            for k, v in change.items():
                setattr(p, k, v)
            self.blocked(p, "approval")

    def test_copy_the_check_is_run_again_with_this_brands_own_rules(self):
        p = self.post(self.bakery, text="Better bread than Harbour Street Cafe.")     # the bakery's never-mention name
        self.assertTrue(P.approval_is_current(p))                        # approved, and still the brand says no
        self.blocked(p, "copy", "copy check")
        same_words = self.post(self.clinic, text="Better bread than Harbour Street Cafe.")
        path = self.batch(self.clinic, [same_words])                     # not on the clinic's list: its rules differ
        report = SEND.schedule_batch(self.clinic, path, self.provider(False))
        self.assertEqual(outcome(report, "p1")["outcome"], "would-send")

    def test_copy_a_post_with_no_words_is_refused(self):
        self.blocked(self.post(self.bakery, text="  "), "copy", "no words")

    def test_time_a_slot_that_has_passed_is_refused(self):
        self.blocked(self.post(self.bakery, when="2020-01-05T15:00:00Z"), "time", "in the past")
        self.blocked(self.post(self.bakery, when=""), "time", "no scheduled time")

    def test_facts_unchecked_facts_need_the_reviewers_written_confirmation(self):
        p = self.post(self.bakery, approved=False)
        p.status, p.approved_at, p.approved_text_sha = "approved", "2029-12-01T09:00:00Z", P.approval_sha(p)
        self.assertEqual(p.sourcing, "unverified")
        self.blocked(p, "facts", "have not been checked")
        ok = approve(self.post(self.bakery, "p2", approved=False), facts_checked=False)     # confirmation on record
        report = SEND.schedule_batch(self.bakery, self.batch(self.bakery, [ok], "b2.json"), self.provider(False))
        self.assertEqual(outcome(report, "p2")["outcome"], "would-send")

    def test_facts_a_failed_fact_check_blocks_even_with_a_confirmation(self):
        p = approve(self.post(self.bakery, approved=False), facts_checked=False)
        p.sourcing = "blocked"
        self.blocked(p, "facts", "does not match")

    def test_media_missing_outside_and_uncleared_files_are_refused(self):
        self.blocked(self.post(self.bakery, media=["Output/visuals/gone.png"]), "media", "not where the post says")
        outside = os.path.join(self.tmp.name, "loose.png")
        Path(outside).write_bytes(b"x")
        self.blocked(self.post(self.bakery, media=[outside]), "media", "not inside this brand's folder")
        theirs = self.card(self.clinic, "clinic.png")                    # a real file, in the OTHER brand's folder
        self.blocked(self.post(self.bakery, media=[self.clinic.path(*theirs.split("/"))]), "media",
                     "not inside this brand's folder")
        self.blocked(self.post(self.bakery, media=["../stride-physio/" + theirs]), "media",
                     "not inside this brand's folder")

    def test_media_the_consent_rule_decides_for_files_from_the_proof_folder(self):
        folder = self.bakery.path("Inputs", "Proof")
        Path(folder, "thank-you-note.png").write_bytes(b"x")
        self.blocked(self.post(self.bakery, media=["Inputs/Proof/thank-you-note.png"]), "media", "no proof item")
        private = os.path.join(self.tmp.name, "private.png")
        Path(private).write_bytes(b"y")
        proof.add(self.bakery, "testimonial", "A customer's note", source="handed over at the counter, March",
                  file_path=private, may_publish="no")
        self.blocked(self.post(self.bakery, media=["Inputs/Proof/private.png"]), "media", "do not publish")
        cleared = os.path.join(self.tmp.name, "cleared.png")
        Path(cleared).write_bytes(b"z")
        proof.add(self.bakery, "photo", "The Saturday queue", source="taken by the owner", file_path=cleared,
                  may_publish="yes")
        ok = self.post(self.bakery, "p9", media=["Inputs/Proof/cleared.png"])
        report = SEND.schedule_batch(self.bakery, self.batch(self.bakery, [ok], "b9.json"), self.provider(False))
        self.assertEqual(outcome(report, "p9")["outcome"], "would-send")

    def test_account_no_such_account_is_never_borrowed_from_anywhere(self):
        self.blocked(self.post(self.bakery, platform="linkedin", identity="person", media=[]), "account",
                     "no linkedin account linked")
        self.blocked(self.post(self.clinic, platform="facebook"), "account", "no facebook account linked",
                     brand=self.clinic)                                  # the bakery has facebook; the clinic must not get it


class TestAccountStates(SendCase):
    BAKERY_ANSWERS = brand_answers(BAKERY, targets=[
        target("person", "instagram", 101),
        target("person", "tiktok", 101, connected=False),                # linked, but switched off
        target("company", "facebook", None),                             # never matched to the service
        target("company", "instagram", 777),                             # an id this key cannot see
        target("company", "linkedin", 102)])                             # the service says 102 has no linkedin

    def check(self, identity, platform, *words):
        p = self.post(self.bakery, identity=identity, platform=platform)
        path = self.batch(self.bakery, [p])
        report = SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)
        row = outcome(report, "p1")
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["account"]), row)
        for w in words:
            self.assertIn(w, " ".join(row["reasons"]))
        self.assertEqual(self.writes(), [])

    def test_an_unconnected_account_blocks(self):
        self.check("person", "tiktok", "not connected")

    def test_an_unlinked_account_blocks(self):
        self.check("company", "facebook", "has not been matched")

    def test_an_account_the_key_cannot_see_blocks(self):
        self.check("company", "instagram", "cannot see the account")

    def test_an_account_the_service_says_is_disconnected_blocks(self):
        self.check("company", "linkedin", "not connected for this brand right now")

    def test_when_the_service_cannot_be_reached_a_real_send_stops_and_a_dry_run_says_so(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])

        def down(req, timeout=None):
            raise http_error(503)

        from smf.posting.metricool import Metricool
        from smf.posting.provider import Transport
        provider = Metricool(Transport(allow_writes=True, opener=down), token="t" * 12, user_id="42")
        with self.assertRaises(SEND.SendError):
            SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        self.assertEqual(Ledger(self.bakery).all(), {})
        report = SEND.schedule_batch(self.bakery, path, provider)
        self.assertIn("could not be reached", " ".join(report["notes"]))


class TestARealSend(SendCase):
    def send(self, path, brand=None, **kw):
        return SEND.schedule_batch(brand or self.bakery, path, self.provider(True), confirm=True, **kw)

    def test_reserve_then_upload_then_schedule_then_record_and_a_second_run_sends_nothing(self):
        path = self.batch(self.bakery, [self.post(self.bakery, "p1"),
                                        self.post(self.bakery, "p2", text="Seeded loaves sell out by ten.",
                                                  when="2030-01-06T15:00:00Z")])
        report = self.send(path)
        self.assertEqual(report["counts"], {"sent": 2})
        self.assertEqual(self.service.order, ["upload", "post", "post"])     # one picture, uploaded once
        led = Ledger(self.bakery).all()
        self.assertEqual(sorted(op["state"] for op in led.values()), ["sent", "sent"])
        saved = {p.id: p for p in P.load_batch(path, self.bakery.id)[0]}
        self.assertEqual([saved[i].status for i in ("p1", "p2")], ["scheduled", "scheduled"])
        self.assertEqual(saved["p1"].provider_post_id, outcome(report, "p1")["provider_post_id"])
        receipts, _bad = S.read_lines(SEND.sent_log_path(self.bakery))
        self.assertEqual([r["post_id"] for r in receipts], ["p1", "p2"])
        self.assertEqual(receipts[0]["text"], "Rye is out at seven.")
        n = len(self.writes())
        again = self.send(path)
        self.assertEqual(again["counts"], {"skipped": 2})
        self.assertEqual(len(self.writes()), n)
        self.assertEqual(len(self.service.accepted), 2)

    def test_the_batch_is_saved_after_each_post_not_at_the_end(self):
        path = self.batch(self.bakery, [self.post(self.bakery, "p1"),
                                        self.post(self.bakery, "p2", text="Seeded loaves sell out by ten.",
                                                  when="2030-01-06T15:00:00Z")])
        provider = self.provider(True)
        real, calls = provider.schedule, []

        def dies_on_the_second(post, *a, **kw):
            calls.append(post.id)
            if len(calls) == 2:
                raise KeyboardInterrupt()                                # the computer is switched off here
            return real(post, *a, **kw)

        provider.schedule = dies_on_the_second
        with self.assertRaises(KeyboardInterrupt):
            SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        self.assertEqual(statuses(self.bakery, path), {"p1": "scheduled", "p2": "approved"})

    def test_a_clear_refusal_is_marked_failed_and_the_retry_succeeds(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        self.service.fail_next_post_with = http_error(400, b'{"error":"caption too long for this network"}')
        report = self.send(path)
        row = outcome(report, "p1")
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("refused", row["reasons"][0])
        key = operation_key(self.post(self.bakery))
        self.assertEqual(Ledger(self.bakery).get(key)["state"], "failed")
        self.assertEqual(statuses(self.bakery, path), {"p1": "approved"})    # still approved: ready to go again
        retry = self.send(path)
        self.assertEqual(retry["counts"], {"sent": 1})
        self.assertEqual(len(self.service.accepted), 1)
        self.assertEqual(Ledger(self.bakery).get(key)["state"], "sent")

    def test_an_upload_that_fails_is_certain_so_it_is_failed_not_unknown(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        provider = self.provider(True)
        provider.upload = mock.Mock(side_effect=SEND.ProviderError("storage timed out", "network", definitive=False))
        report = SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        self.assertEqual(outcome(report, "p1")["outcome"], "failed")     # no post was ever created
        self.assertEqual(statuses(self.bakery, path), {"p1": "approved"})
        self.assertEqual(self.send(path)["counts"], {"sent": 1})

    def test_an_error_after_the_service_took_the_post_is_unknown_and_it_is_never_sent_twice(self):
        path = self.batch(self.bakery, [approve(self.post(self.bakery, approved=False), facts_checked=False)])
        self.service.accept_then_fail_with = http_error(502)            # it arrived; the answer did not
        report = self.send(path)
        row = outcome(report, "p1")
        self.assertEqual(row["outcome"], "unknown")
        self.assertIn("results check", row["reasons"][0])
        key = operation_key(self.post(self.bakery))
        self.assertEqual(Ledger(self.bakery).get(key)["state"], "unknown")
        parked = P.load_batch(path, self.bakery.id)[0][0]
        self.assertEqual(parked.status, "blocked")
        self.assertIn("Run a results check", parked.feedback)
        self.assertIn("checked the facts themselves", parked.feedback)   # the reviewer's confirmation is kept

        second = self.send(path)                                         # the next run must not resend it
        self.assertEqual(outcome(second, "p1")["outcome"], "blocked")
        self.assertIn("results check", outcome(second, "p1")["reasons"][0])
        self.assertEqual(len(self.service.accepted), 1)

        found = R.reconcile(self.bakery, self.provider(False))           # looks at the service's calendar; reads only
        self.assertEqual((found["found"], found["not_found"]), (["p1"], []))
        self.assertEqual(Ledger(self.bakery).get(key)["state"], "sent")
        healed = P.load_batch(path, self.bakery.id)[0][0]
        self.assertEqual((healed.status, healed.provider_post_id), ("scheduled", "9000"))
        self.assertNotIn("Not sure", healed.feedback)

        third = self.send(path)
        self.assertEqual(third["counts"], {"skipped": 1})
        self.assertEqual(len(self.service.accepted), 1)                  # one post on the calendar, ever

    def test_an_unclear_send_that_never_arrived_is_freed_by_the_results_check_and_sent_once(self):
        path = self.batch(self.bakery, [approve(self.post(self.bakery, approved=False), facts_checked=False)])
        self.service.fail_next_post_with = http_error(500)               # the service fell over before taking it
        self.assertEqual(outcome(self.send(path), "p1")["outcome"], "unknown")
        self.assertEqual(outcome(self.send(path), "p1")["outcome"], "blocked")
        self.assertEqual(len(self.service.accepted), 0)
        rep = R.reconcile(self.bakery, self.provider(False), now=AFTER_THE_WAIT())
        self.assertEqual((rep["found"], rep["not_found"]), ([], ["p1"]))
        self.assertEqual(rep["healed"], [("p1", "approved")])
        self.assertEqual(statuses(self.bakery, path), {"p1": "approved"})
        self.assertEqual(self.send(path)["counts"], {"sent": 1})         # the confirmation of facts survived too
        self.assertEqual(len(self.service.accepted), 1)

    def test_a_parked_post_in_a_batch_kept_elsewhere_heals_itself_on_the_next_send(self):
        elsewhere = os.path.join(self.tmp.name, "kept elsewhere.json")
        P.save_batch([self.post(self.bakery)], elsewhere)
        self.service.accept_then_fail_with = http_error(502)
        self.assertEqual(outcome(self.send(elsewhere), "p1")["outcome"], "unknown")
        R.reconcile(self.bakery, self.provider(False))                   # settles the record; cannot see this file
        self.assertEqual(statuses(self.bakery, elsewhere), {"p1": "blocked"})
        self.assertEqual(outcome(self.send(elsewhere), "p1")["outcome"], "already-sent")
        self.assertEqual(statuses(self.bakery, elsewhere), {"p1": "scheduled"})
        self.assertEqual(len(self.service.accepted), 1)

    def test_killed_between_the_service_saying_yes_and_writing_it_down(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        provider = self.provider(True)
        real = provider.schedule

        def power_cut(*a, **kw):
            real(*a, **kw)                                               # the service took the post...
            raise KeyboardInterrupt()                                    # ...and the run died before recording it

        provider.schedule = power_cut
        with self.assertRaises(KeyboardInterrupt):
            SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        key = operation_key(self.post(self.bakery))
        led = Ledger(self.bakery)
        self.assertEqual(led.get(key)["state"], "reserved")              # written BEFORE the send, so it survived
        self.assertEqual(statuses(self.bakery, path), {"p1": "approved"})

        right_away = self.send(path)                                     # the very next run
        self.assertEqual(outcome(right_away, "p1")["outcome"], "refused")
        self.assertEqual(len(self.service.accepted), 1)

        data = json.loads(Path(led.path).read_text(encoding="utf-8"))
        data["operations"][key]["reserved_at_ts"] = time.time() - 3600   # an hour later, still nobody finished it
        Path(led.path).write_text(json.dumps(data), encoding="utf-8")
        later = self.send(path)
        self.assertEqual(outcome(later, "p1")["outcome"], "refused")
        self.assertIn("results check", outcome(later, "p1")["reasons"][0])
        self.assertEqual(led.get(key)["state"], "unknown")
        self.assertEqual(len(self.service.accepted), 1)                  # still exactly one

        self.assertEqual(R.reconcile(self.bakery, self.provider(False))["found"], ["p1"])
        self.assertEqual(statuses(self.bakery, path), {"p1": "scheduled"})
        self.send(path)
        self.assertEqual(len(self.service.accepted), 1)

    def test_a_damaged_posting_record_stops_everything(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        led = Ledger(self.bakery)
        Path(led.path).write_text("{ not json", encoding="utf-8")
        for confirm in (False, True):
            with self.assertRaises(LedgerError) as cm:
                SEND.schedule_batch(self.bakery, path, self.provider(confirm), confirm=confirm)
            self.assertIn("damaged", str(cm.exception))
        self.assertEqual(self.writes(), [])
        self.assertEqual(Path(led.path).read_text(encoding="utf-8"), "{ not json")

    def test_a_small_first_run_can_be_limited(self):
        path = self.batch(self.bakery, [self.post(self.bakery, "p%d" % i, text="Loaf number %d is out." % i,
                                                  when="2030-01-0%dT15:00:00Z" % (i + 1)) for i in range(1, 4)])
        report = self.send(path, limit=1)
        self.assertEqual(report["counts"], {"sent": 1, "held": 2})
        self.assertEqual(len(self.service.accepted), 1)

    def test_a_change_made_in_the_review_page_during_the_run_is_not_overwritten(self):
        path = self.batch(self.bakery, [self.post(self.bakery, "p1"),
                                        self.post(self.bakery, "p2", text="Seeded loaves sell out by ten.",
                                                  when="2030-01-06T15:00:00Z", approved=False)])
        provider = self.provider(True)
        real = provider.schedule

        def someone_edits_meanwhile(post, *a, **kw):
            posts, meta = P.load_batch(path, self.bakery.id)
            posts[1].text = "Seeded loaves sell out by nine."
            P.save_batch(posts, path, meta)
            return real(post, *a, **kw)

        provider.schedule = someone_edits_meanwhile
        SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        saved = {p.id: p for p in P.load_batch(path, self.bakery.id)[0]}
        self.assertEqual(saved["p1"].status, "scheduled")
        self.assertEqual(saved["p2"].text, "Seeded loaves sell out by nine.")


class TestTwoBrandsNeverCross(SendCase):
    """Both brands have an identity called `person` on Instagram. The bakery's is account 101,
    the clinic's is 555."""

    def test_each_brands_posts_go_only_to_its_own_account(self):
        b = self.batch(self.bakery, [self.post(self.bakery, "b1"),
                                     self.post(self.bakery, "b2", text="Seeded loaves sell out by ten.",
                                               when="2030-01-06T15:00:00Z")])
        SEND.schedule_batch(self.bakery, b, self.provider(True), confirm=True)
        self.assertEqual(self.service.accounts_posted_to(), ["101"])
        self.assertEqual(set(self.service.uploads), {"101"})
        c = self.batch(self.clinic, [self.post(self.clinic, "c1", text="Calf pain on hills has a usual cause.")])
        SEND.schedule_batch(self.clinic, c, self.provider(True), confirm=True)
        self.assertEqual([acct for acct, body in self.service.accepted if "Calf pain" in body["text"]], ["555"])
        self.assertEqual([acct for acct, body in self.service.accepted if "loaves" in body["text"]], ["101"])
        self.assertEqual(len(self.service.calendar["555"]), 1)
        self.assertEqual({op["provider_brand_id"] for op in Ledger(self.bakery).all().values()}, {101})
        self.assertEqual({op["provider_brand_id"] for op in Ledger(self.clinic).all().values()}, {555})

    def test_one_brands_batch_cannot_be_sent_as_the_other_brand(self):
        theirs = self.batch(self.clinic, [self.post(self.clinic, "c1")])
        with self.assertRaises(SEND.SendError) as cm:
            SEND.schedule_batch(self.bakery, theirs, self.provider(True), confirm=True)
        self.assertIn("belongs to stride-physio", str(cm.exception))
        self.assertEqual(self.service.requests, [])                      # not even a read

    def test_a_stray_post_from_another_brand_inside_a_batch_refuses_the_whole_file(self):
        path = self.batch(self.bakery, [self.post(self.bakery, "b1")])
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        stray = dict(data["posts"][0], id="c1", brand="stride-physio")
        data["posts"].append(stray)
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SEND.SendError):
            SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)
        self.assertEqual(self.writes(), [])

    def test_the_account_id_never_comes_from_the_post_or_the_batch(self):
        path = self.batch(self.bakery, [self.post(self.bakery, "b1")])
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["meta"]["provider_brand_id"] = 555                          # someone tries to steer it from the file
        data["posts"][0]["provider_brand_id"] = 555
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)
        self.assertEqual(self.service.accounts_posted_to(), ["101"])

    def test_settings_that_point_at_another_brands_account_are_refused(self):
        brands.update("maple-and-main", {"accounts": {"targets": [target("person", "instagram", 555)]}})
        bakery = brands.load("maple-and-main")                           # a copy-paste slip: the clinic's id
        path = self.batch(bakery, [self.post(bakery, "b1")])
        report = SEND.schedule_batch(bakery, path, self.provider(True), confirm=True)
        row = outcome(report, "b1")
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["account"]))
        self.assertIn("stride-physio", row["reasons"][0])
        self.assertEqual(self.writes(), [])

    def test_a_brand_with_no_scheduling_service_cannot_send_and_there_is_no_default(self):
        plain = brands.create("corner-florist", "Corner Florist")
        path = P.save_batch([self.post(plain, "f1", identity="company")], plain.path("Output", "batches", "f.json"))
        with self.assertRaises(SEND.SendError) as cm:
            SEND.schedule_batch(plain, path, self.provider(True), confirm=True)
        self.assertIn("not set up to post", str(cm.exception))
        with self.assertRaises(A.AccountsError):
            A.open_provider(plain)
        with self.assertRaises(BrandError):
            SEND.schedule_batch(None, path, self.provider(True), confirm=True)
        with self.assertRaises(BrandError):
            SEND.schedule_batch("maple-and-main", path, self.provider(True), confirm=True)   # a name is not a brand
        self.assertEqual(self.writes(), [])


class TestLinkingAccountsByIdOnly(SendCase):
    def test_the_list_is_read_only_and_says_who_already_uses_what(self):
        provider = self.provider(False)
        rows = A.overview(self.bakery, A.list_accounts(provider))
        self.assertEqual([r["provider_brand_id"] for r in rows], [101, 102, 555])
        self.assertEqual(rows[0]["linked_here"], ["person/instagram"])
        self.assertEqual(rows[2]["claimed_by_other_brands"], ["stride-physio"])
        self.assertEqual(self.writes(), [])

    def test_entries_are_built_from_an_id_and_an_explicit_mapping(self):
        listed = A.list_accounts(self.provider(False))
        entries = A.build_targets(self.bakery, listed, 101, {"person": ["tiktok", "youtube"]})
        self.assertEqual(entries, [target("person", "tiktok", 101), target("person", "youtube", 101)])
        not_connected = A.build_targets(self.bakery, listed, 102, {"company": ["linkedin"]})
        self.assertIs(not_connected[0]["connected"], False)              # mapped, but the service has no linkedin there

    def test_a_name_is_never_enough_and_a_similar_name_is_never_matched(self):
        listed = A.list_accounts(self.provider(False))
        for wrong in ("Invented Bakery", "invented bakery shop", "", None, True, "10l"):
            with self.assertRaises(A.AccountsError):
                A.build_targets(self.bakery, listed, wrong, {"person": ["tiktok"]})
        with self.assertRaises(A.AccountsError):
            A.build_targets(self.bakery, listed, 999, {"person": ["tiktok"]})              # an id the key cannot see

    def test_wrong_identities_platforms_and_other_brands_accounts_are_refused(self):
        listed = A.list_accounts(self.provider(False))
        with self.assertRaises(A.AccountsError):
            A.build_targets(self.bakery, listed, 101, {"doctor": ["tiktok"]})
        with self.assertRaises(A.AccountsError):
            A.build_targets(self.bakery, listed, 101, {"person": ["myspace"]})
        with self.assertRaises(A.AccountsError) as cm:
            A.build_targets(self.bakery, listed, 555, {"person": ["instagram"]})
        self.assertIn("stride-physio", str(cm.exception))
        with self.assertRaises(A.AccountsError):
            A.build_targets(self.bakery, listed, 101, {"person": ["tiktok"], "company": ["tiktok"]})

    def test_linking_keeps_the_other_accounts_and_the_new_one_can_be_sent_to(self):
        listed = A.list_accounts(self.provider(False))
        updated = A.link(self.bakery, A.build_targets(self.bakery, listed, 101, {"person": ["tiktok"]}))
        self.assertEqual(sorted((t["identity"], t["platform"]) for t in updated.targets()),
                         [("company", "facebook"), ("person", "instagram"), ("person", "tiktok")])
        path = self.batch(updated, [self.post(updated, "t1", platform="tiktok")])
        SEND.schedule_batch(updated, path, self.provider(True), confirm=True)
        self.assertEqual(self.service.accepted[0][0], "101")

    def test_the_command_shows_what_it_would_save_and_saves_only_with_confirm(self):
        with mock.patch.object(A, "open_provider", lambda brand, allow_writes=False, opener=None: self.provider(False)):
            with redirect_stdout(io.StringIO()) as out:
                rc = posting_cli.cli_accounts(["--brand", "maple-and-main", "--provider-brand-id", "101",
                                               "--map", "person=tiktok"])
            self.assertEqual(rc, 0)
            self.assertIn("Nothing was saved", out.getvalue())
            self.assertEqual(len(brands.load("maple-and-main").targets()), 2)
            with redirect_stdout(io.StringIO()):
                posting_cli.cli_accounts(["--brand", "maple-and-main", "--provider-brand-id", "101",
                                          "--map", "person=tiktok", "--confirm"])
            self.assertEqual(len(brands.load("maple-and-main").targets()), 3)
        self.assertEqual(self.writes(), [])


NOW = datetime(2030, 2, 1, 17, 0, tzinfo=timezone.utc)                   # noon at the bakery


def entry(eid, text, when, network="instagram", status="PUBLISHED", detail="", draft=False):
    return {"id": eid, "text": text, "publicationDate": {"dateTime": when}, "draft": draft,
            "providers": [{"network": network, "status": status, "detailedStatus": detail}]}


class TestDidItGoOut(SendCase):
    def test_posts_the_network_refused_are_reported_with_the_networks_own_reason(self):
        self.service.calendar["101"] = [
            entry(1, "Rye is out at seven.", "2030-01-30T10:00:00"),
            entry(2, "Seeded loaves sell out by ten.", "2030-01-31T10:00:00", status="ERROR",
                  detail="The account needs to be connected again."),
            entry(3, "Class places open on Friday.", "2030-02-01T08:00:00", status="PENDING"),      # hours late
            entry(4, "Tomorrow's bake.", "2030-02-02T10:00:00", status="PENDING"),                 # not due yet
            entry(5, "An unfinished thought.", "2030-01-31T10:00:00", status="ERROR", draft=True),
            entry(6, "A tiktok nobody linked here.", "2030-01-31T10:00:00", network="tiktok", status="ERROR")]
        self.service.calendar["555"] = [entry(7, "The clinic's own trouble.", "2030-01-31T10:00:00", status="ERROR")]
        health = R.publish_health(self.bakery, self.provider(False), days_back=14, now=NOW)
        kinds = {p["provider_post_id"]: p["kind"] for p in health["problems"]}
        self.assertEqual(kinds, {"2": "refused", "3": "stalled"})        # nothing of the clinic's, nothing unlinked
        refused = health["problems"][0]
        self.assertEqual(refused["reason"], "The account needs to be connected again.")
        self.assertIn("did NOT go out", R.describe_health(health))
        self.assertEqual(self.writes(), [])

    def test_a_refused_post_the_factory_sent_is_named_by_its_own_id(self):
        path = self.batch(self.bakery, [self.post(self.bakery, "p1", when="2030-01-31T15:00:00Z")])
        SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True,
                            now=datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.service.calendar["101"][0]["providers"][0].update(status="ERROR", detailedStatus="Login expired.")
        problems = R.publish_health(self.bakery, self.provider(False), 14, now=NOW)["problems"]
        self.assertEqual([(p["post_id"], p["reason"]) for p in problems], [("p1", "Login expired.")])

    def test_all_clear_means_it_really_looked(self):
        self.service.calendar["101"] = [entry(1, "Rye is out at seven.", "2030-01-30T10:00:00")]
        brands.update("maple-and-main", {"accounts": {"targets": [target("person", "instagram", 101)]}})
        bakery = brands.load("maple-and-main")
        health = R.publish_health(bakery, self.provider(False), 14, now=NOW)
        self.assertEqual((health["checked"], health["problems"]), (1, []))
        self.service.calendar_is_down = True
        with self.assertRaises(R.ResultsError) as cm:                    # "could not look" is never "all clear"
            R.publish_health(bakery, self.provider(False), 14, now=NOW)
        self.assertIn("UNKNOWN", str(cm.exception))


def insta(post_id, words, views, created="2030-01-30 10:00:05", **more):
    return dict({"postId": post_id, "created": created, "url": "https://example.com/p/%s" % post_id,
                 "content": words, "views": views, "likes": 4, "comments": 1, "shares": 2, "saved": 3}, **more)


class TestTheResultsArchive(SendCase):
    def send_one(self, text="Rye is out at seven.", pid="p1", when="2030-01-30T15:00:00Z", name="w.json"):
        path = self.batch(self.bakery, [self.post(self.bakery, pid, text=text, when=when)], name)
        SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True,
                            now=datetime(2030, 1, 1, tzinfo=timezone.utc))
        return path

    def month_file(self, month="2030-02"):
        return Path(R.metrics_dir(self.bakery), month + ".jsonl")

    def test_results_are_added_once_a_day_and_history_is_never_rewritten(self):
        self.send_one()
        self.service.results[("101", "instagram")] = [insta("IG-777", "Rye is out at seven.", 120)]
        first = R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        self.assertEqual((first["new_rows"], first["linked"]), (1, 1))
        day_one = self.month_file().read_bytes()
        again = R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        self.assertEqual(again["new_rows"], 0)                           # same day: nothing added
        self.assertEqual(self.month_file().read_bytes(), day_one)
        self.service.results[("101", "instagram")] = [insta("IG-777", "Rye is out at seven.", 480)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW + timedelta(days=1))
        grown = self.month_file().read_bytes()
        self.assertTrue(grown.startswith(day_one))                       # yesterday's lines, byte for byte
        rows, bad = R.load_archive(self.bakery)
        self.assertEqual(([r["metrics"]["views"] for r in rows], bad), ([120, 480], 0))
        R.harvest_metrics(self.bakery, self.provider(False), 60, now=datetime(2030, 3, 2, 17, 0, tzinfo=timezone.utc))
        self.assertTrue(self.month_file("2030-03").is_file())            # one file per month
        self.assertEqual(self.month_file().read_bytes(), grown)
        self.assertEqual(self.writes().count(("POST", "https://app.metricool.com/api/v2/scheduler/posts")), 1)

    def test_a_row_is_tied_to_a_send_by_exact_words_never_by_similar_words(self):
        self.send_one("Rye is out at seven.", "p1")
        self.send_one("Seeded loaves sell out by ten.", "p2", "2030-01-31T15:00:00Z", "w2.json")
        self.service.results[("101", "instagram")] = [
            insta("IG-1", "Rye  is out\nat seven.", 100),                # the same words; only the spacing differs
            insta("IG-2", "Seeded loaves sell out by ten. #bread", 200),  # close, but not the words that were sent
            insta("IG-3", "Posted by hand from a phone.", 300)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        rows = {r["post_id"]: r for r in R.load_archive(self.bakery)[0]}
        self.assertEqual(rows["IG-1"]["factory_post_id"], "p1")
        self.assertEqual(rows["IG-1"]["provider_post_id"], "9000")       # the service's id, not the network's
        self.assertEqual((rows["IG-2"]["provider_post_id"], rows["IG-3"]["provider_post_id"]), ("", ""))
        self.assertEqual(len(rows), 3)                                   # unlinked rows are still kept

    def test_words_sent_twice_to_one_account_link_to_neither_send(self):
        self.send_one("Rye is out at seven.", "p1", "2030-01-30T15:00:00Z", "a.json")
        self.send_one("Rye is out at seven.", "p2", "2030-01-31T15:00:00Z", "b.json")
        self.service.results[("101", "instagram")] = [insta("IG-1", "Rye is out at seven.", 100)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        self.assertEqual(R.load_archive(self.bakery)[0][0]["provider_post_id"], "")

    def test_one_brands_results_never_land_in_the_others_archive(self):
        self.service.results[("101", "instagram")] = [insta("IG-1", "Bakery words.", 100)]
        self.service.results[("555", "instagram")] = [insta("IG-9", "Clinic words.", 900)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        R.harvest_metrics(self.clinic, self.provider(False), 30, now=NOW)
        self.assertEqual([r["post_id"] for r in R.load_archive(self.bakery)[0]], ["IG-1"])
        self.assertEqual([r["post_id"] for r in R.load_archive(self.clinic)[0]], ["IG-9"])
        stray = dict(R.load_archive(self.clinic)[0][0])
        S.append_lines(str(self.month_file()), [stray])                  # a line copied into the wrong folder
        self.assertEqual([r["post_id"] for r in R.load_archive(self.bakery)[0]], ["IG-1"])

    def test_the_summary_is_plain_numbers_and_needs_no_connection(self):
        self.send_one()
        self.service.results[("101", "instagram")] = [insta("IG-1", "Rye is out at seven.", 120),
                                                      insta("IG-2", "Posted by hand.", 80)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        reads = len(self.service.requests)
        summary = R.summary(self.bakery, 30, now=NOW)
        self.assertEqual(len(self.service.requests), reads)
        self.assertEqual((summary["sent"], summary["posts_with_results"], summary["totals"]["views"]), (1, 2, 200))
        self.assertEqual(summary["top"][0]["views"], 120)
        self.assertIn("200 views", "\n".join(summary["lines"]))
        empty = R.summary(self.clinic, 30, now=NOW)
        self.assertIn("No results are saved yet", "\n".join(empty["lines"]))

    def test_the_summary_shows_the_weakest_posts_that_have_had_a_fair_chance(self):
        self.service.results[("101", "instagram")] = [
            insta("IG-1", "Why our rye takes three days.", 900, created="2030-01-21 10:00:05"),
            insta("IG-2", "Saturday hours are changing.", 50, created="2030-01-22 10:00:05"),
            insta("IG-3", "How to keep a loaf fresh.", 700, created="2030-01-23 10:00:05"),
            insta("IG-4", "Meet our new oven.", 30, created="2030-01-24 10:00:05"),
            insta("IG-5", "The dense loaf fix.", 400, created="2030-01-25 10:00:05"),
            insta("IG-6", "Where our flour comes from.", 80, created="2030-01-26 10:00:05"),
            insta("IG-7", "Fresh out this morning.", 5, created="2030-02-01 08:00:05"),       # too new to judge
            insta("IG-8", "A photo with no view count.", None, created="2030-01-27 10:00:05")]  # nothing to rank by
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        summary = R.summary(self.bakery, 30, now=NOW)
        self.assertEqual([t["views"] for t in summary["top"]], [900, 700, 400])
        self.assertEqual([w["views"] for w in summary["weakest"]], [30, 50, 80])
        self.assertEqual(set(summary["weakest"][0]), set(summary["top"][0]))      # the same details as the top three
        text = "\n".join(summary["lines"])
        self.assertIn("Least viewed", text)
        self.assertIn("1 post is too new to judge", text)
        self.assertIn("1 post has no view count", text)
        self.assertNotIn("Fresh out this morning", text.split("Least viewed")[1])

    def test_too_new_means_too_new_when_the_numbers_were_taken(self):
        # Numbers saved six hours after posting stay six hours old, however long ago that was.
        self.service.results[("101", "instagram")] = [
            insta("IG-%d" % n, "Post %d." % n, v, created="2030-01-%02d 10:00:05" % (20 + n))
            for n, v in ((1, 900), (2, 800), (3, 700), (4, 600))] + [
            insta("IG-9", "Measured too early.", 3, created="2030-02-01 11:00:05")]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        later = R.summary(self.bakery, 30, now=NOW + timedelta(days=10))
        self.assertEqual([w["views"] for w in later["weakest"]], [600])
        self.assertIn("1 post is too new to judge", "\n".join(later["lines"]))

    def test_a_post_is_never_both_the_best_and_the_weakest(self):
        for count in (1, 2, 3, 4, 5):
            with self.subTest(posts=count):
                for old in Path(R.metrics_dir(self.bakery)).glob("*"):
                    old.unlink()
                self.service.results[("101", "instagram")] = [
                    insta("IG-%d" % n, "Post %d." % n, 100 * n, created="2030-01-%02d 10:00:05" % (20 + n))
                    for n in range(1, count + 1)]
                R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
                summary = R.summary(self.bakery, 30, now=NOW)
                best = {t["text_start"] for t in summary["top"]}
                weakest = {w["text_start"] for w in summary["weakest"]}
                self.assertEqual(best & weakest, set())
                self.assertEqual(len(weakest), max(0, count - 3))

    def test_a_torn_line_is_counted_not_hidden_and_not_a_reason_to_lose_the_rest(self):
        self.service.results[("101", "instagram")] = [insta("IG-1", "Bakery words.", 100)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        with open(self.month_file(), "ab") as f:
            f.write(b'{"captured_at": "2030-02-0')
        rows, bad = R.load_archive(self.bakery)
        self.assertEqual((len(rows), bad), (1, 1))
        self.assertIn("could not be read", "\n".join(R.summary(self.bakery, 30, now=NOW)["lines"]))


LINK = "https://www.instagram.com/p/ABC123/"


class TestPostsPutUpByHand(SendCase):
    """A free-route person posts from the ready-to-post folder, tells the Factory, types the numbers."""

    def exported(self, brand=None, pid="h1", text="Rye is out at seven.", platform="instagram",
                 when="2030-01-25T15:00:00Z", status="exported", name="by-hand.json", extra=()):
        brand = brand or self.bakery
        posts = [self.post(brand, pid, text=text, when=when, platform=platform)] + list(extra)
        for post in posts:
            post.status = status
        return self.batch(brand, posts, name)

    def mark(self, pid="h1", url=LINK, when="2030-01-25 09:15", **kw):
        return H.mark_posted(self.bakery, pid, url, when, confirm=True, now=NOW, **kw)

    def summary_text(self, brand=None, now=NOW):
        summary = R.summary(brand or self.bakery, 30, now=now)
        return summary, "\n".join(summary["lines"])

    def test_recording_a_post_is_a_preview_until_confirmed_and_never_touches_the_batch_or_ledger(self):
        path = self.exported()
        before = Path(path).read_bytes()
        preview = H.mark_posted(self.bakery, "h1", LINK, "2030-01-25 09:15", now=NOW)
        self.assertFalse(preview["saved"])
        self.assertIn("Nothing was saved", "\n".join(preview["lines"]))
        self.assertFalse(os.path.exists(H.log_path(self.bakery)))
        self.mark()
        self.assertEqual(len(S.read_lines(H.log_path(self.bakery))[0]), 1)
        self.assertEqual(Path(path).read_bytes(), before)                # still `exported`, byte for byte
        self.assertEqual(Ledger(self.bakery).all(), {})                  # the Factory never sent it
        H.save_numbers(self.bakery, "h1", ["views=1200"], now=NOW)
        self.assertEqual(R.load_archive(self.bakery)[0], [])             # numbers: also a preview first
        self.assertEqual(self.writes(), [])

    def test_what_cannot_be_recorded_is_refused_with_a_reason_and_nothing_is_saved(self):
        self.exported()
        self.exported(pid="a1", status="approved", name="not-yet.json")
        self.exported(brand=self.clinic, pid="c1", name="clinic.json")
        cases = [(lambda: self.mark("c1"), "no post called"),            # another brand's post
                 (lambda: self.mark("a1"), "cannot be recorded"),        # never exported
                 (lambda: self.mark(url="https://www.facebook.com/p/1"), "this post was for Instagram"),
                 (lambda: self.mark(url="instagram.com/p/1"), "not a web address"),
                 (lambda: self.mark(when="2030-02-09 10:00"), "still to come")]
        for attempt, words in cases:
            with self.subTest(words=words):
                with self.assertRaises(H.HandPostedError) as cm:
                    attempt()
                self.assertIn(words, str(cm.exception))
        self.assertFalse(os.path.exists(H.log_path(self.bakery)))
        self.mark()
        for pairs, words in ((["followers=10"], "does not keep 'followers'"), (["views=1.2K"], "exact count"),
                             (["views=-4"], "not an exact whole number"), ([], "No numbers")):
            with self.subTest(pairs=pairs):
                with self.assertRaises(H.HandPostedError) as cm:
                    H.save_numbers(self.bakery, "h1", pairs, confirm=True, now=NOW)
                self.assertIn(words, str(cm.exception))
        self.assertEqual(R.load_archive(self.bakery)[0], [])
        with self.assertRaises(H.HandPostedError):                        # one link is one post
            self.exported(pid="h2", name="second.json")
            self.mark("h2")

    def test_typed_numbers_are_ordinary_archive_rows_that_nothing_mistakes_for_a_send(self):
        self.exported()
        self.mark()
        H.save_numbers(self.bakery, "h1", ["views=1,200", "likes=40"], confirm=True, now=NOW)
        self.service.results[("101", "instagram")] = [insta("IG-1", "Fetched words.", 10)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        typed, fetched = sorted(R.load_archive(self.bakery)[0], key=lambda r: r.get("source") or "", reverse=True)
        self.assertTrue(set(fetched) <= set(typed))                      # every key a fetched row has
        self.assertEqual(set(typed) - set(fetched), {"source", "batch"})  # plus two added ones
        self.assertEqual((typed["source"], typed["provider_post_id"], typed["linked_by"]), ("typed", "", ""))
        self.assertEqual(typed["metrics"], {"views": 1200, "likes": 40})  # nothing filled in that was not given
        self.assertEqual((typed["post_id"], typed["url"]), (LINK, LINK))
        self.assertEqual(typed["published_at"], "2030-01-25T14:15:00Z")  # 09:15 at the bakery

    def test_the_summary_counts_typed_posts_marks_them_and_names_the_ones_waiting(self):
        self.exported(extra=[self.post(self.bakery, "h2", text="Seeded spelt is back.", when="2030-01-26T15:00:00Z")])
        self.mark()
        self.mark("h2", url="https://www.instagram.com/p/XYZ789/", when="2030-01-26")
        H.save_numbers(self.bakery, "h1", ["views=1200"], confirm=True, now=NOW)
        summary, text = self.summary_text()
        self.assertEqual((summary["posts_with_results"], summary["totals"]["views"]), (1, 1200))
        self.assertIn("(typed in)", text)
        self.assertIn("2 post(s) were put up by hand", text)
        self.assertIn("1 of these 1 post(s) have numbers you typed in", text)
        self.assertIn("1 post you put up by hand has no numbers yet", text)
        self.assertIn("Not given: likes, comments, shares, saves.", text)   # never a total of zero

    def test_a_correction_replaces_the_old_numbers_and_says_what_it_drops(self):
        self.exported()
        self.mark()
        H.save_numbers(self.bakery, "h1", ["views=1200", "likes=40"], confirm=True, now=NOW)
        later = NOW + timedelta(days=1)
        preview = H.save_numbers(self.bakery, "h1", ["views=2000"], now=later)
        self.assertIn("no longer counted: likes 40", "\n".join(preview["lines"]))
        H.save_numbers(self.bakery, "h1", ["views=2000"], confirm=True, now=later)
        summary, _text = self.summary_text(now=later)
        self.assertEqual((summary["totals"]["views"], summary["totals"]["likes"]), (2000, 0))
        self.assertEqual(len(R.load_archive(self.bakery)[0]), 2)         # the first row is still there

    def test_a_fetched_row_for_the_same_post_wins_and_both_stay_saved(self):
        self.exported()
        self.mark(url="https://www.instagram.com/reel/ABC123/?igsh=from-the-share-button")
        H.save_numbers(self.bakery, "h1", ["views=100"], confirm=True, now=NOW)
        fetched = insta("IG-1", "Words the network shows differently.", 500)
        fetched["url"] = "https://instagram.com/p/ABC123"                # the same post, written another way
        self.service.results[("101", "instagram")] = [fetched]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        summary, text = self.summary_text()
        self.assertEqual((summary["posts_with_results"], summary["totals"]["views"]), (1, 500))
        self.assertNotIn("(typed in)", text)
        self.assertEqual(len(R.load_archive(self.bakery)[0]), 2)

    def test_the_same_words_join_only_when_exactly_one_post_has_them(self):
        self.exported()
        self.mark()
        H.save_numbers(self.bakery, "h1", ["views=100"], confirm=True, now=NOW)
        self.service.results[("101", "instagram")] = [insta("IG-1", "Rye  is out at seven.", 500),
                                                      insta("IG-2", "Rye is out at seven.", 700)]
        R.harvest_metrics(self.bakery, self.provider(False), 30, now=NOW)
        summary, _text = self.summary_text()
        self.assertEqual(summary["posts_with_results"], 3)               # two fetched posts share the words: no join
        self.assertIn(100, [p["views"] for p in summary["top"]])

    def test_a_withdrawn_post_stops_counting_and_can_be_recorded_again(self):
        self.exported()
        self.mark(url="https://www.instagram.com/p/WRONG/")
        H.save_numbers(self.bakery, "h1", ["views=100"], confirm=True, now=NOW)
        self.assertIn("would withdraw", "\n".join(H.withdraw(self.bakery, "h1", now=NOW)["lines"]))
        H.withdraw(self.bakery, "h1", confirm=True, now=NOW)
        self.assertEqual(self.summary_text()[0]["posts_with_results"], 0)
        self.mark()
        self.assertEqual(self.summary_text()[0]["posts_with_results"], 0)  # the old link's numbers stay out

    def test_the_sheet_is_filled_in_checked_whole_and_saved_only_with_confirm(self):
        self.exported(extra=[self.post(self.bakery, "h2", text="Seeded spelt is back.", when="2030-01-26T15:00:00Z")])
        self.mark()
        self.mark("h2", url="https://www.instagram.com/p/XYZ789/", when="2030-01-26 10:00")
        made = H.write_sheet(self.bakery, now=NOW)
        self.assertIn(os.path.join("Output", "results-to-fill"), made["path"])
        self.assertNotIn("metrics", made["path"])                         # never beside the results archive
        with open(made["path"], encoding="utf-8-sig", newline="") as f:
            table = list(csv.DictReader(f))
        table[0]["views"], table[0]["likes"] = "1200", "40"
        filled = os.path.join(self.tmp.name, "filled.csv")

        def save(rows):
            with open(filled, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(table[0]))
                w.writeheader()
                w.writerows(rows)

        save(table)
        self.assertFalse(H.read_sheet(self.bakery, filled, now=NOW)["saved"])
        self.assertEqual(R.load_archive(self.bakery)[0], [])
        H.read_sheet(self.bakery, filled, confirm=True, now=NOW)
        self.assertEqual([r["metrics"] for r in R.load_archive(self.bakery)[0]], [{"views": 1200, "likes": 40}])
        table[1]["views"], table[1]["url"] = "50", "https://www.instagram.com/p/EDITED/"
        save(table)
        with self.assertRaises(H.HandPostedError) as cm:                  # one bad line: nothing saved
            H.read_sheet(self.bakery, filled, confirm=True, now=NOW)
        self.assertIn("link was changed", str(cm.exception))
        self.assertEqual(len(R.load_archive(self.bakery)[0]), 1)

    def test_links_that_name_their_post_in_the_query_are_different_posts(self):
        same, different = H.same_link, lambda a, b: self.assertNotEqual(H.same_link(a), H.same_link(b))
        different("https://www.youtube.com/watch?v=AAA", "https://www.youtube.com/watch?v=BBB")
        different("https://www.facebook.com/permalink.php?story_fbid=1&id=9",
                  "https://www.facebook.com/permalink.php?story_fbid=2&id=9")
        different("https://www.facebook.com/photo.php?fbid=1", "https://www.facebook.com/photo.php?fbid=2")
        self.assertEqual(same("https://m.youtube.com/watch?v=AAA&t=30s&si=share"),
                         same("https://www.youtube.com/watch?si=x&v=AAA"))      # tracking and order don't matter
        self.assertEqual(same("https://www.facebook.com/permalink.php?id=9&story_fbid=1&ref=share"),
                         same("https://facebook.com/permalink.php?story_fbid=1&id=9"))
        self.exported(pid="y1", platform="youtube", extra=[
            self.post(self.bakery, "y2", text="Seeded spelt is back.", when="2030-01-26T15:00:00Z", platform="youtube")])
        self.mark("y1", url="https://www.youtube.com/watch?v=AAA")
        self.mark("y2", url="https://www.youtube.com/watch?v=BBB", when="2030-01-26 10:00")   # not "already recorded"
        self.assertEqual(len(H.read_marks(self.bakery)[0]), 2)

    def test_a_date_with_no_time_that_is_still_to_come_is_refused(self):
        self.exported()
        for day in ("2030-02-02", "2030-03-01"):                        # tomorrow and later, at the bakery
            with self.subTest(day=day):
                with self.assertRaises(H.HandPostedError) as cm:
                    self.mark(when=day)
                self.assertIn("still to come", str(cm.exception))
        self.assertFalse(os.path.exists(H.log_path(self.bakery)))
        self.mark(when="2030-02-01")                                     # today is fine
        self.assertEqual(len(H.read_marks(self.bakery)[0]), 1)

    def test_a_second_sheet_never_replaces_one_already_made(self):
        self.exported()
        self.mark()
        first = H.write_sheet(self.bakery, now=NOW)["path"]
        with open(first, "a", encoding="utf-8") as f:
            f.write("typed in by the owner\n")
        before = Path(first).read_bytes()
        made = H.write_sheet(self.bakery, now=NOW)
        second = made["path"]
        self.assertNotEqual(first, second)
        self.assertIn(os.path.basename(second), "\n".join(made["lines"]))   # says which sheet is the new one
        self.assertEqual(Path(first).read_bytes(), before)               # the filled-in sheet is untouched
        self.assertTrue(os.path.isfile(second))

    def test_the_commands_preview_first_and_need_no_scheduling_service(self):
        brands.update("maple-and-main", {"accounts": {"provider": "none"}})
        self.exported()
        went_up = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d 09:15")   # the command runs on today's date

        def run(*args):
            with redirect_stdout(io.StringIO()) as out:
                rc = posting_cli.cli_results(["--brand", "maple-and-main"] + list(args))
            return rc, out.getvalue()

        with mock.patch.object(A, "open_provider", side_effect=AssertionError("no service needed")):
            rc, out = run("--by-hand", "h1", "--url", LINK, "--when", went_up)
            self.assertEqual(rc, 0)
            self.assertIn("Nothing was saved", out)
            self.assertFalse(os.path.exists(H.log_path(self.bakery)))
            run("--by-hand", "h1", "--url", LINK, "--when", went_up, "--confirm")
            rc, out = run("--numbers", "h1", "views=1200")
            self.assertIn("Nothing was saved", out)
            run("--numbers", "h1", "views=1200", "--confirm")
            rc, out = run()                                               # a plain results run on the free route
            self.assertEqual(rc, 0)
            self.assertIn("1200 views", out)
            rc, out = run("--numbers", "h1", "followers=3", "--confirm")
            self.assertEqual(rc, 1)
            self.assertIn("does not keep", out)


class TestTellingTwoPostsApartOnTheCalendar(SendCase):
    """Two posts to one account that open with the same sixty characters. One arrived. The other
    got no clear answer and never arrived."""

    OPENING = "Every Saturday we bake a loaf that is only sold that morning, and this week "

    def two_sends(self):
        first = self.post(self.bakery, "p1", text=self.OPENING + "it is a walnut rye.")
        second = self.post(self.bakery, "p2", text=self.OPENING + "it is a seeded spelt.",
                           when="2030-01-05T16:00:00Z")
        path = self.batch(self.bakery, [first, second])
        self.service.fail_next_post_with = None
        provider = self.provider(True)
        real = provider.schedule

        def second_one_falls_over(post, *a, **kw):
            if post.id == "p2":
                raise SEND.ProviderError("The service had a problem (HTTP 500).", "server", definitive=False)
            return real(post, *a, **kw)

        provider.schedule = second_one_falls_over
        SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        self.assertEqual(len(self.service.accepted), 1)                  # only p1 is on the calendar
        return path, operation_key(second)

    def test_the_ledger_never_mistakes_a_neighbouring_post_for_this_one(self):
        # Two posts to one account open with the same words and only the first arrived. The ledger
        # must not "find" the second as the first: it matches the exact words, and never an entry
        # that another send already owns.
        _path, key = self.two_sends()
        led = Ledger(self.bakery)
        led.reconcile(self.provider(False), self.bakery.timezone)
        self.assertNotEqual(led.get(key)["state"], "sent")

    def test_the_results_check_frees_the_post_that_never_arrived_and_it_goes_out_once(self):
        # Same situation: two posts open with the same words and only p1 arrived. The calendar check
        # matches exact words and never an entry another send owns, so p2 is correctly reported as
        # not there, freed, and sent exactly once on the next run.
        path, key = self.two_sends()
        rep = R.reconcile(self.bakery, self.provider(False), now=AFTER_THE_WAIT())
        self.assertEqual((rep["found"], rep["unclear"], rep["not_found"]), ([], [], ["p2"]))
        self.assertEqual(Ledger(self.bakery).get(key)["state"], "failed")     # safe to send again
        self.assertEqual(statuses(self.bakery, path), {"p1": "scheduled", "p2": "approved"})
        SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)
        self.assertEqual([body["text"].rsplit(" ", 2)[-2:] for _a, body in self.service.accepted],
                         [["walnut", "rye."], ["seeded", "spelt."]])     # each went out once, and only once

    def test_a_person_can_settle_a_send_the_calendar_could_not(self):
        path, key = self.two_sends()                                     # p2 is parked as unclear
        with self.assertRaises(R.ResultsError):
            R.settle_by_hand(self.bakery, "no-such-post", arrived=False)
        R.settle_by_hand(self.bakery, "p2", arrived=False)               # a person looked: it is not there
        self.assertEqual(Ledger(self.bakery).get(key)["state"], "failed")
        self.assertEqual(statuses(self.bakery, path)["p2"], "approved")
        with self.assertRaises(R.ResultsError):
            R.settle_by_hand(self.bakery, "p2", arrived=False)           # already settled: nothing left to settle


if __name__ == "__main__":
    unittest.main(verbosity=2)
