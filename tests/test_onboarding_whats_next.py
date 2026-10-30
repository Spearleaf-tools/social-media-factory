"""After onboarding (spec rev 12 N7, rev 13 M7): "What's next" on the brand summary, and the menu of everything
the Social Media Factory can make, from the Full Content Reference."""
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from smf import brands, status
from smf.onboarding_page import summary, whats_next
from tests.test_brands import BAKERY

READY = {f["id"]: ("ready", "") for f in status.load_features()["features"]}


class TestTheCatalogue(unittest.TestCase):
    def setUp(self):
        self.cat = whats_next.catalogue()
        self.features = {f["id"] for f in status.load_features()["features"]}

    def test_all_54_options_in_their_stages(self):
        self.assertEqual(len(self.cat["items"]), 54)
        ids = [i["id"] for i in self.cat["items"]]
        staged = [i for s in self.cat["stages"] for i in s[1]]
        self.assertEqual(sorted(ids), sorted(staged))

    def test_every_option_is_in_exactly_one_kind(self):
        kinds = [i for k in self.cat["kinds"] for i in k[1]]
        self.assertEqual(sorted(kinds), sorted(i["id"] for i in self.cat["items"]))
        self.assertEqual(len(kinds), len(set(kinds)))
        self.assertEqual([k[0] for k in self.cat["kinds"]][:6], ["Just words", "A post with an image", "A carousel",
                                                                "A short video", "A long video", "A film or ad"])

    def test_platform_tags_are_known_and_cover_the_brand_choices(self):
        known = {p for p, _ in self.cat["platforms"]}
        for it in self.cat["items"]:
            self.assertLessEqual(set(it["platforms"]), known, it["id"])
        self.assertLessEqual({whats_next.BRAND_PLATFORM.get(p, p) for p in brands.PLATFORMS}, known)

    def test_every_option_is_backed_or_says_its_limit(self):
        for it in self.cat["items"]:
            for f in it["implements"] + it.get("also", []):
                self.assertIn(f, self.features, it["id"])
            if not it["implements"]:
                self.assertTrue(it.get("limit"), it["id"])

    def test_every_user_facing_feature_is_covered_or_internal(self):
        used = {f for it in self.cat["items"] for f in it["implements"] + it.get("also", [])} | set(self.cat["internal"])
        self.assertEqual(self.features - used, set())

    def test_it_says_social_media_factory_never_bare_factory(self):
        text = json.dumps(self.cat, ensure_ascii=False)
        self.assertEqual(re.findall(r"(?<!Media )\bFactory\b", text), [])

    def test_the_guide_keys_are_kept(self):
        for it in self.cat["items"]:
            for k in ("id", "group", "name", "when", "needs", "gives", "kind", "route", "note", "prompt", "label",
                      "input", "work", "format", "output", "implements"):
                self.assertIn(k, it, it["id"])


class TestThePages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="next ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_the_summary_has_whats_next_and_add_more(self):
        page = open(summary.build(self.brand, ready=READY), encoding="utf-8").read()
        self.assertIn("What's next", page)
        self.assertIn("Not sure where to start?", page)
        for title, _, _ in whats_next.STARTS:
            self.assertIn(title, page)
        self.assertIn("Help me get started with maple-and-main.", page)
        self.assertIn("Start with whatever you have, and add more whenever you like", page)
        self.assertIn('href="what-can-i-create.html"', page)
        self.assertIn("as checked at", page)
        self.assertNotIn("http", re.sub(r'content="[^"]*"', "", page.split("<main>")[1]))   # loads nothing

    def test_the_menu_is_written_beside_it_with_the_brand_filled_in(self):
        summary.build(self.brand, ready=READY)
        menu = open(self.brand.path(whats_next.MENU_NAME), encoding="utf-8").read()
        self.assertEqual(menu.count('<article class="card"'), 54)
        self.assertIn("For maple-and-main,", menu)
        self.assertNotIn("[brand]", menu)
        self.assertIn("How it works", menu)
        self.assertIn("Not available yet", menu)                 # the DM flow says its limit
        self.assertIn("font-family:Plex;src:url(data:font/ttf;base64,", menu)   # the guide's font, embedded
        self.assertIn("font-src data:", menu)
        self.assertIn("Pick a platform, or pick a kind of post.", menu)
        self.assertIn("For maple-and-main, plan a week of content across my platforms.", menu)

    def test_the_brands_own_platforms_come_first(self):
        self.brand.data["intended_platforms"] = {"by_speaker": {"owner": ["tiktok", "linkedin"]}}
        menu = whats_next.menu_html(self.brand, READY)
        chips = re.findall(r'data-plat="([^"]+)"[^>]*>([^<]+)<', menu)
        self.assertEqual([p for p, _ in chips][:2], ["shorts", "linkedin"])
        self.assertEqual(chips[0][1], "TikTok and YouTube Shorts · yours")
        self.assertNotIn("yours", chips[2][1])
        self.assertEqual(len(chips), 6)

    def test_the_font_ships_with_its_licence(self):
        self.assertTrue(os.path.getsize(whats_next.FONT) > 100000)
        lic = open(os.path.join(os.path.dirname(whats_next.FONT), "OFL.txt"), encoding="utf-8").read()
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", lic)
        self.assertIn("Copyright 2019 IBM Corp.", lic)

    def test_readiness_names_the_least_ready_feature(self):
        ready = dict(READY, **{"make-clips": ("needs setup", "")})
        self.assertEqual(whats_next.worst(["make-clips", "write-posts"], ready), "needs setup")
        self.assertEqual(whats_next.worst([], ready), "not built yet")

    def test_pack_ideas_are_possible_topics(self):
        self.brand.data.setdefault("business", {})["starter_pack"] = {"id": "auto-repair", "version": 1}
        html = whats_next.cards_html(self.brand, READY)
        self.assertIn("a possible topic:", html)
        self.assertIn("Possible topics, not facts", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
