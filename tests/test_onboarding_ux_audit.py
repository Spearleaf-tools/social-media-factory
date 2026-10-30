"""Onboarding page, UX audit round 1 (Oct 19; designs agreed by Claude and ChatGPT, refined in design review):
one primary "Confirm and continue" in design B, typing never lost, a short phone header, "Your brand so far",
one way to choose colours first with a live sample, and the smaller fixes (price, Q14, tiles, mic, targets)."""
import json
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "smf" / "onboarding_page" / "static"
FIELDS = STATIC.parent / "fields.json"


class TestTheMainButton(unittest.TestCase):
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.steps = (STATIC / "steps.html").read_text(encoding="utf-8")
        self.one = (STATIC / "one-page.html").read_text(encoding="utf-8")

    def test_design_b_confirms_and_continues_with_one_primary_button(self):
        self.assertIn('return s === "ok" ? "Save changes and continue" : "Confirm and continue";', self.engine)
        self.assertIn("if (ok && UI.flow) { UI.next(field); }", self.engine)
        self.assertIn("flow: true", self.steps)
        self.assertNotIn('id="next"', self.steps)          # the old black Next is gone
        self.assertNotIn("flow: true", self.one)           # design A keeps saving in place

    def test_skip_is_the_one_way_to_put_a_question_off_and_never_confirms(self):
        self.assertIn('"Skip for now"', self.engine)
        self.assertNotIn('data-act="later">Leave it for later', self.engine)        # audit round 2: one way, not two
        self.assertIn("Skipping never throws typing away", self.engine)

    def test_a_blank_answer_is_never_confirmed(self):
        self.assertIn('if (blank(field)) { err(field, "Type an answer, or tap Skip for now."); return Promise.resolve(false); }', self.engine)

    def test_enter_confirms_only_from_a_one_line_box(self):
        self.assertIn('e.key !== "Enter" || e.isComposing || e.repeat', self.engine)
        self.assertIn('t.tagName !== "INPUT"', self.engine)


class TestTypingIsNeverLost(unittest.TestCase):
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")

    def test_typing_is_kept_on_this_computer_until_confirmed(self):
        self.assertIn('var typedKey = "smf-v2-typed-" + location.pathname;', self.engine)
        self.assertIn("localStorage.setItem(typedKey", self.engine)
        self.assertIn("loadTyped();", self.engine)
        self.assertIn('window.addEventListener("pagehide"', self.engine)

    def test_only_a_confirm_clears_it_and_a_skip_keeps_it(self):
        self.assertIn("Skipping never throws typing away", self.engine)
        self.assertIn('typed: "Not confirmed yet"', self.engine)

    def test_restoring_never_marks_a_box_as_typed(self):
        self.assertIn("if (restoring) { return; }", self.engine)


class TestTheScreens(unittest.TestCase):
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")
        self.steps = (STATIC / "steps.html").read_text(encoding="utf-8")

    def test_phone_header_is_one_row_with_a_menu(self):
        self.assertIn('id="open-menu"', self.steps)
        self.assertIn('.mapline, .subbar, .brandmark, .top .row .navbtn:not(.menu), .count .wide { display:none; }', self.steps)
        for item in ("Your steps", "Type of business: ", "Settings", "Go to Finish", "Finish in chat"):
            self.assertIn(item, self.steps)

    def test_finish_is_your_brand_so_far_and_never_confirms(self):
        self.assertIn("<h1>Your brand so far</h1>", self.steps)
        self.assertIn("Draft waiting for your yes", self.steps)
        self.assertIn("Anything not confirmed stays a draft or a placeholder; nothing is guessed.", self.steps)
        self.assertNotIn("Finish anyway", self.steps)

    def test_map_tiles_are_buttons(self):
        self.assertIn('<button type="button" data-jump="', self.steps)         # rev 14: the five steps are buttons

    def test_colours_lead_with_one_way_and_show_a_sample(self):
        self.assertIn("var lead = picker || packPal || mood", self.engine)
        self.assertIn("<summary>More ways to choose</summary>", self.engine)
        self.assertIn("Sample preview, not your real content", self.engine)
        self.assertIn('"Colours from your website" + page', self.engine)
        self.assertIn('"Suggested palette. Please check it."', self.engine)


class TestTheSmallerFixes(unittest.TestCase):
    def setUp(self):
        self.engine = (STATIC / "v2-common.js").read_text(encoding="utf-8")

    def test_question_3_is_short_with_a_hint_and_one_answer(self):
        q3 = [f for f in json.loads(FIELDS.read_text(encoding="utf-8"))["core"] if f["n"] == 3][0]
        self.assertEqual(q3["ask"], "What do you do, and for whom?")
        self.assertIn("own experience", q3["hint"])
        self.assertEqual([p["name"] for p in q3["parts"]], ["value"])

    def test_offers_have_an_optional_price_and_none_yet_is_a_big_row(self):
        self.assertIn('textInput(fid(field, "price")', self.engine)
        self.assertIn("if (pr) { r2.price = pr; }", self.engine)
        self.assertIn('label class="check row-check"', self.engine)

    def test_beliefs_start_with_one_pair(self):
        self.assertIn('"Add another belief (up to three more)"', self.engine)
        self.assertIn('var waiting = items.querySelector(".item[hidden]");', self.engine)

    def test_mic_is_a_drawn_icon_with_the_button_named(self):
        self.assertIn('<svg class=\\"mic\\"', self.engine)
        self.assertIn('aria-label="Talk instead of typing"', self.engine)

    def test_draft_this_for_me_sits_under_its_box(self):
        self.assertIn("<!--assist-->", self.engine)
        self.assertIn("Not sure?", self.engine)


if __name__ == "__main__":
    unittest.main(verbosity=2)
