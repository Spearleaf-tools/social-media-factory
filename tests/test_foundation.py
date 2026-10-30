"""Foundation tests: no network, no keys, standard library only. Run on every OS in CI.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import bootstrap, keys, status          # noqa: E402
from smf.checks import CHECKS                    # noqa: E402


class TestOldPythonSafety(unittest.TestCase):
    """factory.py and bootstrap.py may be started by whatever Python the computer already has."""

    def test_entry_files_parse_as_python_3_8(self):
        for rel in ("factory.py", "smf/bootstrap.py", "smf/__init__.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            ast.parse(src, filename=rel, feature_version=(3, 8))

    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10+ to list the standard library")
    def test_entry_files_import_nothing_outside_the_standard_library(self):
        allowed = set(sys.stdlib_module_names) | {"smf"}
        for rel in ("factory.py", "smf/bootstrap.py"):
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for n in names:
                    self.assertIn(n.split(".")[0], allowed, "%s imports %s" % (rel, n))


class TestKeys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "keys file.env")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text, encoding="utf-8"):
        with open(self.path, "w", encoding=encoding) as f:
            f.write(text)

    def test_parses_the_ways_people_actually_type_it(self):
        self.write('# comment\n\nA=one\nexport B = "two words"\nC=\'three\'\nD=\nE=has=equals\n')
        got, problems = keys.parse_env_file(self.path)
        self.assertEqual(got, {"A": "one", "B": "two words", "C": "three", "E": "has=equals"})
        self.assertEqual(problems, [])

    def test_windows_notepad_byte_order_mark(self):
        self.write("A=one\n", encoding="utf-8-sig")
        self.assertEqual(keys.parse_env_file(self.path)[0], {"A": "one"})

    def test_bad_lines_are_reported_without_echoing_their_content(self):
        self.write("just-pasted-a-secret-here\nA=ok\n")
        got, problems = keys.parse_env_file(self.path)
        self.assertEqual(got, {"A": "ok"})
        self.assertEqual(len(problems), 1)
        self.assertNotIn("secret", problems[0])

    def test_missing_file_is_fine(self):
        self.assertEqual(keys.parse_env_file(os.path.join(self.tmp.name, "nope.env")), ({}, []))

    def test_environment_beats_the_file_and_sources_are_reported(self):
        self.write("METRICOOL_USER_TOKEN=aaaaaaaa-file\nAPIFY_API_TOKEN=bbbbbbbb-file\n")
        env = {"METRICOOL_USER_TOKEN": "aaaaaaaa-env"}
        with mock.patch.object(keys, "KEYS_FILE", self.path), mock.patch.dict(os.environ, env, clear=True):
            src = keys.load(force=True)
            self.assertEqual(os.environ["METRICOOL_USER_TOKEN"], "aaaaaaaa-env")
            self.assertEqual(src["METRICOOL_USER_TOKEN"], "environment")
            self.assertEqual(src["APIFY_API_TOKEN"], "keys.env")
            self.assertTrue(keys.has("APIFY_API_TOKEN"))
            self.assertFalse(keys.has("ELEVENLABS_API_KEY"))

    def test_redact_removes_every_loaded_value(self):
        self.write("METRICOOL_USER_TOKEN=cccccccc-cccc\n")
        with mock.patch.object(keys, "KEYS_FILE", self.path), mock.patch.dict(os.environ, {}, clear=True):
            keys.load(force=True)
            out = keys.redact("HTTP 401 for token cccccccc-cccc at /v2/posts")
            self.assertNotIn("cccccccc-cccc", out)
            self.assertIn("METRICOOL_USER_TOKEN hidden", out)

    def test_doppler_is_off_unless_asked_for(self):
        self.write("A=1\n")
        with mock.patch.object(keys, "KEYS_FILE", self.path), mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(keys, "_from_doppler") as dop:
            keys.load(force=True)
            dop.assert_not_called()

    def test_every_key_the_code_reads_is_known_and_in_the_template(self):
        # A key the code reads but the template leaves out is a key nobody is told where to put,
        # and one missing from KNOWN_KEYS is invisible to "check my setup" (OPENAI_API_KEY was both).
        pattern = re.compile(r"\b[A-Z][A-Z0-9_]*?_(?:API_KEY|API_TOKEN|USER_TOKEN|USER_ID)\b")
        read = set()
        for path in (ROOT / "smf").rglob("*.py"):
            read.update(pattern.findall(path.read_text(encoding="utf-8")))
        template = (ROOT / "keys.env.example").read_text(encoding="utf-8")
        listed = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", template, re.M))
        self.assertTrue(read)
        self.assertEqual(sorted(read - listed), [], "keys the code reads but keys.env.example leaves out")
        self.assertEqual(sorted(read - set(keys.KNOWN_KEYS)), [], "keys the code reads but keys.KNOWN_KEYS leaves out")
        self.assertEqual(sorted(set(keys.KNOWN_KEYS) - set(keys.SPOKEN)), [], "known keys without a spoken name")


class TestBootstrap(unittest.TestCase):
    def test_state_round_trip_is_atomic_and_tolerates_garbage(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(bootstrap, "STATE_DIR", d), \
                    mock.patch.object(bootstrap, "STATE_FILE", os.path.join(d, "state.json")):
                self.assertEqual(bootstrap.load_state(), {})
                bootstrap.save_state({"tiers": {"core": {}}})
                self.assertEqual(bootstrap.load_state(), {"tiers": {"core": {}}})
                with open(os.path.join(d, "state.json"), "w") as f:
                    f.write("{not json")
                self.assertEqual(bootstrap.load_state(), {})
                self.assertFalse(os.path.exists(os.path.join(d, "state.json.tmp")))

    def test_short_folder_keeps_the_environment_inside_it(self):
        with mock.patch.object(bootstrap, "load_state", return_value={}), \
                mock.patch.object(bootstrap, "WINDOWS", True), \
                mock.patch.object(bootstrap, "ROOT", r"C:\Factory"):
            self.assertTrue(bootstrap.venv_dir().endswith(".venv"))

    def test_deep_windows_folder_moves_the_environment_somewhere_short(self):
        deep = "C:\\Users\\you\\OneDrive - Some Company Ltd\\Documents\\Marketing\\2026\\social-media-factory-main"
        with mock.patch.object(bootstrap, "load_state", return_value={}), \
                mock.patch.object(bootstrap, "WINDOWS", True), \
                mock.patch.object(bootstrap, "ROOT", deep), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\you\AppData\Local"}):
            v = bootstrap.venv_dir()
            self.assertIn("SocialMediaFactory", v)
            self.assertLess(len(v), 70)
            self.assertEqual(v, bootstrap.venv_dir())          # stable for the same folder

    def test_a_mac_never_moves_it(self):
        with mock.patch.object(bootstrap, "load_state", return_value={}), \
                mock.patch.object(bootstrap, "WINDOWS", False), \
                mock.patch.object(bootstrap, "ROOT", "/Users/you/" + "deep/" * 30):
            self.assertTrue(bootstrap.venv_dir().endswith(".venv"))

    def test_python_path_shape_per_system(self):
        with mock.patch.object(bootstrap, "WINDOWS", True):
            self.assertTrue(bootstrap._python_in("X").endswith(os.path.join("Scripts", "python.exe")))
        with mock.patch.object(bootstrap, "WINDOWS", False):
            self.assertTrue(bootstrap._python_in("X").endswith(os.path.join("bin", "python")))

    def test_windows_powershell_is_not_handed_powershell_7_module_folders(self):
        # Started from PowerShell 7, the module path lists 7's own folders first. Windows
        # PowerShell 5.1 then loads 7's security module, fails, and the uv install stops at once.
        from_pwsh7 = ";".join([
            r"C:\Users\you\OneDrive - Some Company\Documents\PowerShell\Modules",
            r"C:\Program Files\PowerShell\Modules",
            r"c:\program files\powershell\7\Modules",
            r"C:\Program Files\WindowsPowerShell\Modules",
            r"C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules",
            r"C:\Tools\MyModules",
        ])
        self.assertEqual(bootstrap.windows_powershell_module_path(from_pwsh7), ";".join([
            r"C:\Program Files\WindowsPowerShell\Modules",
            r"C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules",
            r"C:\Tools\MyModules",
        ]))
        self.assertIsNone(bootstrap.windows_powershell_module_path(r"C:\Program Files\PowerShell\Modules"))
        self.assertIsNone(bootstrap.windows_powershell_module_path(""))

    def test_the_uv_install_on_windows_uses_the_cleaned_module_path(self):
        seen = {}

        def fake_run(cmd, env_extra=None, what=""):
            seen["cmd"], seen["env"] = cmd, dict(env_extra or {})

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bootstrap, "STATE_DIR", d), \
                mock.patch.object(bootstrap, "WINDOWS", True), \
                mock.patch.object(bootstrap, "run", fake_run), \
                mock.patch.object(bootstrap, "find_uv", return_value="uv.exe"), \
                mock.patch.dict(os.environ, {"PSModulePath": r"C:\Program Files\PowerShell\Modules;"
                                                             r"C:\Program Files\WindowsPowerShell\Modules"}):
            bootstrap.install_uv()
        self.assertEqual(seen["cmd"][0], "powershell")
        self.assertEqual(seen["env"]["PSModulePath"], r"C:\Program Files\WindowsPowerShell\Modules")

    def test_a_module_path_with_nothing_left_is_removed_not_emptied(self):
        with mock.patch.dict(os.environ, {"PSModulePath": "x", "SMF_KEEP": "1"}), \
                mock.patch.object(bootstrap.subprocess, "Popen") as popen:
            popen.return_value.stdout.readline.return_value = b""
            popen.return_value.returncode = 0
            bootstrap.run(["x"], env_extra={"PSModulePath": None})
        env = popen.call_args.kwargs["env"]
        self.assertNotIn("PSModulePath", env)
        self.assertEqual(env["SMF_KEEP"], "1")

    def test_requirements_are_locked_and_cover_windows(self):
        for tier in bootstrap.TIERS:
            lock = (ROOT / "requirements" / (tier + ".txt")).read_text(encoding="utf-8")
            pins = [ln for ln in lock.splitlines() if ln and not ln.startswith(("#", " ", "-"))]
            self.assertTrue(pins, tier)
            for ln in pins:
                self.assertIn("==", ln, "unpinned in %s: %s" % (tier, ln))
        core = (ROOT / "requirements" / "core.txt").read_text(encoding="utf-8")
        self.assertIn("tzdata==", core)       # Windows has no timezone database of its own
        video = (ROOT / "requirements" / "video.txt").read_text(encoding="utf-8")
        self.assertIn("sys_platform == 'win32'", video)   # the lock was resolved for Windows too, not just this Mac


class TestTitleRendererSetup(unittest.TestCase):
    """The video tier brings its own Node and HyperFrames into .factory/node: checked against the
    checksum nodejs.org publishes, never the computer's own copies, never phoning home."""

    def test_this_computer_has_a_known_node_build_with_a_checksum_and_a_size(self):
        tag = bootstrap.node_platform()
        self.assertIn(tag, bootstrap.NODE_FILES)
        name, sha, mb = bootstrap.NODE_FILES[tag]
        self.assertIn(bootstrap.NODE_VERSION, name)
        self.assertEqual(len(sha), 64)
        self.assertGreater(mb, 0)

    def test_a_download_that_fails_its_checksum_is_thrown_away_and_nothing_is_installed(self):
        said = []

        def junk(url, dest, what):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(b"not node at all")

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bootstrap, "STATE_DIR", d), \
                mock.patch.object(bootstrap, "STATE_FILE", os.path.join(d, "state.json")), \
                mock.patch.object(bootstrap, "_download", junk), \
                mock.patch.object(bootstrap, "say", said.append):
            with self.assertRaises(bootstrap.StepFailed) as e:
                bootstrap.ensure_node()
            self.assertIn("checksum", str(e.exception))
            self.assertFalse(os.path.exists(bootstrap.node_dir()))
            self.assertFalse(os.listdir(os.path.join(d, "tmp")))
            self.assertEqual(bootstrap.load_state(), {})
        self.assertTrue(any("MB" in s and "nodejs.org" in s for s in said))       # the size is said before it starts

    def test_hyperframes_is_installed_with_the_factorys_own_node_and_told_not_to_phone_home(self):
        seen = {}

        def fake_run(cmd, env_extra=None, what=""):
            seen["cmd"], seen["env"] = cmd, dict(env_extra or {})
            cli = bootstrap.hyperframes_cli()
            os.makedirs(os.path.dirname(cli))
            open(cli, "w").close()

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bootstrap, "STATE_DIR", d), \
                mock.patch.object(bootstrap, "STATE_FILE", os.path.join(d, "state.json")), \
                mock.patch.object(bootstrap, "run", fake_run), \
                mock.patch.object(bootstrap, "say", lambda *_: None):
            node = bootstrap.node_exe()
            os.makedirs(os.path.dirname(node))
            open(node, "w").close()
            self.assertTrue(bootstrap.ensure_hyperframes())
            self.assertEqual(seen["cmd"][0], node)
            self.assertEqual(seen["cmd"][1], bootstrap.npm_cli())
            self.assertIn("hyperframes@%s" % bootstrap.HYPERFRAMES_VERSION, seen["cmd"])
            self.assertEqual(seen["env"].get("HYPERFRAMES_NO_TELEMETRY"), "1")
            self.assertEqual(seen["env"].get("DO_NOT_TRACK"), "1")
            # npm's install scripts start "node" by name: on a computer with no Node of its own, the
            # Factory's has to be the first one found (a blank Windows computer failed exactly here)
            self.assertEqual(seen["env"]["PATH"].split(os.pathsep)[0], os.path.dirname(node))
            self.assertEqual(bootstrap.load_state()["hyperframes"]["version"], bootstrap.HYPERFRAMES_VERSION)
            self.assertEqual(bootstrap.title_programs(), (node, bootstrap.hyperframes_cli()))
            self.assertFalse(bootstrap.ensure_hyperframes())                        # already here: nothing runs twice

    def test_the_titles_check_says_how_to_set_it_up(self):
        from smf import checks
        with mock.patch.object(bootstrap, "load_state", return_value={"tiers": {"core": {}}}):
            ok, why = checks.titles()
            self.assertFalse(ok)
            self.assertIn("setup --tier video", why)
        with mock.patch.object(bootstrap, "load_state", return_value={"tiers": {"core": {}, "video": {}}}), \
                mock.patch.object(bootstrap, "title_programs", return_value=None):
            ok, why = checks.titles()
            self.assertFalse(ok)
            self.assertIn("title renderer", why)
        with mock.patch.object(bootstrap, "load_state", return_value={"tiers": {"core": {}, "video": {}}}), \
                mock.patch.object(bootstrap, "title_programs", return_value=("node", "hf")):
            self.assertEqual(checks.titles(), (True, ""))


