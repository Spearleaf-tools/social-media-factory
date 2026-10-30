"""Two-camera tests: recordings are lined up by their sound with the RIGHT SIGN, the picture follows
the speaker without flickering, who is on which camera is never guessed, and a finished video is
checked by looking at it rather than by re-reading the plan.

    python -m unittest discover -s tests -t . -v

Nothing here uses the network or a key. The conversation is invented: a baker and the presenter
interviewing her. Sound is made with numpy: bursts of noise where the words are, near-silence
between them. (A pure tone will not do. It matches itself at every shift, which is exactly why
one test here proves a tone is refused.) Tests that need the video programs are skipped, with the
reason, when the video tier is not installed; when it is, they build two tiny "cameras" from plain
colour sources, in a folder whose name has a space, an apostrophe and an accent.
"""
from __future__ import annotations

import copy
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:                                                                       # numpy comes with the core install;
    import numpy as np                                                     # noqa: E402   a bare Python still has to
except ImportError:                                                        # be able to LOAD this file and skip
    np = None

from smf import brands                                                     # noqa: E402
from smf.brands import BrandError                                          # noqa: E402
from smf.video import common, cutlist, fine_cut, multicam, multicam_cli, multicam_clips, multicam_verify  # noqa: E402
from smf.video import rough_cut, sync, transcribe, validate_cuts          # noqa: E402
from smf.video.common import Transcript, VideoError                       # noqa: E402
from tests.test_brands import BAKERY, BrandCase                           # noqa: E402

HAS_NUMPY = np is not None
NEEDS_NUMPY = "numpy is not installed (python factory.py setup)"
RATE = 16000
AVA, JONAH, PRODUCER = "Ava Lindqvist", "Jonah Pell", "Mirela Santos"
RECORDING = "Ava's café chat"
CAMERA_A, CAMERA_B = "wide d'Ava.mp4", "close été.mp4"
B_STARTED_LATE = 1.25            # camera B was switched on this long after camera A


def talk(seconds, seed, rate=RATE):
    """Speech-shaped noise: bursts of different loudness with gaps between them."""
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    sound, loud, t = rng.standard_normal(n), np.zeros(n), 0
    while t < n:
        on, off = int(rng.uniform(0.25, 1.6) * rate), int(rng.uniform(0.1, 0.9) * rate)
        loud[t:t + on] = rng.uniform(0.3, 1.0)
        t += on + off
    return sound * loud * 0.3


def two_microphones(base, a_from, b_from, seed=5):
    """The same talk as two different microphones heard it, each starting at its own moment."""
    rng = np.random.default_rng(seed)
    a = base[a_from:] + 0.05 * rng.standard_normal(len(base) - a_from)
    b = 0.4 * base[b_from:] + 0.05 * rng.standard_normal(len(base) - b_from)
    return sync.ArraySound(a, RATE, "wide.mp4"), sync.ArraySound(b, RATE, "close.mp4")


# ============================================================================= lining up by sound
@unittest.skipUnless(HAS_NUMPY, NEEDS_NUMPY)
class TestOffsetsCarryTheirSign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = talk(80, seed=1)

    def test_a_known_shift_is_recovered_with_its_sign_both_ways(self):
        # b_time = a_time + offset. Camera B switched on LATER than A -> the same moment has a
        # smaller time in B -> negative. Switched on EARLIER -> positive.
        for a_from, b_from in ((0, int(1.25 * RATE)), (int(2.0 * RATE), 0), (int(12.5 * RATE), int(0.3 * RATE))):
            a, b = two_microphones(self.base, a_from, b_from)
            found = sync.measure_offset(a, b)
            self.assertAlmostEqual(found.seconds, (a_from - b_from) / float(RATE), places=3)
            self.assertTrue(found.checked)
            self.assertLessEqual(abs(found.residual), sync.BY_SOUND["residual_limit"])
            self.assertLessEqual(found.spread, 0.01)
            self.assertEqual((found.confidence, found.confidence_word, found.method), (1.0, "high", "sound"))
            json.dumps(found.as_dict())                                     # plain numbers, ready to be saved

    def test_the_flipped_sign_is_rejected_by_listening_again(self):
        a, b = two_microphones(self.base, 0, int(1.25 * RATE))
        right = sync.measure_offset(a, b).seconds
        self.assertAlmostEqual(right, -1.25, places=3)
        # The check that fools people: same size, so "convert back with the same number" agrees.
        self.assertEqual(abs(-right), abs(right))
        # The check that does not: shift by it, listen again, and look at what is left over.
        self.assertTrue(sync.check_offset(a, b, right)["ok"])
        flipped = sync.check_offset(a, b, -right)
        self.assertFalse(flipped["ok"])
        self.assertAlmostEqual(abs(flipped["residual"]), 2 * abs(right), places=2)   # twice as far out as before
        self.assertIn("back to front", flipped["why"])
        self.assertFalse(sync.check_offset(a, b, right + 0.4)["ok"])                  # and a wrong size fails too

    def test_two_unrelated_noises_are_refused(self):
        with self.assertRaises(sync.SyncRefused) as cm:
            sync.measure_offset(sync.ArraySound(talk(60, 2), RATE, "wide.mp4"),
                                sync.ArraySound(talk(60, 3), RATE, "close.mp4"))
        self.assertIn("may not be recordings of the same conversation", str(cm.exception))

    def test_a_recording_that_was_paused_part_way_is_refused_not_averaged(self):
        paused = np.concatenate((self.base[:40 * RATE], self.base[45 * RATE:]))
        with self.assertRaises(sync.SyncRefused) as cm:
            sync.measure_offset(sync.ArraySound(self.base, RATE, "wide.mp4"), sync.ArraySound(paused, RATE, "close.mp4"))
        self.assertIn("different answers", str(cm.exception))
        # ... and a number somebody types for it is refused by the same listening check
        self.assertFalse(sync.check_offset(sync.ArraySound(self.base, RATE), sync.ArraySound(paused, RATE), 0.0)["ok"])

    def test_a_pure_tone_matches_everywhere_so_it_is_no_evidence(self):
        t = np.arange(40 * RATE) / float(RATE)
        with self.assertRaises(sync.SyncRefused):
            sync.measure_offset(sync.ArraySound(np.sin(2 * np.pi * 330 * t), RATE, "a"),
                                sync.ArraySound(np.sin(2 * np.pi * 330 * (t + 0.7)), RATE, "b"))

    def test_a_long_silence_in_the_middle_does_not_pull_the_answer(self):
        quiet = self.base.copy()
        quiet[25 * RATE:50 * RATE] *= 0.0005
        a, b = two_microphones(quiet, 0, int(0.5 * RATE))
        self.assertAlmostEqual(sync.measure_offset(a, b).seconds, -0.5, places=2)

    def test_slow_clock_drift_is_centred_and_reported_and_fast_drift_is_refused(self):
        gentle = np.interp(np.arange(0, len(self.base) - 1, 1 + 60e-6), np.arange(len(self.base)), self.base)
        found = sync.measure_offset(sync.ArraySound(self.base, RATE, "wide.mp4"), sync.ArraySound(gentle, RATE, "close.mp4"))
        self.assertLess(abs(found.seconds), 0.01)
        self.assertAlmostEqual(found.drift_per_hour, -0.216, delta=0.05)     # 60 parts in a million, with its sign
        steps = [{"at": float(t), "offset": 1.0 + 0.004 * t, "clear": True} for t in range(0, 140, 20)]
        self.assertEqual(sync._judge(steps, sync.BY_SOUND, 140.0)[2], "drift")
        self.assertEqual(sync._judge(steps[:3] + [dict(steps[3], offset=9.0)] + steps[4:], sync.BY_SOUND, 140.0)[2],
                         "disagree")

    def test_too_little_in_common_is_said_plainly(self):
        with self.assertRaises(sync.SyncRefused) as cm:
            sync.measure_offset(sync.ArraySound(talk(3, 1), RATE, "a"), sync.ArraySound(talk(3, 1), RATE, "b"))
        self.assertIn("too short", str(cm.exception))

    def test_the_sentence_says_which_way_round_with_a_worked_example(self):
        later = sync.in_words(-1.25, "camera A", "camera B")
        self.assertIn("Camera A was already recording 1.250 seconds before camera B started", later)
        self.assertIn("01:00.00 in camera A is at 00:58.75 in camera B", later)
        earlier = sync.in_words(2.0, "camera A", "camera B")
        self.assertIn("Camera B was already recording 2.000 seconds before camera A started", earlier)
        self.assertIn("01:00.00 in camera A is at 01:02.00 in camera B", earlier)
        self.assertEqual([sync.offset_text(x) for x in (3.159, -2.4, 0.0, -0.0001)], ["+3.159", "-2.4", "0", "0"])


