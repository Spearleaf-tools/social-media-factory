"""Clip-engine tests: the gate is the brand's gate, an off-camera voice never gets into a clip,
every hook is words that were really said, and cuts line up on words rather than on times.

    python -m unittest discover -s tests -t . -v

Nothing here uses the network or a key. The two recordings below are invented: a baker being
interviewed in her shop, and a physiotherapist talking to a presenter. Tests that need the video
programs or the local speech model are skipped, with the reason, when those are not installed;
when they are, the tests make their own media (colour bars and a tone) in a throwaway folder
whose name has a space, an apostrophe and an accent.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands, keys                                              # noqa: E402
from smf.brands import BrandError                                         # noqa: E402
from smf.video import common, cutlist, find_clips, fine_cut, gate, rough_cut, transcribe, validate_cuts  # noqa: E402
from smf.video import video_cli                                           # noqa: E402
from smf.video.common import Transcript, VideoError                       # noqa: E402
from tests.test_brands import BAKERY, CLINIC, BrandCase                   # noqa: E402

RECORDING = "2026-09-12 shop interview"
HOST = "Jonah Pell"
AVA = "Ava Lindqvist"


def bakery_answers(**extra):
    a = copy.deepcopy(BAKERY)
    a["identities"][0]["credential_line"] = "Ava Lindqvist, Head Baker"
    a["video"] = {"host_names": [HOST]}
    a["audience"]["questions_they_ask"] = ["Why is my sourdough dense?", "How long should dough proof?"]
    a.update(extra)
    return a


def clinic_answers(**extra):
    a = copy.deepcopy(CLINIC)
    a["video"] = {"host_names": ["Mina Castellane"]}
    a["compliance"] = {"pack": "health", "drop_terms": [], "hold_terms": ["shockwave"],
                       "disclaimer": "General education, not personal medical advice.", "sign_off_by": "Tomas Okafor"}
    a.update(extra)
    return a


# ----------------------------------------------------------------------------- invented recordings
def lay_out(lines, word=0.30, gap=0.08):
    """[(voice, pause_before, text)] -> word list with times, laid end to end."""
    words, t = [], 0.0
    for voice, pause, text in lines:
        t += pause
        for w in text.split():
            words.append({"word": w, "start": round(t, 3), "end": round(t + word, 3), "speaker": voice})
            t += word + gap
    return words


INTERVIEW = [
    (HOST, 1.0, "So tell me, why do so many home loaves come out dense?"),
    (AVA, 1.0, "Most dense loaves are simply underproofed. People trust the recipe time, the kitchen is cold, "
               "and the dough never gets there."),
    (AVA, 1.6, "I tell every class the same thing. Watch the dough, not the clock."),
    (HOST, 1.0, "Watch the dough, not the clock. I like that. Can you say it once more for the camera?"),
    (AVA, 1.2, "Watch the dough, not the clock. When it has grown by half and it wobbles like jelly, it is ready."),
    (HOST, 1.0, "And is cheap flour the real problem, 9 times out of 10?"),
    (AVA, 1.0, "We go through 90 kilos of flour a week here and cheap flour is not the problem."),
    (HOST, 0.5, "Really?"),
    (AVA, 0.5, "Really. Time is an ingredient, and most people leave it out of the bowl."),
]


def interview(names=True):
    words = lay_out(INTERVIEW)
    if not names:
        relabel = {HOST: "speaker_0", AVA: "speaker_1"}
        words = [dict(w, speaker=relabel[w["speaker"]]) for w in words]
    return Transcript({"words": words, "source": {"media": "interview-main.mp4", "made_by": "a test"}})


def when(transcript, phrase, nth=0, voice=None):
    """(start, end) of the nth time `phrase` is said (optionally by one voice). Keeps the tests
    free of hand-typed times."""
    toks = common.tokens_of(phrase, keep_numbers=True)
    heard = [common.tokens_of(w["word"], keep_numbers=True) for w in transcript.words]
    hits = []
    for i in range(len(heard)):
        flat, j = [], i
        while j < len(heard) and len(flat) < len(toks):
            flat += heard[j]
            j += 1
        if flat == toks and (voice is None or transcript.words[i]["speaker"] == voice):
            hits.append((transcript.words[i]["start"], transcript.words[j - 1]["end"]))
    return hits[nth]


def good_cut_list(t, brand_id="maple-and-main"):
    a0, _ = when(t, "Most dense loaves are simply underproofed")
    _, a1 = when(t, "Watch the dough, not the clock", 0, AVA)
    h0, h1 = when(t, "Watch the dough, not the clock", 0, AVA)
    cl = cutlist.CutList(title=RECORDING)
    cl.reference = {"recording": "Shop interview about dense loaves", "brand": brand_id,
                    "cut_from": "interview-main.mp4", "timestamps_from": "Transcriptions/transcript.json", "offset": "0"}
    cl.bodies = [cutlist.Body(key="A", title="Why loaves come out dense", start=a0, end=a1,
                              starts_with="Most dense loaves are simply underproofed",
                              ends_with="Watch the dough, not the clock", on_screen_text="Your loaf is not broken",
                              lower_third="Ava Lindqvist, Head Baker", gate="SHIP",
                              hooks=[cutlist.Hook(1, h0, h1, "Watch the dough, not the clock"),
                                     cutlist.Hook(2, a0, a0 + 2.2, "Most dense loaves are simply underproofed")])]
    return cl


def errors(findings, rule=None):
    return [f for f in findings if f.severity == "ERROR" and (rule is None or f.rule == rule)]


def warnings(findings, rule=None):
    return [f for f in findings if f.severity == "WARN" and (rule is None or f.rule == rule)]


class VideoCase(BrandCase):
    def setUp(self):
        super().setUp()
        self.bakery = brands.create("maple-and-main", "Maple & Main Bakery", bakery_answers())
        self.clinic = brands.create("stride-physio", "Stride Physio", clinic_answers())

    def place_video(self, brand=None, name="interview-main.mp4"):
        """An empty stand-in, so 'the file the cut list names is really there' can be tested
        without any media."""
        folder = common.recording_dir(brand or self.bakery, RECORDING)
        os.makedirs(folder, exist_ok=True)
        Path(folder, name).write_bytes(b"")
        return os.path.join(folder, name)


# ============================================================================= the compliance gate
class TestTheGateIsTheBrandsGate(VideoCase):
    def test_no_brand_means_no_gate(self):
        for nothing in (None, "", "no-such-brand"):
            with self.assertRaises(BrandError):
                gate.GateRules.for_brand(nothing)
        with self.assertRaises(TypeError):
            gate.check("anything at all", None)

    def test_an_unregulated_brand_runs_with_a_nearly_empty_gate(self):
        rules = gate.GateRules.for_brand(self.bakery)
        self.assertEqual((rules.pack, rules._patterns), ("generic", []))
        for line in ("A longer proof cures a dense crumb, I guarantee it.",
                     "Use 400 grams of flour and two tablets of vitamin C if you like.",
                     "You do not need a doctor to tell you the dough is ready."):
            self.assertEqual(gate.check(line, rules).status, gate.PASS, line)

    def test_the_same_words_are_stopped_for_a_health_brand(self):
        rules = gate.GateRules.for_brand(self.clinic)
        self.assertEqual(rules.pack, "health")
        for line, reason in (("Hip drops cure runner's knee.", "cure"),
                             ("I guarantee you will run pain free in six weeks.", "guaranteed"),
                             ("Do this instead of your medication.", "usual care"),
                             ("You don't need a scan for this.", "usual care"),
                             ("Stop taking your painkillers before a race.", "usual care"),
                             ("Take 400 milligrams before every long run.", "specific dose"),
                             ("Two to three tablets a day is plenty.", "specific dose")):
            verdict = gate.check(line, rules)
            self.assertEqual(verdict.status, gate.DROP, line)
            self.assertTrue(any(reason in r for r in verdict.reasons), (line, verdict.reasons))

    def test_a_health_field_gets_the_health_pack_even_when_the_pack_was_left_at_generic(self):
        b = brands.create("left-generic", "Left Generic Physio", copy.deepcopy(CLINIC))
        self.assertEqual(b.data["compliance"]["pack"], "generic")
        self.assertEqual(gate.check("This will cure it.", gate.GateRules.for_brand(b)).status, gate.DROP)

    def test_softer_health_claims_are_held_for_a_named_person_not_dropped(self):
        rules = gate.GateRules.for_brand(self.clinic)
        for line in ("The right dose depends on the runner.", "One of my patients was back in three weeks.",
                     "Loading the tendon reverses the weakness.", "Shockwave is something we offer."):
            self.assertEqual(gate.check(line, rules).status, gate.HOLD, line)
        calm = "Most knee pain in runners over thirty starts at the hip. We change the load first."
        self.assertEqual(gate.check(calm, rules).status, gate.PASS)
        self.assertEqual(gate.check("A secure strap and an accurate fit.", rules).status, gate.PASS)

    def test_the_worst_finding_wins_and_every_reason_is_kept(self):
        v = gate.check("One of my patients took 200 mg and it cured her.", gate.GateRules.for_brand(self.clinic))
        self.assertEqual(v.status, gate.DROP)
        self.assertGreaterEqual(len(v.reasons), 3)
        self.assertIn("cure", v.reasons[0] + v.reasons[1])                 # DROP reasons come first

    def test_a_brands_own_terms_and_never_mention_list_apply_whatever_the_field(self):
        b = brands.update("maple-and-main", {"compliance": {"drop_terms": ["gluten-free"], "hold_terms": ["allergen"],
                                                           "disclaimer": "We bake with nuts.", "sign_off_by": AVA}})
        rules = gate.GateRules.for_brand(b)
        self.assertEqual(gate.check("This loaf is gluten-free.", rules).status, gate.DROP)
        self.assertEqual(gate.check("Ask us about allergens.", rules).status, gate.HOLD)
        named = gate.check("It is better than the bread at Harbour Street Cafe.", rules)
        self.assertEqual(named.status, gate.HOLD)
        self.assertIn("never-mention", named.reasons[0])

    def test_a_regulated_brand_with_no_rules_is_refused_not_waved_through(self):
        answers = copy.deepcopy(BAKERY)
        answers["business"] = dict(answers["business"], regulated="finance")
        b = brands.create("ledger-lane", "Ledger Lane Advisers", answers)
        with self.assertRaises(VideoError) as cm:
            gate.GateRules.for_brand(b)
        self.assertIn("regulated", str(cm.exception))
        b = brands.update("ledger-lane", {"compliance": {"drop_terms": ["guaranteed return"]}})
        self.assertEqual(gate.check("A guaranteed return of nine percent.", gate.GateRules.for_brand(b)).status, gate.DROP)

    def test_two_brands_never_share_a_gate(self):
        line = "This cures it."
        self.assertEqual(gate.check(line, gate.GateRules.for_brand("maple-and-main")).status, gate.PASS)
        self.assertEqual(gate.check(line, gate.GateRules.for_brand("stride-physio")).status, gate.DROP)


# ============================================================================= who may appear
class TestTheSpeakerGate(VideoCase):
    def test_a_host_never_appears_however_the_name_is_written(self):
        p = gate.SpeakerPolicy(self.bakery, [AVA, "JONAH PELL"])
        self.assertTrue(p.may_publish(AVA))
        for spelling in ("JONAH PELL", "jonah pell", "Jonah", "Jonah  Pell "):
            self.assertFalse(p.may_publish(spelling), spelling)
        self.assertEqual((p.on_camera(), p.status), ([AVA], "checked"))

    def test_an_unnamed_voice_in_a_shared_recording_is_kept_out_until_someone_names_it(self):
        p = gate.SpeakerPolicy(self.bakery, ["speaker_0", "speaker_1"])
        self.assertFalse(p.may_publish("speaker_0") or p.may_publish("speaker_1") or p.may_publish(""))
        with self.assertRaises(VideoError) as cm:
            p.require_checkable()
        self.assertIn("speaker_0", str(cm.exception))
        half = gate.SpeakerPolicy(self.bakery, [AVA, "speaker_1"])
        self.assertEqual(half.on_camera(), [AVA])                         # the unnamed one is out, no name needed

    def test_a_single_voice_needs_no_name(self):
        p = gate.SpeakerPolicy(self.bakery, ["speaker_0"])
        self.assertTrue(p.may_publish("speaker_0"))
        p.require_checkable()

    def test_a_recording_where_every_voice_is_off_camera_stops(self):
        with self.assertRaises(VideoError):
            gate.SpeakerPolicy(self.bakery, [HOST]).require_checkable()

    def test_no_voice_labels_is_unverified_and_blocks_a_brand_that_has_hosts(self):
        p = gate.SpeakerPolicy(self.bakery, [])
        self.assertEqual(p.status, "unverified")
        self.assertFalse(p.may_publish(""))
        with self.assertRaises(VideoError) as cm:
            p.require_checkable()
        self.assertIn("--nobody-off-camera", str(cm.exception))
        vouched = gate.SpeakerPolicy(self.bakery, [], everyone_on_camera=True)
        vouched.require_checkable()
        self.assertEqual(vouched.status, gate.ATTESTED)
        no_hosts = brands.create("solo-bakes", "Solo Bakes", copy.deepcopy(BAKERY))
        solo = gate.SpeakerPolicy(no_hosts, [])
        solo.require_checkable()
        self.assertTrue(solo.may_publish(""))
        self.assertEqual(solo.status, "unverified")                       # allowed, but never called checked

    def test_the_pad_is_wider_than_any_distance_a_cut_may_travel(self):
        self.assertGreater(gate.EXCLUDE_PAD, rough_cut.MAX_LEAD)
        self.assertGreater(gate.EXCLUDE_PAD, gate.WALL_GUARD)

    def test_an_off_camera_voice_in_the_middle_splits_the_segment(self):
        t = interview()
        policy = gate.SpeakerPolicy.for_transcript(self.bakery, t)
        start, _ = when(t, "We go through 90 kilos")
        _, end = when(t, "out of the bowl")
        host0, host1 = when(t, "Really?", 0, HOST)
        seg = {"start": start, "end": end, "starts_with": "We go through 90 kilos", "ends_with": "out of the bowl"}
        first, second = gate.publishable_pieces(seg, t.turns(), policy)
        self.assertAlmostEqual(first["end"], host0 - gate.EXCLUDE_PAD, places=2)
        self.assertAlmostEqual(second["start"], host1 + gate.EXCLUDE_PAD, places=2)
        # boundary words stay only on the edges the person chose, never on an edge made by removal
        self.assertEqual((first["starts_with"], first["ends_with"]), ("We go through 90 kilos", ""))
        self.assertEqual((second["starts_with"], second["ends_with"]), ("", "out of the bowl"))
        self.assertAlmostEqual(first["wall_hi"], host0 - gate.WALL_GUARD, places=2)
        self.assertAlmostEqual(second["wall_lo"], host1 + gate.WALL_GUARD, places=2)
        self.assertGreater(gate.off_camera_seconds(start, end, t.turns(), policy), 0.2)

    def test_trimming_only_silence_keeps_the_boundary_words_and_costs_nothing(self):
        t = interview()
        policy = gate.SpeakerPolicy.for_transcript(self.bakery, t)
        start, _ = when(t, "Most dense loaves")
        _, end = when(t, "never gets there")
        early = {"start": start - 0.6, "end": end, "starts_with": "Most dense loaves", "ends_with": "never gets there"}
        (piece,) = gate.publishable_pieces(early, t.turns(), policy)      # the time was written early, in the pause
        self.assertGreater(piece["start"], early["start"])                # trimmed back from the host...
        self.assertEqual((piece["lost_head"], piece["starts_with"]), (0.0, "Most dense loaves"))   # ...at no cost
        # "Really?" comes half a second after she stops, so the margin around him reaches into her last word
        s2, _ = when(t, "We go through 90 kilos")
        _, e2 = when(t, "is not the problem.")
        tight = {"start": s2, "end": e2, "starts_with": "We go through", "ends_with": "is not the problem"}
        (clipped,) = gate.publishable_pieces(tight, t.turns(), policy)
        host0, _ = when(t, "Really?", 0, HOST)
        self.assertAlmostEqual(clipped["lost_tail"], gate.EXCLUDE_PAD - (host0 - e2), places=2)
        self.assertGreater(clipped["lost_tail"], 0.05)
        self.assertEqual((clipped["starts_with"], clipped["ends_with"]), ("We go through", ""))

    def test_the_lower_third_is_the_brands_own_line_or_nothing(self):
        self.assertEqual(gate.lower_third_for(self.bakery, AVA), "Ava Lindqvist, Head Baker")
        self.assertEqual(gate.lower_third_for(self.bakery, "ava lindqvist"), "Ava Lindqvist, Head Baker")
        self.assertEqual(gate.lower_third_for(self.bakery, "A Visiting Miller"), "")      # no invented credentials
        self.assertEqual(gate.lower_third_for(self.clinic, "Tomas Okafor"), "Tomas Okafor")


# ============================================================================= the cut list
class TestTheCutList(VideoCase):
    def setUp(self):
        super().setUp()
        self.t = interview()
        self.place_video()

    def check(self, cl, brand=None, transcript=None, **kw):
        return cutlist.validate(cl, transcript or self.t, brand or self.bakery, recording=RECORDING, **kw)

    def test_it_survives_being_written_and_read_back(self):
        cl = good_cut_list(self.t)
        cl.bodies[0].hooks[1].gate = "HOLD"
        cl.bodies[0].signed_off = "Ava Lindqvist, 2026-09-14"
        again = cutlist.parse(cutlist.write(cl))
        self.assertEqual(again.problems, [])
        curly = cutlist.parse("## Body A: x\n- **Body:** [00:05 \u2013 00:20]\n- **Hook 1:** [0:05 \u2014 0:08] \u201cQuoted so\u201d\n")
        self.assertEqual((curly.problems, curly.bodies[0].end, curly.bodies[0].hooks[0].text), ([], 20.0, "Quoted so"))
        self.assertEqual(again.reference, cl.reference)
        self.assertEqual(again.title, RECORDING)
        b0, b1 = cl.bodies[0], again.bodies[0]
        self.assertEqual((b1.key, b1.title, b1.gate, b1.on_screen_text, b1.lower_third, b1.signed_off),
                         (b0.key, b0.title, b0.gate, b0.on_screen_text, b0.lower_third, b0.signed_off))
        self.assertAlmostEqual(b1.start, b0.start, places=1)
        self.assertEqual([(h.number, h.text, h.gate) for h in b1.hooks], [(h.number, h.text, h.gate) for h in b0.hooks])

    def test_a_cut_list_that_quotes_real_words_by_the_person_on_camera_holds_up(self):
        findings = self.check(good_cut_list(self.t))
        self.assertEqual(errors(findings), [], [str(f) for f in findings])

    def test_a_hook_nobody_said_is_refused(self):
        cl = good_cut_list(self.t)
        cl.bodies[0].hooks[0].text = "Dense bread is always the baker's fault"
        found = errors(self.check(cl), "verbatim")
        self.assertEqual(len(found), 1)
        self.assertIn("not in the transcript", found[0].detail)

    def test_a_hook_read_out_by_the_host_is_a_defect_and_the_real_delivery_is_pointed_to(self):
        cl = good_cut_list(self.t)
        host_read = when(self.t, "Watch the dough, not the clock", 0, HOST)
        cl.bodies[0].hooks[0].start, cl.bodies[0].hooks[0].end = host_read
        found = [f for f in errors(self.check(cl), "speaker") if "is spoken by" in f.detail]
        self.assertEqual(len(found), 1)
        self.assertIn(HOST, found[0].detail)
        self.assertIn("on camera says the same words", found[0].detail)

    def test_a_time_that_points_somewhere_else_is_refused(self):
        cl = good_cut_list(self.t)
        cl.bodies[0].hooks[1].start += 40
        cl.bodies[0].hooks[1].end += 40
        self.assertTrue(any("not near" in f.detail for f in errors(self.check(cl), "verbatim")))

    def test_boundary_words_must_be_real_too(self):
        cl = good_cut_list(self.t)
        cl.bodies[0].ends_with = "and that is the whole secret"
        self.assertEqual(len(errors(self.check(cl), "boundary")), 1)
        cl = good_cut_list(self.t)
        cl.bodies[0].starts_with = "Most dense"
        self.assertTrue(warnings(self.check(cl), "boundary"))

    def test_on_screen_text_is_three_to_seven_words(self):
        for text, ok in (("Dense loaf", False), ("Your loaf is not broken", True),
                         ("This is far too many words to read in one second", False), ("", False)):
            cl = good_cut_list(self.t)
            cl.bodies[0].on_screen_text = text
            self.assertEqual(errors(self.check(cl), "on-screen") == [], ok, text)

    def test_it_must_open_by_saying_what_it_is_about(self):
        cl = good_cut_list(self.t)
        cl.reference = {}
        self.assertEqual(len(errors(self.check(cl), "reference")), 4)

    def test_a_cut_list_for_another_brand_or_a_missing_video_is_refused(self):
        self.assertTrue(errors(self.check(good_cut_list(self.t, "stride-physio")), "reference"))
        cl = good_cut_list(self.t)
        cl.reference["cut_from"] = "a-file-nobody-has.mp4"
        found = errors(self.check(cl), "reference")
        self.assertTrue(found and "cannot be found" in found[0].detail)

    def test_a_mistyped_line_is_reported_and_never_defaults_to_ship(self):
        text = cutlist.write(good_cut_list(self.t)).replace("**Gate:**", "**Gaet:**")
        cl = cutlist.parse(text)
        self.assertTrue(any(f.rule == "unknown-line" for f in cl.problems))
        self.assertTrue(errors(self.check(cl), "gate"))
        self.assertEqual([c.gate for c in cl.clips()], ["DROP", "DROP"])   # unreadable means strictest

    def test_a_clip_cannot_be_marked_looser_than_the_brands_rules(self):
        words = lay_out([("Tomas Okafor", 1.0, "Hip drops cure runner's knee and I guarantee it works for everyone here.")])
        t = Transcript({"words": words})
        self.place_video(self.clinic, "clinic.mp4")
        cl = cutlist.CutList(title="clinic")
        cl.reference = {"recording": "Clinic talk", "brand": "stride-physio", "cut_from": "clinic.mp4",
                        "timestamps_from": "Transcriptions/transcript.json"}
        s, e = words[0]["start"], words[-1]["end"]
        cl.bodies = [cutlist.Body(key="A", title="Knee", start=s, end=e, starts_with="Hip drops cure runner's knee",
                                  ends_with="works for everyone here", on_screen_text="Runner's knee starts higher",
                                  gate="SHIP", hooks=[cutlist.Hook(1, s, s + 2, "Hip drops cure runner's knee")])]
        found = errors(self.check(cl, self.clinic, t), "gate")
        self.assertTrue(found and "DROP" in found[0].detail, [str(f) for f in found])
        cl.bodies[0].gate = "DROP"
        self.assertEqual(errors(self.check(cl, self.clinic, t), "gate"), [])

    def test_hold_needs_a_disclaimer_and_a_named_person(self):
        cl = good_cut_list(self.t)
        cl.bodies[0].gate = "HOLD"
        found = errors(self.check(cl), "gate")
        self.assertTrue(found and "sign" in found[0].detail)
        b = brands.update("maple-and-main", {"compliance": {"disclaimer": "We bake with nuts.", "sign_off_by": AVA}})
        findings = self.check(cl, b)
        self.assertEqual(errors(findings), [])
        self.assertTrue(warnings(findings, "needs-sign-off"))

    def test_on_screen_text_may_not_carry_a_claim(self):
        b = brands.update("maple-and-main", {"compliance": {"drop_terms": ["gluten-free"]}})
        cl = good_cut_list(self.t)
        cl.bodies[0].on_screen_text = "Our gluten-free loaf explained"
        self.assertTrue(errors(self.check(cl, b), "on-screen"))

    def test_each_hook_is_one_clip_and_a_lifted_hook_goes_in_front_of_the_whole_body(self):
        lifted, in_place = good_cut_list(self.t).clips()
        self.assertEqual((lifted.id, in_place.id), ("A1", "A2"))
        self.assertEqual([s["role"] for s in lifted.segments], ["hook", "body"])
        self.assertEqual([s["role"] for s in in_place.segments], ["body"])
        self.assertEqual(lifted.file_stem, "A1-why-loaves-come-out-dense")
        cl = good_cut_list(self.t)
        cl.bodies[0].hooks[0].gate = "DROP"
        self.assertEqual([c.gate for c in cl.clips()], ["DROP", "SHIP"])   # a hook can only make its clip stricter

    def test_a_body_with_the_host_talking_inside_it_is_flagged(self):
        cl = good_cut_list(self.t)
        s, _ = when(self.t, "We go through 90 kilos")
        _, e = when(self.t, "out of the bowl")
        cl.bodies.append(cutlist.Body(key="B", title="Flour", start=s, end=e, starts_with="We go through 90 kilos",
                                      ends_with="out of the bowl", on_screen_text="Cheap flour is fine", gate="SHIP",
                                      lower_third="Ava Lindqvist, Head Baker",
                                      hooks=[cutlist.Hook(1, s, s + 3, "We go through 90 kilos of flour")]))
        findings = self.check(cl)
        self.assertEqual(errors(findings), [], [str(f) for f in findings])
        self.assertTrue(any("off camera talking inside" in f.detail for f in warnings(findings, "speaker")))

    def test_a_new_cut_list_starts_with_its_reference_block_filled_in(self):
        policy = gate.SpeakerPolicy.for_transcript(self.bakery, self.t)
        cl = cutlist.parse(cutlist.starter(self.bakery, RECORDING, self.t, policy))
        self.assertEqual((cl.reference["brand"], cl.reference["cut_from"]), ("maple-and-main", "interview-main.mp4"))
        self.assertEqual((cl.bodies, cl.problems), ([], []))
        self.assertTrue(any(f.rule == "empty" for f in self.check(cl)))

    def test_a_subtitle_transcript_can_be_checked_but_says_the_voices_are_unverified(self):
        no_hosts = brands.create("solo-bakes", "Solo Bakes", copy.deepcopy(BAKERY))
        t = Transcript({"segments": [{"start": 4, "end": 9, "text": "Most dense loaves are simply underproofed."},
                                     {"start": 9, "end": 15, "text": "Watch the dough, not the clock."}]})
        self.place_video(no_hosts)
        cl = good_cut_list(self.t, "solo-bakes")
        cl.bodies[0].start, cl.bodies[0].end = 4, 15
        cl.bodies[0].lower_third = ""
        cl.bodies[0].hooks = [cutlist.Hook(1, 9, 15, "Watch the dough, not the clock")]
        findings = cutlist.validate(cl, t, no_hosts, recording=RECORDING)
        self.assertEqual(errors(findings), [], [str(f) for f in findings])
        self.assertTrue(warnings(findings, "unverified"))


# ============================================================================= lining cuts up on words
def heard(transcript, shift=0.0):
    return [(w["start"] + shift, w["end"] + shift, w["word"]) for w in transcript.words]


class TestCutsLineUpOnWordsNotOnTimes(VideoCase):
    def setUp(self):
        super().setUp()
        self.t = interview()
        self.words = heard(self.t)

    def test_a_time_that_is_over_a_second_early_still_lands_on_the_quoted_words(self):
        onset, _ = when(self.t, "Most dense loaves")
        cut, how = rough_cut.snap_head(self.words, [], onset - 1.2, "Most dense loaves are simply underproofed")
        self.assertEqual(how, "text")
        self.assertAlmostEqual(cut, onset - 0.15, places=2)
        _, end = when(self.t, "never gets there")
        cut, how = rough_cut.snap_tail(self.words, [], end - 1.0, "and the dough never gets there")
        self.assertEqual(how, "text")
        self.assertAlmostEqual(cut, end + 0.3, places=2)

    def test_a_measured_pause_beats_the_models_guess_at_where_a_word_starts(self):
        onset, _ = when(self.t, "Most dense loaves")
        pause = [(onset - 0.9, onset + 0.2)]                              # the sound really starts 0.2s later
        cut, _how = rough_cut.snap_head(self.words, pause, onset, "Most dense loaves are simply")
        self.assertAlmostEqual(cut, onset + 0.05, places=2)               # just inside the pause, before the attack

    def test_a_cut_never_travels_further_than_max_lead_from_its_word(self):
        self.assertAlmostEqual(rough_cut.head_cut(10.0, [(8.0, 10.4)]), 10.25)
        self.assertGreaterEqual(rough_cut.head_cut(10.0, [(9.0, 9.71)]), 10.0 - rough_cut.MAX_LEAD)
        self.assertLessEqual(rough_cut.tail_cut(10.0, [(10.5, 12.0)]), 10.0 + rough_cut.MAX_LEAD)
        self.assertAlmostEqual(rough_cut.tail_cut(10.0, []), 10.3)

    def test_when_a_line_is_said_twice_the_one_nearest_the_written_time_wins(self):
        first = when(self.t, "Watch the dough, not the clock", 0, AVA)
        second = when(self.t, "Watch the dough, not the clock", 1, AVA)
        toks = common.tokens_of("Watch the dough, not the clock")
        i = rough_cut.match_text(self.words, toks, 0, 999, anchor_last=False, prefer=second[0])
        self.assertAlmostEqual(self.words[i][0], second[0])
        i = rough_cut.match_text(self.words, toks, 0, 999, anchor_last=False, prefer=first[0])
        self.assertAlmostEqual(self.words[i][0], first[0])

    def test_a_wall_keeps_the_search_and_the_cut_away_from_the_host(self):
        host = when(self.t, "Watch the dough, not the clock", 0, HOST)
        mine = when(self.t, "Watch the dough, not the clock", 1, AVA)
        stamp = host[0] + 0.5                                             # a sloppy time, inside the host's reading
        cut, how = rough_cut.snap_head(self.words, [], stamp, "Watch the dough, not the clock")
        self.assertLess(cut, host[1])                                     # without a wall it grabs the host
        wall = mine[0] - 0.2
        found = rough_cut.snap_head(self.words, [], mine[0] - 0.5, "Watch the dough, not the clock", wall_lo=wall)
        self.assertAlmostEqual(found[0], mine[0] - 0.15, places=2)
        self.assertEqual(rough_cut.clamp(wall - 3.0, wall, None, 500.0), wall)
        self.assertEqual(rough_cut.clamp(99.0, None, 42.0, 500.0), 42.0)
        self.assertEqual(rough_cut.clamp(-5.0, None, None, 500.0), 0.0)

    def test_numbers_are_never_used_to_match(self):
        toks = common.tokens_of("We go through 90 kilos of flour")
        self.assertNotIn("90", toks)
        said_differently = [(a, b, "ninety" if w == "90" else w) for a, b, w in self.words]
        onset, _ = when(self.t, "We go through")
        cut, how = rough_cut.snap_head(said_differently, [], onset - 0.4, "We go through 90 kilos of flour")
        self.assertEqual(how, "text")

    def test_with_no_quote_it_opens_on_the_first_sentence_after_the_time(self):
        onset, _ = when(self.t, "I tell every class")
        cut, how = rough_cut.snap_head(self.words, [], onset - 0.9, "")
        self.assertEqual(how, "word")
        self.assertAlmostEqual(cut, onset - 0.15, places=2)
        self.assertIsNone(rough_cut.snap_head([], [], 12.0, "anything at all"))

    def test_pauses_alone_are_the_last_resort_before_a_fixed_margin(self):
        self.assertAlmostEqual(rough_cut.head_from_silences([(9.0, 10.4)], 10.0), 10.4 - rough_cut.HEAD_MARGIN)
        self.assertIsNone(rough_cut.head_from_silences([(2.0, 3.0)], 10.0))
        self.assertAlmostEqual(rough_cut.tail_from_silences([(10.3, 11.5)], 10.0), 10.3 + rough_cut.TAIL_MARGIN)

    def test_the_plan_takes_the_host_out_and_moves_everything_onto_the_videos_clock(self):
        cl = good_cut_list(self.t)
        s, _ = when(self.t, "We go through 90 kilos")
        _, e = when(self.t, "out of the bowl")
        cl.bodies = [cutlist.Body(key="B", title="Flour", start=s, end=e, starts_with="We go through 90 kilos",
                                  ends_with="out of the bowl", gate="SHIP", on_screen_text="Cheap flour is fine",
                                  hooks=[cutlist.Hook(1, s, s + 3, "We go through 90 kilos of flour")])]
        cl.reference["offset"] = "2.5"
        policy = gate.SpeakerPolicy.for_transcript(self.bakery, self.t)
        planned, skipped = rough_cut.plan_clips(cl, self.t, policy)
        segs = planned[0]["segments"]
        self.assertEqual((len(segs), skipped), (2, []))
        self.assertAlmostEqual(segs[0]["start"], s + 2.5, places=2)
        host0, host1 = when(self.t, "Really?", 0, HOST)
        self.assertLess(segs[0]["end"], host0 + 2.5)
        self.assertGreater(segs[1]["start"], host1 + 2.5)
        # lining up on words afterwards still cannot reach the host
        snapper = rough_cut.Snapper(lambda a, b: [w for w in heard(self.t, 2.5) if a <= w[0] <= b], lambda a, b: [], 500.0)
        snapper.prepare([x for seg in segs for x in (seg["start"], seg["end"])])
        rough_cut.resolve_cuts(planned, snapper, "unused", 500.0)
        for a, b in (seg["cut"] for seg in segs):
            self.assertFalse(a < host1 + 2.5 and b > host0 + 2.5, (a, b))

    def test_a_drop_clip_is_never_cut_and_an_unknown_clip_name_is_an_error(self):
        cl = good_cut_list(self.t)
        cl.bodies[0].hooks[0].gate = "DROP"
        policy = gate.SpeakerPolicy.for_transcript(self.bakery, self.t)
        planned, skipped = rough_cut.plan_clips(cl, self.t, policy)
        self.assertEqual(([p["clip"].id for p in planned], [s["id"] for s in skipped]), (["A2"], ["A1"]))
        with self.assertRaises(VideoError):
            rough_cut.plan_clips(cl, self.t, policy, only=["Z9"])

    def test_words_that_cannot_be_heard_near_their_times_raise_the_alarm(self):
        seg = {"starts_with": "a", "ends_with": "b"}
        found = [{"segments": [dict(seg, snap=["text", "text"]), dict(seg, snap=["text", "word"])]}]
        lost = [{"segments": [dict(seg, snap=["word", "silence"]), dict(seg, snap=["pad", "text"])]}]
        self.assertEqual(rough_cut.snap_alarm(found, "speech-model"), "")
        self.assertIn("different video file", rough_cut.snap_alarm(lost, "speech-model"))
        self.assertEqual(rough_cut.snap_alarm(lost, "transcript"), "")    # agreeing with itself proves nothing


# ============================================================================= fine cut decisions
def spoken(*items):
    """(word, start, end) triples -> word list."""
    return [{"word": w, "start": a, "end": b} for w, a, b in items]


class TestFineCutIsSmoothNotSurgical(unittest.TestCase):
    def test_a_filler_in_its_own_pocket_of_silence_is_taken_out(self):
        words = spoken(("Time", 1.0, 1.3), ("is", 1.35, 1.5), ("um", 2.4, 2.7), ("an", 3.6, 3.75), ("ingredient", 3.8, 4.4))
        keeps, removals = fine_cut.plan_segment(0.8, 4.8, words)
        self.assertEqual(len(removals), 1)
        self.assertIn("filler 'um'", removals[0][2])
        self.assertAlmostEqual(removals[0][0], 1.5 + fine_cut.CUT_OUT_PAD)
        self.assertAlmostEqual(removals[0][1], 3.6 - fine_cut.CUT_IN_PAD)
        self.assertEqual(len(keeps), 2)

    def test_a_filler_wedged_between_words_is_left_alone(self):
        words = spoken(("Time", 1.0, 1.3), ("um", 1.35, 1.55), ("is", 1.6, 1.75), ("an", 1.8, 1.95), ("ingredient", 2.0, 2.6))
        keeps, removals = fine_cut.plan_segment(0.8, 3.0, words)
        self.assertEqual((len(keeps), removals), (1, []))

    def test_only_a_long_pause_is_tightened_and_a_beat_is_left_either_side(self):
        words = spoken(("Watch", 1.0, 1.3), ("the", 1.35, 1.5), ("dough", 1.55, 2.0), ("not", 2.9, 3.1),
                       ("the", 3.15, 3.3), ("clock", 5.4, 5.9))
        keeps, removals = fine_cut.plan_segment(0.8, 6.3, words)
        self.assertEqual(len(removals), 1)                                # 0.9s is a breath; 2.1s is dead air
        a, b, why = removals[0]
        self.assertIn("pause", why)
        self.assertAlmostEqual(a, 3.3 + fine_cut.CUT_OUT_PAD)
        self.assertAlmostEqual(b, 5.4 - fine_cut.CUT_IN_PAD)
        kept_time = sum(y - x for x, y in keeps)
        for w in words:                                                   # no real word is ever touched
            self.assertTrue(any(x <= w["start"] and w["end"] <= y for x, y in keeps), w)
        self.assertLess(kept_time, 6.3 - 0.8)

    def test_it_opens_and_closes_on_the_quoted_words_not_on_scraps_either_side(self):
        words = spoken(("camera?", 0.7, 1.05), ("Watch", 1.4, 1.7), ("the", 1.75, 1.9), ("dough", 1.95, 2.4),
                       ("not", 2.45, 2.6), ("the", 2.65, 2.8), ("clock", 2.85, 3.3), ("And", 3.5, 3.7))
        keeps, _ = fine_cut.plan_segment(0.9, 3.6, words, starts_with="Watch the dough", ends_with="not the clock")
        self.assertEqual(len(keeps), 1)
        head, tail = keeps[0]
        self.assertGreaterEqual(head, 1.05)                               # none of the word before
        self.assertLessEqual(head, 1.4)
        self.assertGreaterEqual(tail, 3.3)
        self.assertLessEqual(tail, 3.5)                                   # and none of the word after

    def test_a_common_first_word_does_not_latch_on_to_the_wrong_place(self):
        words = spoken(("the", 1.0, 1.1), ("end.", 1.15, 1.4), ("The", 2.0, 2.15), ("dough", 2.2, 2.6), ("decides", 2.65, 3.1))
        self.assertEqual(fine_cut.anchor_index(words, "The dough decides", last=False), 2)
        self.assertEqual(fine_cut.anchor_index(words, "dough decides", last=True), 4)
        self.assertEqual(fine_cut.anchor_index(words, "", last=True), 4)

    def test_length_lost_at_the_edges_is_told_apart_from_a_long_pause_being_tightened(self):
        words = spoken(("The", 1.0, 1.2), ("dough", 1.25, 1.7), ("rests.", 1.75, 2.2), ("um", 5.0, 5.3),
                       ("The", 8.0, 8.2), ("oven", 8.25, 8.7), ("waits.", 8.75, 9.3))
        keeps, removals = fine_cut.plan_segment(0.8, 9.7, words, starts_with="The dough rests", ends_with="oven waits")
        self.assertLess(fine_cut.edge_loss(8.9, keeps, removals), 0.05)   # one huge pause: honest tightening
        wrong, removed = fine_cut.plan_segment(0.8, 9.7, words, starts_with="The oven waits", ends_with="oven waits")
        self.assertGreater(fine_cut.edge_loss(8.9, wrong, removed), fine_cut.SUSPICIOUS_EDGE_LOSS)

    def test_a_sliver_is_absorbed_instead_of_becoming_a_stutter(self):
        words = spoken(("One", 1.0, 1.3), ("um", 2.2, 2.4), ("two", 3.3, 3.5), ("uh", 4.4, 4.6), ("three", 5.5, 5.9))
        keeps, removals = fine_cut.plan_segment(0.8, 6.3, words, settings={"min_keep": 1.0})
        self.assertEqual(len(removals), 2)
        self.assertTrue(all(y - x >= 0.5 for x, y in keeps), keeps)
        self.assertLess(len(keeps), 3)

    def test_measured_silence_places_the_boundary_not_the_transcripts_word_end(self):
        try:
            import numpy                                                   # noqa: F401
        except ImportError:
            self.skipTest("numpy is not installed (python factory.py setup)")
        hops = int(6.0 / fine_cut.ENV_HOP)
        loud = [0.0001] * hops
        for i in range(int(1.0 / fine_cut.ENV_HOP), int(2.6 / fine_cut.ENV_HOP)):     # the voice holds on until 2.6
            loud[i] = 0.2
        env = fine_cut.Envelope(loud)
        self.assertAlmostEqual(env.speech_ends_after(2.0), 2.6, places=1)
        self.assertAlmostEqual(env.speech_starts_before(1.5), 1.0, places=1)
        words = spoken(("absolutely", 1.0, 1.9))                          # the transcript thinks it ends at 1.9
        keeps, _ = fine_cut.plan_segment(0.5, 3.5, words, envelope=env)
        self.assertGreaterEqual(keeps[0][1], 2.6)

    def test_cuts_sit_on_whole_frames(self):
        self.assertAlmostEqual(fine_cut.frame_snap(1.017, 25.0), 1.0)
        self.assertAlmostEqual(fine_cut.frame_snap(1.03, 25.0), 1.04)


# ============================================================================= the finder
CLINIC_TALK = [
    ("Mina Castellane", 1.0, "So is it true that 90 percent of runners get 3 injuries in 2 years?"),
    ("Tomas Okafor", 1.0, "Most knee pain in runners over thirty starts at the hip and not at the knee. "
                          "We change the training load first, by about 20 percent, for 3 weeks."),
    ("Tomas Okafor", 9.0, "Hip drops cure runner's knee in 2 weeks and I guarantee that for every injury I see."),
    ("Tomas Okafor", 9.0, "Some runners ask about tablets. The right dose depends on the person, so that is a "
                          "conversation for 10 minutes with your own doctor."),
]


class TestTheFinderFlagsAndPointsButNeverRanks(VideoCase):
    def test_it_refuses_to_run_without_a_brand(self):
        with self.assertRaises(BrandError):
            find_clips.find(None, interview())

    def test_pass_and_quarantine_come_with_reasons(self):
        t = Transcript({"words": lay_out(CLINIC_TALK)})
        r = find_clips.find(self.clinic, t)
        self.assertEqual(r["kept_out"], ["Mina Castellane"])
        self.assertEqual(len(r["pass"]), 1)
        self.assertIn("starts at the hip", r["pass"][0]["line"] + " " + " ".join(CLINIC_TALK[1][2].split()))
        gates = {e["gate"]: e for e in r["quarantine"]}
        self.assertEqual(set(gates), {"DROP", "HOLD"})
        self.assertTrue(any("cure" in x for x in gates["DROP"]["reasons"]))
        self.assertTrue(any("dosing" in x for x in gates["HOLD"]["reasons"]))
        self.assertNotIn("score", r["pass"][0])                           # a hint about density, never a score or rank
        self.assertEqual([e["start"] for e in r["pass"] + r["quarantine"]],
                         sorted(e["start"] for e in r["pass"] + r["quarantine"]))

    def test_the_hosts_line_is_never_offered_as_the_line_to_lift(self):
        t = Transcript({"words": lay_out(CLINIC_TALK)})
        for e in find_clips.find(self.clinic, t)["pass"]:
            self.assertEqual(e["line_by"], "Tomas Okafor")
        self.assertTrue(find_clips.looks_like_host("So is that really true?"))
        self.assertFalse(find_clips.looks_like_host("Most knee pain in runners starts at the hip and not the knee."))

    def test_the_same_talk_is_clean_for_a_brand_with_no_health_rules(self):
        words = [dict(w, speaker=AVA if w["speaker"] == "Tomas Okafor" else HOST) for w in lay_out(CLINIC_TALK)]
        r = find_clips.find(self.bakery, Transcript({"words": words}))
        self.assertEqual(r["quarantine"], [])

    def test_on_topic_words_come_from_the_brands_own_files(self):
        self.assertIn("sourdough", find_clips.topic_words(self.bakery))
        self.assertNotIn("sourdough", find_clips.topic_words(self.clinic))
        self.assertIn("injury", find_clips.topic_words(self.clinic))

    def test_a_second_take_is_folded_into_the_first(self):
        twice = CLINIC_TALK[:2] + [("Tomas Okafor", 9.0, CLINIC_TALK[1][2])]
        r = find_clips.find(self.clinic, Transcript({"words": lay_out(twice)}))
        self.assertEqual(len(r["pass"]), 1)
        self.assertEqual(len(r["pass"][0]["other_takes"]), 1)

    def test_running_it_writes_the_lists_and_starts_a_cut_list_once(self):
        transcribe.write_transcript(self.clinic, RECORDING, words=lay_out(CLINIC_TALK), source={"media": "talk.mp4"})
        first = find_clips.run(self.clinic, RECORDING)
        out = common.output_dir(self.clinic, RECORDING)
        text = Path(out, "candidates.md").read_text(encoding="utf-8")
        self.assertIn("NOT a ranking", text)
        self.assertIn("QUARANTINE", text)
        self.assertTrue(first["started_cut_list"])
        Path(out, common.CUT_LIST_FILE).write_text("my own work", encoding="utf-8")
        self.assertFalse(find_clips.run(self.clinic, RECORDING)["started_cut_list"])
        self.assertEqual(Path(out, common.CUT_LIST_FILE).read_text(encoding="utf-8"), "my own work")


# ============================================================================= transcribing
SERVICE_ANSWER = {"language_code": "en", "words": [
    {"text": "Watch", "start": 0.5, "end": 0.8, "type": "word", "speaker_id": "speaker_0"},
    {"text": " ", "start": 0.8, "end": 0.85, "type": "spacing", "speaker_id": "speaker_0"},
    {"text": "the", "start": 0.85, "end": 1.0, "type": "word", "speaker_id": "speaker_0"},
    {"text": "dough.", "start": 1.05, "end": 1.5, "type": "word", "speaker_id": "speaker_0"},
    {"text": "(laughs)", "start": 1.6, "end": 2.0, "type": "audio_event", "speaker_id": "speaker_1"},
    {"text": "Lovely.", "start": 2.4, "end": 2.9, "type": "word", "speaker_id": "speaker_1"}]}
FAKE_KEY = "kkkkkkkk-kkkk-kkkk"              # stands in for a key; deliberately nothing like a real one


class TestTranscribingSpendsNothingUntilAsked(VideoCase):
    def setUp(self):
        super().setUp()
        self.media = os.path.join(self.tmp.name, "Ava's caf\u00e9 interview.mp4")
        Path(self.media).write_bytes(b"not really a video")
        self.sent = []
        for name, value in (("probe_duration", lambda p: 42 * 60.0), ("has_audio", lambda p: True),
                            ("extract_audio", lambda media, dst: dst)):
            patcher = mock.patch.object(transcribe, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def keys_are(self, env):
        env_patch = mock.patch.dict(os.environ, env, clear=True)
        file_patch = mock.patch.object(keys, "KEYS_FILE", os.path.join(self.tmp.name, "no-keys.env"))
        env_patch.start()
        file_patch.start()
        self.addCleanup(file_patch.stop)
        self.addCleanup(env_patch.stop)
        keys.load(force=True)

    def fake_send(self, audio, api_key, speakers):
        self.sent.append((audio, api_key, speakers))
        return SERVICE_ANSWER

    def test_the_price_is_shown_first_and_nothing_is_sent(self):
        self.keys_are({"ELEVENLABS_API_KEY": FAKE_KEY})
        result = transcribe.transcribe(self.bakery, RECORDING, self.media, send=self.fake_send)
        self.assertEqual((result["sent"], self.sent), (False, []))
        words = transcribe.plan_words(result["plan"])
        self.assertIn("42 minutes", words)
        self.assertIn("about 15 cents", words)
        self.assertIn("--confirm", words)
        self.assertNotIn(FAKE_KEY, words + json.dumps(result["plan"]))
        self.assertFalse(os.path.exists(common.transcriptions_dir(self.bakery, RECORDING)))

    def test_costs_read_like_money(self):
        self.assertEqual(transcribe.cost_words(transcribe.estimate_cost(3600)), "about 22 cents")
        self.assertEqual(transcribe.cost_words(transcribe.estimate_cost(20)), "about 1 cent")
        self.assertEqual(transcribe.cost_words(transcribe.estimate_cost(6 * 3600)), "about $1.32")

    def test_without_a_key_it_says_what_is_missing_and_what_it_costs(self):
        self.keys_are({})
        self.assertIn("22 cents", transcribe.plan_words(transcribe.transcribe(self.bakery, RECORDING, self.media)["plan"]))
        with self.assertRaises(VideoError) as cm:
            transcribe.transcribe(self.bakery, RECORDING, self.media, confirm=True, send=self.fake_send)
        self.assertIn("not set up yet", str(cm.exception))
        self.assertIn("22 cents per hour", str(cm.exception))
        self.assertEqual(self.sent, [])

    def test_a_confirmed_run_writes_the_canonical_files(self):
        self.keys_are({"ELEVENLABS_API_KEY": FAKE_KEY})
        result = transcribe.transcribe(self.bakery, RECORDING, self.media, confirm=True, speakers=2, send=self.fake_send)
        self.assertEqual((len(self.sent), self.sent[0][1:]), (1, (FAKE_KEY, 2)))
        folder = common.transcriptions_dir(self.bakery, RECORDING)
        self.assertEqual(sorted(os.listdir(folder)), sorted([common.TRANSCRIPT_FILE, common.READABLE_FILE,
                                                             common.ON_CAMERA_FILE, common.PLAIN_FILE]))
        for name in os.listdir(folder):
            self.assertNotIn(FAKE_KEY, Path(folder, name).read_text(encoding="utf-8"))
        t = Transcript.load(self.bakery, RECORDING)
        self.assertEqual([w["word"] for w in t.words], ["Watch", "the", "dough.", "Lovely."])   # no spacing, no (laughs)
        self.assertEqual(t.speakers, ["speaker_0", "speaker_1"])
        self.assertEqual(t.source["media_name"], "Ava's caf\u00e9 interview.mp4")
        self.assertEqual(result["policy"].on_camera(), [])                 # two unnamed voices: nobody cleared yet
        self.assertIn("Nobody is cleared", Path(folder, common.ON_CAMERA_FILE).read_text(encoding="utf-8"))

    def test_a_second_send_is_refused_unless_asked_for_by_name(self):
        self.keys_are({"ELEVENLABS_API_KEY": FAKE_KEY})
        transcribe.transcribe(self.bakery, RECORDING, self.media, confirm=True, send=self.fake_send)
        with self.assertRaises(VideoError) as cm:
            transcribe.transcribe(self.bakery, RECORDING, self.media, confirm=True, send=self.fake_send)
        self.assertIn("costs money again", str(cm.exception))
        transcribe.transcribe(self.bakery, RECORDING, self.media, confirm=True, again=True, send=self.fake_send)
        self.assertEqual(len(self.sent), 2)

    def test_the_wrong_brand_or_a_folder_escape_is_refused_before_anything_else(self):
        self.keys_are({"ELEVENLABS_API_KEY": FAKE_KEY})
        with self.assertRaises(BrandError):
            transcribe.transcribe("harbour-street", RECORDING, self.media, confirm=True, send=self.fake_send)
        for bad in ("../elsewhere", "a/b", "", ".hidden"):
            with self.assertRaises(VideoError):
                transcribe.transcribe(self.bakery, bad, self.media, confirm=True, send=self.fake_send)
        self.assertEqual(self.sent, [])

    def test_naming_the_voices_is_free_all_or_nothing_and_rewrites_the_on_camera_file(self):
        transcribe.write_transcript(self.bakery, RECORDING, words=interview(names=False).words)
        with self.assertRaises(VideoError):
            transcribe.rename_speakers(self.bakery, RECORDING, {"speaker_1": AVA})            # leaves one unnamed
        with self.assertRaises(VideoError):
            transcribe.rename_speakers(self.bakery, RECORDING, {"speaker_0": AVA, "speaker_1": AVA})
        with self.assertRaises(VideoError):
            transcribe.rename_speakers(self.bakery, RECORDING, {"speaker_7": AVA, "speaker_0": HOST, "speaker_1": AVA})
        _t, policy = transcribe.rename_speakers(self.bakery, RECORDING, {"speaker_0": HOST, "speaker_1": AVA})
        self.assertEqual((policy.on_camera(), policy.off_camera()), ([AVA], [HOST]))
        on_camera = Path(common.transcriptions_dir(self.bakery, RECORDING), common.ON_CAMERA_FILE).read_text(encoding="utf-8")
        self.assertIn("Watch the dough", on_camera)
        self.assertNotIn("say it once more for the camera", on_camera)     # the host is absent, not just unselected
        self.assertEqual(self.sent, [])

    def test_an_editors_subtitles_become_a_sentence_level_transcript(self):
        srt = os.path.join(self.tmp.name, "final cut.srt")
        Path(srt).write_text("1\n00:00:04,000 --> 00:00:09,200\n<i>Most dense loaves</i>\nare simply underproofed.\n\n"
                             "2\n00:00:09,200 --> 00:00:15,000\nWatch the dough, not the clock.\n\n"
                             "junk that is not a cue\n", encoding="utf-8")
        t, policy = transcribe.ingest_srt(self.bakery, RECORDING, srt)
        self.assertEqual((len(t.segments), t.word_level, policy.status), (2, False, "unverified"))
        self.assertEqual(t.segments[0]["text"], "Most dense loaves are simply underproofed.")
        self.assertAlmostEqual(t.segments[0]["end"], 9.2)
        self.assertFalse(Transcript.load(self.bakery, RECORDING).word_level)
        with self.assertRaises(VideoError):
            policy.require_checkable()                                     # the bakery has a host: subtitles cannot clear him

    def test_the_command_line_needs_a_brand_and_speaks_plainly(self):
        self.keys_are({})
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            video_cli.cli_transcribe(["--recording", RECORDING, "--media", self.media])
        with mock.patch("builtins.print") as out:
            self.assertEqual(video_cli.cli_transcribe(["--brand", "nobody", "--recording", RECORDING, "--media", self.media]), 1)
            self.assertEqual(video_cli.cli_transcribe(["--brand", "maple-and-main", "--recording", RECORDING,
                                                       "--media", self.media]), 0)
        said = " ".join(str(c.args[0]) for c in out.call_args_list)
        self.assertIn("there is no brand called 'nobody'", said)
        self.assertIn("Nothing has been sent", said)
        self.assertNotIn("Traceback", said)


# ============================================================================= small shared pieces
class TestSharedPieces(VideoCase):
    def test_times_go_in_and_out_of_text(self):
        for text, secs in (("02:14.2", 134.2), ("1:02:03", 3723.0), ("45", 45.0), (12.5, 12.5), ("00:09,5", 9.5)):
            self.assertAlmostEqual(common.parse_ts(text), secs)
        self.assertEqual((common.fmt_ts(134.25), common.fmt_ts(3723.04, 2), common.fmt_ts(59.96)), ("02:14.2", "1:02:03.04", "01:00.0"))
        for bad in ("soon", "1:2:3:4", "", True):
            with self.assertRaises(VideoError):
                common.parse_ts(bad)

    def test_a_join_list_survives_an_apostrophe_in_a_folder_name(self):
        line = common.concat_line(os.path.join(self.tmp.name, "Ava's caf\u00e9", "part 1.mp4"))
        self.assertTrue(line.startswith("file '") and line.endswith("'\n"))
        self.assertIn("'\\''", line)
        self.assertNotIn("\\", line.replace("'\\''", ""))                  # forward slashes on every system

    def test_locations_are_recorded_relative_to_the_brand_and_never_climb_out(self):
        inside = self.place_video()
        self.assertEqual(common.locate(self.bakery, inside), "Inputs/Recordings/%s/interview-main.mp4" % RECORDING)
        self.assertEqual(common.resolve(self.bakery, RECORDING, "interview-main.mp4"), inside)
        self.assertEqual(common.resolve(self.bakery, RECORDING, "Inputs/Recordings/%s/interview-main.mp4" % RECORDING), inside)
        self.assertIsNone(common.resolve(self.bakery, RECORDING, "../../stride-physio/brand-master.json"))
        self.assertEqual(common.slug("Caf\u00e9 cr\u00e8me & Ava's \u00e9clair!"), "cafe-creme-ava-s-eclair")

    def test_a_clips_words_are_retimed_by_arithmetic_not_by_listening_again(self):
        words = spoken(("one", 10.0, 10.3), ("two", 10.4, 10.7), ("um", 12.0, 12.2), ("three", 20.0, 20.4))
        inside = common.words_in_clip([[9.8, 11.0], [19.9, 20.6]], words)
        self.assertEqual([w["word"] for w in inside], ["one", "two", "three"])
        self.assertAlmostEqual(inside[0]["start"], 0.2)
        self.assertAlmostEqual(inside[2]["start"], 1.2 + 0.1)             # after the first piece's 1.2 seconds
        shifted = common.words_in_clip([[12.8, 14.0]], words, offset=3.0)
        self.assertEqual([w["word"] for w in shifted], ["one", "two"])

    def test_a_damaged_transcript_is_reported_in_plain_words(self):
        folder = common.transcriptions_dir(self.bakery, RECORDING)
        os.makedirs(folder)
        Path(folder, common.TRANSCRIPT_FILE).write_text("{ not json", encoding="utf-8")
        with self.assertRaises(VideoError) as cm:
            Transcript.load(self.bakery, RECORDING)
        self.assertIn("damaged", str(cm.exception))
        with self.assertRaises(VideoError) as cm:
            Transcript.load(self.bakery, "a recording nobody made")
        self.assertIn("no transcript yet", str(cm.exception))

    def test_what_a_clip_is_judged_on_is_what_was_heard_in_the_file(self):
        clip = {"segments": [{"starts_with": "Watch the dough", "ends_with": "not the clock", "duration": 3.0},
                             {"starts_with": "Most dense loaves are simply", "ends_with": "never gets there", "duration": 9.0}]}
        right = [(0.2, 0.5, "Watch"), (0.6, 0.8, "the"), (0.9, 1.3, "dough,"), (3.2, 3.5, "Most"), (3.6, 3.9, "dense"),
                 (4.0, 4.4, "loaves"), (4.5, 4.7, "are"), (4.8, 5.2, "simply"), (10.6, 10.9, "never"), (11.0, 11.3, "gets"),
                 (11.4, 11.8, "there.")]
        checks = validate_cuts.judge(clip, right, 12.0)
        self.assertEqual(checks, {"head": 1.0, "seam 1": 1.0, "tail": 1.0})
        wrong = [(t0 + 0.0, t1, w) for t0, t1, w in right if w not in ("Most", "dense", "loaves", "simply")]
        self.assertLess(validate_cuts.judge(clip, wrong, 12.0)["seam 1"], validate_cuts.THRESHOLD)
        self.assertEqual(validate_cuts.match_ratio("90 kilos", ["ninety", "kilos"]), 1.0)     # numbers never decide it


# ============================================================================= with the real video programs
def _video_tier():
    try:
        import static_ffmpeg                                               # noqa: F401
        from smf import media
        media.ensure_ffmpeg()
        return True
    except Exception:
        return False


def _speech_model_is_here():
    if not HAS_VIDEO:
        return False
    try:
        os.environ.setdefault("HF_HUB_VERBOSITY", "error")
        from faster_whisper import WhisperModel
        WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
        return True
    except Exception:
        return False


HAS_VIDEO = _video_tier()
NEEDS_VIDEO = "the video tools are not installed (python factory.py setup --tier video)"

# A tone that is silent for the first second of every four, like someone pausing between sentences.
SENTENCES = [
    (AVA, 1.2, "Most dense loaves are simply underproofed."),
    (AVA, 5.2, "People trust the recipe time."),
    (HOST, 9.2, "Say that again please."),
    (AVA, 13.2, "Watch the dough, not the clock."),
    (AVA, 17.2, "um"),
    (AVA, 21.2, "Time is an ingredient."),
]


def timed_sentences():
    words = []
    for voice, start, text in SENTENCES:
        t = start
        for w in text.split():
            words.append({"word": w, "start": round(t, 3), "end": round(t + 0.4, 3), "speaker": voice})
            t += 0.5
    return words


class RealVideoCase(VideoCase):
    """Makes a 26 second test video (colour bars, a tone with pauses) and its invented transcript."""

    def setUp(self):
        super().setUp()
        from smf import media
        self.ff, self.fp = media.ensure_ffmpeg()
        folder = common.recording_dir(self.bakery, RECORDING)
        os.makedirs(folder)
        self.video = os.path.join(folder, "Ava's caf\u00e9 take.mp4")
        made = subprocess.run([self.ff, "-y", "-hide_banner", "-loglevel", "error",
                               "-f", "lavfi", "-i", "smptebars=size=320x180:rate=25:duration=26",
                               "-f", "lavfi", "-i", "sine=frequency=330:duration=26",
                               "-af", "volume=0:enable='lt(mod(t,4),1)'",
                               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                               "-shortest", self.video], capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stderr[-400:])
        transcribe.write_transcript(self.bakery, RECORDING, words=timed_sentences(),
                                    source={"media": common.locate(self.bakery, self.video), "duration": 26.0})
        self.t = Transcript.load(self.bakery, RECORDING)

    def write_cut_list(self, end_phrase="Watch the dough, not the clock", late=0.0):
        cl = cutlist.CutList(title=RECORDING)
        cl.reference = {"recording": "A test tone standing in for a shop interview", "brand": "maple-and-main",
                        "cut_from": "Ava's caf\u00e9 take.mp4", "timestamps_from": "Transcriptions/transcript.json", "offset": "0"}
        s, _ = when(self.t, "Most dense loaves")
        _, e = when(self.t, end_phrase)
        h = when(self.t, "Watch the dough, not the clock")
        cl.bodies = [cutlist.Body(key="A", title="Caf\u00e9 loaves, Ava's way", start=s + late, end=e,
                                  starts_with="Most dense loaves are simply", ends_with=end_phrase,
                                  on_screen_text="Your loaf is not broken", lower_third="Ava Lindqvist, Head Baker",
                                  gate="SHIP", hooks=[cutlist.Hook(1, h[0], h[1], "Watch the dough, not the clock"),
                                                      cutlist.Hook(2, s, s + 2.4, "Most dense loaves are simply underproofed")])]
        path = common.output_dir(self.bakery, RECORDING, common.CUT_LIST_FILE)
        common.write_text_atomic(path, cutlist.write(cl))
        return path


@unittest.skipUnless(HAS_VIDEO, NEEDS_VIDEO)
class TestWithRealVideo(RealVideoCase):
    def test_the_tools_measure_what_is_really_in_the_file(self):
        self.assertAlmostEqual(common.probe_duration(self.video), 26.0, delta=0.2)
        self.assertTrue(common.has_audio(self.video))
        self.assertEqual(common.probe_shape(self.video), {"orientation": "horizontal", "width": 320, "height": 180})
        self.assertTrue(common.decodes_cleanly(self.video))
        pauses = rough_cut.find_silences(self.video, 0.0, 10.0)
        self.assertTrue(any(abs(a - 4.0) < 0.15 and abs(b - 5.0) < 0.15 for a, b in pauses), pauses)

    def test_rough_cuts_are_made_from_a_folder_with_an_apostrophe_and_the_host_is_not_in_them(self):
        self.write_cut_list()
        report = rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript")
        out = common.output_dir(self.bakery, RECORDING, "rough")
        self.assertEqual([c["status"] for c in report["clips"]], ["ok", "ok"])
        lifted, in_place = report["clips"]
        self.assertEqual(lifted["file"], "A1-cafe-loaves-ava-s-way.mp4")
        for c in report["clips"]:
            self.assertTrue(os.path.isfile(os.path.join(out, c["file"])))
            self.assertAlmostEqual(c["actual_duration"], c["expected_duration"], delta=0.35)
            self.assertTrue(common.decodes_cleanly(os.path.join(out, c["file"])))
        # the host spoke inside the body, so the body became two pieces and neither touches him
        host0, host1 = when(self.t, "Say that again please.")
        body_pieces = [s["cut"] for s in in_place["segments"]]
        self.assertEqual(len(body_pieces), 2)
        for a, b in body_pieces:
            self.assertFalse(a < host1 and b > host0, (a, b))
        turns, policy = self.t.turns(), gate.SpeakerPolicy.for_transcript(self.bakery, self.t)
        self.assertEqual(validate_cuts.off_camera_inside(in_place, turns, policy, 0.0), 0.0)
        # the shared body was encoded once and both clips were joined from the same parts
        self.assertEqual([s["part"] for s in lifted["segments"][1:]], [s["part"] for s in in_place["segments"]])
        self.assertTrue(all(s["snap"] == ["text", "text"] for s in lifted["segments"][:1]))
        saved = json.loads(Path(out, "rough-cut-report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["source"], "Inputs/Recordings/%s/Ava's caf\u00e9 take.mp4" % RECORDING)
        self.assertFalse(any(os.path.islink(os.path.join(out, n)) for n in os.listdir(out)))

    def test_a_dry_run_plans_every_cut_and_makes_nothing(self):
        self.write_cut_list()
        report = rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript", dry_run=True)
        self.assertEqual({c["status"] for c in report["clips"]}, {"planned"})
        self.assertFalse(os.path.exists(common.output_dir(self.bakery, RECORDING, "rough")))

    def test_a_video_that_is_not_the_one_that_was_transcribed_is_refused(self):
        self.write_cut_list()
        transcribe.write_transcript(self.bakery, RECORDING, words=timed_sentences(), source={"duration": 300.0})
        with self.assertRaises(VideoError) as cm:
            rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript")
        self.assertIn("not the same video", str(cm.exception))

    def test_a_broken_cut_list_stops_the_cut_and_lists_every_problem(self):
        path = self.write_cut_list()
        text = Path(path).read_text(encoding="utf-8").replace('"Watch the dough, not the clock"', '"Bread is easy, honestly"')
        Path(path).write_text(text, encoding="utf-8")
        with self.assertRaises(rough_cut.CutListProblems) as cm:
            rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript")
        self.assertTrue(any("not in the transcript" in f.detail for f in cm.exception.findings))
        with mock.patch("builtins.print"):
            self.assertEqual(video_cli.cli_rough_cut(["--brand", "maple-and-main", "--recording", RECORDING]), 1)

    def test_the_fine_cut_reads_the_real_cuts_takes_out_dead_air_and_keeps_every_word(self):
        # The cut list's start time is 0.6s LATE: it points past the first word. The rough cut moves
        # outward to catch the quoted word, and the fine cut must plan from where the rough cut really
        # cut. Planning from the written time instead would lose "Most".
        self.write_cut_list(end_phrase="Time is an ingredient.", late=0.6)
        rough = rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript", only=["A2"])
        self.assertLess(rough["clips"][0]["segments"][0]["cut"][0], rough["clips"][0]["segments"][0]["requested"][0])
        fine = fine_cut.fine_cut(self.bakery, RECORDING)
        clip = fine["clips"][0]
        self.assertEqual((clip["id"], clip["status"]), ("A2", "ok"))
        self.assertLess(clip["fine_duration"], clip["rough_duration"] - 2.0)
        self.assertTrue(any("filler 'um'" in r["reason"] for r in clip["removals"]))
        self.assertAlmostEqual(clip["actual_duration"], clip["fine_duration"], delta=1.0)
        kept = [w["word"] for w in common.words_in_clip(clip["pieces"], self.t.words)]
        self.assertEqual(kept, [w for w in " ".join(s[2] for s in SENTENCES if s[0] == AVA).split() if w != "um"])
        # and the pieces either side of the host still keep clear of him
        host0, host1 = when(self.t, "Say that again please.")
        for a, b in clip["pieces"]:
            self.assertFalse(a < host1 + gate.WALL_GUARD - 0.05 and b > host0 - gate.WALL_GUARD + 0.05, (a, b))
        out = common.output_dir(self.bakery, RECORDING, "fine")
        self.assertTrue(common.decodes_cleanly(os.path.join(out, clip["file"])))

    def test_recutting_one_clip_does_not_make_the_others_disappear_from_the_report(self):
        self.write_cut_list()
        rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript")
        again = rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript", only=["A2"])
        self.assertEqual([c["id"] for c in again["clips"]], ["A2"])
        saved = json.loads(Path(common.output_dir(self.bakery, RECORDING, "rough"), "rough-cut-report.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual([c["id"] for c in saved["clips"]], ["A1", "A2"])

    def test_a_sound_only_recording_is_refused_in_plain_words(self):
        sound = os.path.join(common.recording_dir(self.bakery, RECORDING), "sound only.m4a")
        subprocess.run([self.ff, "-y", "-loglevel", "error", "-i", self.video, "-vn", "-c:a", "copy", sound], check=True)
        path = self.write_cut_list()
        text = Path(path).read_text(encoding="utf-8").replace("Ava's caf\u00e9 take.mp4", "sound only.m4a")
        Path(path).write_text(text, encoding="utf-8")
        with self.assertRaises(VideoError) as cm:
            rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript")
        self.assertIn("no picture", str(cm.exception))

    def test_a_half_written_part_is_made_again_instead_of_adopted(self):
        self.write_cut_list()
        report = rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript", only=["A1"])
        out = common.output_dir(self.bakery, RECORDING, "rough")
        part = os.path.join(out, *report["clips"][0]["segments"][0]["part"].split("/"))
        whole = common.probe_duration(part)
        short = part + ".short.mp4"
        subprocess.run([self.ff, "-y", "-loglevel", "error", "-i", part, "-t", "0.5", "-c", "copy", short], check=True)
        os.replace(short, part)
        self.assertFalse(common.usable_part(part, whole))
        rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript", only=["A1"])
        self.assertTrue(common.usable_part(part, whole))

    def test_checking_nothing_is_never_a_pass(self):
        with self.assertRaises(VideoError):
            validate_cuts.validate(self.bakery, RECORDING, hear=lambda p: [])
        self.write_cut_list()
        rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript", only=["A2"])
        with self.assertRaises(VideoError) as cm:
            validate_cuts.validate(self.bakery, RECORDING, only=["Z9"], hear=lambda p: [])
        self.assertIn("not a pass", str(cm.exception))

    def test_a_clip_passes_on_what_is_heard_in_it_and_a_damaged_file_fails(self):
        self.write_cut_list()
        rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript", only=["A2"])
        out = common.output_dir(self.bakery, RECORDING, "rough")
        saved = json.loads(Path(out, "rough-cut-report.json").read_text(encoding="utf-8"))
        clip = saved["clips"][0]

        def hears_the_right_words(_path):
            return [(w["start"], w["end"], w["word"]) for w in common.words_in_clip(clip["pieces"], self.t.words)]
        self.assertEqual(validate_cuts.validate(self.bakery, RECORDING, hear=hears_the_right_words)["failed"], [])
        self.assertEqual(validate_cuts.validate(self.bakery, RECORDING, hear=lambda p: [])["failed"], ["A2"])
        path = os.path.join(out, clip["file"])
        with open(path, "r+b") as f:                                      # right name, plausible size, broken inside
            f.truncate(os.path.getsize(path) // 2)
        result = validate_cuts.validate(self.bakery, RECORDING, hear=hears_the_right_words)
        self.assertEqual(result["failed"], ["A2"])
        self.assertIn("does not play", result["clips"][0]["problems"][0])


@unittest.skipUnless(_speech_model_is_here(), "the small speech model has not been downloaded yet "
                                              "(python factory.py doctor --deep)")
class TestWithTheSpeechModel(RealVideoCase):
    """Only one thing needs the real model: proving the checker listens to the FILE. A tone has no
    words in it, so a clip cut from a tone must fail, however right the plan looked."""

    def test_a_clip_with_no_such_words_in_it_fails_however_good_the_plan_was(self):
        self.write_cut_list()
        rough_cut.rough_cut(self.bakery, RECORDING, listen="transcript", only=["A2"])
        result = validate_cuts.validate(self.bakery, RECORDING)
        self.assertEqual(result["failed"], ["A2"])
        self.assertTrue(any("not heard" in p for p in result["clips"][0]["problems"]))

    def test_listening_to_the_real_video_finds_no_quoted_words_in_a_tone_and_says_so(self):
        self.write_cut_list()
        with self.assertRaises(VideoError) as cm:
            rough_cut.rough_cut(self.bakery, RECORDING, listen="model")
        self.assertIn("different video file", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(common.output_dir(self.bakery, RECORDING, "rough"), "rough-cut-report.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
