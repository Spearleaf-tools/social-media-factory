"""Montage tests: a film made from many sources under a written narration.

    python -m unittest discover -s tests -t . -v

Every test here is a mistake that really happened while cutting a narrated film by hand, and that
a person only caught by watching:

  * a shot that ran past the end of its source came out short, and every cut after it slid out of
    step with the voice;
  * a shot that straddled a scene change inside its source showed as a one-frame blip;
  * a shot of a slow push across a still image read as a frozen frame;
  * adding one line re-voiced every line after it, which moved the words the cuts were timed to;
  * a fix to how one word is said should re-voice only the lines holding that word;
  * a number in the narration had no source;
  * a music bed made to order was paid for twice because the film's estimated length moved.
  * a motion title carried words nobody wrote, came out the wrong size, placed itself as a shot,
    or was re-rendered (and renumbered) on every run; a film render swept the title clips away.

Nothing here uses the network or a key. Tests that need the video programs are skipped, with the
reason, when the video tier is not installed.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                   # noqa: E402
from smf.video import montage, montage_cli               # noqa: E402
from smf.video.common import VideoError                  # noqa: E402
from tests.test_brands import BrandCase                  # noqa: E402

FILM = "Spring bake ' é"
# a valid 1x1 white PNG, for a brand's logo file in tests that never open it
ONE_PIXEL_PNG = bytes.fromhex("89504e470d0a1a0a0000000d494844520000000100000001080200000090775"
                              "3de0000000c49444154789c63f8ffff3f0005fe02fe0d2ff7250000000049454e44ae426082")


def plan_with(sources, lines, **extra):
    plan = {"title": "Spring bake", "size": [320, 180], "fps": 25, "gap": 0.3, "quality": "draft",
            "voice": {"recording": "voiceover.wav"}, "sources": sources, "lines": lines}
    plan.update(extra)
    return plan


class MontageCase(BrandCase):
    """A bakery brand, a film folder, and footage files whose lengths the tests decide."""

    def setUp(self):
        super().setUp()
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery")
        self.home = montage.film_dir(self.brand, FILM)
        os.makedirs(self.home)
        self.lengths = {"voiceover.wav": 60.0}
        for name in ("voiceover.wav",):
            Path(self.home, name).write_bytes(b"")
        self.cuts, self.still = {}, set()
        patches = [mock.patch.object(montage, "probe_duration", side_effect=self._length),
                   mock.patch.object(montage, "scene_cuts", side_effect=self._cuts),
                   mock.patch.object(montage, "is_still", side_effect=self._still)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def footage(self, name, seconds, cuts=(), still=False, inside=True):
        folder = self.home if inside else self.tmp.name
        path = os.path.join(folder, name)
        Path(path).write_bytes(b"")
        self.lengths[name] = seconds
        self.cuts[name] = list(cuts)
        if still:
            self.still.add(name)
        return name if inside else path

    def _length(self, path):
        return self.lengths[os.path.basename(path)]

    def _cuts(self, path, start, seconds):
        return [c for c in self.cuts.get(os.path.basename(path), []) if start < c < start + seconds]

    def _still(self, path, start, seconds):
        return os.path.basename(path) in self.still

    def write(self, plan):
        Path(self.home, montage.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")


class TestStartingAFilm(MontageCase):
    def test_new_writes_a_starter_plan_and_never_overwrites_one(self):
        other = "Autumn loaf"
        path = montage.create(self.brand, other, title="Autumn loaf")
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(plan["title"], "Autumn loaf")
        self.assertTrue(plan["lines"] and plan["sources"])
        with self.assertRaises(VideoError) as e:
            montage.create(self.brand, other)
        self.assertIn("already", str(e.exception))

    def test_a_film_name_cannot_climb_out_of_the_brand_folder(self):
        with self.assertRaises(VideoError):
            montage.film_dir(self.brand, "../elsewhere")


class TestCheckingTheShots(MontageCase):
    def lines(self, *shots, say="Fresh bread every morning.", **line):
        entry = {"say": say, "from": 0.0, "to": 2.0, "shots": list(shots)}
        entry.update(line)
        return [entry]

    def test_a_clean_plan_has_no_errors(self):
        src = self.footage("oven.mp4", 30.0)
        self.write(plan_with({"oven": {"file": src, "credit": "Our own footage"}},
                             self.lines({"source": "oven", "at": 4.0})))
        found = montage.check(self.brand, FILM)
        self.assertEqual(found["errors"], [])

    def test_a_shot_that_runs_past_the_end_of_its_source_is_an_error(self):
        src = self.footage("oven.mp4", 5.0)
        self.write(plan_with({"oven": {"file": src}}, self.lines({"source": "oven", "at": 4.0})))
        found = montage.check(self.brand, FILM)
        self.assertEqual(len(found["errors"]), 1)
        self.assertIn("oven", found["errors"][0])
        self.assertIn("ends at 00:05.0", found["errors"][0])

    def test_a_shot_that_crosses_a_scene_change_in_its_source_is_an_error_naming_the_change(self):
        src = self.footage("oven.mp4", 30.0, cuts=[5.2])
        self.write(plan_with({"oven": {"file": src}}, self.lines({"source": "oven", "at": 4.0})))
        found = montage.check(self.brand, FILM)
        self.assertEqual(len(found["errors"]), 1)
        self.assertIn("scene change at 00:05.2", found["errors"][0])

    def test_a_still_looking_shot_is_a_warning_the_person_decides_on(self):
        src = self.footage("poster.mp4", 30.0, still=True)
        self.write(plan_with({"poster": {"file": src}}, self.lines({"source": "poster", "at": 4.0})))
        found = montage.check(self.brand, FILM)
        self.assertEqual(found["errors"], [])
        self.assertTrue(any("still" in w for w in found["warnings"]))

    def test_pinned_shots_that_leave_no_room_for_the_rest_are_errors(self):
        src = self.footage("oven.mp4", 30.0)
        crowded = self.lines({"source": "oven", "at": 1.0, "seconds": 2.1}, {"source": "oven", "at": 10.0})
        self.write(plan_with({"oven": {"file": src}}, crowded))
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("leaves" in e for e in found["errors"]), found["errors"])

    def test_a_line_whose_shots_are_all_pinned_is_an_error_because_the_picture_would_drift(self):
        src = self.footage("oven.mp4", 30.0)
        self.write(plan_with({"oven": {"file": src}}, self.lines({"source": "oven", "at": 1.0, "seconds": 1.0})))
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("every shot" in e for e in found["errors"]), found["errors"])

    def test_a_slowed_shot_uses_less_of_its_source_and_is_checked_on_what_it_really_uses(self):
        src = self.footage("oven.mp4", 30.0, cuts=[5.5])
        # 2.3 seconds on screen at half speed takes 1.15 seconds of source: 4.0 to 5.15, clear of 5.5
        self.write(plan_with({"oven": {"file": src}}, self.lines({"source": "oven", "at": 4.0, "speed": 0.5})))
        self.assertEqual(montage.check(self.brand, FILM)["errors"], [])
        # at full speed the same shot runs 4.0 to 6.3, across the change
        self.write(plan_with({"oven": {"file": src}}, self.lines({"source": "oven", "at": 4.0})))
        self.assertTrue(any("scene change" in e for e in montage.check(self.brand, FILM)["errors"]))
        self.write(plan_with({"oven": {"file": src}}, self.lines({"source": "oven", "at": 4.0, "speed": 0})))
        self.assertTrue(any("speed" in e for e in montage.check(self.brand, FILM)["errors"]))

    def test_messages_read_as_sentences(self):
        src = self.footage("oven.mp4", 5.0)
        self.write(plan_with({"oven": {"file": src}}, self.lines({"source": "oven", "at": 4.0})))
        self.assertTrue(montage.check(self.brand, FILM)["errors"][0].startswith("Shot 1 (line 1) takes"))

    def test_a_still_image_is_never_past_its_end_or_across_a_cut_and_is_not_flagged_as_frozen(self):
        Path(self.home, "drawing.png").write_bytes(b"")
        self.write(plan_with({"drawing": {"file": "drawing.png", "move": "in"}},
                             self.lines({"source": "drawing", "at": 0})))
        def length(path):
            if path.endswith(".png"):
                raise AssertionError("a still has no length to measure")
            return self._length(path)
        with mock.patch.object(montage, "probe_duration", side_effect=length):
            found = montage.check(self.brand, FILM)
        self.assertEqual(found["errors"], [])
        self.assertFalse(any("still" in w for w in found["warnings"]))

    def test_an_unknown_camera_move_is_an_error(self):
        Path(self.home, "drawing.png").write_bytes(b"")
        self.write(plan_with({"drawing": {"file": "drawing.png"}},
                             self.lines({"source": "drawing", "at": 0, "move": "spin"})))
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("move" in e for e in found["errors"]), found["errors"])

    def test_an_unknown_source_is_an_error(self):
        self.write(plan_with({}, self.lines({"source": "oven", "at": 1.0})))
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("'oven'" in e for e in found["errors"]), found["errors"])

    def test_a_number_in_the_narration_without_a_source_is_flagged_unverified(self):
        src = self.footage("oven.mp4", 30.0)
        self.write(plan_with({"oven": {"file": src}},
                             self.lines({"source": "oven", "at": 1.0}, say="We bake 400 loaves a day.")))
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("unverified" in w and "400" in w for w in found["warnings"]), found["warnings"])
        self.write(plan_with({"oven": {"file": src}},
                             self.lines({"source": "oven", "at": 1.0}, say="We bake 400 loaves a day.",
                                        fact_source="Studio/facts.json: daily-bake")))
        self.assertFalse(any("unverified" in w for w in montage.check(self.brand, FILM)["warnings"]))

    def test_footage_from_outside_the_brand_folder_without_a_credit_is_flagged(self):
        src = self.footage("archive.mp4", 30.0, inside=False)
        self.write(plan_with({"archive": {"file": src}}, self.lines({"source": "archive", "at": 1.0})))
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("credit" in w for w in found["warnings"]), found["warnings"])


class TestTheTimeline(MontageCase):
    def test_every_shot_is_a_whole_number_of_frames_and_the_picture_ends_with_the_voice(self):
        src = self.footage("oven.mp4", 100.0)
        lines = [{"say": "One.", "from": 0.0, "to": 1.37, "shots": [{"source": "oven", "at": 1.0},
                                                                   {"source": "oven", "at": 20.0}]},
                 {"say": "Two.", "from": 2.0, "to": 3.91, "shots": [{"source": "oven", "at": 40.0, "seconds": 0.9},
                                                                   {"source": "oven", "at": 60.0}]},
                 {"say": "Three.", "from": 5.0, "to": 6.03, "hold": 0.5, "shots": [{"source": "oven", "at": 80.0}]}]
        self.write(plan_with({"oven": {"file": src}}, lines, opening=[{"source": "oven", "at": 90.0, "seconds": 1.3}]))
        found = montage.check(self.brand, FILM)
        self.assertEqual(found["errors"], [])
        tl = found["timeline"]
        fps = 25
        shots = [s for s in tl["shots"]]
        self.assertTrue(all(isinstance(s["frames"], int) and s["frames"] > 0 for s in shots))
        self.assertEqual(sum(s["frames"] for s in shots), tl["frames"])
        # each line's picture starts on the frame its voice starts
        for line in tl["lines"]:
            first = [s for s in shots if s["line"] == line["number"]][0]
            self.assertEqual(first["start_frame"], round(line["start"] * fps))
        # the voice spans: gap after every line, plus the hold on the last
        spans = [round(x["span"], 2) for x in tl["lines"]]
        self.assertEqual(spans, [round(1.37 + 0.3, 2), round(1.91 + 0.3, 2), round(1.03 + 0.3 + 0.5, 2)])
        self.assertEqual(tl["frames"], round((1.3 + sum(x["span"] for x in tl["lines"])) * fps))


HAS_REQUESTS = importlib.util.find_spec("requests") is not None
NEEDS_REQUESTS = "requests is not installed (python factory.py setup)"


@unittest.skipUnless(HAS_REQUESTS, NEEDS_REQUESTS)
class TestTheVoice(MontageCase):
    VOICE = {"elevenlabs": {"voice_id": "abc123", "model": "eleven_turbo_v2"}}

    def eleven_plan(self, lines, **extra):
        src = self.footage("oven.mp4", 100.0)
        shots = [{"source": "oven", "at": 1.0}]
        return plan_with({"oven": {"file": src}}, [{"say": s, "shots": shots} for s in lines],
                         voice=self.VOICE, **extra)

    def test_adding_a_line_does_not_re_voice_the_others(self):
        before = self.eleven_plan(["First line.", "Second line."])
        after = self.eleven_plan(["First line.", "A new line.", "Second line."])
        k1 = [montage.voice_key(before, i) for i in range(2)]
        k2 = [montage.voice_key(after, i) for i in range(3)]
        self.assertEqual(k1[0], k2[0])
        self.assertEqual(k1[1], k2[2])

    def test_a_pronunciation_fix_re_voices_only_the_lines_holding_that_word(self):
        before = self.eleven_plan(["Our brioche is braided by hand.", "Bread is warm."])
        after = self.eleven_plan(["Our brioche is braided by hand.", "Bread is warm."], say_as={"brioche": "bree-osh"})
        self.assertNotEqual(montage.voice_key(before, 0), montage.voice_key(after, 0))
        self.assertEqual(montage.voice_key(before, 1), montage.voice_key(after, 1))
        self.assertEqual(montage.spoken(after, 0), "Our bree-osh is braided by hand.")

    def test_without_confirm_nothing_is_sent_and_it_says_how_much_text_would_be(self):
        self.write(self.eleven_plan(["First line.", "Second line."]))
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), \
                mock.patch("requests.post") as post:
            out = montage.make_voice(self.brand, FILM, confirm=False)
        post.assert_not_called()
        self.assertEqual(out["to_make"], [1, 2])
        self.assertEqual(out["characters"], len("First line.") + len("Second line."))
        self.assertFalse(out["sent"])

    def test_with_confirm_only_the_missing_takes_are_made(self):
        self.write(self.eleven_plan(["First line.", "Second line."]))
        answer = mock.Mock(status_code=200, content=b"ID3 fake mp3")
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), \
                mock.patch("requests.post", return_value=answer) as post:
            montage.make_voice(self.brand, FILM, confirm=True)
            self.assertEqual(post.call_count, 2)
            sent = post.call_args[1]["json"]
            self.assertEqual(sent["model_id"], "eleven_turbo_v2")
            post.reset_mock()
            self.write(self.eleven_plan(["First line.", "A new line.", "Second line."]))
            out = montage.make_voice(self.brand, FILM, confirm=True)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(out["to_make"], [2])

    def test_finding_word_times_says_the_cost_and_sends_nothing_without_confirm(self):
        plan = self.eleven_plan(["First line."])
        self.write(plan)
        take = montage._take(self.brand, FILM, plan, 0)
        os.makedirs(os.path.dirname(take))
        Path(take).write_bytes(b"ID3")
        self.lengths[os.path.basename(take)] = 2.0
        from smf.video import transcribe
        with mock.patch.object(transcribe, "send_to_elevenlabs") as send:
            out = montage.line_words(self.brand, FILM, 1, confirm=False)
            send.assert_not_called()
            self.assertIsNone(out["words"])
            self.assertIn("cent", out["cost_words"])
            send.return_value = {"words": [{"type": "word", "text": "First", "start": 0.1, "end": 0.4}]}
            with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}):
                out = montage.line_words(self.brand, FILM, 1, confirm=True)
            self.assertEqual([w["word"] for w in out["words"]], ["First"])
            send.reset_mock()
            again = montage.line_words(self.brand, FILM, 1, confirm=True)       # saved: never paid for twice
            send.assert_not_called()
            self.assertEqual(again["words"], out["words"])

    def test_a_refused_key_is_a_sentence_and_the_key_never_appears(self):
        self.write(self.eleven_plan(["First line."]))
        answer = mock.Mock(status_code=401, text='{"detail": "invalid key sk_test_value"}')
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), \
                mock.patch("requests.post", return_value=answer):
            with self.assertRaises(VideoError) as e:
                montage.make_voice(self.brand, FILM, confirm=True)
        self.assertIn("refused", str(e.exception))
        self.assertNotIn("sk_test_value", str(e.exception))


@unittest.skipUnless(HAS_REQUESTS, NEEDS_REQUESTS)
class TestVoiceStyles(MontageCase):
    """A personal voice: the brand's own ElevenLabs voice, on a model that takes direction, with
    named styles that are audio tags. Every mistake that would cost a take is refused first."""

    V4 = {"elevenlabs": {"voice_id": "ava-clone", "model": "eleven_v4", "settings": {"stability": "natural"},
                         "styles": {"confident": "[confident]", "warm": "[warm, unhurried]"}, "style": "confident"}}

    def plan(self, lines, voice=None, **extra):
        src = self.footage("oven.mp4", 100.0)
        return plan_with({"oven": {"file": src}}, [dict({"say": s, "shots": [{"source": "oven", "at": 1.0}]}, **more)
                                                    for s, more in lines], voice=voice or self.V4, **extra)

    def test_a_style_puts_its_tag_before_the_words_and_changes_only_that_take(self):
        before = self.plan([("First line.", {}), ("Second line.", {})])
        after = self.plan([("First line.", {}), ("Second line.", {"style": "warm"})])
        self.assertEqual(montage.spoken(before, 0), "[confident] First line.")
        self.assertEqual(montage.spoken(after, 1), "[warm, unhurried] Second line.")
        self.assertEqual(montage.voice_key(before, 0), montage.voice_key(after, 0))
        self.assertNotEqual(montage.voice_key(before, 1), montage.voice_key(after, 1))
        bare = self.plan([("First line.", {"style": ""})])
        self.assertEqual(montage.spoken(bare, 0), "First line.")

    def test_a_line_may_give_the_tag_itself_but_not_a_style_nobody_defined(self):
        plan = self.plan([("First line.", {"style": "[whispers]"}), ("Second line.", {"style": "gravelly"})])
        self.assertEqual(montage.spoken(plan, 0), "[whispers] First line.")
        with self.assertRaises(VideoError) as e:
            montage.style_tag(plan, 1)
        self.assertIn("gravelly", str(e.exception))
        self.write(plan)
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("gravelly" in err for err in found["errors"]))
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), mock.patch("requests.post") as post:
            with self.assertRaises(VideoError):
                montage.make_voice(self.brand, FILM, confirm=True)
            post.assert_not_called()

    def test_a_tag_on_a_model_that_would_read_it_aloud_is_refused_before_anything_is_sent(self):
        old = {"elevenlabs": {"voice_id": "abc", "model": "eleven_turbo_v2", "styles": {"confident": "[confident]"},
                              "style": "confident"}}
        self.write(self.plan([("First line.", {})], voice=old))
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("read it aloud" in err for err in found["errors"]))
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), mock.patch("requests.post") as post:
            with self.assertRaises(VideoError) as e:
                montage.make_voice(self.brand, FILM, confirm=True)
            post.assert_not_called()
        self.assertIn("nothing was sent", str(e.exception))

    def test_a_phoneme_tag_on_a_model_that_drops_the_word_is_refused(self):
        self.write(self.plan([("Our brioche is braided by hand.", {})],
                             say_as={"brioche": "<phoneme alphabet=\"ipa\" ph=\"briˈɔʃ\">brioche</phoneme>"}))
        found = montage.check(self.brand, FILM)
        self.assertTrue(any("silence where the word should be" in err for err in found["errors"]))
        self.assertTrue(any("IPA" in err for err in found["errors"]))

    def test_a_stability_word_becomes_the_number_and_only_what_the_model_hears_is_sent(self):
        self.write(self.plan([("First line.", {})]))
        answer = mock.Mock(status_code=200, content=b"ID3 fake mp3")
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), \
                mock.patch("requests.post", return_value=answer) as post:
            montage.make_voice(self.brand, FILM, confirm=True)
        sent = post.call_args[1]["json"]
        self.assertEqual(sent["model_id"], "eleven_v4")
        self.assertEqual(sent["text"], "[confident] First line.")
        self.assertEqual(sent["voice_settings"], {"stability": 0.5})

    def test_an_unknown_model_is_a_warning_and_is_sent_as_written(self):
        self.write(self.plan([("First line.", {})], voice={"elevenlabs": {"voice_id": "abc", "model": "eleven_v9"}}))
        found = montage.check(self.brand, FILM)
        self.assertFalse(found["errors"])
        self.assertTrue(any("eleven_v9" in w and "not one this copy knows" in w for w in found["warnings"]))

    def test_a_new_or_drafted_plan_speaks_with_the_brands_own_voice(self):
        voiced = brands.create("voiced", "Voiced", answers={
            "business": {"what_we_do": "We bake bread."},
            "video": {"voice": {"elevenlabs": self.V4["elevenlabs"], "say_as": {"brioche": "/briˈɔʃ/"}}}})
        path = montage.create(voiced, "Fresh")
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(plan["voice"]["elevenlabs"]["voice_id"], "ava-clone")
        self.assertEqual(plan["say_as"], {"brioche": "/briˈɔʃ/"})
        out = montage.draft(voiced, "Story", from_brand=True)
        self.assertTrue(out["own_voice"])
        self.assertEqual(out["model"], "eleven_v4")
        drafted = json.loads(Path(montage.film_dir(voiced, "Story"), montage.PLAN_FILE).read_text(encoding="utf-8"))
        self.assertEqual(drafted["voice"]["elevenlabs"]["styles"]["warm"], "[warm, unhurried]")
        plain = montage.create(self.brand, "Plain")
        self.assertEqual(json.loads(Path(plain).read_text(encoding="utf-8"))["voice"]["elevenlabs"]["voice_id"],
                         "PUT-A-VOICE-ID-HERE")


class TestSilentPassages(MontageCase):
    VOICE = {"elevenlabs": {"voice_id": "abc123", "model": "eleven_turbo_v2"}}

    def plan(self):
        src = self.footage("oven.mp4", 100.0)
        return plan_with({"oven": {"file": src}},
                         [{"say": "First line.", "shots": [{"source": "oven", "at": 1.0}]},
                          {"pause": 6.0, "shots": [{"source": "oven", "at": 20.0}, {"source": "oven", "at": 40.0}]},
                          {"say": "Second line.", "shots": [{"source": "oven", "at": 60.0}]}], voice=self.VOICE)

    def test_a_pause_is_never_voiced_and_costs_nothing(self):
        self.write(self.plan())
        out = montage.make_voice(self.brand, FILM, confirm=False)      # without confirm nothing is ever sent
        self.assertFalse(out["sent"])
        self.assertEqual(out["to_make"], [1, 3])
        self.assertEqual(out["characters"], len("First line.") + len("Second line."))

    def test_a_pause_lasts_exactly_its_seconds_with_no_gap_added(self):
        plan = self.plan()
        tl, errors = montage.timeline(plan, [2.0, 6.0, 2.0])
        self.assertEqual(errors, [])
        self.assertAlmostEqual(tl["lines"][1]["span"], 6.0)
        pause_frames = sum(s["frames"] for s in tl["shots"] if s["line"] == 2)
        # frames are counted on the film's own clock, so a pause may round by one frame at its edges
        self.assertLessEqual(abs(pause_frames - 6 * 25), 1)


class TestTheFootageFolder(MontageCase):
    """Every brand's footage goes in ONE folder, and the film is cut from what is there."""

    def drop(self, rel, seconds=10.0):
        path = os.path.join(montage.footage_dir(self.brand), *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_bytes(b"")
        self.lengths[os.path.basename(rel)] = seconds
        return path

    def test_each_file_is_listed_with_its_length_and_a_note_still_to_write(self):
        self.drop("oven.mp4", 12.0)
        self.drop("logo.png")
        found = montage.scan_footage(self.brand)
        files = montage.load_footage(self.brand)["files"]
        self.assertEqual(sorted(found["added"]), ["logo", "oven"])
        self.assertEqual(files["oven"]["file"], "Inputs/Footage/oven.mp4")
        self.assertEqual((files["oven"]["kind"], files["oven"]["seconds"]), ("video", 12.0))
        self.assertEqual((files["logo"]["kind"], files["logo"]["seconds"]), ("image", None))
        self.assertEqual(sorted(found["unnamed"]), ["logo", "oven"])
        self.assertTrue(os.path.isfile(found["path"]))

    def test_what_a_person_wrote_about_a_file_survives_a_rescan(self):
        self.drop("oven.mp4", 12.0)
        montage.scan_footage(self.brand)
        path = montage.footage_file(self.brand)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["files"]["oven"].update({"shows": "bread coming out of the oven", "credit": "Our own footage",
                                      "crop": "1920:1000:0:40"})
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        self.lengths["oven.mp4"] = 13.0                        # re-exported since: the length is measured again
        found = montage.scan_footage(self.brand)
        entry = montage.load_footage(self.brand)["files"]["oven"]
        self.assertEqual(entry["shows"], "bread coming out of the oven")
        self.assertEqual(entry["crop"], "1920:1000:0:40")
        self.assertEqual(entry["seconds"], 13.0)
        self.assertEqual(found["unnamed"], [])
        self.assertEqual(found["added"], [])

    def test_a_file_that_has_gone_is_marked_missing_never_dropped_and_comes_back(self):
        path = self.drop("oven.mp4", 12.0)
        montage.scan_footage(self.brand)
        os.remove(path)
        found = montage.scan_footage(self.brand)
        self.assertEqual(found["missing"], ["oven"])
        self.assertTrue(montage.load_footage(self.brand)["files"]["oven"]["missing"])
        self.assertNotIn("oven", montage.footage_sources(montage.load_footage(self.brand)))
        Path(path).write_bytes(b"")
        found = montage.scan_footage(self.brand)
        self.assertEqual(found["returned"], ["oven"])
        self.assertNotIn("missing", montage.load_footage(self.brand)["files"]["oven"])

    def test_two_files_with_the_same_name_in_different_folders_get_their_own_ids(self):
        self.drop("oven.mp4", 12.0)
        self.drop("day two/oven.mp4", 8.0)
        montage.scan_footage(self.brand)
        files = montage.load_footage(self.brand)["files"]
        self.assertEqual(sorted(files), ["oven", "oven-2"])
        self.assertEqual({files["oven"]["file"], files["oven-2"]["file"]},
                         {"Inputs/Footage/oven.mp4", "Inputs/Footage/day two/oven.mp4"})

    def test_a_file_that_is_not_footage_is_left_alone(self):
        self.drop("oven.mp4", 12.0)
        Path(montage.footage_dir(self.brand), "notes.txt").write_text("where it came from", encoding="utf-8")
        found = montage.scan_footage(self.brand)
        self.assertEqual(found["added"], ["oven"])
        self.assertEqual(found["files"], 1)

    def test_a_damaged_footage_list_is_reported_not_overwritten(self):
        os.makedirs(montage.footage_dir(self.brand), exist_ok=True)
        Path(montage.footage_file(self.brand)).write_text("{not json", encoding="utf-8")
        with self.assertRaises(VideoError) as e:
            montage.scan_footage(self.brand)
        self.assertIn("damaged", str(e.exception))
        self.assertEqual(Path(montage.footage_file(self.brand)).read_text(encoding="utf-8"), "{not json")


class DraftCase(MontageCase):
    """A brand that answered onboarding in its own words, and a footage folder with notes."""

    ANSWERS = {
        "business": {"what_we_do": "We bake naturally leavened bread and teach people to do the same."},
        "audience": {"problems": ["Their home loaves come out dense and they do not know why"]},
        "person": {"why_started": "I wanted bread I could not buy anywhere near me."},
        "positioning": {
            "story": {"catalyst": {"id": "catalyst", "value": "The supermarket loaf stopped being bread."},
                      "core_truth": {"id": "core-truth", "value": "Good bread is time, not equipment."},
                      "proof": [{"id": "sp-1", "value": "Every loaf we sell proofed overnight."}]},
            "differentiation": [{"id": "diff-1", "others": "Bread is made fast with additives.",
                                 "us": "Ours ferments for at least 18 hours."}]},
        "myths": [{"id": "myth-1", "value": "You need a special oven."}],
        "mistakes": [{"id": "mistake-1", "value": "Baking before the dough has finished proofing."}],
        "steps_to_result": [{"id": "step-1", "value": "Press the dough and watch the dent."}],
        "offers": [{"id": "sourdough-class", "rung": "main", "name": "The Saturday sourdough class",
                    "what": "Four hours, eight people, two loaves to take home", "price": "95 dollars",
                    "link": "https://example.test/class"}],
    }

    def setUp(self):
        super().setUp()
        self.bakery = brands.create("bakery-words", "Maple & Main Bakery", answers=json.loads(json.dumps(self.ANSWERS)))

    def drop(self, brand, rel, seconds=10.0, shows=""):
        path = os.path.join(montage.footage_dir(brand), *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_bytes(b"")
        self.lengths[os.path.basename(rel)] = seconds
        if shows:
            montage.scan_footage(brand)
            listed = montage.footage_file(brand)
            data = json.loads(Path(listed).read_text(encoding="utf-8"))
            fid = next(k for k, v in data["files"].items() if v["file"].endswith(rel))
            data["files"][fid]["shows"] = shows
            Path(listed).write_text(json.dumps(data), encoding="utf-8")
        return path

    def plan_of(self, brand, film):
        return json.loads(Path(montage.film_dir(brand, film), montage.PLAN_FILE).read_text(encoding="utf-8"))


class TestDraftingFromTheBrand(DraftCase):
    def test_every_line_is_the_brands_own_words_with_where_it_came_from_and_no_shots(self):
        out = montage.draft(self.bakery, "Our story", from_brand=True)
        plan = self.plan_of(self.bakery, "Our story")
        said = [ln["say"] for ln in plan["lines"]]
        own = json.dumps(self.ANSWERS)
        for line in plan["lines"]:
            self.assertEqual(line["shots"], [], line["say"])
            self.assertTrue(line["fact_source"], line["say"])
            self.assertTrue(line["wants"], line["say"])
            for sentence in line["say"].rstrip(".").split(". "):
                self.assertIn(sentence, own, "not the brand's own words: %s" % sentence)
        self.assertEqual([ln["part"] for ln in plan["lines"]][:4], ["why", "catalyst", "problem", "core_truth"])
        self.assertEqual(plan["lines"][-1]["part"], "offer")
        self.assertEqual(plan["lines"][-1]["fact_source"], "offer:sourdough-class")
        self.assertEqual(plan["lines"][-1]["link"], "https://example.test/class")
        self.assertIn("Ours ferments for at least 18 hours.", said)
        self.assertEqual(out["lines"], len(plan["lines"]))
        self.assertEqual(out["missing"], [])
        self.assertIn("brand", plan["drafted_from"])

    def test_what_the_brand_has_not_said_is_named_never_filled_in(self):
        thin = brands.create("thin-words", "Thin", answers={"business": {"what_we_do": "We bake bread."}})
        out = montage.draft(thin, "Our story", from_brand=True)
        plan = self.plan_of(thin, "Our story")
        self.assertEqual([ln["say"] for ln in plan["lines"]], ["We bake bread."])
        joined = " ".join(out["missing"])
        for want in ("why they started", "what changed", "truth", "shows the story", "offer"):
            self.assertIn(want, joined)

    def test_a_brand_with_nothing_to_say_is_refused(self):
        with self.assertRaises(VideoError) as e:
            montage.draft(self.brand, "Our story", from_brand=True)
        self.assertIn("not said enough", str(e.exception))

    def test_a_draft_never_overwrites_a_plan_with_lines_but_may_replace_an_untouched_starter(self):
        montage.create(self.bakery, "Our story")
        montage.draft(self.bakery, "Our story", from_brand=True)        # the starter's one placeholder line
        with self.assertRaises(VideoError) as e:
            montage.draft(self.bakery, "Our story", from_brand=True)
        self.assertIn("already has a plan", str(e.exception))
        self.assertEqual(self.plan_of(self.bakery, "Our story")["lines"][0]["part"], "why")

    def test_the_words_come_from_one_place(self):
        with self.assertRaises(VideoError):
            montage.draft(self.bakery, "Our story")
        with self.assertRaises(VideoError):
            montage.draft(self.bakery, "Our story", from_brand=True, script="anything.md")

    def test_sources_come_from_the_footage_folder_and_a_suggestion_is_never_a_shot(self):
        self.drop(self.bakery, "oven.mp4", 30.0, shows="bread coming out of the oven, the dough tub")
        self.drop(self.bakery, "street.mp4", 30.0, shows="the shop front from the street")
        out = montage.draft(self.bakery, "Our story", from_brand=True)
        plan = self.plan_of(self.bakery, "Our story")
        self.assertEqual(plan["sources"]["oven"]["file"], "Inputs/Footage/oven.mp4")
        self.assertEqual(out["sources"], 2)
        dent = next(ln for ln in plan["lines"] if ln["part"] == "step")
        self.assertEqual(dent["suggested"], ["oven"])                   # "dough" is in its note
        self.assertEqual(dent["shots"], [])
        found = montage.check(self.bakery, "Our story")
        self.assertTrue(all("has no shots" in e for e in found["errors"]))
        self.assertEqual(len(found["errors"]), len(plan["lines"]))

    def test_without_footage_the_draft_says_so_and_keeps_the_placeholder_source(self):
        out = montage.draft(self.bakery, "Our story", from_brand=True)
        self.assertTrue(out["no_footage"])
        self.assertIn("example", self.plan_of(self.bakery, "Our story")["sources"])


SCRIPT = """# Why your loaf is dense

- Brand: bakery-words
- Batch: test
- Script: 01
- Speaker: person
- Job: trust
- Format: talking to camera
- Length: 45 seconds
- Hook pattern: the fault on the bench

## The one idea

Dense bread is under-proofed bread.

## Opening

Promise: why your loaf is dense
On screen: Dense loaf?
Show: Two loaves cut in half, side by side.
Say: Your loaf is dense because it never finished proofing.

## Line 1

Say: Our dough ferments for at least 18 hours.
Show: The dough tub with yesterday's time written on the lid.
Source: fact:ferment-18h

## Line 2

Say: TODO
Show: TODO

## Call to action

Kind: question
Say: What does your dough do when you press it?
Show: Ava presses the dough and looks up.
"""


class TestDraftingFromAScript(DraftCase):
    def script(self, text=SCRIPT, name="01-dense-loaf.md"):
        folder = self.bakery.path("Output", "batches", "test")
        os.makedirs(folder, exist_ok=True)
        Path(folder, name).write_text(text, encoding="utf-8")
        return "Output/batches/test/" + name

    def test_the_opening_the_lines_and_the_ending_become_lines_in_order_with_what_they_show(self):
        self.drop(self.bakery, "tub.mp4", 20.0, shows="the dough tub on the bench, lid on")
        out = montage.draft(self.bakery, "Dense loaf", script=self.script())
        plan = self.plan_of(self.bakery, "Dense loaf")
        self.assertEqual([ln["part"] for ln in plan["lines"]], ["opening", "line 1", "call to action"])
        self.assertEqual(plan["lines"][0]["say"], "Your loaf is dense because it never finished proofing.")
        self.assertEqual(plan["lines"][0]["on_screen"], "Dense loaf?")
        self.assertEqual(plan["lines"][0]["wants"], "Two loaves cut in half, side by side.")
        self.assertEqual(plan["lines"][1]["fact_source"], "fact:ferment-18h")
        self.assertEqual(plan["lines"][1]["suggested"], ["tub"])
        self.assertEqual(plan["lines"][2]["wants"], "Ava presses the dough and looks up.")
        self.assertTrue(all(ln["shots"] == [] for ln in plan["lines"]))
        self.assertIn("01-dense-loaf.md", plan["drafted_from"])
        self.assertEqual(out["lines"], 3)

    def test_a_script_nobody_filled_in_has_nothing_to_draft_from(self):
        from smf.scripts import brief
        starter = brief.starter("Dense loaf", "bakery-words", "test", "02", "person", "trust")
        with self.assertRaises(VideoError) as e:
            montage.draft(self.bakery, "Dense loaf", script=self.script(starter, "02-starter.md"))
        self.assertIn("no spoken lines", str(e.exception))
        self.assertFalse(os.path.exists(os.path.join(montage.film_dir(self.bakery, "Dense loaf"), montage.PLAN_FILE)))

    def test_a_script_that_is_not_there_is_an_error(self):
        with self.assertRaises(VideoError) as e:
            montage.draft(self.bakery, "Dense loaf", script="Output/batches/test/nowhere.md")
        self.assertIn("not there", str(e.exception))


@unittest.skipUnless(HAS_REQUESTS, NEEDS_REQUESTS)
class TestMusicToOrder(MontageCase):
    """A music bed composed by ElevenLabs Music from a few words. Nothing is sent without --confirm,
    the same bed is never paid for twice, and the plan ends up playing the saved file exactly as it
    would play a licensed track."""

    PROMPT = "warm, unhurried acoustic guitar for a small bakery at dawn"

    def plan(self, compose=None, to=2.0, **music):
        src = self.footage("oven.mp4", 100.0)
        bed = {"compose": dict({"prompt": self.PROMPT}, **(compose or {})), "level_db": -14}
        bed.update(music)
        # the voice is a recording, so the film's length is known: 2.0 of speech plus the 0.3 gap
        return plan_with({"oven": {"file": src}},
                         [{"say": "Fresh bread.", "from": 0.0, "to": to, "shots": [{"source": "oven", "at": 4.0}]}],
                         music=bed)

    def saved_plan(self):
        return json.loads(Path(self.home, montage.PLAN_FILE).read_text(encoding="utf-8"))

    def make(self, confirm, status=200, content=b"ID3 fake mp3", text=""):
        answer = mock.Mock(status_code=status, content=content, text=text)
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), \
                mock.patch("requests.post", return_value=answer) as post:
            out = montage.make_music(self.brand, FILM, confirm=confirm)
        return out, post

    def test_without_confirm_nothing_is_sent_and_it_says_what_would_be(self):
        self.write(self.plan())
        out, post = self.make(confirm=False)
        post.assert_not_called()
        self.assertFalse(out["sent"])
        self.assertEqual(out["model"], "music_v2_5")
        self.assertTrue(out["instrumental"])
        self.assertFalse(out["pinned"])
        self.assertEqual(out["seconds"], 7)                    # 2.3 seconds of film, plus a few, whole seconds
        self.assertEqual(out["prompt"], self.PROMPT)
        self.assertNotIn("file", self.saved_plan()["music"])
        self.assertFalse(os.path.exists(os.path.join(self.home, montage.MUSIC_DIR)))

    def test_with_confirm_the_bed_is_made_saved_and_the_plan_plays_it(self):
        self.write(self.plan())
        before = montage.check(self.brand, FILM)
        self.assertTrue(any("montage music" in e for e in before["errors"]), before["errors"])
        out, post = self.make(confirm=True)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args[0][0], "https://api.elevenlabs.io/v1/music")
        self.assertEqual(post.call_args[1]["headers"]["xi-api-key"], "sk_test_value")
        self.assertEqual(post.call_args[1]["json"], {"prompt": self.PROMPT, "music_length_ms": 7000,
                                                     "force_instrumental": True, "model_id": "music_v2_5"})
        self.assertTrue(out["sent"] and out["made"])
        self.assertRegex(out["file"], r"^music/[0-9a-f]{12}\.mp3$")
        saved = os.path.join(self.home, "music", os.path.basename(out["file"]))
        self.assertEqual(Path(saved).read_bytes(), b"ID3 fake mp3")
        music = self.saved_plan()["music"]
        self.assertEqual(music["file"], out["file"])           # render finds it as it finds any music file
        self.assertEqual(montage._find(self.brand, FILM, music["file"]), saved)
        self.assertEqual(music["made"]["seconds"], 7)
        self.assertEqual(music["level_db"], -14)
        self.assertFalse(any("music" in e for e in montage.check(self.brand, FILM)["errors"]))

    def test_the_same_words_length_and_model_are_never_made_twice(self):
        self.write(self.plan())
        out, post = self.make(confirm=True)
        again, post = self.make(confirm=True)
        post.assert_not_called()
        self.assertTrue(again["reused"])
        self.assertEqual(again["file"], out["file"])
        # the film's length moves as the voice is made: a bed that is still long enough is kept
        plan = self.saved_plan()
        plan["lines"][0]["to"] = 1.0
        self.write(plan)
        shorter, post = self.make(confirm=True)
        post.assert_not_called()
        self.assertTrue(shorter["reused"])
        # a film that has outgrown its bed, or new words, costs a new bed
        plan["lines"][0]["to"] = 8.0
        self.write(plan)
        longer, post = self.make(confirm=True)
        self.assertEqual(post.call_count, 1)
        self.assertNotEqual(longer["file"], out["file"])
        plan = self.saved_plan()
        plan["music"]["compose"]["prompt"] = "bright marimba"
        self.write(plan)
        _reworded, post = self.make(confirm=True)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args[1]["json"]["prompt"], "bright marimba")
        self.assertEqual(len(os.listdir(os.path.join(self.home, "music"))), 3)

    def test_the_length_may_be_pinned_and_one_the_model_cannot_make_is_refused(self):
        self.write(self.plan(compose={"seconds": 90}))
        out, post = self.make(confirm=True)
        self.assertTrue(out["pinned"])
        self.assertEqual(post.call_args[1]["json"]["music_length_ms"], 90000)
        self.write(self.plan(compose={"seconds": 700}))
        with mock.patch("requests.post") as post:
            with self.assertRaises(VideoError) as e:
                montage.make_music(self.brand, FILM, confirm=True)
            post.assert_not_called()
        self.assertIn("10 minutes", str(e.exception))

    def test_sung_words_must_be_the_brands_own_and_the_music_is_instrumental_by_default(self):
        self.write(self.plan(compose={"instrumental": False}))
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), mock.patch("requests.post") as post:
            with self.assertRaises(VideoError) as e:
                montage.make_music(self.brand, FILM, confirm=True)
            post.assert_not_called()
        self.assertIn("brand's own", str(e.exception))
        self.assertTrue(any("brand's own" in err for err in montage.check(self.brand, FILM)["errors"]))
        self.write(self.plan(compose={"instrumental": False, "words": "Fresh bread every morning.",
                                      "words_source": "Brand/voice-samples.md"}))
        out, post = self.make(confirm=True)
        sent = post.call_args[1]["json"]
        self.assertFalse(sent["force_instrumental"])
        self.assertIn("Fresh bread every morning.", sent["prompt"])
        self.assertFalse(out["instrumental"])

    def test_a_refused_key_is_a_sentence_and_the_key_never_appears(self):
        self.write(self.plan())
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), \
                mock.patch("requests.post", return_value=mock.Mock(status_code=401,
                                                                   text='{"detail": "invalid key sk_test_value"}')):
            with self.assertRaises(VideoError) as e:
                montage.make_music(self.brand, FILM, confirm=True)
        self.assertIn("refused", str(e.exception))
        self.assertNotIn("sk_test_value", str(e.exception))
        self.assertFalse(os.path.exists(os.path.join(self.home, montage.MUSIC_DIR)))
        self.assertNotIn("file", self.saved_plan()["music"])

    def test_music_that_is_not_made_to_order_has_nothing_to_make(self):
        self.write(self.plan())
        plan = self.saved_plan()
        plan["music"] = {"bed": "drone"}
        self.write(plan)
        with mock.patch("requests.post") as post:
            self.assertEqual(montage.make_music(self.brand, FILM, confirm=True)["mode"], "bed")
            plan["music"] = {}
            self.write(plan)
            with self.assertRaises(VideoError):
                montage.make_music(self.brand, FILM, confirm=True)
            post.assert_not_called()

    def test_with_no_prompt_the_words_are_the_brands_own_shown_first_and_never_sent_unread(self):
        voiced = brands.create("voiced", "Voiced", answers={
            "business": {"what_we_do": "We bake bread every morning.", "industry": "food and drink"},
            "voice": {"register": "Warm, plain and specific. Sounds like a baker talking across the counter."},
            "visual": {"likes": ["flour on wood", "morning light"], "dislikes": ["neon"]}})
        home = montage.film_dir(voiced, FILM)
        os.makedirs(home)
        Path(home, "voiceover.wav").write_bytes(b"")
        Path(home, "oven.mp4").write_bytes(b"")
        plan = self.plan()
        plan["music"]["compose"] = {}
        Path(home, montage.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
        answer = mock.Mock(status_code=200, content=b"ID3 fake mp3")
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), \
                mock.patch("requests.post", return_value=answer) as post:
            out = montage.make_music(voiced, FILM, confirm=True)     # even with --confirm: unread words are not sent
            post.assert_not_called()
            self.assertTrue(out["drafted"])
            self.assertFalse(out["sent"])
            saved = json.loads(Path(home, montage.PLAN_FILE).read_text(encoding="utf-8"))["music"]["compose"]
            self.assertEqual(saved["prompt"], out["prompt"])
            for theirs in ("food and drink", "Warm, plain and specific", "talking across the counter",
                           "flour on wood; morning light", "neon"):
                self.assertIn(theirs, saved["prompt"])
            self.assertEqual(saved["prompt_source"],
                             "brand-master.json: business.industry, voice.register, visual.likes, visual.dislikes")
            self.assertEqual(out["drafted_from"], ["business.industry", "voice.register", "visual.likes",
                                                   "visual.dislikes"])
            again = montage.make_music(voiced, FILM, confirm=True)   # the words have been shown: now it is made
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args[1]["json"]["prompt"], saved["prompt"])
            self.assertTrue(again["made"])

    def test_a_brand_whose_settings_say_nothing_usable_gets_no_invented_mood(self):
        plan = self.plan()                      # the test bakery's register and industry are still TODO
        plan["music"]["compose"] = {"instrumental": True}
        self.write(plan)
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "sk_test_value"}), mock.patch("requests.post") as post:
            with self.assertRaises(VideoError) as e:
                montage.make_music(self.brand, FILM, confirm=True)
            post.assert_not_called()
        self.assertIn("three words", str(e.exception))
        self.assertNotIn("prompt", self.saved_plan()["music"]["compose"])
        self.assertEqual(montage.brand_music_words(self.brand), ("", []))
        # the person's own words, once given, are used exactly as written and never redrafted
        plan["music"]["compose"] = {"prompt": "slow, warm, wooden"}
        self.write(plan)
        out, post = self.make(confirm=False)
        self.assertFalse(out["drafted"])
        self.assertEqual(out["prompt"], "slow, warm, wooden")

    def test_the_status_screen_says_the_bed_and_the_voice_need_the_elevenlabs_key(self):
        from smf import status
        film = next(f for f in status.load_features()["features"] if f["id"] == "narrated-film")
        self.assertIn("made to order", film["output"])
        state = {"tiers": {"core": {}, "video": {}}}
        with mock.patch.dict(status.CHECKS, {"ffmpeg": lambda: (True, "")}), \
                mock.patch.object(status.keys, "has", return_value=False):
            st, why, _next = status.evaluate(film, state, have_brand=True)
        self.assertEqual(st, "ready")
        self.assertIn("ELEVENLABS_API_KEY", why)
        self.assertIn("music bed", why)
        self.assertIn("voicing", why)
        with mock.patch.dict(status.CHECKS, {"ffmpeg": lambda: (True, "")}), \
                mock.patch.object(status.keys, "has", return_value=True):
            self.assertEqual(status.evaluate(film, state, have_brand=True), ("ready", "", ""))

    def test_the_verb_says_the_cost_and_sends_nothing_without_confirm(self):
        self.write(self.plan())
        with mock.patch("requests.post") as post, mock.patch("builtins.print") as said:
            self.assertEqual(montage_cli.cli_montage(["music", "--brand", "maple-and-main", "--film", FILM]), 0)
        post.assert_not_called()
        spoken = " ".join(str(c[0][0]) for c in said.call_args_list)
        self.assertIn("Nothing was sent", spoken)
        self.assertIn("credits from your ElevenLabs plan", spoken)
        self.assertIn(self.PROMPT, spoken)
        self.assertIn("music_v2_5", spoken)


