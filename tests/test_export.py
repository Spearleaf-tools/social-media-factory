"""Ready-to-post folder tests: only what a person approved gets out, once, under names every computer accepts.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                # noqa: E402
from smf.studio import export as X                                    # noqa: E402
from smf.studio import posts as P                                     # noqa: E402
from smf.studio import review_cli                                     # noqa: E402
from smf.studio.review import store as S                              # noqa: E402
from tests.test_review import CLEAN, ReviewCase, png_bytes            # noqa: E402

RUN = "2026-10-04"
FORBIDDEN = set('<>:"/\\|?*')
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def windows_safe(name):
    return (not (set(name) & FORBIDDEN) and not any(ord(ch) < 32 for ch in name) and name == name.rstrip(" .")
            and name == name.lstrip(" ") and 0 < len(name) < 120 and name.split(".")[0].upper() not in RESERVED)


class ExportCase(ReviewCase):
    def approved(self, pid, **kw):
        """A post a person approved: the stamp matches exactly what it says."""
        post = self.post(pid, **kw)
        post.status = "approved"
        post.approved_at = "2026-10-03T10:00:00Z"
        post.approved_text_sha = P.approval_sha(post)
        return post

    def save(self, posts, name="week 1's batch é.json"):
        """Save as they are (no re-check), so a test can put a batch in any state it likes."""
        path = self.brand.path("Output", "batches", name)
        P.save_batch(posts, path, {})
        return path

    def run_export(self, paths, **kw):
        return X.export_posts(self.brand, paths, run_date=RUN, **kw)

    def tree(self, folder):
        out = []
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                out.append((os.path.relpath(full, folder).replace(os.sep, "/"), Path(full).read_bytes()))
        return out


class TestWhatLandsInTheFolder(ExportCase):
    def test_layout_words_media_order_and_the_optional_files(self):
        cover = self.image("Output/visuals/cover é.png", rgb=(10, 20, 30))
        crumb = self.image("Output/visuals/crumb's close-up.png", rgb=(40, 50, 60))
        words = "Eighteen hours.  \n\nThat is the whole secret. Crème fraîche helps. 🍞\n"
        carousel = self.approved("ig-1", platform="instagram", text=words, media_paths=[crumb, cover],
                                 alt_text="A torn sourdough loaf.", first_comment="Classes open Monday.",
                                 link="maple.example/classes", scheduled_time_local="2026-10-05 06:30")
        plain = self.approved("li-1", scheduled_time_local="2026-10-06 12:00")
        path = self.save([carousel, plain])

        folder = X.export_ready_folder(self.brand, [path])
        self.assertIsInstance(folder, Path)
        self.assertEqual(folder.parent, Path(self.brand.path("Output", "ready-to-post")))
        self.assertRegex(folder.name, r"^\d{4}-\d{2}-\d{2}$")                                 # the day of the run

        ig = folder / "2026-10-05 0630 instagram person ig-1"
        self.assertEqual(sorted(os.listdir(ig)), ["1.png", "2.png", "alt-text.txt", "first-comment.txt",
                                                  "link.txt", "post.txt"])
        self.assertEqual((ig / "post.txt").read_bytes(), words.encode("utf-8"))               # exact, to the byte
        self.assertEqual((ig / "1.png").read_bytes(), png_bytes(rgb=(40, 50, 60)))            # posting order, not name order
        self.assertEqual((ig / "2.png").read_bytes(), png_bytes(rgb=(10, 20, 30)))
        self.assertEqual((ig / "alt-text.txt").read_text(encoding="utf-8"), "A torn sourdough loaf.")
        self.assertEqual((ig / "first-comment.txt").read_text(encoding="utf-8"), "Classes open Monday.")

        li = folder / "2026-10-06 1200 linkedin person li-1"
        self.assertEqual(os.listdir(li), ["post.txt"])                                        # nothing optional, nothing extra
        self.assertEqual(sorted(os.listdir(folder)), sorted([ig.name, li.name, "README.txt", "manifest.json",
                                                             "schedule.csv"]))

    def test_the_readme_is_plain_and_lists_the_posting_order_and_where_to_paste(self):
        late = self.approved("b", platform="facebook", identity="company", scheduled_time_local="2026-10-07 17:00")
        early = self.approved("a", scheduled_time_local="2026-10-05 06:30")
        unchecked = self.approved("c", platform="twitter", sourcing="unverified", scheduled_time_local="2026-10-06 10:00")
        folder = Path(self.run_export([self.save([late, early, unchecked])]).folder)
        readme = (folder / "README.txt").read_bytes().decode("utf-8")          # as Notepad will see it
        self.assertNotIn("\n", readme.replace("\r\n", ""))
        self.assertIn("Maple & Main Bakery", readme)
        self.assertIn("Nothing here has been posted", readme)
        self.assertIn(self.brand.timezone, readme)
        order = [readme.index("2026-10-05 0630"), readme.index("2026-10-06 1000"), readme.index("2026-10-07 1700")]
        self.assertEqual(order, sorted(order))
        for network in ("LinkedIn", "Facebook", "X"):
            self.assertIn("\r\n  %s\r\n" % network, readme)
        self.assertNotIn("Instagram\r\n", readme)                                             # only the networks in this run
        self.assertIn("last researched in " + X.PASTE_NOTES_AS_OF, readme)
        self.assertIn("not checked against your own material", readme)
        self.assertNotIn(self.tmp.name, readme)                                               # no paths from this computer

    def test_tiktok_and_youtube_get_their_own_steps_not_the_general_line(self):
        clip = self.image("Output/visuals/clip-cover.png")
        tiktok = self.approved("tt-1", platform="tiktok", media_paths=[clip], first_comment="Classes open Monday.",
                               scheduled_time_local="2026-10-05 06:30")
        youtube = self.approved("yt-1", platform="youtube", media_paths=[clip], scheduled_time_local="2026-10-06 12:00")
        folder = Path(self.run_export([self.save([tiktok, youtube])]).folder)
        readme = (folder / "README.txt").read_text(encoding="utf-8")
        steps = readme[readme.index("WHERE TO PASTE"):readme.index("IF SOMETHING NEEDS TO CHANGE")]
        self.assertNotIn(X.PASTE_FALLBACK, steps)
        on_tiktok, on_youtube = steps[steps.index("  TikTok"):steps.index("  YouTube")], steps[steps.index("  YouTube"):]
        self.assertIn("Paste post.txt as the description", on_tiktok)                         # where the words go
        self.assertIn("first-comment.txt", on_tiktok)
        self.assertIn("who can view", on_tiktok)
        self.assertIn("title", on_youtube)
        self.assertIn("paste post.txt as the description", on_youtube)
        self.assertIn("thumbnail", on_youtube)
        self.assertIn("made for kids", on_youtube)

    def test_the_schedule_is_a_table_a_spreadsheet_opens_cleanly(self):
        posts = [self.approved("b", platform="facebook", identity="company", text="=SUM(A1:A9) is not a formula here.",
                               scheduled_time_local="2026-10-07 17:00"),
                 self.approved("a", text="Été. Crème brûlée on Saturday.", scheduled_time_local="2026-10-05 06:30")]
        folder = Path(self.run_export([self.save(posts)]).folder)
        raw = (folder / "schedule.csv").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))                                      # so Excel reads the accents
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual([r["post_id"] for r in rows], ["a", "b"])
        self.assertEqual((rows[0]["order"], rows[0]["date"], rows[0]["time"], rows[0]["network"], rows[0]["voice"]),
                         ("1", "2026-10-05", "06:30", "LinkedIn", "Ava Lindqvist"))
        self.assertEqual(rows[0]["first_line"], "Été. Crème brûlée on Saturday.")
        self.assertEqual(rows[1]["voice"], "Maple & Main")
        self.assertTrue(rows[1]["first_line"].startswith("'="))                               # shown, never run
        self.assertEqual(rows[0]["folder"], "2026-10-05 0630 linkedin person a")

    def test_a_thread_is_numbered_tweet_by_tweet(self):
        thread = self.approved("x-1", platform="twitter", text="First, the flour.",
                               thread=["Then the water.\nWarm, not hot.", "Then you wait."],
                               scheduled_time_local="2026-10-05 10:00")
        folder = Path(self.run_export([self.save([thread])]).folder)
        text = (folder / "2026-10-05 1000 twitter person x-1" / "post.txt").read_text(encoding="utf-8")
        self.assertEqual(text, "[1/3]\nFirst, the flour.\n\n[2/3]\nThen the water.\nWarm, not hot.\n\n[3/3]\nThen you wait.\n")
        rows = list(csv.DictReader(io.StringIO((folder / "schedule.csv").read_text(encoding="utf-8-sig"))))
        self.assertEqual(rows[0]["tweets"], "3")

    def test_a_post_with_no_time_still_gets_a_folder_and_sorts_last(self):
        folder = Path(self.run_export([self.save([self.approved("later"), self.approved(
            "timed", scheduled_time_local="2026-10-05 06:30")])]).folder)
        self.assertTrue((folder / "no-date linkedin person later").is_dir())
        readme = (folder / "README.txt").read_text(encoding="utf-8")
        self.assertLess(readme.index("0630 linkedin person timed"), readme.index("no-date linkedin person later"))


class TestOnlyWhatWasApprovedGetsOut(ExportCase):
    def test_unapproved_and_voided_posts_never_reach_the_folder(self):
        good = self.approved("good")
        voided = self.approved("voided")
        voided.text = "Rewritten after the approval, by something that left the stamp in place."
        forged = self.post("forged", status="approved")                       # says approved, no stamp at all
        half = self.post("half", status="approved", approved_at="2026-10-03T10:00:00Z")
        others = [self.post("ready", status="lint_pass"), self.post("draft", status="draft"),
                  self.post("no", status="rejected"), self.post("remake", status="regen_queued")]
        path = self.save([good, voided, forged, half] + others)

        report = self.run_export([path])
        folder = Path(report.folder)
        self.assertEqual([e["post_id"] for e in report.exported], ["good"])
        self.assertEqual(sorted(r["post_id"] for r in report.refused), ["forged", "half", "voided"])
        self.assertTrue(all("changed after it was approved" in r["reason"] for r in report.refused))
        self.assertEqual(report.waiting, {"lint_pass": 1, "draft": 1, "rejected": 1, "regen_queued": 1})
        self.assertEqual([n for n in os.listdir(folder) if (folder / n).is_dir()], ["no-date linkedin person good"])
        everything = b"".join(data for _name, data in self.tree(folder))
        self.assertNotIn(b"Rewritten after the approval", everything)
        self.assertEqual([self.on_disk(path, i).status for i in ("good", "voided", "forged", "ready")],
                         ["exported", "approved", "approved", "lint_pass"])

    def test_the_same_holds_when_the_approval_came_from_the_review_page(self):
        path = self.batch([self.post("a"), self.post("b")])
        store = S.BatchStore(self.brand, [path])
        for pid in ("a", "b"):
            shown = store.one(pid)
            store.approve(pid, shown["rev"], shown["content_sha"])
        store.edit("b", store.one("b")["rev"], text="Changed my mind about this one.")       # the edit voids it
        report = self.run_export([path])
        self.assertEqual([e["post_id"] for e in report.exported], ["a"])
        self.assertEqual(report.waiting, {"lint_pass": 1})
        self.assertEqual(S.read_history(path)[-1]["actor"], "export")

    def test_an_approved_post_that_no_longer_passes_this_brands_checks_is_held_back(self):
        rel = self.image()
        breaks_rule = self.approved("rule", text="We supply Harbour Street Cafe.")
        no_image = self.approved("gone", platform="instagram", media_paths=["Output/visuals/deleted since.png"])
        theirs = self.image("Brand/brand-kit/logos/clinic logo.png", brand=self.clinic)
        leak = self.approved("leak", platform="instagram", media_paths=["../stride-physio/" + theirs])
        failed = self.approved("facts", sourcing="blocked")
        fine = self.approved("fine", platform="instagram", media_paths=[rel])
        report = self.run_export([self.save([breaks_rule, no_image, leak, failed, fine])])
        why = {r["post_id"]: r["reason"] for r in report.refused}
        self.assertEqual([e["post_id"] for e in report.exported], ["fine"])
        self.assertIn("Harbour Street Cafe", why["rule"])
        self.assertIn("not where the post says", why["gone"])
        self.assertIn("not inside this brand's folder", why["leak"])
        self.assertIn("fact check", why["facts"])
        everything = b"".join(data for _n, data in self.tree(report.folder))
        self.assertNotIn(b"Harbour", everything)

    def test_a_proof_file_that_is_not_cleared_never_reaches_the_folder(self):
        from smf.studio import proof
        private = self.image("Inputs/Proof/a regular's note.png", rgb=(9, 9, 9))
        proof.add(self.brand, "testimonial", "A note from a regular", source="a card left at the counter",
                  file_path=self.brand.path(*private.split("/")), may_publish="no")
        unlisted = self.image("Inputs/Proof/nobody listed this.png", rgb=(8, 8, 8))
        posts = [self.approved("private", platform="instagram", media_paths=[private]),
                 self.approved("unlisted", platform="instagram", media_paths=[unlisted]),
                 self.approved("fine", platform="instagram", media_paths=[self.image()])]
        report = self.run_export([self.save(posts)])
        self.assertEqual([e["post_id"] for e in report.exported], ["fine"])
        why = {r["post_id"]: r["reason"] for r in report.refused}
        self.assertIn("do not publish", why["private"])
        self.assertIn("no proof item", why["unlisted"])
        copied = [data for name, data in self.tree(report.folder) if name.endswith(".png")]
        self.assertEqual(copied, [png_bytes()])

    def test_with_nothing_approved_it_says_so_and_makes_no_folder(self):
        path = self.save([self.post("a", status="lint_pass")])
        with self.assertRaises(X.ExportError) as cm:
            self.run_export([path])
        self.assertIn("no approved posts", str(cm.exception))
        self.assertEqual(os.listdir(self.brand.path("Output", "ready-to-post")), [])
        voided = self.approved("v")
        voided.text += " changed"
        with self.assertRaises(X.ExportError) as cm:
            self.run_export([self.save([voided], "second.json")])
        self.assertIn("changed after it was approved", str(cm.exception))

    def test_only_approved_posts_can_be_asked_for(self):
        path = self.save([self.post("a", status="lint_pass")])
        for status in ("lint_pass", "draft", "rejected", "", None):
            with self.assertRaises(X.ExportError):
                X.export_ready_folder(self.brand, [path], only_status=status)

    def test_the_brand_is_always_named_and_another_brands_batch_is_refused(self):
        path = self.save([self.approved("a")])
        with self.assertRaises(brands.BrandError):
            X.export_ready_folder(None, [path])
        with self.assertRaises(brands.BrandError):
            X.export_ready_folder("no-such-brand", [path])
        with self.assertRaises(S.Refusal) as cm:
            X.export_ready_folder(self.clinic, [path])
        self.assertIn("belongs to maple-and-main", str(cm.exception))
        self.assertEqual(os.listdir(self.clinic.path("Output", "ready-to-post")), [])
        self.assertEqual(self.on_disk(path, "a").status, "approved")

    def test_a_check_writes_nothing_at_all(self):
        path = self.save([self.approved("a")])
        before = Path(path).read_bytes()
        report = self.run_export([path], check_only=True)
        self.assertEqual([e["post_id"] for e in report.exported], ["a"])
        self.assertEqual(os.listdir(self.brand.path("Output", "ready-to-post")), [])
        self.assertEqual(Path(path).read_bytes(), before)


class TestSafeToRunTwice(ExportCase):
    def test_posts_are_marked_exported_in_one_atomic_write(self):
        path = self.save([self.approved("a"), self.approved("b"), self.post("c", status="lint_pass")])
        self.run_export([path])
        a = self.on_disk(path, "a")
        self.assertEqual((a.status, a.rev), ("exported", 1))
        self.assertTrue(P.approval_is_current(a))                                             # the stamp survives
        self.assertEqual(self.on_disk(path, "c").rev, 0)
        self.assertEqual([f for f in os.listdir(os.path.dirname(path)) if f.startswith(".tmp-")], [])
        self.assertTrue(os.path.isfile(path + ".bak"))

    def test_a_second_run_copies_nothing_and_reports_what_was_already_there(self):
        rel = self.image()
        path = self.save([self.approved("a", platform="instagram", media_paths=[rel],
                                        scheduled_time_local="2026-10-05 06:30"), self.approved("b")])
        first = self.run_export([path])
        before = self.tree(first.folder)
        batch_before = Path(path).read_bytes()

        second = self.run_export([path])
        self.assertEqual(second.exported, [])
        self.assertEqual(sorted(a["post_id"] for a in second.already), ["a", "b"])
        self.assertTrue(all(os.path.isdir(a["folder"]) for a in second.already))
        self.assertEqual(second.folder, first.folder)
        self.assertEqual(self.tree(first.folder), before)
        self.assertEqual(Path(path).read_bytes(), batch_before)
        self.assertEqual(X.export_ready_folder(self.brand, [path]), Path(first.folder))       # and on another day

    def test_a_newly_approved_post_joins_the_same_days_folder(self):
        path = self.save([self.approved("a", scheduled_time_local="2026-10-05 06:30")])
        first = self.run_export([path])
        posts, meta = P.load_batch(path, self.brand.id)
        posts.append(self.approved("b", scheduled_time_local="2026-10-04 06:30"))
        P.save_batch(posts, path, meta)
        second = self.run_export([path])
        self.assertEqual(([e["post_id"] for e in second.exported], [a["post_id"] for a in second.already]), (["b"], ["a"]))
        self.assertEqual(second.folder, first.folder)
        readme = (Path(first.folder) / "README.txt").read_text(encoding="utf-8")
        self.assertLess(readme.index("person b"), readme.index("person a"))                   # the list is re-made in order
        manifest = json.loads((Path(first.folder) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([e["post_id"] for e in manifest["posts"]], ["a", "b"])

    def test_a_run_that_stopped_before_marking_is_finished_by_the_next_one(self):
        path = self.save([self.approved("a")])
        first = self.run_export([path])
        before = self.tree(first.folder)
        posts, meta = P.load_batch(path, self.brand.id)                       # as if the batch was never marked
        posts[0].status = "approved"
        P.save_batch(posts, path, meta)
        second = self.run_export([path])
        self.assertEqual((second.exported, [a["post_id"] for a in second.already]), ([], ["a"]))
        self.assertEqual(self.on_disk(path, "a").status, "exported")
        self.assertEqual(self.tree(first.folder), before)

    def test_a_finished_folder_that_was_never_listed_is_adopted_not_duplicated(self):
        path = self.save([self.approved("a")])
        first = self.run_export([path])
        os.remove(os.path.join(first.folder, "manifest.json"))                # as if the run stopped right after the copy
        posts, meta = P.load_batch(path, self.brand.id)
        posts[0].status = "approved"
        P.save_batch(posts, path, meta)
        second = self.run_export([path])
        self.assertEqual((second.exported, [a["post_id"] for a in second.already]), ([], ["a"]))
        self.assertEqual([n for n in os.listdir(first.folder) if os.path.isdir(os.path.join(first.folder, n))],
                         ["no-date linkedin person a"])

    def test_words_that_changed_after_an_export_never_overwrite_the_folder(self):
        path = self.save([self.approved("a")])
        first = self.run_export([path])
        again = self.approved("a", text="A second version, approved later.")
        P.save_batch([again], path, {})
        with self.assertRaises(X.ExportError) as cm:
            self.run_export([path])
        self.assertIn("exported before with different words", str(cm.exception))
        self.assertEqual(self.on_disk(path, "a").status, "approved")
        self.assertEqual((Path(first.folder) / "no-date linkedin person a" / "post.txt").read_text(encoding="utf-8"), CLEAN)

    def test_leftovers_of_a_stopped_run_are_cleared_and_nothing_else_is_touched(self):
        run_dir = self.brand.path("Output", "ready-to-post", RUN)
        os.makedirs(os.path.join(run_dir, ".tmp-export-half made"))
        keep = os.path.join(run_dir, "my own notes.txt")
        Path(keep).write_text("remember the flour order", encoding="utf-8")
        self.run_export([self.save([self.approved("a")])])
        self.assertEqual([n for n in os.listdir(run_dir) if n.startswith(".tmp-")], [])
        self.assertEqual(Path(keep).read_text(encoding="utf-8"), "remember the flour order")


class TestNamesEveryComputerAccepts(ExportCase):
    HOSTILE_IDS = ['a/b:c*?"<>|', "CON", "nul.txt", "trailing dot. ", "  leading", "..", "x" * 300, "x" * 299 + "y",
                   "Café déjà vu", "tab\there", "A1", "a1", "quote's", "week 1\\day 2"]

    def test_safe_name_on_its_own(self):
        for text in self.HOSTILE_IDS + ["", None, ".", "LPT9", "com1", "COM1.png", "...", " . "]:
            self.assertTrue(windows_safe(X.safe_name(text)), repr(text))
        self.assertEqual(X.safe_name("Café déjà vu"), "Café déjà vu")                          # accents are kept
        self.assertEqual(X.safe_name("café"), "café")                                   # and spelled one way

    def test_every_name_in_the_tree_is_safe_and_no_two_posts_collide(self):
        rel = self.image("Output/visuals/UPPER case.PNG")
        posts = [self.approved(pid, platform="instagram", media_paths=[rel], first_comment="x",
                               scheduled_time_local="2026-10-05 06:30") for pid in self.HOSTILE_IDS]
        posts.append(self.approved("odd-platform", platform='tik/tok: "live"', scheduled_time_local="not a time"))
        report = self.run_export([self.save(posts)])
        self.assertEqual(report.refused, [])
        self.assertEqual(len(report.exported), len(posts))
        folders = [n for n in os.listdir(report.folder) if os.path.isdir(os.path.join(report.folder, n))]
        self.assertEqual(len({n.lower() for n in folders}), len(posts))                       # "A1" and "a1" stay apart
        for root, dirs, files in os.walk(report.folder):
            for name in dirs + files:
                self.assertTrue(windows_safe(name), name)
        self.assertTrue(all(os.path.isfile(os.path.join(report.folder, n, "1.png")) for n in folders
                            if "instagram" in n))                                             # the extension is tidied too
        self.assertNotIn("..", [p for n in folders for p in n.split(" ")])

    def test_it_survives_a_factory_folder_with_spaces_an_apostrophe_and_an_accent(self):
        self.assertIn("' é", self.tmp.name)
        report = self.run_export([self.save([self.approved("a")], "lundi's fournée é.json")])
        self.assertTrue(os.path.isfile(os.path.join(report.exported[0]["folder"], "post.txt")))


class TestTheTwoVerbs(ExportCase):
    def say(self, fn, args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = fn(args)
        return code, out.getvalue()

    def test_export_reports_in_plain_words(self):
        voided = self.approved("voided")
        voided.text += " changed"
        self.save([self.approved("a"), voided, self.post("c", status="lint_pass")])
        code, said = self.say(review_cli.cli_export, ["--brand", "maple-and-main"])
        self.assertEqual(code, 0)
        self.assertIn("1 post written", said)
        self.assertIn("voided: it was changed after it was approved", said)
        self.assertIn("1 post not approved yet", said)
        self.assertIn("README.txt", said)
        self.assertNotIn("Traceback", said)
        code, said = self.say(review_cli.cli_export, ["--brand", "maple-and-main"])
        self.assertEqual(code, 0)
        self.assertIn("No new posts were written", said)
        self.assertIn("1 already exported earlier", said)

    def test_check_says_what_would_happen_and_writes_nothing(self):
        path = self.save([self.approved("a")])
        code, said = self.say(review_cli.cli_export, ["--brand", "maple-and-main", "--check"])
        self.assertEqual(code, 0)
        self.assertIn("would be written", said)
        self.assertEqual(os.listdir(self.brand.path("Output", "ready-to-post")), [])
        self.assertEqual(self.on_disk(path, "a").status, "approved")

    def test_both_verbs_need_a_brand_and_say_so_plainly(self):
        self.save([self.approved("a")])
        for verb in (review_cli.cli_review, review_cli.cli_export):
            code, said = self.say(verb, [])
            self.assertEqual(code, 1)
            self.assertIn("no brand was named", said)
            self.assertIn("maple-and-main", said)                                             # the brands that exist
            code, said = self.say(verb, ["--brand", "harbour-street"])
            self.assertEqual(code, 1)
            self.assertIn("there is no brand called", said)
            code, said = self.say(verb, ["--brand", "maple-and-main", "--sideways"])
            self.assertEqual(code, 1)
            self.assertNotIn("usage:", said)

    def test_a_brand_with_no_batches_is_told_what_to_do_first(self):
        for verb in (review_cli.cli_review, review_cli.cli_export):
            code, said = self.say(verb, ["--brand", "stride-physio", "--no-browser"] if verb is review_cli.cli_review
                                  else ["--brand", "stride-physio"])
            self.assertEqual(code, 1)
            self.assertIn("no batches yet", said)

    def test_the_newest_batch_is_found_and_side_files_are_not_batches(self):
        old = self.save([self.approved("a")], "monday's.json")
        new = self.save([self.approved("b")], "tuesday é.json")
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_800_000_000, 1_800_000_000))
        folder = os.path.dirname(new)
        for side in ("tuesday é.history.jsonl", "tuesday é.json.bak", ".hidden.json"):
            Path(folder, side).write_text("{}", encoding="utf-8")
            os.utime(os.path.join(folder, side), (1_900_000_000, 1_900_000_000))
        self.assertEqual(review_cli.newest_batch(self.brand), new)
        self.assertEqual(review_cli.all_batches(self.brand), [old, new])

    def test_a_bare_file_name_or_a_pattern_is_looked_for_in_the_brands_own_batches(self):
        a = self.save([self.approved("a")], "monday's.json")
        b = self.save([self.approved("b")], "tuesday é.json")
        self.assertEqual(review_cli.resolve_batches(self.brand, ["monday's.json"]), [os.path.abspath(a)])
        self.assertEqual(review_cli.resolve_batches(self.brand, ["*day*.json", a]), [os.path.abspath(a), os.path.abspath(b)])
        with self.assertRaises(review_cli.StudioError) as cm:
            review_cli.resolve_batches(self.brand, ["friday.json"])
        self.assertIn("Output/batches", str(cm.exception))

    def test_review_is_handed_the_brand_the_batches_and_the_browser_choice(self):
        path = self.save([self.approved("a")], "monday's.json")
        calls = []

        class FakeServer(object):
            @staticmethod
            def serve(brand, paths, port=None, open_browser=True):
                calls.append((brand.id, paths, port, open_browser))
                return 0

        import smf.studio.review as package
        had = sys.modules.get("smf.studio.review.server")
        sys.modules["smf.studio.review.server"] = FakeServer
        had_attr = getattr(package, "server", None)
        package.server = FakeServer
        try:
            self.assertEqual(self.say(review_cli.cli_review, ["--brand", "maple-and-main", "--no-browser"])[0], 0)
            self.assertEqual(self.say(review_cli.cli_review, ["--brand", "maple-and-main", "monday's.json",
                                                              "--port", "9001"])[0], 0)
        finally:
            if had is None:
                sys.modules.pop("smf.studio.review.server", None)
            else:
                sys.modules["smf.studio.review.server"] = had
            if had_attr is None:
                delattr(package, "server")
            else:
                package.server = had_attr
        self.assertEqual(calls, [("maple-and-main", [path], None, False),
                                 ("maple-and-main", [os.path.abspath(path)], 9001, True)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