def spoken_words(seed=11, until=110.0, voice=AVA):
    rng = np.random.default_rng(seed)
    words, t = [], 1.0
    while t < until:
        for _ in range(int(rng.integers(3, 12))):
            d = float(rng.uniform(0.18, 0.5))
            words.append({"word": "bread", "start": round(t, 3), "end": round(t + d, 3), "speaker": voice})
            t += d + float(rng.uniform(0.03, 0.12))
        t += float(rng.uniform(0.5, 2.0))
    return words


def sound_of(words, shift, seconds, seed=4):
    rng = np.random.default_rng(seed)
    x = 0.004 * rng.standard_normal(int(seconds * RATE))
    for w in words:
        i, j = max(0, int((w["start"] + shift) * RATE)), int((w["end"] + shift) * RATE)
        if j > i:
            x[i:j] += 0.3 * rng.standard_normal(j - i)
    return x


@unittest.skipUnless(HAS_NUMPY, NEEDS_NUMPY)
class TestATranscriptAgainstAVideo(unittest.TestCase):
    """The cut list's Offset (video time = transcript time + offset) when the file that was
    transcribed is gone: the words' own times against the video's loudness."""

    def test_the_offset_is_found_from_the_words_alone_with_its_sign(self):
        transcript = Transcript({"words": spoken_words()})
        for shift in (3.16, -2.4, 0.0):
            video = sync.ArraySound(sound_of(transcript.words, shift, transcript.duration + 8), RATE, "take.mp4")
            found = sync.measure_transcript_offset(video, transcript)
            self.assertAlmostEqual(found.seconds, shift, delta=0.05)
            self.assertEqual((found.method, found.checked), ("words", True))
            if shift:
                flipped = sync.check_offset(sync.activity(transcript), sync._loudness_of(video), -found.seconds, sync.BY_WORDS)
                self.assertFalse(flipped["ok"])

    def test_words_that_belong_to_some_other_recording_are_refused(self):
        transcript = Transcript({"words": spoken_words(seed=11)})
        other = sync.ArraySound(sound_of(spoken_words(seed=99), 0.0, 120), RATE, "another day.mp4")
        with self.assertRaises(sync.SyncRefused):
            sync.measure_transcript_offset(other, transcript)

    def test_sentence_times_alone_are_not_enough_and_it_says_what_to_do(self):
        subtitles = Transcript({"segments": [{"start": 1.0, "end": 4.0, "text": "Watch the dough, not the clock."}]})
        with self.assertRaises(sync.SyncRefused) as cm:
            sync.measure_transcript_offset(sync.ArraySound(talk(30, 1), RATE, "take.mp4"), subtitles)
        self.assertIn("sentence times only", str(cm.exception))


# ============================================================================= turn-taking
def turn(voice, start, end, text="We proof the dough overnight in the cold room and bake at dawn"):
    return {"speaker": voice, "start": start, "end": end, "text": text}


ON = {AVA: "A", JONAH: "B", "": None}


def shows(shots):
    return [s["show"] for s in shots]


