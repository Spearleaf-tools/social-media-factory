"""Robustness tests: a check that examined nothing never passes, a key never reaches the screen,
output survives a Windows pipe, a rebuilt environment gets its packages back, and a settings file
somebody edited by hand is never replaced behind their back.

    python -m unittest discover -s tests -t . -v

Nothing here uses the network or a real key. Every key below is a made-up string.
"""
from __future__ import annotations

import http.client
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands, keys                                              # noqa: E402
from smf.posting import accounts as A                                     # noqa: E402
from smf.posting import posting_cli                                       # noqa: E402
from smf.posting.metricool import Metricool                               # noqa: E402
from smf.posting.provider import ProviderError, Transport                 # noqa: E402
from smf.research import apify                                            # noqa: E402
from smf import bootstrap, verify_keys                                    # noqa: E402
from smf.video import common, transcribe, validate_cuts                   # noqa: E402
from smf.video.common import VideoError                                   # noqa: E402
from tests.test_brands import BAKERY, BrandCase                           # noqa: E402
from tests.test_video import RECORDING, bakery_answers, interview, when   # noqa: E402


# ============================================================================= 13: listening to clips
def said(*words, start=0.2):
    """[(start, end, word)] laid end to end, the shape the speech model hands back."""
    out, t = [], start
    for w in words:
        out.append((round(t, 2), round(t + 0.3, 2), w))
        t += 0.4
    return out


class TestACheckThatComparedNothingIsNotAPass(unittest.TestCase):
    def test_boundaries_made_only_of_numbers_do_not_score_full_marks_in_silence(self):
        clip = {"segments": [{"starts_with": "1 2 3", "ends_with": "8 9 10", "duration": 12.0}]}
        unchecked = {}
        checks = validate_cuts.judge(clip, [], 12.0, unchecked)
        self.assertNotIn(1.0, checks.values())
        self.assertEqual(sorted(unchecked), ["head", "tail"])

    def test_numbers_that_are_heard_as_written_are_compared_instead_of_thrown_away(self):
        clip = {"segments": [{"starts_with": "1 2 3", "ends_with": "8 9 10", "duration": 6.0}]}
        heard = said("1", "2", "3", "and", "so", "on", "until", "8", "9", "10")
        unchecked = {}
        self.assertEqual(validate_cuts.judge(clip, heard, 4.3, unchecked), {"head": 1.0, "tail": 1.0})
        self.assertEqual(unchecked, {})

    def test_numbers_written_another_way_are_not_a_failure_and_not_a_pass(self):
        clip = {"segments": [{"starts_with": "1 2 3", "ends_with": "never gets there", "duration": 6.0}]}
        heard = said("one", "two", "three", "and", "the", "dough", "never", "gets", "there")
        unchecked = {}
        self.assertEqual(validate_cuts.judge(clip, heard, 4.0, unchecked), {"tail": 1.0})
        self.assertEqual(list(unchecked), ["head"])
        self.assertIn("numbers", unchecked["head"])

    def test_a_boundary_with_no_quoted_words_is_named_as_not_checked(self):
        clip = {"segments": [{"starts_with": "", "ends_with": "not the clock", "duration": 3.0},
                             {"starts_with": "[she laughs]", "duration": 3.0}]}
        unchecked = {}
        checks = validate_cuts.judge(clip, said("Watch", "the", "dough", "not", "the", "clock"), 6.0, unchecked)
        self.assertEqual(checks, {})
        self.assertEqual(sorted(unchecked), ["head", "seam 1", "tail"])
        unchecked = {}
        validate_cuts.judge({"segments": []}, said("hello", "there"), 6.0, unchecked)
        self.assertEqual(sorted(unchecked), ["head", "tail"])

    def test_a_join_made_by_taking_a_voice_out_needs_no_words_but_a_hand_over_between_parts_does(self):
        heard = said("Watch", "the", "dough", "and", "then", "it", "never", "gets", "there")
        split = {"segments": [{"role": "body", "starts_with": "Watch the dough", "ends_with": "", "duration": 1.2},
                              {"role": "body", "starts_with": "", "ends_with": "never gets there", "duration": 2.4}]}
        unchecked = {}
        self.assertEqual(validate_cuts.judge(split, heard, 3.6, unchecked), {"head": 1.0, "tail": 1.0})
        self.assertEqual(unchecked, {})
        lifted = {"segments": [dict(split["segments"][0], role="hook"), split["segments"][1]]}
        validate_cuts.judge(lifted, heard, 3.6, unchecked)
        self.assertEqual(list(unchecked), ["seam 1"])

    def test_words_still_decide_it_when_there_are_words(self):
        self.assertEqual(validate_cuts.match_ratio("90 kilos", ["ninety", "kilos"]), 1.0)
        self.assertIsNone(validate_cuts.match_ratio("", ["ninety", "kilos"]))
        self.assertIsNone(validate_cuts.match_ratio("90", ["ninety", "kilos"]))
        self.assertEqual(validate_cuts.match_ratio("90", ["90", "kilos"]), 1.0)


