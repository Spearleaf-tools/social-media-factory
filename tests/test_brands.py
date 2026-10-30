"""Brand tests: a brand is always explicit, an empty brand is a normal brand, two brands never mix.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                      # noqa: E402
from smf.brands import BrandError           # noqa: E402

BAKERY = {
    "business": {"what_we_do": "A neighbourhood bakery that sells sourdough and teaches weekend baking classes.",
                 "industry": "food and drink", "regulated": "none"},
    "audience": {"who": "People within a few miles who care about good bread and want to learn to bake it."},
    "identities": [{"id": "person", "kind": "person", "display_name": "Ava Lindqvist", "role": "Head baker"},
                   {"id": "company", "kind": "company", "display_name": "Maple & Main"}],
    "voice": {"register": "Warm, plain and specific. Talks like a baker at the counter, not a brochure."},
    "visual": {"colors": {"ground": "#FBF7F0", "ink": "#2B1D14", "accent": "#C2571A"}, "wordmark": "Maple & Main"},
    "never_mention": ["Harbour Street Cafe"],
    "accounts": {"provider": "metricool", "targets": [
        {"identity": "person", "platform": "instagram", "provider_brand_id": 101, "connected": True},
        {"identity": "company", "platform": "facebook", "provider_brand_id": 102, "connected": True}]},
}
CLINIC = {
    "business": {"what_we_do": "A physiotherapy clinic that treats running injuries for amateur athletes.",
                 "industry": "health", "regulated": "health"},
    "audience": {"who": "Runners over thirty who keep getting the same injury and want to understand why."},
    "identities": [{"id": "person", "kind": "person", "display_name": "Tomas Okafor"}],
    "voice": {"register": "Calm, exact and encouraging. Explains the why before the what."},
    "visual": {"colors": {"ground": "#FFFFFF", "ink": "#10222E", "accent": "#0E7C86"}, "wordmark": "Stride Physio"},
    "accounts": {"provider": "metricool", "targets": [
        {"identity": "person", "platform": "instagram", "provider_brand_id": 555, "connected": True}]},
}


class BrandCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brands ' é ")
        self.p1 = mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client"))
        self.p2 = mock.patch.object(brands, "ROOT", self.tmp.name)
        self.p1.start()
        self.p2.start()

    def tearDown(self):
        self.p1.stop()
        self.p2.stop()
        self.tmp.cleanup()


class TestEmptyBrandIsANormalBrand(BrandCase):
    def test_new_brand_has_every_folder_a_settings_file_and_an_empty_proof_library(self):
        b = brands.create("maple-and-main", "Maple & Main Bakery")
        for bucket in brands.BUCKETS:
            self.assertTrue(os.path.isdir(b.path(*bucket.split("/"))), bucket)
        self.assertTrue(os.path.isfile(b.path("README.md")))
        self.assertIn("Maple & Main Bakery", Path(b.path("README.md")).read_text(encoding="utf-8"))
        con = sqlite3.connect(b.path("Studio", "registry.db"))
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(con.execute("SELECT count(*) FROM proof").fetchone()[0], 0)
        con.close()
        self.assertEqual(tables, {"proof", "posts_written"})

    def test_a_blank_brand_loads_but_is_flagged_as_unfinished(self):
        brands.create("maple-and-main", "Maple & Main Bakery")
        b = brands.load("maple-and-main")
        problems, warnings = brands.validate(b.data)
        self.assertEqual(problems, [])
        self.assertTrue(any("placeholders" in w for w in warnings))

    def test_with_no_accounts_linked_planning_still_has_platforms(self):
        b = brands.create("maple-and-main", "Maple & Main Bakery")
        self.assertEqual(b.platforms_for("company"), ["linkedin", "instagram", "facebook"])

    def test_creating_twice_changes_nothing(self):
        brands.create("maple-and-main", "Maple & Main Bakery")
        with self.assertRaises(BrandError):
            brands.create("maple-and-main", "Someone Else")
        self.assertEqual(brands.load("maple-and-main").name, "Maple & Main Bakery")

    def test_bad_ids_are_refused_in_plain_words(self):
        for bad in ("", "Maple Main", "../escape", "a", "UPPER"):
            with self.assertRaises(BrandError):
                brands.create(bad, "X")


class TestNoDefaultBrandEver(BrandCase):
    def test_no_brand_named_is_an_error_not_a_guess(self):
        brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)
        for nothing in (None, "", 0):
            with self.assertRaises(BrandError) as cm:
                brands.load(nothing)
            self.assertIn("maple-and-main", str(cm.exception))      # it says what DOES exist

    def test_unknown_brand_is_an_error_not_a_fallback(self):
        brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)
        with self.assertRaises(BrandError):
            brands.load("stride-physio")

    def test_a_folder_whose_settings_name_a_different_brand_is_refused(self):
        brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)
        brands.create("stride-physio", "Stride Physio", CLINIC)
        src = os.path.join(brands.CLIENT_DIR, "stride-physio", brands.MASTER)
        dst = os.path.join(brands.CLIENT_DIR, "maple-and-main", brands.MASTER)
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")   # a copy-paste accident
        with self.assertRaises(BrandError) as cm:
            brands.load("maple-and-main")
        self.assertIn("must match", str(cm.exception))


class TestTwoBrandsNeverMix(BrandCase):
    def setUp(self):
        super().setUp()
        self.bakery = brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)
        self.clinic = brands.create("stride-physio", "Stride Physio", CLINIC)

    def test_both_have_an_identity_called_person_and_they_resolve_to_different_accounts(self):
        self.assertEqual(self.bakery.target("person", "instagram")["provider_brand_id"], 101)
        self.assertEqual(self.clinic.target("person", "instagram")["provider_brand_id"], 555)

    def test_an_account_the_brand_does_not_have_blocks_instead_of_borrowing(self):
        with self.assertRaises(BrandError):
            self.clinic.target("person", "facebook")        # the bakery has facebook; the clinic must not get it
        with self.assertRaises(BrandError):
            self.clinic.target("company", "instagram")      # the clinic has no company identity at all
        with self.assertRaises(BrandError):
            self.bakery.identity("doctor")

    def test_platform_rotation_is_per_brand_per_identity(self):
        self.assertEqual(self.bakery.platforms_for("person"), ["instagram"])
        self.assertEqual(self.bakery.platforms_for("company"), ["facebook"])

    def test_state_folders_are_separate(self):
        self.assertNotEqual(self.bakery.state_dir, self.clinic.state_dir)
        self.assertTrue(self.bakery.state_dir.startswith(self.bakery.home))


class TestValidationSpeaksPlainly(BrandCase):
    def test_problems_name_the_field_in_words(self):
        data = brands.blank_master("x-brand", "X Brand")
        data["visual"]["colors"]["accent"] = "blue"
        data["identities"] = []
        data["business"]["what_we_do"] = ""
        problems, _ = brands.validate(data)
        text = " | ".join(problems)
        self.assertIn("visual.colors.accent", text)
        self.assertIn("identities", text)
        self.assertIn("business.what_we_do", text)

    def test_cross_checks(self):
        data = brands.blank_master("x-brand", "X Brand")
        brands._deep_update(data, BAKERY)
        data["accounts"]["targets"].append({"identity": "ghost", "platform": "linkedin"})
        data["never_mention"].append("x brand")
        problems, _ = brands.validate(data)
        self.assertTrue(any("ghost" in p for p in problems))
        self.assertTrue(any("never-mention" in p for p in problems))

    def test_unreadable_colours_are_a_warning_not_a_block(self):
        data = brands.blank_master("x-brand", "X Brand")
        brands._deep_update(data, BAKERY)
        data["visual"]["colors"].update({"ground": "#FFFFFF", "ink": "#DDDDDD"})
        problems, warnings = brands.validate(data)
        self.assertEqual(problems, [])
        self.assertTrue(any("hard to read" in w for w in warnings))

    def test_a_damaged_settings_file_says_so_and_changes_nothing(self):
        brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)
        path = os.path.join(brands.CLIENT_DIR, "maple-and-main", brands.MASTER)
        Path(path).write_text("{ this is not json", encoding="utf-8")
        with self.assertRaises(BrandError) as cm:
            brands.load("maple-and-main")
        self.assertIn("damaged", str(cm.exception))
        self.assertEqual(Path(path).read_text(encoding="utf-8"), "{ this is not json")


class TestSync(BrandCase):
    def setUp(self):
        super().setUp()
        self.b = brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)

    def read(self, *parts):
        return json.loads(Path(self.b.path(*parts)).read_text(encoding="utf-8"))

    def test_derives_the_settings_files_with_a_stamp(self):
        rep = brands.sync(self.b)
        self.assertEqual(len(rep["written"]), 4)
        tokens = self.read("Brand", "brand-kit", "tokens.json")
        self.assertEqual(tokens["accent"], "#C2571A")
        self.assertEqual(tokens["marigold"], "#C2571A")          # legacy slot name, same colour
        self.assertNotIn(tokens["surface"], ("#F3F4F6", ""))     # mixed from THEIR colours, not placeholder grey
        self.assertGreater(brands.contrast(tokens["ground"], tokens["muted"]), 3.0)
        self.assertEqual(self.read("Brand", "brand-kit", "brand.json")["wordmark"], "Maple & Main")
        self.assertEqual(self.read("Studio", "rules.json")["never_mention"], ["Harbour Street Cafe"])
        self.assertIn("_derived", tokens)

    def test_running_it_again_changes_nothing(self):
        brands.sync(self.b)
        rep = brands.sync(self.b)
        self.assertEqual((rep["written"], len(rep["unchanged"])), ([], 4))

    def test_a_settings_change_flows_through(self):
        brands.sync(self.b)
        self.b.data["visual"]["colors"]["accent"] = "#123456"
        rep = brands.sync(self.b)
        self.assertEqual(len(rep["written"]), 1)                 # only the colour file; the others are left alone
        self.assertEqual(self.read("Brand", "brand-kit", "tokens.json")["accent"], "#123456")

    def test_a_hand_edit_is_never_silently_overwritten(self):
        brands.sync(self.b)
        path = self.b.path("Studio", "rules.json")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["never_mention"].append("Added By Hand Ltd")
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        self.b.data["never_mention"] = ["Harbour Street Cafe", "Another One"]
        rep = brands.sync(self.b)
        self.assertEqual(len(rep["refused"]), 1)
        self.assertIn("Added By Hand Ltd", Path(path).read_text(encoding="utf-8"))
        rep = brands.sync(self.b, force=True)
        self.assertEqual(rep["refused"], [])
        self.assertNotIn("Added By Hand Ltd", Path(path).read_text(encoding="utf-8"))

    def test_sync_never_touches_evidence_or_state(self):
        proof = Path(self.b.path("Inputs", "Proof", "review.txt"))
        proof.write_text("A real review", encoding="utf-8")
        ledger = Path(self.b.path("_state", "ledger.json"))
        ledger.write_text("{}", encoding="utf-8")
        before = {p: p.stat().st_mtime_ns for p in (proof, ledger, Path(self.b.path("Studio", "registry.db")))}
        brands.sync(self.b, force=True)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})


def windows_says_no(times):
    """os.replace that is refused `times` times (as antivirus or a sync tool holding the file
    makes Windows do), then works."""
    real = os.replace
    calls = []

    def replace(src, dst):
        calls.append(dst)
        if len(calls) <= times:
            raise PermissionError(5, "Access is denied", dst)
        return real(src, dst)
    return replace, calls


class TestSafeSave(BrandCase):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.tmp.name, "saved.json")
        self.no_wait = mock.patch.object(brands.time, "sleep")
        self.no_wait.start()

    def tearDown(self):
        self.no_wait.stop()
        super().tearDown()

    def leftovers(self):
        return [n for n in os.listdir(self.tmp.name) if n.startswith(".tmp-")]

    def test_a_briefly_refused_save_waits_and_goes_through(self):
        replace, calls = windows_says_no(2)
        with mock.patch.object(brands.os, "replace", replace):
            brands._write_json_atomic(self.path, {"name": "Maple & Main"})
        self.assertEqual(len(calls), 3)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"name": "Maple & Main"})
        self.assertEqual(self.leftovers(), [])

    def test_a_save_that_stays_refused_gives_up_plainly_and_keeps_the_old_file(self):
        brands._write_json_atomic(self.path, {"version": 1})
        replace, calls = windows_says_no(1000)
        with mock.patch.object(brands.os, "replace", replace), self.assertRaises(PermissionError) as caught:
            brands._write_json_atomic(self.path, {"version": 2})
        self.assertGreater(len(calls), 1)
        self.assertIn("saved.json", str(caught.exception))
        self.assertIn("another program", str(caught.exception))
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"version": 1})
        self.assertEqual(self.leftovers(), [])

    def test_other_problems_are_not_retried(self):
        calls = []

        def replace(src, dst):
            calls.append(dst)
            raise FileNotFoundError(2, "No such file", src)
        with mock.patch.object(brands.os, "replace", replace), self.assertRaises(FileNotFoundError):
            brands.write_text_atomic(self.path, "hello\n")
        self.assertEqual(len(calls), 1)

    def test_it_tries_seven_times_over_about_three_seconds_then_stops(self):
        brands.write_text_atomic(self.path, "old\n")
        replace, calls = windows_says_no(1000)
        with mock.patch.object(brands.os, "replace", replace), \
                mock.patch.object(brands.time, "sleep") as sleep, self.assertRaises(PermissionError):
            brands.write_text_atomic(self.path, "new\n")
        self.assertEqual(len(calls), 7)
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(waits, list(brands.SAVE_WAITS))
        self.assertAlmostEqual(sum(waits), 3.05)

    def test_a_first_save_with_no_old_file_works_and_leaves_nothing_behind(self):
        folder = os.path.join(self.tmp.name, "new folder")
        brands.write_text_atomic(os.path.join(folder, "first.txt"), "hello\n")
        with open(os.path.join(folder, "first.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "hello\n")
        self.assertEqual([n for n in os.listdir(folder) if n.startswith(".tmp-")], [])

    def test_a_failed_write_or_permission_copy_keeps_the_old_file_and_leaves_nothing_behind(self):
        brands.write_text_atomic(self.path, "old\n")
        for owner, target, error in ((brands.shutil, "copymode", PermissionError(1, "Operation not permitted")),
                                     (brands.os, "fdopen", OSError(28, "No space left on device"))):
            with mock.patch.object(owner, target, side_effect=error), self.assertRaises(OSError) as caught:
                brands.write_text_atomic(self.path, "new\n")
            self.assertIs(caught.exception, error, "the real problem reaches the person, not a cleanup error")
            with open(self.path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "old\n")
            self.assertEqual(self.leftovers(), [], target)

    def test_a_disk_that_fills_up_while_writing_or_closing_keeps_the_old_file(self):
        brands.write_text_atomic(self.path, "old\n")
        real_fdopen = os.fdopen
        for when in ("write", "close"):
            error = OSError(28, "No space left on device")

            def fdopen(fd, *a, **k):
                f = real_fdopen(fd, *a, **k)

                class Half:                         # a real file that fails part-way, as a full disk does
                    def __enter__(self):
                        return self

                    def __exit__(self, *exc):
                        f.close()
                        if when == "close" and exc[0] is None:
                            raise error

                    def write(self, text):
                        f.write(text[:2])
                        if when == "write":
                            raise error
                        return f.write(text[2:])
                return Half()
            with mock.patch.object(brands.os, "fdopen", fdopen), self.assertRaises(OSError) as caught:
                brands.write_text_atomic(self.path, "new and longer\n")
            self.assertIs(caught.exception, error, when)
            with open(self.path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "old\n", when)
            self.assertEqual(self.leftovers(), [], when)

    def test_a_cleanup_that_is_also_refused_never_hides_the_real_message(self):
        brands.write_text_atomic(self.path, "old\n")
        replace, _calls = windows_says_no(1000)
        with mock.patch.object(brands.os, "replace", replace), \
                mock.patch.object(brands.os, "remove", side_effect=PermissionError(5, "Access is denied")), \
                self.assertRaises(PermissionError) as caught:
            brands.write_text_atomic(self.path, "new\n")
        self.assertIn("Could not save saved.json", str(caught.exception))
        self.assertIn("temporary file", str(caught.exception))       # and it says what was left behind
        for name in self.leftovers():
            os.remove(os.path.join(self.tmp.name, name))

    def test_an_unrelated_error_survives_a_refused_cleanup(self):
        def replace(src, dst):
            raise FileNotFoundError(2, "No such file", src)
        err = io.StringIO()
        with mock.patch.object(brands.os, "replace", replace), \
                mock.patch.object(brands.os, "remove", side_effect=PermissionError(5, "Access is denied")), \
                mock.patch.object(brands.sys, "stderr", err), self.assertRaises(FileNotFoundError):
            brands.write_text_atomic(self.path, "hello\n")
        self.assertIn("temporary file", err.getvalue())               # the leftover is mentioned too
        self.assertIn("saved.json", err.getvalue())
        for name in self.leftovers():
            os.remove(os.path.join(self.tmp.name, name))

    def test_a_note_that_cannot_be_written_never_replaces_the_real_error(self):
        error = FileNotFoundError(2, "No such file")
        broken = mock.Mock()
        broken.write.side_effect = OSError(32, "Broken pipe")
        with mock.patch.object(brands.os, "replace", side_effect=error), \
                mock.patch.object(brands.os, "remove", side_effect=PermissionError(5, "Access is denied")), \
                mock.patch.object(brands.sys, "stderr", broken), self.assertRaises(FileNotFoundError) as caught:
            brands.write_text_atomic(self.path, "hello\n")
        self.assertIs(caught.exception, error)
        for name in self.leftovers():
            os.remove(os.path.join(self.tmp.name, name))

    def test_text_can_be_saved_with_the_same_line_endings_on_every_computer(self):
        brands.write_text_atomic(self.path, "one\ntwo\n", newline="\n")
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), b"one\ntwo\n")

    def test_setup_state_the_guide_and_the_checklist_all_use_the_safe_save(self):
        from smf import bootstrap, guide
        state = os.path.join(self.tmp.name, "state.json")
        guide_file = os.path.join(self.tmp.name, "GUIDE.md")
        services_file = os.path.join(self.tmp.name, "SERVICES.md")
        b = brands.create("maple-and-main", "Maple & Main Bakery")
        from smf import checklist, services
        # (save, patches, files it writes): one refused try, then each file saves. The guide writes
        # GUIDE.md and SERVICES.md, so it makes one more call.
        for save, patches, files in (
                (lambda: bootstrap.save_state({"venv": "x"}),
                 [mock.patch.object(bootstrap, "STATE_DIR", self.tmp.name),
                  mock.patch.object(bootstrap, "STATE_FILE", state)], 1),
                (lambda: guide.main([]), [mock.patch.object(guide, "GUIDE", guide_file),
                                          mock.patch.object(services, "MARKDOWN", services_file)], 2),
                (lambda: checklist.build(b), [], 1)):
            replace, calls = windows_says_no(1)
            with mock.patch.object(brands.os, "replace", replace), mock.patch("builtins.print"):
                for p in patches:
                    p.start()
                try:
                    save()
                finally:
                    for p in patches:
                        p.stop()
            self.assertEqual(len(calls), files + 1, save)
        with open(state, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"venv": "x"})
        self.assertTrue(os.path.getsize(guide_file) > 0)
        self.assertTrue(os.path.getsize(services_file) > 0)
        self.assertTrue(os.path.isfile(b.path("accounts-checklist.md")))


class TestEverySaveWaitsForWindows(BrandCase):
    """Windows refuses a save for a moment while antivirus, OneDrive or the search indexer has the
    file open. Every save in every area swaps its finished file in with replace_patiently, so a
    brief refusal means a short wait, never a crash."""

    def setUp(self):
        super().setUp()
        self.no_wait = mock.patch.object(brands.time, "sleep")
        self.no_wait.start()
        self.src = os.path.join(self.tmp.name, ".tmp-new")
        self.dst = os.path.join(self.tmp.name, "record.json")
        Path(self.src).write_text("new", encoding="utf-8")
        Path(self.dst).write_text("old", encoding="utf-8")

    def tearDown(self):
        self.no_wait.stop()
        super().tearDown()

    def test_a_brief_refusal_waits_and_goes_through(self):
        replace, calls = windows_says_no(3)
        with mock.patch.object(brands.os, "replace", replace):
            brands.replace_patiently(self.src, self.dst)
        self.assertEqual(len(calls), 4)
        self.assertEqual(Path(self.dst).read_text(encoding="utf-8"), "new")

    def test_a_refusal_that_never_clears_raises_the_last_error_and_keeps_the_old_file(self):
        raised = []

        def replace(src, dst):
            raised.append(PermissionError(5, "Access is denied", dst))
            raise raised[-1]
        with mock.patch.object(brands.os, "replace", replace), self.assertRaises(PermissionError) as caught:
            brands.replace_patiently(self.src, self.dst)
        self.assertEqual(len(raised), len(brands.SAVE_WAITS) + 1)         # about 3 seconds, then stop
        self.assertIs(caught.exception, raised[-1])
        self.assertEqual(Path(self.dst).read_text(encoding="utf-8"), "old")
        self.assertTrue(os.path.exists(self.src))                         # the caller decides what to do with it

    def test_other_problems_are_not_retried(self):
        calls = []

        def replace(src, dst):
            calls.append(dst)
            raise FileNotFoundError(2, "No such file", src)
        with mock.patch.object(brands.os, "replace", replace), self.assertRaises(FileNotFoundError):
            brands.replace_patiently(self.src, self.dst)
        self.assertEqual(len(calls), 1)

    def test_the_posting_record_waits_too(self):
        # The crash seen on Windows: saving posting-ledger.json refused while it was being read.
        from smf.posting import ledger as L
        brand = brands.create("maple-and-main", "Maple & Main Bakery")
        led = L.Ledger(brand)
        replace, calls = windows_says_no(2)
        with mock.patch.object(brands.os, "replace", replace):
            led._update(lambda data: data["operations"].update({"k": {"state": "reserved"}}))
        self.assertEqual(len(calls), 3)
        self.assertEqual(led.get("k"), {"state": "reserved"})

    def test_no_save_swaps_a_file_in_without_waiting(self):
        # A new save must use replace_patiently. These are the only plain swaps, each on purpose.
        allowed = {
            "smf/brands.py": 1,                       # replace_patiently itself
            "smf/onboarding_page/session.py": 2,      # write_json keeps its own short retry; shutil.move files material
            "smf/studio/export.py": 1,                # renames a finished folder, not a file
            "smf/studio/render/__init__.py": 4,       # all-or-nothing picture swap with its own way back
            "smf/studio/render/engine.py": 1,         # an optional debugging copy; failure is ignored
            "smf/video/deliver.py": 2,                # os.rename: must refuse to overwrite a finished film
        }
        swap = re.compile(r"^[^#\n]*\b(?:os\.replace|os\.rename|shutil\.move)\s*\(", re.M)
        found = {}
        for path in sorted((ROOT / "smf").rglob("*.py")):
            n = len(swap.findall(path.read_text(encoding="utf-8")))
            if n:
                found[path.relative_to(ROOT).as_posix()] = n
        self.assertEqual(found, allowed, "use brands.replace_patiently for a new save")


class TestTheBrandCheckNamesPlaceholders(BrandCase):
    """Card F2: the check used to look only for TODO, only in the settings. A brand whose files still
    say "Link to add" was called ready. Now every placeholder is named, with its file, as a note."""

    def make(self, files, offers=None):
        answers = json.loads(json.dumps(BAKERY))
        answers["offers"] = offers if offers is not None else [
            {"id": "class", "name": "Saturday class", "what": "Four hours, eight people.",
             "call_to_action": "Book a class", "link": "https://example.com/classes"}]
        b = brands.create("stride-bakery", "Stride Bakery", answers)
        for name, text in files.items():
            Path(b.path("Brand", name)).write_text(text, encoding="utf-8")
        return brands.load("stride-bakery")

    def test_placeholders_in_the_brand_files_are_named_with_their_file(self):
        b = self.make({"business-profile.md": "# Offers\n\n- The book, on pre-order. Link to add.\n- The music. Link to add.\n",
                       "audience.md": "# Questions\n\n- Not collected\n",
                       "brand-voice.md": "Register: TODO\n",
                       "pillars-and-offers.md": "| Book | Readers | Pre-order (to add) |\n| Talk | All | placeholder |\n"})
        notes = brands.placeholder_notes(b)
        text = "\n".join(notes)
        for file_name in ("business-profile.md", "audience.md", "brand-voice.md", "pillars-and-offers.md"):
            self.assertIn(file_name, text)
        self.assertIn("Link to add", text)
        self.assertIn("Not collected", text)

    def test_an_offer_with_no_link_is_named(self):
        b = self.make({}, offers=[{"id": "book", "name": "The book", "what": "Pre-order.", "call_to_action": "Pre-order the book"}])
        _problems, warnings = brands.validate(b.data)
        self.assertTrue(any("The book" in w and "link" in w for w in warnings), warnings)

    def test_these_are_notes_never_problems(self):
        b = self.make({"business-profile.md": "Link to add.\n"},
                      offers=[{"id": "book", "name": "The book", "what": "Pre-order.", "call_to_action": "Pre-order"}])
        problems, _warnings = brands.validate(b.data)
        self.assertEqual(problems, [])

    def test_a_placeholder_left_in_the_settings_names_the_setting(self):
        answers = json.loads(json.dumps(BAKERY))
        answers["business"]["industry"] = "TODO"
        b = brands.create("stride-bakery", "Stride Bakery", answers)
        self.assertTrue(any("business.industry" in n for n in brands.placeholder_notes(b)))

    def test_a_clean_brand_shows_no_placeholder_notes(self):
        b = self.make({})
        self.assertEqual(brands.placeholder_notes(b), [])
        _problems, warnings = brands.validate(b.data)
        self.assertFalse(any("link" in w for w in warnings))

    def test_ordinary_words_are_not_mistaken_for_placeholders(self):
        b = self.make({"brand-voice.md": "We love ideas to add value. Customers who have not collected their loaf by noon get a call.\n"
                                         "We have several ideas to add.\n"})
        self.assertEqual(brands.placeholder_notes(b), [])

    def test_the_check_only_reads_and_never_changes_a_file(self):
        b = self.make({"business-profile.md": "Link to add.\n"})
        before = {p: p.read_bytes() for p in Path(b.home).rglob("*") if p.is_file()}
        brands.placeholder_notes(b)
        self.assertEqual(before, {p: p.read_bytes() for p in Path(b.home).rglob("*") if p.is_file()})


class TestTheBrandCommandsDoOnlyWhatTheyAreAsked(BrandCase):
    """F7: asking for help, or mistyping an option, used to update every brand on the computer."""

    def setUp(self):
        super().setUp()
        brands.create("maple-and-main", "Maple & Main Bakery", BAKERY)
        brands.create("stride-physio", "Stride Physio", CLINIC)

    def files(self, bid):
        home = Path(brands.CLIENT_DIR, bid)
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file()}

    def everything(self):
        return {bid: self.files(bid) for bid in ("maple-and-main", "stride-physio")}

    def run_cmd(self, fn, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = fn(list(args))
        return rc, out.getvalue()

    def assertNothingChanged(self, fn, *args, code):
        before = self.everything()
        rc, text = self.run_cmd(fn, *args)
        self.assertEqual(rc, code, "%s %s -> %r" % (fn.__name__, args, text))
        self.assertEqual(before, self.everything(), "%s %s changed a brand's files" % (fn.__name__, args))
        return text

    def test_asking_for_help_shows_help_and_updates_nothing(self):
        for args in (["--help"], ["-h"], ["--help", "--force"], ["maple-and-main", "--help"], ["--all", "-h"]):
            text = self.assertNothingChanged(brands.cli_sync, *args, code=0)
            self.assertIn("sync-brand --all", text)
            self.assertNotIn("already current", text)

    def test_a_mistyped_option_stops_plainly_and_updates_nothing(self):
        text = self.assertNothingChanged(brands.cli_sync, "maple-and-main", "--froce", code=2)
        self.assertIn("sync-brand doesn't know --froce. Did you mean --force?", text)
        text = self.assertNothingChanged(brands.cli_sync, "--for", code=2)       # never guessed from a beginning
        self.assertIn("doesn't know --for", text)

    def test_no_brand_named_means_no_brand_updated(self):
        text = self.assertNothingChanged(brands.cli_sync, code=2)
        self.assertIn("Which brand?", text)
        self.assertIn("maple-and-main, stride-physio", text)
        self.assertIn("--all", text)

    def test_arguments_that_contradict_each_other_stop(self):
        self.assertNothingChanged(brands.cli_sync, "maple-and-main", "--all", code=2)
        self.assertNothingChanged(brands.cli_sync, "--brand", code=2)
        self.assertNothingChanged(brands.cli_sync, "--brand", "--force", code=2)
        text = self.assertNothingChanged(brands.cli_sync, "stride-physio", "--brand", "maple-and-main", code=2)
        self.assertIn("Two different brands", text)
        self.assertNothingChanged(brands.cli_sync, "maple-and-main", "stride-physio", "--brand", "maple-and-main", code=2)

    def test_naming_a_brand_updates_that_brand_only(self):
        for args in (["maple-and-main"], ["--brand", "maple-and-main"], ["maple-and-main", "--brand", "maple-and-main"]):
            clinic = self.files("stride-physio")
            rc, text = self.run_cmd(brands.cli_sync, *args)
            self.assertEqual(rc, 0, text)
            self.assertIn("maple-and-main:", text)
            self.assertNotIn("stride-physio", text)
            self.assertEqual(clinic, self.files("stride-physio"))

    def test_several_brands_or_all_of_them_on_purpose(self):
        for args in (["maple-and-main", "stride-physio"], ["--all"]):
            rc, text = self.run_cmd(brands.cli_sync, *args)
            self.assertEqual(rc, 0, text)
            self.assertIn("maple-and-main:", text)
            self.assertIn("stride-physio:", text)

    def test_the_brand_check_reads_options_safely_too(self):
        text = self.assertNothingChanged(brands.cli_check, "--help", code=0)
        self.assertIn("check-brand <id>", text)
        self.assertIn("doesn't know --chek", self.assertNothingChanged(brands.cli_check, "--chek", code=2))
        rc, text = self.run_cmd(brands.cli_check)                     # no brand: every brand, it only reads
        self.assertIn("(maple-and-main)", text)
        self.assertIn("(stride-physio)", text)
        rc, text = self.run_cmd(brands.cli_check, "maple-and-main", "stride-physio")
        self.assertIn("(stride-physio)", text)


def _item(value, source="typed", **more):
    out = {"value": value, "source": source}
    out.update(more)
    return out


STANDS_FOR = {
    "known_for": _item("the bakery that takes two days"),
    "core_belief": _item("Bread should take two days, not two hours."),
    "contrarian": [_item("Sourdough is a process, not a flavour.", id="c-1", experience="Twelve years of night shifts.")],
    "for": [_item("slow bread", id="for-1", experience="We lost money proving it works.")],
    "against": [_item("'fresh-baked' from frozen dough", id="against-1")],
    "differentiation": [{"id": "diff-1", "others": "bake from frozen at 5am", "us": "start the dough two days ahead",
                         "source": "typed"}],
    "non_negotiables": [_item("show real hands and real ovens", id="nn-1")],
    "story": {"catalyst": _item("Every bakery in town sold the same frozen loaf."),
              "core_truth": _item("Time is the ingredient."),
              "proof": [_item("Sold out every Saturday since 2021.", id="sp-1")]},
    "home_medium": "video",
    "stage": "under_100k",
}


class TestWhatTheBrandStandsFor(BrandCase):
    """Onboarding v2, piece 1 (cards F4 and F8): the brand settings gain what the brand stands for,
    the offer ladder and the rest, all optional; a brand without them works exactly as before."""

    def make(self, **extra):
        answers = json.loads(json.dumps(BAKERY))
        answers.update(json.loads(json.dumps(extra)))
        self.made = getattr(self, "made", 0) + 1                # a fresh brand each time, in one test
        return brands.create("maple-and-main-%d" % self.made, "Maple & Main Bakery", answers)

    def test_a_brand_with_none_of_the_new_answers_is_still_valid(self):
        b = self.make()
        self.assertEqual(brands.validate(b.data)[0], [])

    def test_the_new_answers_are_accepted(self):
        b = self.make(
            positioning=STANDS_FOR,
            person={"why_started": "My gran's oven.", "stories": [{"id": "s-1", "kind": "failure", "text": "...", "source": "spoken"}]},
            myths=[_item("Sourdough is sour.", id="m-1")], mistakes=[_item("Rushing the prove.", id="k-1")],
            steps_to_result=[_item("Feed the starter.", id="st-1")],
            intended_platforms={"by_speaker": {"person": ["instagram", "linkedin"], "company": ["facebook"]}, "other": ""},
            capacity={"hours_per_week": 4, "helpers": "my partner", "posts_per_week": 3},
            vocabulary=[_item("the two-day loaf", id="v-1")],
            offers=[{"id": "starter-guide", "name": "Starter guide", "what": "One page", "rung": "free",
                     "keyword": "STARTER", "keyword_ready": False,
                     "call_to_action": "Ask for the starter guide at the counter.", "link": "https://example.com/guide"}])
        problems, _warnings = brands.validate(b.data)
        self.assertEqual(problems, [])

    def test_an_offer_call_to_action_may_not_promise_a_keyword(self):
        for words in ("Comment STARTER and I'll send it.", "DM me GUIDE for the recipe", "Reply STARTER below"):
            b = self.make(offers=[{"id": "guide", "name": "Guide", "rung": "free", "keyword": "STARTER",
                                   "keyword_ready": False, "call_to_action": words, "link": "https://example.com"}])
            problems, _ = brands.validate(b.data)
            self.assertTrue(any("comment" in p.lower() or "keyword" in p.lower() for p in problems), words)

    def test_one_offer_per_rung_and_keywords_follow_the_rule(self):
        two = [{"id": "a", "name": "A", "rung": "main", "link": "https://example.com"},
               {"id": "b", "name": "B", "rung": "main", "link": "https://example.com"}]
        self.assertTrue(any("main" in p for p in brands.validate(self.make(offers=two).data)[0]))
        for bad in ("starter", "TOO-LONG-WORD", "ABCDEFGHIJK", "FREE"):
            b = self.make(offers=[{"id": "a", "name": "A", "rung": "free", "keyword": bad, "link": "https://example.com"}])
            self.assertNotEqual(brands.validate(b.data)[0], [], bad)

    def test_intended_platforms_name_real_speakers_and_known_platforms(self):
        b = self.make(intended_platforms={"by_speaker": {"nobody": ["instagram"]}})
        self.assertTrue(any("nobody" in p for p in brands.validate(b.data)[0]))
        b = self.make(intended_platforms={"by_speaker": {"person": ["myspace"]}})
        self.assertTrue(any("myspace" in p for p in brands.validate(b.data)[0]))

    def test_a_new_brand_no_longer_gets_a_goal_nobody_chose(self):
        b = brands.create("stride-physio", "Stride Physio")
        self.assertNotIn("goal", b.data)
        notes = brands.strategy_notes(b.data)
        self.assertTrue(any("win" in n.lower() for n in notes), notes)

    def test_empty_strategy_answers_are_a_warning_and_the_brand_stays_ready(self):
        b = self.make(goal="authority")
        notes = brands.strategy_notes(b.data)
        self.assertEqual(len(notes), 1, "one grouped note, not seven")
        self.assertIn("core belief", notes[0])
        self.assertEqual(brands.validate(b.data)[0], [])
        b2 = brands.create("stride-physio", "Stride Physio", dict(json.loads(json.dumps(CLINIC)), goal="leads",
                                                                   positioning=STANDS_FOR))
        self.assertEqual(brands.strategy_notes(b2.data), [])

    def test_sync_writes_the_brand_strategy_file_from_what_it_stands_for(self):
        b = self.make(positioning=STANDS_FOR)
        rep = brands.sync(b)
        path = Path(b.path("Brand", "brand-strategy.md"))
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        for words in ("Bread should take two days", "start the dough two days ahead", "show real hands",
                      "Time is the ingredient", "Twelve years of night shifts"):
            self.assertIn(words, text)
        self.assertIn("Brand/brand-strategy.md", " ".join(rep["written"]).replace("\\", "/"))
        again = brands.sync(b)
        self.assertNotIn("Brand/brand-strategy.md", " ".join(again["written"]).replace("\\", "/"))

    def test_empty_strategy_answers_never_block_the_brand(self):
        empty = {"known_for": {"value": ""}, "core_belief": {}, "for": [{"value": "", "id": "for-1"}],
                 "differentiation": [{"id": "diff-1", "others": "", "us": ""}], "story": {"catalyst": {"value": ""}}}
        b = self.make(positioning=empty, person={"stories": [{"kind": "origin", "text": ""}]}, myths=[{"value": ""}])
        self.assertEqual(brands.validate(b.data)[0], [])
        self.assertTrue(brands.strategy_notes(b.data))

    def test_keyword_asks_are_caught_and_ordinary_next_steps_are_not(self):
        asks = ("Comment STARTER and I'll send it.", "comment starter below", "DM me GUIDE", "Reply X",
                "Send STARTER for the guide", "message us GUIDE", "Type the word BREAD to get it", "Comment 'loaf'!",
                "Message STARTER", "Message 'starter' for the guide")
        for text in asks:
            self.assertTrue(brands.asks_for_keyword(text), text)
        fine = ("Book a Saturday class", "Reserve your weekly loaf", "Ask for a feeding card at the counter",
                "Message our UK office", "Comment below", "Send us an email", "Reply to this post",
                "Book a STARTER class", "Text us to book a table", "Comment with your favourite loaf")
        for text in fine:
            self.assertFalse(brands.asks_for_keyword(text), text)

    def test_odd_shapes_give_problems_not_crashes(self):
        for extra in ({"offers": [{"id": "a", "name": "A", "keyword": ["X"]}]},
                      {"offers": [{"id": "a", "name": "A", "rung": {"x": 1}}]},
                      {"intended_platforms": {"by_speaker": ["person"]}},
                      {"intended_platforms": {"by_speaker": {"person": "instagram"}}},
                      {"intended_platforms": "instagram"}):
            b = self.make(**extra)
            problems, _ = brands.validate(b.data)
            self.assertTrue(problems, "a malformed setting must be reported: %r" % extra)

    def test_clearing_every_strategy_answer_removes_the_old_file(self):
        for cleared in ({}, None):
            b = self.make(positioning=STANDS_FOR)
            brands.sync(b)
            path = Path(b.path("Brand", "brand-strategy.md"))
            self.assertTrue(path.exists())
            if cleared is None:
                del b.data["positioning"]
            else:
                b.data["positioning"] = cleared
            brands.sync(b)
            self.assertFalse(path.exists(), "old beliefs must not linger")

    def test_a_cleared_brand_keeps_a_hand_edited_strategy_file(self):
        b = self.make(positioning=STANDS_FOR)
        brands.sync(b)
        path = Path(b.path("Brand", "brand-strategy.md"))
        path.write_text("My own strategy notes.\n", encoding="utf-8")
        del b.data["positioning"]
        rep = brands.sync(b)
        self.assertTrue(path.exists())
        self.assertTrue(rep["refused"])

    def test_a_damaged_stamp_is_treated_as_a_hand_edit(self):
        for bad in ("[]", "null", "{oops"):
            b = self.make(positioning=STANDS_FOR)
            brands.sync(b)
            path = Path(b.path("Brand", "brand-strategy.md"))
            text = path.read_text(encoding="utf-8")
            path.write_text(text[:text.rindex("<!-- smf-derived ")] + "<!-- smf-derived %s -->\n" % bad, encoding="utf-8")
            b.data["positioning"]["core_belief"]["value"] = "Changed."
            rep = brands.sync(b)
            self.assertTrue(rep["refused"], bad)
            brands.sync(b, force=True)
            self.assertIn("Changed.", path.read_text(encoding="utf-8"))
            self.assertTrue([n for n in os.listdir(path.parent) if n.startswith("brand-strategy.before-sync")])

    def test_the_stamp_survives_windows_line_endings(self):
        b = self.make(positioning=STANDS_FOR)
        brands.sync(b)
        path = Path(b.path("Brand", "brand-strategy.md"))
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))          # as git can check it out on Windows
        rep = brands.sync(b)
        self.assertEqual(rep["refused"], [])

    def test_a_hand_edited_strategy_file_is_never_silently_replaced(self):
        b = self.make(positioning=STANDS_FOR)
        brands.sync(b)
        path = Path(b.path("Brand", "brand-strategy.md"))
        path.write_text(path.read_text(encoding="utf-8") + "\nMy own note.\n", encoding="utf-8")
        b.data["positioning"]["core_belief"]["value"] = "Bread takes time."
        rep = brands.sync(b)
        self.assertIn("My own note.", path.read_text(encoding="utf-8"))
        self.assertTrue(rep["refused"])
        brands.sync(b, force=True)
        self.assertIn("Bread takes time.", path.read_text(encoding="utf-8"))

    def test_no_strategy_file_for_a_brand_without_answers(self):
        b = self.make()
        brands.sync(b)
        self.assertFalse(Path(b.path("Brand", "brand-strategy.md")).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