class TestThePictureFollowsTheSpeaker(unittest.TestCase):
    def test_it_cuts_to_whoever_is_talking_a_moment_before_their_first_word(self):
        shots = multicam.build_decisions([turn(AVA, 0.5, 9.0), turn(JONAH, 10.0, 20.0), turn(AVA, 21.0, 30.0)],
                                         ON, layout="solo", start=0.0, end=30.0, fps=25.0)
        self.assertEqual(shows(shots), ["A", "B", "A"])
        self.assertAlmostEqual(shots[1]["start"], 10.0 - multicam.RULES["cut_ahead"], delta=0.021)   # on a whole frame
        self.assertLess(shots[1]["start"], 10.0)
        self.assertEqual({s["why"] for s in shots}, {"speaking"})

    def test_no_shot_is_shorter_than_the_minimum_however_fast_the_talk(self):
        for seed in range(12):
            rng = random.Random(seed)
            turns, t = [], 0.0
            while t < 120:
                length = rng.choice((0.3, 0.7, 1.1, 1.8, 2.6, 4.0, 9.0))
                turns.append(turn(rng.choice((AVA, JONAH)), t, t + length))
                t += length + rng.choice((-0.5, 0.0, 0.1, 0.4, 1.2))
                t = max(t, 0.0)
            for layout in ("hybrid", "solo"):
                shots = multicam.build_decisions(turns, ON, layout=layout, start=0.0, end=120.0, fps=30.0)
                lengths = [s["end"] - s["start"] for s in shots]
                self.assertGreaterEqual(min(lengths), multicam.RULES["shortest_shot"] - 0.5 / 30.0, (seed, layout))
                # no gaps, no overlaps, whole frames, the whole range
                self.assertEqual((shots[0]["start"], shots[-1]["end"]), (0.0, 120.0))
                for before, after in zip(shots, shots[1:]):
                    self.assertEqual(before["end"], after["start"])
                    self.assertNotEqual(before["show"], after["show"])
                    self.assertAlmostEqual(after["start"] * 30.0, round(after["start"] * 30.0), places=2)
                if layout == "solo":
                    self.assertNotIn("both", shows(shots))

    def test_a_short_interjection_is_held_through(self):
        talk_ = [turn(AVA, 0.0, 9.0), turn(JONAH, 9.1, 9.6, "Yeah, right."), turn(AVA, 9.8, 20.0)]
        self.assertEqual(shows(multicam.build_decisions(talk_, ON, layout="solo", start=0.0, end=20.0)), ["A"])
        # the same length of talk that is NOT an acknowledgement, and long enough, does take the shot
        rules = {"shortest_shot": 1.0}
        real = [turn(AVA, 0.0, 9.0), turn(JONAH, 9.1, 10.4, "Which flour though?"), turn(AVA, 10.6, 20.0)]
        self.assertEqual(shows(multicam.build_decisions(real, ON, layout="solo", start=0.0, end=20.0, rules=rules)),
                         ["A", "B", "A"])
        # and anything shorter than the shortest turn never does, whatever was said
        blip = [turn(AVA, 0.0, 9.0), turn(JONAH, 9.1, 9.5, "Flour!"), turn(AVA, 9.8, 20.0)]
        self.assertEqual(shows(multicam.build_decisions(blip, ON, layout="solo", start=0.0, end=20.0, rules=rules)), ["A"])
        self.assertTrue(multicam.is_interjection(turn(JONAH, 0, 1.0, "Mm-hmm. Okay."), multicam.RULES))
        self.assertFalse(multicam.is_interjection(turn(JONAH, 0, 1.0, "Okay but why?"), multicam.RULES))

    def test_both_people_are_shown_while_they_talk_over_each_other(self):
        over = [turn(AVA, 0.0, 12.0), turn(JONAH, 9.0, 18.0), turn(AVA, 19.0, 30.0)]
        shots = multicam.build_decisions(over, ON, layout="hybrid", start=0.0, end=30.0,
                                         rules={"open_wide": 0, "close_wide": 0})
        both = [s for s in shots if s["show"] == "both"]
        self.assertEqual([s["why"] for s in both], ["both talking"])
        self.assertLessEqual(both[0]["start"], 9.0)
        self.assertGreaterEqual(both[0]["end"], 12.0)
        self.assertEqual(shows(multicam.build_decisions(over, ON, layout="solo", start=0.0, end=30.0)), ["A", "B", "A"])

    def test_a_quick_back_and_forth_is_shown_wide_instead_of_ping_ponged(self):
        rally, t = [turn(AVA, 0.0, 10.0)], 10.2
        for i in range(8):
            rally.append(turn((JONAH, AVA)[i % 2], t, t + 0.8, "No it is not the flour"))
            t += 0.9
        rally.append(turn(AVA, t + 0.5, t + 12.0))
        shots = multicam.build_decisions(rally, ON, layout="hybrid", start=0.0, end=t + 12.0,
                                         rules={"open_wide": 0, "close_wide": 0, "wide_every": 0})
        self.assertIn("quick back-and-forth", [s["why"] for s in shots if s["show"] == "both"])
        self.assertLessEqual(len(shots), 4)

    def test_the_look_at_both_after_a_long_stretch_is_optional_and_lands_on_a_pause(self):
        long_talk = [turn(AVA, 0.0, 50.0), turn(AVA, 53.0, 120.0)]            # one pause, at 50 to 53
        quiet = {"open_wide": 0, "close_wide": 0}
        shots = multicam.build_decisions(long_talk, ON, layout="hybrid", start=0.0, end=120.0, rules=quiet)
        wide = [s for s in shots if s["show"] == "both"]
        self.assertTrue(wide and all(s["why"] == "a look at both after a long stretch" for s in wide))
        self.assertAlmostEqual(wide[0]["start"], 51.5, delta=0.05)           # the middle of the pause, not 45.0 sharp
        never = multicam.build_decisions(long_talk, ON, layout="hybrid", start=0.0, end=120.0,
                                         rules=dict(quiet, wide_every=0))
        self.assertEqual(shows(never), ["A"])

    def test_it_opens_and_closes_on_both_people_unless_the_video_is_short(self):
        talk_ = [turn(AVA, 0.0, 30.0), turn(JONAH, 31.0, 60.0)]
        shots = multicam.build_decisions(talk_, ON, layout="hybrid", start=0.0, end=60.0, rules={"wide_every": 0})
        self.assertEqual([(s["show"], s["why"]) for s in (shots[0], shots[-1])], [("both", "opening"), ("both", "closing")])
        short = multicam.build_decisions(talk_, ON, layout="hybrid", start=0.0, end=20.0, rules={"wide_every": 0})
        self.assertEqual(shows(short), ["A"])

    def test_side_by_side_is_one_shot_and_needs_nobody_placed(self):
        shots = multicam.build_decisions([turn("speaker_7", 0.0, 5.0)], {}, layout="side-by-side", start=0.0, end=10.0)
        self.assertEqual([(s["show"], s["start"], s["end"]) for s in shots], [("both", 0.0, 10.0)])

    def test_a_first_shot_too_short_to_read_is_taken_over_by_the_next_one(self):
        shots = multicam.build_decisions([turn(JONAH, 0.0, 1.2, "So why is that"), turn(AVA, 1.4, 12.0)], ON,
                                         layout="solo", start=0.0, end=12.0, rules={"shortest_turn": 0.2})
        self.assertEqual([(s["show"], s["start"]) for s in shots], [("A", 0.0)])

    def test_a_stretch_with_no_talk_long_enough_to_cut_to_still_shows_someone_sensible(self):
        hook_only = [turn(AVA, 0.0, 8.0), turn(JONAH, 20.0, 20.4, "Really?"), turn(AVA, 30.0, 40.0)]
        self.assertEqual(shows(multicam.build_decisions(hook_only, ON, layout="solo", start=19.5, end=21.0)), ["B"])
        self.assertEqual(shows(multicam.build_decisions(hook_only, ON, layout="solo", start=10.0, end=14.0)), ["A"])

    def test_the_list_of_shots_is_deterministic(self):
        rng = random.Random(7)
        turns, t = [], 0.0
        while t < 300:
            length = rng.uniform(0.3, 14.0)
            turns.append(turn(rng.choice((AVA, JONAH)), round(t, 3), round(t + length, 3)))
            t += length + rng.uniform(-0.4, 1.5)
        once = multicam.build_decisions(turns, ON, start=0.0, end=300.0)
        again = multicam.build_decisions(copy.deepcopy(turns), dict(ON), start=0.0, end=300.0)
        shuffled = copy.deepcopy(turns)
        rng.shuffle(shuffled)
        self.assertEqual(json.dumps(once), json.dumps(again))
        self.assertEqual(json.dumps(once), json.dumps(multicam.build_decisions(shuffled, ON, start=0.0, end=300.0)))
        self.assertEqual(multicam.summarise(once)["shots"], len(once))
        self.assertAlmostEqual(sum(multicam.summarise(once)["share_of_screen"].values()), 1.0, places=2)

    def test_a_voice_nobody_placed_is_an_error_never_a_guess(self):
        with self.assertRaises(VideoError) as cm:
            multicam.build_decisions([turn(AVA, 0, 5), turn("speaker_2", 5, 10)], ON, start=0.0, end=10.0)
        self.assertIn("speaker_2", str(cm.exception))
        self.assertIn("Nothing is guessed", str(cm.exception))

    def test_a_misspelt_rule_or_layout_is_an_error_not_a_setting_that_does_nothing(self):
        for bad in ({"shortest_shoot": 3}, {"shortest_shot": -1}, {"shortest_shot": "long"}, {"cut_ahead": True}):
            with self.assertRaises(VideoError):
                multicam.merge_rules(bad)
        self.assertEqual(multicam.merge_rules({"back_and_forth_changes": 3.0})["back_and_forth_changes"], 3)
        with self.assertRaises(VideoError):
            multicam.build_decisions([turn(AVA, 0, 5)], ON, layout="picture-in-picture", start=0.0, end=5.0)


class TestTheEncoderIsSoftwareUnlessHardwareIsProven(unittest.TestCase):
    LISTED = " V....D libx264              libx264 H.264\n V....D h264_videotoolbox    VideoToolbox H.264 Encoder\n"

    def test_software_is_the_default_everywhere(self):
        self.assertEqual(multicam.SOFTWARE, "libx264")
        self.assertEqual(multicam.pick_encoder("auto", listed=" V....D libx264   x\n", works=lambda n: True,
                                               platform="darwin"), "libx264")
        self.assertEqual(multicam.pick_encoder("auto", listed=self.LISTED, works=lambda n: True, platform="win32"), "libx264")
        self.assertEqual(multicam.pick_encoder(None, listed=self.LISTED, works=lambda n: False, platform="darwin"), "libx264")

    def test_hardware_is_used_only_when_listed_and_working_and_not_refused(self):
        self.assertEqual(multicam.pick_encoder("auto", listed=self.LISTED, works=lambda n: True, platform="darwin"),
                         "h264_videotoolbox")
        self.assertEqual(multicam.pick_encoder("software", listed=self.LISTED, works=lambda n: True, platform="darwin"),
                         "libx264")
        with self.assertRaises(VideoError) as cm:
            multicam.pick_encoder("hardware", listed=self.LISTED, works=lambda n: False, platform="darwin")
        self.assertIn("software one works everywhere", str(cm.exception))
        with self.assertRaises(VideoError):
            multicam.pick_encoder("fastest")
        self.assertIn("-crf", multicam.encoder_args("libx264", (1920, 1080), 30.0))
        self.assertIn("6000k", multicam.encoder_args("h264_videotoolbox", (1920, 1080), 30.0))


# ============================================================================= a brand, a recording, two cameras
CONVERSATION = [
    (JONAH, 0.6, "So tell me why do so many home loaves come out dense and heavy in the middle?"),
    (AVA, 0.9, "Most dense loaves are simply underproofed. People trust the recipe time but the kitchen is cold."),
    (JONAH, 0.3, "Right."),
    (AVA, 0.4, "So I tell every class the same thing. Watch the dough, not the clock."),
    (JONAH, 1.0, "And is cheap flour the real problem when a loaf fails to rise at home?"),
    (AVA, 0.9, "Cheap flour is not the problem. Time is an ingredient and most people leave it out."),
]


def lay_out(lines, word=0.30, gap=0.08):
    words, t = [], 0.0
    for voice, pause, text in lines:
        t += pause
        for w in text.split():
            words.append({"word": w, "start": round(t, 3), "end": round(t + word, 3), "speaker": voice})
            t += word + gap
    return words