class TestValidatingClipsByEar(BrandCase):
    """The whole check, with the listening and the file test stood in for, so no video program is
    needed: what matters here is what the verdict is made from."""

    def setUp(self):
        super().setUp()
        self.bakery = brands.create("maple-and-main", "Maple & Main Bakery", bakery_answers())
        self.t = interview()
        transcribe.write_transcript(self.bakery, RECORDING, words=self.t.words, source={"made_by": "a test"})
        self.out = common.output_dir(self.bakery, RECORDING, "rough")
        os.makedirs(self.out, exist_ok=True)
        self.p = mock.patch.object(validate_cuts, "decodes_cleanly", return_value=True)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        super().tearDown()

    def report(self, starts_with, ends_with, clip_id="A1"):
        a, b = when(self.t, "Most dense loaves are simply underproofed")[0], when(self.t, "never gets there")[1]
        name = "%s.mp4" % clip_id
        Path(self.out, name).write_bytes(b"stand-in")
        clip = {"id": clip_id, "file": name, "status": "ok", "actual_duration": round(b - a, 2), "pieces": [[a, b]],
                "segments": [{"role": "body", "starts_with": starts_with, "ends_with": ends_with,
                              "duration": round(b - a, 2)}]}
        common.write_json_atomic(os.path.join(self.out, "rough-cut-report.json"),
                                 {"schema": 1, "kind": "rough", "offset": 0.0, "clips": [clip]})
        return clip

    def hears(self, clip):
        return lambda _path: [(w["start"], w["end"], w["word"]) for w in common.words_in_clip(clip["pieces"], self.t.words)]

    def test_a_silent_clip_fails_even_when_its_quoted_words_are_all_numbers(self):
        self.report("1 2 3", "8 9 10")
        lines = []
        result = validate_cuts.validate(self.bakery, RECORDING, hear=lambda _p: [], say=lines.append)
        self.assertEqual(result["failed"], ["A1"])
        entry = result["clips"][0]
        self.assertFalse(entry["pass"])
        self.assertEqual(entry["state"], "failed")
        self.assertTrue(any("no speech" in p for p in entry["problems"]), entry["problems"])
        self.assertTrue(lines[0].startswith("FAIL"), lines)

    def test_a_clip_whose_boundaries_cannot_be_compared_is_its_own_state_and_never_a_pass(self):
        clip = self.report("", "")
        lines = []
        result = validate_cuts.validate(self.bakery, RECORDING, hear=self.hears(clip), say=lines.append)
        entry = result["clips"][0]
        self.assertFalse(entry["pass"])
        self.assertEqual(entry["state"], "could not be checked")
        self.assertEqual(sorted(entry["unchecked"]), ["head", "tail"])
        self.assertEqual(result["could_not_check"], ["A1"])
        self.assertEqual(result["failed"], ["A1"])                # `failed` still means "did not pass"
        self.assertIn("could not be checked by ear: watch this one yourself", lines[0])
        self.assertFalse(lines[0].startswith("FAIL"), lines)
        saved = json.loads(Path(self.out, "validation-report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["could_not_check"], ["A1"])

    def test_a_clip_that_is_heard_to_be_right_still_passes_and_keeps_its_old_fields(self):
        clip = self.report("Most dense loaves are simply underproofed", "the dough never gets there")
        result = validate_cuts.validate(self.bakery, RECORDING, hear=self.hears(clip))
        entry = result["clips"][0]
        self.assertTrue(entry["pass"])
        self.assertEqual(entry["state"], "passed")
        self.assertEqual((entry["checks"]["head"], entry["checks"]["tail"], entry["problems"]), (1.0, 1.0, []))
        self.assertEqual((result["failed"], result["could_not_check"], result["checked"]), ([], [], 1))

    def test_wrong_words_are_a_failure_not_an_unknown(self):
        clip = self.report("Time is an ingredient", "")
        result = validate_cuts.validate(self.bakery, RECORDING, hear=self.hears(clip))
        entry = result["clips"][0]
        self.assertEqual(entry["state"], "failed")                 # one boundary heard wrong outranks one unknown
        self.assertEqual((result["failed"], result["could_not_check"]), (["A1"], []))
        self.assertEqual(list(entry["unchecked"]), ["tail"])


# ============================================================================= 14 + 15: keys never reach the screen
# A stand-in for a key, spelled out in words and joined up here so that nothing in this file can
# be mistaken for a real one, by a person or by a secret scanner.
MADE_UP = "-".join(("mc", "invented", "stand", "in", "for", "a", "scheduling", "key"))
BROKEN = MADE_UP[:14] + "\n" + MADE_UP[14:]           # the same one, pasted with a line break in the middle


def strict_headers(req, timeout=None):
    """Stands in for the network, and checks headers with Python's OWN rule without ever
    connecting: the real complaint about a bad header quotes the whole value."""
    conn = http.client.HTTPConnection("service.invalid")
    conn.putrequest(req.get_method(), "/")
    for name, value in req.header_items():
        conn.putheader(name, value)
    raise AssertionError("the request should have been refused before it got this far")


class KeysCase(unittest.TestCase):
    """A keys file that does not exist and a bare set of surroundings, so only invented keys are loaded."""

    KEYS = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="keys ' \u00e9 ")
        self.patches = [mock.patch.object(keys, "KEYS_FILE", os.path.join(self.tmp.name, "none.txt")),
                        mock.patch.dict(os.environ, self.KEYS, clear=True)]
        for p in self.patches:
            p.start()
        keys.load(force=True)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        keys.load(force=True)
        self.tmp.cleanup()


class TestABrokenKeyIsRefusedInAFixedSentence(KeysCase):
    KEYS = {"METRICOOL_USER_TOKEN": BROKEN, "METRICOOL_USER_ID": "42"}

    def assert_safe(self, text):
        for piece in (MADE_UP, BROKEN, MADE_UP[:14], MADE_UP[14:], repr(BROKEN)):
            self.assertNotIn(piece, text)
        self.assertNotIn("Traceback", text)

    def test_pythons_own_complaint_would_have_quoted_the_key(self):
        with self.assertRaises(ValueError) as cm:
            strict_headers(mock.Mock(get_method=lambda: "GET", header_items=lambda: [("X-Mc-Auth", BROKEN)]))
        self.assertIn(MADE_UP[:14], str(cm.exception))             # this is the leak the transport must get ahead of

    def test_the_transport_refuses_it_before_any_request_is_built(self):
        transport = Transport(allow_writes=False, opener=strict_headers)
        with self.assertRaises(ProviderError) as cm:
            Metricool(transport).list_accounts()
        self.assert_safe(str(cm.exception))
        self.assertEqual(str(cm.exception), "The Metricool key on this computer has a line break or a stray "
                         "character in it. It was set outside the keys file, so set it again there as one line "
                         "with nothing extra, and try again.")
        self.assertTrue(cm.exception.definitive)                # nothing was sent, so nothing can have arrived

    def test_a_key_from_the_keys_file_gets_the_keys_file_sentence(self):
        self.assertEqual(keys.damaged("Bearer ok-ok-ok-ok"), "")
        with mock.patch.object(keys, "source", return_value="keys.env"):
            sentence = keys.damaged(BROKEN)
        self.assertEqual(sentence, "The Metricool key in your keys file has a line break or a stray character in it. "
                         "Open the keys file, paste the key again on one line, save, and try again.")
        self.assertIn("A key", keys.damaged("nobody-knows-this-one\u200b"))   # pasted with an invisible character
        self.assert_safe(sentence)

    def test_a_surprise_from_the_request_machinery_never_carries_the_key_out(self):
        def surprise(req, timeout=None):
            raise ValueError("Invalid header value %r" % BROKEN.encode("utf-8"))
        for method, allow in (("GET", False), ("POST", True)):
            with self.assertRaises(ProviderError) as cm:
                Transport(allow_writes=allow, opener=surprise).request(method, "https://service.invalid/x",
                                                                      headers={"Accept": "application/json"})
            self.assert_safe(str(cm.exception))
            self.assertIn("ValueError", str(cm.exception))
            self.assertEqual(cm.exception.definitive, method == "GET")   # a write may or may not have arrived

        def cut_off(req, timeout=None):
            raise http.client.IncompleteRead(b"half an answer")
        with self.assertRaises(ProviderError):
            Transport(opener=cut_off).request("GET", "https://service.invalid/x")


class TestThePostingCommandsNeverShowATraceback(BrandCase):
    def setUp(self):
        super().setUp()
        brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)

    def run_accounts(self, open_provider):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(A, "open_provider", open_provider), redirect_stdout(out), redirect_stderr(err):
            rc = posting_cli.cli_accounts(["--brand", "maple-and-main"])
        return rc, out.getvalue() + err.getvalue()

    def test_a_broken_key_comes_out_as_the_fixed_sentence(self):
        broken = {"METRICOOL_USER_TOKEN": BROKEN, "METRICOOL_USER_ID": "42"}
        with mock.patch.dict(os.environ, broken, clear=True), \
                mock.patch.object(keys, "KEYS_FILE", os.path.join(self.tmp.name, "none.txt")):
            keys.load(force=True)
            rc, text = self.run_accounts(lambda brand, allow_writes=False:
                                         Metricool(Transport(allow_writes=False, opener=strict_headers)))
        keys.load(force=True)
        self.assertEqual(rc, 1)
        self.assertIn("has a line break or a stray character in it", text)
        for piece in (MADE_UP[:14], MADE_UP[14:], "Traceback"):
            self.assertNotIn(piece, text)

    def test_an_account_that_now_points_somewhere_else_is_named_on_screen(self):
        """destination_changes() belongs to the sending work; this guards the one line that puts
        what it found in front of a person."""
        moved = [{"identity": "person", "platform": "instagram", "kind": "moved", "was": "somebody.else",
                  "now": "invented.bakery",
                  "note": "the instagram account for 'person' now points at invented.bakery on the scheduling "
                          "service, not at somebody.else. Nothing will be sent there until this is saved again."}]
        with mock.patch.object(A, "list_accounts", return_value=[]), \
                mock.patch.object(A, "overview", return_value=[]), \
                mock.patch.object(A, "connection_changes", return_value=[]), \
                mock.patch.object(A, "destination_changes", return_value=moved):
            _rc, text = self.run_accounts(lambda brand, allow_writes=False: object())
        self.assertIn("  Note: " + moved[0]["note"], text)

    def test_anything_unexpected_is_one_sentence_and_the_exit_code_says_it_failed(self):
        def explodes(brand, allow_writes=False):
            raise RuntimeError("secret detail %s" % MADE_UP)
        rc, text = self.run_accounts(explodes)
        self.assertEqual(rc, 1)
        self.assertIn("RuntimeError", text)
        self.assertNotIn(MADE_UP, text)
        self.assertNotIn("Traceback", text)
        self.assertEqual(len(text.strip().splitlines()), 1)


