# Clip rubric: how to pick clips out of a recording

> last_researched: 2026-09-20 (as of September 2026). Confidence: high on the method, low on any number
> Covers choosing short clips from a longer recording: an interview, a podcast, a talk, a filmed
> question-and-answer session. It does not cover writing scripts (see `short-form-scripts.md`) or
> what makes an opening work (see `hooks.md`). Every example is invented. See `README.md`.

## The short version

1. A tool checks two things it can check: **compliance** and **who is speaking**.
2. A person checks the one thing a tool cannot: **is there a first frame worth stopping for?**
3. Then a person picks, by reading the transcript, using six questions. Nothing is scored and summed.
4. Every hook is copied from the transcript word for word. Nothing is written fresh.

## Why a person picks, and the tool only points

It is tempting to score every passage (numbers, strong words, surprises) and cut the top ten.
That was tested. The scores were compared with how real published clips had actually performed,
and there was no relationship. The score did no better than guessing from the clip's length.

So the finder in the Factory (`find-clips`) does two honest jobs and stops:

- **It lints.** It flags passages that break the brand's compliance rules, with the reason.
- **It points.** It lists stretches that are dense with numbers, reactions and the brand's own
  subjects, in the order they happen, as places to read first.

It prints no rank and no quality score, on purpose. If you catch yourself sorting by its
`density` figure, stop: that figure says "a lot is going on per second here" and nothing more.

## Gate 1: compliance and speaker (the tool enforces it)

A passage that fails this gate is out, however good it sounds.

**Compliance** comes from the brand's own settings. There are three outcomes:

| Status | Meaning | What happens |
|---|---|---|
| SHIP | Nothing in the brand's rules applies | It can be cut and posted |
| HOLD | It contains a claim that needs the brand's disclaimer and a named person's sign-off | It can be cut so that person can watch it. It is not posted until they sign it off |
| DROP | It contains a claim the brand must never publish | It is never cut |