class TestTheVerb(MontageCase):
    def test_the_footage_verb_needs_only_a_brand_and_the_draft_verb_answers_in_sentences(self):
        with mock.patch("builtins.print") as said:
            self.assertEqual(montage_cli.cli_montage(["footage", "--brand", "maple-and-main"]), 0)
            self.assertIn("footage folder", " ".join(c[0][0] for c in said.call_args_list))
            self.assertEqual(montage_cli.cli_montage(["draft", "--brand", "maple-and-main", "--film", FILM]), 1)
            self.assertIn("--from-brand", said.call_args[0][0])

    def test_the_verb_answers_in_sentences_and_needs_a_brand_and_a_film(self):
        with mock.patch("builtins.print") as said:
            self.assertEqual(montage_cli.cli_montage(["check", "--brand", "maple-and-main", "--film", "Nothing here"]), 1)
            self.assertIn("no plan", said.call_args[0][0].lower())
            self.assertEqual(montage_cli.cli_montage(["dance", "--brand", "maple-and-main", "--film", FILM]), 1)
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            montage_cli.cli_montage(["check", "--film", FILM])


# ============================================================================= motion titles (HyperFrames)
class TitlesCase(MontageCase):
    """A bakery that chose its colours, a wordmark and a handle, and a stand-in for HyperFrames
    that writes a clip of the planned length without starting Node."""

    BAKERY = {"visual": {"colors": {"ground": "#FBF7F0", "ink": "#2B1D14", "accent": "#C2571A"},
                         "wordmark": "Maple & Main", "handle": "@mapleandmain"}}

    def setUp(self):
        super().setUp()
        self.brand = brands.create("maple-titles", "Maple & Main Bakery", answers=json.loads(json.dumps(self.BAKERY)))
        self.home = montage.film_dir(self.brand, FILM)
        os.makedirs(self.home)
        self.rendered, self.size = [], (320, 180)
        patches = [mock.patch.object(montage, "_title_programs", return_value=("node", "hyperframes.mjs")),
                   mock.patch.object(montage, "_hyperframes_render", side_effect=self._render),
                   mock.patch.object(montage, "_probe_size", side_effect=lambda path: self.size)]
        self.ready = patches[0]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _render(self, project_dir, out_path, fps, quality):
        html = Path(project_dir, "index.html").read_text(encoding="utf-8")
        seconds = float(html.split('data-duration="')[1].split('"')[0])
        Path(out_path).write_bytes(b"not really a film")
        self.lengths[os.path.basename(out_path)] = seconds
        self.rendered.append({"dir": project_dir, "out": out_path, "fps": fps, "html": html, "seconds": seconds})

    def plan(self, **extra):
        plan = plan_with({"oven": {"file": self.footage("oven.mp4", 30.0), "credit": "Our own footage"}},
                         [{"say": "Fresh bread every morning.", "from": 0.0, "to": 2.0, "on_screen": "Fresh bread",
                           "shots": [{"source": "oven", "at": 4.0}]},
                          {"say": "Watch the dough, not the clock.", "from": 2.0, "to": 5.0,
                           "shots": [{"source": "oven", "at": 9.0}], "suggested": ["oven"]},
                          {"say": "Time is an ingredient.", "from": 5.0, "to": 7.0, "shots": [],
                           "on_screen": "Time is\nan ingredient"}], **extra)
        self.write(plan)
        return plan

    def saved(self):
        return json.loads(Path(self.home, montage.PLAN_FILE).read_text(encoding="utf-8"))

    def html(self, n):
        return Path(montage.titles_dir(self.brand, FILM), str(n), "index.html").read_text(encoding="utf-8")