def stand_in_for_requests(post):
    """The transcription upload uses the `requests` package. This takes its place, so the test
    neither needs the package nor can reach the network."""
    return types.SimpleNamespace(post=post, RequestException=OSError)


class TestRedactionComesBeforeShortening(KeysCase):
    KEYS = {"METRICOOL_USER_TOKEN": MADE_UP, "METRICOOL_USER_ID": "42", "ELEVENLABS_API_KEY": "el-" + MADE_UP,
            "APIFY_API_TOKEN": "ap-" + MADE_UP}

    def test_a_key_echoed_across_the_cut_off_point_leaves_no_piece_behind(self):
        body = ("x" * 590 + MADE_UP + " and more").encode("utf-8")

        def refuses(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 400, "invented", {}, io.BytesIO(body))
        with self.assertRaises(ProviderError) as cm:
            Transport(opener=refuses).request("GET", "https://service.invalid/x")
        text = str(cm.exception)
        self.assertNotIn(MADE_UP[:8], text)
        self.assertLess(len(text), 760)                            # still shortened

    def test_research_hides_the_key_wherever_apify_echoes_it(self):
        """Apify's answer is read whole, scrubbed, and only then cut down to fit on screen. Swept
        across the places a key could sit, including either side of every length the code cuts at."""
        key = os.environ["APIFY_API_TOKEN"]
        for at in (0, 10, 290, 299, 310, 780, 795, 810):
            body = ("z" * at + key + " was not accepted").encode("utf-8")

            def refuses(req, timeout=None, _b=body):
                raise urllib.error.HTTPError(req.full_url, 400, "invented", {}, io.BytesIO(_b))
            client = apify.Apify(transport=apify.Transport(allow_runs=True, opener=refuses), out=lambda _t: None)
            with self.assertRaises(apify.ApifyError) as cm:
                client.run("x_search", ["rye"], max_items=5, confirm=True)
            self.assertNotIn(key[:8], str(cm.exception), at)
            self.assertNotIn(MADE_UP[:8], str(cm.exception), at)

    def test_the_transcription_service_gets_the_same_order(self):
        key = os.environ["ELEVENLABS_API_KEY"]
        answer = mock.Mock(status_code=422, text="y" * 292 + key + " was not accepted")
        audio = os.path.join(self.tmp.name, "sound.m4a")
        Path(audio).write_bytes(b"not really sound")
        with mock.patch.dict(sys.modules, {"requests": stand_in_for_requests(lambda *a, **k: answer)}):
            with self.assertRaises(VideoError) as cm:
                transcribe.send_to_elevenlabs(audio, key)
        self.assertNotIn(key[:8], str(cm.exception))
        self.assertNotIn(MADE_UP[:8], str(cm.exception))

    def test_a_broken_transcription_key_is_refused_before_anything_is_sent(self):
        audio = os.path.join(self.tmp.name, "sound.m4a")
        Path(audio).write_bytes(b"not really sound")
        def must_not_send(*_a, **_k):
            raise AssertionError("nothing should be sent")
        with mock.patch.dict(sys.modules, {"requests": stand_in_for_requests(must_not_send)}):
            with self.assertRaises(VideoError) as cm:
                transcribe.send_to_elevenlabs(audio, "el-" + BROKEN)
        self.assertIn("ElevenLabs key", str(cm.exception))
        self.assertIn("line break or a stray character", str(cm.exception))
        self.assertNotIn(MADE_UP[:14], str(cm.exception))