A brand in a regulated field gets a stricter pack. For a health brand, for example, a cure
claim, a guaranteed result, advice to go without usual care, or a specific dose is a DROP. Softer
things (dosing language with no number, one person's result, what a treatment "does") are a HOLD.
A brand that is not regulated runs with a nearly empty gate: only its own listed terms and its
never-mention list.

Two rules that are easy to miss:

- **A flag covers the whole range, not the quoted line.** If a held sentence sits inside a body,
  every clip made from that body is held, including the ones whose hook is a different sentence.
- **Sign-off approves the clip as designed.** If the design kept a qualifier next to a claim, the
  qualifier stays. Approval does not loosen the edit.

**Speaker.** On any recording with someone off camera (a host, a coach, a producer reading
questions), a hook or a body in that person's voice is a defect. Watch for the classic trap: the
cleanest-sounding version of a line is often the host reading it *to* the guest, a few seconds
before the guest says it themselves. Always take the guest's own delivery, and its time. Work
from the on-camera transcript and the trap cannot happen, because the host is not in that file.

## Gate 2: the first frame (only a person can pass it)

People decide to stay or swipe on the first frame and the first second: the picture, the words on
screen, and the sound together. A sentence that reads well on paper is not enough.

Before a passage goes on the cut list, say what its first frame is:

- **The picture.** Who or what is on screen, and is it worth a glance?
- **The on-screen text.** Three to seven words. The words a viewer with the sound off reads
  before hearing anything. It names the subject and leaves the question open.
- **The sound.** Does the first word land immediately, or is there a breath and a false start?

If you cannot describe a first frame that would stop someone, the passage does not ship, no
matter how good the sentence is.

On-screen text has no room for a qualifier, so claims stay out of it: no doses, no promised
results, no bare numbers for a regulated brand. "Your loaf is not broken" is fine. "Fix dense
bread in one day" is a promise.

## The six questions

Ask these of every passage that clears both gates. Write one line of evidence for each. Then
choose by judgement. Do not add the answers up: a total looks precise and means nothing.

| # | Question | What a yes looks like |
|---|---|---|
| 1 | Does the opening two seconds earn the next ten? | A number or a flat statement that contradicts what the viewer believes, or names a worry they already have |
| 2 | Does it stand alone? | Someone who saw nothing else understands it, with at most one line of on-screen setup |
| 3 | Is it worth a second watch? | Dense enough, or with a turn in it, that a viewer loops it or sends it |
| 4 | Does the reward arrive in time? | The payoff comes before the viewer would leave. Shorter clip, earlier payoff |
| 5 | Does it make you feel something? | Surprise, relief, recognition, a small shock. Felt, not just understood |
| 6 | Does it serve the brand's goal? | The right viewer takes the next step (books, visits, asks). Reach from the wrong viewers does not count |

If two people score the same passage and disagree badly, the passage is not the problem. The
question was read two ways. Talk about it and tighten the wording for next time.

**What is not on the list: whether it can be cut cleanly.** That is not a judgement from text.
It is checked on the video: a clean in and out, nobody talking over the line, the speaker in
frame, the better of two takes.

## One idea per clip

A **body** is one self-contained idea: a single question answered, a single mistake explained, a
single story told. If a passage needs a second idea to make sense, it is two clips or none.

A quick test: can you name the body in five words? "Why loaves come out dense" is a body.
"Proofing, flour and ovens" is three.

## The buried lead and the cold open

People rarely say their best sentence first. In conversation the strong line usually arrives in
the middle of an answer, after the warm-up. That line is the **buried lead**.

To find the hook for a body, weigh three candidates:

1. the sentence the body naturally opens with,
2. the payoff line in the middle,
3. any line that comes at the idea from a different angle.

Pick the strongest. If it already opens the body, the clip is simply the body. If it sits
elsewhere, lift it to the front: the clip is the hook, a hard cut, then the whole body. The
viewer hears the line again when the body reaches it. That is intended; it lands as a callback.
This is a **cold open**.

Invented example, from a baker being interviewed:

> *Natural opening:* "Most dense loaves are simply underproofed."
> *Buried in the middle:* "Watch the dough, not the clock."
>
> The second line is shorter, stranger and quotable. Lift it. The clip opens on "Watch the dough,
> not the clock", cuts hard, and then the body explains why loaves come out dense and arrives
> back at the same line.

**A cold open is a tool, not a rule.** Lift a line only when all three of these hold:

| Test | Why |
|---|---|
| The body still holds a second, larger reward the hook does not give away (the mechanism, the story, the number) | If the hook IS the whole point, opening on it closes the loop in two seconds and the viewer leaves. Keep that kind of line in place and let the body build to it |
| The line stands up by itself at the very start | No "it", "that" or "he" pointing at something the viewer has not heard yet |
| Lifting it does not strip a qualifier | If the sentence before it said "alongside your physio's plan", and the lift loses that, the clip now makes a claim the speaker never made. For any held line, this test is absolute |

Invented example of the first test failing: a physiotherapist says "Most runner's knee starts at
the hip." If the body is only that sentence restated twice, there is nothing left to stay for.
Leave it where it is, and open instead on the question it answers.

Several good hooks for one body are fine: each becomes its own clip, and the body is only cut
once. But one strong hook beats three passable ones. Add a second only when it is clearly
different and clearly as good.

## Writing it down: the cut list

The cut list is the brief for everything after it. It has a fixed shape (the `check-cut-list`
tool enforces it):

- **It opens with a reference block**: which recording, which brand, the exact video file the
  times belong to, where the times came from, and the offset if the clips are cut from a
  different file than the one that was transcribed. Times against a file nobody has are useless.
- **Bodies, each with its hooks.** Every hook is quoted exactly as the transcript has it,
  mishearings included. Put a correction in [square brackets]; never quietly fix the quote.
- **The first and last words of each body, quoted.** The cutter lines up on these words, not on
  the times, because times drift and words do not. Quote five or six words, and do not start or
  end a quote on a number: numbers are transcribed differently every time.
- **On-screen text**, three to seven words, one per body.
- **The lower-third**: the speaker's name and credential exactly as the brand wrote it. A
  credential is a claim, so it is never invented.
- **The gate** for each body: SHIP, HOLD or DROP.

## What this method does not know

- None of this has been proven to predict how a clip performs. It is a way of not shipping bad
  clips and of looking in the right places, not a way of forecasting winners.
- The finder's signals come from text. It cannot see a great facial expression, a prop, or a
  moment of silence that works. Watch the recording as well as reading it.
- With a subtitle-file transcript there are no voice labels, so the speaker check is unverified
  and has to be done by ear.
- The only real test is publishing and reading the results for your own audience. When you have
  those numbers, trust them over this page.
