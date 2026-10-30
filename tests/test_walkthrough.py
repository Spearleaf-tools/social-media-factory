"""The walkthrough: a brand-new, EMPTY brand goes all the way round with no key and no account.

    onboard -> plan from its own material -> write from a contract -> check the facts ->
    file into a batch -> draw a picture -> schedule the days -> review and approve -> ready-to-post folder

This is the promise on the front of the box, run as one test, in a folder whose name has a
space, an apostrophe and an accent. If a change breaks the loop for a stranger with nothing
set up, this is the test that says so.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands, checklist, keys                           # noqa: E402
from smf.studio import contract, plan, posts as P, topics         # noqa: E402

ANSWERS = {
    "business": {"what_we_do": "A two-person bicycle repair shop that fixes commuter bikes the same day.",
                 "industry": "bicycle repair", "regulated": "none"},
    "audience": {"who": "People who ride to work and cannot be without their bike for a week.",
                 "questions_they_ask": ["Why do my brakes squeal in the rain?", "How often should a chain be replaced?"]},
    "pillars": [{"id": "keep-it-rolling", "name": "Keep it rolling", "about": "Small checks that stop big repairs."}],
    "identities": [{"id": "person", "kind": "person", "display_name": "Noor Halvorsen", "role": "Mechanic"}],
    "voice": {"register": "Dry, practical and quick. Says what to check and how long it takes."},
    "visual": {"colors": {"ground": "#F7F7F2", "ink": "#14213D", "accent": "#E85D04"}, "wordmark": "Same Day Spokes"},
    "wants": ["posts", "visuals"],
}
DRAFT = ("Here is why your brakes squeal in the rain.\n\n"
         "Wet rims carry road grit, and grit on a brake pad sings.\n\n"
         "Three checks that take five minutes:\n"
         "1. Wipe the rims with a clean rag.\n"
         "2. Look for shiny, glazed pads and sand them lightly.\n"
         "3. Check the pads sit flat on the rim, not on the tyre.\n\n"
         "Save this for the next wet Monday.")


def tiny_png():
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x20\x30\x40" * 4 for _ in range(4))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class TestAStrangerWithNothingSetUp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="walk ' é through ")
        # Only the brands folder is moved. The rulebooks, shapes and fonts are the REAL ones that
        # ship with the Social Media Factory, because the point is to prove the shipped product works.
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(keys, "KEYS_FILE", os.path.join(self.tmp.name, "no-keys.env")),
                        mock.patch.dict(os.environ, {k: "" for k in keys.KNOWN_KEYS})]
        for p in self.patches:
            p.start()
        keys.load(force=True)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        keys.load(force=True)
        self.tmp.cleanup()

    def test_the_whole_loop_with_no_key_and_an_empty_brand(self):
        # 1. onboard: eight answers, nothing else. No proof, no photos, no past posts.
        brand = brands.create("same-day-spokes", "Same Day Spokes", json.loads(json.dumps(ANSWERS)))
        self.assertEqual(brands.validate(brand.data)[0], [])
        brands.sync(brand)
        _path, services = checklist.build(brand)
        self.assertEqual(services, [], "writing and visuals must need no outside account")

        # 2. plan: topics come from the brand's own material, and must say where from
        brief = topics.planning_brief(brand)
        self.assertIn("Why do my brakes squeal in the rain?", brief)
        topics.add_topics(brand, "week-1", [topics.new_topic("Why brakes squeal in the rain",
                                                             source_ref="audience.questions_they_ask[0]",
                                                             pillar="keep-it-rolling")])
        tid = topics.load_run(brand, "week-1")[0]["topic_id"]
        topics.set_status(brand, "week-1", tid, "approved")
        problems, _warnings = topics.check_topics(brand, topics.approved_topics(brand, "week-1"))
        self.assertEqual(problems, [])
        planned = plan.plan_topic(topics.get_topic(brand, "week-1", tid), brand, "person", "reach")
        shapes = planned["plans"]["person"]["platform_shapes"]                 # a plan is kept per identity
        self.assertEqual(len({s["shape"] for s in shapes.values()}), len(shapes), "a different angle per platform")
        platform = "linkedin"
        self.assertIn(platform, shapes)
        self.assertTrue(set(planned["plans"]["person"]["visual_format"]["draws_as"]),
                        "an empty brand is only planned pictures the Social Media Factory can draw")

        # 3. write from a contract, then check it: nothing invented, so nothing blocks
        c = contract.build_contract(brand, "person", platform, planned, shapes[platform]["shape"], "reach")
        self.assertIn("Never invent", c.markdown)
        self.assertIn("Noor Halvorsen", c.markdown)
        report = contract.validate_draft(DRAFT, brand, "person", platform, planned, job="reach")
        self.assertTrue(report["ok"], contract.format_report(report))
        self.assertIn(report["sourcing"], ("passed", "unverified"))
        self.assertNotEqual(report["sourcing"], "blocked")

        # ...and an invented number IS caught, for the same empty brand
        lie = DRAFT.replace("Three checks", "We have fixed 12,400 bikes. Three checks")
        self.assertEqual(contract.validate_draft(lie, brand, "person", platform, planned, job="reach")["sourcing"], "blocked")

        # 4. file it, give it a picture, plan the days
        post = P.Post(id="p1", brand=brand.id, identity="person", platform=platform, text=DRAFT, topic_id=tid)
        contract.apply_to_post(post, report)
        picture = Path(brand.path("Output", "visuals", "run 1", "card-01.png"))
        picture.parent.mkdir(parents=True)
        picture.write_bytes(tiny_png())
        post.media_paths = ["Output/visuals/run 1/card-01.png"]
        P.check_batch([post], brand)
        self.assertEqual(post.status, "lint_pass", post.lint_errors)
        P.assign_drip_slots([post], brand, start_date="2031-05-05")
        self.assertEqual(post.scheduled_time_local[:10], "2031-05-05")
        batch = brand.path("Output", "batches", "week-1.json")
        P.save_batch([post], batch)

        # 5. approve exactly what was shown, then a ready-to-post folder comes out
        from smf.studio import export
        from smf.studio.review.store import BatchStore, Refusal
        with self.assertRaises(export.ExportError):
            export.export_ready_folder(brand, [batch])                     # nothing is approved yet
        store = BatchStore(brand, [batch])
        shown = store.one("p1")
        if post.sourcing != "passed":
            with self.assertRaises(Refusal):                                # unverified needs a deliberate tick
                store.approve("p1", shown["rev"], P.approval_sha(post))
        store.approve("p1", shown["rev"], P.approval_sha(post), acknowledged=True)
        approved, _meta = P.load_batch(batch, brand.id)
        self.assertEqual(approved[0].status, "approved")
        self.assertTrue(P.approval_is_current(approved[0]))

        folder = export.export_ready_folder(brand, [batch])
        files = sorted(str(p.relative_to(folder)).replace(os.sep, "/") for p in Path(folder).rglob("*") if p.is_file())
        self.assertTrue(any(f.endswith("post.txt") for f in files), files)
        self.assertTrue(any(f.endswith("1.png") for f in files), files)
        words = next(Path(folder).rglob("post.txt")).read_text(encoding="utf-8")
        self.assertIn("Here is why your brakes squeal in the rain.", words)

        # 6. it is marked as exported, and running the export again duplicates nothing
        exported, _meta = P.load_batch(batch, brand.id)
        self.assertEqual(exported[0].status, "exported")
        again = export.export_posts(brand, [batch])
        self.assertEqual(sorted(str(p.relative_to(folder)).replace(os.sep, "/")
                                for p in Path(folder).rglob("*") if p.is_file()), files)
        self.assertTrue(again.folder)


if __name__ == "__main__":
    unittest.main(verbosity=2)
