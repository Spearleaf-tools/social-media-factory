"""Posting-safety tests: a dry run is dry, a send is recorded before it happens, a crash cannot
cause a double post, and a damaged record stops everything instead of reading as empty.

    python -m unittest discover -s tests -t . -v

Every response from the scheduling service in this file is invented.
"""
from __future__ import annotations

import io
import json
import multiprocessing
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                    # noqa: E402
from smf.posting import ledger as L                                       # noqa: E402
from smf.posting.metricool import Metricool, local_wall_clock             # noqa: E402
from smf.posting.provider import DryRunViolation, ProviderError, Transport  # noqa: E402
from smf.studio.posts import Post                                         # noqa: E402
from tests.test_brands import BAKERY                                      # noqa: E402


class FakeResponse(io.BytesIO):
    def __init__(self, payload, status=200, headers=None):
        io.BytesIO.__init__(self, json.dumps(payload).encode("utf-8") if not isinstance(payload, bytes) else payload)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeService(object):
    """Stands in for the scheduling service. Records every request it receives."""

    def __init__(self):
        self.requests = []
        self.calendar_entries = []
        self.fail_next_post_with = None

    def __call__(self, req, timeout=None):
        method, url = req.get_method(), req.full_url
        self.requests.append((method, url.split("?")[0]))
        if "/admin/profiles-auth" in url:
            return FakeResponse([{"id": 101, "label": "Invented Bakery", "instagram": "invented.bakery",
                                  "facebookPageId": "000111"},
                                 {"id": 555, "label": "Invented Clinic", "instagram": "invented.clinic"}])
        if "/v2/scheduler/posts" in url and method == "GET":
            return FakeResponse({"data": self.calendar_entries})
        if "/v2/scheduler/posts" in url and method == "POST":
            if self.fail_next_post_with is not None:
                exc, self.fail_next_post_with = self.fail_next_post_with, None
                raise exc
            body = json.loads(req.data.decode("utf-8"))
            entry = {"id": 9000 + len(self.calendar_entries), "text": body["text"],
                     "publicationDate": body["publicationDate"], "providers": body["providers"], "draft": body["draft"]}
            self.calendar_entries.append(entry)
            return FakeResponse({"data": {"id": entry["id"]}})
        raise AssertionError("unexpected request %s %s" % (method, url))

    @property
    def writes(self):
        return [r for r in self.requests if r[0] not in ("GET", "HEAD")]


class PostingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="posting ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
        self.service = FakeService()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def provider(self, allow_writes):
        return Metricool(Transport(allow_writes=allow_writes, opener=self.service), token="t" * 12, user_id="42")

    def post(self, pid="p1", text="Rye is out at seven.", when="2030-01-05T15:00:00Z", platform="instagram", **kw):
        return Post(id=pid, brand=self.brand.id, identity="person", platform=platform, text=text,
                    scheduled_time_iso=when, media_paths=["x.png"], **kw)


class TestDryRunIsDry(PostingCase):
    def test_reads_work_and_no_write_leaves_the_computer(self):
        m = self.provider(allow_writes=False)
        accounts = m.list_accounts()
        self.assertEqual([a["provider_brand_id"] for a in accounts], [101, 555])
        self.assertEqual(accounts[0]["networks"], ["facebook", "instagram"])
        self.assertEqual(m.calendar(101, "2030-01-01T00:00:00", "2030-01-10T00:00:00", "America/New_York"), [])
        with self.assertRaises(DryRunViolation):
            m.schedule(self.post(), 101, [], "America/New_York")
        f = Path(self.tmp.name) / "card.png"
        f.write_bytes(b"not really a png")
        with self.assertRaises(DryRunViolation):
            m.upload(str(f), 101)
        self.assertEqual(self.service.writes, [])

    def test_there_is_no_draft_mode_that_sneaks_a_write_through(self):
        body = self.provider(False).build_body(self.post(), ["https://example.com/a.png"], "America/New_York")
        self.assertIs(body["draft"], False)             # a real schedule or nothing; never a quiet remote draft

    def test_missing_keys_say_what_is_missing_and_what_plan_is_needed(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("smf.keys.KEYS_FILE", "/nonexistent/keys.env"):
            import smf.keys
            smf.keys.load(force=True)
            with self.assertRaises(ProviderError) as cm:
                Metricool(Transport())
        self.assertEqual(cm.exception.kind, "not-configured")
        self.assertIn("Advanced", str(cm.exception))


class TestRequestShape(PostingCase):
    def test_utc_time_is_converted_into_the_brands_zone_not_trimmed(self):
        self.assertEqual(local_wall_clock("2030-01-05T15:00:00Z", "America/New_York"), "2030-01-05T10:00:00")
        self.assertEqual(local_wall_clock("2030-07-05T15:00:00Z", "America/New_York"), "2030-07-05T11:00:00")
        self.assertEqual(local_wall_clock("2030-01-05T10:00:00", "America/New_York"), "2030-01-05T10:00:00")

    def test_thread_first_comment_and_reel(self):
        m = self.provider(False)
        p = self.post(platform="twitter", thread=["two", "three"], first_comment="link in here")
        body = m.build_body(p, [], "America/New_York")
        self.assertEqual([d["text"] for d in body["descendants"]], ["two", "three"])
        self.assertEqual(body["firstCommentText"], "link in here")
        reel = self.post(media_type="reel")
        self.assertEqual(m.build_body(reel, ["u"], "America/New_York")["instagramData"]["type"], "REEL")
        self.assertNotIn("instagramData", m.build_body(self.post(), ["u"], "America/New_York"))

    def test_a_refused_key_explains_the_plan_requirement_and_never_shows_the_key(self):
        def refuse(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b'{"error":"token tttttttttttt bad"}'))
        m = Metricool(Transport(opener=refuse), token="tttttttttttt", user_id="42")
        with mock.patch.dict(os.environ, {"METRICOOL_USER_TOKEN": "tttttttttttt"}):
            import smf.keys
            smf.keys.load(force=True)
            with self.assertRaises(ProviderError) as cm:
                m.list_accounts()
        self.assertEqual(cm.exception.kind, "no-api-access")
        self.assertNotIn("tttttttttttt", str(cm.exception))


