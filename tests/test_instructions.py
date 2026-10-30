"""Every command written in the instructions exists in the real program, option by option.

    python -m unittest discover -s tests -t . -v

Claude runs what the skills tell it to run. A skill that names an action or an option the program
does not have strands a person who cannot read a usage message, so this reads every
`factory.py ...` command out of the skills, the agents, CLAUDE.md, AGENTS.md and the README, and asks the
real program whether it knows each piece.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import cli          # noqa: E402

# These run before the Social Media Factory's own packages exist, so they are not in cli.VERBS.
BEFORE_SETUP = {"setup", "status", "doctor", "where", "guide"}
# Foundation's commands promise that --help only shows help (card F7), so their help must succeed.
HELP_MUST_SUCCEED = BEFORE_SETUP | {"sync-brand", "check-brand"}
COMMAND = re.compile(r"factory\.py\s+([a-z][a-z-]*)((?:[ \t]+[^\n`|]*)?)")
OPTION = re.compile(r"(?<![\w-])(--[a-z][a-z-]*)")


def _has_packages():
    try:
        import PIL              # noqa: F401
        return True
    except ImportError:
        return False


def instruction_files():
    found = glob.glob(str(ROOT / ".claude" / "skills" / "*" / "SKILL.md")) + glob.glob(str(ROOT / ".claude" / "agents" / "*.md"))
    return sorted(found) + [str(ROOT / "CLAUDE.md"), str(ROOT / "AGENTS.md"), str(ROOT / "HELP.md"), str(ROOT / "README.md")]


class TestEveryWrittenCommandIsReal(unittest.TestCase):
    def test_every_verb_in_the_instructions_exists(self):
        for path in instruction_files():
            for m in COMMAND.finditer(Path(path).read_text(encoding="utf-8")):
                self.assertIn(m.group(1), set(cli.VERBS) | set(BEFORE_SETUP),
                              "%s tells Claude to run `factory.py %s`, which does not exist" % (os.path.relpath(path, ROOT), m.group(1)))

    @unittest.skipUnless(_has_packages(), "needs the Social Media Factory's own packages (python factory.py setup)")
    def test_every_action_and_option_in_the_instructions_exists(self):
        pages, wrong, looked_at = {}, [], 0
        surroundings = dict(os.environ, PYTHONIOENCODING="utf-8")

        def help_for(*parts):
            if parts not in pages:
                done = subprocess.run([sys.executable, str(ROOT / "factory.py")] + list(parts) + ["--help"], cwd=str(ROOT),
                                      capture_output=True, text=True, encoding="utf-8", errors="replace", env=surroundings)
                pages[parts] = (done.stdout or "") + (done.stderr or "")
                if parts[0] in HELP_MUST_SUCCEED and done.returncode != 0:
                    wrong.append("`factory.py %s --help` failed (exit %d)" % (" ".join(parts), done.returncode))
            return pages[parts]

        for path in instruction_files():
            rel = os.path.relpath(path, ROOT)
            for m in COMMAND.finditer(Path(path).read_text(encoding="utf-8")):
                verb, rest = m.group(1), m.group(2) or ""
                options = OPTION.findall(rest)
                words = rest.split()
                action = words[0] if words and re.fullmatch(r"[a-z][a-z-]*", words[0]) else None
                page = help_for(verb)
                if action:
                    if not re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(action), page):
                        wrong.append("%s: `%s %s` is not an action of %s" % (rel, verb, action, verb))
                        continue
                    page += help_for(verb, action)
                for o in options:
                    looked_at += 1
                    if o != "--help" and not re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(o), page):
                        wrong.append("%s: `%s%s %s`" % (rel, verb, " " + action if action else "", o))
        self.assertGreater(looked_at, 100, "the instructions were not really read")     # a check that saw nothing is a failure
        self.assertEqual(sorted(set(wrong)), [], "the instructions name things the program does not have")


class TestAgentsFileKeepsUpWithTheSkills(unittest.TestCase):
    """Agents other than Claude (ChatGPT's Codex) do not load skills by themselves. AGENTS.md
    points them at each one, so a new skill that is missing from it is invisible to them."""

    def test_every_skill_is_listed_in_agents_md(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for skill in sorted(glob.glob(str(ROOT / ".claude" / "skills" / "*" / "SKILL.md"))):
            name = os.path.basename(os.path.dirname(skill))
            self.assertIn(".claude/skills/%s/SKILL.md" % name, text,
                          "AGENTS.md does not point other agents at the %s skill" % name)

    def test_agents_md_keeps_the_keys_rule(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Never read, print, search, copy, summarise, parse", text)
        self.assertIn("keys.env", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