class TestFeatureTable(unittest.TestCase):
    def setUp(self):
        self.data = status.load_features()

    def test_every_feature_is_well_formed(self):
        sections = {s["id"] for s in self.data["sections"]}
        seen = set()
        for f in self.data["features"]:
            self.assertNotIn(f["id"], seen)
            seen.add(f["id"])
            self.assertIn(f["section"], sections, f["id"])
            for field in ("name", "output", "skill"):
                self.assertTrue(f.get(field), "%s lacks %s" % (f["id"], field))
            needs = f.get("needs", {})
            for k in needs.get("keys", []) + needs.get("any_key", []):
                self.assertIn(k, keys.KNOWN_KEYS, f["id"])
            for t in needs.get("tiers", []):
                self.assertIn(t, bootstrap.TIERS, f["id"])
            for c in needs.get("checks", []):
                self.assertIn(c, CHECKS, f["id"])

    def test_every_section_has_at_least_one_feature(self):
        used = {f["section"] for f in self.data["features"]}
        for s in self.data["sections"]:
            self.assertIn(s["id"], used, s["id"])

    def test_writing_and_visuals_and_review_need_no_key(self):
        free = {"write-posts", "write-scripts", "make-visuals", "review", "export-folder", "plan-content"}
        for f in self.data["features"]:
            if f["id"] in free:
                self.assertEqual(f.get("needs", {}).get("keys", []), [], f["id"])

    def test_built_features_point_at_a_skill_that_exists(self):
        for f in self.data["features"]:
            if f.get("built"):
                self.assertTrue((ROOT / ".claude" / "skills" / f["skill"] / "SKILL.md").is_file(), f["id"])