class TestLedger(PostingCase):
    def test_normal_path_and_the_same_post_is_never_sent_twice(self):
        led = L.Ledger(self.brand)
        key, why = led.reserve(self.post(), "metricool", 101)
        self.assertIsNone(why)
        led.mark_sent(key, "9001")
        key2, why2 = led.reserve(self.post(), "metricool", 101)
        self.assertEqual(key, key2)
        self.assertIn("already scheduled", why2)

    def test_an_edit_makes_it_a_different_operation_but_not_a_way_round_the_record(self):
        # Changing the words makes a new key. That must not become a way to send the same post
        # twice while the first attempt is still in the air, so the post's id is checked too.
        led = L.Ledger(self.brand)
        k1, _ = led.reserve(self.post(), "metricool", 101)
        k2, why = led.reserve(self.post(text="Rye is out at eight."), "metricool", 101)
        self.assertNotEqual(k1, k2)
        self.assertIn("being sent right now", why)
        led.mark_failed(k1, "the service said no")                   # settled: the edit may go
        k3, why3 = led.reserve(self.post(text="Rye is out at eight."), "metricool", 101)
        self.assertEqual((k3, why3), (k2, None))

    def test_a_definite_refusal_can_be_retried(self):
        led = L.Ledger(self.brand)
        key, _ = led.reserve(self.post(), "metricool", 101)
        led.mark_failed(key, "the service said no")
        self.assertIsNone(led.reserve(self.post(), "metricool", 101)[1])

    def test_an_unclear_outcome_blocks_until_reconciled(self):
        led = L.Ledger(self.brand)
        key, _ = led.reserve(self.post(), "metricool", 101)
        led.mark_unknown(key, "timed out")
        self.assertIn("results check", led.reserve(self.post(), "metricool", 101)[1])

    def test_reconcile_finds_the_post_that_did_arrive(self):
        led = L.Ledger(self.brand)
        key, _ = led.reserve(self.post(), "metricool", 101)
        led.mark_unknown(key, "connection dropped after sending")
        self.service.calendar_entries.append({"id": 9123, "text": "Rye is out at seven.",
                                              "publicationDate": {"dateTime": "2030-01-05T10:00:00"},
                                              "providers": [{"network": "instagram", "status": "PENDING"}]})
        rep = led.reconcile(self.provider(False), "America/New_York")
        self.assertEqual(rep, {"found": ["p1"], "not_found": [], "too_soon": [], "could_not_check": []})
        self.assertEqual(led.get(key)["state"], "sent")
        self.assertEqual(led.get(key)["provider_post_id"], "9123")
        self.assertEqual(self.service.writes, [])

    def test_reconcile_frees_the_post_that_never_arrived_once_enough_time_has_passed(self):
        led = L.Ledger(self.brand)
        key, _ = led.reserve(self.post(), "metricool", 101)
        led.mark_unknown(key, "timed out")
        straight_away = led.reconcile(self.provider(False), "America/New_York")
        self.assertEqual((straight_away["not_found"], straight_away["too_soon"]), ([], ["p1"]))
        self.assertEqual(led.get(key)["state"], "unknown")           # a calendar can lag: still unknown
        later = led.reconcile(self.provider(False), "America/New_York",
                              now=time.time() + L.NOT_FOUND_AFTER_SECONDS + 60)
        self.assertEqual(later["not_found"], ["p1"])
        self.assertIsNone(led.reserve(self.post(), "metricool", 101)[1])

    def test_a_run_that_died_mid_send_is_treated_as_possibly_sent(self):
        led = L.Ledger(self.brand)
        key, _ = led.reserve(self.post(), "metricool", 101)
        data = json.loads(Path(led.path).read_text(encoding="utf-8"))
        data["operations"][key]["reserved_at_ts"] = time.time() - 3600          # an hour ago, never finished
        Path(led.path).write_text(json.dumps(data), encoding="utf-8")
        _, why = led.reserve(self.post(), "metricool", 101)
        self.assertIn("stopped half way", why)
        self.assertEqual(led.get(key)["state"], "unknown")

    def test_a_damaged_record_stops_everything(self):
        led = L.Ledger(self.brand)
        led.reserve(self.post(), "metricool", 101)
        Path(led.path).write_text("{ not json", encoding="utf-8")
        with self.assertRaises(L.LedgerError) as cm:
            led.reserve(self.post(), "metricool", 101)
        self.assertIn("damaged", str(cm.exception))
        self.assertEqual(Path(led.path).read_text(encoding="utf-8"), "{ not json")     # and it was not overwritten

    def test_a_record_from_another_brand_is_refused(self):
        led = L.Ledger(self.brand)
        led.reserve(self.post(), "metricool", 101)
        data = json.loads(Path(led.path).read_text(encoding="utf-8"))
        data["brand"] = "stride-physio"
        Path(led.path).write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(L.LedgerError):
            led.all()

    def test_a_stale_lock_is_taken_over_and_a_live_one_is_respected(self):
        led = L.Ledger(self.brand)
        Path(led.lock_path).write_text("999999 0", encoding="ascii")
        old = time.time() - L.LOCK_STALE_SECONDS - 5
        os.utime(led.lock_path, (old, old))
        self.assertIsNone(led.reserve(self.post(), "metricool", 101)[1])
        Path(led.lock_path).write_text("999999 0", encoding="ascii")            # fresh: someone is posting now
        with mock.patch.object(L._Lock, "__init__", lambda s, path, wait_seconds=30: (setattr(s, "path", path),
                               setattr(s, "wait", 0.3), setattr(s, "fd", None)) and None):
            with self.assertRaises(L.LedgerError) as cm:
                led.reserve(self.post(pid="p2", text="Another."), "metricool", 101)
        self.assertIn("Another run is posting", str(cm.exception))
        os.unlink(led.lock_path)

    def test_windows_refusing_the_lock_while_it_is_being_cleared_means_wait_not_crash(self):
        # On Windows, creating a file another run is deleting at that moment says "permission denied".
        led, real_open, refusals = L.Ledger(self.brand), os.open, []

        def open_while_clearing(path, flags, *more):
            if path == led.lock_path and len(refusals) < 2:
                refusals.append(path)
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, flags, *more)

        with mock.patch.object(L.os, "open", open_while_clearing):
            self.assertIsNone(led.reserve(self.post(), "metricool", 101)[1])
        self.assertEqual(len(refusals), 2)
        self.assertFalse(os.path.exists(led.lock_path))                       # let go afterwards

    def test_a_lock_that_is_never_allowed_stops_in_plain_words(self):
        led = L.Ledger(self.brand)

        def never(path, flags, *more):
            raise PermissionError(13, "Permission denied", path)

        with mock.patch.object(L._Lock, "__init__", lambda s, path, wait_seconds=30: (setattr(s, "path", path),
                               setattr(s, "wait", 0.3), setattr(s, "fd", None)) and None):
            with mock.patch.object(L.os, "open", never):
                with self.assertRaises(L.LedgerError) as cm:
                    led.reserve(self.post(), "metricool", 101)
        self.assertIn("could not be opened", str(cm.exception))
        self.assertEqual(led.all(), {})                                        # nothing was reserved


def _race(home, brand_id, n, out_q):
    """One competing process: try to reserve the same post; report whether it won."""
    sys.path.insert(0, str(ROOT))
    from smf import brands as b
    from smf.posting import ledger as led_mod
    from smf.studio.posts import Post as P2
    brand = b.Brand(brand_id, home, {"id": brand_id, "name": "x"})
    post = P2(id="p1", brand=brand_id, identity="person", platform="instagram", text="Rye is out at seven.",
              scheduled_time_iso="2030-01-05T15:00:00Z", media_paths=["x.png"])
    _key, why = led_mod.Ledger(brand).reserve(post, "metricool", 101)
    out_q.put((n, why is None))


class TestCompetingProcesses(PostingCase):
    def test_eight_runs_start_at_once_and_exactly_one_may_send(self):
        ctx = multiprocessing.get_context("spawn")            # the only start method Windows has
        q = ctx.Queue()
        procs = [ctx.Process(target=_race, args=(self.brand.home, self.brand.id, i, q)) for i in range(8)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
        results = [q.get(timeout=10) for _ in procs]
        self.assertEqual(sum(1 for _n, won in results if won), 1, results)
        self.assertEqual(len(L.Ledger(self.brand).all()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