def when(transcript, phrase, nth=0):
    toks = phrase.split()
    hits = [i for i in range(len(transcript.words)) if [w["word"] for w in transcript.words[i:i + len(toks)]] == toks]
    i = hits[nth]
    return transcript.words[i]["start"], transcript.words[i + len(toks) - 1]["end"]


class TwoCameraCase(BrandCase):
    """A brand whose presenter stays out of clips, a transcribed recording, and (as empty stand-ins,
    unless a subclass makes real ones) two camera files with thoroughly awkward names."""

    def setUp(self):
        super().setUp()
        answers = copy.deepcopy(BAKERY)
        answers["identities"][0]["credential_line"] = "Ava Lindqvist, Head Baker"
        answers["video"] = {"host_names": [JONAH]}
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery", answers)
        self.folder = common.recording_dir(self.brand, RECORDING)
        os.makedirs(self.folder)
        self.words = lay_out(CONVERSATION)
        self.place_cameras()
        transcribe.write_transcript(self.brand, RECORDING, words=self.words,
                                    source={"media": common.locate(self.brand, os.path.join(self.folder, CAMERA_A)),
                                            "duration": self.words[-1]["end"] + 2.0})
        self.t = Transcript.load(self.brand, RECORDING)

    def place_cameras(self):
        for name in (CAMERA_A, CAMERA_B):
            Path(self.folder, name).write_bytes(b"")

    def save_setup(self, b_offset=-B_STARTED_LATE, **extra):
        setup = {"cameras": {"A": {"file": common.locate(self.brand, os.path.join(self.folder, CAMERA_A)), "offset": 0.0},
                             "B": {"file": common.locate(self.brand, os.path.join(self.folder, CAMERA_B)),
                                   "offset": b_offset}}, "sound": {"from": "A"}}
        return multicam.save_setup(self.brand, RECORDING, dict(setup, **extra))

    def write_cut_list(self, hook="Watch the dough, not the clock.", offset="0", cut_from=CAMERA_A):
        s, _ = when(self.t, "Most dense loaves")
        _, e = when(self.t, "not the clock.")
        h = when(self.t, hook)
        cl = cutlist.CutList(title=RECORDING)
        cl.reference = {"recording": "A chat about dense loaves", "brand": "maple-and-main", "cut_from": cut_from,
                        "timestamps_from": "Transcriptions/transcript.json", "offset": offset}
        cl.bodies = [cutlist.Body(key="A", title="Café loaves, Ava's way", start=s, end=e,
                                  starts_with="Most dense loaves are simply", ends_with="Watch the dough, not the clock.",
                                  on_screen_text="Your loaf is not broken", lower_third="Ava Lindqvist, Head Baker",
                                  gate="SHIP", hooks=[cutlist.Hook(1, h[0], h[1], hook),
                                                      cutlist.Hook(2, s, s + 2.0, "Most dense loaves are simply underproofed.")])]
        path = common.output_dir(self.brand, RECORDING, common.CUT_LIST_FILE)
        common.write_text_atomic(path, cutlist.write(cl))
        return path


class TestWhoIsOnWhichCameraIsNeverGuessed(TwoCameraCase):
    def test_every_voice_must_be_placed_by_a_person(self):
        with self.assertRaises(VideoError) as cm:
            multicam.who_is_where(self.brand, self.t, {JONAH: "B"})
        self.assertIn("'Ava Lindqvist'", str(cm.exception))
        self.assertIn("never worked out from a name", str(cm.exception))
        self.assertEqual(multicam.who_is_where(self.brand, self.t, {AVA: "A", JONAH: "B"}),
                         {AVA: "A", JONAH: "B", "": None})

    def test_file_names_that_look_like_an_answer_are_not_used_as_one(self):
        for name in ("Ava Lindqvist.mp4", "Jonah Pell.mp4"):
            Path(self.folder, name).write_bytes(b"")
        setup = self.save_setup()
        setup["cameras"]["A"]["file"] = common.locate(self.brand, os.path.join(self.folder, "Ava Lindqvist.mp4"))
        setup["cameras"]["B"]["file"] = common.locate(self.brand, os.path.join(self.folder, "Jonah Pell.mp4"))
        multicam.save_setup(self.brand, RECORDING, setup)
        with self.assertRaises(VideoError) as cm:
            multicam.prepare(self.brand, RECORDING)
        self.assertIn("Nobody has said who is on which camera", str(cm.exception))

    def test_a_person_the_brand_keeps_off_camera_needs_no_placing_and_is_never_cut_to(self):
        placed = multicam.who_is_where(self.brand, self.t, {AVA: "A"})
        self.assertEqual((placed[AVA], placed[JONAH]), ("A", None))
        shots = multicam.build_decisions(self.t.turns(), placed, layout="solo", start=0.0, end=self.t.duration)
        self.assertEqual(shows(shots), ["A"])

    def test_typos_wrong_cameras_and_contradictions_are_said_plainly(self):
        for speakers, off, expect in (({"Ava Lindqvst": "A"}, (), "no voice called 'Ava Lindqvst'"),
                                      ({AVA: "C"}, (), "cameras are called A and B"),
                                      ({AVA: "A", JONAH: "B"}, (JONAH,), "also off camera"),
                                      ({AVA: "A"}, ("Somebody Else",), "no voice called 'Somebody Else'")):
            with self.assertRaises(VideoError) as cm:
                multicam.who_is_where(self.brand, self.t, speakers, off)
            self.assertIn(expect, str(cm.exception))
        self.assertEqual(multicam.who_is_where(self.brand, self.t, {"  ava   LINDQVIST ": "a", JONAH: "b"})[AVA], "A")

    def test_a_third_voice_is_placed_or_declared_off_camera_never_assumed(self):
        words = self.words + [{"word": "Rolling.", "start": 0.05, "end": 0.4, "speaker": PRODUCER}]
        t = Transcript({"words": words})
        with self.assertRaises(VideoError) as cm:
            multicam.who_is_where(self.brand, t, {AVA: "A", JONAH: "B"})
        self.assertIn(PRODUCER, str(cm.exception))
        self.assertIsNone(multicam.who_is_where(self.brand, t, {AVA: "A", JONAH: "B"}, [PRODUCER])[PRODUCER])

    def test_a_transcript_with_no_voice_labels_cannot_drive_the_picture(self):
        bare = Transcript({"words": [dict(w, speaker="") for w in self.words]})
        with self.assertRaises(VideoError) as cm:
            multicam.who_is_where(self.brand, bare, {AVA: "A"})
        self.assertIn("does not say who is speaking", str(cm.exception))

    def test_no_brand_is_an_error_and_so_is_the_wrong_brand(self):
        for nothing in (None, "", "no-such-brand"):
            with self.assertRaises(BrandError):
                multicam.load_setup(nothing, RECORDING)
        self.save_setup()
        other = brands.create("stride-physio", "Stride Physio")
        with self.assertRaises(VideoError) as cm:
            multicam.load_setup(other, RECORDING)
        self.assertIn("have not been lined up yet", str(cm.exception))
        shutil.copytree(multicam.multicam_dir(self.brand, RECORDING), multicam.multicam_dir(other, RECORDING))
        with self.assertRaises(VideoError) as cm:
            multicam.load_setup(other, RECORDING)
        self.assertIn("different brand", str(cm.exception))