class TestTheOtherDoorsGetTheSameTreatment(KeysCase):
    """Research and the key check put a key in a header too."""

    KEYS = {"APIFY_API_TOKEN": "ap-" + BROKEN, "ELEVENLABS_API_KEY": "el-" + BROKEN}

    def test_research_refuses_a_broken_key_before_anything_can_start(self):
        client = apify.Apify(transport=apify.Transport(allow_runs=True, opener=strict_headers), out=lambda _t: None)
        with self.assertRaises(apify.ApifyError) as cm:
            client.run("x_search", ["rye"], max_items=5, confirm=True)
        self.assertEqual(cm.exception.kind, "not-configured")
        self.assertIn("The Apify key", str(cm.exception))
        self.assertIn("line break or a stray character", str(cm.exception))
        self.assertNotIn(MADE_UP[:14], str(cm.exception))
        self.assertEqual(client.transport.starts, 0)

    def test_a_surprise_inside_research_is_a_plain_error_without_the_key(self):
        def surprise(req, timeout=None):
            raise ValueError("Invalid header value %r" % req.get_header("Authorization"))
        client = apify.Apify(transport=apify.Transport(allow_runs=True, opener=surprise), token="ap-" + MADE_UP,
                             out=lambda _t: None)
        with self.assertRaises(apify.ApifyError) as cm:
            client.run("x_search", ["rye"], max_items=5, confirm=True)
        self.assertNotIn(MADE_UP[:8], str(cm.exception))
        self.assertIs(cm.exception.definitive, False)             # a run may have started: look before retrying

    def test_the_key_check_reports_a_broken_key_in_the_fixed_sentence(self):
        state = os.path.join(self.tmp.name, "state.json")
        with mock.patch.object(bootstrap, "STATE_DIR", self.tmp.name), mock.patch.object(bootstrap, "STATE_FILE", state):
            report = verify_keys.verify(Transport(allow_writes=False, opener=strict_headers))
            saved = Path(state).read_text(encoding="utf-8")
        by = {r["service"]: r for r in report}
        self.assertFalse(by["ElevenLabs"]["ok"])
        self.assertIn("The ElevenLabs key", by["ElevenLabs"]["reason"])
        self.assertIn("The Apify key", by["Apify"]["reason"])
        for text in (json.dumps(report), saved):
            self.assertNotIn(MADE_UP[:14], text)
            self.assertNotIn(MADE_UP[14:], text)


