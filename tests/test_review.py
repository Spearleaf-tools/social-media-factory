"""Review page tests: one brand at a time, approval means what it says, nothing is lost or leaked.

    python -m unittest discover -s tests -t . -v

The web tests use Flask's test client and are skipped where Flask is not installed (it arrives
with `python factory.py setup`). The rules underneath are tested without a web server as well.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import socket
import struct
import sys
import tempfile
import unittest
import zlib
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                        # noqa: E402
from smf.studio import posts as P                             # noqa: E402
from smf.studio.review import store as S                      # noqa: E402
from tests.test_brands import BAKERY, CLINIC                  # noqa: E402
from tests.test_studio import FOUR                            # noqa: E402

HAVE_FLASK = importlib.util.find_spec("flask") is not None
needs_flask = unittest.skipUnless(HAVE_FLASK, "Flask is installed by `python factory.py setup`")
PAGE = ROOT / "smf" / "studio" / "review" / "static" / "index.html"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
CLEAN = "We proof the dough for eighteen hours.\n\nThat is why the crust cracks when you press it."


def png_bytes(width=4, height=4, rgb=(194, 87, 26)):
    """A real, tiny PNG made from nothing but the standard library. No image file lives in the repo."""
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class ReviewCase(unittest.TestCase):
    """Two fictional brands in a folder with a space, an apostrophe and an accent in its name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="review ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        answers = json.loads(json.dumps(BAKERY))
        answers.update(json.loads(json.dumps(FOUR)))
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", answers)
        self.clinic = brands.create("stride-physio", "Stride Physio", json.loads(json.dumps(CLINIC)))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    # building blocks -------------------------------------------------------------------------
    def image(self, rel="Output/visuals/loaf's crumb é.png", brand=None, rgb=(194, 87, 26)):
        path = (brand or self.brand).path(*rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(png_bytes(rgb=rgb))
        return rel

    def post(self, pid, platform="linkedin", identity="person", text=CLEAN, sourcing="passed", **kw):
        return P.Post(id=pid, brand=self.brand.id, identity=identity, platform=platform, text=text,
                      sourcing=sourcing, topic_id=kw.pop("topic_id", "t-" + pid), **kw)

    def batch(self, posts, name="week 1's batch é.json", brand=None):
        brand = brand or self.brand
        P.check_batch(posts, brand)
        path = brand.path("Output", "batches", name)
        P.save_batch(posts, path, {"generated_at": "2026-10-01T09:00:00Z"})
        return path

    def on_disk(self, path, pid, brand=None):
        posts, _meta = P.load_batch(path, (brand or self.brand).id)
        return next(p for p in posts if p.id == pid)

    def client(self, paths, brand=None):
        from smf.studio.review.server import create_app
        return create_app(brand or self.brand, paths).test_client()

    def shown(self, client, pid):
        return client.get("/api/post/" + pid).get_json()["post"]

    def approve(self, client, pid, **extra):
        p = self.shown(client, pid)
        body = {"rev": p["rev"], "content_sha": p["content_sha"]}
        body.update(extra)
        return client.post("/api/post/%s/approve" % pid, json=body)


# ============================================================================= the brand comes first
@needs_flask
class TestOneBrandOnly(ReviewCase):
    def test_another_brands_batch_is_refused_at_the_door(self):
        theirs = P.Post(id="c1", brand="stride-physio", identity="person", platform="instagram", text="Run tall.")
        path = self.batch([theirs], "clinic week.json", brand=self.clinic)
        from smf.studio.review.server import create_app
        with self.assertRaises(S.Refusal) as cm:
            create_app(self.brand, [path])
        self.assertIn("belongs to stride-physio", str(cm.exception))
        self.assertEqual(cm.exception.status, 403)

    def test_one_foreign_batch_among_good_ones_stops_the_whole_review(self):
        mine = self.batch([self.post("a")])
        theirs = self.batch([P.Post(id="c1", brand="stride-physio", identity="person", platform="instagram",
                                    text="Run tall.")], "clinic week.json", brand=self.clinic)
        from smf.studio.review.server import create_app
        with self.assertRaises(S.Refusal):
            create_app(self.brand, [mine, theirs])

    def test_there_is_no_default_brand(self):
        from smf.studio.review.server import create_app
        path = self.batch([self.post("a")])
        for nobody in (None, "", "no-such-brand"):
            with self.assertRaises(brands.BrandError):
                create_app(nobody, [path])

    def test_a_brand_id_works_as_well_as_a_brand(self):
        path = self.batch([self.post("a")])
        from smf.studio.review.server import create_app
        data = create_app("maple-and-main", [path]).test_client().get("/api/batch").get_json()
        self.assertEqual(data["brand"]["id"], "maple-and-main")
        self.assertEqual(data["brand"]["identities"]["person"], "Ava Lindqvist")

    def test_no_batch_and_a_missing_batch_are_plain_refusals(self):
        from smf.studio.review.server import create_app
        with self.assertRaises(S.Refusal):
            create_app(self.brand, [])
        with self.assertRaises(S.Refusal) as cm:
            create_app(self.brand, [self.brand.path("Output", "batches", "nothing here.json")])
        self.assertIn("could not be found", str(cm.exception))

    def test_two_posts_with_one_id_cannot_share_a_review(self):
        a = self.batch([self.post("same")], "monday.json")
        b = self.batch([self.post("same")], "tuesday.json")
        from smf.studio.review.server import create_app
        with self.assertRaises(S.Refusal) as cm:
            create_app(self.brand, [a, b])
        self.assertIn("share the id", str(cm.exception))

    def test_several_batches_open_as_one_review_and_are_linted_with_this_brands_rules(self):
        a = self.batch([self.post("mon")], "monday.json")
        b = self.batch([self.post("tue", text="We supply Harbour Street Cafe.")], "tuesday.json")
        data = self.client([a, b]).get("/api/batch").get_json()
        self.assertEqual([p["id"] for p in data["posts"]], ["mon", "tue"])
        tue = data["posts"][1]
        self.assertTrue(any("never-mention" in e for e in tue["lint_errors"]))      # the bakery's own rule
        self.assertEqual(data["limits"]["linkedin"]["fold"], S.FOLD_MARKERS["linkedin"])
        self.assertEqual(data["limits"]["twitter"], {"max": 280})
        self.assertEqual(data["style"]["max_sentence_words"], self.brand.style["max_sentence_words"])


# ============================================================================= the page and the door
@needs_flask
class TestThePageAndWhoMayTalkToIt(ReviewCase):
    def setUp(self):
        super().setUp()
        self.c = self.client([self.batch([self.post("a")])])

    def test_the_page_is_served_with_a_policy_that_forbids_loading_anything_from_elsewhere(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Social Media Factory review", r.get_data(as_text=True))
        policy = r.headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", policy)
        self.assertIn("connect-src 'self'", policy)
        self.assertNotIn("http", policy)
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        r.close()

    def test_a_foreign_host_name_or_origin_is_turned_away(self):
        self.assertEqual(self.c.get("/api/batch", headers={"Host": "elsewhere.example:8642"}).status_code, 403)
        p = self.shown(self.c, "a")
        r = self.c.post("/api/post/a/reject", json={"rev": p["rev"]}, headers={"Origin": "https://elsewhere.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.shown(self.c, "a")["status"], "lint_pass")

    def test_a_change_that_is_not_json_is_refused(self):
        r = self.c.post("/api/post/a/reject", data="rev=0", content_type="text/plain")
        self.assertEqual(r.status_code, 415)
        self.assertEqual(self.shown(self.c, "a")["status"], "lint_pass")

    def test_unknown_addresses_and_posts_get_a_sentence_not_a_stack_trace(self):
        for url in ("/nothing", "/api/post/ghost"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 404)
            self.assertIn("error", r.get_json())
            self.assertNotIn("Traceback", r.get_data(as_text=True))

    def test_it_only_ever_listens_on_this_computer_and_finds_a_free_port(self):
        from smf.studio.review import server
        self.assertEqual(server.HOST, "127.0.0.1")
        self.assertNotIn("host", inspect.signature(server.serve).parameters)
        busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        busy.bind((server.HOST, 0))
        busy.listen(1)
        try:
            taken = busy.getsockname()[1]
            self.assertNotEqual(server.pick_port(taken), taken)
        finally:
            busy.close()


# ============================================================================= media
@needs_flask
class TestMediaStaysInsideTheBrand(ReviewCase):
    def test_a_posts_own_image_is_served_and_no_path_reaches_the_page(self):
        rel = self.image()
        c = self.client([self.batch([self.post("ig", platform="instagram", media_paths=[rel])])])
        r = c.get("/media/ig/0")
        self.assertEqual((r.status_code, r.mimetype), (200, "image/png"))
        self.assertEqual(r.get_data(), png_bytes())
        r.close()
        shown = self.shown(c, "ig")
        self.assertNotIn("media_paths", shown)
        self.assertEqual(shown["media"], [{"index": 0, "name": "loaf's crumb é.png", "kind": "image", "problem": ""}])
        self.assertNotIn(self.tmp.name, json.dumps(c.get("/api/batch").get_json()))

    def test_path_traversal_and_other_brands_files_are_refused(self):
        self.image("Brand/brand-kit/logos/clinic logo.png", brand=self.clinic)
        outside = os.path.join(self.tmp.name, "loose file.png")
        with open(outside, "wb") as f:
            f.write(png_bytes())
        hostile = ["../stride-physio/Brand/brand-kit/logos/clinic logo.png",
                   "..\\stride-physio\\Brand\\brand-kit\\logos\\clinic logo.png",
                   "Output/../../stride-physio/Brand/brand-kit/logos/clinic logo.png",
                   self.clinic.path("Brand", "brand-kit", "logos", "clinic logo.png"),
                   outside]
        c = self.client([self.batch([self.post("bad", platform="instagram", media_paths=hostile)])])
        for i in range(len(hostile)):
            r = c.get("/media/bad/%d" % i)
            self.assertEqual(r.status_code, 403, hostile[i])
            self.assertNotEqual(r.get_data(), png_bytes())
        shown = self.shown(c, "bad")
        self.assertEqual({m["problem"] for m in shown["media"]}, {"outside"})
        self.assertTrue(any("media-outside" in e for e in shown["lint_errors"]))
        self.assertEqual(self.approve(c, "bad").status_code, 400)             # what cannot be seen cannot be approved

    def test_a_link_that_leads_out_of_the_brand_folder_is_refused(self):
        outside = os.path.join(self.tmp.name, "secret.png")
        with open(outside, "wb") as f:
            f.write(png_bytes())
        link = self.brand.path("Output", "visuals", "looks innocent.png")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("this computer does not allow links")
        c = self.client([self.batch([self.post("l", platform="instagram",
                                               media_paths=["Output/visuals/looks innocent.png"])])])
        self.assertEqual(c.get("/media/l/0").status_code, 403)

    def test_missing_files_wrong_kinds_and_wrong_positions(self):
        rel = self.image()
        c = self.client([self.batch([self.post("m", platform="instagram",
                                               media_paths=[rel, "Output/visuals/gone.png", "brand-master.json"])])])
        self.assertEqual(c.get("/media/m/1").status_code, 404)
        self.assertEqual(c.get("/media/m/2").status_code, 415)                # the settings file is not media
        self.assertEqual(c.get("/media/m/3").status_code, 404)
        self.assertEqual(c.get("/media/m/-1").status_code, 404)
        self.assertEqual(c.get("/media/ghost/0").status_code, 404)
        self.assertEqual(c.get("/media/m/0/../../../brand-master.json").status_code, 404)


# ============================================================================= approving
@needs_flask
class TestApproving(ReviewCase):
    def test_approving_stamps_exactly_what_was_shown(self):
        rel = self.image()
        path = self.batch([self.post("ig", platform="instagram", media_paths=[rel], first_comment="Classes open Monday.")])
        c = self.client([path])
        r = self.approve(c, "ig")
        self.assertEqual(r.status_code, 200, r.get_json())
        saved = self.on_disk(path, "ig")
        self.assertEqual(saved.status, "approved")
        self.assertTrue(saved.approved_at.endswith("Z"))
        self.assertEqual(saved.approved_text_sha, P.approval_sha(saved))
        self.assertTrue(P.approval_is_current(saved))
        self.assertEqual(saved.rev, 1)
        self.assertEqual(r.get_json()["post"]["approval"], "current")
        self.assertEqual([f for f in os.listdir(os.path.dirname(path)) if f.startswith(".tmp-")], [])
        self.assertTrue(os.path.isfile(path + ".bak"))                         # the untouched copy
        history = S.read_history(path)
        self.assertEqual((history[-1]["action"], history[-1]["actor"], history[-1]["prev"]["status"]),
                         ("approve", "review-page", "lint_pass"))

    def test_the_fingerprint_covers_words_media_order_thread_and_first_comment(self):
        p = self.post("x", platform="twitter", thread=["two", "three"], media_paths=["a.png", "b.png"])
        base = P.approval_sha(p)
        for change in (dict(text=p.text + " "), dict(thread=["two", "three!"]), dict(media_paths=["b.png", "a.png"]),
                       dict(first_comment="hello"), dict(alt_text="a loaf"), dict(link="maple.example/classes")):
            q = self.post("x", platform="twitter", thread=["two", "three"], media_paths=["a.png", "b.png"])
            for k, v in change.items():
                setattr(q, k, v)
            self.assertNotEqual(P.approval_sha(q), base, change)
        self.assertEqual(P.approval_sha(self.post("x", platform="twitter", thread=["two", "three"],
                                                  media_paths=["a.png", "b.png"], feedback="a note")), base)

    def test_a_post_with_lint_errors_cannot_be_approved_and_nothing_changes(self):
        path = self.batch([self.post("bad", text="An innovative loaf — baked for Harbour Street Cafe.")])
        before = Path(path).read_bytes()
        c = self.client([path])
        r = self.approve(c, "bad", acknowledge_unverified=True)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["reason"], "lint")
        self.assertTrue(r.get_json()["problems"])
        self.assertEqual(Path(path).read_bytes(), before)
        self.assertIn("must be fixed", self.shown(c, "bad")["approve_block"])

    def test_instagram_without_an_image_cannot_be_approved(self):
        c = self.client([self.batch([self.post("ig", platform="instagram")])])
        self.assertEqual(self.approve(c, "ig").status_code, 400)

    def test_an_unverified_post_shows_the_badge_and_needs_an_explicit_acknowledgement(self):
        path = self.batch([self.post("u", sourcing="unverified")])
        before = Path(path).read_bytes()
        c = self.client([path])
        shown = self.shown(c, "u")
        self.assertEqual(shown["sourcing_note"],
                         "unverified: the facts in this post have not been checked against your own material")
        self.assertTrue(shown["needs_acknowledgement"])

        for not_a_yes in ({}, {"acknowledge_unverified": False}, {"acknowledge_unverified": "yes"},
                          {"acknowledge_unverified": 1}):
            r = self.approve(c, "u", **not_a_yes)
            self.assertEqual(r.status_code, 400, not_a_yes)
            self.assertTrue(r.get_json()["needs_acknowledgement"])
        self.assertEqual(Path(path).read_bytes(), before)

        r = self.approve(c, "u", acknowledge_unverified=True)
        self.assertEqual(r.status_code, 200)
        saved = self.on_disk(path, "u")
        self.assertEqual(saved.status, "approved")
        self.assertEqual(saved.sourcing, "unverified")                        # approving does not make it checked
        self.assertIn("confirmed they checked the facts themselves", saved.feedback)

    def test_sourcing_is_unverified_unless_something_said_otherwise(self):
        fresh = P.Post(id="n", brand=self.brand.id, identity="person", platform="linkedin", text=CLEAN)
        c = self.client([self.batch([fresh])])
        self.assertEqual(self.approve(c, "n").status_code, 400)

    def test_a_failed_fact_check_cannot_be_waved_through(self):
        c = self.client([self.batch([self.post("f", sourcing="blocked")])])
        r = self.approve(c, "f", acknowledge_unverified=True)
        self.assertEqual((r.status_code, r.get_json()["reason"]), (400, "facts-failed"))

    def test_a_proof_file_that_is_not_cleared_never_gets_approved(self):
        """The consent rule is the proof library's own (`proof.media_block_reason`); the review page
        and the export both obey it. Linked private proof only warns: it may be background."""
        from smf.studio import proof
        shots = {}
        for name, rgb in (("cleared.png", (1, 1, 1)), ("private.png", (2, 2, 2)), ("unlisted.png", (3, 3, 3))):
            shots[name] = self.image("Inputs/Proof/" + name, rgb=rgb)
        yes = proof.add(self.brand, "screenshot", "Saturday class sold out", source="the class booking sheet",
                        file_path=self.brand.path("Inputs", "Proof", "cleared.png"), may_publish="yes")
        no = proof.add(self.brand, "testimonial", "A note from a regular", source="a card left at the counter",
                       file_path=self.brand.path("Inputs", "Proof", "private.png"), may_publish="no")
        rows = {r["proof_id"]: r["file_path"] for r in proof.items(self.brand)}
        c = self.client([self.batch([
            self.post("ok", platform="instagram", media_paths=[rows[yes]], proof_ids=[yes]),
            self.post("private", platform="instagram", media_paths=[rows[no]]),
            self.post("unlisted", platform="instagram", media_paths=[shots["unlisted.png"]]),
            self.post("background", proof_ids=[no, "PRF-9999"])])])
        self.assertEqual(self.approve(c, "ok").status_code, 200)
        for pid in ("private", "unlisted"):
            self.assertEqual(self.approve(c, pid).status_code, 400, pid)
            self.assertTrue(any("media-not-cleared" in e for e in self.shown(c, pid)["lint_errors"]), pid)
        background = self.shown(c, "background")
        self.assertTrue(any("private-proof" in w for w in background["lint_warnings"]))
        self.assertTrue(any("proof-unknown" in w for w in background["lint_warnings"]))
        self.assertEqual(self.approve(c, "background").status_code, 200)       # told, not stopped

    def test_the_request_must_say_which_version_it_means(self):
        path = self.batch([self.post("a")])
        c = self.client([path])
        p = self.shown(c, "a")
        self.assertEqual(c.post("/api/post/a/approve", json={"content_sha": p["content_sha"]}).status_code, 400)
        self.assertEqual(c.post("/api/post/a/approve", json={"rev": p["rev"]}).status_code, 400)
        self.assertEqual(c.post("/api/post/a/approve", json={"rev": True, "content_sha": p["content_sha"]}).status_code, 400)
        self.assertEqual(self.on_disk(path, "a").status, "lint_pass")

    def test_approving_twice_or_approving_a_post_that_has_gone_out_is_refused(self):
        path = self.batch([self.post("a"), self.post("sent", status="exported")])
        c = self.client([path])
        self.assertEqual(self.approve(c, "a").status_code, 200)
        self.assertEqual(self.approve(c, "a").get_json()["reason"], "already")
        self.assertEqual(self.approve(c, "sent").get_json()["reason"], "locked")


# ============================================================================= an edit voids the approval
@needs_flask
class TestAnEditVoidsTheApproval(ReviewCase):
    def edit(self, c, pid, **body):
        body["rev"] = self.shown(c, pid)["rev"]
        return c.post("/api/post/%s/edit" % pid, json=body)

    def test_editing_the_words_clears_the_approval_and_relints_with_this_brands_rules(self):
        path = self.batch([self.post("a")])
        c = self.client([path])
        self.approve(c, "a")
        r = self.edit(c, "a", text="We proof the dough for twenty hours.")
        self.assertEqual(r.status_code, 200)
        saved = self.on_disk(path, "a")
        self.assertEqual((saved.status, saved.approved_at, saved.approved_text_sha), ("lint_pass", "", ""))
        self.assertEqual(saved.sourcing, "unverified")                        # new words, nobody checked these facts
        self.assertEqual(saved.rev, 2)

        self.approve(c, "a", acknowledge_unverified=True)
        self.edit(c, "a", text="We supply Harbour Street Cafe.")               # on the bakery's never-mention list
        saved = self.on_disk(path, "a")
        self.assertEqual((saved.status, saved.approved_at), ("draft", ""))
        self.assertTrue(any("never-mention" in e for e in saved.lint_errors))
        self.assertEqual(self.approve(c, "a", acknowledge_unverified=True).status_code, 400)

    def test_the_same_words_are_fine_for_a_brand_without_that_rule(self):
        theirs = P.Post(id="c1", brand="stride-physio", identity="person", platform="linkedin", text="Run tall.",
                        sourcing="passed")
        path = self.batch([theirs], "clinic.json", brand=self.clinic)
        c = self.client([path], brand=self.clinic)
        r = c.post("/api/post/c1/edit", json={"rev": 0, "text": "We treat the team at Harbour Street Cafe."})
        self.assertEqual(r.get_json()["post"]["status"], "lint_pass")

    def test_changing_the_media_clears_the_approval_too(self):
        one, two = self.image("Output/visuals/1 cover.png"), self.image("Output/visuals/2 crumb.png", rgb=(1, 2, 3))
        path = self.batch([self.post("ig", platform="instagram", media_paths=[one, two])])
        c = self.client([path])
        self.approve(c, "ig")
        self.assertEqual(self.edit(c, "ig", media_order=[1, 0]).status_code, 200)
        saved = self.on_disk(path, "ig")
        self.assertEqual(saved.media_paths, [two, one])
        self.assertEqual((saved.status, saved.approved_text_sha), ("lint_pass", ""))
        self.assertEqual(saved.sourcing, "passed")                            # the words did not change

        self.approve(c, "ig")
        self.edit(c, "ig", media_order=[])                                    # Instagram with no image is not a post
        saved = self.on_disk(path, "ig")
        self.assertEqual((saved.status, saved.media_paths), ("draft", []))

    def test_the_page_can_only_rearrange_a_posts_own_media(self):
        one = self.image("Output/visuals/1 cover.png")
        path = self.batch([self.post("ig", platform="instagram", media_paths=[one])])
        c = self.client([path])
        before = Path(path).read_bytes()
        for nonsense in ([0, 0], [1], [-1], ["Output/visuals/1 cover.png"], [True], "0"):
            self.assertEqual(self.edit(c, "ig", media_order=nonsense).status_code, 400, nonsense)
        for bad in (dict(text=5), dict(thread="one"), dict(thread=[1]), dict(alt_text=[]), dict(first_comment={})):
            self.assertEqual(self.edit(c, "ig", **bad).status_code, 400, bad)
        self.assertEqual(Path(path).read_bytes(), before)

    def test_a_thread_is_edited_tweet_by_tweet_and_every_tweet_is_checked(self):
        path = self.batch([self.post("x", platform="twitter", thread=["Second tweet.", "Third tweet."])])
        c = self.client([path])
        self.approve(c, "x")
        self.edit(c, "x", thread=["Second tweet.", "", "y" * 300])
        saved = self.on_disk(path, "x")
        self.assertEqual(saved.thread, ["Second tweet.", "y" * 300])           # the emptied tweet is gone
        self.assertEqual(saved.status, "draft")
        self.assertTrue(any("[tweet 3]" in e for e in saved.lint_errors))

    def test_an_edit_that_changes_nothing_writes_nothing(self):
        path = self.batch([self.post("a")])
        c = self.client([path])
        self.approve(c, "a")
        before = Path(path).read_bytes()
        self.assertEqual(self.edit(c, "a", text=CLEAN).get_json()["post"]["status"], "approved")
        self.assertEqual(Path(path).read_bytes(), before)

    def test_a_post_changed_behind_the_pages_back_shows_as_no_longer_approved(self):
        path = self.batch([self.post("a")])
        c = self.client([path])
        self.approve(c, "a")
        posts, meta = P.load_batch(path, self.brand.id)
        posts[0].text = "Someone else rewrote this and left the approval in place."
        P.save_batch(posts, path, meta)
        shown = self.shown(c, "a")
        self.assertEqual((shown["status"], shown["approval"]), ("approved", "voided"))
        self.assertEqual(self.approve(c, "a").status_code, 200)               # and it can be approved again, knowingly
        self.assertTrue(P.approval_is_current(self.on_disk(path, "a")))

    def test_a_post_that_has_gone_out_cannot_be_edited(self):
        path = self.batch([self.post("sent", status="exported")])
        c = self.client([path])
        self.assertEqual(self.edit(c, "sent", text="Too late.").status_code, 400)
        self.assertEqual(self.on_disk(path, "sent").text, CLEAN)


# ============================================================================= reject, remake, undo
@needs_flask
class TestRejectRemakeUndo(ReviewCase):
    def setUp(self):
        super().setUp()
        self.path = self.batch([self.post("a"), self.post("b")])
        self.c = self.client([self.path])

    def send(self, pid, action, **body):
        body["rev"] = self.shown(self.c, pid)["rev"]
        return self.c.post("/api/post/%s/%s" % (pid, action), json=body)

    def test_reject_keeps_the_note_and_clears_any_approval(self):
        self.approve(self.c, "a")
        self.assertEqual(self.send("a", "reject", note="  Wrong week for this.  ").status_code, 200)
        saved = self.on_disk(self.path, "a")
        self.assertEqual((saved.status, saved.feedback, saved.approved_at), ("rejected", "Wrong week for this.", ""))
        self.assertEqual(self.approve(self.c, "a").get_json()["reason"], "status")

    def test_a_remake_request_waits_with_its_note_and_blocks_approval(self):
        self.assertEqual(self.send("a", "remake", note="make it shorter", kind="image").status_code, 200)
        saved = self.on_disk(self.path, "a")
        self.assertEqual((saved.status, saved.feedback), ("regen_queued", "[image] make it shorter"))
        self.assertEqual(self.approve(self.c, "a").get_json()["reason"], "remake")
        self.assertEqual(self.send("b", "remake", note="x", kind="everything").status_code, 400)
        self.assertEqual(self.on_disk(self.path, "b").status, "lint_pass")

    def test_undo_walks_backwards_one_step_at_a_time_and_then_stops(self):
        self.approve(self.c, "a")
        self.send("a", "edit", text="A new first line.")
        self.send("a", "reject", note="no")
        self.assertEqual(self.send("a", "undo").get_json()["post"]["status"], "lint_pass")     # un-reject
        back = self.send("a", "undo").get_json()["post"]                                       # un-edit
        self.assertEqual((back["text"], back["status"], back["approval"]), (CLEAN, "approved", "current"))
        self.assertEqual(self.send("a", "undo").get_json()["post"]["status"], "lint_pass")     # un-approve
        r = self.send("a", "undo")
        self.assertEqual(r.status_code, 400)
        self.assertIn("nothing left to undo", r.get_json()["error"])
        self.assertEqual(self.on_disk(self.path, "a").rev, 6)                  # every write bumped rev
        self.assertEqual(len([e for e in S.read_history(self.path) if e["post_id"] == "a"]), 6)


# ============================================================================= somebody else changed it
@needs_flask
class TestWhenTheFileChangesUnderneath(ReviewCase):
    def test_a_stale_rev_is_a_conflict_in_plain_words_and_changes_nothing(self):
        path = self.batch([self.post("a")])
        c = self.client([path])
        mine = self.shown(c, "a")

        posts, meta = P.load_batch(path, self.brand.id)                       # a remake lands while the page is open
        posts[0].text, posts[0].rev = "A remade post nobody has read yet.", posts[0].rev + 1
        P.save_batch(posts, path, meta)
        before = Path(path).read_bytes()

        for action, body in (("approve", {"content_sha": mine["content_sha"]}), ("edit", {"text": "Mine."}),
                             ("reject", {"note": "n"}), ("remake", {"note": "n"}), ("undo", {})):
            body["rev"] = mine["rev"]
            r = c.post("/api/post/a/" + action, json=body)
            self.assertEqual(r.status_code, 409, action)
            answer = r.get_json()
            self.assertTrue(answer["conflict"])
            self.assertIn("changed by something else", answer["error"])
            self.assertEqual(answer["post"]["text"], "A remade post nobody has read yet.")    # the fresh copy
        self.assertEqual(Path(path).read_bytes(), before)
        self.assertEqual(S.read_history(path), [])

    def test_words_changed_without_a_new_rev_still_cannot_be_approved_unseen(self):
        path = self.batch([self.post("a")])
        c = self.client([path])
        mine = self.shown(c, "a")
        posts, meta = P.load_batch(path, self.brand.id)
        posts[0].text = "Swapped in quietly."                                 # a careless tool: same rev
        P.save_batch(posts, path, meta)
        r = c.post("/api/post/a/approve", json={"rev": mine["rev"], "content_sha": mine["content_sha"]})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.on_disk(path, "a").status, "lint_pass")


# ============================================================================= looked at, and approve all
@needs_flask
class TestSeenAndApproveAll(ReviewCase):
    def setUp(self):
        super().setUp()
        self.path = self.batch([self.post("seen"), self.post("unseen"), self.post("facts", sourcing="unverified"),
                                self.post("broken", text="An innovative loaf.")])
        self.c = self.client([self.path])

    def look(self, pid):
        return self.c.post("/api/post/%s/seen" % pid, json={"content_sha": self.shown(self.c, pid)["content_sha"]})

    def test_looking_is_remembered_without_touching_the_batch(self):
        before = Path(self.path).read_bytes()
        self.assertFalse(self.shown(self.c, "seen")["seen"])
        self.assertTrue(self.look("seen").get_json()["post"]["seen"])
        self.look("seen")
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertEqual(len(S.read_history(self.path)), 1)                   # looking twice is one note

    def test_approve_all_only_takes_posts_that_were_looked_at_clean_and_checked(self):
        for pid in ("seen", "facts", "broken"):
            self.look(pid)
        items = [{"id": p["id"], "rev": p["rev"], "content_sha": p["content_sha"]}
                 for p in self.c.get("/api/batch").get_json()["posts"]] + [{"id": "ghost", "rev": 0, "content_sha": "x"}]
        answer = self.c.post("/api/approve-all", json={"posts": items}).get_json()
        self.assertEqual(answer["approved"], ["seen"])
        why = {s["id"]: s["reason"] for s in answer["skipped"]}
        self.assertIn("not looked at", why["unseen"])
        self.assertIn("unverified", why["facts"])
        self.assertIn("must be fixed", why["broken"])
        self.assertIn("not in this review", why["ghost"])
        self.assertEqual([self.on_disk(self.path, i).status for i in ("seen", "unseen", "facts", "broken")],
                         ["approved", "lint_pass", "lint_pass", "draft"])
        self.assertTrue(P.approval_is_current(self.on_disk(self.path, "seen")))

    def test_a_post_changed_since_it_was_seen_is_flagged_and_not_swept_up(self):
        self.look("seen")
        stale = self.shown(self.c, "seen")
        posts, meta = P.load_batch(self.path, self.brand.id)
        posts[0].text, posts[0].rev = "Remade after you looked.", 1
        P.save_batch(posts, self.path, meta)
        now = self.shown(self.c, "seen")
        self.assertEqual((now["seen"], now["changed_since_seen"]), (False, True))
        for item in (stale, now):                                             # the old version, and the unseen new one
            answer = self.c.post("/api/approve-all", json={"posts": [
                {"id": "seen", "rev": item["rev"], "content_sha": item["content_sha"]}]}).get_json()
            self.assertEqual(answer["approved"], [])
        self.assertEqual(self.c.post("/api/post/seen/seen", json={"content_sha": stale["content_sha"]}).status_code, 409)


# ============================================================================= the rules, without a web server
class TestTheRulesWithoutAWebServer(ReviewCase):
    def test_another_brands_batch_is_refused(self):
        theirs = P.Post(id="c1", brand="stride-physio", identity="person", platform="instagram", text="Run tall.")
        path = self.batch([theirs], "clinic.json", brand=self.clinic)
        with self.assertRaises(S.Refusal) as cm:
            S.BatchStore(self.brand, [path])
        self.assertIn("belongs to stride-physio", str(cm.exception))
        with self.assertRaises(brands.BrandError):
            S.BatchStore(None, [path])

    def test_media_is_resolved_inside_the_brand_folder_or_not_at_all(self):
        rel = self.image()
        self.image("Brand/brand-kit/logos/clinic logo.png", brand=self.clinic)
        real, problem = S.resolve_media(self.brand, rel)
        self.assertEqual((os.path.basename(real), problem), ("loaf's crumb é.png", ""))
        self.assertEqual(S.resolve_media(self.brand, self.brand.path(*rel.split("/")))[1], "")    # absolute, but inside
        for bad in ("../stride-physio/Brand/brand-kit/logos/clinic logo.png", "..\\..\\anything.png", "/etc/hosts",
                    "C:\\Windows\\win.ini", self.clinic.path("Brand", "brand-kit", "logos", "clinic logo.png")):
            self.assertEqual(S.resolve_media(self.brand, bad), (None, "outside"), bad)
        self.assertEqual(S.resolve_media(self.brand, "Output/visuals/gone.png"), (None, "missing"))
        self.assertEqual(S.resolve_media(self.brand, "brand-master.json"), (None, "type"))
        self.assertEqual(S.resolve_media(self.brand, ""), (None, "missing"))

    def test_approve_edit_and_conflict_through_the_store(self):
        path = self.batch([self.post("a")])
        store = S.BatchStore("maple-and-main", [path])
        shown = store.one("a")
        self.assertEqual(store.approve("a", shown["rev"], shown["content_sha"])["status"], "approved")
        with self.assertRaises(S.Refusal) as cm:
            store.edit("a", shown["rev"], text="Stale.")                      # the page still holds the old rev
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(store.edit("a", 1, text="We bake at four in the morning.")["status"], "lint_pass")
        self.assertEqual(self.on_disk(path, "a").approved_text_sha, "")

    def test_a_damaged_batch_and_a_damaged_history_line_are_survivable(self):
        path = self.batch([self.post("a")])
        with open(S.history_path(path), "w", encoding="utf-8") as f:
            f.write('{"post_id": "a", "action": "seen", "actor": "review-page", "content_sha": "x"}\n{torn line')
        self.assertEqual(len(S.read_history(path)), 1)
        broken = self.brand.path("Output", "batches", "broken.json")
        Path(broken).write_text("{not json", encoding="utf-8")
        with self.assertRaises(S.Refusal) as cm:
            S.BatchStore(self.brand, [broken])
        self.assertIn("damaged", str(cm.exception))


# ============================================================================= the page file itself
class _Outline(HTMLParser):
    VOID = {"meta", "link", "br", "hr", "img", "input", "source", "col", "area", "base", "wbr"}

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.stack, self.problems, self.ids, self.tags, self.attrs_of = [], [], [], [], {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if a.get("id"):
            self.ids.append(a["id"])
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append("</%s> closes %s" % (tag, self.stack[-1] if self.stack else "nothing"))
        else:
            self.stack.pop()


class TestThePageFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        cls.outline = _Outline()
        cls.outline.feed(cls.html)

    def test_it_asks_the_internet_for_nothing(self):
        """No web address anywhere in the file, in code or in comments, with one exception: the SVG
        format's own name inside the icon that is drawn in the page. That string is an identifier
        the browser needs to draw an SVG; nothing is ever fetched from it."""
        rest = self.html.replace(SVG_NAMESPACE, "")
        self.assertEqual(re.findall(r"https?://\S*", rest, flags=re.I), [])
        self.assertEqual(re.findall(r"""(?:src|href)\s*=\s*["']?//""", rest), [])          # no //host shortcuts either
        self.assertLessEqual(self.html.count(SVG_NAMESPACE), 1)

    def test_everything_is_inline_in_the_one_file(self):
        for tag, a in self.outline.tags:
            if tag == "script":
                self.assertNotIn("src", a)
            if tag == "link":
                self.assertEqual(a.get("rel"), "icon")
                self.assertTrue(a["href"].startswith("data:image/svg+xml,"))
            self.assertNotIn(tag, ("iframe", "object", "embed"))
        self.assertNotIn("@import", self.html)
        self.assertNotIn("@font-face", self.html)
        self.assertEqual(re.findall(r"url\(", self.html), [])
        self.assertIn("system-ui", self.html)

    def test_it_is_light_only_with_a_white_ground_and_near_black_ink(self):
        self.assertNotIn("prefers-color-scheme", self.html)
        self.assertNotIn("data-theme", self.html)
        self.assertIn("color-scheme: light", self.html)
        self.assertRegex(self.html, r"--ground:\s*#ffffff")
        self.assertRegex(self.html, r"--ink:\s*#111111")
        self.assertRegex(self.html, r"body\s*\{[^}]*background:\s*var\(--ground\)")

    def test_the_structure_is_sound_and_the_basics_of_access_are_there(self):
        o = self.outline
        self.assertEqual(o.problems, [])
        self.assertEqual(o.stack, [])
        self.assertEqual(sorted(i for i in set(o.ids) if o.ids.count(i) > 1), [])
        tags = [t for t, _a in o.tags]
        self.assertEqual(dict(o.tags)["html"].get("lang"), "en")
        self.assertIn(("meta", {"name": "viewport", "content": "width=device-width, initial-scale=1"}), o.tags)
        self.assertEqual(self.html.count("<title>Social Media Factory review</title>"), 1)
        for landmark in ("header", "nav", "main"):
            self.assertEqual(tags.count(landmark), 1, landmark)
        self.assertEqual(tags.count("h1"), 1)
        for tag, a in o.tags:
            if tag == "button":
                self.assertEqual(a.get("type"), "button")
            if tag == "dialog":
                self.assertIn(a.get("aria-labelledby"), o.ids)
            if tag == "nav":
                self.assertTrue(a.get("aria-label"))
        self.assertIn("aria-live", self.html)
        self.assertIn("@media (max-width: 560px)", self.html)                 # a phone layout exists
        self.assertIn("prefers-reduced-motion", self.html)

    def test_post_text_is_never_turned_into_html(self):
        script = self.html.split("<script>")[1]
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)
        self.assertNotIn("document.write", script)
        self.assertNotIn("eval(", script)

    def test_it_is_neutral_about_whose_posts_these_are(self):
        self.assertNotIn("/asset/", self.html)
        self.assertNotIn("logo", self.html.lower().replace("name or logo", ""))


# ============================================================================= where a picture came from
class TestTheReviewPageSaysWhenAPictureIsStockOrGenerated(ReviewCase):
    def test_a_stock_photo_and_a_drawing_with_a_generated_image_inside_are_labelled_and_own_photos_are_not(self):
        own = self.image("Output/visuals/own loaf.png")
        stock = self.image("Brand/brand-kit/photos/stock/loaf.png")
        with open(self.brand.path(*stock.split("/")) + ".source.json", "w", encoding="utf-8") as f:
            json.dump({"source": "stock", "from": "https://unsplash.com/photos/x"}, f)
        drawn = self.image("Output/visuals/set/set-01-cover.png")
        with open(self.brand.path("Output", "visuals", "set", "render-report.json"), "w", encoding="utf-8") as f:
            json.dump({"images": [{"file": "set-01-cover.png", "uses": [{"image": "x", "source": "generated"}]}]}, f)
        self.assertEqual(S.picture_origins(self.brand.path(*own.split("/"))), [])
        self.assertEqual(S.picture_origins(self.brand.path(*stock.split("/"))), ["stock photo"])
        self.assertEqual(S.picture_origins(self.brand.path(*drawn.split("/"))), ["generated image"])
        self.assertIn("origins", PAGE.read_text(encoding="utf-8"))                # the page shows it

    @needs_flask
    def test_the_label_reaches_the_page_as_words_only(self):
        stock = self.image("Brand/brand-kit/photos/stock/loaf.png")
        with open(self.brand.path(*stock.split("/")) + ".source.json", "w", encoding="utf-8") as f:
            json.dump({"source": "stock", "from": "https://unsplash.com/photos/x"}, f)
        path = self.batch([self.post("ig", platform="instagram", media_paths=[stock])])
        shown = self.shown(self.client([path]), "ig")
        self.assertEqual(shown["media"][0]["origins"], ["stock photo"])
        self.assertNotIn(self.tmp.name, json.dumps(shown))                        # never where the file is


if __name__ == "__main__":
    unittest.main(verbosity=2)
