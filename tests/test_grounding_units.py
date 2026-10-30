"""A number glued to its unit is still a claim, and must reach the fact check.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf.studio import grounding          # noqa: E402


def numbers(text):
    return [m.group(1) for m in grounding._NUMBER.finditer(text)]


class TestNumbersGluedToUnits(unittest.TestCase):
    def test_a_unit_does_not_hide_the_number(self):
        self.assertEqual(numbers("Proofed for 72h at 4C, shaped 5kg of dough, 3x the rise."), ["72", "4", "5", "3"])
        self.assertEqual(numbers("Rest it 45mins, then 18hrs cold."), ["45", "18"])
        self.assertEqual(numbers("A 10KG bag"), ["10"])

    def test_things_that_are_not_measurements_stay_invisible(self):
        self.assertEqual(numbers("Open at 10am. Vitamin B12. An MP3 file. Version v2."), [])

    def test_plain_numbers_and_multipliers_still_work(self):
        self.assertEqual(numbers("We taught 4,200 people and reached 5K homes, 18 hours each."), ["4,200", "5", "18"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
