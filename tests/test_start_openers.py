"""A new person's first words reach the front door, and the front door gets them going without a menu.

    python -m unittest tests.test_start_openers -v

People do not say "start". They say "hi", "I'm new", "where do I begin". The start skill's description
is what Claude matches them against, so it has to name them. With no brand of their own yet, the start
skill goes straight to onboarding, and onboarding asks for their material (on the computer and online)
first, then opens the page without asking "page or chat?".
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = ROOT / ".claude" / "skills" / "start" / "SKILL.md"
ONBOARD = ROOT / ".claude" / "skills" / "onboard-brand" / "SKILL.md"


def _description(path):
    head = path.read_text(encoding="utf-8").split("---", 2)[1]
    return next(line for line in head.splitlines() if line.startswith("description:"))


class TestTheFrontDoorHearsNewPeople(unittest.TestCase):
    def test_the_description_names_the_ways_people_really_begin(self):
        description = _description(START)
        for words in ('"hi"', '"get started"', '"I\'m new"', '"first time here"', '"where do I begin"',
                      '"set me up"', '"I own a', "website"):
            self.assertIn(words, description)

    def test_no_brand_goes_straight_to_onboarding(self):
        skill = START.read_text(encoding="utf-8")
        self.assertIn("without asking first", skill)
        self.assertIn("then come back to what they asked for", skill)

    def test_someone_new_on_a_computer_with_a_brand_is_asked_whether_it_is_theirs(self):
        self.assertIn("Is that yours, or are we setting up a new brand?", START.read_text(encoding="utf-8"))


class TestOnboardingAsksForMaterialThenOpensThePage(unittest.TestCase):
    def setUp(self):
        skill = ONBOARD.read_text(encoding="utf-8")
        self.step0 = skill.split("## Step 0", 1)[1].split("## On the page", 1)[0]
        self.skill = skill

    def test_it_asks_for_files_and_for_things_online(self):
        for words in ("**On your computer:**", "**Online:**", "a book", "YouTube", "podcast", "interviews"):
            self.assertIn(words, self.step0)

    def test_a_book_is_their_own_file_never_a_download_from_elsewhere(self):
        self.assertIn("Never download a copy from anywhere else", self.step0)

    def test_the_page_opens_without_asking_page_or_chat(self):
        self.assertNotIn("Which do you prefer?", self.skill)
        self.assertIn("without asking which they prefer", self.step0)
        self.assertIn("Prefer to do it here in the chat? Just say so.", self.step0)

    def test_the_material_is_asked_for_before_the_page_opens(self):
        self.assertLess(self.skill.index("onboard-page --material"), self.skill.index("onboard-page --draft"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
