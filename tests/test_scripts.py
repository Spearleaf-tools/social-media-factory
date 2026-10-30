"""Short-form script tests: the checker, the batch record, the teleprompter, the index and the audit.

    python -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                        # noqa: E402
from smf.scripts import ScriptsError                          # noqa: E402
from smf.scripts import audit as A                            # noqa: E402
from smf.scripts import brief as B                            # noqa: E402
from smf.scripts import index as I                            # noqa: E402
from smf.scripts import manifest as M                         # noqa: E402
from smf.scripts import paths as P                            # noqa: E402
from smf.scripts import teleprompter as T                     # noqa: E402
from smf.scripts import validate as V                         # noqa: E402
from smf.scripts.scripts_cli import cli_scripts               # noqa: E402
from smf.studio import grounding                              # noqa: E402
from tests.test_brands import BAKERY, CLINIC                  # noqa: E402

BATCH = "week 1"

SCRIPT = """# %(title)s

- Brand: %(brand)s
- Batch: %(batch)s
- Script: %(sid)s
- Speaker: %(speaker)s
- Job: %(job)s
- Pillar: fix-my-loaf
- Format: hands in frame
- Length: 30 seconds
- Hook pattern: a belief corrected

## The one idea

%(idea)s

## Opening

Promise: %(promise)s
On screen: %(on_screen)s
Show: %(show)s
Say: %(say)s
%(opening_source)s
## Line 1

Say: %(line1)s
Show: %(line1_show)s
%(line1_source)s
## Line 2

Say: %(line2)s
Show: A second bowl of dough, the dent staying as a small dimple.

## Call to action

Kind: %(cta_kind)s
%(cta_extra)sSay: %(cta_say)s
Show: %(cta_show)s

## To shoot this

- Two loaves, one under-proofed, both cut in half
"""

BAKERY_SCRIPT = {
    "title": "Why a loaf comes out dense", "brand": "maple-and-main", "batch": BATCH, "sid": "01",
    "speaker": "person", "job": "trust",
    "idea": "A dense loaf is usually dough that went into the oven before it had proofed enough.",
    "promise": "why a loaf comes out dense, and how to check the proof",
    "on_screen": "Dense loaf? Check the proof",
    "show": "Two cut loaves side by side on the bench, one dense and one open.",
    "say": "A dense loaf is rarely the flour. It is the proof.",
    "opening_source": "",
    "line1": "Press a floured finger into the dough, about a knuckle deep.",
    "line1_show": "Close on a floured finger pressing into shaped dough.",
    "line1_source": "",
    "line2": "If the dent fills back slowly and leaves a dimple, it is ready to bake.",
    "cta_kind": "question", "cta_extra": "", "cta_say": "What does your dough do when you press it?",
    "cta_show": "Ava presses the dough once more and looks up.",
}
CLINIC_SCRIPT = dict(BAKERY_SCRIPT, **{
    "title": "Why heel pain comes back", "brand": "stride-physio",
    "idea": "Heel pain in runners comes back when the calf is never loaded again after resting.",
    "promise": "why heel pain in runners keeps coming back",
    "on_screen": "Heel pain keeps coming back?",
    "show": "A runner presses a thumb into a sore heel on the clinic bench.",
    "say": "If your heel pain keeps coming back, rest was never the whole answer.",
    "line1": "Rest calms the heel down, and it does nothing for the calf that feeds it.",
    "line1_show": "Tomas points from the heel up the back of the calf.",
    "line2": "So the first run back asks a weak calf to do a strong calf's job.",
    "cta_say": "Where does your heel hurt first, the morning or the run?",
    "cta_show": "Tomas sits back on the bench and looks at the camera.",
})


def script(base=None, **changes):
    parts = dict(base or BAKERY_SCRIPT)
    parts.update(changes)
    for key in ("opening_source", "line1_source"):
        if parts[key] and not parts[key].endswith("\n"):
            parts[key] += "\n"
    return SCRIPT % parts


def rules_of(report):
    return {(f.severity, f.rule) for f in report["findings"]}


def details_of(report, rule):
    return " ".join(f.detail for f in report["findings"] if f.rule == rule)


class ScriptsCase(unittest.TestCase):
    """Two brands in a folder whose name has a space, an apostrophe and an accent in it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="scripts ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        bakery = json.loads(json.dumps(BAKERY))
        bakery["style"] = {"banned_words": ["artisanal"]}
        bakery["audience"]["questions_they_ask"] = ["Why is my sourdough dense?", "Can I bake in a normal oven?"]
        bakery["offers"] = [{"id": "weekend-class", "name": "Saturday sourdough class", "what": "A hands-on class.",
                             "call_to_action": "Book a Saturday class"}]
        self.bakery = brands.create("maple-and-main", "Maple & Main Bakery", bakery)
        grounding.add_fact(self.bakery, "Our sourdough ferments for at least 18 hours", "Our own production sheet",
                           fact_id="ferment-18h")
        clinic = json.loads(json.dumps(CLINIC))
        clinic["compliance"] = {"pack": "health", "drop_terms": ["cures plantar fasciitis"],
                                "hold_terms": ["shockwave therapy"], "disclaimer": "This is general information.",
                                "sign_off_by": "Tomas Okafor"}
        self.clinic = brands.create("stride-physio", "Stride Physio", clinic)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    # -- helpers ---------------------------------------------------------------------------
    def pitch(self, title="Why a loaf comes out dense", topic="dense-loaf", **kw):
        p = {"title": title, "job": "trust", "speaker": "person", "topic_id": topic,
             "source_ref": "audience.questions_they_ask[0]", "hook": "Dense loaf? Check the proof"}
        p.update(kw)
        return p

    def batch_with(self, pitches=None, brand=None, batch=BATCH, approve=True):
        brand = brand or self.bakery
        M.create_batch(brand, batch)
        added, _skipped = M.add_pitches(brand, batch, pitches or [self.pitch()])
        if approve:
            M.set_status(brand, batch, [e["id"] for e in added], "approved")
        return added

    def write_script(self, text, brand=None, batch=BATCH, sid="01"):
        brand = brand or self.bakery
        entry = M.find(M.load(brand, batch), sid)
        path = P.file_in_batch(brand, batch, entry["script_file"])
        Path(path).write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_scripts(list(args))
        return code, out.getvalue()