class TestStatusStates(unittest.TestCase):
    FEATURE = {"id": "x", "built": True, "needs": {"tiers": ["core"], "keys": ["APIFY_API_TOKEN"], "brand": True}}

    def ev(self, state, have_brand, has_key, fp="fp-now"):
        with mock.patch.object(keys, "has", return_value=has_key), mock.patch.object(keys, "fingerprint", return_value=fp):
            return status.evaluate(self.FEATURE, state, have_brand)[0]

    def test_the_ladder_of_states(self):
        installed = {"tiers": {"core": {}}}
        self.assertEqual(status.evaluate({"id": "y", "built": False}, {}, True)[0], "not built yet")
        self.assertEqual(self.ev({}, True, True), "needs setup")
        self.assertEqual(self.ev(installed, True, False), "needs input")
        self.assertEqual(self.ev(installed, False, True), "needs input")
        self.assertEqual(self.ev(installed, True, True), "unverified")
        ok = dict(installed, verified_keys={"APIFY_API_TOKEN": {"ok": True, "fp": "fp-now"}})
        self.assertEqual(self.ev(ok, True, True), "ready")
        bad = dict(installed, verified_keys={"APIFY_API_TOKEN": {"ok": False, "reason": "plan has no API access", "fp": "fp-now"}})
        with mock.patch.object(keys, "has", return_value=True), mock.patch.object(keys, "fingerprint", return_value="fp-now"):
            st, why, _ = status.evaluate(self.FEATURE, bad, True)
        self.assertEqual((st, why), ("blocked", "plan has no API access"))

    def test_a_replaced_key_is_unverified_again_never_still_blocked(self):
        # Spec rev 11: a result belongs to the key that was checked, not just its name.
        installed = {"tiers": {"core": {}}}
        bad = dict(installed, verified_keys={"APIFY_API_TOKEN": {"ok": False, "reason": "refused", "fp": "old-key"}})
        self.assertEqual(self.ev(bad, True, True, fp="new-key"), "unverified")
        before_fingerprints = dict(installed, verified_keys={"APIFY_API_TOKEN": {"ok": True}})
        self.assertEqual(self.ev(before_fingerprints, True, True), "unverified")     # counted once more, then fine


    def test_a_missing_key_is_named_in_plain_words_never_shown(self):
        with mock.patch.object(keys, "has", return_value=False):
            _, why, nxt = status.evaluate(self.FEATURE, {"tiers": {"core": {}}}, True)
        self.assertIn("research (Apify)", why)
        self.assertIn("keys file", nxt)


