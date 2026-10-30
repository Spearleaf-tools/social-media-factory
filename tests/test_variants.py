"""Tests for versions of a clip, the text drawn on them, the words under them, and delivery.

    python -m unittest discover -s tests -t . -v

What is proved here: a plan is the same every time and its versions really differ; mirroring is
off until a brand AND a person both say otherwise; a clip on HOLD cannot be made for posting
without sign-off and cannot be made at all without its disclaimer; captions never run off the
screen or straddle a cut; a description with an invented number, an interviewer's words, a service
nobody offers or another version's words is stopped; one brand's rules never leak into another's;
delivery names files the way posting expects and never overwrites anything.

Nothing uses the network or a key. The recordings are invented: a baker interviewed in her shop
and a physiotherapist talking to a presenter. Tests that need the video programs are skipped,
with the reason, when the video tools are not installed; when they are, the tests make their own
media (a test pattern and a tone) inside a folder whose name has a space, an apostrophe and an
accent. No media is ever kept.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                    # noqa: E402
from smf.brands import BrandError, contrast                               # noqa: E402
from smf.studio import grounding                                          # noqa: E402
from smf.video import common, cutlist, transcribe                         # noqa: E402
from smf.video import deliver as DL                                       # noqa: E402
from smf.video import describe as D                                       # noqa: E402
from smf.video import overlays as O                                       # noqa: E402
from smf.video import variants as V                                       # noqa: E402
from smf.video import variants_cli, verify as VF                          # noqa: E402
from smf.video.common import Transcript, VideoError                       # noqa: E402
from tests import test_video as TV                                        # noqa: E402

def _has(module):
    try:
        __import__(module)
        return True
    except Exception:
        return False


draws = unittest.skipUnless(_has("PIL") and _has("numpy"), "the imaging library is not installed, so nothing can be "
                                                           "drawn (python factory.py setup)")

REC = "2026-09-12 Ava's caf\u00e9 talk"
AVA, JONAH = TV.AVA, TV.HOST
TOMAS, MINA = "Tomas Okafor", "Mina Castellane"
DISCLAIMER = "General education, not personal medical advice."
OFFERS = [{"id": "weekend-class", "name": "Weekend sourdough class", "what": "A three hour Saturday class for beginners.",
           "call_to_action": "Book a Saturday class at the counter."}]

CLINIC_TALK = [
    (MINA, 0.8, "So what should a runner with sore knees actually do first?"),
    (TOMAS, 1.0, "Most knee pain in runners over thirty starts at the hip. We change the load first, and the knee "
                 "usually settles."),
    (MINA, 1.0, "And is it true that rest fixes 8 out of 10 sore knees?"),
    (TOMAS, 1.0, "Shockwave is something we offer when loading alone is not enough."),
]


def span(t, first, last, voice, lead=0.3, tail=0.5):
    return [round(TV.when(t, first, 0, voice)[0] - lead, 3), round(TV.when(t, last, 0, voice)[1] + tail, 3)]


class VariantCase(TV.VideoCase):
    """Two brands, each with a transcribed recording and a fine-cut report. The clip files are
    empty stand-ins unless a test makes real ones."""

    def setUp(self):
        super().setUp()
        self.bakery = brands.update("maple-and-main", {"offers": OFFERS})
        self.t_bakery = self.record(self.bakery, TV.lay_out(TV.INTERVIEW))
        self.t_clinic = self.record(self.clinic, TV.lay_out(CLINIC_TALK))
        t = self.t_bakery
        self.bakery_clips = [
            self.clip("A1", "A", "Why loaves come out dense", "Your loaf is not broken", "SHIP",
                      [span(t, "Most dense loaves", "never gets there.", AVA), span(t, "I tell every class", "not the clock.", AVA)]),
            self.clip("B1", "B", "Cheap flour is not the problem", "Flour is not the problem", "SHIP",
                      [span(t, "We go through", "not the problem.", AVA)])]
        t = self.t_clinic
        self.clinic_clips = [
            self.clip("A1", "A", "Knee pain starts at the hip", "Knee pain starts at the hip", "SHIP",
                      [span(t, "Most knee pain", "usually settles.", TOMAS)], third="Tomas Okafor"),
            self.clip("B1", "B", "When loading is not enough", "When loading is not enough", "HOLD",
                      [span(t, "Shockwave is", "not enough.", TOMAS)], third="Tomas Okafor")]
        self.write_report(self.bakery, self.bakery_clips)
        self.write_report(self.clinic, self.clinic_clips)

    # fixtures ------------------------------------------------------------------------------
    def record(self, brand, words):
        transcribe.write_transcript(brand, REC, words=words, source={"media": "talk.mp4", "made_by": "a test"})
        return Transcript.load(brand, REC)

    @staticmethod
    def clip(cid, body, title, text, gate_, pieces, third="Ava Lindqvist, Head Baker", signed=""):
        return {"id": cid, "file": "%s-%s.mp4" % (cid, common.slug(title)), "body": body, "hook": 1, "title": title,
                "hook_text": title, "on_screen_text": text, "lower_third": third, "gate": gate_,
                "disclaimer": DISCLAIMER if gate_ == "HOLD" else "", "sign_off_by": TOMAS if gate_ == "HOLD" else "",
                "signed_off": signed, "status": "ok", "pieces": pieces,
                "actual_duration": round(sum(b - a for a, b in pieces), 2)}

    def write_report(self, brand, clips, shape=None, cut_list=""):
        folder = common.output_dir(brand, REC, "fine")
        os.makedirs(folder, exist_ok=True)
        for c in clips:
            path = os.path.join(folder, c["file"])
            if not os.path.exists(path):
                Path(path).write_bytes(b"stand-in")
        common.write_json_atomic(os.path.join(folder, "fine-cut-report.json"), {
            "schema": 1, "kind": "fine", "brand": brand.id, "recording": REC, "source": "Inputs/Recordings/%s/talk.mp4" % REC,
            "offset": 0.0, "cut_list": cut_list, "speaker_check": "checked",
            "shape": shape or {"orientation": "horizontal", "width": 1280, "height": 720}, "clips": clips})

    def plan(self, brand=None, **kw):
        kw.setdefault("face_finder", False)
        return V.plan_variants(brand or self.bakery, REC, **kw)

    def sign_off(self, brand, body="B", who="Tomas Okafor, 14 September 2026"):
        """A cut list whose body carries a sign-off, and a report that points at it."""
        cl = cutlist.CutList(title=REC)
        cl.reference = {"recording": REC, "brand": brand.id, "cut_from": "talk.mp4",
                        "timestamps_from": "Transcriptions/transcript.json", "offset": "0"}
        cl.bodies = [cutlist.Body(key=body, title="When loading is not enough", start=1.0, end=5.0, gate="HOLD",
                                  signed_off=who)]
        path = common.output_dir(brand, REC, common.CUT_LIST_FILE)
        common.write_text_atomic(path, cutlist.write(cl))
        self.write_report(brand, self.clinic_clips, cut_list=common.locate(brand, path))

    def everything_under(self, folder):
        return sorted(os.path.relpath(os.path.join(r, n), folder) for r, _d, names in os.walk(folder) for n in names)


# ============================================================================= recipes and the plan
class TestThePlan(VariantCase):
    def test_the_same_plan_every_time_and_a_different_seed_gives_a_different_one(self):
        first = self.plan(n=3)
        again = self.plan(n=3)
        def strip(m):
            return [(c["id"], [(v["version"], v["recipe"], v["fingerprint"]) for v in c["versions"]]) for c in m["clips"]]
        self.assertEqual(strip(first), strip(again))
        picks = {tuple(v["recipe"]["id"] for v in self.plan(n=3, seed=s)["clips"][0]["versions"]) for s in "abcdefgh"}
        self.assertGreater(len(picks), 1)
        self.assertEqual([v["version"] for v in first["clips"][0]["versions"]], ["v1", "v2", "v3"])

    def test_every_two_versions_differ_on_three_dials_as_they_are_really_applied(self):
        for seed in ("", "monday", "a caf\u00e9"):
            for clip in self.plan(n=V.MAX_VERSIONS, seed=seed)["clips"]:
                recipes = [v["recipe"] for v in clip["versions"]]
                self.assertEqual(len(recipes), V.MAX_VERSIONS)
                for i, a in enumerate(recipes):
                    self.assertFalse(a["mirror"] or a["music"], a)            # switched off here, so they cannot count
                    for b in recipes[i + 1:]:
                        self.assertGreaterEqual(len(V.axes_apart(a, b)), 3, (a["id"], b["id"]))

    def test_the_library_itself_keeps_its_distance_with_every_optional_dial_off(self):
        plain = [V.effective(r) for r in V.RECIPES]
        for i, a in enumerate(plain):
            for b in plain[i + 1:]:
                self.assertGreaterEqual(len(V.axes_apart(a, b)), 3, (a["id"], b["id"]))
        close = [dict(V.RECIPES[0], id="one"), dict(V.RECIPES[0], id="two", speed=1.03, zoom=1.03)]
        with self.assertRaises(VideoError) as cm:
            V.choose_recipes(2, "seed", library=close)
        self.assertIn("Only 1 version", str(cm.exception))
        for n in (0, V.MAX_VERSIONS + 1):
            with self.assertRaises(VideoError):
                V.choose_recipes(n, "seed")

    def test_mirroring_is_off_until_the_brand_and_a_person_both_say_so(self):
        flips = lambda m: [v["recipe"]["id"] for c in m["clips"] for v in c["versions"] if v["recipe"]["mirror"]]  # noqa: E731
        self.assertTrue(any(r["mirror"] for r in V.RECIPES))                  # the dial exists; it is just not used
        self.assertEqual(flips(self.plan(n=6)), [])
        self.assertEqual(flips(self.plan(n=6, no_text_in_footage=True)), [])  # a person alone is not enough
        self.bakery = brands.update("maple-and-main", {"video": {"allow_mirror": True}})
        brand_only = self.plan(n=6)
        self.assertEqual(flips(brand_only), [])                               # the brand alone is not enough
        self.assertEqual(brand_only["mirror"], {"brand_allows": True, "a_person_said_no_text_in_picture": False, "used": False})
        self.assertTrue(flips(self.plan(n=6, no_text_in_footage=True)))
        self.assertFalse(V.effective(V.RECIPES[3], mirror_ok=False)["mirror"])
        self.assertFalse(V.mirror_allowed(self.clinic))

    def test_a_trim_only_ever_takes_silence_the_clip_report_shows(self):
        tail = next(r for r in V.RECIPES if r["trim"] == "tail")
        self.assertEqual(V.effective(tail, slack={"head": 0.3, "tail": 0.3})["trim"], "none")
        some = V.effective(tail, slack={"head": 0.0, "tail": 0.75})
        self.assertEqual((some["trim"], some["trim_seconds"]), ("tail", 0.5))
        self.assertEqual(V.effective(tail, slack={"tail": 9.0})["trim_seconds"], V.TRIM_MOST)
        words, _ = V.clip_words(self.bakery_clips[1], self.t_bakery, 0.0)
        slack = V.slack_of(words, V.planned_length(self.bakery_clips[1]))
        self.assertAlmostEqual(slack["head"], 0.3, delta=0.02)
        self.assertAlmostEqual(slack["tail"], 0.5, delta=0.02)
        for clip in self.plan(n=6)["clips"]:
            for v in clip["versions"]:
                self.assertLessEqual(v["recipe"]["trim_seconds"], 0.5 - V.TRIM_KEEP["tail"] + 0.02)

    def test_a_recipe_outside_the_natural_ranges_is_refused(self):
        for change in ({"speed": 1.25}, {"pitch": 0.9}, {"zoom": 1.4}, {"music": 0.6}, {"format": "wide"}, {"eq": "boom"}):
            with self.assertRaises(VideoError, msg=change):
                V.effective(dict(V.RECIPES[0], **change))

    def test_music_only_ever_comes_from_the_brands_own_folder(self):
        self.assertEqual(V.music_beds(self.bakery), ([], ""))
        self.assertTrue(all(v["recipe"]["music"] == 0 for c in self.plan(n=6)["clips"] for v in c["versions"]))
        folder = self.bakery.path("Brand", "music beds")
        os.makedirs(folder)
        Path(folder, "Ava's morning loop.mp3").write_bytes(b"not really music")
        Path(folder, "notes.txt").write_text("not a bed", encoding="utf-8")
        self.bakery = brands.update("maple-and-main", {"video": {"music_folder": "Brand/music beds"}})
        beds, note = V.music_beds(self.bakery)
        self.assertEqual(([os.path.basename(b) for b in beds], note), (["Ava's morning loop.mp3"], ""))
        with_music = [v["recipe"] for c in self.plan(n=6)["clips"] for v in c["versions"] if v["recipe"]["music"]]
        self.assertTrue(with_music)
        self.assertTrue(all(r["music_bed"] == "Brand/music beds/Ava's morning loop.mp3" and r["music"] <= V.MUSIC_MOST
                            for r in with_music))
        self.assertTrue(V.resolve_bed(self.bakery, with_music[0]).endswith("loop.mp3"))
        self.assertEqual(V.resolve_bed(self.bakery, dict(with_music[0], music_bed="../stride-physio/x.mp3")), "")
        for bad in ("../stride-physio/Brand", os.path.join(brands.CLIENT_DIR, "stride-physio", "Brand")):
            b = brands.update("maple-and-main", {"video": {"music_folder": bad}})
            beds, note = V.music_beds(b)
            self.assertEqual(beds, [])
            self.assertTrue(note)

    def test_the_manifest_is_written_before_anything_is_made_and_carries_what_is_known_now(self):
        m = self.plan(self.clinic, n=2)
        saved = json.loads(Path(V.manifest_path(self.clinic, REC)).read_text(encoding="utf-8"))
        self.assertEqual(saved["clips"][1]["id"], m["clips"][1]["id"])
        hold = saved["clips"][1]
        self.assertEqual((hold["gate"], hold["needs_disclaimer"], hold["disclaimer"], hold["sign_off_by"], hold["signed_off"],
                          hold["may_be_delivered"]), ("HOLD", True, DISCLAIMER, TOMAS, "", False))
        self.assertEqual(hold["report_entry"]["pieces"], self.clinic_clips[1]["pieces"])
        self.assertEqual(hold["source"]["file"], "Output/video/%s/fine/B1-when-loading-is-not-enough.mp4" % REC)
        self.assertEqual(hold["versions"][0]["output"], "Output/video/%s/variants/B1-when-loading-is-not-enough__v1.mp4" % REC)
        self.assertIn("/previews/", hold["versions"][0]["preview_output"])
        self.assertTrue(hold["versions"][0]["preview_output"].endswith("__v1.preview.mp4"))
        ship = saved["clips"][0]
        self.assertEqual((ship["gate"], ship["needs_disclaimer"], ship["disclaimer"], ship["may_be_delivered"]),
                         ("SHIP", False, "", True))
        made = [n for n in self.everything_under(V.variants_dir(self.clinic, REC)) if n.endswith(".mp4")]
        self.assertEqual(made, [])
        self.assertIn("centre", " ".join(saved["clips"][0]["notes"]))         # horizontal, and nobody looked for a face

    def test_planning_one_clip_again_keeps_the_others(self):
        self.plan(n=2)
        again = self.plan(n=3, clip_ids=["b1"])
        self.assertEqual([c["id"] for c in again["clips"]], ["B1"])
        saved = json.loads(Path(V.manifest_path(self.bakery, REC)).read_text(encoding="utf-8"))
        self.assertEqual([(c["id"], len(c["versions"])) for c in saved["clips"]], [("A1", 2), ("B1", 3)])
        with self.assertRaises(VideoError) as cm:
            self.plan(clip_ids=["Z9"])
        self.assertIn("A1, B1", str(cm.exception))

    def test_words_on_screen_that_the_brands_rules_would_stop_make_the_clip_stricter_never_looser(self):
        clips = [dict(self.clinic_clips[0], on_screen_text="Shockwave for sore knees"),
                 dict(self.clinic_clips[0], id="C1", on_screen_text="This cures runners knee")]
        self.write_report(self.clinic, clips)
        m = self.plan(self.clinic)
        self.assertEqual([(c["id"], c["gate"], c["disclaimer"]) for c in m["clips"]], [("A1", "HOLD", DISCLAIMER)])
        self.assertEqual(m["refused"][0]["id"], "C1")
        self.assertIn("never publishes", m["refused"][0]["why"])

    def test_on_screen_text_is_three_to_seven_words_or_it_is_left_off(self):
        clips = [dict(self.bakery_clips[0], on_screen_text="Dense loaf"),
                 dict(self.bakery_clips[1], on_screen_text="One two three four five six seven eight")]
        self.write_report(self.bakery, clips)
        m = self.plan()
        self.assertEqual([c["on_screen_text"] for c in m["clips"]], ["", ""])
        self.assertTrue(all(any("3 to 7" in n for n in c["notes"]) for c in m["clips"]))

    def test_a_person_can_say_where_the_speaker_is(self):
        m = self.plan(centre_on={"a1": 0.8})
        framing = m["clips"][0]["framing"]
        self.assertEqual((framing["found"], framing["x"], framing["by"]), (True, 0.8, "a person"))
        self.assertFalse(any("centre" in n for n in m["clips"][0]["notes"]))
        with self.assertRaises(VideoError):
            self.plan(centre_on={"A1": 1.8})


class TestTheRightBrandsFolderAndNoOther(VariantCase):
    def test_no_brand_is_an_error_and_a_recording_name_cannot_climb_out(self):
        for nothing in (None, "", "no-such-brand"):
            with self.assertRaises(BrandError):
                V.plan_variants(nothing, REC)
            with self.assertRaises(BrandError):
                D.check_descriptions(nothing, REC)
        for bad in ("../stride-physio", "a/b", "..", ".hidden", ""):
            with self.assertRaises(VideoError):
                V.plan_variants(self.bakery, bad, face_finder=False)

    def test_everything_one_brand_makes_stays_in_its_own_folder_whatever_the_folder_is_called(self):
        self.assertIn("'", self.bakery.home)
        self.assertIn("\u00e9", REC)
        before = self.everything_under(self.clinic.home)
        m = self.plan(n=2)
        _c, page = D.write_contract(self.bakery, REC, "A1")
        D.save_store(self.bakery, REC, [{"clip": "A1", "version": "v1", "platform": "tiktok", "text": "Watch the dough, not the clock."}])
        D.check_descriptions(self.bakery, REC)
        self.assertEqual(self.everything_under(self.clinic.home), before)
        home = os.path.realpath(self.bakery.home)
        for path in (V.manifest_path(self.bakery, REC), page, D.store_path(self.bakery, REC)):
            self.assertTrue(os.path.realpath(path).startswith(home + os.sep), path)
        for clip in m["clips"]:
            for v in clip["versions"]:
                for written in (v["output"], v["preview_output"], clip["source"]["file"]):
                    self.assertFalse(os.path.isabs(written) or ".." in written.split("/"), written)

    def test_a_plan_or_a_report_that_belongs_to_another_brand_is_refused(self):
        self.plan()
        os.makedirs(V.variants_dir(self.clinic, REC), exist_ok=True)
        Path(V.manifest_path(self.clinic, REC)).write_text(Path(V.manifest_path(self.bakery, REC)).read_text(encoding="utf-8"),
                                                          encoding="utf-8")
        with self.assertRaises(VideoError) as cm:
            V.load_manifest(self.clinic, REC)
        self.assertIn("belongs to 'maple-and-main'", str(cm.exception))
        theirs = os.path.join(common.output_dir(self.bakery, REC, "fine"), "fine-cut-report.json")
        mine = os.path.join(common.output_dir(self.clinic, REC, "fine"), "fine-cut-report.json")
        Path(mine).write_text(Path(theirs).read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(VideoError):
            self.plan(self.clinic)

    def test_each_brand_gets_its_own_colours_and_there_is_no_look_without_a_brand(self):
        a, b = O.look_for(self.bakery), O.look_for(self.clinic)
        self.assertNotEqual((a.card_bg, a.tag_bg), (b.card_bg, b.tag_bg))
        self.assertEqual(a.card_bg.upper(), "#2B1D14")                        # the bakery's own headline colour
        with self.assertRaises(BrandError):
            O.look_for(None)
        for path in a.faces.paths.values():                                   # fonts that ship with the Factory, nothing from the computer
            self.assertTrue(os.path.realpath(path).startswith(os.path.realpath(str(O.KIT.FONTS_DIR))), path)


# ============================================================================= a clip on HOLD
class TestAClipOnHold(VariantCase):
    def setUp(self):
        super().setUp()
        self.scratch = tempfile.mkdtemp(prefix="overlays ' \u00e9 ", dir=self.tmp.name)
        self.look = O.look_for(self.clinic)

    def test_it_cannot_be_planned_without_a_disclaimer_to_show(self):
        self.clinic = brands.update("stride-physio", {"compliance": {"disclaimer": ""}})
        self.write_report(self.clinic, [dict(self.clinic_clips[1], disclaimer="")])
        with self.assertRaises(VideoError) as cm:
            self.plan(self.clinic)
        self.assertIn("no disclaimer written", str(cm.exception))
        self.assertFalse(os.path.exists(V.manifest_path(self.clinic, REC)))

    @draws
    def test_its_overlays_cannot_be_built_without_the_band_in_either_format(self):
        for fmt in O.FORMATS:
            for missing in ("", "   ", None):
                with self.assertRaises(O.OverlayError) as cm:
                    O.compose(self.look, fmt, self.scratch, on_screen_text="Knee pain starts at the hip",
                              disclaimer=missing, need_disclaimer=True, duration=8.0)
                self.assertIn("disclaimer", str(cm.exception))
            made = O.compose(self.look, fmt, self.scratch, on_screen_text="Knee pain starts at the hip",
                             lower_third=TOMAS, disclaimer=DISCLAIMER, need_disclaimer=True, duration=8.0, preview_for=TOMAS)
            kinds = [layer.kind for layer in made.layers]
            self.assertEqual([k for k in kinds if k != "preview"][-1], "disclaimer")   # nothing is laid over it
            self.assertEqual(kinds[-1], "preview")
            band = made.layer("disclaimer")
            self.assertEqual((band.start, band.end), (0.0, None))             # from the first frame to the last
            self.assertGreaterEqual(made.disclaimer["type_size"], O.DISCLAIMER_SIZES[1])
            self.assertEqual(made.disclaimer["clear_on"], sorted(O.SAFE_MARGINS))
        self.assertIsNone(O.compose(self.look, "fullbleed", self.scratch, disclaimer=DISCLAIMER, duration=5.0).disclaimer)

    @draws
    def test_no_command_is_built_when_the_band_or_the_preview_stamp_has_gone_missing(self):
        made = O.compose(self.look, "fullbleed", self.scratch, disclaimer=DISCLAIMER, need_disclaimer=True, duration=6.0)
        job = {"recipe": V.effective(V.RECIPES[0]), "crop": {"x": 0, "y": 0, "w": 404, "h": 720}, "overlays": made, "fps": 25.0,
               "head": 0.0, "tail": 0.0, "kept": 6.0, "length_out": 6.0, "need_disclaimer": True, "preview": False, "bed": ""}
        cmd = V.build_command("ffmpeg", "in.mp4", "out.mp4", job)
        self.assertTrue(all(isinstance(part, str) for part in cmd))
        self.assertIn(made.layer("disclaimer").path, cmd)
        made.layers = [layer for layer in made.layers if layer.kind != "disclaimer"]
        with self.assertRaises(VideoError) as cm:
            V.build_command("ffmpeg", "in.mp4", "out.mp4", job)
        self.assertIn("Nothing was made", str(cm.exception))
        plain = O.compose(self.look, "fullbleed", self.scratch, duration=6.0)
        with self.assertRaises(VideoError):
            V.build_command("ffmpeg", "in.mp4", "out.mp4", dict(job, overlays=plain, need_disclaimer=False, preview=True))

    @draws
    def test_a_disclaimer_too_long_to_read_on_a_phone_is_an_error_not_smaller_print(self):
        with self.assertRaises(O.OverlayError) as cm:
            O.disclaimer_band(self.look, " ".join(["This is general education and not personal medical advice."] * 6))
        self.assertIn("Shorten it", str(cm.exception))
        _band, facts = O.disclaimer_band(self.look, "General education only. This is not personal medical advice. See a "
                                                    "clinician about your own injury before you change your training.")
        self.assertGreaterEqual(facts["type_size"], 38)
        self.assertLessEqual(facts["lines"], O.DISCLAIMER_MAX_LINES)

    def test_without_sign_off_it_waits_or_becomes_a_stamped_preview_and_with_one_it_may_be_made(self):
        m = self.plan(self.clinic, n=2)
        hold = m["clips"][1]
        self.assertEqual(V._may_render(hold, "", preview=False)[0], "wait")
        self.assertEqual(V._may_render(hold, "", preview=True)[0], "preview")
        self.assertEqual(V._may_render(hold, "Tomas Okafor, 14 September", preview=True)[0], "deliver")
        self.assertEqual(V._may_render(m["clips"][0], "", preview=False)[0], "deliver")       # SHIP needs nobody
        with mock.patch.object(V, "programs", return_value=("no-ffmpeg", "no-ffprobe")):
            result = V.render_variants(self.clinic, REC, clip_ids=["B1"])
        self.assertEqual((result["made"], result["failed"], [w["clip"] for w in result["waiting"]]), ([], [], ["B1"]))
        self.assertIn("preview", result["waiting"][0]["why"])
        self.assertEqual([n for n in self.everything_under(V.variants_dir(self.clinic, REC)) if n.endswith(".mp4")], [])

    def test_the_sign_off_is_read_from_the_cut_list_today_not_from_the_day_the_clip_was_cut(self):
        m = self.plan(self.clinic)
        self.assertEqual(m["clips"][1]["signed_off"], "")
        self.sign_off(self.clinic)
        report, _f, _k = V.load_report(self.clinic, REC)
        self.assertEqual(report["clips"][1]["signed_off"], "")                # the report still says nobody has
        self.assertEqual(V.current_sign_off(self.clinic, REC, report, report["clips"][1]), "Tomas Okafor, 14 September 2026")
        self.assertEqual(V.current_sign_off(self.clinic, REC, report, report["clips"][0]), "")
        rows = {r["clip"]: r for r in V.status(self.clinic, REC)}
        self.assertTrue(rows["B1"]["may_be_delivered"])

    @draws
    def test_the_band_is_recognised_in_a_frame_and_missed_when_it_is_not_there(self):
        from PIL import Image, ImageDraw
        made = O.compose(self.look, "fullbleed", self.scratch, disclaimer=DISCLAIMER, need_disclaimer=True, duration=6.0)
        layer = made.layer("disclaimer")
        busy = Image.new("RGB", (O.CANVAS_W, O.CANVAS_H), (190, 170, 40))
        draw = ImageDraw.Draw(busy)
        for x in range(0, O.CANVAS_W, 40):
            draw.rectangle([x, 0, x + 18, O.CANVAS_H], fill=(20, 40, 200))
        self.assertEqual(O.band_present(busy, made.disclaimer)[0], False)     # footage alone
        dark = Image.new("RGB", (O.CANVAS_W, O.CANVAS_H), (11, 11, 11))    # a black frame is not a band
        self.assertEqual(O.band_present(dark, made.disclaimer), (False, "the disclaimer's outline is not there"))
        caption = dark.copy().convert("RGBA")                                 # nor is a caption sitting where the band would be
        strip = O.caption_strip(self.look, ["not", "personal", "advice"], 1)
        caption.alpha_composite(strip, (0, layer.y))
        self.assertFalse(O.band_present(caption.convert("RGB"), made.disclaimer)[0])
        empty = busy.copy().convert("RGBA")
        empty.alpha_composite(O.framed_plate(layer.rect[2] - layer.rect[0], layer.rect[3] - layer.rect[1]), (layer.x, layer.y))
        self.assertEqual(O.band_present(empty.convert("RGB"), made.disclaimer), (False, "the plate is there but the words are not"))
        shown = busy.copy().convert("RGBA")
        shown.alpha_composite(Image.open(layer.path).convert("RGBA"), (layer.x, layer.y))
        self.assertEqual(O.band_present(shown.convert("RGB"), made.disclaimer), (True, ""))
        covered = shown.copy()
        ImageDraw.Draw(covered).rectangle([layer.x + 60, layer.y, layer.x + 700, layer.y + 200], fill=(250, 250, 250, 255))
        self.assertFalse(O.band_present(covered.convert("RGB"), made.disclaimer)[0])
        self.assertFalse(O.band_present(shown.convert("RGB"), dict(made.disclaimer, rect=[0, 0, 10, 10]))[0])


# ============================================================================= captions and text on screen
class TestCaptionsAndTextOnScreen(VariantCase):
    def setUp(self):
        super().setUp()
        self.look = O.look_for(self.bakery)
        self.scratch = tempfile.mkdtemp(prefix="captions ' \u00e9 ", dir=self.tmp.name)

    def words(self, clip=None):
        words, _ = V.clip_words(clip or self.bakery_clips[0], self.t_bakery, 0.0)
        return words

    def test_a_clips_words_come_from_the_transcript_by_arithmetic_and_know_their_piece(self):
        words = self.words()
        self.assertEqual(" ".join(w["word"] for w in words),
                         "Most dense loaves are simply underproofed. People trust the recipe time, the kitchen is cold, and "
                         "the dough never gets there. I tell every class the same thing. Watch the dough, not the clock.")
        self.assertEqual(sorted({w["piece"] for w in words}), [0, 1])
        first_of_second = next(w for w in words if w["piece"] == 1)
        self.assertAlmostEqual(first_of_second["start"], V.piece_joins(self.bakery_clips[0])[0] + 0.3, delta=0.01)
        self.assertEqual({w["speaker"] for w in words}, {AVA})

    def test_a_word_from_someone_off_camera_is_never_captioned_even_if_the_cut_let_it_in(self):
        t = self.t_bakery
        leaky = dict(self.bakery_clips[1], pieces=[[TV.when(t, "And is cheap flour", 0, JONAH)[0],
                                                    TV.when(t, "not the problem.", 0, AVA)[1] + 0.3]])
        policy = V.speaker_policy(self.bakery, t, {"speaker_check": "checked"})
        words, kept_out = V.clip_words(leaky, t, 0.0, policy)
        self.assertEqual(kept_out, len("And is cheap flour the real problem, 9 times out of 10?".split()))
        self.assertEqual({w["speaker"] for w in words}, {AVA})
        self.write_report(self.bakery, [leaky])
        self.assertTrue(any("off camera" in n for n in self.plan()["clips"][0]["notes"]))

    def test_lines_hold_two_to_four_words_and_never_straddle_a_removal(self):
        words = self.words()
        lines = O.caption_lines(words)
        self.assertEqual(sum(len(ln["words"]) for ln in lines), len(words))
        for ln in lines:
            self.assertEqual(len({w["piece"] for w in ln["words"]}), 1, ln["text"])
            self.assertTrue(2 <= len(ln["words"]) <= 4, ln["text"])
        # a removal in the middle of a sentence: the line still breaks there, whatever reads better
        mid = [dict(w, piece=0 if i < 3 else 1) for i, w in enumerate(words[:8])]
        self.assertEqual([len(ln["words"]) for ln in O.caption_lines(mid)][:1], [3])
        self.assertEqual([ln["text"] for ln in O.caption_lines(words[:5])], ["Most dense loaves", "are simply"])
        # a word alone between two removals stays alone rather than joining a neighbour across the cut
        alone = [dict(w, piece=piece) for w, piece in zip(words, (0, 0, 1, 2, 2))]
        self.assertEqual([len(ln["words"]) for ln in O.caption_lines(alone)], [2, 1, 2])
        # a long silence starts a new line too
        paused = [dict(w) for w in words[:6]]
        for w in paused[3:]:
            w["start"], w["end"] = w["start"] + 2.0, w["end"] + 2.0
        self.assertEqual([len(ln["words"]) for ln in O.caption_lines(paused)], [3, 3])

    @draws
    def test_no_line_is_ever_wider_than_the_column_however_long_the_words(self):
        from PIL import Image
        left, right = O.text_column()
        long_words = ("Extraordinarily overproofed wholemeal sourdough Pneumonoultramicroscopicsilicovolcanoconiosis "
                      "a I hydration-percentage-calculations bannetons").split()
        synthetic = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4, "piece": 0} for i, w in enumerate(long_words)]
        lines = O.caption_lines(synthetic, fits=O.caption_fits(self.look))
        self.assertGreater(len(lines), 2)
        for ln in lines:
            for active in range(len(ln["words"])):
                strip = O.caption_strip(self.look, [O.caption_token(w["word"]) for w in ln["words"]], active)
                ink = O.ink_box(strip)
                self.assertGreaterEqual(ink[0], left, ln["text"])
                self.assertLessEqual(ink[2], right, ln["text"])
                self.assertEqual(strip.size, (O.CANVAS_W, O.CAPTION_STRIP_H))
        made = O.compose(self.look, "fullbleed", self.scratch, lines=lines, duration=6.0)
        box = O.design_box()
        rect = made.layer("captions").rect
        self.assertTrue(box[0] <= rect[0] and rect[2] <= box[2] and box[1] <= rect[1] and rect[3] <= box[3])
        self.assertEqual(Image.open(os.path.join(self.scratch, "c-blank.png")).getchannel("A").getbbox(), None)

    def test_the_timeline_covers_the_clip_exactly_and_a_line_comes_down_at_the_join(self):
        words = self.words()
        lines = O.caption_lines(words)
        length = V.planned_length(self.bakery_clips[0])
        joins = V.piece_joins(self.bakery_clips[0])
        states = O.caption_timeline(lines, length, joins)
        self.assertEqual(states[0][0], 0.0)
        self.assertAlmostEqual(states[-1][1], length, places=2)
        for a, b in zip(states, states[1:]):
            self.assertAlmostEqual(a[1], b[0], places=3)                      # no gaps and no overlaps
        self.assertTrue(all(end - start >= O.CAPTION_MIN_STATE - 1e-6 for start, end, _i, _k in states))
        last_before = max(i for i, ln in enumerate(lines) if ln["piece"] == 0)
        shown_until = max(end for _s, end, i, _k in states if i == last_before)
        self.assertLessEqual(shown_until, joins[0] + 0.001)
        spoken = [(i, k) for _s, _e, i, k in states if i is not None]
        self.assertEqual(spoken, sorted(spoken))                              # words light up in the order they are said
        self.assertEqual(len(spoken), len(words))

    def test_fillers_and_abandoned_words_are_not_printed_unless_that_would_gut_the_clip(self):
        said = [{"word": w, "start": i, "end": i + 0.5, "piece": 0} for i, w in
                enumerate("So, um, the th- the dough is ready. Summer mum Umbrella long-term".split())]
        kept, dropped, note = O.printable_words(said)
        self.assertEqual((" ".join(w["word"] for w in kept), dropped, note),
                         ("So, the the dough is ready. Summer mum Umbrella long-term", 2, ""))
        hesitant = [{"word": w, "start": i, "end": i + 0.5, "piece": 0} for i, w in enumerate("um uh bread um uh".split())]
        kept, dropped, note = O.printable_words(hesitant)
        self.assertEqual((len(kept), dropped), (5, 0))
        self.assertIn("check the transcript", note)
        self.assertEqual([O.caption_token(w) for w in ("clock.", "\u201cdough,\u201d", "ready?", "Ava's", "...")],
                         ["clock", "dough", "ready?", "Ava's", ""])

    def test_the_word_being_spoken_can_be_read_on_the_plate_for_any_accent_colour(self):
        lightest = O.caption_plate_at_its_lightest()
        self.assertGreaterEqual(contrast("#FFFFFF", lightest), 7.0)
        navy = brands.create("night-runners", "Night Runners", dict(TV.clinic_answers(), visual={
            "colors": {"ground": "#FFFFFF", "ink": "#0B1020", "accent": "#0B1F3A"}, "wordmark": "Night Runners"}))
        for brand in (self.bakery, self.clinic, navy):
            look = O.look_for(brand)
            self.assertGreaterEqual(contrast(look.accent_on_plate, lightest), O.ACCENT_CONTRAST, brand.id)
        self.assertNotEqual(O.look_for(navy).accent_on_plate.upper(), "#0B1F3A")     # lightened, and still the brand's blue
        self.assertEqual(O.look_for(navy).notes, [])

    @draws
    def test_text_stays_inside_the_area_every_app_leaves_clear_and_pieces_never_collide(self):
        box = O.design_box()
        self.assertEqual(box, (max(m["left"] for m in O.SAFE_MARGINS.values()), max(m["top"] for m in O.SAFE_MARGINS.values()),
                               O.CANVAS_W - max(m["right"] for m in O.SAFE_MARGINS.values()),
                               O.CANVAS_H - max(m["bottom"] for m in O.SAFE_MARGINS.values())))
        self.assertLess(O.design_box(["linkedin"])[1], box[1])
        with self.assertRaises(O.OverlayError):
            O.design_box(["myspace"])
        lines = O.caption_lines(self.words(), fits=O.caption_fits(self.look))
        for fmt in O.FORMATS:
            for text in ("Your loaf is not broken", "Underproofed sourdough always collapses during overnight refrigeration"):
                made = O.compose(O.look_for(self.clinic), fmt, self.scratch, on_screen_text=text,
                                 lower_third="Ava Lindqvist, Head Baker and Founder of Maple & Main", disclaimer=DISCLAIMER,
                                 need_disclaimer=True, preview_for="", lines=lines, duration=12.0, face=(0.3, 0.16))
                for layer in made.layers:
                    r = layer.rect
                    self.assertTrue(box[0] - 2 <= r[0] and r[2] <= box[2] + 2 and box[1] - 2 <= r[1] and r[3] <= box[3] + 2,
                                    (fmt, layer.kind, r))
                    self.assertTrue(os.path.isfile(layer.path))
                x, y, w, h = made.video_rect
                self.assertEqual((w % 2, h % 2), (0, 0))
                if fmt == "square":
                    self.assertEqual(w, h)
                    self.assertGreater(made.layer("captions").rect[1], y + h)  # the caption line sits under the picture
        with self.assertRaises(O.OverlayError) as cm:
            O.hook_card(self.look, "Pneumonoultramicroscopicsilicovolcanoconiosisandthensomemoreletters is not three words")
        self.assertIn("Shorten it", str(cm.exception))
        self.assertEqual(O._balanced("YOUR LOAF IS NOT BROKEN", self.look.faces.get("poster", 90), 700, 2),
                         ["YOUR LOAF IS", "NOT BROKEN"])

    def test_the_opening_card_keeps_off_the_face_when_it_can(self):
        self.assertEqual(O._place_card(300, 1030, 220, 1200, None), (880, ""))
        top, note = O._place_card(300, 1030, 220, 1500, (0.50, 0.16))         # a face right where the card would go
        self.assertEqual(note, "")
        self.assertGreaterEqual(top, int((0.50 + 0.08 + O.HEAD_CLEARANCE) * O.CANVAS_H))
        top, note = O._place_card(300, 1030, 220, 1200, (0.72, 0.20))         # no room below: it goes above the head
        self.assertEqual(note, "")
        self.assertLessEqual(top + 300, int((0.72 - 0.10 - O.HEAD_CLEARANCE) * O.CANVAS_H) + 1)
        _top, note = O._place_card(700, 1030, 220, 1200, (0.45, 0.40))
        self.assertIn("Watch it", note)

    def test_the_slice_of_the_picture_follows_the_face_and_falls_back_to_the_centre(self):
        wide = {"width": 1280, "height": 720}
        centre = V.crop_for(wide, "fullbleed", {"found": False})
        self.assertEqual((centre["x"], centre["y"], centre["w"], centre["h"], centre["around"]), (437, 0, 404, 720, "the centre"))
        nearer = V.crop_for(wide, "fullbleed", {"found": True, "x": 0.7, "y": 0.4, "h": 0.25, "by": "the face finder"})
        self.assertAlmostEqual(nearer["x"] + nearer["w"] / 2.0, 0.7 * 1280, delta=2)
        right = V.crop_for(wide, "fullbleed", {"found": True, "x": 0.95, "y": 0.4, "h": 0.25, "by": "the face finder"})
        self.assertEqual((right["x"], right["around"]), (1280 - 405, "the face"))   # pushed to the edge, never past it
        self.assertAlmostEqual(right["face"][0], 0.4, places=2)
        said = V.crop_for(wide, "square", {"found": True, "x": 0.25, "y": 0.0, "h": 0.0, "by": "a person"})
        self.assertEqual((said["x"], said["w"], said["h"], said["around"], said["face"]),
                         (0, 720, 720, "where a person said they are", None))
        tall = V.crop_for({"width": 1080, "height": 1920}, "square",
                          {"found": True, "x": 0.5, "y": 0.3, "h": 0.12, "by": "the face finder"}, zoom=1.05)
        self.assertEqual((tall["w"], tall["h"]), (1028, 1028))
        self.assertAlmostEqual((0.3 * 1920 - tall["y"]) / tall["h"], V.HEAD_AT, places=2)
        full = V.crop_for({"width": 1080, "height": 1920}, "fullbleed", {"found": False})
        self.assertEqual((full["x"], full["y"], full["w"], full["h"]), (0, 0, 1080, 1920))
        self.assertEqual(V.find_face("missing.mp4", wide, 0.2)["found"], False)


# ============================================================================= the words under the video
class TestDescriptions(VariantCase):
    def setUp(self):
        super().setUp()
        grounding.add_fact(self.bakery, "We have taught 240 people to bake since 2021.", "class sign-up sheets")
        self.plan(n=2)
        self.plan(self.clinic, n=2)

    def verdict(self, text, clip="A1", version="v1", platform="tiktok", brand=None, others=()):
        brand = brand or self.bakery
        D.save_store(brand, REC, [{"clip": clip, "version": version, "platform": platform, "text": text}] + list(others))
        report = D.check_descriptions(brand, REC)
        return next(r for r in report["descriptions"] if (r["clip"], r["version"], r["platform"]) == (clip, version, platform))

    def test_the_contract_holds_the_clips_own_words_and_nothing_of_the_other_brand(self):
        c = D.build_contract(self.bakery, REC, "b1")
        self.assertEqual(c["clip"]["said_word_for_word"],
                         "We go through 90 kilos of flour a week here and cheap flour is not the problem.")
        self.assertEqual((c["clip"]["on_camera"], c["clip"]["kept_off_camera"]), ([AVA], [JONAH]))
        self.assertEqual((c["versions"], c["platforms"]), (["v1", "v2"], ["instagram", "facebook"]))
        self.assertEqual(c["speaker"]["display_name"], AVA)
        self.assertEqual(c["facts"]["numbers_said_on_camera"], [90.0])
        self.assertEqual(c["offers"][0]["name"], "Weekend sourdough class")
        self.assertEqual(c["facts"]["brand_facts"][0]["claim"], "We have taught 240 people to bake since 2021.")
        for must in (D.HARD_RULE, "cheap flour is not the problem", "Nothing they said may be put under this video",
                     "Every version needs words of its own", "Book a Saturday class at the counter.", "Harbour Street Cafe"):
            self.assertIn(must, c.markdown)
        for never in ("9 times out of 10", "Stride", "Tomas", "medical"):
            self.assertNotIn(never, c.markdown)
        hold = D.build_contract(self.clinic, REC, "B1")
        self.assertIn("EVERY description of it must carry the brand's disclaimer", hold.markdown)
        self.assertIn(DISCLAIMER, hold.markdown)
        self.assertIn("regulated field (health)", hold.markdown)
        with self.assertRaises(D.DescribeError):
            D.build_contract(self.bakery, REC, "A1", only_platforms=["myspace"])
        with self.assertRaises(D.DescribeError):
            D.build_contract(self.bakery, REC, "Z9")

    def test_honest_words_pass(self):
        good = self.verdict("Most dense loaves are simply underproofed.\n\nWatch the dough, not the clock. Save this for your next bake.")
        self.assertEqual((good["sourcing"], good["problems"], good["unverified"]), ("passed", [], []))
        said = self.verdict("We go through 90 kilos of flour a week, and cheap flour is not the problem.", clip="B1")
        self.assertEqual(said["sourcing"], "passed")                          # a number she says on camera may be repeated
        fact = self.verdict("We have taught 240 people to bake. Most dense loaves are simply underproofed.")
        self.assertEqual(fact["sourcing"], "passed")                          # and so may one from the brand's own facts
        ask = self.verdict("The kitchen is cold and the dough never gets there.\n\nBook a Saturday class at the counter.")
        self.assertEqual(ask["sourcing"], "passed")

    def test_an_invented_number_blocks(self):
        bad = self.verdict("73% of home loaves come out dense because they are underproofed.")
        self.assertEqual(bad["sourcing"], "blocked")
        self.assertTrue(any("73" in p and "not said in the clip" in p for p in bad["problems"]))
        wrong_clip = self.verdict("We go through 90 kilos of flour a week.", clip="A1")       # said, but in the OTHER clip
        self.assertEqual(wrong_clip["sourcing"], "blocked")

    def test_a_claim_only_the_interviewer_made_is_caught(self):
        bad = self.verdict("Cheap flour is the real problem 9 times out of 10.", clip="B1")
        self.assertEqual(bad["sourcing"], "blocked")
        joined = " ".join(bad["problems"])
        self.assertIn(JONAH, joined)
        self.assertIn("off camera", joined)
        words = self.verdict("Is cheap flour the real problem in your kitchen?", clip="B1")  # his words, no number
        self.assertEqual(words["sourcing"], "blocked")
        self.assertTrue(any("only said by " + JONAH in p for p in words["problems"]))
        echoed = self.verdict("Watch the dough, not the clock.")               # he repeated HER line; it is still hers
        self.assertEqual(echoed["sourcing"], "passed")

    def test_a_service_the_brand_does_not_offer_is_caught(self):
        bad = self.verdict("Most dense loaves are simply underproofed. We also run a gluten-free pastry course.")
        self.assertEqual(bad["sourcing"], "blocked")
        self.assertTrue(any("not among Maple & Main Bakery's offers (Weekend sourdough class)" in p for p in bad["problems"]),
                        bad["problems"])
        for fine in ("Most dense loaves are simply underproofed. We run a weekend sourdough class.",
                     "Watch the dough, not the clock. Book a Saturday class at the counter.",
                     "Watch the dough, not the clock. I run every morning before the ovens go on."):
            self.assertNotEqual(self.verdict(fine)["sourcing"], "blocked", fine)
        keyword = self.verdict("Watch the dough, not the clock. Comment STARTER and I will send you the guide.")
        self.assertEqual(keyword["sourcing"], "blocked")                      # a promise nobody has set up

    def test_two_versions_may_not_share_their_words(self):
        same = "Most dense loaves are simply underproofed, so watch the dough and not the clock."
        first = self.verdict(same, others=[{"clip": "A1", "version": "v2", "platform": "tiktok", "text": same + " Save this."}])
        self.assertEqual(first["sourcing"], "blocked")
        self.assertTrue(any("shares its words with A1 v2" in p for p in first["problems"]))
        across = self.verdict(same, others=[{"clip": "A1", "version": "v2", "platform": "instagram", "text": same}])
        self.assertEqual(across["sourcing"], "blocked")                       # another platform does not excuse it
        own = self.verdict(same, others=[
            {"clip": "A1", "version": "v2", "platform": "tiktok",
             "text": "People trust the recipe time, the kitchen is cold, and the dough never gets there."},
            {"clip": "A1", "version": "v1", "platform": "instagram", "text": same}])          # one version, two platforms: fine
        self.assertEqual(own["sourcing"], "passed")
        other_clip = self.verdict(same, others=[{"clip": "B1", "version": "v1", "platform": "tiktok", "text": same}])
        self.assertTrue(any("Two clips from the same passage" in p for p in other_clip["problems"]))
        self.assertEqual(D.same_words("Watch the dough!", "watch the dough"), 1.0)

    def test_the_clinics_health_rules_apply_to_the_clinic_and_not_to_the_bakery(self):
        bakery = self.verdict("A longer proof cures a dense loaf.")
        self.assertFalse(any("never publishes" in p for p in bakery["problems"]), bakery["problems"])
        self.assertNotEqual(bakery["sourcing"], "blocked")
        clinic = self.verdict("Hip drops cure knee pain in runners over thirty.", brand=self.clinic)
        self.assertEqual(clinic["sourcing"], "blocked")
        self.assertTrue(any("Stride Physio never publishes" in p and "cure" in p for p in clinic["problems"]))
        named = self.verdict("Better bread than Harbour Street Cafe. Watch the dough, not the clock.")
        self.assertEqual(named["sourcing"], "blocked")                        # and each brand's own never-mention list holds

    def test_a_hold_clips_words_must_carry_the_disclaimer_and_a_cleared_clips_words_must_not_need_one(self):
        bare = self.verdict("Shockwave is something we offer when loading alone is not enough.", clip="B1", brand=self.clinic)
        self.assertEqual(bare["sourcing"], "blocked")
        self.assertTrue(any("must carry the brand's disclaimer" in p for p in bare["problems"]))
        carried = self.verdict("When loading alone is not enough, shockwave is something to ask about.\n\n" + DISCLAIMER,
                               clip="B1", brand=self.clinic)
        self.assertEqual(carried["problems"], [])
        drifted = self.verdict("Knee pain starts at the hip. Ask us about shockwave.", clip="A1", brand=self.clinic)
        self.assertEqual(drifted["sourcing"], "blocked")
        self.assertTrue(any("cleared without one" in p for p in drifted["problems"]))

    def test_a_claim_found_nowhere_is_unverified_and_the_brands_rules_still_block(self):
        odd = self.verdict("Sourdough was invented in ancient Egypt by accident.")
        self.assertEqual(odd["sourcing"], "unverified")
        self.assertIn("neither in the clip nor in", odd["unverified"][0])
        dash = self.verdict("Watch the dough \u2014 not the clock.")
        self.assertEqual(dash["sourcing"], "blocked")
        title = self.verdict("Why your sourdough loaf comes out dense " * 4 + "\n\nWatch the dough, not the clock.", platform="youtube")
        self.assertTrue(any("first line is the title" in p for p in title["problems"]))
        unknown = self.verdict("Watch the dough, not the clock.", version="v9")
        self.assertTrue(any("no version called 'v9'" in p for p in unknown["problems"]))

    def test_checking_nothing_is_never_a_pass(self):
        with self.assertRaises(D.DescribeError) as cm:
            D.check_descriptions(self.bakery, REC)
        self.assertIn("not a pass", str(cm.exception))
        D.save_store(self.bakery, REC, [{"clip": "A1", "version": "v1", "platform": "tiktok", "text": "Watch the dough, not the clock."}])
        with self.assertRaises(D.DescribeError):
            D.check_descriptions(self.bakery, REC, only=["B1"])
        report = D.check_descriptions(self.bakery, REC)
        self.assertIn("A1 v2", report["no_words_yet"])
        self.assertEqual(D.verdicts(self.clinic, REC), {})

    def test_small_tools(self):
        self.assertEqual(sorted(D.spoken_numbers("ninety kilos, 9 times out of 10, two hundred and forty people, twenty one")),
                         [9.0, 10.0, 21.0, 90.0, 240.0])
        self.assertEqual(D.stem("baking"), D.stem("baked"))
        self.assertEqual(D.stem("loaves"), D.stem("loaf"))
        self.assertEqual(D.key_terms("The dough and the clock"), ["dough", "clock"])
        self.assertEqual(D.own_words("Save this. " + DISCLAIMER + " #bread #dough", [DISCLAIMER]), "Save this.")


# ============================================================================= what was heard, who was in it
class TestJudgingAFinishedVersion(VariantCase):
    def expected(self):
        return V.clip_words(self.bakery_clips[0], self.t_bakery, 0.0)[0]

    def heard(self, words, shift=0.0):
        return [(w["start"] + shift, w["end"] + shift, w["word"]) for w in words]

    def test_the_right_words_pass_and_the_wrong_clip_fails(self):
        want = self.expected()
        length = V.planned_length(self.bakery_clips[0])
        problems, looks, facts = VF.judge_words(want, self.heard(want), length)
        self.assertEqual((problems, looks, facts["overall"], facts["head"], facts["tail"]), ([], [], 1.0, 1.0, 1.0))
        other = V.clip_words(self.bakery_clips[1], self.t_bakery, 0.0)[0]
        self.assertTrue(any("wrong clip" in p for p in VF.judge_words(want, self.heard(other), length)[0]))
        self.assertEqual(VF.judge_words(want, [], length)[0], ["no words were heard in it at all"])
        self.assertIn("not checked", VF.judge_words([], self.heard(want), length)[0][0])

    def test_a_cut_that_lost_its_first_words_is_caught(self):
        want = self.expected()
        length = V.planned_length(self.bakery_clips[0])
        problems = VF.judge_words(want, self.heard(want[5:]), length)[0]
        self.assertTrue(any("lost its first words" in p for p in problems), problems)
        problems = VF.judge_words(want, self.heard(want[:-6]), length)[0]
        self.assertTrue(any("does not close" in p for p in problems), problems)

    def test_talk_about_the_take_and_the_off_camera_voice_are_heard_for(self):
        want = self.expected()
        length = V.planned_length(self.bakery_clips[0])
        extra = [(length - 1.0, length - 0.5, "Can"), (length - 0.5, length - 0.3, "you"), (length - 0.3, length - 0.2, "say"),
                 (length - 0.2, length - 0.1, "that"), (length - 0.1, length, "again?")]
        problems = VF.judge_words(want, self.heard(want) + extra, length)[0]
        self.assertTrue(any("talk about the take" in p for p in problems), problems)
        turn = {"speaker": JONAH, "text": "And is cheap flour the real problem, 9 times out of 10?"}
        leaked = self.heard(want) + [(length + i * 0.1, length + i * 0.1 + 0.05, w) for i, w in enumerate(turn["text"].split())]
        problems = VF.judge_words(want, leaked, length, [turn])[0]
        self.assertTrue(any(JONAH in p and "off camera" in p for p in problems), problems)
        echo = {"speaker": JONAH, "text": "Watch the dough, not the clock."}    # he repeats her line: hearing it proves nothing
        self.assertEqual(VF.judge_words(want, self.heard(want), length, [echo])[0], [])

    def test_who_is_in_it_is_checked_against_what_was_really_cut_and_nothing_checked_is_a_failure(self):
        t = self.t_bakery
        policy = V.speaker_policy(self.bakery, t, {"speaker_check": "checked"})
        problems, facts = VF.judge_voices(self.bakery_clips[0], t.turns(), policy, 0.0, True)
        self.assertEqual((problems, facts["off_camera_seconds"], facts["pieces"]), ([], 0.0, 2))
        leaky = dict(self.bakery_clips[1], pieces=[[TV.when(t, "And is cheap flour", 0, JONAH)[0],
                                                    TV.when(t, "not the problem.", 0, AVA)[1]]])
        self.assertIn("off camera is inside it", VF.judge_voices(leaky, t.turns(), policy, 0.0, True)[0][0])
        self.assertIn("was not checked", VF.judge_voices(dict(leaky, pieces=[]), t.turns(), policy, 0.0, True)[0][0])
        unlabelled = Transcript({"words": [dict(w, speaker="") for w in t.words]})
        blind = V.speaker_policy(self.bakery, unlabelled, {"speaker_check": "unverified"})
        self.assertIn("could not be checked", VF.judge_voices(self.bakery_clips[0], unlabelled.turns(), blind, 0.0, True)[0][0])
        self.assertEqual(VF.judge_voices(self.bakery_clips[0], unlabelled.turns(), blind, 0.0, False)[0], [])

    def test_with_no_finished_versions_the_check_fails_instead_of_passing(self):
        self.plan()
        with self.assertRaises(VideoError) as cm:
            VF.verify(self.bakery, REC, hear=lambda path: [])
        self.assertIn("not a pass", str(cm.exception))
        with mock.patch.object(VF.VC, "speech_model", return_value=None):
            with self.assertRaises(VideoError) as cm:
                VF.verify(self.bakery, REC)
        self.assertIn("nothing was verified", str(cm.exception))
        self.assertEqual(VF.passed(self.bakery, REC), {})


# ============================================================================= delivery
class TestDelivery(VariantCase):
    def setUp(self):
        super().setUp()
        self.manifest = self.plan(n=2)
        self.inbox = self.bakery.path("Inputs", "Edited", REC)

    def pretend_made(self, brand, manifest, band=None, checked=True):
        """Stand-in files, with the record a real render leaves and (optionally) a passed check."""
        entries, rows = [], []
        for clip in manifest["clips"]:
            for v in clip["versions"]:
                path = brand.path(*v["output"].split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                Path(path).write_bytes(("video of %s %s" % (clip["id"], v["version"])).encode("utf-8"))
                need = bool(clip["needs_disclaimer"])
                entries.append({"clip": clip["id"], "version": v["version"], "preview": False, "file": v["output"], "status": "ok",
                                "fingerprint": v["fingerprint"], "sha256": V.sha256_of(path), "recipe": v["recipe"], "duration": 9.0,
                                "gate": clip["gate"], "disclaimer": band if band is not None else
                                {"required": need, "present": need, "text": clip["disclaimer"]}})
                rows.append({"clip": clip["id"], "version": v["version"], "file": v["output"], "pass": True, "sha256": V.sha256_of(path)})
        V._save_log(brand, REC, entries)
        if checked:
            common.write_json_atomic(V.variants_dir(brand, REC, VF.REPORT_FILE), {"schema": 1, "brand": brand.id, "versions": rows})

    def test_files_are_named_the_way_posting_expects_with_their_words_beside_them(self):
        from smf.posting import shorts as SH
        self.pretend_made(self.bakery, self.manifest)
        D.save_store(self.bakery, REC, [
            {"clip": "A1", "version": "v1", "platform": "tiktok", "text": "Most dense loaves are simply underproofed."},
            {"clip": "A1", "version": "v2", "platform": "tiktok", "text": "Watch the dough, not the clock."},
            {"clip": "A1", "version": "v2", "platform": "", "text": "People trust the recipe time, and the kitchen is cold."}])
        record = DL.deliver(self.bakery, REC)
        self.assertEqual(sorted(os.listdir(self.inbox)), [
            "A1-why-loaves-come-out-dense__v1.mp4", "A1-why-loaves-come-out-dense__v1.tiktok.txt",
            "A1-why-loaves-come-out-dense__v2.mp4", "A1-why-loaves-come-out-dense__v2.tiktok.txt",
            "A1-why-loaves-come-out-dense__v2.txt", "B1-cheap-flour-is-not-the-problem__v1.mp4",
            "B1-cheap-flour-is-not-the-problem__v2.mp4", "delivery-manifest.json"])
        self.assertEqual(Path(self.inbox, "A1-why-loaves-come-out-dense__v2.tiktok.txt").read_text(encoding="utf-8"),
                         "Watch the dough, not the clock.\n")
        self.assertEqual({v["outcome"] for v in record["videos"]}, {"delivered"})
        self.assertEqual({v["cleared"] for v in record["videos"]}, {"passed the check"})
        saved = json.loads(Path(self.inbox, DL.MANIFEST_FILE).read_text(encoding="utf-8"))
        first = saved["deliveries"][0]["videos"][0]
        self.assertEqual((first["clip"], first["version"], first["gate"], first["source_clip"], saved["brand"]),
                         ("A1", "v1", "SHIP", "Output/video/%s/fine/A1-why-loaves-come-out-dense.mp4" % REC, "maple-and-main"))
        found = SH.discover(self.bakery, probe=False)                          # the posting side sees ONE clip with two versions
        clip = next(c for c in found["clips"] if c["title"] == "A1-why-loaves-come-out-dense")
        self.assertEqual([f["version"] for f in clip["files"]], ["v1", "v2"])
        words, name = SH.description_for(clip["files"][1]["path"], clip["files"][1]["clip_stem"], "tiktok")
        self.assertEqual((words, name), ("Watch the dough, not the clock.", "A1-why-loaves-come-out-dense__v2.tiktok.txt"))
        self.assertEqual(SH.description_for(clip["files"][1]["path"], clip["files"][1]["clip_stem"], "instagram")[0],
                         "People trust the recipe time, and the kitchen is cold.")

    def test_nothing_in_the_inbox_is_ever_overwritten(self):
        self.pretend_made(self.bakery, self.manifest)
        D.save_store(self.bakery, REC, [{"clip": "A1", "version": "v1", "platform": "tiktok",
                                         "text": "Most dense loaves are simply underproofed."}])
        DL.deliver(self.bakery, REC, clip_ids=["A1"])
        video = Path(self.inbox, "A1-why-loaves-come-out-dense__v1.mp4")
        words = Path(self.inbox, "A1-why-loaves-come-out-dense__v1.tiktok.txt")
        again = DL.deliver(self.bakery, REC, clip_ids=["A1"])
        self.assertEqual({v["outcome"] for v in again["videos"]}, {"already"})
        self.assertEqual(len(json.loads(Path(self.inbox, DL.MANIFEST_FILE).read_text(encoding="utf-8"))["deliveries"]), 2)
        video.write_bytes(b"something a person put here")
        words.write_text("words a person edited", encoding="utf-8")
        D.save_store(self.bakery, REC, [{"clip": "A1", "version": "v1", "platform": "tiktok", "text": "Watch the dough, not the clock."}])
        third = DL.deliver(self.bakery, REC, clip_ids=["A1"], versions=["v1"])
        self.assertEqual([v["outcome"] for v in third["videos"]], ["different"])
        self.assertEqual(video.read_bytes(), b"something a person put here")
        self.assertEqual(words.read_text(encoding="utf-8"), "words a person edited")
        dry = DL.deliver(self.bakery, REC, clip_ids=["B1"], dry_run=True)
        self.assertEqual({v["outcome"] for v in dry["videos"]}, {"would be delivered"})
        self.assertFalse(any(n.startswith("B1") for n in os.listdir(self.inbox)))
        self.assertFalse(any(n.startswith(".arriving") for n in os.listdir(self.inbox)))

    def test_a_hold_clip_without_sign_off_is_never_delivered_whoever_vouches_for_it(self):
        m = self.plan(self.clinic, n=1)
        self.pretend_made(self.clinic, m)
        record = DL.deliver(self.clinic, REC, watched_by="Mina Castellane")
        self.assertEqual([(v["clip"], v["outcome"]) for v in record["videos"]], [("A1", "delivered")])
        self.assertEqual([(r["clip"], "has not signed it off" in r["why"]) for r in record["refused"]], [("B1", True)])
        self.sign_off(self.clinic)
        record = DL.deliver(self.clinic, REC, clip_ids=["B1"])
        self.assertEqual([(v["clip"], v["outcome"], v["signed_off"], v["disclaimer_on_screen"]) for v in record["videos"]],
                         [("B1", "delivered", "Tomas Okafor, 14 September 2026", True)])

    def test_a_file_whose_own_record_says_the_disclaimer_is_missing_is_never_delivered(self):
        m = self.plan(self.clinic, n=1)
        self.sign_off(self.clinic)
        for band, why in (({"required": True, "present": False, "text": DISCLAIMER}, "did not get it"),
                          ({"required": False, "present": False, "text": ""}, "needs its disclaimer"), ({}, "needs its disclaimer")):
            self.pretend_made(self.clinic, m, band=band)
            record = DL.deliver(self.clinic, REC, clip_ids=["B1"], watched_by=TOMAS)
            self.assertEqual(record["videos"], [])
            self.assertIn(why, record["refused"][0]["why"])
        self.assertFalse(os.path.exists(self.clinic.path("Inputs", "Edited", REC)))

    def test_an_unchecked_or_changed_file_needs_a_person_or_is_refused(self):
        self.pretend_made(self.bakery, self.manifest, checked=False)
        record = DL.deliver(self.bakery, REC, clip_ids=["A1"], versions=["v1"])
        self.assertIn("has not passed the check", record["refused"][0]["why"])
        record = DL.deliver(self.bakery, REC, clip_ids=["A1"], versions=["v1"], watched_by="  Ava   Lindqvist ")
        self.assertEqual(record["videos"][0]["cleared"], "Ava Lindqvist said they watched it")
        path = self.bakery.path(*self.manifest["clips"][0]["versions"][1]["output"].split("/"))
        Path(path).write_bytes(b"edited afterwards")
        record = DL.deliver(self.bakery, REC, clip_ids=["A1"], versions=["v2"], watched_by="Ava Lindqvist")
        self.assertIn("changed since it was made", record["refused"][0]["why"])
        with self.assertRaises(VideoError):
            DL.deliver(self.bakery, REC, clip_ids=["Z9"])

    def test_blocked_words_are_never_written_and_unverified_ones_only_on_a_persons_say_so(self):
        self.pretend_made(self.bakery, self.manifest)
        D.save_store(self.bakery, REC, [
            {"clip": "A1", "version": "v1", "platform": "tiktok", "text": "73% of loaves come out dense."},
            {"clip": "A1", "version": "v2", "platform": "tiktok", "text": "Sourdough was invented in ancient Egypt by accident."}])
        record = DL.deliver(self.bakery, REC, clip_ids=["A1"])
        self.assertEqual(sorted(n for n in os.listdir(self.inbox) if n.endswith(".txt")), [])
        self.assertTrue(all(w["outcome"].startswith("not written") for w in record["words"]))
        record = DL.deliver(self.bakery, REC, clip_ids=["A1"], allow_unverified_words=True)
        self.assertEqual(sorted(n for n in os.listdir(self.inbox) if n.endswith(".txt")), ["A1-why-loaves-come-out-dense__v2.tiktok.txt"])
        self.assertTrue(next(w for w in record["words"] if w["version"] == "v2")["let_through_by_a_person"])

    def test_the_inbox_is_the_brands_own_and_never_another_brands(self):
        self.pretend_made(self.bakery, self.manifest)
        theirs = os.path.join(brands.CLIENT_DIR, "stride-physio", "Inputs", "Edited")
        self.bakery = brands.update("maple-and-main", {"video": {"inbox_folder": theirs}})
        with self.assertRaises(VideoError) as cm:
            DL.deliver(self.bakery, REC)
        self.assertIn("another brand", str(cm.exception))
        outside = tempfile.mkdtemp(prefix="cloud drive ' \u00e9 ", dir=self.tmp.name)
        self.bakery = brands.update("maple-and-main", {"video": {"inbox_folder": outside}})
        record = DL.deliver(self.bakery, REC, clip_ids=["B1"])
        self.assertEqual(len(record["videos"]), 2)
        self.assertEqual(len([n for n in os.listdir(os.path.join(outside, REC)) if n.endswith(".mp4")]), 2)


class TestTheVerbs(VariantCase):
    def run_verb(self, fn, *args):
        with mock.patch("builtins.print") as out:
            code = fn(list(args))
        return code, "\n".join(str(c.args[0]) for c in out.call_args_list if c.args)

    def test_every_action_needs_a_brand_and_a_recording_and_says_so_plainly(self):
        self.assertEqual(self.run_verb(variants_cli.cli_variants)[0], 1)
        self.assertEqual(self.run_verb(variants_cli.cli_describe, "nonsense")[0], 1)
        for fn, actions in ((variants_cli.cli_variants, variants_cli.VARIANT_ACTIONS),
                            (variants_cli.cli_describe, variants_cli.DESCRIBE_ACTIONS)):
            for action in actions:
                for missing in (["--brand", "maple-and-main"], ["--recording", REC]):
                    with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                        fn([action] + missing)
        code, said = self.run_verb(variants_cli.cli_variants, "plan", "--brand", "nobody-here", "--recording", REC)
        self.assertEqual(code, 1)
        self.assertIn("there is no brand called 'nobody-here'", said)

    def test_plan_status_contract_and_check_run_end_to_end(self):
        with mock.patch.object(V, "find_face", return_value={"found": False, "note": V.NO_FINDER}):
            code, said = self.run_verb(variants_cli.cli_variants, "plan", "--brand", "stride-physio", "--recording", REC,
                                       "--versions", "2", "--no-text-in-picture")
        self.assertEqual(code, 0, said)
        for must in ("Nothing has been made yet", "waiting for sign-off: B1", "no version is mirrored", "cannot look for faces"):
            self.assertIn(must, said)
        code, said = self.run_verb(variants_cli.cli_variants, "status", "--brand", "stride-physio", "--recording", REC)
        self.assertIn("B1  HOLD, on HOLD, waiting for sign-off by Tomas Okafor", said)
        code, said = self.run_verb(variants_cli.cli_describe, "contract", "--brand", "stride-physio", "--recording", REC, "--clip", "A1")
        self.assertEqual(code, 0, said)
        self.assertTrue(os.path.isfile(V.variants_dir(self.clinic, REC, "contracts", "A1.md")))
        D.save_store(self.clinic, REC, [{"clip": "A1", "version": "v1", "platform": "instagram",
                                         "text": "Rest fixes 8 out of 10 sore knees."}])
        code, said = self.run_verb(variants_cli.cli_describe, "check", "--brand", "stride-physio", "--recording", REC)
        self.assertEqual(code, 1)
        self.assertIn("only said by " + MINA, said)
        code, said = self.run_verb(variants_cli.cli_variants, "plan", "--brand", "stride-physio", "--recording", REC, "--centre-on", "A1")
        self.assertEqual(code, 1)
        self.assertIn("--centre-on A1=0.3", said)


# ============================================================================= with the real video programs
class RealClipsCase(VariantCase):
    """The clips are cut from a test pattern with a tone: small, quick, and nobody's footage."""

    def setUp(self):
        super().setUp()
        from smf import media
        self.ff, self.fp = media.ensure_ffmpeg()
        self.fast = mock.patch.dict(V.ENCODE, {"preset": "ultrafast", "crf": "30"})
        self.fast.start()
        self.addCleanup(self.fast.stop)
        master = os.path.join(self.tmp.name, "pattern.mp4")
        self.ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=30", "-f", "lavfi", "-i",
                    "sine=frequency=220:duration=30", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", master)
        for brand, clips in ((self.bakery, self.bakery_clips), (self.clinic, self.clinic_clips)):
            folder = common.output_dir(brand, REC, "fine")
            for c in clips:
                length = sum(b - a for a, b in c["pieces"])
                self.ffmpeg("-ss", "1", "-t", "%.3f" % length, "-i", master, "-c:v", "libx264", "-preset", "ultrafast",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", os.path.join(folder, c["file"]))
            self.write_report(brand, clips, shape={"orientation": "horizontal", "width": 640, "height": 360})

    def ffmpeg(self, *args):
        done = subprocess.run([self.ff, "-y", "-hide_banner", "-loglevel", "error"] + list(args), capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr[-400:])

    def files(self, brand, *parts):
        folder = V.variants_dir(brand, REC, *parts)
        return sorted(n for n in os.listdir(folder) if n.endswith(".mp4")) if os.path.isdir(folder) else []



@unittest.skipUnless(TV.HAS_VIDEO, TV.NEEDS_VIDEO)
class TestWithRealVideo(RealClipsCase):
    def test_every_recipe_in_the_library_makes_an_upright_video_with_sound_of_the_right_length(self):
        bed = self.bakery.path("Brand", "music")
        os.makedirs(bed)
        self.ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2", os.path.join(bed, "Ava's loop.wav"))
        self.bakery = brands.update("maple-and-main", {"video": {"music_folder": "Brand/music", "allow_mirror": True}})
        m = self.plan(clip_ids=["B1"], n=V.MAX_VERSIONS, no_text_in_footage=True)
        beds, _ = V.music_beds(self.bakery)
        words, _ = V.clip_words(self.bakery_clips[1], self.t_bakery, 0.0)
        slack = V.slack_of(words, V.planned_length(self.bakery_clips[1]))
        clip = m["clips"][0]
        bed_at = common.locate(self.bakery, beds[0])

        def out_for(version):
            return common.locate(self.bakery, V.variants_dir(self.bakery, REC, V.version_file(clip["report_entry"], version)))
        clip["versions"] = [dict(clip["versions"][0], version="v%d" % (i + 1), fingerprint="all-%d" % i,
                                 recipe=dict(V.effective(r, True, beds, slack), music_bed=bed_at if r["music"] else ""),
                                 output=out_for("v%d" % (i + 1)))
                            for i, r in enumerate(V.RECIPES)]
        common.write_json_atomic(V.manifest_path(self.bakery, REC), m)
        result = V.render_variants(self.bakery, REC)
        self.assertEqual((len(result["made"]), result["failed"]), (len(V.RECIPES), []))
        log = {e["version"]: e for e in V.load_log(self.bakery, REC)}
        source_length = common.probe_duration(os.path.join(common.output_dir(self.bakery, REC, "fine"), clip["report_entry"]["file"]))
        for v in clip["versions"]:
            path = self.bakery.path(*v["output"].split("/"))
            entry, recipe = log[v["version"]], v["recipe"]
            self.assertEqual(common.probe_shape(path), {"orientation": "vertical", "width": 1080, "height": 1920}, recipe["id"])
            self.assertTrue(common.has_audio(path) and common.decodes_cleanly(path), recipe["id"])
            self.assertAlmostEqual(common.probe_duration(path), (source_length - recipe["trim_seconds"]) / recipe["speed"], delta=0.25)
            self.assertEqual((entry["status"], entry["applied"]["mirror"], entry["applied"]["trim"]["seconds"], entry["sha256"]),
                             ("ok", recipe["mirror"], recipe["trim_seconds"], V.sha256_of(path)))
            self.assertEqual(entry["applied"]["music"], {"bed": "Ava's loop.wav", "level": recipe["music"]} if recipe["music"] else None)
            self.assertEqual(entry["on_screen"]["captions"]["words"], len(words))
            self.assertEqual(entry["disclaimer"], {"required": False, "present": False, "text": ""})
        self.assertTrue(any(log[v]["applied"]["mirror"] for v in log) and any(log[v]["applied"]["music"] for v in log))
        self.assertEqual([n for n in self.everything_under(V.variants_dir(self.bakery, REC)) if "working" in n], [])

    def test_a_hold_clip_is_a_stamped_preview_until_it_is_signed_off_and_always_carries_its_band(self):
        self.plan(self.clinic, n=1)
        waiting = V.render_variants(self.clinic, REC, clip_ids=["B1"])
        self.assertEqual((waiting["made"], [w["clip"] for w in waiting["waiting"]]), ([], ["B1"]))
        V.render_variants(self.clinic, REC, preview=True)
        self.assertEqual(self.files(self.clinic), ["A1-knee-pain-starts-at-the-hip__v1.mp4"])     # never under the delivery name
        self.assertEqual(self.files(self.clinic, "previews"), ["B1-when-loading-is-not-enough__v1.preview.mp4"])
        log = {(e["clip"], e["preview"]): e for e in V.load_log(self.clinic, REC)}
        preview = log[("B1", True)]
        self.assertEqual((preview["disclaimer"]["required"], preview["disclaimer"]["present"], preview["disclaimer"]["frames_checked"],
                          preview["on_screen"]["preview_stamp"]), (True, True, 3, True))
        path = self.clinic.path(*preview["file"].split("/"))
        for share in (0.05, 0.5, 0.95):
            frame = V.grab_frame(path, preview["duration"] * share)
            self.assertEqual(O.band_present(frame, preview["disclaimer"]), (True, ""))
        ship = log[("A1", False)]
        bare = V.grab_frame(self.clinic.path(*ship["file"].split("/")), 1.0)
        self.assertFalse(O.band_present(bare, preview["disclaimer"])[0])      # the same look at a clip without one says no
        self.assertEqual(V.disclaimer_in_pixels(self.clinic.path(*ship["file"].split("/")), preview["disclaimer"], ship["duration"])[0], 3)
        self.assertTrue(V.disclaimer_in_pixels(self.clinic.path(*ship["file"].split("/")), preview["disclaimer"], ship["duration"])[1])

        self.sign_off(self.clinic)
        made = V.render_variants(self.clinic, REC, clip_ids=["B1"])
        self.assertEqual(made["made"], ["Output/video/%s/variants/B1-when-loading-is-not-enough__v1.mp4" % REC])
        final = next(e for e in V.load_log(self.clinic, REC) if e["clip"] == "B1" and not e["preview"])
        self.assertEqual((final["disclaimer"]["present"], final["on_screen"]["preview_stamp"], final["signed_off"]),
                         (True, False, "Tomas Okafor, 14 September 2026"))

        heard = lambda p: [(w["start"], w["end"], w["word"]) for w in V.clip_words(  # noqa: E731
            self.clinic_clips[1 if "B1" in p else 0], self.t_clinic, 0.0)[0]]
        checked = VF.verify(self.clinic, REC, hear=heard)
        self.assertEqual((checked["checked"], checked["failed"]), (2, []))
        self.assertEqual(next(r for r in checked["versions"] if r["clip"] == "B1")["checks"]["disclaimer"], {"frames": 5})
        record = DL.deliver(self.clinic, REC)
        self.assertEqual(sorted(v["file"] for v in record["videos"]),
                         ["A1-knee-pain-starts-at-the-hip__v1.mp4", "B1-when-loading-is-not-enough__v1.mp4"])
        self.assertEqual(VF.verify(self.clinic, REC, hear=lambda p: [])["failed"], ["A1 v1", "B1 v1"])
        self.assertEqual(VF.passed(self.clinic, REC), {})

    def test_finished_files_are_left_alone_unless_asked_and_a_changed_plan_is_made_again(self):
        self.plan(clip_ids=["B1"], n=1)
        first = V.render_variants(self.bakery, REC)
        path = self.bakery.path(*first["made"][0].split("/"))
        stamp = os.stat(path).st_mtime_ns
        second = V.render_variants(self.bakery, REC)
        self.assertEqual((second["made"], second["already"]), ([], first["made"]))
        self.assertEqual(os.stat(path).st_mtime_ns, stamp)
        third = V.render_variants(self.bakery, REC, again=True)
        self.assertEqual(third["made"], first["made"])
        plan = json.loads(Path(V.manifest_path(self.bakery, REC)).read_text(encoding="utf-8"))
        plan["clips"][0]["versions"][0]["fingerprint"] = "the plan changed"    # a finished file that no longer matches it
        common.write_json_atomic(V.manifest_path(self.bakery, REC), plan)
        self.assertEqual(V.render_variants(self.bakery, REC)["made"], first["made"])
        with open(path, "r+b") as f:
            f.truncate(2000)
        self.assertIn("changed since it was made", VF.verify(self.bakery, REC, hear=lambda p: [])["versions"][0]["problems"][0])

    def test_a_horizontal_video_is_reframed_around_the_face_or_the_centre_with_a_plain_note(self):
        right = lambda path, shape, duration: {"found": True, "x": 0.85, "y": 0.35, "h": 0.2, "seen_in": 9, "looked_at": 9,  # noqa: E731
                                               "by": "the face finder", "note": ""}
        m = V.plan_variants(self.bakery, REC, clip_ids=["B1"], n=1, face_finder=right)
        self.assertEqual(m["clips"][0]["notes"], [])
        V.render_variants(self.bakery, REC)
        applied = V.load_log(self.bakery, REC)[0]["applied"]
        self.assertEqual(applied["framed_around"], "the face")
        self.assertGreater(applied["slice_of_source"]["x"] + applied["slice_of_source"]["w"] / 2.0, 0.6 * 640)
        m = V.plan_variants(self.bakery, REC, clip_ids=["B1"], n=1)             # the built-in finder, whatever it can do here
        if not m["clips"][0]["framing"]["found"]:
            self.assertTrue(any("cropped around its centre" in n for n in m["clips"][0]["notes"]))
            V.render_variants(self.bakery, REC)
            applied = V.load_log(self.bakery, REC)[0]["applied"]
            self.assertEqual(applied["framed_around"], "the centre")
            self.assertAlmostEqual(applied["slice_of_source"]["x"] + applied["slice_of_source"]["w"] / 2.0, 320, delta=2)

    def test_captions_are_on_screen_while_someone_speaks_and_gone_in_a_long_silence(self):
        t = self.t_bakery
        clip = dict(self.bakery_clips[0], pieces=[[TV.when(t, "Most dense loaves", 0, AVA)[0] - 0.3,
                                                   TV.when(t, "not the clock.", 0, AVA)[1] + 0.5]])      # the 1.6s pause left in
        clip["actual_duration"] = round(clip["pieces"][0][1] - clip["pieces"][0][0], 2)
        self.ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=%.2f" % clip["actual_duration"], "-f", "lavfi", "-i",
                    "sine=frequency=220:duration=%.2f" % clip["actual_duration"], "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    os.path.join(common.output_dir(self.bakery, REC, "fine"), clip["file"]))
        self.write_report(self.bakery, [clip], shape={"orientation": "horizontal", "width": 640, "height": 360})
        m = self.plan(n=1)
        m["clips"][0]["versions"][0]["recipe"] = V.effective(V.RECIPES[0])
        common.write_json_atomic(V.manifest_path(self.bakery, REC), m)
        V.render_variants(self.bakery, REC)
        entry = V.load_log(self.bakery, REC)[0]
        path = self.bakery.path(*entry["file"].split("/"))
        words, _ = V.clip_words(clip, t, 0.0)
        speaking = next(w for w in words if w["word"] == "kitchen")
        silence_from = next(w for w in words if w["word"] == "there.")["end"]

        def plate_at(when):
            import numpy as np
            frame = V.grab_frame(path, when)
            strip = np.asarray(frame.crop((440, int(O.FB_CAPTION_CY - 30), 640, int(O.FB_CAPTION_CY + 30))), dtype="int16")
            return float((strip.max(axis=2) < 70).mean())                     # how much of the middle of the line is dark plate
        self.assertGreater(plate_at((speaking["start"] + speaking["end"]) / 2.0), 0.5)
        self.assertLess(plate_at(silence_from + 0.9), 0.2)
        self.assertEqual(entry["on_screen"]["shown_for"], O.HOOK_HOLD)


@unittest.skipUnless(TV._speech_model_is_here(), "the small speech model has not been downloaded yet "
                                                 "(python factory.py doctor --deep)")
class TestWithTheSpeechModel(RealClipsCase):
    """One thing needs the real model: proving the check listens to the FILE. A tone has no words
    in it, so a version made from a tone must fail however right its record looks."""

    def test_a_version_with_none_of_its_words_in_it_fails_however_good_its_record_looks(self):
        self.plan(clip_ids=["B1"], n=1)
        V.render_variants(self.bakery, REC)
        result = VF.verify(self.bakery, REC)
        self.assertEqual(result["failed"], ["B1 v1"])
        self.assertTrue(any("heard" in p for p in result["versions"][0]["problems"]))
        record = DL.deliver(self.bakery, REC)
        self.assertEqual(record["videos"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