# =============================================================================== the checker
class TestACleanScriptPasses(ScriptsCase):
    def test_a_well_formed_script_has_no_findings_and_its_sourcing_passes(self):
        report = V.check_script(script(), self.bakery, batch=BATCH, script_id="01")
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["ok"])
        self.assertEqual(report["sourcing"], "passed")

    def test_there_is_no_default_brand(self):
        for nothing in (None, ""):
            with self.assertRaises(brands.BrandError):
                V.check_script(script(), nothing)

    def test_a_script_is_only_checked_against_its_own_brand(self):
        report = V.check_script(script(brand="stride-physio"), self.bakery, batch=BATCH, script_id="01")
        self.assertIn(("ERROR", "wrong-brand"), rules_of(report))

    def test_a_speaker_the_brand_does_not_have_is_an_error(self):
        report = V.check_script(script(CLINIC_SCRIPT, speaker="company"), self.clinic)
        self.assertIn(("ERROR", "speaker"), rules_of(report))


class TestTheOpeningMustAgree(ScriptsCase):
    def test_words_on_screen_about_something_else(self):
        report = V.check_script(script(on_screen="Saturday class has eight places"), self.bakery)
        self.assertIn(("ERROR", "hook-disagrees"), rules_of(report))
        self.assertIn("the words on screen", details_of(report, "hook-disagrees"))

    def test_a_first_picture_that_does_not_show_the_subject(self):
        report = V.check_script(script(show="Ava waves from the shop doorway in the rain."), self.bakery)
        self.assertIn("the first picture", details_of(report, "hook-disagrees"))
        self.assertFalse(report["ok"])

    def test_a_first_spoken_line_that_promises_something_else(self):
        report = V.check_script(script(say="Our Saturday class runs for four hours."), self.bakery)
        self.assertIn("the first spoken line", details_of(report, "hook-disagrees"))

    def test_different_forms_of_the_same_word_still_agree(self):
        report = V.check_script(script(promise="how to tell when dough has proofed",
                                       on_screen="Is it proofing enough?",
                                       show="A bowl of doughs at three stages of proof.",
                                       say="Here is how I tell a proofed dough from one that needs longer."), self.bakery)
        self.assertNotIn(("ERROR", "hook-disagrees"), rules_of(report))

    def test_a_promise_with_no_subject_is_refused(self):
        report = V.check_script(script(promise="what you need to know"), self.bakery)
        self.assertIn(("ERROR", "hook-promise"), rules_of(report))


class TestTheBrandsRulesApplyToSpokenLines(ScriptsCase):
    LONG = ("When the dough has been sitting on the bench for most of the morning and the kitchen is warm it will "
            "have risen much further than you expect it to.")

    def test_a_spoken_sentence_over_the_brands_cap_blocks_and_the_cap_is_the_brands(self):
        self.assertGreater(len(self.LONG.split()), 22)
        report = V.check_script(script(line1=self.LONG), self.bakery)
        self.assertIn(("ERROR", "sentence-words"), rules_of(report))
        self.assertIn("Line 1", details_of(report, "sentence-words"))
        relaxed = brands.update("maple-and-main", {"style": {"max_sentence_words": 40}})
        self.assertNotIn(("ERROR", "sentence-words"), rules_of(V.check_script(script(line1=self.LONG), relaxed)))

    def test_a_never_mention_name_is_caught_when_spoken_and_when_filmed(self):
        spoken = V.check_script(script(line1="We deliver to Harbour Street Cafe every morning."), self.bakery)
        self.assertIn(("ERROR", "never-mention"), rules_of(spoken))
        filmed = V.check_script(script(line1_show="The van parked outside Harbour Street Cafe."), self.bakery)
        self.assertIn("the picture", details_of(filmed, "never-mention"))
        self.assertFalse(filmed["ok"])

    def test_the_brands_banned_words_and_long_dashes(self):
        report = V.check_script(script(line1="This is an artisanal loaf \u2014 pressed by hand."), self.bakery)
        self.assertIn(("ERROR", "banned-word"), rules_of(report))
        self.assertIn(("ERROR", "em-dash"), rules_of(report))

    def test_a_compliance_term_blocks_the_clinic_and_is_fine_for_the_bakery(self):
        line = "Our plan cures plantar fasciitis."
        clinic = V.check_script(script(CLINIC_SCRIPT, line1=line), self.clinic)
        self.assertIn(("ERROR", "never-publish"), rules_of(clinic))
        self.assertFalse(clinic["ok"])
        bakery = V.check_script(script(line1=line), self.bakery)
        self.assertNotIn(("ERROR", "never-publish"), rules_of(bakery))
        self.assertTrue(bakery["ok"])

    def test_a_sign_off_term_does_not_block_but_names_who_signs(self):
        report = V.check_script(script(CLINIC_SCRIPT, line1="We also offer shockwave therapy for stubborn heels."),
                                self.clinic)
        self.assertTrue(report["ok"])
        self.assertTrue(report["needs_sign_off"])
        self.assertEqual(report["sign_off_by"], "Tomas Okafor")


