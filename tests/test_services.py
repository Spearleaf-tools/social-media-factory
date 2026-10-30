"""The outside services list (smf/services.json): one place for prices, dated and sourced, that
SERVICES.md, the setup checklist, GUIDE.md and the setup skill all read (spec rev 11).

    python -m unittest tests.test_services -v
"""
from __future__ import annotations

import datetime
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import checklist, guide, keys, services       # noqa: E402

SPENDING = {"subscription", "plan", "credit", "free"}


class TestTheList(unittest.TestCase):
    def setUp(self):
        self.data = services.load()
        self.all = self.data["services"]

    def test_every_price_has_a_date_and_a_source(self):
        for s in self.all:
            self.assertRegex(s["checked"], r"^\d{4}-\d{2}-\d{2}$", s["id"])
            datetime.date.fromisoformat(s["checked"])
            self.assertTrue(s["source"].startswith("https://"), s["id"])
            self.assertIn(s["spending"], SPENDING, s["id"])

    def test_every_service_says_what_it_does_costs_how_to_limit_it_and_how_to_set_it_up(self):
        for s in self.all:
            for field in ("name", "short", "for", "needed_for", "cost", "limit", "signup", "remove"):
                self.assertTrue(s.get(field), "%s lacks %s" % (s["id"], field))
            self.assertTrue(s["steps"], s["id"])

    def test_every_key_the_code_knows_belongs_to_exactly_one_service(self):
        owners = {}
        for s in self.all:
            for k in s["keys"]:
                self.assertNotIn(k, owners, k)
                owners[k] = s["id"]
        self.assertEqual(sorted(owners), sorted(keys.KNOWN_KEYS))

    def test_a_reminder_is_never_called_a_limit(self):
        # Rev 11: subscriptions charge whatever you use; budgets and alerts only warn.
        for s in self.all:
            if s["spending"] == "subscription":
                self.assertIn("It's a subscription", s["limit"], s["id"])
        self.assertIn("only warn", services.by_id("openai")["limit"])

    def test_the_prices_in_the_code_agree_with_the_list(self):
        from smf.studio.render import imagegen
        from smf.video import transcribe
        self.assertEqual(transcribe.PRICE_PER_HOUR_USD, services.by_id("elevenlabs")["price_per_hour_usd"])
        cents = [round(p * 100) for sizes in imagegen.PRICES_USD.values() for q in sizes.values() for p in q.values()]
        low, high = services.by_id("openai")["picture_cents"]
        self.assertEqual((min(cents), max(cents)), (low, high))


class TestTheWalkthroughWords(unittest.TestCase):
    def test_metricool_says_which_value_goes_after_which_name(self):
        text = (ROOT / "SERVICES.md").read_text(encoding="utf-8")
        self.assertIn("Paste the API token after `METRICOOL_USER_TOKEN=` and the user id after `METRICOOL_USER_ID=`", text)

    def test_dates_read_the_same_on_any_computer(self):
        import locale
        s = services.by_id("metricool")
        self.assertEqual(services.checked_words(s), "15 October 2026")
        self.assertNotIn("strftime", (ROOT / "smf" / "services.py").read_text(encoding="utf-8").split("def checked_words")[1].split("def ")[0])

    def test_free_plans_and_paid_plans_are_never_called_credit_that_runs_out(self):
        for sid in ("apify", "elevenlabs"):
            s = services.by_id(sid)
            self.assertEqual(s["spending"], "plan", sid)
            self.assertIn("renew whatever you use", s["limit"], sid)


class TestOldPrices(unittest.TestCase):
    def test_a_stale_price_says_where_to_check_instead_of_a_number(self):
        s = services.by_id("metricool")
        fresh = services.cost_line(s, today=datetime.date.fromisoformat(s["checked"]))
        self.assertEqual(fresh, s["cost"])
        later = datetime.date.fromisoformat(s["checked"]) + datetime.timedelta(days=services.load()["stale_after_days"] + 1)
        stale = services.cost_line(s, today=later)
        self.assertNotIn("$", stale)
        self.assertIn(s["source"], stale)
        self.assertIn("last checked", stale)


class TestEverywhereReadsTheOneList(unittest.TestCase):
    def test_services_md_is_made_from_the_list_and_up_to_date(self):
        text = (ROOT / "SERVICES.md").read_text(encoding="utf-8")
        self.assertEqual(text, services.markdown())
        for s in services.load()["services"]:
            self.assertIn("## %s" % s["name"], text)
            self.assertIn(s["source"], text)

    def test_the_checklist_and_the_guide_quote_the_list(self):
        for entry in checklist.SERVICES:
            s = next(x for x in services.load()["services"] if x["name"] == entry["name"])
            self.assertEqual(entry["cost"], services.cost_line(s))
            self.assertEqual(entry["limit"], s["limit"])
        self.assertEqual(guide.SERVICE_FOR_KEY["METRICOOL_USER_TOKEN"], "Metricool (Advanced plan or higher)")
        self.assertIn("SERVICES.md", guide.INTRO)

    def test_no_price_is_hard_coded_in_the_setup_skill(self):
        skill = (ROOT / ".claude" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\$\d|\d+ cents", skill))
        self.assertIn("smf/services.json", skill)

    def test_the_name_is_social_media_factory(self):
        for path in (ROOT / "smf" / "services.json", ROOT / "smf" / "services.py"):
            self.assertIsNone(re.search(r"(?<!Social Media )\bFactory\b", path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
