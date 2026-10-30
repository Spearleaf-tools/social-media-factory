"""Key verification: one harmless read per service, plain reasons, nothing of the key on disk.

    python -m unittest discover -s tests -t . -v

Every service response in this file is invented.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import bootstrap, keys, status, verify_keys          # noqa: E402
from smf.posting.provider import Transport                      # noqa: E402

TOKEN, ELEVEN, APIFY = "mmmmmmmm-token", "eeeeeeee-key", "aaaaaaaa-token"


class Reply(io.BytesIO):
    def __init__(self, payload, status=200):
        io.BytesIO.__init__(self, json.dumps(payload).encode("utf-8"))
        self.status, self.headers = status, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Services(object):
    def __init__(self, refuse=()):
        self.refuse, self.seen = set(refuse), []

    def __call__(self, req, timeout=None):
        self.seen.append((req.get_method(), req.full_url.split("?")[0]))
        host = req.full_url.split("/")[2]
        if host in self.refuse:
            raise urllib.error.HTTPError(req.full_url, 401, "no", {},
                                         io.BytesIO(("bad key " + TOKEN + ELEVEN + APIFY).encode()))
        if "metricool" in host:
            return Reply([{"id": 7, "label": "Invented Bakery", "instagram": "invented.bakery"}])
        return Reply({"ok": True})


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="verify ' é ")
        state = os.path.join(self.tmp.name, "state.json")
        self.patches = [mock.patch.object(bootstrap, "STATE_DIR", self.tmp.name),
                        mock.patch.object(bootstrap, "STATE_FILE", state),
                        mock.patch.object(keys, "KEYS_FILE", os.path.join(self.tmp.name, "none.env")),
                        mock.patch.object(keys, "CHECK_SECRET", os.path.join(self.tmp.name, "key-check-secret"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        keys.load(force=True)
        self.tmp.cleanup()

    def run_verify(self, env, services):
        blank = {k: "" for k in keys.KNOWN_KEYS}
        blank.update(env)
        with mock.patch.dict(os.environ, blank):
            keys.load(force=True)
            return verify_keys.verify(Transport(allow_writes=False, opener=services))


class TestVerify(Case):
    def test_only_services_with_keys_are_checked_and_every_call_is_a_read(self):
        s = Services()
        rep = self.run_verify({"APIFY_API_TOKEN": APIFY}, s)
        self.assertEqual([(r["service"], r["ok"]) for r in rep], [("Apify", True)])
        self.assertTrue(all(method == "GET" for method, _u in s.seen))
        self.assertEqual(len(s.seen), 1)

    def test_no_keys_means_nothing_is_called(self):
        s = Services()
        self.assertEqual(self.run_verify({}, s), [])
        self.assertEqual(s.seen, [])

    def test_half_a_metricool_setup_is_explained_without_calling_anything(self):
        s = Services()
        rep = self.run_verify({"METRICOOL_USER_TOKEN": TOKEN}, s)
        self.assertFalse(rep[0]["ok"])
        self.assertIn("METRICOOL_USER_ID", rep[0]["reason"])
        self.assertEqual(s.seen, [])

    def test_a_refused_key_gets_a_plain_reason_and_the_key_never_appears(self):
        rep = self.run_verify({"METRICOOL_USER_TOKEN": TOKEN, "METRICOOL_USER_ID": "42", "ELEVENLABS_API_KEY": ELEVEN},
                              Services(refuse={"app.metricool.com", "api.elevenlabs.io"}))
        by = {r["service"]: r for r in rep}
        self.assertIn("Advanced", by["Metricool"]["reason"])              # the plan requirement, in words
        self.assertIn("refused the key", by["ElevenLabs"]["reason"])
        saved = Path(bootstrap.STATE_FILE).read_text(encoding="utf-8")
        for secret in (TOKEN, ELEVEN, APIFY):
            self.assertNotIn(secret, json.dumps(rep))
            self.assertNotIn(secret, saved)

    def test_the_result_drives_the_status_screen(self):
        feature = {"id": "x", "built": True, "needs": {"keys": ["APIFY_API_TOKEN"]}}
        with mock.patch.dict(os.environ, {"APIFY_API_TOKEN": APIFY}):
            keys.load(force=True)
            self.assertEqual(status.evaluate(feature, bootstrap.load_state(), True)[0], "unverified")
        self.run_verify({"APIFY_API_TOKEN": APIFY}, Services())
        with mock.patch.dict(os.environ, {"APIFY_API_TOKEN": APIFY}):
            keys.load(force=True)
            self.assertEqual(status.evaluate(feature, bootstrap.load_state(), True)[0], "ready")
        self.run_verify({"APIFY_API_TOKEN": APIFY}, Services(refuse={"api.apify.com"}))
        with mock.patch.dict(os.environ, {"APIFY_API_TOKEN": APIFY}):
            keys.load(force=True)
            st, why, _ = status.evaluate(feature, bootstrap.load_state(), True)
        self.assertEqual(st, "blocked")
        self.assertIn("refused the key", why)

    def test_replacing_a_refused_key_starts_fresh(self):
        feature = {"id": "x", "built": True, "needs": {"keys": ["APIFY_API_TOKEN"]}}
        self.run_verify({"APIFY_API_TOKEN": APIFY}, Services(refuse={"api.apify.com"}))
        with mock.patch.dict(os.environ, {"APIFY_API_TOKEN": APIFY + "x9"}):
            keys.load(force=True)
            self.assertEqual(status.evaluate(feature, bootstrap.load_state(), True)[0], "unverified")
            self.assertEqual(verify_keys.key_state("APIFY_API_TOKEN"), "unverified")
        with mock.patch.dict(os.environ, {"APIFY_API_TOKEN": APIFY}):
            keys.load(force=True)
            self.assertEqual(verify_keys.key_state("APIFY_API_TOKEN"), "not_working")

    def test_really_using_a_key_records_it_like_a_check(self):
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": ELEVEN}):
            keys.load(force=True)
            self.assertEqual(verify_keys.key_state("ELEVENLABS_API_KEY"), "unverified")
            verify_keys.record(["ELEVENLABS_API_KEY"], True)
            self.assertEqual(verify_keys.key_state("ELEVENLABS_API_KEY"), "verified")
            verify_keys.record(["ELEVENLABS_API_KEY"], False, "ElevenLabs refused the key.")
            self.assertEqual(verify_keys.key_state("ELEVENLABS_API_KEY"), "not_working")
        self.assertNotIn(ELEVEN, Path(bootstrap.STATE_FILE).read_text(encoding="utf-8"))

    def test_removing_a_key_forgets_its_old_result(self):
        self.run_verify({"APIFY_API_TOKEN": APIFY}, Services())
        self.assertIn("APIFY_API_TOKEN", bootstrap.load_state()["verified_keys"])
        self.run_verify({}, Services())
        self.assertNotIn("APIFY_API_TOKEN", bootstrap.load_state()["verified_keys"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