class TestTheShapeOfAScript(ScriptsCase):
    def test_every_spoken_line_needs_a_visual_direction(self):
        report = V.check_script(script(line1_show=""), self.bakery)
        self.assertIn(("ERROR", "no-picture"), rules_of(report))

    def test_one_idea_means_one_sentence(self):
        report = V.check_script(script(idea="A dense loaf is under-proofed. Also, steam makes the crust."), self.bakery)
        self.assertIn(("ERROR", "one-idea"), rules_of(report))

    def test_text_without_a_known_label_cannot_hide_from_the_checks(self):
        text = script().replace("Say: Press a floured finger", "Spoken line: Press a floured finger")
        report = V.check_script(text, self.bakery)
        self.assertIn(("ERROR", "format"), rules_of(report))
        self.assertIn("no label", details_of(report, "format"))

    def test_the_call_to_action_has_to_fit_the_job(self):
        selling = dict(cta_kind="offer", cta_extra="Offer: weekend-class\n", cta_say="Book a Saturday class.")
        self.assertIn("trust script", details_of(V.check_script(script(**selling), self.bakery), "call-to-action"))
        self.assertTrue(V.check_script(script(job="leads", **selling), self.bakery)["ok"])

    def test_an_offer_the_brand_does_not_sell_is_refused(self):
        report = V.check_script(script(job="leads", cta_kind="offer", cta_extra="Offer: wholesale-bread\n"), self.bakery)
        self.assertIn("no offer called 'wholesale-bread'", details_of(report, "call-to-action"))

    def test_a_keyword_nobody_set_up_is_refused(self):
        report = V.check_script(script(job="leads", cta_kind="keyword", cta_extra="Keyword: STARTER\n",
                                       cta_say="Comment STARTER and I will send you the feeding card."), self.bakery)
        self.assertIn("STARTER", details_of(report, "call-to-action"))
        self.assertFalse(report["ok"])

    def test_an_untouched_starter_file_is_unwritten_not_a_pile_of_errors(self):
        starter = B.starter("Why a loaf comes out dense", "maple-and-main", BATCH, "01", "person", "trust")
        self.assertTrue(B.parse(starter).unwritten)
        self.assertEqual(T.render(B.parse(starter)).strip(), "")


class TestSourcing(ScriptsCase):
    FACT = "Our dough ferments for at least 18 hours before it is shaped."

    def test_a_factual_line_with_no_source_note_blocks(self):
        report = V.check_script(script(line1=self.FACT), self.bakery)
        self.assertIn(("ERROR", "no-source"), rules_of(report))
        self.assertEqual(report["sourcing"], "blocked")

    def test_a_source_that_points_at_the_brands_own_fact_passes(self):
        report = V.check_script(script(line1=self.FACT, line1_source="Source: fact:ferment-18h"), self.bakery)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["sourcing"], "passed")

    def test_a_spelled_out_number_is_still_a_fact_and_still_traces(self):
        line = "Our dough ferments for at least eighteen hours before it is shaped."
        self.assertIn(("ERROR", "no-source"), rules_of(V.check_script(script(line1=line), self.bakery)))
        ok = V.check_script(script(line1=line, line1_source="Source: fact:ferment-18h"), self.bakery)
        self.assertEqual(ok["sourcing"], "passed")

    def test_counting_the_scripts_own_parts_is_not_a_fact(self):
        self.assertFalse(V.states_a_fact("Here are 3 things to check before you bake."))
        self.assertFalse(V.states_a_fact("Cut the two loaves in half."))
        self.assertTrue(V.states_a_fact("About 40 percent of home loaves are under-proofed."))

    def test_a_pointer_to_nothing_blocks(self):
        report = V.check_script(script(line1=self.FACT, line1_source="Source: fact:no-such-fact"), self.bakery)
        self.assertIn(("ERROR", "source-missing"), rules_of(report))

    def test_a_number_the_brand_cannot_show_is_labelled_unverified_not_passed(self):
        report = V.check_script(script(line1="We sell about 300 loaves every Saturday.",
                                       line1_source="Source: Ava said so on a call"), self.bakery)
        self.assertTrue(report["ok"])
        self.assertEqual(report["sourcing"], "unverified")
        self.assertIn(("WARN", "unverified"), rules_of(report))

    def test_the_opening_is_never_a_fact_the_brand_cannot_back(self):
        hook = dict(on_screen="300 dense loaves a week", say="We see 300 dense loaves a week from home bakers.",
                    promise="why a loaf comes out dense", opening_source="Source: Ava said so on a call")
        report = V.check_script(script(**hook), self.bakery)
        self.assertIn(("ERROR", "hook-unbacked"), rules_of(report))
        self.assertEqual(report["sourcing"], "blocked")
        backed = dict(on_screen="18 hours for a loaf that is not dense",
                      say="Our loaf is not dense because the dough ferments for 18 hours.",
                      promise="why a loaf comes out dense", opening_source="Source: fact:ferment-18h")
        self.assertTrue(V.check_script(script(**backed), self.bakery)["ok"])