class TestTitles(TitlesCase):
    def test_every_title_is_words_already_in_the_plan_or_the_brand_and_nothing_else(self):
        self.plan()
        out = montage.titles(self.brand, FILM, say=lambda *_: None)
        plan = self.saved()
        self.assertEqual([t["name"] for t in out["titles"]], ["title-1", "title-2", "title-3", "title-4"])
        self.assertEqual([t["text"] for t in out["titles"]],
                         [["Spring bake"], ["Fresh bread"], ["Time is", "an ingredient"], ["Maple & Main", "@mapleandmain"]])
        self.assertEqual(out["without"], [2])                      # line 2 has no words on screen: no title
        for t in out["titles"]:
            src = plan["sources"][t["name"]]
            self.assertEqual(src["credit"], montage.TITLE_CREDIT)
            self.assertTrue(os.path.isfile(os.path.join(self.home, *src["file"].split("/"))), src["file"])
        self.assertIn("Spring bake", self.html(1))
        self.assertIn("Time is<br>an ingredient", self.html(3))
        self.assertIn("Maple &amp; Main", self.html(4))
        self.assertIn("@mapleandmain", self.html(4))
        self.assertNotIn("Fresh bread", self.html(1))             # one page, one piece of text

    def test_the_brands_colours_and_fonts_are_in_every_title(self):
        self.plan()
        montage.titles(self.brand, FILM, say=lambda *_: None)
        page = self.html(2)
        for colour in ("#FBF7F0", "#2B1D14", "#C2571A"):
            self.assertIn(colour, page)
        self.assertIn('url("fonts/Inter-Variable.ttf")', page)        # the built-in face, copied beside the page
        self.assertTrue(os.path.isfile(os.path.join(montage.titles_dir(self.brand, FILM), "2", "fonts", "Inter-Variable.ttf")))

    def test_each_kind_of_title_sits_on_the_ground_the_cards_would_use_with_their_exact_colours(self):
        from smf.studio.render import kit as K
        self.plan()
        montage.titles(self.brand, FILM, say=lambda *_: None)
        kit = K.resolve(self.brand)
        bold, main = kit.palette("bold"), kit.palette("main")
        self.assertIn("background:%s" % bold["bg"], self.html(1))             # the opening title: the bold ground
        self.assertIn("color:%s" % bold["head"], self.html(1))
        self.assertIn("background:%s" % main["bg"], self.html(2))             # words on screen: the brand's own background
        self.assertIn("color:%s" % main["head"], self.html(2))
        self.assertIn("background:%s" % bold["accent"], self.html(1))         # the rule, nudged readable as a card's would be
        self.assertIn("background:%s" % bold["bg"], self.html(4))             # the end card closes as the opening opened

    def test_a_title_never_uses_the_factorys_placeholder_colours_when_the_brand_has_its_own(self):
        placeholders = {c.upper() for c in brands.blank_master("x", "X")["visual"]["colors"].values()}
        self.plan()
        montage.titles(self.brand, FILM, say=lambda *_: None)
        for n in (1, 2, 3, 4):
            page = self.html(n).upper()
            for colour in placeholders:
                self.assertNotIn(colour, page, "title %d carries the placeholder %s" % (n, colour))

    def test_titles_for_two_brands_with_different_colours_differ(self):
        other = brands.create("stride-titles", "Stride Physio",
                              answers={"visual": {"colors": {"ground": "#0E1F2B", "ink": "#F2F6F7", "accent": "#5BD1B9"},
                                                  "wordmark": "Stride", "handle": "@stride"}})
        os.makedirs(montage.film_dir(other, FILM))
        self.plan()
        bakery = self.home
        self.home = montage.film_dir(other, FILM)
        self.plan()
        self.home = bakery
        montage.titles(self.brand, FILM, say=lambda *_: None)
        montage.titles(other, FILM, say=lambda *_: None)
        page_of = lambda b, n: Path(montage.titles_dir(b, FILM), str(n), "index.html").read_text(encoding="utf-8")   # noqa: E731
        self.assertIn("background:#FBF7F0", page_of(self.brand, 2))
        self.assertIn("background:#0E1F2B", page_of(other, 2))
        self.assertNotIn("#FBF7F0", page_of(other, 2).upper())

    def test_a_change_of_colour_draws_every_title_again(self):
        self.plan()
        montage.titles(self.brand, FILM, say=lambda *_: None)
        master = json.loads(Path(self.brand.home, brands.MASTER).read_text(encoding="utf-8"))
        master["visual"]["colors"]["accent"] = "#3E6B4F"
        Path(self.brand.home, brands.MASTER).write_text(json.dumps(master), encoding="utf-8")
        out = montage.titles(brands.load("maple-titles"), FILM, say=lambda *_: None)
        self.assertEqual(len(self.rendered), 8)
        self.assertFalse(any(t["reused"] for t in out["titles"]))
        self.assertIn("#3E6B4F", self.html(out["titles"][1]["name"].split("-")[1]))

    def test_the_brands_logo_is_on_the_end_card_and_nowhere_else(self):
        logos = Path(self.brand.kit_dir, "logos")
        logos.mkdir(parents=True, exist_ok=True)
        (logos / "mark.png").write_bytes(ONE_PIXEL_PNG)
        master = json.loads(Path(self.brand.home, brands.MASTER).read_text(encoding="utf-8"))
        master["visual"]["logo"] = "Brand/brand-kit/logos/mark.png"
        Path(self.brand.home, brands.MASTER).write_text(json.dumps(master), encoding="utf-8")
        self.plan()
        montage.titles(brands.load("maple-titles"), FILM, say=lambda *_: None)
        self.assertIn('<img class="logo" src="logo.png"', self.html(4))
        self.assertTrue(os.path.isfile(os.path.join(montage.titles_dir(self.brand, FILM), "4", "logo.png")))
        for n in (1, 2, 3):
            self.assertNotIn("logo.png", self.html(n))

    def test_a_brand_may_choose_the_ground_for_each_kind_and_an_unknown_choice_is_ignored(self):
        from smf.studio.render import kit as K
        master = json.loads(Path(self.brand.home, brands.MASTER).read_text(encoding="utf-8"))
        master["visual"]["titles"] = {"opening": "accent", "words": "sparkly"}
        Path(self.brand.home, brands.MASTER).write_text(json.dumps(master), encoding="utf-8")
        brand = brands.load("maple-titles")
        self.plan()
        montage.titles(brand, FILM, say=lambda *_: None)
        kit = K.resolve(brand)
        self.assertIn("background:%s" % kit.palette("accent")["bg"], self.html(1))
        self.assertIn("background:%s" % kit.palette("main")["bg"], self.html(2))

    def test_one_entrance_one_exit_and_stillness_between(self):
        self.plan()
        out = montage.titles(self.brand, FILM, say=lambda *_: None)
        page = self.html(1)
        self.assertEqual(page.count("@keyframes"), 3)                        # rise, grow (the rule) and leave: nothing else
        self.assertIn("animation:leave %.2fs ease-in %.3fs both" % (montage.TITLE_EXIT, out["titles"][0]["seconds"] - montage.TITLE_EXIT), page)

    def test_a_brands_own_font_file_is_used_when_it_names_one(self):
        fonts = Path(self.brand.kit_dir, "fonts")
        fonts.mkdir(parents=True, exist_ok=True)
        (fonts / "House.ttf").write_bytes(b"\x00\x01\x00\x00 not a real font, and never opened here")
        master = json.loads(Path(self.brand.home, brands.MASTER).read_text(encoding="utf-8"))
        master["visual"]["fonts"] = {"display": "House.ttf"}
        Path(self.brand.home, brands.MASTER).write_text(json.dumps(master), encoding="utf-8")
        self.plan()
        montage.titles(brands.load("maple-titles"), FILM, say=lambda *_: None)
        page = self.html(1)
        self.assertIn('font-family:"smf-display";src:url("fonts/House.ttf")', page)
        self.assertTrue(os.path.isfile(os.path.join(montage.titles_dir(self.brand, FILM), "1", "fonts", "House.ttf")))

    def test_titles_are_the_plans_size_and_frame_rate_and_long_enough_for_their_line(self):
        self.plan()
        out = montage.titles(self.brand, FILM, say=lambda *_: None)
        self.assertEqual({r["fps"] for r in self.rendered}, {25})
        for r in self.rendered:
            self.assertIn('data-width="320"', r["html"])
            self.assertIn('data-height="180"', r["html"])
            self.assertIn("data-no-timeline", r["html"])             # CSS drives it; nothing else to wait for
        by_name = {t["name"]: t for t in out["titles"]}
        self.assertEqual(by_name["title-1"]["seconds"], montage.TITLE_SECONDS)
        # line 3 runs 2.0s of voice plus the gap: its words outlast it by the margin, never less than the minimum
        self.assertEqual(by_name["title-3"]["seconds"], max(montage.TITLE_MIN, round(2.0 + 0.3 + montage.TITLE_MARGIN, 1)))

    def test_a_title_is_suggested_on_its_line_and_never_placed(self):
        before = self.plan()
        montage.titles(self.brand, FILM, say=lambda *_: None)
        after = self.saved()
        for i, line in enumerate(after["lines"]):
            self.assertEqual(line["shots"], before["lines"][i]["shots"])
            self.assertEqual({k: v for k, v in line.items() if k != "suggested"},
                             {k: v for k, v in before["lines"][i].items() if k != "suggested"})
        self.assertEqual(after["lines"][0]["suggested"], ["title-1", "title-2"])      # the opening title and its words
        self.assertEqual(after["lines"][1]["suggested"], ["oven"])                    # what was there stays
        self.assertEqual(after["lines"][2]["suggested"], ["title-3", "title-4"])      # its words, then the end card
        self.assertEqual(after.get("opening", []), before.get("opening", []))
        self.assertEqual(after["sources"]["oven"], before["sources"]["oven"])

    def test_running_again_renders_nothing_and_changes_nothing(self):
        self.plan()
        montage.titles(self.brand, FILM, say=lambda *_: None)
        once = self.saved()
        out = montage.titles(self.brand, FILM, say=lambda *_: None)
        self.assertEqual(len(self.rendered), 4)
        self.assertTrue(all(t["reused"] for t in out["titles"]))
        self.assertEqual(self.saved(), once)

    def test_changed_words_get_a_new_clip_and_a_persons_own_source_is_never_touched(self):
        plan = self.plan()
        plan["sources"]["title-1"] = {"file": "oven.mp4", "credit": "A title I made myself"}
        self.write(plan)
        montage.titles(self.brand, FILM, say=lambda *_: None)
        saved = self.saved()
        self.assertEqual(saved["sources"]["title-1"], plan["sources"]["title-1"])
        self.assertEqual(sorted(k for k in saved["sources"] if k.startswith("title-")),
                         ["title-1", "title-2", "title-3", "title-4", "title-5"])
        saved["lines"][0]["on_screen"] = "Fresh bread, every day"
        self.write(saved)
        out = montage.titles(self.brand, FILM, say=lambda *_: None)
        self.assertEqual(len(self.rendered), 5)                    # one new clip, the other three reused
        new = [t for t in out["titles"] if not t["reused"]]
        self.assertEqual([t["text"] for t in new], [["Fresh bread, every day"]])
        self.assertEqual(new[0]["name"], "title-6")
        self.assertIn("title-6", self.saved()["lines"][0]["suggested"])

    def test_without_the_title_renderer_it_says_how_to_set_it_up_and_nothing_is_written(self):
        from smf import bootstrap
        self.plan()
        before = self.saved()
        self.ready.stop()
        try:
            with mock.patch.object(bootstrap, "title_programs", return_value=None):
                with self.assertRaises(VideoError) as e:
                    montage.titles(self.brand, FILM, say=lambda *_: None)
        finally:
            self.ready.start()
        self.assertIn("setup --tier video", str(e.exception))
        self.assertIn("Nothing was changed", str(e.exception))
        self.assertFalse(os.path.exists(montage.titles_dir(self.brand, FILM)))
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.rendered, [])

    def test_a_clip_of_the_wrong_size_is_refused_and_the_plan_untouched(self):
        self.plan()
        before = self.saved()
        self.size = (640, 360)
        with self.assertRaises(VideoError) as e:
            montage.titles(self.brand, FILM, say=lambda *_: None)
        self.assertIn("640x360", str(e.exception))
        self.assertEqual(self.saved(), before)
        self.assertFalse(os.path.isfile(self.rendered[0]["out"]))

    def test_a_render_that_fails_is_a_sentence_and_the_plan_untouched(self):
        self.plan()
        before = self.saved()
        with mock.patch.object(montage, "_hyperframes_render", side_effect=VideoError("HyperFrames could not render the "
                                                                                       "title in 1. It said: boom.")):
            with self.assertRaises(VideoError) as e:
                montage.titles(self.brand, FILM, say=lambda *_: None)
        self.assertIn("boom", str(e.exception))
        self.assertEqual(self.saved(), before)

    def test_a_brand_without_a_wordmark_is_refused_before_anything_is_made(self):
        master = json.loads(Path(self.brand.home, brands.MASTER).read_text(encoding="utf-8"))
        master["visual"]["wordmark"] = ""
        Path(self.brand.home, brands.MASTER).write_text(json.dumps(master), encoding="utf-8")
        self.plan()
        with self.assertRaises(brands.BrandError) as e:
            montage.titles(brands.load("maple-titles"), FILM, say=lambda *_: None)
        self.assertIn("wordmark", str(e.exception))
        self.assertFalse(os.path.exists(montage.titles_dir(self.brand, FILM)))

    def test_the_verb_answers_in_sentences(self):
        self.plan()
        with mock.patch("builtins.print") as said:
            self.assertEqual(montage_cli.cli_montage(["titles", "--brand", "maple-titles", "--film", FILM]), 0)
            text = " ".join(str(c[0][0]) for c in said.call_args_list)
        self.assertIn("title-1", text)
        self.assertIn("placed nowhere", text)
        self.assertIn("line 2", text)                               # the line with no words on screen is named