# ============================================================================= 16: output through a Windows pipe
BRAND_NAME = "\u67ab\u53f6\u9762\u5305\u623f \U0001F35E"          # a bakery's name in Chinese, and a loaf of bread


class TestOutputSurvivesAWindowsPipe(unittest.TestCase):
    """When a program reads the Social Media Factory's output through a pipe on Windows, Python writes it in
    the old Western code page, which has no Chinese and no emoji. The work was done, then saying
    so crashed. Forcing that code page on the child reproduces it on any computer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pipe ' \u00e9 ")
        self.kit = os.path.join(self.tmp.name, "kit")
        os.makedirs(os.path.join(self.kit, ".factory"))
        shutil.copy2(str(ROOT / "factory.py"), self.kit)
        shutil.copytree(str(ROOT / "smf"), os.path.join(self.kit, "smf"), ignore=shutil.ignore_patterns("__pycache__"))
        # This copy counts whichever Python runs the tests as its own, so the command runs in the
        # first process and nothing needs installing.
        Path(self.kit, ".factory", "state.json").write_text(json.dumps({"venv": sys.prefix}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_brand_named_in_chinese_with_an_emoji_is_created_and_reported_without_a_crash(self):
        surroundings = dict(os.environ, PYTHONIOENCODING="cp1252")
        surroundings.pop("PYTHONUTF8", None)
        done = subprocess.run([sys.executable, os.path.join(self.kit, "factory.py"), "new-brand", "--name", BRAND_NAME,
                               "--id", "maple-abroad"], cwd=self.kit, env=surroundings, capture_output=True)
        out, err = done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")
        self.assertEqual(done.returncode, 0, err[-600:])
        self.assertNotIn("Traceback", out + err)
        self.assertIn(BRAND_NAME, out)                             # and it arrives readable, not as question marks
        self.assertTrue(os.path.isfile(os.path.join(self.kit, "Client", "maple-abroad", "brand-master.json")))

    def test_the_launcher_hands_utf8_to_the_factorys_own_python(self):
        factory = importlib.import_module("factory")
        with mock.patch.object(bootstrap, "env_python", return_value="/somewhere/python"), \
                mock.patch.object(bootstrap, "running_inside_env", return_value=False), \
                mock.patch.object(factory.subprocess, "call", return_value=0) as call:
            for argv in (["new-brand", "--name", BRAND_NAME], ["status"]):
                self.assertEqual(factory.main(argv), 0)
                child = call.call_args.kwargs["env"]
                self.assertEqual((child["PYTHONIOENCODING"], child["PYTHONUTF8"]), ("utf-8", "1"))
                self.assertEqual(call.call_args.args[0][2:], argv)

    def test_setting_up_the_output_never_fails_on_a_stream_that_cannot_be_changed(self):
        with mock.patch.object(sys, "stdout", io.StringIO()), mock.patch.object(sys, "stderr", None):
            bootstrap.utf8_output()                                # a stand-in stream, or none at all: left alone


# ============================================================================= 17: markers and their environment
class TestARebuiltEnvironmentGetsItsPackagesBack(unittest.TestCase):
    """Setup remembers which groups of packages it installed, so a second run is quick. Those
    notes describe ONE environment. If that environment is rebuilt, every note about it is worth
    nothing, and believing one leaves the person with a setup that says it worked and a Social Media Factory
    that cannot start."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="setup ' \u00e9 ")
        self.venv = os.path.join(self.tmp.name, "env")
        self.py = bootstrap._python_in(self.venv)
        self.said, self.ran = [], []
        self.patches = [mock.patch.object(bootstrap, "STATE_DIR", self.tmp.name),
                        mock.patch.object(bootstrap, "STATE_FILE", os.path.join(self.tmp.name, "state.json")),
                        mock.patch.object(bootstrap, "venv_dir", lambda: self.venv),
                        mock.patch.object(bootstrap, "say", self.said.append),
                        mock.patch.object(bootstrap, "run", self.fake_run)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def fake_run(self, cmd, env_extra=None, what=""):
        self.ran.append(list(cmd))
        if "venv" in cmd:                                  # uv creating the environment
            self.make_env()
        return ""

    def make_env(self):
        """What uv leaves behind: a Python, and nothing the Social Media Factory put there before."""
        if os.path.isdir(self.venv):
            shutil.rmtree(self.venv)
        os.makedirs(os.path.dirname(self.py))
        Path(self.py).write_text("#!/bin/sh\n", encoding="utf-8")

    def marked(self, tier="core", **extra):
        """State as it looks after a successful install of one group into the CURRENT environment."""
        req = os.path.join(bootstrap.ROOT, "requirements", tier + ".txt")
        done = {"requirements_sha": bootstrap._sha(req), "python": self.py,
                "env": bootstrap.env_id(self.venv), "installed_at": "2026-01-01 09:00:00"}
        done.update(extra)
        bootstrap.save_state({"venv": self.venv, "tiers": {tier: done},
                              "renderer": "2026-01-01 09:00:00", "video_programs": "2026-01-01 09:00:00"})

    def installs(self):
        return [c for c in self.ran if "pip" in c and "install" in c]

    def test_a_rebuilt_environment_forgets_everything_that_was_in_the_old_one(self):
        self.make_env()
        self.marked()
        os.remove(self.py)                                 # the environment lost its Python
        _py, made = bootstrap.ensure_env("uv")
        self.assertTrue(made)
        state = bootstrap.load_state()
        self.assertEqual(state.get("tiers", {}), {})
        self.assertNotIn("renderer", state)
        self.assertNotIn("video_programs", state)
        self.assertIn("   The Social Media Factory's Python had to be rebuilt, so its packages are being installed again.",
                      self.said)

    def test_a_first_install_says_nothing_about_rebuilding(self):
        _py, made = bootstrap.ensure_env("uv")
        self.assertTrue(made)
        self.assertEqual([t for t in self.said if "rebuilt" in t], [])

    def test_an_environment_that_is_already_right_is_left_alone(self):
        self.make_env()
        self.marked()
        with mock.patch.object(bootstrap.subprocess, "check_output", return_value=b"3.12\n"):
            _py, made = bootstrap.ensure_env("uv")
        self.assertFalse(made)
        self.assertEqual(bootstrap.load_state()["renderer"], "2026-01-01 09:00:00")

    def test_a_note_left_over_from_another_environment_is_not_believed(self):
        self.make_env()
        self.marked(env="an-environment-that-is-gone")
        with mock.patch.dict(bootstrap.TIER_PROOF, {"core": "json"}):
            self.assertTrue(bootstrap.ensure_tier("uv", self.py, "core"))
        self.assertEqual(len(self.installs()), 1)
        self.assertEqual(bootstrap.load_state()["tiers"]["core"]["env"], bootstrap.env_id(self.venv))

    def test_a_note_whose_packages_are_not_really_there_is_not_believed(self):
        self.make_env()
        self.marked()
        with mock.patch.dict(bootstrap.TIER_PROOF, {"core": "a_package_that_was_never_installed"}), \
                mock.patch.object(bootstrap.subprocess, "call", return_value=1):
            self.assertTrue(bootstrap.ensure_tier("uv", self.py, "core"))
        self.assertEqual(len(self.installs()), 1)

    def test_a_note_that_matches_an_environment_that_really_has_the_packages_is_believed(self):
        self.make_env()
        self.marked()
        with mock.patch.dict(bootstrap.TIER_PROOF, {"core": "json"}), \
                mock.patch.object(bootstrap.subprocess, "call", return_value=0):
            self.assertFalse(bootstrap.ensure_tier("uv", self.py, "core"))
        self.assertEqual(self.installs(), [])

    def test_setup_all_the_way_through_installs_again_after_a_rebuild(self):
        """The reviewer's scenario end to end: setup says it worked, and the packages are in."""
        self.make_env()
        self.marked()
        os.remove(self.py)
        with mock.patch.object(bootstrap, "find_uv", return_value="uv"), \
                mock.patch.object(bootstrap, "ensure_keys_file", return_value=False), \
                mock.patch.dict(bootstrap.TIER_PROOF, {"core": "json"}), \
                mock.patch.object(bootstrap.subprocess, "call", return_value=0):
            self.assertEqual(bootstrap.setup([]), 0)
        self.assertEqual(len(self.installs()), 1, self.ran)          # the core packages went in again
        self.assertTrue(any("playwright" in " ".join(c) for c in self.ran))   # and so did the page renderer
        state = bootstrap.load_state()
        self.assertEqual(state["tiers"]["core"]["env"], bootstrap.env_id(self.venv))


# ============================================================================= 18: a file somebody edited
class TestSyncNeverReplacesAFileItCannotProveItWrote(BrandCase):
    """Sync derives four settings files from brand-master.json and stamps each one. The stamp is
    the ONLY thing that says the Social Media Factory wrote a file and nobody has touched it since. A file that
    cannot be read cannot show a stamp, so it is somebody's work until proved otherwise."""

    def setUp(self):
        super().setUp()
        self.b = brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)
        brands.sync(self.b)
        self.path = self.b.path("Studio", "rules.json")
        self.rel = os.path.relpath(self.path, brands.ROOT)

    def leave(self, text, encoding="utf-8"):
        Path(self.path).write_text(text, encoding=encoding)
        self.b.data["never_mention"] = ["Harbour Street Cafe", "Another One"]   # so sync wants to write
        return text

    def backups(self):
        return sorted(p.name for p in Path(self.b.path("Studio")).iterdir() if "before-sync" in p.name)

    def test_a_trailing_comma_does_not_make_the_file_fair_game(self):
        left = self.leave('{\n  "style": {},\n  "never_mention": ["Added By Hand Ltd"],\n}\n')
        rep = brands.sync(self.b)
        self.assertEqual(Path(self.path).read_text(encoding="utf-8"), left)     # byte for byte
        self.assertEqual(rep["refused"], [self.rel])
        self.assertEqual(rep["written"], [])
        self.assertEqual(rep["notes"], ["%s was left as it is (it is not valid JSON any more, so something in it "
                                        "has been mistyped): move what you want to keep into brand-master.json, or "
                                        "run sync again with --force to replace it." % self.rel])

    def test_valid_json_that_is_not_a_group_of_settings_is_left_alone_too(self):
        left = self.leave('["Added By Hand Ltd"]\n')
        rep = brands.sync(self.b)
        self.assertEqual(Path(self.path).read_text(encoding="utf-8"), left)
        self.assertEqual(rep["refused"], [self.rel])
        self.assertIn("it no longer holds a group of settings", rep["notes"][0])

    def test_a_file_with_no_stamp_at_all_is_left_alone(self):
        left = self.leave('{"style": {}, "never_mention": ["Added By Hand Ltd"]}\n')
        rep = brands.sync(self.b)
        self.assertEqual(Path(self.path).read_text(encoding="utf-8"), left)
        self.assertEqual(rep["refused"], [self.rel])
        self.assertIn("the Social Media Factory did not write it, or its stamp has been removed", rep["notes"][0])

    def test_a_file_notepad_saved_with_a_byte_order_mark_is_still_read_as_ours(self):
        """Saving a file on Windows can add an invisible mark at the front. That is not damage,
        and it must not look like a hand edit."""
        same = Path(self.path).read_text(encoding="utf-8")
        Path(self.path).write_text(same, encoding="utf-8-sig")
        rep = brands.sync(self.b)
        self.assertEqual(rep["refused"], [])
        self.assertIn(self.rel, rep["unchanged"])                     # the mark alone is not a change
        self.b.data["never_mention"] = ["Harbour Street Cafe", "Another One"]
        rep = brands.sync(self.b)
        self.assertEqual(rep["written"], [self.rel])                  # and it never blocks a real one
        self.assertEqual(rep["notes"], [])

    def test_a_hand_edit_under_a_byte_order_mark_is_still_caught(self):
        data = json.loads(Path(self.path).read_text(encoding="utf-8"))
        data["never_mention"].append("Added By Hand Ltd")
        Path(self.path).write_text(json.dumps(data), encoding="utf-8-sig")
        self.b.data["never_mention"] = ["Harbour Street Cafe", "Another One"]
        rep = brands.sync(self.b)
        self.assertEqual(rep["refused"], [self.rel])
        self.assertIn("edited by hand", rep["notes"][0])
        self.assertIn("Added By Hand Ltd", Path(self.path).read_text(encoding="utf-8-sig"))

    def test_force_replaces_it_but_keeps_what_was_there(self):
        left = self.leave('{\n  "never_mention": ["Added By Hand Ltd"],\n}\n')
        rep = brands.sync(self.b, force=True)
        self.assertEqual(rep["refused"], [])
        self.assertIn(self.rel, rep["written"])
        self.assertEqual(len(rep["kept"]), 1)
        kept = self.backups()
        self.assertEqual(len(kept), 1, kept)
        self.assertEqual(Path(self.b.path("Studio", kept[0])).read_text(encoding="utf-8"), left)
        self.assertEqual(json.loads(Path(self.path).read_text(encoding="utf-8"))["never_mention"],
                         ["Harbour Street Cafe", "Another One"])
        self.assertEqual(rep["notes"], ["%s was replaced; what was there before is kept beside it as %s."
                                        % (self.rel, kept[0])])

    def test_force_on_a_file_the_factory_wrote_keeps_no_clutter(self):
        self.b.data["never_mention"] = ["Harbour Street Cafe", "Another One"]
        rep = brands.sync(self.b, force=True)
        self.assertEqual(self.backups(), [])                          # nothing of anyone's was at risk
        self.assertEqual(rep["kept"], [])

    def test_the_sync_command_says_what_happened_and_stops_short_of_claiming_success(self):
        self.leave('{"never_mention": ["Added By Hand Ltd"],}\n')
        out = io.StringIO()
        with mock.patch.object(brands, "list_brands", return_value=["maple-and-main"]), redirect_stdout(out):
            rc = brands.cli_sync(["maple-and-main"])
        text = out.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("was left as it is (it is not valid JSON any more", text)
        self.assertIn("run sync again with --force to replace it.", text)
        self.assertNotIn("edited by hand", text)                      # the real reason, not a guess


if __name__ == "__main__":
    unittest.main(verbosity=2)