# =============================================================================== the teleprompter
class TestTeleprompter(ScriptsCase):
    MARKED = "> **Press** a _floured_ finger [pause] into the `dough`, see [our method](https://example.com/method)."

    def test_it_holds_only_spoken_words_with_every_marking_removed(self):
        text = T.render(B.parse(script(line1=self.MARKED, line1_source="Source: fact:ferment-18h")))
        for mark in ("*", "_", "`", "[", "]", "#", ">", "http", "pause"):
            self.assertNotIn(mark, text, mark)
        for label in ("Say:", "Show:", "On screen:", "Source:", "Promise:", "Kind:", "fact:", "side by side", "bench"):
            self.assertNotIn(label, text, label)
        self.assertIn("Press a floured finger into the dough, see our method.", text.replace("\n", " "))

    def test_lines_are_paced_for_reading_aloud(self):
        long_line = ("When the dough has rested overnight in the cold room, and the kitchen has warmed up, "
                     "press it gently because a cold dough springs back far more slowly than a warm one does.")
        text = T.render(B.parse(script(line1=long_line)))
        lines = [ln for ln in text.splitlines() if ln.strip()]
        self.assertTrue(all(len(ln.split()) <= T.LINE_WORDS for ln in lines), lines)
        self.assertEqual(" ".join(lines).count("press it gently"), 1)             # nothing lost, nothing repeated
        self.assertIn("\n\n", text)                                               # a breath between script lines
        self.assertEqual(sum(len(ln.split()) for ln in lines), B.parse(script(line1=long_line)).spoken_words())

    def test_one_file_per_script_made_on_a_pass_and_stale_when_the_words_change(self):
        self.batch_with()
        path = self.write_script(script())
        code, _out = self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)
        self.assertEqual(code, 0)
        entry = M.find(M.load(self.bakery, BATCH), "01")
        tele = P.file_in_batch(self.bakery, BATCH, entry["teleprompter_file"])
        self.assertTrue(os.path.isfile(tele))
        self.assertEqual(T.state(self.bakery, BATCH, entry, B.parse(script()))[0], "current")

        changed = script(line2="If the dent stays as a dimple, bake it now.")
        Path(path).write_text(changed, encoding="utf-8")
        self.assertEqual(T.state(self.bakery, BATCH, entry, B.parse(changed))[0], "stale")
        _data, rows = I.survey(self.bakery, BATCH)
        self.assertEqual(rows[0]["entry"]["status"], "draft")                     # a changed script is a draft again
        code, _out = self.run_cli("teleprompter", "--brand", "maple-and-main", "--batch", BATCH, "--check")
        self.assertEqual(code, 1)

        self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)   # passing again re-makes it
        entry = M.find(M.load(self.bakery, BATCH), "01")
        self.assertEqual(T.state(self.bakery, BATCH, entry, B.parse(changed))[0], "current")
        self.assertIn("bake it now", Path(tele).read_text(encoding="utf-8"))

    def test_a_changed_picture_voids_the_check_but_not_the_teleprompter(self):
        self.batch_with()
        path = self.write_script(script())
        self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)
        repainted = script(line1_show="A wide shot of the whole bench.")
        Path(path).write_text(repainted, encoding="utf-8")
        _data, rows = I.survey(self.bakery, BATCH)
        self.assertEqual((rows[0]["entry"]["status"], rows[0]["teleprompter"]), ("draft", "current"))

    def test_a_hand_edit_and_a_deleted_file_are_both_noticed(self):
        self.batch_with()
        self.write_script(script())
        self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)
        entry = M.find(M.load(self.bakery, BATCH), "01")
        tele = P.file_in_batch(self.bakery, BATCH, entry["teleprompter_file"])
        Path(tele).write_text("Something typed in by hand.\n", encoding="utf-8")
        self.assertEqual(T.state(self.bakery, BATCH, entry, B.parse(script()))[0], "edited")
        os.unlink(tele)
        self.assertEqual(T.state(self.bakery, BATCH, entry, B.parse(script()))[0], "missing")