# ============================================================================= with the real video programs
def _video_tier():
    try:
        import static_ffmpeg                                               # noqa: F401
        from smf import media
        media.ensure_ffmpeg()
        return True
    except Exception:
        return False


HAS_VIDEO = _video_tier()
NEEDS_VIDEO = "the video tools are not installed (python factory.py setup --tier video)"


@unittest.skipUnless(HAS_VIDEO, NEEDS_VIDEO)
class TestWithRealFootage(BrandCase):
    """Footage made from plain sources: a red-then-blue clip with a hard change at 2.0 seconds, a
    frozen grey card, and a moving test pattern. The voice is a plain tone standing in for a
    recorded read, so nothing is sent anywhere."""

    @classmethod
    def setUpClass(cls):
        from smf import media
        cls.ff, cls.fp = media.ensure_ffmpeg()
        cls.made = tempfile.TemporaryDirectory(prefix="montage ' é ")
        d = cls.made.name

        def make(args, name):
            r = subprocess.run([cls.ff, "-y", "-v", "error"] + args + [os.path.join(d, name)],
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[-400:]

        make(["-f", "lavfi", "-i", "color=c=red:s=320x180:r=25:d=2", "-f", "lavfi", "-i",
              "color=c=blue:s=320x180:r=25:d=3", "-filter_complex", "[0][1]concat=n=2:v=1[v]", "-map", "[v]",
              "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"], "two scenes.mp4")
        make(["-f", "lavfi", "-i", "color=c=gray:s=320x180:r=25:d=6", "-c:v", "libx264", "-preset", "ultrafast",
              "-pix_fmt", "yuv420p"], "still card.mp4")
        make(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=12", "-c:v", "libx264", "-preset", "ultrafast",
              "-pix_fmt", "yuv420p"], "moving.mp4")
        make(["-f", "lavfi", "-i", "sine=frequency=220:duration=8", "-c:a", "pcm_s16le"], "read.wav")
        make(["-f", "lavfi", "-i", "color=c=white:s=200x200", "-frames:v", "1"], "card.png")

    @classmethod
    def tearDownClass(cls):
        cls.made.cleanup()

    def setUp(self):
        super().setUp()
        self.brand = brands.create("maple-and-main", "Maple & Main Bakery")
        self.home = montage.film_dir(self.brand, FILM)
        shutil.copytree(self.made.name, self.home)

    def test_the_scene_change_is_found_where_it_is(self):
        path = os.path.join(self.home, "two scenes.mp4")
        cuts = montage.scene_cuts(path, 1.0, 2.0)
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0], 2.0, delta=0.1)
        self.assertEqual(montage.scene_cuts(path, 2.3, 2.0), [])

    def test_a_frozen_card_is_still_and_a_moving_pattern_is_not(self):
        self.assertTrue(montage.is_still(os.path.join(self.home, "still card.mp4"), 1.0, 3.0))
        self.assertFalse(montage.is_still(os.path.join(self.home, "moving.mp4"), 1.0, 3.0))

    def plan(self, **extra):
        plan = plan_with({"moving": {"file": "moving.mp4", "credit": "Test pattern"},
                          "scenes": {"file": "two scenes.mp4", "credit": "Test colours"}},
                         [{"say": "Fresh bread.", "from": 0.0, "to": 2.2,
                           "shots": [{"source": "moving", "at": 1.0}, {"source": "scenes", "at": 2.4}]},
                          {"say": "Every morning.", "from": 3.0, "to": 5.5,
                           "shots": [{"source": "moving", "at": 6.0}]}],
                         voice={"recording": "read.wav"},
                         opening=[{"source": "scenes", "at": 0.2, "seconds": 1.0}])
        plan.update(extra)
        Path(self.home, montage.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
        return plan

    def test_a_plan_with_errors_is_not_rendered(self):
        plan = self.plan()
        plan["lines"][0]["shots"][1]["at"] = 1.5                   # straddles the change at 2.0
        Path(self.home, montage.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(VideoError) as e:
            montage.render(self.brand, FILM, say=lambda *_: None)
        self.assertIn("scene change", " ".join(getattr(e.exception, "findings", []) or [str(e.exception)]))
        self.assertFalse(os.path.exists(os.path.join(self.home, montage.FILM_FILE)))

    def test_the_film_renders_in_step_with_its_voice_with_a_contact_sheet_and_credits(self):
        self.plan()
        report = montage.render(self.brand, FILM, say=lambda *_: None)
        film = os.path.join(self.home, montage.FILM_FILE)
        self.assertTrue(os.path.isfile(film))
        tl = report["timeline"]
        from smf.video.common import probe_duration
        self.assertAlmostEqual(probe_duration(film), tl["frames"] / 25.0, delta=0.08)
        self.assertLessEqual(abs(report["picture_seconds"] - report["sound_seconds"]), 1.0 / 25 + 0.03)
        self.assertTrue(os.path.isfile(os.path.join(self.home, montage.SHEET_FILE)))
        credits = Path(self.home, montage.CREDITS_FILE).read_text(encoding="utf-8")
        self.assertIn("Test pattern", credits)
        self.assertIn("Test colours", credits)
        self.assertFalse([n for n in os.listdir(self.home) if ".working" in n])

    def test_a_music_bed_and_an_end_card_keep_the_film_in_step(self):
        self.plan(music={"bed": "drone", "level_db": -14}, end_card={"image": "card.png", "seconds": 1.5})
        report = montage.render(self.brand, FILM, say=lambda *_: None)
        tl = report["timeline"]
        self.assertTrue(tl["shots"][-1].get("card"))
        self.assertAlmostEqual(tl["seconds"], 1.0 + (2.2 + 0.3) + (2.5 + 0.3) + 1.5, delta=1.0 / 25)
        self.assertLessEqual(abs(report["picture_seconds"] - report["sound_seconds"]), 1.0 / 25 + 0.03)

    def test_a_slow_motion_shot_renders_at_its_planned_length(self):
        plan = self.plan()
        plan["lines"][1]["shots"][0]["speed"] = 0.5
        Path(self.home, montage.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
        report = montage.render(self.brand, FILM, say=lambda *_: None)
        self.assertLessEqual(abs(report["picture_seconds"] - report["sound_seconds"]), 1.0 / 25 + 0.03)
        self.assertAlmostEqual(report["picture_seconds"], report["timeline"]["seconds"], delta=0.08)

    def test_a_still_image_renders_with_a_slow_move_at_its_planned_length(self):
        plan = self.plan()
        plan["sources"]["card"] = {"file": "card.png", "fit": "pad", "credit": "Test card"}
        plan["lines"][1]["shots"] = [{"source": "card", "at": 0, "move": "in"}, {"source": "moving", "at": 6.0}]
        Path(self.home, montage.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
        report = montage.render(self.brand, FILM, say=lambda *_: None)
        self.assertLessEqual(abs(report["picture_seconds"] - report["sound_seconds"]), 1.0 / 25 + 0.03)
        self.assertAlmostEqual(report["picture_seconds"], report["timeline"]["seconds"], delta=0.08)

    def test_a_dry_run_makes_nothing(self):
        self.plan()
        said = []
        report = montage.render(self.brand, FILM, dry_run=True, say=said.append)
        self.assertTrue(report["dry_run"])
        self.assertFalse(os.path.exists(os.path.join(self.home, montage.FILM_FILE)))
        self.assertTrue(any("moving" in s for s in said))

    def test_a_render_leaves_the_title_clips_alone(self):
        self.plan()
        kept = Path(montage.titles_dir(self.brand, FILM), "1", "title-1.mp4")
        kept.parent.mkdir(parents=True)
        kept.write_bytes(b"a title clip made earlier")
        montage.render(self.brand, FILM, say=lambda *_: None)
        self.assertTrue(kept.is_file())
        self.assertFalse(os.path.exists(os.path.join(self.home, montage.WORK_DIR, "render")))


@unittest.skipUnless(HAS_VIDEO, NEEDS_VIDEO)
class TestTitlesWithHyperFrames(BrandCase):
    """The real renderer, when Node 22+ is here and HyperFrames is already in npx's cache: one title
    is rendered and a frame of it is looked at. Skipped, with the reason, anywhere else."""

    @classmethod
    def setUpClass(cls):
        ok, why = montage.titles_available()
        if not ok:
            raise unittest.SkipTest("titles cannot be rendered here: %s" % why)

    def setUp(self):
        super().setUp()
        self.brand = brands.create("maple-titles", "Maple & Main Bakery", answers=json.loads(json.dumps(TitlesCase.BAKERY)))
        self.home = montage.film_dir(self.brand, FILM)
        os.makedirs(self.home)

    def test_a_title_renders_at_the_plans_size_and_length_in_the_brands_colours(self):
        plan = plan_with({}, [{"say": "Fresh bread every morning.", "from": 0.0, "to": 2.0, "shots": [],
                               "on_screen": "Fresh bread"}], title="", quality="draft")
        Path(self.home, montage.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
        out = montage.titles(self.brand, FILM, say=lambda *_: None)
        self.assertEqual([t["name"] for t in out["titles"]], ["title-1", "title-2"])
        clip = os.path.join(self.home, *self.plan_source("title-1").split("/"))
        self.assertEqual(montage._probe_size(clip), (320, 180))
        from smf.video.common import probe_duration
        self.assertAlmostEqual(probe_duration(clip), out["titles"][0]["seconds"], delta=1.0 / 25 + 0.05)
        try:
            from PIL import Image
        except ImportError:
            return
        from smf import media
        ff, _fp = media.ensure_ffmpeg()
        frame = os.path.join(self.tmp.name, "frame.png")
        subprocess.run([ff, "-y", "-v", "error", "-ss", "3", "-i", clip, "-frames:v", "1", frame], check=True)
        colours = sorted(Image.open(frame).convert("RGB").getcolors(maxcolors=1 << 20), reverse=True)
        self.assertGreater(len(colours), 1)                        # words on the page, not a flat card
        most = colours[0][1]
        self.assertTrue(all(abs(a - b) <= 10 for a, b in zip(most, (0xFB, 0xF7, 0xF0))),
                        "the ground should be the brand's, got %r" % (most,))

    def plan_source(self, name):
        plan = json.loads(Path(self.home, montage.PLAN_FILE).read_text(encoding="utf-8"))
        return plan["sources"][name]["file"]

    def test_two_brands_titles_differ_in_their_pixels_at_the_background(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("the imaging library is not installed")
        from smf import media
        ff, _fp = media.ensure_ffmpeg()
        other = brands.create("stride-titles", "Stride Physio",
                              answers={"visual": {"colors": {"ground": "#0E1F2B", "ink": "#F2F6F7", "accent": "#5BD1B9"},
                                                  "wordmark": "Stride", "handle": "@stride"}})
        corners = {}
        for brand in (self.brand, other):
            home = montage.film_dir(brand, FILM)
            os.makedirs(home, exist_ok=True)
            plan = plan_with({}, [{"say": "Fresh bread every morning.", "from": 0.0, "to": 1.0, "shots": [],
                                   "on_screen": "Fresh bread"}], title="", quality="draft", size=[160, 90])
            Path(home, montage.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
            out = montage.titles(brand, FILM, say=lambda *_: None)
            words = next(t for t in out["titles"] if t["kind"] == "words")
            clip = os.path.join(home, montage.WORK_DIR, montage.TITLES_DIR, words["name"].split("-")[1], words["name"] + ".mp4")
            frame = os.path.join(self.tmp.name, "%s.png" % brand.id)
            subprocess.run([ff, "-y", "-v", "error", "-ss", "2", "-i", clip, "-frames:v", "1", frame], check=True)
            corners[brand.id] = Image.open(frame).convert("RGB").getpixel((3, 3))
        bakery, physio = corners["maple-titles"], corners["stride-titles"]
        self.assertTrue(all(abs(a - b) <= 10 for a, b in zip(bakery, (0xFB, 0xF7, 0xF0))), bakery)
        self.assertTrue(all(abs(a - b) <= 10 for a, b in zip(physio, (0x0E, 0x1F, 0x2B))), physio)


if __name__ == "__main__":
    unittest.main()