class TestTheSpeakerGateStillApplies(TwoCameraCase):
    def policy(self, placed, **kw):
        return multicam_clips.CameraPolicy(self.brand, self.t.speakers, placed, **kw)

    def test_the_brands_off_camera_person_stays_out_of_clips_even_with_a_camera_on_them(self):
        p = self.policy({AVA: "A", JONAH: "B", "": None})
        self.assertEqual((p.on_camera(), p.off_camera()), ([AVA], [JONAH]))
        self.write_cut_list(hook="Watch the dough, not the clock.")
        cl = cutlist.load(common.output_dir(self.brand, RECORDING, common.CUT_LIST_FILE))
        self.assertTrue(cutlist.is_valid(cutlist.validate(cl, self.t, self.brand, RECORDING, policy=p, check_files=False)))

    def test_a_hook_spoken_by_the_excluded_voice_is_refused(self):
        self.write_cut_list(hook="And is cheap flour the real problem")
        cl = cutlist.load(common.output_dir(self.brand, RECORDING, common.CUT_LIST_FILE))
        findings = cutlist.validate(cl, self.t, self.brand, RECORDING, policy=self.policy({AVA: "A", JONAH: "B", "": None}),
                                    check_files=False)
        self.assertTrue(any(f.severity == "ERROR" and f.rule == "speaker" and JONAH in f.detail for f in findings))

    def test_a_voice_on_neither_camera_is_refused_whatever_the_brand_allows(self):
        unhosted = brands.update("maple-and-main", {"video": {"host_names": []}})
        p = multicam_clips.CameraPolicy(unhosted, self.t.speakers, {AVA: "A", JONAH: None, "": None})
        self.assertEqual(p.on_camera(), [AVA])
        self.write_cut_list(hook="And is cheap flour the real problem")
        cl = cutlist.load(common.output_dir(self.brand, RECORDING, common.CUT_LIST_FILE))
        findings = cutlist.validate(cl, self.t, unhosted, RECORDING, policy=p, check_files=False)
        self.assertTrue(any(f.severity == "ERROR" and f.rule == "speaker" for f in findings))

    def test_saying_nobody_is_off_camera_is_only_accepted_when_everyone_has_a_camera(self):
        both = self.policy({AVA: "A", JONAH: "B", "": None}, everyone_on_camera=True)
        self.assertEqual(both.on_camera(), [AVA, JONAH])
        with self.assertRaises(VideoError) as cm:
            self.policy({AVA: "A", JONAH: None, "": None}, everyone_on_camera=True)
        self.assertIn("on neither camera", str(cm.exception))

    def test_a_cut_list_offset_with_the_wrong_sign_is_caught_against_what_was_measured(self):
        files = {"A": {"path": os.path.join(self.folder, CAMERA_A), "offset": 0.0},
                 "B": {"path": os.path.join(self.folder, CAMERA_B), "offset": -B_STARTED_LATE},
                 "sound": {"path": os.path.join(self.folder, CAMERA_A), "offset": 0.0}}
        for offset, cut_from, bad in (("0", CAMERA_A, False), ("-1.25", CAMERA_B, False), ("+1.25", CAMERA_B, True),
                                      ("-3", CAMERA_B, True)):
            cl = cutlist.load(self.write_cut_list(offset=offset, cut_from=cut_from))
            found = multicam_clips.reference_findings(cl, self.brand, RECORDING, files)
            self.assertEqual(bool(found) and found[0].severity == "ERROR", bad, (offset, cut_from))
            if bad:
                self.assertIn("wrong size or the wrong sign", found[0].detail)


class TestHostileFolderNames(TwoCameraCase):
    def test_the_setup_survives_a_folder_with_a_space_an_apostrophe_and_an_accent(self):
        self.save_setup(speakers={AVA: "A", JONAH: "B"})
        setup = multicam.load_setup("maple-and-main", RECORDING)
        self.assertEqual(setup["cameras"]["B"]["file"], "Inputs/Recordings/%s/%s" % (RECORDING, CAMERA_B))
        files = multicam.files_of(self.brand, RECORDING, setup)
        self.assertTrue(os.path.samefile(files["B"]["path"], os.path.join(self.folder, CAMERA_B)))
        self.assertEqual(files["sound"], {"path": files["A"]["path"], "offset": 0.0})
        self.assertEqual(os.listdir(multicam.multicam_dir(self.brand, RECORDING)), ["setup.json"])     # no leftovers

    def test_names_that_would_leave_the_brand_folder_are_refused(self):
        for bad in ("../elsewhere", "a/b", ".hidden", "", "c:evil"):
            with self.assertRaises(VideoError):
                multicam.load_setup(self.brand, bad)
        self.save_setup()
        setup = multicam.load_setup(self.brand, RECORDING)
        setup["cameras"]["B"]["file"] = "../../../somewhere/else.mp4"
        with self.assertRaises(VideoError) as cm:
            multicam.files_of(self.brand, RECORDING, setup)
        self.assertIn("cannot be found", str(cm.exception))

    def test_no_folder_name_is_ever_written_inside_the_filter_description(self):
        files = {"A": {"path": os.path.join(self.folder, CAMERA_A), "offset": 0.0, "nudge": 0.0},
                 "B": {"path": os.path.join(self.folder, CAMERA_B), "offset": -1.25, "nudge": 0.0},
                 "sound": {"path": os.path.join(self.folder, CAMERA_A), "offset": 0.0}}
        shots = [{"start": 2.0, "end": 6.0, "show": "A", "why": "speaking"},
                 {"start": 6.0, "end": 9.0, "show": "B", "why": "speaking"},
                 {"start": 9.0, "end": 12.0, "show": "both", "why": "closing"}]
        out = os.path.join(multicam.multicam_dir(self.brand, RECORDING), "two-camera-edit.mp4")
        seen = {}

        def pretend(cmd, total, say, cwd, what):
            seen.update(cmd=cmd, cwd=cwd, script=Path(cwd, "cuts.txt").read_text(encoding="utf-8"))
            Path(cmd[-1]).write_bytes(b"finished")

        with mock.patch.object(multicam, "programs", return_value=("ffmpeg", "ffprobe")), \
                mock.patch.object(multicam, "_watch", side_effect=pretend):
            multicam.render_shots(files, shots, out, (320, 180), "25", 25.0)
        cmd = seen["cmd"]
        graph = cmd[cmd.index("-filter_complex") + 1]
        for fragment in ("'", "é", os.sep, "caf", "Ava"):
            self.assertNotIn(fragment, graph)
        self.assertIn("sendcmd=f=cuts.txt", graph)
        self.assertIn("[pboth]sendcmd", graph)                       # carried by the last picture to arrive, see render_shots
        self.assertEqual(seen["script"].splitlines(), ["4.0000 streamselect map 1;", "7.0000 streamselect map 2;"])
        self.assertNotEqual(os.path.abspath(seen["cwd"]), os.path.abspath(os.path.dirname(out)))
        for path in (files["A"]["path"], files["B"]["path"]):
            self.assertIn(os.path.abspath(path), cmd)                 # handed over whole, as its own argument
        # camera B is read from ITS OWN clock: transcript 2.0 is 0.75 in a camera that started 1.25 late
        self.assertEqual([cmd[i + 1] for i, x in enumerate(cmd) if x == "-ss"], ["2.0000", "0.7500", "2.0000"])
        self.assertEqual(Path(out).read_bytes(), b"finished")
        self.assertEqual(sorted(os.listdir(os.path.dirname(out))), ["two-camera-edit.mp4"])     # no '.working' left behind

    def test_the_verbs_answer_in_sentences_and_need_a_brand(self):
        with mock.patch("builtins.print") as said:
            self.assertEqual(multicam_cli.cli_multicam(["plan", "--brand", "maple-and-main", "--recording", RECORDING]), 1)
            self.assertIn("have not been lined up yet", said.call_args[0][0])
            self.assertEqual(multicam_cli.cli_multicam(["dance"]), 1)
            self.assertEqual(multicam_cli.cli_multicam(["plan", "--brand", "nobody-home", "--recording", RECORDING]), 1)
            self.assertEqual(multicam_cli.cli_sync(["--brand", "maple-and-main", "--recording", RECORDING,
                                                    "--camera-a", CAMERA_A]), 1)
            self.assertIn("give both", said.call_args[0][0])
        for verb in (multicam_cli.cli_sync, lambda a: multicam_cli.cli_multicam(["render"] + a)):
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                verb(["--recording", RECORDING])


# ============================================================================= with the real video programs
def _video_tier():
    try:
        import static_ffmpeg                                               # noqa: F401
        from smf import media
        media.ensure_ffmpeg()
        return True
    except Exception:
        return False


HAS_VIDEO = HAS_NUMPY and _video_tier()
NEEDS_VIDEO = "the video tools are not installed (python factory.py setup --tier video)"