# =============================================================================== the batch record
class TestManifestSteps(ScriptsCase):
    def test_pitches_get_ids_in_order_and_start_as_pitched(self):
        added = self.batch_with([self.pitch(), self.pitch("Baking in a normal oven", "normal-oven")], approve=False)
        self.assertEqual([(e["id"], e["status"]) for e in added], [("01", "pitched"), ("02", "pitched")])
        self.assertEqual(added[1]["script_file"], "02-baking-in-a-normal-oven.md")

    def test_a_pitch_with_no_source_in_the_brands_material_is_refused_and_nothing_is_saved(self):
        M.create_batch(self.bakery, BATCH)
        for bad in (self.pitch(source_ref=""), self.pitch(source_ref="fact:no-such-fact"), self.pitch(job="fame"),
                    self.pitch(speaker="doctor")):
            with self.assertRaises((ScriptsError, brands.BrandError)):
                M.add_pitches(self.bakery, BATCH, [self.pitch("A fine pitch", "fine"), bad])
        self.assertEqual(M.load(self.bakery, BATCH)["scripts"], [])

    def test_one_pitch_per_topic_and_never_a_subject_an_earlier_batch_covered(self):
        self.batch_with()
        _added, skipped = M.add_pitches(self.bakery, BATCH, [self.pitch("The same subject again")])
        self.assertIn("this batch", skipped[0][1])
        M.create_batch(self.bakery, "week 2")
        added, skipped = M.add_pitches(self.bakery, "week 2", [self.pitch(), self.pitch("Normal ovens", "oven")])
        self.assertEqual([e["title"] for e in added], ["Normal ovens"])
        self.assertIn("week 1/01", skipped[0][1])
        again, _ = M.add_pitches(self.bakery, "week 2", [self.pitch()], allow_repeat=True)
        self.assertEqual(len(again), 1)

    def test_a_recording_batch_takes_one_pitch_per_body(self):
        cut_list = self.bakery.path("Inputs", "Recordings", "counter chat", "cut-list.md")
        os.makedirs(os.path.dirname(cut_list))
        Path(cut_list).write_text("# Cut list\n\n## Body A\n\n## Body B\n", encoding="utf-8")
        ref = "Inputs/Recordings/counter chat/cut-list.md"
        M.create_batch(self.bakery, "from the counter", track="recording", source=ref)
        with self.assertRaises(M.ManifestError):
            M.add_pitches(self.bakery, "from the counter", [self.pitch(source_ref=ref, topic_id="")])
        added, skipped = M.add_pitches(self.bakery, "from the counter", [
            self.pitch("Dense loaves", "", body="A", source_ref=ref), self.pitch("Dense again", "", body="A", source_ref=ref),
            self.pitch("Cold dough", "", body="B", source_ref=ref)])
        self.assertEqual([e["body"] for e in added], ["A", "B"])
        self.assertEqual(len(skipped), 1)

    def test_nothing_is_written_checked_or_filmed_before_a_person_says_yes(self):
        self.batch_with(approve=False)
        with self.assertRaises(M.ManifestError) as cm:
            M.set_status(self.bakery, BATCH, ["01"], "recorded")
        self.assertIn("approve", str(cm.exception))
        code, out = self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH, "--script", "01")
        self.assertEqual(code, 1)
        self.assertIn("approve", out)

    def test_only_the_checker_marks_a_script_validated_and_only_validated_scripts_are_filmed(self):
        self.batch_with()
        for by_hand in ("draft", "validated"):
            with self.assertRaises(M.ManifestError):
                M.set_status(self.bakery, BATCH, ["01"], by_hand)
        with self.assertRaises(M.ManifestError):
            M.set_status(self.bakery, BATCH, ["01"], "recorded")
        self.write_script(script(line1_show=""))
        self.assertEqual(self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)[0], 1)
        self.assertEqual(M.find(M.load(self.bakery, BATCH), "01")["status"], "draft")
        self.write_script(script())
        self.assertEqual(self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)[0], 0)
        self.assertEqual(M.find(M.load(self.bakery, BATCH), "1")["status"], "validated")
        code, _ = self.run_cli("status", "--brand", "maple-and-main", "--batch", BATCH, "--recorded", "1")
        self.assertEqual((code, M.find(M.load(self.bakery, BATCH), "01")["status"]), (0, "recorded"))

    def test_a_script_edited_after_it_passed_cannot_be_marked_as_filmed(self):
        self.batch_with()
        path = self.write_script(script())
        self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)
        Path(path).write_text(script(line1="We deliver to Harbour Street Cafe."), encoding="utf-8")
        code, _out = self.run_cli("status", "--brand", "maple-and-main", "--batch", BATCH, "--recorded", "01")
        self.assertEqual(code, 1)
        self.assertEqual(M.find(M.load(self.bakery, BATCH), "01")["status"], "draft")

    def test_approving_writes_a_starter_with_the_call_to_action_chosen_for_the_job(self):
        self.batch_with([self.pitch(), self.pitch("What the class covers", "class", job="leads", speaker="company",
                                                  source_ref="offer:weekend-class")], approve=False)
        code, _ = self.run_cli("approve", "--brand", "maple-and-main", "--batch", BATCH, "--scripts", "2", "--cut", "1")
        self.assertEqual(code, 0)
        data = M.load(self.bakery, BATCH)
        self.assertEqual([s["status"] for s in data["scripts"]], ["cut", "approved"])
        starter = B.parse(Path(P.file_in_batch(self.bakery, BATCH, data["scripts"][1]["script_file"])).read_text(encoding="utf-8"))
        self.assertEqual((starter.cta.kind, starter.cta.offer, starter.job), ("offer", "weekend-class", "lead_gen"))
        self.assertEqual(starter.header["brand"], "maple-and-main")
        self.assertFalse(os.path.exists(P.file_in_batch(self.bakery, BATCH, data["scripts"][0]["script_file"])))

    def test_approving_never_overwrites_a_script_someone_already_wrote(self):
        self.batch_with(approve=False)
        entry = M.load(self.bakery, BATCH)["scripts"][0]
        path = P.file_in_batch(self.bakery, BATCH, entry["script_file"])
        Path(path).write_text(script(), encoding="utf-8")
        self.run_cli("approve", "--brand", "maple-and-main", "--batch", BATCH, "--all")
        self.assertEqual(Path(path).read_text(encoding="utf-8"), script())


