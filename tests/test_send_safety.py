"""The seven ways a post could have gone out without the person's yes, and the gates that stop them.

    python -m unittest discover -s tests -t . -v

Each class here is one of them, written as the thing that actually happens to a person:
a picture is remade under the same name, an account is reconnected to somebody else's page,
a post is turned down while the run is half way through, an unclear send is edited around,
two results checks tread on each other, a calendar has not caught up yet, and an upload runs
past the post's own time.

Every account, id, response, picture and number in here is invented. Nothing talks to a real
service: the fake scheduling service and `Transport(allow_writes=...)` are all there is.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                    # noqa: E402
from smf.posting import accounts as A                                     # noqa: E402
from smf.posting import promote as PR                                     # noqa: E402
from smf.posting import results as R                                      # noqa: E402
from smf.posting import send as SEND                                      # noqa: E402
from smf.posting import shorts as SH                                      # noqa: E402
from smf.posting import state as S                                        # noqa: E402
from smf.posting.ledger import NOT_FOUND_AFTER_SECONDS, Ledger, operation_key, standing  # noqa: E402
from smf.posting.metricool import Metricool                               # noqa: E402
from smf.posting.provider import Transport                                # noqa: E402
from smf.studio import export as X                                        # noqa: E402
from smf.studio import posts as P                                         # noqa: E402
from smf.studio.review import store as RS                                 # noqa: E402
from tests.posting_fakes import (SendCase, approve, approve_batch, brand_answers, drop_video,  # noqa: E402
                                 http_error, statuses, target)
from tests.test_brands import BAKERY                                      # noqa: E402
from tests.test_posting import FakeResponse                               # noqa: E402


def outcome(report, post_id):
    return next(r for r in report["posts"] if r["id"] == post_id)


def after_the_wait():
    """Far enough past a send that a calendar without it really does mean it never arrived."""
    return time.time() + NOT_FOUND_AFTER_SECONDS + 60


class MovingClock(object):
    """A clock the test winds forward, in place of the real one, so an upload can take an hour
    without the test taking an hour."""

    def __init__(self, start):
        self.now_utc = start

    def forward(self, minutes):
        self.now_utc += timedelta(minutes=minutes)

    def patch(self):
        clock = self

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.now_utc if tz else clock.now_utc.replace(tzinfo=None)

        return mock.patch.object(P, "datetime", Frozen)


# ============================================================================= 1. the picture changed
class TestWhatIsInThePictureIsPartOfTheApproval(SendCase):
    """Approving `card.png` approves THAT picture, not the name of a file that can be rewritten."""

    def test_a_picture_remade_under_the_same_name_voids_the_approval_and_nothing_is_sent(self):
        post = self.post(self.bakery)
        path = self.batch(self.bakery, [post])
        Path(self.bakery.path(*post.media_paths[0].split("/"))).write_bytes(b"a different picture entirely")
        report = SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)
        row = outcome(report, "p1")
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["approval"]))
        self.assertIn("picture or video that changed after you approved it", row["reasons"][0])
        self.assertEqual(self.writes(), [])                              # not even an upload was started
        self.assertEqual(Ledger(self.bakery).all(), {})
        self.assertEqual(statuses(self.bakery, path), {"p1": "approved"})

    def test_the_same_picture_left_alone_still_sends(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        self.assertEqual(SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)["counts"],
                         {"sent": 1})

    def test_the_fingerprint_follows_the_bytes_not_the_name(self):
        post = self.post(self.bakery)
        first = P.approval_sha(post)
        Path(self.bakery.path(*post.media_paths[0].split("/"))).write_bytes(b"repainted")
        self.assertNotEqual(P.approval_sha(post), first)
        self.assertEqual(P.approval_state(post), "media-changed")

    def test_a_video_is_read_in_pieces_so_a_large_one_never_has_to_fit_in_memory(self):
        big = self.bakery.path("Output", "visuals", "long.mp4")
        os.makedirs(os.path.dirname(big), exist_ok=True)
        Path(big).write_bytes(b"\x00" * (P.HASH_CHUNK_BYTES * 2 + 17))
        import hashlib
        self.assertEqual(P.file_sha256(big), hashlib.sha256(b"\x00" * (P.HASH_CHUNK_BYTES * 2 + 17)).hexdigest())

    def test_an_approval_from_before_this_check_asks_to_be_approved_once_more(self):
        # A batch approved by an older copy of the Factory: the stamp covers the words and the
        # file NAMES only. That is not an error and must not crash; it just is not current.
        post = self.post(self.bakery, approved=False)
        post.status, post.approved_at = "approved", "2029-12-01T09:00:00Z"
        post.sourcing = "passed"
        post.approved_text_sha = P._shown_sha(post)                      # the old-style stamp
        self.assertEqual(P.approval_state(post), "media-unchecked")
        path = self.batch(self.bakery, [post])
        row = outcome(SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True), "p1")
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["approval"]))
        self.assertIn("approve it once more", row["reasons"][0])
        self.assertEqual(self.writes(), [])

    def test_a_file_swapped_after_the_gates_is_caught_on_the_bytes_that_would_be_uploaded(self):
        # The gate passed, and the picture is rewritten before the upload reads it. The upload
        # fingerprints what it actually read, so the swap is caught and no post is created.
        post = self.post(self.bakery)
        path = self.batch(self.bakery, [post])
        real_file = self.bakery.path(*post.media_paths[0].split("/"))
        provider = self.provider(True)
        real_gate, checked = SEND.gate, P.media_digests(post)

        def gate_then_swap(*a, **kw):
            reasons, tgt, paths, _digests = real_gate(*a, **kw)
            Path(real_file).write_bytes(b"swapped a moment too late")
            return reasons, tgt, paths, checked            # the gates saw the approved picture

        with mock.patch.object(SEND, "gate", gate_then_swap):
            report = SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        row = outcome(report, "p1")
        self.assertEqual((row["outcome"], row["gates"]), ("failed", ["approval"]))
        self.assertIn("changed after it was approved", row["reasons"][0])
        self.assertEqual(self.service.accepted, [])                      # nothing was scheduled
        self.assertEqual(Ledger(self.bakery).get(operation_key(post))["state"], "failed")

    def test_the_review_page_is_told_which_of_the_three_things_happened(self):
        post = self.post(self.bakery)
        path = self.batch(self.bakery, [post])
        store = RS.BatchStore(self.bakery, [path])
        self.assertEqual(store.one("p1")["approval"], "current")
        Path(self.bakery.path(*post.media_paths[0].split("/"))).write_bytes(b"remade")
        shown = RS.BatchStore(self.bakery, [path]).one("p1")
        self.assertEqual(shown["approval"], "voided")
        self.assertEqual(shown["approval_note"], RS.APPROVAL_NOTES["media-changed"])
        self.assertIn("picture or video on this post changed", shown["approval_note"])
        self.assertNotIn("review page", shown["approval_note"])           # they are already on it

    def test_the_export_refuses_a_changed_picture_and_copies_only_what_was_approved(self):
        good = self.post(self.bakery, "keep")
        swapped = self.post(self.bakery, "swap", text="Seeded loaves sell out by ten.",
                            when="2030-01-06T15:00:00Z", media=[self.card(self.bakery, "other.png")])
        for p in (good, swapped):
            p.scheduled_time_local = "2030-01-05 06:30"
        path = self.batch(self.bakery, [good, swapped])
        Path(self.bakery.path("Output", "visuals", "other.png")).write_bytes(b"remade after approval")
        report = X.export_posts(self.bakery, [path], run_date="2030-01-05")
        self.assertEqual([e["post_id"] for e in report.exported], ["keep"])
        refused = {r["post_id"]: r["reason"] for r in report.refused}
        self.assertIn("swap", refused)
        self.assertIn("picture or video that changed", refused["swap"])
        self.assertEqual(statuses(self.bakery, path)["swap"], "approved")  # left alone, not marked exported


# ============================================================================= 2. the account moved
class TestTheAccountMustStillPointWhereItDid(SendCase):
    """A profile on the scheduling service keeps its id when somebody reconnects it to a
    different page. The id alone therefore cannot say whose page these words land on."""

    def test_linking_writes_down_where_each_network_points(self):
        listed = A.list_accounts(self.provider(False))
        entries = A.build_targets(self.bakery, listed, 101, {"person": ["tiktok"]})
        self.assertEqual(entries[0]["destination"], "invented.bakery")

    def test_a_reconnected_page_stops_that_network_and_says_what_to_do(self):
        post = self.post(self.bakery, "fb1", identity="company", platform="facebook")
        path = self.batch(self.bakery, [post])
        self.service.accounts[1]["facebookPageId"] = "000999"            # reconnected to another page
        row = outcome(SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True), "fb1")
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["account"]))
        self.assertIn("now points somewhere else", row["reasons"][0])
        self.assertIn("accounts step again", row["reasons"][0])
        self.assertEqual(self.writes(), [])
        self.assertEqual(Ledger(self.bakery).all(), {})

    def test_only_the_network_that_moved_is_stopped(self):
        insta = self.post(self.bakery, "ig1")
        face = self.post(self.bakery, "fb1", identity="company", platform="facebook",
                         text="Seeded loaves sell out by ten.", when="2030-01-06T15:00:00Z")
        path = self.batch(self.bakery, [insta, face])
        self.service.accounts[1]["facebookPageId"] = "000999"
        report = SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)
        self.assertEqual(outcome(report, "ig1")["outcome"], "sent")
        self.assertEqual(outcome(report, "fb1")["outcome"], "blocked")

    def test_a_link_saved_before_this_was_kept_asks_to_be_confirmed_once_not_treated_as_an_error(self):
        brands.update("maple-and-main", {"accounts": {"targets": [target("person", "instagram", 101, where="")]}})
        bakery = brands.load("maple-and-main")
        path = self.batch(bakery, [self.post(bakery)])
        row = outcome(SEND.schedule_batch(bakery, path, self.provider(True), confirm=True), "p1")
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["account"]))
        self.assertIn("saved before the Factory kept a note", row["reasons"][0])
        self.assertNotIn("points somewhere else", row["reasons"][0])
        # ...and running the accounts step again records it, after which the post sends.
        listed = A.list_accounts(self.provider(False))
        A.link(bakery, A.build_targets(bakery, listed, 101, {"person": ["instagram"]}))
        confirmed = brands.load("maple-and-main")
        self.assertEqual(confirmed.target("person", "instagram")["destination"], "invented.bakery")
        self.assertEqual(SEND.schedule_batch(confirmed, path, self.provider(True), confirm=True)["counts"],
                         {"sent": 1})

    def test_the_accounts_step_names_what_moved_and_what_was_never_confirmed(self):
        brands.update("maple-and-main", {"accounts": {"targets": [
            target("person", "instagram", 101, where="somebody.else"),
            target("company", "facebook", 102, where="")]}})
        bakery = brands.load("maple-and-main")
        changes = {c["platform"]: c for c in A.destination_changes(bakery, A.list_accounts(self.provider(False)))}
        self.assertEqual(changes["instagram"]["kind"], "moved")
        self.assertIn("not at somebody.else", changes["instagram"]["note"])
        self.assertEqual(changes["facebook"]["kind"], "never-confirmed")
        self.assertIn("Save it again to confirm", changes["facebook"]["note"])

    def test_a_network_the_service_says_nothing_about_is_not_treated_as_moved(self):
        # The service reports a connection but no page id for it. That is not evidence of a move.
        listed = [{"provider_brand_id": 101, "label": "Invented Bakery", "networks": ["instagram"],
                   "destinations": {}}]
        self.assertEqual(A.destination_changes(self.bakery, listed), [])


# ============================================================================= 3. turned down mid-send
class TestTurningAPostDownDuringASendStopsIt(SendCase):
    def test_a_post_rejected_while_the_run_is_going_is_not_sent(self):
        path = self.batch(self.bakery, [self.post(self.bakery, "p1"),
                                        self.post(self.bakery, "p2", text="Seeded loaves sell out by ten.",
                                                  when="2030-01-06T15:00:00Z")])
        provider = self.provider(True)
        real = provider.schedule
        store = RS.BatchStore(self.bakery, [path])

        def turned_down_meanwhile(post, *a, **kw):
            if post.id == "p1":                                          # the person is in the review page
                store.reject("p2", store.one("p2")["rev"], note="not this week")
            return real(post, *a, **kw)

        provider.schedule = turned_down_meanwhile
        report = SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        self.assertEqual(outcome(report, "p1")["outcome"], "sent")
        row = outcome(report, "p2")
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["approval"]))
        self.assertIn("changed or turned down while this run was going", row["reasons"][0])
        self.assertEqual(len(self.service.accepted), 1)
        self.assertEqual(statuses(self.bakery, path)["p2"], "rejected")   # the person's decision stands

    def test_an_edit_that_lands_between_the_gates_and_the_reservation_stops_the_send(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        provider = self.provider(True)
        real_claim, edited = SEND._claim, []

        def edit_between(led, brand, batch_path, post, name, pbid):
            if not edited:                                    # the person types in the review page here
                edited.append(True)
                store = RS.BatchStore(brand, [batch_path])
                store.edit("p1", store.one("p1")["rev"], text="Rye is out at six.")
            return real_claim(led, brand, batch_path, post, name, pbid)

        with mock.patch.object(SEND, "_claim", edit_between):
            report = SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        self.assertEqual(outcome(report, "p1")["outcome"], "blocked")
        self.assertEqual(self.service.accepted, [])
        self.assertEqual(Ledger(self.bakery).all(), {})

    def test_an_outcome_is_never_stamped_on_a_version_that_was_not_sent(self):
        # The post goes out as approved, and something rewrites it while the answer is coming
        # back. The newer words must not end up marked "scheduled": they were never sent.
        path = self.batch(self.bakery, [self.post(self.bakery)])
        provider = self.provider(True)
        real = provider.schedule

        def rewrite_after_it_left(post, *a, **kw):
            ppid = real(post, *a, **kw)
            posts, meta = P.load_batch(path, self.bakery.id)              # a Claude session remaking posts
            posts[0].text = "Rye is out at six."
            P.save_batch(posts, path, meta)
            return ppid

        provider.schedule = rewrite_after_it_left
        report = SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        row = outcome(report, "p1")
        self.assertEqual(row["outcome"], "sent")
        self.assertIn("newer version was left alone", row["reasons"][0])
        saved = P.load_batch(path, self.bakery.id)[0][0]
        self.assertEqual(saved.text, "Rye is out at six.")                # the newer words are kept
        self.assertNotEqual(saved.status, "scheduled")                    # and NOT claimed to have gone out
        self.assertIn("has NOT been sent", saved.feedback)
        receipts, _bad = S.read_lines(SEND.sent_log_path(self.bakery))
        self.assertEqual(receipts[0]["text"], "Rye is out at seven.")      # the record keeps what really went

    def test_the_review_page_will_not_change_a_post_that_is_being_sent_right_now(self):
        post = self.post(self.bakery)
        path = self.batch(self.bakery, [post])
        Ledger(self.bakery).reserve(post, "metricool", 101, batch=os.path.basename(path))
        store = RS.BatchStore(self.bakery, [path])
        with self.assertRaises(RS.Refusal) as cm:
            store.edit("p1", store.one("p1")["rev"], text="Rye is out at six.")
        self.assertIn("being sent to the scheduling service right now", str(cm.exception))
        self.assertEqual(P.load_batch(path, self.bakery.id)[0][0].text, "Rye is out at seven.")


# ============================================================================= 4. editing round an unclear send
class TestEditingCannotWalkRoundAnUnclearSend(SendCase):
    def park_one(self):
        """One post whose send got no clear answer: the service took it, the answer was lost."""
        path = self.batch(self.bakery, [self.post(self.bakery)])
        self.service.accept_then_fail_with = http_error(502)
        self.assertEqual(outcome(SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True),
                                 "p1")["outcome"], "unknown")
        return path

    def test_the_review_page_refuses_to_edit_approve_or_turn_down_an_unclear_post(self):
        path = self.park_one()
        store = RS.BatchStore(self.bakery, [path])
        shown = store.one("p1")
        self.assertEqual(shown["approve_block_code"], "unsettled")
        self.assertIn("run a results check", shown["approve_block"].lower())
        for change in (lambda: store.edit("p1", shown["rev"], text="Rye is out at eight."),
                       lambda: store.reject("p1", shown["rev"], note="no"),
                       lambda: store.approve("p1", shown["rev"], shown["content_sha"], acknowledged=True)):
            with self.assertRaises(RS.Refusal) as cm:
                change()
            self.assertIn("never got a clear answer", str(cm.exception))

    def test_the_posting_record_refuses_a_new_reservation_even_when_the_words_changed(self):
        self.park_one()
        led = Ledger(self.bakery)
        changed = self.post(self.bakery, text="Rye is out at eight.")
        _key, why = led.reserve(changed, "metricool", 101)
        self.assertIn("may or may not have gone out", why)
        self.assertIn("results check", why)

    def test_a_changed_copy_of_an_unclear_post_is_not_sent_by_a_later_run(self):
        path = self.park_one()
        posts, meta = P.load_batch(path, self.bakery.id)                  # edited by hand, round the review page
        posts[0].text = "Rye is out at eight."
        posts[0].feedback = ""
        approve(posts[0])
        P.save_batch(posts, path, meta)
        row = outcome(SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True), "p1")
        self.assertEqual(row["outcome"], "refused")
        self.assertEqual(len(self.service.accepted), 1)                   # still exactly the one that arrived

    def test_a_dry_run_says_the_same_thing_without_reserving_anything(self):
        path = self.park_one()
        posts, meta = P.load_batch(path, self.bakery.id)
        posts[0].text, posts[0].feedback = "Rye is out at eight.", ""
        approve(posts[0])
        P.save_batch(posts, path, meta)
        before = Ledger(self.bakery).all()
        row = outcome(SEND.schedule_batch(self.bakery, path, self.provider(False)), "p1")
        self.assertEqual(row["outcome"], "refused")
        self.assertEqual(Ledger(self.bakery).all(), before)

    def test_once_it_is_settled_the_edit_is_allowed_again(self):
        path = self.park_one()
        R.settle_by_hand(self.bakery, "p1", arrived=False)                 # a person looked at the calendar
        store = RS.BatchStore(self.bakery, [path])
        shown = store.edit("p1", store.one("p1")["rev"], text="Rye is out at eight.")
        self.assertEqual(shown["text"], "Rye is out at eight.")

    def test_a_second_version_from_the_same_batch_cannot_follow_one_that_went_out(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        self.assertEqual(SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)["counts"],
                         {"sent": 1})
        posts, meta = P.load_batch(path, self.bakery.id)
        posts[0].text, posts[0].status = "Rye is out at eight.", "lint_pass"
        approve(posts[0])
        P.save_batch(posts, path, meta)
        row = outcome(SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True), "p1")
        self.assertEqual(row["outcome"], "refused")
        self.assertIn("already went out from this batch", " ".join(row["reasons"]))
        self.assertEqual(len(self.service.accepted), 1)

    def test_a_damaged_posting_record_stops_the_review_page_too(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        led = Ledger(self.bakery)
        led.reserve(self.post(self.bakery), "metricool", 101)
        Path(led.path).write_text("{ not json", encoding="utf-8")
        store = RS.BatchStore(self.bakery, [path])
        with self.assertRaises(RS.Refusal) as cm:
            store.edit("p1", 0, text="Rye is out at six.")
        self.assertIn("damaged", str(cm.exception))


# ============================================================================= 5. two results checks at once
class TestTwoResultsChecksDoNotTreadOnEachOther(SendCase):
    def test_a_slow_check_never_writes_off_a_send_that_moved_on_while_it_looked(self):
        led = Ledger(self.bakery)
        post = self.post(self.bakery)
        key, _ = led.reserve(post, "metricool", 101)
        led.mark_unknown(key, "the answer was lost")
        provider = self.provider(False)
        real = provider.calendar

        def slow_look(*a, **kw):
            entries = real(*a, **kw)
            # While this check waits for the calendar, a quicker one frees the send and a sender
            # takes it again and gets it away.
            led.mark_failed(key, "a quicker check freed it")
            led.reserve(post, "metricool", 101)
            led.mark_sent(key, "9777")
            return entries

        provider.calendar = slow_look
        report = led.reconcile(provider, self.bakery.timezone, now=after_the_wait())
        self.assertEqual(led.get(key)["state"], "sent")                   # the newer truth stands
        self.assertEqual(led.get(key)["provider_post_id"], "9777")
        self.assertEqual(report["not_found"], [])
        self.assertIn("already scheduled", led.reserve(post, "metricool", 101)[1])

    def test_a_slow_check_never_overwrites_a_fresh_reservation(self):
        led = Ledger(self.bakery)
        post = self.post(self.bakery)
        key, _ = led.reserve(post, "metricool", 101)
        led.mark_unknown(key, "the answer was lost")
        provider = self.provider(False)
        real = provider.calendar

        def slow_look(*a, **kw):
            entries = real(*a, **kw)
            led.mark_failed(key, "a quicker check freed it")
            led.reserve(post, "metricool", 101)                           # a sender is on it right now
            return entries

        provider.calendar = slow_look
        led.reconcile(provider, self.bakery.timezone, now=after_the_wait())
        self.assertEqual(led.get(key)["state"], "reserved")
        self.assertIn("sending it right now", led.reserve(post, "metricool", 101)[1])

    def test_a_check_that_finds_it_still_writes_when_nothing_moved(self):
        led = Ledger(self.bakery)
        post = self.post(self.bakery)
        key, _ = led.reserve(post, "metricool", 101)
        led.mark_unknown(key, "the answer was lost")
        self.service.calendar["101"].append({
            "id": 9123, "text": "Rye is out at seven.", "draft": False,
            "publicationDate": {"dateTime": "2030-01-05T10:00:00"},
            "providers": [{"network": "instagram", "status": "PENDING"}]})
        report = led.reconcile(self.provider(False), self.bakery.timezone, now=after_the_wait())
        self.assertEqual(report["found"], ["p1"])
        self.assertEqual(led.get(key)["provider_post_id"], "9123")


# ============================================================================= 6. the calendar has not caught up
class TestAnEmptyCalendarIsNotProof(SendCase):
    def park_one(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        self.service.accept_then_fail_with = http_error(502)              # it DID arrive; the answer was lost
        SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)
        return path

    def blank_calendar_provider(self, payload=b""):
        inner = self.service

        def answers_blank(req, timeout=None):
            if "/v2/scheduler/posts" in req.full_url and req.get_method() == "GET":
                return FakeResponse(payload)
            return inner(req, timeout=timeout)

        return Metricool(Transport(allow_writes=False, opener=answers_blank), token="t" * 12, user_id="42")

    def lagging_calendar_provider(self):
        """A calendar that answers properly and simply does not show the post yet."""
        return self.blank_calendar_provider(b'{"data": []}')

    def test_an_empty_body_leaves_the_send_unknown_instead_of_freeing_it(self):
        path = self.park_one()
        rep = R.reconcile(self.bakery, self.blank_calendar_provider(), now=after_the_wait())
        self.assertEqual((rep["found"], rep["not_found"]), ([], []))
        self.assertEqual([c["post_id"] for c in rep["could_not_check"]], ["p1"])
        self.assertEqual(Ledger(self.bakery).unresolved()[operation_key(self.post(self.bakery))]["state"], "unknown")
        self.assertEqual(statuses(self.bakery, path), {"p1": "blocked"})   # still parked, not offered again

    def test_a_calendar_in_a_shape_the_factory_does_not_know_is_refused_in_plain_words(self):
        self.park_one()
        for payload in (b'{"data": {"posts": []}}', b'{"data": ["not a post"]}', b"not json at all"):
            rep = R.reconcile(self.bakery, self.blank_calendar_provider(payload), now=after_the_wait())
            self.assertEqual(rep["not_found"], [], payload)
            self.assertTrue(rep["could_not_check"], payload)
            why = rep["could_not_check"][0]["why"]
            self.assertNotIn("Traceback", why)
            self.assertTrue(why.endswith(".") or why.endswith("minutes."), why)

    def test_a_calendar_read_too_soon_after_the_send_keeps_it_unknown_and_says_it_will_look_again(self):
        # The post arrived, and the service's calendar has not caught up yet: it answers properly
        # and the post simply is not on it. Straight after a send that is not evidence of anything.
        path = self.park_one()
        rep = R.reconcile(self.bakery, self.lagging_calendar_provider())
        self.assertEqual((rep["found"], rep["not_found"]), ([], []))
        self.assertEqual(rep["too_soon"], ["p1"])
        self.assertEqual(statuses(self.bakery, path), {"p1": "blocked"})
        self.assertIn("p1", rep["still_waiting"])

    def test_once_enough_time_has_passed_an_empty_calendar_does_free_it(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        self.service.fail_next_post_with = http_error(500)                # it never arrived
        SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True)
        rep = R.reconcile(self.bakery, self.provider(False), now=after_the_wait())
        self.assertEqual(rep["not_found"], ["p1"])
        self.assertEqual(statuses(self.bakery, path), {"p1": "approved"})

    def test_settling_it_by_hand_still_works_while_the_calendar_cannot_be_read(self):
        path = self.park_one()
        R.reconcile(self.bakery, self.blank_calendar_provider(), now=after_the_wait())
        healed = R.settle_by_hand(self.bakery, "p1", arrived=True, provider_post_id="9000")
        self.assertEqual(healed, [("p1", "scheduled")])
        self.assertEqual(statuses(self.bakery, path), {"p1": "scheduled"})

    def test_one_unreadable_calendar_does_not_stop_the_others_being_settled(self):
        first = self.batch(self.bakery, [self.post(self.bakery, "p1")], "one.json")
        second = self.batch(self.bakery, [self.post(self.bakery, "p2", text="Seeded loaves sell out by ten.",
                                                    when="2030-01-06T15:00:00Z")], "two.json")
        self.service.accept_then_fail_with = http_error(502)
        SEND.schedule_batch(self.bakery, first, self.provider(True), confirm=True)
        self.service.accept_then_fail_with = http_error(502)
        SEND.schedule_batch(self.bakery, second, self.provider(True), confirm=True)
        inner, calls = self.service, []

        def blank_for_the_first_look(req, timeout=None):
            if "/v2/scheduler/posts" in req.full_url and req.get_method() == "GET":
                calls.append(1)
                if len(calls) == 1:
                    return FakeResponse(b"")
            return inner(req, timeout=timeout)

        provider = Metricool(Transport(allow_writes=False, opener=blank_for_the_first_look),
                             token="t" * 12, user_id="42")
        rep = R.reconcile(self.bakery, provider, now=after_the_wait())
        unreadable = [c["post_id"] for c in rep["could_not_check"]]
        settled = rep["found"] + rep["not_found"]
        self.assertEqual(len(unreadable), 1)                              # whichever was looked at first
        self.assertEqual(len(settled), 1)
        self.assertEqual(sorted(unreadable + settled), ["p1", "p2"])


# ============================================================================= 7. the slot passed while uploading
class TestASlotThatPassesWhileFilesUploadStopsTheSend(SendCase):
    def send_with_a_slow_upload(self, minutes, when="2030-01-05T15:00:00Z", start_minutes_before=31):
        """Schedule a post `start_minutes_before` minutes before its time, then let the upload
        take `minutes`. Returns (report, clock)."""
        due = datetime.fromisoformat(when.replace("Z", "+00:00"))
        clock = MovingClock(due - timedelta(minutes=start_minutes_before))
        path = self.batch(self.bakery, [self.post(self.bakery, when=when)])
        provider = self.provider(True)
        real = provider.upload

        def slow(*a, **kw):
            link = real(*a, **kw)
            clock.forward(minutes)
            return link

        provider.upload = slow
        with clock.patch():
            report = SEND.schedule_batch(self.bakery, path, provider, confirm=True)
        return report, path

    def test_a_post_whose_time_passes_during_the_upload_is_not_sent(self):
        report, path = self.send_with_a_slow_upload(35)
        row = outcome(report, "p1")
        self.assertEqual((row["outcome"], row["gates"]), ("failed", ["time"]))
        self.assertIn("finished uploading", row["reasons"][0])
        self.assertIn("Give it a new time", row["reasons"][0])
        self.assertEqual(self.service.accepted, [])                       # no scheduling request was made
        self.assertEqual(statuses(self.bakery, path), {"p1": "approved"})  # still approved, for a new time

    def test_the_reservation_is_released_so_a_new_time_can_be_sent(self):
        report, _path = self.send_with_a_slow_upload(35)
        self.assertEqual(report["counts"], {"failed": 1})
        led = Ledger(self.bakery)
        key = operation_key(self.post(self.bakery))
        self.assertEqual(led.get(key)["state"], "failed")
        self.assertIn("finished uploading", led.get(key)["note"])
        self.assertIsNone(led.reserve(self.post(self.bakery), "metricool", 101)[1])

    def test_a_post_still_comfortably_in_the_future_is_unaffected(self):
        report, _path = self.send_with_a_slow_upload(5, start_minutes_before=600)
        self.assertEqual(outcome(report, "p1")["outcome"], "sent")

    def test_a_slot_that_slips_inside_the_buffer_is_stopped_too(self):
        # 31 minutes to go, the upload takes 10: 21 minutes left, inside the 30-minute buffer.
        report, _path = self.send_with_a_slow_upload(10)
        row = outcome(report, "p1")
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("less than %d minutes away" % P.FUTURE_SLOT_BUFFER_MIN, row["reasons"][0])
        self.assertEqual(self.service.accepted, [])

    def test_a_reservation_written_off_while_the_upload_ran_does_not_then_send(self):
        path = self.batch(self.bakery, [self.post(self.bakery)])
        provider = self.provider(True)
        real = provider.upload
        led = Ledger(self.bakery)

        def upload_then_someone_writes_it_off(*a, **kw):
            link = real(*a, **kw)
            led.mark_failed(operation_key(self.post(self.bakery)), "a results check gave up on it")
            return link

        provider.upload = upload_then_someone_writes_it_off
        row = outcome(SEND.schedule_batch(self.bakery, path, provider, confirm=True), "p1")
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("written this send off", row["reasons"][0])
        self.assertEqual(self.service.accepted, [])


# ============================================================================= the video loops use the same gates
VIDEO_TARGETS = [target("person", "instagram", 101), target("person", "tiktok", 101),
                 target("person", "youtube", 101), target("company", "facebook", 102)]
TODAY = datetime(2030, 1, 1).date()
EARLY = datetime(2029, 12, 1, tzinfo=timezone.utc)


class TestTheDailyShortsGoThroughTheSameGates(SendCase):
    BAKERY_ANSWERS = brand_answers(BAKERY, targets=VIDEO_TARGETS,
                                   video={"inbox_folder": "Inputs/Edited"})

    def planned_and_approved(self):
        drop_video(self.bakery.path("Inputs", "Edited"), "rye loaf.mp4", "Why our rye takes three days.")
        plan = SH.plan_shorts(self.bakery, days=14, save=True, today=TODAY)
        approve_batch(self.bakery, plan["batch"])
        return plan["batch"]

    def test_a_changed_video_voids_the_approval_of_a_short(self):
        path = self.planned_and_approved()
        posts, _meta = P.load_batch(path, self.bakery.id)
        video = self.bakery.path(*posts[0].media_paths[0].split("/"))
        Path(video).write_bytes(Path(video).read_bytes() + b"re-exported by the editor")
        report = SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True, now=EARLY)
        row = outcome(report, posts[0].id)
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["approval"]))
        self.assertIn("picture or video that changed", row["reasons"][0])
        self.assertEqual(self.service.accepted, [])

    def test_a_drifted_destination_stops_a_short(self):
        path = self.planned_and_approved()
        self.service.accounts[0]["tiktok"] = "somebody.elses.account"
        report = SEND.schedule_batch(self.bakery, path, self.provider(True), confirm=True, now=EARLY)
        tiktok = [r for r in report["posts"] if r["platform"] == "tiktok"]
        self.assertTrue(tiktok)
        for row in tiktok:
            self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["account"]))
            self.assertIn("now points somewhere else", row["reasons"][0])
        self.assertNotIn("tiktok", [body["providers"][0]["network"] for _a, body in self.service.accepted])


class TestTheTestAndPromoteLoopGoesThroughTheSameGates(SendCase):
    BAKERY_ANSWERS = brand_answers(BAKERY, targets=VIDEO_TARGETS,
                                   video={"inbox_folder": "Inputs/Edited", "test_and_promote": True})

    def wave(self):
        folder = self.bakery.path("Inputs", "Edited")
        drop_video(folder, "rye loaf__warm.mp4", "Why our rye takes three days, slowly.")
        drop_video(folder, "rye loaf__fast.mp4", "Three days of rye, in thirty seconds.")
        plan = PR.plan_test_wave(self.bakery, days=7, save=True, today=TODAY)
        approve_batch(self.bakery, plan["batch"])
        return plan["batch"]

    def test_a_changed_video_voids_the_approval_in_the_loop(self):
        path = self.wave()
        posts, _meta = P.load_batch(path, self.bakery.id)
        video = self.bakery.path(*posts[0].media_paths[0].split("/"))
        Path(video).write_bytes(Path(video).read_bytes() + b"a new cut")
        report = PR.send(self.bakery, path, self.provider(True), confirm=True)
        row = outcome(report, posts[0].id)
        self.assertEqual((row["outcome"], row["gates"]), ("blocked", ["approval"]))
        self.assertIn("picture or video that changed", row["reasons"][0])

    def test_a_drifted_destination_stops_the_whole_wave(self):
        path = self.wave()
        self.service.accounts[0]["tiktok"] = "somebody.elses.account"     # the test runs on TikTok
        report = PR.send(self.bakery, path, self.provider(True), confirm=True)
        self.assertEqual(set(r["outcome"] for r in report["posts"]), {"blocked"})
        self.assertIn("now points somewhere else", outcome(report, report["posts"][0]["id"])["reasons"][0])
        self.assertEqual(self.service.accepted, [])


# ============================================================================= the record's own reading of a post
class TestWhatTheRecordSaysAboutAPost(SendCase):
    def test_standing_names_the_one_thing_in_the_way(self):
        post = self.post(self.bakery)
        led = Ledger(self.bakery)
        self.assertEqual(standing({}, post, "w.json"), (None, None))
        key, _ = led.reserve(post, "metricool", 101, batch="w.json")
        self.assertEqual(standing(led.all(), post, "w.json")[0], "sending")
        led.mark_sent(key, "9000")
        self.assertEqual(standing(led.all(), post, "w.json")[0], "sent")
        changed = self.post(self.bakery, text="Rye is out at eight.")
        self.assertEqual(standing(led.all(), changed, "w.json")[0], "sent-before")
        self.assertEqual(standing(led.all(), changed, "another.json"), (None, None))

    def test_an_abandoned_reservation_reads_as_unsettled_not_as_being_sent(self):
        post = self.post(self.bakery)
        led = Ledger(self.bakery)
        led.reserve(post, "metricool", 101, batch="w.json")
        long_after = time.time() + 60 * 60
        self.assertEqual(standing(led.all(), post, "w.json", now=long_after)[0], "unsettled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