def colour_at(ff, video, seconds):
    """'A' (red), 'B' (blue) or 'both' (red beside blue): what is on screen at one moment."""
    raw = subprocess.run([ff, "-v", "error", "-ss", "%.3f" % seconds, "-i", video, "-frames:v", "1", "-vf", "scale=8:4",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    frame = np.frombuffer(raw[:96], np.uint8).reshape(4, 8, 3).astype(int)
    sides = ["A" if frame[2:, cols].mean(axis=(0, 1))[0] > 150 else "B" for cols in (slice(0, 2), slice(6, 8))]
    return sides[0] if sides[0] == sides[1] else "both"


@unittest.skipUnless(HAS_VIDEO, NEEDS_VIDEO)
class TestWithTwoRealCameras(TwoCameraCase):
    """Camera A is red, camera B is blue, and B was switched on 1.25 seconds after A. Each grows a
    stripe (yellow on A, green on B) twenty seconds into its OWN recording, so a picture taken from
    the wrong moment of a camera is visible too. The media is made once and copied per test."""

    @classmethod
    def setUpClass(cls):
        from smf import media
        cls.ff, cls.fp = media.ensure_ffmpeg()
        cls.made = tempfile.TemporaryDirectory(prefix="two cameras ' é ")
        words = lay_out(CONVERSATION)
        cls.total = words[-1]["end"] + 2.0
        sound = sound_of(words, 0.0, cls.total, seed=3)
        wav = os.path.join(cls.made.name, "room.wav")
        with wave.open(wav, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes((np.clip(sound, -1, 1) * 32767).astype("<i2").tobytes())
        lead_in = os.path.join(cls.made.name, "lead-in.wav")
        with wave.open(lead_in, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            early = np.concatenate((0.2 * np.random.default_rng(8).standard_normal(int(0.8 * RATE)), sound))
            f.writeframes((np.clip(early, -1, 1) * 32767).astype("<i2").tobytes())
        for name, colour, stripe, skip, track in ((CAMERA_A, "red", "yellow", 0.0, wav),
                                                  (CAMERA_B, "blue", "green", B_STARTED_LATE, wav),
                                                  ("early bird.mp4", "gray", "white", 0.0, lead_in)):
            made = subprocess.run([cls.ff, "-y", "-v", "error", "-f", "lavfi",
                                   "-i", "color=c=%s:s=320x180:r=25:d=%.2f" % (colour, cls.total - skip),
                                   "-ss", "%.3f" % skip, "-i", track,
                                   "-vf", "drawbox=enable='gte(t,20)':color=%s:t=fill:w=iw:h=40" % stripe,
                                   "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                                   "-shortest", os.path.join(cls.made.name, name)], capture_output=True, text=True)
            assert made.returncode == 0, made.stderr[-400:]
        # Camera A again, but its sound track only BEGINS 0.44 seconds into the file (its content is
        # still in the right place: the start is simply missing). Real camera files do this.
        tail = os.path.join(cls.made.name, "tail.m4a")
        subprocess.run([cls.ff, "-y", "-v", "error", "-ss", "0.5", "-i", wav, "-c:a", "aac", tail], check=True)
        subprocess.run([cls.ff, "-y", "-v", "error", "-i", os.path.join(cls.made.name, CAMERA_A), "-itsoffset", "0.5",
                        "-i", tail, "-map", "0:v", "-map", "1:a", "-c", "copy",
                        os.path.join(cls.made.name, "sound starts late.mp4")], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.made.cleanup()

    def place_cameras(self):
        for name in (CAMERA_A, CAMERA_B, "early bird.mp4", "sound starts late.mp4"):
            shutil.copy(os.path.join(self.made.name, name), os.path.join(self.folder, name))

    def lined_up(self, **who):
        multicam.line_up(self.brand, RECORDING, CAMERA_A, CAMERA_B)
        return dict({"speakers": {AVA: "A", JONAH: "B"}, "rules": {"open_wide": 3.0, "close_wide": 3.0}}, **who)

    def test_the_cameras_are_lined_up_from_their_files_with_the_right_sign(self):
        setup = multicam.line_up(self.brand, RECORDING, CAMERA_A, CAMERA_B)
        a, b = setup["cameras"]["A"], setup["cameras"]["B"]
        self.assertEqual((a["offset"], a["how"]["method"]), (0.0, "same-file"))
        self.assertAlmostEqual(b["offset"], -B_STARTED_LATE, delta=0.03)          # switched on later -> negative
        self.assertTrue(b["how"]["checked"])
        self.assertLessEqual(abs(b["how"]["residual"]), 0.03)
        self.assertTrue(setup["transcript"]["how"]["checked"])                    # the words do land on camera A's speech
        # a camera that was switched on EARLIER comes out positive
        early = sync.measure_offset(os.path.join(self.folder, CAMERA_A), os.path.join(self.folder, "early bird.mp4"))
        self.assertAlmostEqual(early.seconds, 0.8, delta=0.03)
        saved = json.loads(Path(multicam.multicam_dir(self.brand, RECORDING, "setup.json")).read_text(encoding="utf-8"))
        self.assertEqual(saved["cameras"]["B"]["file"], "Inputs/Recordings/%s/%s" % (RECORDING, CAMERA_B))

    def test_a_typed_offset_is_checked_by_listening_and_the_wrong_sign_is_refused(self):
        with self.assertRaises(sync.SyncRefused) as cm:
            multicam.line_up(self.brand, RECORDING, CAMERA_A, CAMERA_B, given={"B": +B_STARTED_LATE})
        self.assertIn("back to front", str(cm.exception))
        self.assertFalse(os.path.exists(multicam.multicam_dir(self.brand, RECORDING, "setup.json")))   # nothing saved
        setup = multicam.line_up(self.brand, RECORDING, CAMERA_A, CAMERA_B, given={"B": -B_STARTED_LATE})
        self.assertEqual((setup["cameras"]["B"]["how"]["method"], setup["cameras"]["B"]["how"]["checked"]), ("given", True))
        with self.assertRaises(VideoError):
            multicam.line_up(self.brand, RECORDING, CAMERA_A, CAMERA_A)

    def test_the_cut_lists_offset_for_one_camera_is_measured_and_written_with_its_sign(self):
        path = self.write_cut_list(offset="+1.25", cut_from=CAMERA_B)             # somebody typed the sign backwards
        out = sync.offset_for_cut_list(self.brand, RECORDING)
        self.assertAlmostEqual(out["offset"].seconds, -B_STARTED_LATE, delta=0.03)
        self.assertEqual((out["was"], out["saved"]), (1.25, False))
        sync.offset_for_cut_list(self.brand, RECORDING, save=True)
        self.assertAlmostEqual(cutlist.load(path).offset, -B_STARTED_LATE, delta=0.03)
        self.assertEqual(cutlist.load(path).bodies[0].hooks[0].text, "Watch the dough, not the clock.")   # nothing else moved
        with self.assertRaises(VideoError) as cm:                                 # an offset belongs to ONE file
            sync.offset_for_cut_list(self.brand, RECORDING, video="early bird.mp4", save=True)
        self.assertIn("belongs to one particular file", str(cm.exception))

    def test_with_the_transcribed_file_gone_the_words_alone_still_find_the_offset_in_a_real_file(self):
        words = spoken_words(until=100.0)
        take = os.path.join(self.folder, "long take.wav")
        with wave.open(take, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes((np.clip(sound_of(words, -2.4, 108.0), -1, 1) * 32767).astype("<i2").tobytes())
        found = sync.measure_transcript_offset(take, Transcript({"words": words}))
        self.assertEqual((found.method, found.checked), ("words", True))
        self.assertAlmostEqual(found.seconds, -2.4, delta=0.1)
        # half a minute of talk is too little for this fallback: it refuses, and says what would work
        transcribe.write_transcript(self.brand, RECORDING, words=self.words, source={"media": "gone.mp4"})
        with self.assertRaises(sync.SyncRefused) as cm:
            sync.offset_for_cut_list(self.brand, RECORDING, video=CAMERA_B)
        self.assertIn("Put it back", str(cm.exception))

    def test_a_dry_run_shows_the_shots_and_writes_nothing(self):
        who = self.lined_up()
        before = sorted(os.listdir(multicam.multicam_dir(self.brand, RECORDING)))
        decisions = multicam.render(self.brand, RECORDING, dry_run=True, **who)
        self.assertTrue(decisions["dry_run"])
        self.assertIn("both", shows(decisions["shots"]))
        self.assertEqual(sorted(os.listdir(multicam.multicam_dir(self.brand, RECORDING))), before)
        self.assertNotIn("speakers", multicam.load_setup(self.brand, RECORDING))                  # not even the setup
        self.assertTrue(any("camera A" in line for line in multicam.describe(decisions)))

    def test_the_switch_renders_and_the_expected_colour_is_on_screen_at_every_decision_point(self):
        who = self.lined_up()
        decisions = multicam.render(self.brand, RECORDING, encoder="software", **who)
        folder = multicam.multicam_dir(self.brand, RECORDING)
        video = os.path.join(folder, "two-camera-edit.mp4")
        self.assertEqual(sorted(os.listdir(folder)), ["setup.json", "two-camera-edit.edit-decisions.json",
                                                      "two-camera-edit.mp4"])
        self.assertEqual((decisions["encoder"], decisions["status"]), ("libx264", "ok"))
        self.assertTrue(common.decodes_cleanly(video))
        self.assertAlmostEqual(common.probe_duration(video), decisions["duration"], delta=0.2)
        shots = decisions["shots"]
        # opening on both; the presenter is still asking his question when it ends, so B; then the answers
        self.assertEqual(shows(shots), ["both", "B", "A", "B", "A", "both"])
        self.assertEqual([s["why"] for s in (shots[0], shots[-1])], ["opening", "closing"])
        self.assertAlmostEqual(shots[0]["start"], B_STARTED_LATE, delta=0.05)     # nothing before camera B was rolling
        self.assertTrue(any("first moment both cameras" in n for n in decisions["notes"]))
        for shot in shots:                                                        # three frames either side of every cut
            for moment in (shot["out_start"] + 0.12, (shot["out_start"] + shot["out_end"]) / 2, shot["out_end"] - 0.12):
                self.assertEqual(colour_at(self.ff, video, moment), shot["show"], (shot, moment))
        saved = json.loads(Path(multicam.decisions_path(video)).read_text(encoding="utf-8"))
        self.assertEqual(saved["shots"], shots)
        self.assertEqual(saved["speakers"], {AVA: "A", JONAH: "B"})
        self.assertEqual(saved["cameras"]["B"]["file"], "Inputs/Recordings/%s/%s" % (RECORDING, CAMERA_B))

        # the checker agrees, and it looked at something
        check = multicam_verify.verify_edit(self.brand, RECORDING)
        self.assertTrue(check["pass"], check["problems"])
        self.assertGreaterEqual(check["pictures"]["checked"], 2 * (len(shots) - 1))
        self.assertGreaterEqual(check["sound"]["checked"], 2)
        self.assertTrue(all(abs(p["out_by"]) <= 0.06 for p in check["sound"]["places"] if p["clear"]))

        # it reads the FILE, not the plan: tell it the people were the other way round and it fails
        lie = copy.deepcopy(saved)
        for s in lie["shots"]:
            s["show"] = {"A": "B", "B": "A"}.get(s["show"], s["show"])
        common.write_json_atomic(multicam.decisions_path(video), lie)
        wrong = multicam_verify.verify_edit(self.brand, RECORDING)
        self.assertFalse(wrong["pass"])
        self.assertTrue(any("should show camera B but shows camera A" in p for p in wrong["problems"]))
        # ... and a picture shifted against its sound is caught too (camera offsets off by half a second)
        shifted = copy.deepcopy(saved)
        shifted["sound"]["offset"] += 0.5
        common.write_json_atomic(multicam.decisions_path(video), shifted)
        late = multicam_verify.verify_edit(self.brand, RECORDING)
        self.assertTrue(any("away from where it belongs" in p for p in late["problems"]), late["problems"])

    def test_every_cut_lands_on_the_planned_frame_not_a_few_frames_early(self):
        # The timed commands must ride on the LAST picture to reach the selector. Carried by an earlier
        # one, a command flips the selector while frames for earlier moments are still queued, and the
        # cut lands early by however much was queued. So every frame is looked at, not a sample.
        files = {"A": {"path": os.path.join(self.folder, CAMERA_A), "offset": 0.0, "nudge": 0.0},
                 "B": {"path": os.path.join(self.folder, CAMERA_B), "offset": -B_STARTED_LATE, "nudge": 0.0},
                 "sound": {"path": os.path.join(self.folder, CAMERA_A), "offset": 0.0}}
        order = ["A", "B", "both", "B", "A", "both", "A", "B"]
        shots = multicam.timeline([{"start": 2.0 + 1.48 * i, "end": 2.0 + 1.48 * (i + 1), "show": show, "why": "speaking"}
                                   for i, show in enumerate(order)])
        out = os.path.join(self.tmp.name, "every frame.mp4")
        multicam.render_shots(files, shots, out, (320, 180), "25", 25.0)
        raw = subprocess.run([self.ff, "-v", "error", "-i", out, "-vf", "scale=8:4", "-f", "rawvideo", "-pix_fmt", "rgb24",
                              "-"], capture_output=True).stdout
        frames = np.frombuffer(raw, np.uint8).reshape(-1, 4, 8, 3).astype(int)
        seen = []
        for f in frames:
            sides = ["A" if f[2:, cols].mean(axis=(0, 1))[0] > 150 else "B" for cols in (slice(0, 2), slice(6, 8))]
            seen.append(sides[0] if sides[0] == sides[1] else "both")
        switched_at = [i / 25.0 for i in range(1, len(seen)) if seen[i] != seen[i - 1]]
        self.assertEqual(len(switched_at), len(order) - 1)
        for actual, shot in zip(switched_at, shots[1:]):
            self.assertAlmostEqual(actual, shot["out_start"], delta=1.5 / 25.0, msg=shot)      # within a frame and a half

    def test_a_sound_track_that_begins_late_in_its_own_file_is_not_slid_early(self):
        # Time zero is where the file was asked to start, not where its first sample happens to be.
        late = os.path.join(self.folder, "sound starts late.mp4")
        self.assertGreater(float(subprocess.run([self.fp, "-v", "error", "-select_streams", "a", "-show_entries",
                                                 "stream=start_time", "-of", "csv=p=0", late],
                                                capture_output=True, text=True).stdout.strip()), 0.3)
        self.assertAlmostEqual(sync.measure_offset(os.path.join(self.folder, CAMERA_A), late).seconds, 0.0, delta=0.02)
        on_time = {"path": os.path.join(self.folder, "early bird.mp4"), "offset": 0.0, "nudge": 0.0}   # any picture will do
        files = {"A": {"path": late, "offset": 0.0, "nudge": 0.0}, "B": on_time, "sound": {"path": late, "offset": 0.0}}
        with self.assertRaises(VideoError) as cm:                                 # never quietly started from the wrong place
            multicam.render_shots(dict(files, B=dict(on_time, path=os.path.join(self.folder, CAMERA_B), offset=-B_STARTED_LATE)),
                                  multicam.timeline([{"start": 0.0, "end": 5.0, "show": "A", "why": "speaking"}]),
                                  os.path.join(self.tmp.name, "too early.mp4"), (320, 180), "25", 25.0)
        self.assertIn("before camera B was recording", str(cm.exception))
        shots = multicam.timeline([{"start": 0.0, "end": 5.0, "show": "A", "why": "speaking"},
                                   {"start": 5.0, "end": 10.0, "show": "both", "why": "closing"}])
        out = os.path.join(self.tmp.name, "from the very start.mp4")
        multicam.render_shots(files, shots, out, (320, 180), "25", 25.0)
        # judged against the ORIGINAL, complete sound, not against the file with the gap
        places = multicam_verify.check_sound(out, shots, {"path": os.path.join(self.folder, CAMERA_A), "offset": 0.0})
        self.assertGreaterEqual(len([p for p in places if p["clear"]]), 2)
        for p in places:
            if p["clear"]:
                self.assertLessEqual(abs(p["out_by"]), 0.03, places)

    def test_checking_nothing_is_never_a_pass(self):
        with self.assertRaises(VideoError) as cm:
            multicam_verify.verify_edit(self.brand, RECORDING)
        self.assertIn("not a pass", str(cm.exception))
        with self.assertRaises(VideoError) as cm:
            multicam_verify.verify_clips(self.brand, RECORDING)
        self.assertIn("not a pass", str(cm.exception))
        # two cameras that show the same thing cannot be told apart, and that is a failure, not a pass
        same = {k: np.full((36, 64, 3), 90.0) for k in ("A", "B", "both")}
        self.assertEqual(multicam_verify.judge_frame(np.full((36, 64, 3), 90.0), same, "A")["verdict"], "cannot-tell")

    def test_clips_come_from_the_same_cut_list_and_read_like_rough_cuts(self):
        who = self.lined_up()
        self.write_cut_list()
        planned = multicam_clips.make_clips(self.brand, RECORDING, listen="transcript", dry_run=True, **who)
        self.assertEqual({c["status"] for c in planned["clips"]}, {"planned"})
        self.assertFalse(os.path.exists(common.output_dir(self.brand, RECORDING, "rough")))

        report = multicam_clips.make_clips(self.brand, RECORDING, listen="transcript", **who)
        out = common.output_dir(self.brand, RECORDING, "rough")
        saved = json.loads(Path(out, "rough-cut-report.json").read_text(encoding="utf-8"))
        self.assertEqual([c["status"] for c in report["clips"]], ["ok", "ok"])
        self.assertEqual((saved["kind"], saved["made_with"], saved["offset"], saved["layout"]),
                         ("rough", "two cameras", 0.0, "solo"))
        self.assertEqual((saved["on_camera"], saved["kept_out"]), ([AVA], [JONAH]))
        # every key a one-camera rough-cut report has, the two-camera one has too, clip by clip
        one_camera = {"schema", "kind", "brand", "recording", "source", "source_duration", "shape", "cut_list", "offset",
                      "speaker_check", "on_camera", "kept_out", "listened_with", "dry_run", "alarm", "clips", "by_ear"}
        self.assertLessEqual(one_camera, set(saved))
        per_clip = {"id", "file", "body", "hook", "title", "hook_text", "on_screen_text", "lower_third", "gate",
                    "disclaimer", "sign_off_by", "signed_off", "segments", "pieces", "expected_duration",
                    "actual_duration", "status"}
        per_segment = {"role", "requested", "cut", "duration", "walls", "snap", "starts_with", "ends_with", "part"}
        for clip in saved["clips"]:
            self.assertLessEqual(per_clip, set(clip))
            self.assertTrue(all(per_segment <= set(seg) for seg in clip["segments"]))
            self.assertTrue(common.decodes_cleanly(os.path.join(out, clip["file"])))
            self.assertAlmostEqual(clip["actual_duration"], clip["expected_duration"], delta=0.35)
        lifted, in_place = saved["clips"]
        self.assertEqual(lifted["file"], "A1-cafe-loaves-ava-s-way.mp4")
        self.assertEqual([s["role"] for s in lifted["segments"]], ["hook", "body", "body"])
        self.assertEqual([s["part"] for s in lifted["segments"][1:]], [s["part"] for s in in_place["segments"]])

        # the presenter said "Right." inside the body: the body became two pieces and neither touches him
        right0, right1 = when(self.t, "Right.")
        for a, b in in_place["pieces"]:
            self.assertFalse(a < right1 and b > right0, (a, b))
        # the step that listens to finished clips reads this report with no special case
        policy = multicam_clips.gate.SpeakerPolicy.for_transcript(self.brand, self.t)
        self.assertEqual(validate_cuts.off_camera_inside(in_place, self.t.turns(), policy, 0.0), 0.0)

        def hears(path):
            clip = next(c for c in saved["clips"] if os.path.join(out, c["file"]) == path)
            return [(w["start"], w["end"], w["word"]) for w in common.words_in_clip(clip["pieces"], self.t.words)]
        self.assertEqual(validate_cuts.validate(self.brand, RECORDING, hear=hears)["failed"], [])
        # the body is Ava's, so every frame of a solo clip is camera A, and the checker agrees
        for moment in (0.2, lifted["actual_duration"] / 2, lifted["actual_duration"] - 0.2):
            self.assertEqual(colour_at(self.ff, os.path.join(out, lifted["file"]), moment), "A")
        self.assertEqual(multicam_verify.verify_clips(self.brand, RECORDING)["failed"], [])
        # a step that re-cuts from ONE source file stops instead of quietly making one-camera clips
        with self.assertRaises(VideoError):
            fine_cut.fine_cut(self.brand, RECORDING)
        self.assertFalse(any(os.path.islink(os.path.join(out, n)) for n in os.listdir(out)))

    def test_with_everyone_cleared_a_clip_cuts_between_the_cameras_and_drops_the_one_name_caption(self):
        who = self.lined_up()
        s, _ = when(self.t, "And is cheap flour")
        _, e = when(self.t, "leave it out.")
        cl = cutlist.CutList(title=RECORDING)
        cl.reference = {"recording": "A chat about dense loaves", "brand": "maple-and-main", "cut_from": CAMERA_A,
                        "timestamps_from": "Transcriptions/transcript.json", "offset": "0"}
        cl.bodies = [cutlist.Body(key="B", title="Is it the flour", start=s, end=e, starts_with="And is cheap flour the real",
                                  ends_with="most people leave it out.", on_screen_text="It is not the flour",
                                  lower_third="Ava Lindqvist, Head Baker", gate="SHIP",
                                  hooks=[cutlist.Hook(1, s, s + 2.0, "And is cheap flour the real problem")])]
        common.write_text_atomic(common.output_dir(self.brand, RECORDING, common.CUT_LIST_FILE), cutlist.write(cl))
        with self.assertRaises(rough_cut.CutListProblems) as cm:                  # the presenter opens it: refused
            multicam_clips.make_clips(self.brand, RECORDING, listen="transcript", **who)
        self.assertTrue(any(f.rule == "speaker" for f in cm.exception.findings))
        report = multicam_clips.make_clips(self.brand, RECORDING, listen="transcript", everyone_on_camera=True, **who)
        clip = report["clips"][0]
        self.assertEqual((clip["status"], clip["shows"]), ("ok", ["A", "B"]))
        self.assertEqual((clip["lower_third"], clip["lower_third_left_off"]), ("", "Ava Lindqvist, Head Baker"))
        video = os.path.join(common.output_dir(self.brand, RECORDING, "rough"), clip["file"])
        self.assertEqual([colour_at(self.ff, video, 0.3), colour_at(self.ff, video, clip["actual_duration"] - 0.3)], ["B", "A"])
        self.assertEqual(multicam_verify.verify_clips(self.brand, RECORDING)["failed"], [])

    def test_the_verbs_run_the_whole_job_from_a_hostile_folder(self):
        base = ["--brand", "maple-and-main", "--recording", RECORDING]
        with mock.patch("builtins.print") as said:
            self.assertEqual(multicam_cli.cli_sync(base + ["--camera-a", CAMERA_A, "--camera-b", CAMERA_B]), 0)
            heard = " ".join(str(c[0][0]) for c in said.call_args_list if c[0])
            self.assertIn("Camera A was already recording 1.25", heard)
            self.assertEqual(multicam_cli.cli_multicam(["plan"] + base + ["--speaker", AVA + "=A"]), 0)   # host: automatic
            self.assertEqual(multicam_cli.cli_multicam(["plan"] + base + ["--speaker", AVA + "=A", "--speaker", JONAH + "=B",
                                                                         "--rule", "open_wide=3", "--rule", "close_wide=3"]), 0)
            self.assertEqual(multicam_cli.cli_multicam(["render"] + base + ["--dry-run"]), 0)
            self.assertEqual(multicam_cli.cli_multicam(["verify"] + base), 1)                             # nothing to check yet
            self.assertEqual(multicam_cli.cli_multicam(["render"] + base + ["--encoder", "software"]), 0)
            self.assertEqual(multicam_cli.cli_multicam(["verify"] + base), 0)
            self.write_cut_list()
            self.assertEqual(multicam_cli.cli_multicam(["clips"] + base + ["--listen", "transcript"]), 0)
            self.assertEqual(multicam_cli.cli_multicam(["verify"] + base + ["--clips"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