class TestKeyFingerprints(unittest.TestCase):
    """The mark that ties a check result to one key: one-way, per computer, never the key."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.secret = os.path.join(self.tmp.name, ".factory", "key-check-secret")

    def tearDown(self):
        self.tmp.cleanup()

    def fp(self, value):
        with mock.patch.object(keys, "CHECK_SECRET", self.secret), \
                mock.patch.dict(os.environ, {"APIFY_API_TOKEN": value} if value else {}, clear=True), \
                mock.patch.object(keys, "_loaded", True):
            return keys.fingerprint("APIFY_API_TOKEN")

    def test_same_key_same_mark_new_key_new_mark_no_key_no_mark(self):
        a, again, b = self.fp("apify_api_firstkey12345"), self.fp("apify_api_firstkey12345"), self.fp("apify_api_secondkey678")
        self.assertEqual(a, again)
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 12)
        self.assertIsNone(self.fp(""))

    def test_the_mark_never_contains_the_key_and_the_secret_stays_in_factory(self):
        mark = self.fp("apify_api_firstkey12345")
        self.assertNotIn("firstkey", mark)
        self.assertTrue(os.path.isfile(self.secret))
        self.assertIn(".factory", self.secret)


class TestTheBakeryIsNotYourBrand(unittest.TestCase):
    """Card F3: the made-up bakery used to answer "does a brand exist?" with yes, so a brand-new
    person saw ready everywhere before onboarding anything of their own."""

    INSTALLED = {"tiers": {"core": {}, "video": {}}, "renderer": True}

    def run_status(self, brand_ids):
        out = io.StringIO()
        with mock.patch.object(status.brands, "list_brands", return_value=list(brand_ids)), \
                mock.patch.object(status.bootstrap, "load_state", return_value=self.INSTALLED), \
                mock.patch.object(status.bootstrap, "env_python", return_value="python"), \
                mock.patch.object(status.bootstrap, "title_programs", return_value=("node", "hf")), \
                mock.patch.object(keys, "has", return_value=False), \
                mock.patch("sys.stdout", out):
            status.main(["--json"])
        return json.loads(out.getvalue())

    def brand_features(self, report):
        needs_brand = {f["id"] for f in status.load_features()["features"]
                       if f.get("built") and f.get("needs", {}).get("brand") and not f.get("needs", {}).get("keys")}
        self.assertTrue(needs_brand, "the table should have features that need only a brand")
        return [r for r in report["features"] if r["id"] in needs_brand]

    def test_with_only_the_bakery_brand_features_wait_for_your_brand(self):
        rows = self.brand_features(self.run_status(["maple-and-main"]))
        for r in rows:
            self.assertEqual(r["state"], "needs input", r["id"])
            self.assertIn("onboard your brand", r["next"], r["id"])

    def test_with_the_bakery_and_one_real_brand_they_are_ready(self):
        rows = self.brand_features(self.run_status(["maple-and-main", "stride-physio"]))
        for r in rows:
            self.assertEqual(r["state"], "ready", r["id"])

    def test_the_bakery_still_shows_up_as_the_example(self):
        report = self.run_status(["maple-and-main"])
        self.assertIn("maple-and-main", report["brands"])
        self.assertEqual(report["example_brands"], ["maple-and-main"])
        out = io.StringIO()
        with mock.patch.object(status.brands, "list_brands", return_value=["maple-and-main"]), \
                mock.patch.object(status.bootstrap, "load_state", return_value=self.INSTALLED), \
                mock.patch.object(status.bootstrap, "env_python", return_value="python"), \
                mock.patch("sys.stdout", out):
            status.main([])
        self.assertIn("maple-and-main (the made-up example)", out.getvalue())


class TestDocsUseOnlyPlainCommands(unittest.TestCase):
    """The shell may be zsh, Git Bash or PowerShell. Anything Claude is told to type must be a plain
    command: no pipes, no &&, no $(...), no VAR=x prefixes. The first-run scripts exist precisely
    so that the docs never need a clever one-liner."""

    FORBIDDEN = [(r"&&", "&&"), (r"\|\|", "||"), (r"(?<!\|)\|(?!\|)", "a pipe"), (r"\$\(", "$( )"),
                 (r"^\s*[A-Z_]+=\S+\s+\w", "an env-var prefix"), (r"with-" + "secrets", "the old secrets wrapper"),
                 (r";\s*\w", "a second command after ;")]

    def commands(self, text):
        for m in re.finditer(r"`([^`\n]+)`", text):
            c = m.group(1).strip()
            first = c.split()[0] if c.split() else ""
            if first in ("python", "python3", "py", "PY", "sh", "powershell", "open", "notepad") \
                    or first.endswith(("python", "python.exe", "uv", "uv.exe")) or "factory.py" in c:
                yield c

    def test_no_shell_syntax_in_anything_claude_is_told_to_run(self):
        docs = list((ROOT / ".claude").rglob("*.md")) + [p for p in (ROOT / "README.md", ROOT / "GUIDE.md",
                                                                      ROOT / "CLAUDE.md", ROOT / "AGENTS.md", ROOT / "HELP.md") if p.is_file()]
        self.assertTrue(docs)
        for doc in docs:
            for c in self.commands(doc.read_text(encoding="utf-8")):
                for pattern, label in self.FORBIDDEN:
                    self.assertIsNone(re.search(pattern, c), "%s: `%s` uses %s" % (doc.name, c, label))



class TestTheTableTheGuideAndTheCommandsAgree(unittest.TestCase):
    """One table drives the menu, the status screen and the guide. These keep them honest."""

    def setUp(self):
        self.data = status.load_features()

    def test_every_built_feature_names_commands_that_exist_and_import(self):
        from smf import cli
        for f in self.data["features"]:
            if not f.get("built"):
                continue
            for verb in f.get("verbs", []):
                if verb == "setup":
                    continue                                  # handled by factory.py before the environment exists
                self.assertIn(verb, cli.VERBS, "%s names the command '%s', which is not registered" % (f["id"], verb))
                module, func, _about = cli.VERBS[verb]
                try:
                    mod = __import__(module, fromlist=[func])
                except ImportError as e:
                    self.skipTest("a package this command needs is not installed here: %s" % e)
                self.assertTrue(callable(getattr(mod, func, None)), "%s.%s" % (module, func))

    def test_every_registered_command_belongs_to_a_feature_or_is_plumbing(self):
        from smf import cli
        plumbing = {"guide"}
        named = {v for f in self.data["features"] for v in f.get("verbs", [])}
        for verb in cli.VERBS:
            if verb in plumbing:
                continue
            self.assertIn(verb, named, "the command '%s' is registered but no feature in the table mentions it" % verb)

    def test_the_guide_is_up_to_date(self):
        from smf import guide
        self.assertEqual(guide.main(["--check"]), 0, "GUIDE.md is stale: run `python factory.py guide`")

    def test_every_skill_folder_is_a_real_folder_with_a_real_file(self):
        skills = ROOT / ".claude" / "skills"
        for d in skills.iterdir():
            self.assertFalse(d.is_symlink(), "%s is a symlink; skills must be real files" % d.name)
            self.assertTrue((d / "SKILL.md").is_file(), d.name)
            head = (d / "SKILL.md").read_text(encoding="utf-8")[:400]
            self.assertIn("name: %s" % d.name, head)


class TestShellCommandsCannotShowAKey(unittest.TestCase):
    """settings.json stops Claude's file tools from opening keys.env, but a shell command went
    around it. The guard in .claude/hooks runs before every shell command and blocks the ones
    that would show a key, while still letting Claude open keys.env in the person's editor.
    These run the guard exactly as settings.json does, so a broken hook (which Claude would
    quietly skip) fails here instead."""

    BLOCKED = [
        "cat keys.env", "type keys.env", "Get-Content keys.env", "Get-Content -Raw ./keys.env",
        "python -c \"print(open('keys.env').read())\"", "grep METRICOOL keys.env",
        "cp keys.env notes.txt", "cat ./KEYS.ENV", "cat .env", "cat .env.local",
        "printenv", "env", "cd smf && env", "set", "export -p",
        "Get-ChildItem env:", "gci Env:", "dir env:",
        "echo $APIFY_API_TOKEN", "echo ${METRICOOL_USER_TOKEN}", "$env:ELEVENLABS_API_KEY",
        "python -c \"import os; print(os.environ)\"", "cat /proc/self/environ",
        "doppler secrets download --no-file",
        "open -t keys.env; cat keys.env", "notepad keys.env & type keys.env",
        "open -t keys.env | cat",
        # Oct 10: searching the whole folder (found by ChatGPT)
        "grep -r TOKEN .", "grep -rn TOKEN", "grep -R -A 3 TOKEN ./", "egrep -r 'sk_' ..",
        "rg --no-ignore TOKEN", "rg -uu TOKEN .", "git grep --no-index TOKEN", "ack TOKEN",
        "Get-ChildItem -Recurse | Select-String TOKEN", "gci -r . | sls TOKEN",
        "Get-ChildItem -Path . -Recurse | Select-String -Pattern TOKEN", "dir -s | sls TOKEN",
        "grep -r TOKEN ../social-media-factory", r"grep -r TOKEN C:\Users\Ava\social-media-factory",
        "grep -r TOKEN ~/Documents", "grep -r TOKEN $PWD", "cd smf && grep -r TOKEN ..",
        # wildcards and brace patterns that pick a keys file without spelling it
        "cat keys.e*", "cat ./k*.env", r"type .\k*.env", "Get-Content keys.*", "cat ke{ys,x}.e{nv,xt}",
        "cat .e?v", "cat *", "head -5 [k]eys.env", "findstr /s TOKEN *.*", "Select-String TOKEN -Path *",
        # the Social Media Factory's own key reader from a one-liner
        "python -c \"from smf import keys; print(keys.parse_env_file(keys.KEYS_FILE))\"",
        ".venv/bin/python -c \"import smf.keys as k; print(open(k.KEYS_FILE).read())\"",
        "py -c \"from smf import bootstrap, keys; print(keys.load())\"",
        "python - <<'EOF'\nfrom smf import keys\nprint(keys.parse_env_file(keys.KEYS_FILE))\nEOF",
        # found in ChatGPT's review of the change: a word in front, an option that takes a value,
        # quoted wildcards in a PowerShell file command, another .env.* name
        "command grep -r TOKEN .", "sudo grep -r TOKEN .", "xargs grep -r TOKEN",
        "grep -r --exclude-dir .git TOKEN", "grep -r --include *.py TOKEN",
        "Get-Content \"keys.*\"", "type '.\\k*.env'", "cat .e?v.staging", "echo 'a|b' && cat *",
        "echo \\'hello; cat *", "& 'Get-Content' 'keys.*'",
    ]
    ALLOWED = [
        "open -t keys.env", "notepad keys.env", "open -t \"keys.env\"",
        ".venv/bin/python factory.py status", ".venv\\Scripts\\python.exe factory.py status",
        "git status", "python -m venv .venv", "ls .venv", "set -e", "echo hello",
        "grep -rn TODO smf", "cat keys.env.example", "sed -n 1,5p .env.example",
        "rg hook smf tests", "rg TOKEN .", "grep -rn foo smf tests", "grep -r --exclude='*env*' TOKEN .",
        "git grep TOKEN", "ls *.md", "cat README.md", "grep foo README.md", "grep -c TODO smf/*.py",
        "python -m unittest tests.test_foundation", "Get-ChildItem -Recurse smf | Select-String hook",
        r"findstr /s hook smf\*.py", "python -c \"print(1)\"", "git add smf/brands.py",
        "rg '.*' smf", "python -c \"print(2 * 3)\"", "grep -rn 'a*b' smf tests", "echo 'done *'",
        "grep -r --exclude-dir .git TOKEN smf", "rg '.*' smf | cat", "python -c \"x = 2 * 3; print(x)\"",
        'python -c "print(\\"*\\")"',
    ]

    def test_a_wildcard_that_fits_a_keys_file_really_in_the_folder_is_blocked(self):
        project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        Path(project, ".env.qa").write_text("X=1\n", encoding="utf-8")
        self.assertEqual(self.run_guard("cat .e?v.qa", project=project).returncode, 2)
        self.assertEqual(self.run_guard("cat .e?v.qa", project=ROOT).returncode, 0)   # no such file there

    @staticmethod
    def find_sh():
        # Claude runs hooks in Git Bash on Windows, whose sh is usually not on the PATH.
        found = shutil.which("sh")
        git = shutil.which("git")
        if not found and git:
            for up in (Path(git).resolve().parent.parent, Path(git).resolve().parent.parent.parent):
                candidate = up / "usr" / "bin" / "sh.exe"
                if candidate.is_file():
                    return str(candidate)
        return found

    def guard_hooks(self):
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        return [h for entry in settings.get("hooks", {}).get("PreToolUse", [])
                if set(entry["matcher"].split("|")) >= {"Bash", "PowerShell"} for h in entry["hooks"]
                if "guard-keys.sh" in h.get("command", "")]

    def setUp(self):
        hooks = self.guard_hooks()
        self.assertEqual(len(hooks), 1, "one keys guard covers both shell tools")
        self.assertIn("run-guard.sh", hooks[0]["command"])            # wired through the JSON answer
        self.command = 'bash "%s"' % (ROOT / ".claude" / "hooks" / "guard-keys.sh").as_posix()   # the guard itself
        self.sh = self.find_sh()
        needs_shell = self._testMethodName.startswith(("test_commands", "test_everyday", "test_a_wildcard"))
        if needs_shell and not (self.sh and shutil.which("bash", path=os.path.dirname(self.sh) + os.pathsep
                                                          + os.environ.get("PATH", ""))):
            self.skipTest("no sh and bash on this computer (Windows without Git)")

    def run_guard(self, command, project=ROOT, tool="Bash"):
        request = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                              "tool_input": {"command": command, "description": "x"}})
        # Git Bash puts its own tools (tr, sed, grep) first on the PATH; do the same here.
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project),
                   PATH=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))
        # The guard always comes from this repository, whichever project folder it looks at.
        command = self.command.replace("$CLAUDE_PROJECT_DIR/.claude", (ROOT / ".claude").as_posix())
        return subprocess.run([self.sh, "-c", command], input=request, env=env,
                              capture_output=True, text=True, timeout=30)

    def test_commands_that_would_show_a_key_are_blocked(self):
        for command in self.BLOCKED:
            for tool in ("Bash", "PowerShell"):
                r = self.run_guard(command, tool=tool)
                self.assertEqual(r.returncode, 2, "%s let through: %s" % (tool, command))
                self.assertIn("factory.py status", r.stderr)

    def test_everyday_commands_and_opening_the_editor_still_work(self):
        for command in self.ALLOWED:
            r = self.run_guard(command)
            self.assertEqual(r.returncode, 0, "wrongly blocked: %s (%s)" % (command, r.stderr))

    def test_the_guard_keeps_plain_line_endings(self):
        # Git on Windows can check a script out with CRLF endings, which bash cannot run, and a
        # hook that cannot run lets the command through.
        for script in (ROOT / ".claude" / "hooks").glob("*.sh"):
            self.assertNotIn(b"\r", script.read_bytes(), script.name)
        for rule in (".claude/hooks/*.sh text eol=lf",):
            self.assertIn(rule, (ROOT / ".gitattributes").read_text(encoding="utf-8"))

    def test_the_old_file_tool_block_is_still_there(self):
        deny = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
        for rule in ("Read(./keys.env)", "Edit(./keys.env)", "Read(./.env)"):
            self.assertIn(rule, deny)


class TestAKeyInTheOutputIsNoticed(unittest.TestCase):
    """guard-output.sh, the second line: after a command runs, a key that shows up in what it
    returned is noticed, named by its line (never its value), and the AI is told to stop.
    Made-up keys in a made-up folder; the real keys.env is never touched."""

    FAKE = "apify_api_TESTONLYnotarealkey0123456789AB"
    FAKE2 = "sk_TESTONLY_elevenlabs_0123456789abcdefXYZ"
    KNOWN = ("APIFY_API_TOKEN", "ELEVENLABS_API_KEY", "METRICOOL_USER_TOKEN", "METRICOOL_USER_ID")

    def setUp(self):
        self.sh = TestShellCommandsCannotShowAKey.find_sh()
        if not (self.sh and shutil.which("bash", path=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))):
            self.skipTest("no sh and bash on this computer (Windows without Git)")
        self.project = tempfile.mkdtemp(prefix="keys ' é ")
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        Path(self.project, "keys.env").write_text(
            "﻿# made-up keys for a test\nexport APIFY_API_TOKEN=\"%s\"\r\nELEVENLABS_API_KEY = %s  \n"
            "METRICOOL_USER_ID=1234567\nEMPTY=\n" % (self.FAKE, self.FAKE2), encoding="utf-8")
        Path(self.project, ".env.example").write_text("APIFY_API_TOKEN=apify_api_EXAMPLEONLYexample0000\n",
                                                      encoding="utf-8")
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        hooks = [h for entry in settings["hooks"].get("PostToolUse", []) for h in entry["hooks"]
                 if "guard-output.sh" in h.get("command", "")]
        self.assertEqual(len(hooks), 1, "the output tripwire is wired into settings.json once")
        self.assertIn("run-guard.sh", hooks[0]["command"])            # wired through the JSON answer
        self.command = 'bash "%s"' % (ROOT / ".claude" / "hooks" / "guard-output.sh").as_posix()   # the guard itself

    def after(self, output, environment=None):
        request = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                              "tool_input": {"command": "some command"},
                              "tool_response": {"stdout": output, "stderr": "", "interrupted": False}})
        env = {k: v for k, v in os.environ.items() if k not in self.KNOWN}
        env.update(environment or {})
        env.update(CLAUDE_PROJECT_DIR=self.project,
                   PATH=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))
        # The hook lives in this repository; the keys it reads live in the made-up project.
        command = self.command.replace("$CLAUDE_PROJECT_DIR/.claude", (ROOT / ".claude").as_posix())
        return subprocess.run([self.sh, "-c", command], input=request, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_a_key_in_the_output_is_named_by_its_line_and_never_repeated(self):
        for output, service in (("token is %s ok" % self.FAKE, "Apify"), ("x" + self.FAKE2, "ElevenLabs")):
            r = self.after(output)
            self.assertEqual(r.returncode, 2, output)
            self.assertIn(service, r.stderr)
            self.assertIn("Replace a key", r.stderr)
            for value in (self.FAKE, self.FAKE2):
                self.assertNotIn(value, r.stderr + r.stdout, "the warning must never hold the key")

    def test_ordinary_output_passes_silently(self):
        for output in ("All 12 tests passed.", "account 1234567", "", "apify_api_EXAMPLEONLYexample0000"):
            r = self.after(output)
            self.assertEqual((r.returncode, r.stderr), (0, ""), output)

    def test_a_key_set_in_the_environment_is_known_too(self):
        r = self.after("value: METRICOOLfromtheenvironment99",
                       environment={"METRICOOL_USER_TOKEN": "METRICOOLfromtheenvironment99"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("Metricool", r.stderr)
        self.assertNotIn("METRICOOLfromtheenvironment99", r.stderr)

    def test_a_key_with_a_quote_or_backslash_is_found_in_json_too(self):
        odd = 'Odd"Key\\with/slash99'
        Path(self.project, ".env.staging").write_text("SOME_TOKEN=%s\n" % odd, encoding="utf-8")
        r = self.after("the value is %s" % odd)          # the request is JSON: Odd\"Key\\with/slash99
        self.assertEqual(r.returncode, 2, "a .env.* file is read, and its escaped value is found")
        self.assertIn("SOME_TOKEN", r.stderr)
        self.assertNotIn("slash99", r.stderr)

    def test_long_output_with_the_key_near_the_start_or_the_end(self):
        # What the hook is given, it checks in full. What Claude cuts short before calling the
        # hook is out of its reach; that limit is written in the hook's header.
        filler = "line of ordinary output\n" * 20000
        for output in (self.FAKE + "\n" + filler, filler + self.FAKE):
            self.assertEqual(self.after(output).returncode, 2)
        self.assertEqual(self.after(filler).returncode, 0)

    def test_failed_commands_and_search_results_are_checked_too(self):
        hooks = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
        for event in ("PostToolUse", "PostToolUseFailure"):
            entries = [e for e in hooks.get(event, []) if any("guard-output.sh" in h["command"] for h in e["hooks"])]
            self.assertEqual(len(entries), 1, event)
            self.assertTrue({"Bash", "PowerShell", "Grep", "Read"} <= set(entries[0]["matcher"].split("|")), event)


class TestClaudeRunsTheGuardsOnWindowsToo(unittest.TestCase):
    """Found in a live test on Oct 10: on Windows, Claude starts project hooks through PowerShell.
    There "$CLAUDE_PROJECT_DIR" is an empty PowerShell variable, so the guard was "not found", and a
    guard's exit 2 turns into a plain failure; either way Claude went ahead. Every hook must use
    ${CLAUDE_PROJECT_DIR} (which Claude fills in itself) and answer in JSON through run-guard.sh.
    These start each hook the way Claude does: through PowerShell on Windows, through sh elsewhere."""

    FAKE = "apify_api_TESTONLYnotarealkey0123456789AB"
    BLOCKED = {"PreToolUse": {"tool_input": {"command": "cat keys.e*"}},
               "UserPromptSubmit": {"prompt": "my key is " + FAKE},
               "PostToolUse": {"tool_input": {"command": "f=ke; cat ${f}ys.env"}, "tool_response": "APIFY_API_TOKEN=" + FAKE},
               "PostToolUseFailure": {"tool_input": {"command": "x"}, "error": "failed near APIFY_API_TOKEN=" + FAKE}}

    def setUp(self):
        self.sh = TestShellCommandsCannotShowAKey.find_sh()
        if not (self.sh and shutil.which("bash", path=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))):
            self.skipTest("no sh and bash on this computer (Windows without Git)")
        self.hooks = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
        # The keys the tripwire reads come from a made-up project; the hooks come from this repository.
        self.project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        Path(self.project, "keys.env").write_text("APIFY_API_TOKEN=%s\n" % self.FAKE, encoding="utf-8")

    def commands(self):
        for event, entries in self.hooks.items():
            for entry in entries:
                for h in entry["hooks"]:
                    yield event, h["command"]

    def test_every_hook_names_the_folder_in_a_way_powershell_understands(self):
        for event, command in self.commands():
            self.assertIn("${CLAUDE_PROJECT_DIR}/.claude/hooks/run-guard.sh", command, event)
            self.assertNotIn("$CLAUDE_PROJECT_DIR/", command, "PowerShell reads this as an empty variable")

    def test_a_hook_that_cannot_start_blocks_instead_of_letting_things_through(self):
        # Needs Claude Code 2.1.295 or later; older versions ignore the setting (HELP.md says so).
        for event, entries in self.hooks.items():
            for entry in entries:
                for h in entry["hooks"]:
                    self.assertEqual(h.get("onFailure"), "block", event)

    def test_a_folder_named_like_a_keys_file_is_not_mistaken_for_one(self):
        os.mkdir(os.path.join(self.project, ".env.old"))
        command = [c for e, c in self.commands() if e == "PostToolUse"][0]
        r = self.start(command, {"tool_input": {"command": "ls"}, "tool_response": "fine"})
        self.assertEqual(r.stdout.strip(), "")

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "Windows and root can still read a file with no read permission")
    def test_a_keys_file_the_tripwire_cannot_read_stops_it_too(self):
        locked = Path(self.project, ".env.qa")
        locked.write_text("QA_TOKEN=qa_TESTONLY_madeup_value_12345\n", encoding="utf-8")
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o644)
        command = [c for e, c in self.commands() if e == "PostToolUse"][0]
        r = self.start(command, {"tool_input": {"command": "ls"}, "tool_response": "fine"})
        self.assertEqual(json.loads(r.stdout)["decision"], "block")
        self.assertIn("could not run", r.stdout)

    def start(self, command, request):
        # Claude fills in ${CLAUDE_PROJECT_DIR} before the shell sees the command.
        filled = command.replace("${CLAUDE_PROJECT_DIR}", ROOT.as_posix())
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project,
                   PATH=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))
        shell = shutil.which("powershell") if os.name == "nt" else None
        argv = [shell, "-NoProfile", "-Command", filled] if shell else [self.sh, "-c", filled]
        return subprocess.run(argv, input=json.dumps(request), env=env, cwd=str(ROOT),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_a_blocked_command_and_a_blocked_message_get_a_json_answer(self):
        for event, command in self.commands():
            if event not in self.BLOCKED:
                continue
            r = self.start(command, self.BLOCKED[event])
            answer = json.loads(r.stdout)
            decision = answer["hookSpecificOutput"]["permissionDecision"] if event == "PreToolUse" else answer["decision"]
            self.assertIn(decision, ("deny", "block"), "%s: %r" % (event, r.stdout + r.stderr))

    def test_everyday_use_gets_no_answer(self):
        for event, command in self.commands():
            request = {"prompt": "write me a post"} if event == "UserPromptSubmit" else \
                {"tool_input": {"command": "rg hook smf tests"}, "tool_response": "3 matches"}
            r = self.start(command, request)
            self.assertEqual(r.stdout.strip(), "", "%s: %r" % (event, r.stdout + r.stderr))


class TestChatGPTRunsTheSameGuards(unittest.TestCase):
    """Codex runs Claude's two keys guards through .claude/hooks/run-guard.sh. Codex treats exit 2
    as a hook that failed and runs the command anyway, so the wrapper must answer in the JSON
    Codex obeys. Run here exactly as .codex/config.toml starts it, from the Social Media Factory folder."""

    def setUp(self):
        self.sh = TestShellCommandsCannotShowAKey.find_sh()
        if not (self.sh and shutil.which("bash", path=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))):
            self.skipTest("no sh and bash on this computer (Windows without Git)")
        import tomllib
        config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.hooks = {event: [h["command"] for entry in config["hooks"][event] for h in entry["hooks"]]
                      for event in ("PreToolUse", "PostToolUse")}
        self.assertEqual({e: len(c) for e, c in self.hooks.items()}, {"PreToolUse": 1, "PostToolUse": 1})
        self.assertEqual(config["sandbox_mode"], "workspace-write")             # the old guardrails stay
        self.assertFalse(config["sandbox_workspace_write"]["network_access"])

    def run_hook(self, event, request, project=ROOT):
        env = dict(os.environ, PATH=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))
        env.pop("CLAUDE_PROJECT_DIR", None)
        if project != ROOT:
            env["CLAUDE_PROJECT_DIR"] = str(project)
        return subprocess.run([self.sh, "-c", self.hooks[event][0]], input=json.dumps(request), env=env, cwd=str(ROOT),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_a_command_that_would_show_a_key_is_denied_in_codexs_words(self):
        r = self.run_hook("PreToolUse", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                         "tool_input": {"command": "cat keys.e*"}})
        self.assertEqual(r.returncode, 0, "Codex runs the command anyway when a hook exits 2")
        answer = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual((answer["hookEventName"], answer["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("factory.py status", answer["permissionDecisionReason"])

    def test_a_message_with_backslashes_and_quotes_is_still_valid_json(self):
        r = self.run_hook("PreToolUse", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                         "tool_input": {"command": "type .\\ke?s.e*"}})
        answer = json.loads(r.stdout)["hookSpecificOutput"]            # a broken answer would let it run
        self.assertEqual(answer["permissionDecision"], "deny")
        self.assertIn("ke?s.e*", answer["permissionDecisionReason"])

    def test_a_guard_that_cannot_run_stops_the_command_instead_of_waving_it_through(self):
        env = dict(os.environ, PATH=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))
        for event, guard in (("PreToolUse", "guard-keys.sh"), ("PostToolUse", "guard-output.sh")):
            command = self.hooks[event][0].replace(guard, "guard-that-is-missing.sh")
            r = subprocess.run([self.sh, "-c", command], input=json.dumps({"tool_input": {"command": "ls"}}), env=env,
                               cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=30)
            answer = json.loads(r.stdout)
            decision = answer["hookSpecificOutput"]["permissionDecision"] if event == "PreToolUse" else answer["decision"]
            self.assertIn(decision, ("deny", "block"), event)
            self.assertIn("could not run", r.stdout)

    def test_an_everyday_command_gets_no_answer(self):
        r = self.run_hook("PreToolUse", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                         "tool_input": {"command": "rg hook smf tests"}})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_a_key_in_the_output_is_replaced_and_never_repeated(self):
        project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        fake = "apify_api_TESTONLYnotarealkey0123456789AB"
        Path(project, "keys.env").write_text("APIFY_API_TOKEN=%s\n" % fake, encoding="utf-8")
        r = self.run_hook("PostToolUse", {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                          "tool_input": {"command": "f=ke; cat ${f}ys.env"},
                                          "tool_response": "APIFY_API_TOKEN=%s" % fake}, project=project)
        self.assertEqual(r.returncode, 0)
        answer = json.loads(r.stdout)
        self.assertEqual(answer["decision"], "block")
        self.assertIn("Apify", answer["reason"])
        self.assertNotIn(fake, r.stdout + r.stderr)


class TestAMessageHoldingAKeyIsNeverSent(unittest.TestCase):
    """A key pasted into the chat by mistake has already left the computer, and the only fix is
    replacing it at the service. The check in .claude/hooks/guard-prompt.sh runs on every
    message before it is sent and holds back one that looks like it carries a key. These run it
    exactly as settings.json does. Every key below is made up, and split in two so that nothing
    key-shaped sits in the repository."""

    HELD_BACK = [
        "here is my key apify_" "api_AbCdEf1234567890abcdEFGH12",
        "sk_" "3f9a2b7c1d4e5f60718293a4b5c6d7e8f9012345abcdef01",
        "APIFY_API_TOKEN=apify_" "api_xyz12345678",
        "METRICOOL_USER_TOKEN = Q7x9Lm2Pz4Kw8Rt6Yv1Bn3Cd5Fg7Hj9",  # gitleaks:allow (a made-up value the test needs)
        "my password: Fluffy2024!",
        "use this one Q7x9Lm2Pz4Kw8Rt6Yv1Bn3Cd5Fg7Hj9Kp0 for metricool",
        "ghp_" "abcdefghijklmnopqrstuvwxyz0123456789",
        "line one\nELEVENLABS_API_KEY=abcdef0123456789abcdef\nline three",  # gitleaks:allow (a made-up value the test needs)
    ]
    SENT = [
        "open my keys file", "the password is in Bitwarden", "which keys do I have set up?",
        "commit 5877486 and 66c1ff6e3b2a9d8c7f6e5d4c3b2a1908f7e6d5c4 merged",
        "see https://claude.ai/artifact/Ex4mpleArt1factL1nk00A",
        "run check-brand on maple-and-main", "id 550e8400-e29b-41d4-a716-446655440000",
        "the background colour is #FBF7F0",
    ]

    def setUp(self):
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        hooks = [h for entry in settings.get("hooks", {}).get("UserPromptSubmit", []) for h in entry["hooks"]
                 if "guard-prompt.sh" in h.get("command", "")]
        self.assertEqual(len(hooks), 1, "one message check")
        self.assertIn("run-guard.sh", hooks[0]["command"])            # wired through the JSON answer
        self.command = 'bash "%s"' % (ROOT / ".claude" / "hooks" / "guard-prompt.sh").as_posix()   # the guard itself
        self.sh = TestShellCommandsCannotShowAKey.find_sh()
        if not (self.sh and shutil.which("bash", path=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))):
            self.skipTest("no sh and bash on this computer (Windows without Git)")

    def send(self, message):
        # The project folder's path rides along in the request; it must never trip the check.
        request = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "550e8400-e29b-41d4-a716-446655440000",
                              "transcript_path": "/Users/Ava/.claude/projects/-Users-AvaLindqvist2-Documents-social-media-factory/a.jsonl",
                              "prompt": message})
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT),
                   PATH=os.path.dirname(self.sh) + os.pathsep + os.environ.get("PATH", ""))
        return subprocess.run([self.sh, "-c", self.command], input=request, env=env,
                              capture_output=True, text=True, timeout=30)

    def test_a_message_with_a_key_is_held_back(self):
        for message in self.HELD_BACK:
            r = self.send(message)
            self.assertEqual(r.returncode, 2, "sent anyway: %r" % message)
            self.assertIn("open my keys file", r.stderr)
            self.assertNotIn(message.split()[-1], r.stderr, "the warning must not repeat the key")

    def test_everyday_messages_go_through(self):
        for message in self.SENT:
            r = self.send(message)
            self.assertEqual(r.returncode, 0, "wrongly held back: %r (%s)" % (message, r.stderr))


class TestDoctorCleansUpOnlyItsOwnScratch(unittest.TestCase):
    """The onboarding page keeps its live session and the person's answers in .factory/tmp. HELP.md
    sends a stuck person to `doctor`, so doctor must never sweep that folder, only its own."""

    def setUp(self):
        from smf import doctor
        self.doctor = doctor
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state, ignore_errors=True)
        self.tmp = os.path.join(self.state, "tmp")
        os.makedirs(os.path.join(self.tmp, "something else"))
        self.kept = [os.path.join(self.tmp, "onboarding-session.json"),
                     os.path.join(self.tmp, "onboarding-intake-20261010-0900.json"),
                     os.path.join(self.tmp, "something else", "note.txt")]
        for path in self.kept:
            with open(path, "w", encoding="utf-8") as f:
                f.write("{}")
        for patch in (mock.patch.object(bootstrap, "STATE_DIR", self.state),
                      mock.patch.object(bootstrap, "running_inside_env", return_value=True),
                      mock.patch.object(bootstrap, "load_state", return_value={"tiers": {"core": True}}),
                      mock.patch.object(doctor, "check_imports", return_value=(True, "all import")),
                      mock.patch.object(doctor, "check_timezones", return_value=(True, "fine"))):
            patch.start()
            self.addCleanup(patch.stop)

    def scratch(self):
        return os.path.join(self.tmp, "doctor's café test")

    def run_doctor(self):
        with mock.patch("sys.stdout", io.StringIO()):
            return self.doctor.main([])

    def test_the_onboarding_answers_and_other_files_survive(self):
        with mock.patch.object(self.doctor, "check_renderer", return_value=(True, "drew it")):
            self.run_doctor()
        for path in self.kept:
            self.assertTrue(os.path.exists(path), "doctor deleted %s" % os.path.relpath(path, self.state))
        self.assertFalse(os.path.exists(self.scratch()), "doctor left its own scratch folder behind")

    def test_its_scratch_is_gone_even_when_a_check_is_interrupted(self):
        with mock.patch.object(self.doctor, "check_renderer", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_doctor()
        self.assertFalse(os.path.exists(self.scratch()), "doctor left its own scratch folder behind")
        for path in self.kept:
            self.assertTrue(os.path.exists(path))



class TestAskingForHelpNeverSetsACommandOff(unittest.TestCase):
    """F7: `--help` on guide, doctor, status, setup or where used to run the command instead
    (rewrite GUIDE.md, run every check, ask the services about the keys, start installing).
    Every part that does real work is booby-trapped here, so a help request that starts it fails."""

    def run_cmd(self, fn, *args):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            rc = fn(list(args))
        return rc, out.getvalue()

    def commands(self):
        from smf import doctor, guide
        import factory
        trap = mock.Mock(side_effect=AssertionError("the command started working"))
        return [
            ("guide", guide.main, [mock.patch.object(guide, "build", trap)]),
            ("doctor", doctor.main, [mock.patch.object(bootstrap, "load_state", trap)]),
            ("status", status.main, [mock.patch.object(status, "load_features", trap),
                                     mock.patch("smf.verify_keys.verify", trap)]),
            ("setup", bootstrap.setup, [mock.patch.object(bootstrap, "log", trap),
                                        mock.patch.object(bootstrap, "find_uv", trap)]),
            ("where", lambda a: factory.main(["where"] + a), []),
        ]

    def test_help_prints_how_to_use_it_and_does_nothing_else(self):
        extra = {"guide": "--check", "doctor": "--deep", "status": "--verify", "setup": "--force", "where": "-h"}
        for verb, fn, traps in self.commands():
            for args in (["--help"], ["-h"], ["--help", extra[verb]]):
                with contextlib.ExitStack() as stack:
                    for trap in traps:
                        stack.enter_context(trap)
                    rc, text = self.run_cmd(fn, *args)
                self.assertEqual(rc, 0, "%s %s -> %r" % (verb, args, text))
                self.assertIn("python factory.py %s" % verb, text)

    def test_an_unknown_option_stops_with_a_plain_message(self):
        for verb, fn, traps in self.commands():
            with contextlib.ExitStack() as stack:
                for trap in traps:
                    stack.enter_context(trap)
                rc, text = self.run_cmd(fn, "--nonsense")
            self.assertEqual(rc, 2, verb)
            self.assertIn("%s doesn't know --nonsense." % verb, text)
            self.assertIn("python factory.py %s --help" % verb, text)

    def test_close_misspellings_get_a_suggestion_and_abbreviations_are_refused(self):
        rc, text = self.run_cmd(bootstrap.setup, "--teir", "video")
        self.assertEqual(rc, 2)
        self.assertIn("Did you mean --tier?", text)
        from smf import doctor
        with mock.patch.object(bootstrap, "load_state", mock.Mock(side_effect=AssertionError)):
            rc, text = self.run_cmd(doctor.main, "--de")
        self.assertEqual(rc, 2)

    def test_a_missing_value_or_a_stray_word_stops(self):
        rc, text = self.run_cmd(bootstrap.setup, "--tier")
        self.assertEqual(rc, 2)
        self.assertIn("--tier needs a value after it.", text)
        rc, text = self.run_cmd(status.main, "everything")
        self.assertEqual(rc, 2)
        self.assertIn("status doesn't take 'everything'.", text)

    def test_the_options_people_already_use_still_work(self):
        opts, words, rc = bootstrap.read_options(["--tier", "video", "--force"], "setup", "",
                                                 flags=("--force",), values=("--tier",))
        self.assertEqual((opts, words, rc), ({"--tier": "video", "--force": True}, [], None))
        opts, _w, rc = bootstrap.read_options(["--tier=video"], "setup", "", values=("--tier",))
        self.assertEqual((opts, rc), ({"--tier": "video"}, None))

    def test_through_the_front_door_on_a_computer_that_is_not_set_up(self):
        import factory
        with mock.patch.object(bootstrap, "env_python", return_value=None),                 mock.patch.object(bootstrap, "running_inside_env", return_value=False):
            for verb in ("where", "setup", "status", "doctor", "guide", "sync-brand", "check-brand"):
                rc, text = self.run_cmd(factory.main, *[verb, "--help"])
                self.assertEqual(rc, 0, "%s --help -> %r" % (verb, text))
                self.assertIn("python factory.py %s" % verb, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