class TestManifestLock(ScriptsCase):
    def test_a_held_lock_makes_the_next_writer_wait_then_stop_without_changing_anything(self):
        self.batch_with(approve=False)
        before = Path(P.manifest_path(self.bakery, BATCH)).read_text(encoding="utf-8")
        with M.Lock(P.batch_dir(self.bakery, BATCH)):
            with self.assertRaises(M.ManifestBusy) as cm:
                M.update(self.bakery, BATCH, lambda data: data["scripts"].clear(), wait_seconds=0.2)
        self.assertIn("Nothing was changed", str(cm.exception))
        self.assertEqual(Path(P.manifest_path(self.bakery, BATCH)).read_text(encoding="utf-8"), before)
        M.set_status(self.bakery, BATCH, ["01"], "approved")                       # and it is free again afterwards

    def test_the_lock_is_released_when_a_change_fails_and_nothing_is_written(self):
        self.batch_with(approve=False)
        def broken(data):
            data["scripts"][0]["status"] = "approved"
            raise RuntimeError("stopped half way")
        with self.assertRaises(RuntimeError):
            M.update(self.bakery, BATCH, broken)
        self.assertFalse(os.path.exists(os.path.join(P.batch_dir(self.bakery, BATCH), M.LOCK_NAME)))
        self.assertEqual(M.load(self.bakery, BATCH)["scripts"][0]["status"], "pitched")

    def test_a_lock_left_behind_by_a_crash_is_taken_over(self):
        self.batch_with(approve=False)
        lock = os.path.join(P.batch_dir(self.bakery, BATCH), M.LOCK_NAME)
        Path(lock).write_text("999999 0", encoding="ascii")
        old = time.time() - M.LOCK_STALE_SECONDS - 5
        os.utime(lock, (old, old))
        M.set_status(self.bakery, BATCH, ["01"], "approved")
        self.assertEqual(M.load(self.bakery, BATCH)["scripts"][0]["status"], "approved")

    def test_writers_finishing_at_the_same_moment_lose_nothing(self):
        M.create_batch(self.bakery, BATCH)
        errors = []

        def one(n):
            try:
                M.add_pitches(self.bakery, BATCH, [self.pitch("Subject number %d" % n, "topic-%d" % n)])
            except Exception as e:                                                # noqa: BLE001
                errors.append(e)
        threads = [threading.Thread(target=one, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        scripts = M.load(self.bakery, BATCH)["scripts"]
        self.assertEqual(sorted(s["id"] for s in scripts), ["%02d" % n for n in range(1, 9)])
        self.assertEqual(len({s["topic_id"] for s in scripts}), 8)
        leftovers = [f for f in os.listdir(P.batch_dir(self.bakery, BATCH)) if f.startswith(".tmp-") or f.endswith(".lock")]
        self.assertEqual(leftovers, [])


class TestADamagedManifestStopsEverything(ScriptsCase):
    def damage(self, text="{ this is not json"):
        path = P.manifest_path(self.bakery, BATCH)
        Path(path).write_text(text, encoding="utf-8")
        return path

    def test_it_is_never_read_as_an_empty_batch_and_never_overwritten(self):
        self.batch_with()
        path = self.damage()
        with self.assertRaises(M.ManifestError) as cm:
            M.load(self.bakery, BATCH)
        self.assertIn("damaged", str(cm.exception))
        with self.assertRaises(M.ManifestError):
            M.add_pitches(self.bakery, BATCH, [self.pitch("A new subject", "new")])
        with self.assertRaises(M.ManifestError):
            I.write(self.bakery, BATCH)
        self.assertEqual(Path(path).read_text(encoding="utf-8"), "{ this is not json")
        for step in (["status", "--batch", BATCH], ["validate", "--batch", BATCH], ["index", "--batch", BATCH],
                     ["audit", "--batch", BATCH], ["status"]):
            code, out = self.run_cli(step[0], "--brand", "maple-and-main", *step[1:])
            self.assertEqual(code, 1, step)
            self.assertIn("damaged", out)
            self.assertNotIn("Traceback", out)

    def test_a_damaged_record_in_one_batch_stops_pitching_in_another(self):
        self.batch_with()
        self.damage()
        M.create_batch(self.bakery, "week 2")
        with self.assertRaises(M.ManifestError):
            M.add_pitches(self.bakery, "week 2", [self.pitch()])                   # it might be a repeat; nobody can tell

    def test_the_wrong_shape_is_refused_too(self):
        self.batch_with()
        for wrong in ('{"brand": "maple-and-main", "batch": "week 1", "scripts": {}}', "[]",
                      '{"brand": "maple-and-main", "batch": "week 1", "scripts": [{"id": "01", "status": "published"}]}',
                      '{"brand": "maple-and-main", "batch": "week 1", "scripts": [{"id": "01", "status": "draft"}, '
                      '{"id": "01", "status": "draft"}]}'):
            self.damage(wrong)
            with self.assertRaises(M.ManifestError):
                M.load(self.bakery, BATCH)

    def test_a_batch_that_does_not_exist_is_an_error_that_lists_what_does(self):
        self.batch_with()
        with self.assertRaises(M.ManifestError) as cm:
            M.load(self.bakery, "week 9")
        self.assertIn("week 1", str(cm.exception))
        with self.assertRaises(M.ManifestError):
            M.create_batch(self.bakery, BATCH)                                      # and an existing one is never reset


# =============================================================================== two brands never mix
class TestEverythingStaysInsideTheRightBrand(ScriptsCase):
    def test_a_whole_run_only_touches_the_named_brands_folder(self):
        self.run_cli("new-batch", "--brand", "maple-and-main", "--name", BATCH)
        pitches = os.path.join(self.tmp.name, "pitches.json")
        Path(pitches).write_text(json.dumps([self.pitch()]), encoding="utf-8")
        self.run_cli("pitch", "--brand", "maple-and-main", "--batch", BATCH, "--from", pitches)
        self.run_cli("approve", "--brand", "maple-and-main", "--batch", BATCH, "--all")
        self.write_script(script())
        self.assertEqual(self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)[0], 0)
        self.run_cli("index", "--brand", "maple-and-main", "--batch", BATCH)
        folder = self.bakery.path("Studio", "scripts", BATCH)
        self.assertEqual(sorted(os.listdir(folder)),
                         ["01-why-a-loaf-comes-out-dense.md", "01-why-a-loaf-comes-out-dense.teleprompter.txt",
                          "INDEX.md", "manifest.json", "pitches.md"])
        self.assertFalse(os.path.exists(self.clinic.path("Studio", "scripts")))
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["Client", "pitches.json"])
        index = Path(folder, "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("Maple & Main Bakery", index)
        self.assertIn("ready to film", index)
        self.assertNotIn("\u2014", index)

    def test_a_batch_copied_into_another_brands_folder_is_refused(self):
        self.batch_with()
        shutil.copytree(self.bakery.path("Studio", "scripts"), self.clinic.path("Studio", "scripts"))
        with self.assertRaises(M.ManifestError) as cm:
            M.load(self.clinic, BATCH)
        self.assertIn("belongs to 'maple-and-main'", str(cm.exception))
        code, out = self.run_cli("status", "--brand", "stride-physio", "--batch", BATCH)
        self.assertEqual(code, 1)

    def test_the_same_batch_name_in_two_brands_is_two_separate_batches(self):
        self.batch_with()
        self.batch_with([self.pitch("Why heel pain comes back", "heel", source_ref="A question from the front desk")],
                        brand=self.clinic)
        self.assertEqual(M.load(self.bakery, BATCH)["scripts"][0]["title"], "Why a loaf comes out dense")
        self.assertEqual(M.load(self.clinic, BATCH)["scripts"][0]["title"], "Why heel pain comes back")
        self.assertEqual(set(M.already_made(self.clinic)), {"topic:heel", "slug:why-heel-pain-comes-back"})

    def test_every_step_needs_a_brand_and_an_unknown_brand_is_an_error_not_a_guess(self):
        for step in ("new-batch", "pitch", "approve", "validate", "teleprompter", "index", "status", "audit"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                cli_scripts([step, "--batch", BATCH, "--name", BATCH])
        code, out = self.run_cli("status", "--brand", "harbour-bakes")
        self.assertEqual(code, 1)
        self.assertIn("maple-and-main", out)                                       # it says what DOES exist


class TestHostileNames(ScriptsCase):
    def test_a_batch_name_can_never_leave_the_brands_folder(self):
        for bad in ("../escape", "..", "a/b", "a\\b", "/tmp/x", "C:\\x", "", " lead", "trailing.", "con", "NUL.txt",
                    "week*1", "x" * 80, None):
            with self.assertRaises(ScriptsError, msg=repr(bad)):
                M.create_batch(self.bakery, bad)
        self.assertFalse(os.path.exists(self.bakery.path("Studio", "scripts")))
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["Client"])

    def test_spaces_dots_and_dashes_are_fine(self):
        M.create_batch(self.bakery, "Week 1. take-2")
        self.assertEqual(P.list_batches(self.bakery), ["Week 1. take-2"])

    def test_a_file_name_in_a_hand_edited_record_cannot_point_outside_the_batch(self):
        self.batch_with()
        path = P.manifest_path(self.bakery, BATCH)
        outside = os.path.join(self.tmp.name, "outside.md")
        Path(outside).write_text(script(), encoding="utf-8")
        for hostile in ("../../../../outside.md", outside, "sub/01.md", ".."):
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            data["scripts"][0]["script_file"] = hostile
            data["scripts"][0]["teleprompter_file"] = hostile
            Path(path).write_text(json.dumps(data), encoding="utf-8")
            code, out = self.run_cli("validate", "--brand", "maple-and-main", "--batch", BATCH)
            self.assertEqual(code, 1, hostile)
            self.assertIn("not inside its own folder", out)
        self.assertEqual(Path(outside).read_text(encoding="utf-8"), script())

    def test_titles_with_odd_characters_become_plain_file_names(self):
        added = self.batch_with([self.pitch("Crème brûlée? It's / not \\ bread: ../ really", "creme")])
        self.assertEqual(added[0]["script_file"], "01-creme-brulee-it-s-not-bread-really.md")


# =============================================================================== the audit
class TestOutlierMaths(unittest.TestCase):
    def test_typical_is_the_median_and_standing_out_is_a_multiple_of_it(self):
        got = A.outliers({"01": 100, "02": 110, "03": 120, "04": 1000, "05": 30})
        self.assertEqual(got["typical"], 110)
        self.assertEqual(got["high"], [("04", 9.09)])
        self.assertEqual(got["low"], [("05", 0.27)])
        self.assertEqual(A.outliers({"01": 100, "02": 110, "03": 120, "04": 320})["high"], [])      # 2.9 times is not 3
        self.assertEqual(A.outliers({"01": 100, "02": 110, "03": 120, "04": 320}, times=2.5)["high"], [("04", 2.78)])

    def test_one_runaway_video_does_not_move_what_counts_as_typical(self):
        self.assertEqual(A.outliers({"01": 90, "02": 100, "03": 110, "04": 100, "05": 1000000})["typical"], 100)

    def test_too_few_scripts_or_a_batch_of_zeros_names_no_outliers(self):
        few = A.outliers({"01": 10, "02": 5000, "03": 12})
        self.assertEqual((few["typical"], few["high"], few["low"]), (None, [], []))
        self.assertIn("at least 4", few["note"])
        zeros = A.outliers({"01": 0, "02": 0, "03": 0, "04": 9})
        self.assertEqual(zeros["high"], [])
        self.assertIn("zero", zeros["note"])
        with self.assertRaises(A.AuditError):
            A.outliers({"01": 1, "02": 2, "03": 3, "04": 4}, times=1)

    def test_rates_are_only_worked_out_from_numbers_that_exist(self):
        self.assertEqual(A.with_rates({"views": 2000, "saves": 30, "sends": 10})["kept_per_1000"], 20.0)
        self.assertNotIn("kept_per_1000", A.with_rates({"views": 2000, "saves": 30}))
        self.assertNotIn("leads_per_1000", A.with_rates({"views": 0, "leads": 3}))


def rows(*triples):
    """(value, hook_pattern, format) per script."""
    return [{"id": "%02d" % i, "title": "s%d" % i, "value": v,
             "variables": {"hook_pattern": h, "format": f, "speaker": "person", "length_band": "30 to 45 seconds",
                           "pillar": "", "cta_kind": c}}
            for i, (v, h, f, c) in enumerate(triples, start=1)]


class TestTheSingleVariableRule(unittest.TestCase):
    EVEN = {"typical": 100, "high": [], "low": [], "note": ""}

    def test_exactly_one_thing_to_change_and_everything_else_is_held(self):
        batch = rows((300, "a question", "hands in frame", "save"), (280, "a question", "talking to camera", "share"),
                     (320, "a question", "hands in frame", "share"), (100, "the result first", "talking to camera", "save"),
                     (90, "the result first", "hands in frame", "save"), (110, "the result first", "talking to camera", "share"))
        test, why = A.propose_test(batch, "views", self.EVEN)
        self.assertEqual(why, "")
        self.assertIsInstance(test, dict)                                           # one test, never a list of them
        self.assertEqual(test["variable"], "hook_pattern")
        self.assertIn("'a question'", test["change"])
        self.assertNotIn("the opening pattern", test["hold_still"])
        self.assertEqual(set(test["hold_still"]), set(A.VARIABLES.values()) - {"the opening pattern"})
        self.assertEqual(test["judge_by"], "views")

    def test_two_things_that_always_moved_together_are_named_and_the_earlier_one_is_tested(self):
        batch = rows((300, "a question", "hands in frame", "save"), (310, "a question", "hands in frame", "save"),
                     (100, "the result first", "talking to camera", "save"), (95, "the result first", "talking to camera", "save"))
        test, _ = A.propose_test(batch, "views", self.EVEN)
        self.assertEqual(test["variable"], "hook_pattern")
        self.assertEqual(test["moved_together_with"], ["the format"])
        self.assertIn("the format", test["hold_still"])

    def test_a_clear_winner_means_repeat_its_shape_and_change_only_the_subject(self):
        batch = rows((900, "a question", "hands in frame", "save"), (100, "a question", "hands in frame", "save"),
                     (95, "the result first", "talking to camera", "save"), (105, "the result first", "talking to camera", "save"))
        test, _ = A.propose_test(batch, "views", A.outliers({r["id"]: r["value"] for r in batch}))
        self.assertEqual((test["kind"], test["variable"]), ("repeat", "subject"))
        self.assertEqual(test["hold_still"], list(A.VARIABLES.values()))

    def test_no_clear_gap_or_a_single_example_proposes_nothing(self):
        alike = rows((100, "a question", "hands in frame", "save"), (104, "a question", "hands in frame", "save"),
                     (98, "the result first", "hands in frame", "save"), (101, "the result first", "hands in frame", "save"))
        test, why = A.propose_test(alike, "views", self.EVEN)
        self.assertIsNone(test)
        self.assertIn("ONE thing", why)
        lone = rows((500, "a question", "hands in frame", "save"), (100, "the result first", "hands in frame", "save"),
                    (110, "the result first", "hands in frame", "save"), (90, "the result first", "hands in frame", "save"))
        self.assertIsNone(A.propose_test(lone, "views", self.EVEN)[0])              # one script is an anecdote


class TestAuditOnABatch(ScriptsCase):
    def setUp(self):
        super().setUp()
        pitches = [self.pitch("Subject %d" % n, "t%d" % n, job="reach",
                              hook_pattern="a question" if n <= 3 else "the result first") for n in range(1, 7)]
        self.batch_with(pitches)
        self.numbers = os.path.join(self.tmp.name, "numbers.csv")

    def test_it_uses_only_the_persons_own_numbers_and_says_who_has_none(self):
        Path(self.numbers).write_text("script,Views,Saves,shares\n1,\"3,000\",30,12\n2,2800,20,9\n3,3300,41,15\n"
                                      "4,1000,5,1\n5,900,4,0\n", encoding="utf-8")
        code, out = self.run_cli("audit", "--brand", "maple-and-main", "--batch", BATCH, "--numbers", self.numbers)
        self.assertEqual(code, 0)
        self.assertIn("Change one thing, and only one", out)
        self.assertIn("'a question'", out)
        stored = M.find(M.load(self.bakery, BATCH), "01")["numbers"]
        self.assertEqual(stored, {"views": 3000.0, "saves": 30.0, "sends": 12.0})
        report = Path(self.bakery.path("Studio", "scripts", BATCH, "audit.md")).read_text(encoding="utf-8")
        self.assertIn("06 (Subject 6)", report)                                     # left out, and named
        self.assertIn("## The one thing to test next", report)
        self.assertEqual(report.count("## The one thing to test next"), 1)
        self.assertIn("The stop", report)
        self.assertNotIn("\u2014", report)

    def test_no_numbers_means_no_pattern_and_nothing_is_made_up(self):
        result = A.run(self.bakery, BATCH)
        self.assertEqual((result["ranking"], result["test"], result["high"]), ([], None, []))
        self.assertIn("no numbers", result["recommendation"])

    def test_numbers_for_a_script_the_batch_does_not_have_are_refused(self):
        with self.assertRaises(A.AuditError):
            A.run(self.bakery, BATCH, supplied={"42": {"views": 10}})

    def test_the_brands_local_metrics_archive_is_read_when_there_is_one(self):
        folder = self.bakery.path("_state", "metrics")
        os.makedirs(folder)
        Path(folder, "2026-10.json").write_text(json.dumps({"rows": [
            {"script": "%s/0%d" % (BATCH, n), "platform": "instagram", "views": v} for n, v in
            ((1, 3000), (2, 2900), (3, 3100), (4, 1000), (5, 950), (6, 1050))]
            + [{"script": "another batch/01", "views": 999999}]}), encoding="utf-8")
        Path(folder, "broken.json").write_text("{ nope", encoding="utf-8")
        result = A.run(self.bakery, BATCH)
        self.assertEqual([r["id"] for r in result["ranking"]], ["03", "01", "02", "06", "04", "05"])
        self.assertTrue(any("broken.json" in n for n in result["notes"]))
        self.assertNotIn(999999, [r["value"] for r in result["ranking"]])          # another batch's numbers stay out

    def test_scripts_written_for_different_jobs_are_not_judged_together(self):
        M.add_pitches(self.bakery, BATCH, [self.pitch("A trust one", "t7", job="trust")])
        supplied = {"%02d" % n: {"views": 1000 + n} for n in range(1, 8)}
        result = A.run(self.bakery, BATCH, supplied=supplied)
        self.assertEqual(result["job"], "reach")
        self.assertNotIn("07", [r["id"] for r in result["ranking"]])
        self.assertTrue(any("mixes jobs" in n for n in result["notes"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
