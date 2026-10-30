# YouTube packaging: from a topic to a video worth making

> last_researched: 2026-06-11 (as of June 2026). Confidence: medium
> This is the METHOD for one long video: decide it is worth making, title it, picture it, open
> it, lay it out, ask for one thing, describe it. How the platform treats long videos is in
> `youtube-longform.md`. Opening lines are in `hooks.md`. Support decks are in `slide-decks.md`.
> This file does not repeat them. Every example is invented, for the two fictional brands in
> `README.md`. No title here is, or is adapted from, a real video's title.

## The order, and why it is this order

**Package before you script. Script before you film.** Most videos fail before the camera is on,
because nobody decided what would make a stranger click and stay. So the work runs in this order,
and each step is a step in the tool (`factory.py youtube ...`):

| # | Step | What you end up with | Tool step |
|---|---|---|---|
| 1 | Is it worth making? | make, reshape or drop, and where the viewer is | `new`, plus a demand check |
| 2 | Titles | three to five options from patterns, one chosen | `titles` |
| 3 | Thumbnail | two or three concepts drawn, looked at small, one chosen | `thumbnail` |
| 4 | The first 30 seconds | the promise, what is said, what is shown, the text on screen | `set --hook` |
| 5 | Structure | a skeleton, a length, named parts, planned chapters | `set --structure` |
| 6 | The ask | one ask, matched to the viewer, from the brand's own offers | `set --stage` |
| 7 | Description | the question, the short answer, chapters, hashtags | `set --description`, `check` |
| 8 | Script, deck, teleprompter | the person's own words, slides that show, a clean read | `teleprompter`, `deck` |

Everything for one video lives in one folder inside the brand, with a record (`brief.json`) and a
page a person can read (`brief.md`). `check` reads the whole package against the brand's rules and
facts and says what is wrong in sentences.

**One promise, three places.** The title, the thumbnail and the first 30 seconds make the same
promise. If they do not, fix the package, not the edit.

**The law over all of it: do not invent. Reuse what is proven as a PATTERN, never as someone's
words.** A sentence shape is free to everyone. A title, a line, a thumbnail idea or a story that
belongs to somebody else is not yours to reuse, and a number that is not in the brand's files is
not yours to state.

## 1. Is the idea worth making?

Decide before anything is written. Four questions, answered honestly:

1. **Does anyone already ask this?** Look in the brand's own files first: `Brand/audience.md`
   ("Questions they really ask"), the question slate if there is one (section 9), comments and
   messages. A topic nobody has asked about needs a very good reason.
2. **Would a stranger get something from it with no background?** Assume every video is
   somebody's first from this brand. If it only makes sense to regulars, it is a post, not a video.
3. **Can you already see the title and the thumbnail?** If you cannot picture how it would be
   offered to a stranger, the idea is not ready. Reshape it until you can, or drop it.
4. **Do several wordings lead to it?** People asking the same thing in different words, or two or
   three neighbouring questions, mean real and lasting interest. One odd phrase on its own is a guess.

Then a **demand check**, if the research key is set up (`factory.py research youtube`, see the
research skill). It answers one thing: are RECENT videos on this subject being watched, or only
old ones? "Alive" means there is room. "Stale" means look for a fresher angle. Small channels
winning on the subject is the best sign of all: the topic pulled the views, not the audience.
Demand moves, so check when the video is planned, not months before.

**With no research key this step is skipped, and the record says so.** That is allowed. It means
nobody knows whether the subject is alive, so lean harder on question 1.

Last, say **where the viewer is** (it decides the ask in section 6): learning the subject,
comparing ways to solve it, or ready to choose.

| Verdict | When |
|---|---|
| Make | Asked for, clear to a stranger, picturable, reached by several wordings |
| Reshape | The subject is right and the angle is not: too broad, too inside, no picture |
| Drop | Nobody asks, or the brand has nothing of its own to show |

## 2. Titles, by pattern

Write three to five options **from different patterns**, then choose. A pattern is a sentence
shape with slots. The slots are filled from the brand's own material. If a slot needs a number and
the brand has no real one, pick another pattern.

A title does one of three jobs, and the job sets the rules.

### Search: someone typed a question

| Pattern | Shape | Bakery | Clinic |
|---|---|---|---|
| The question, as typed | `[the search phrase] ([what they get, or who it is for])` | "How do I know when dough has proofed enough? (The poke test, filmed)" | "Should I run with sore shins? (What I check first)" |
| The whole subject, in one place | `[subject], from [the first step] to [the last] ([who it is for])` | "Your first sourdough loaf, from flour to slicing (no mixer needed)" | "Back from a calf strain, from day one to your first 5K" |
| The subject, with a clock on it | `[subject] in [N] minutes ([who it is for])` | "Dough hydration in 6 minutes (for new bakers)" | "Training load in 7 minutes (for weekend runners)" |
| The counted answer | `The [N] [reasons / checks / signs] behind [the outcome]` | "The 4 reasons behind a tight crumb" | "The 3 diary habits behind most sore knees" |
| What it really costs, or how long | `How [much / long] [the thing] really [costs / takes] ([what the figures rest on])` | "How long sourdough really takes (our 18 hour schedule)" | "How long a calf strain really takes to settle (what I tell runners)" |

**The keep-the-keyword rule.** When a video is made to be found for a search phrase, that phrase
survives in the title as one unbroken run of words. Add words before it and after it. Change
capitals and the punctuation around it. Never reorder it, reword it or put a word in the middle
of it, however clumsy it reads. People find the video because of that exact wording. Tidying it
throws the match away. The tool refuses a title that breaks this, and says which words moved.

**An addition in brackets is a promise.** The phrase does the finding. The few words in brackets
after it earn the click: who it is for, what they get ("3 causes, one fix each"), how it is shown
("filmed at the bench"), something held back ("and the step most people skip"), a running time
("in under 8 minutes"). Write the addition last, from the script. If it promises three, the video
has exactly three. If it promises eight minutes, the video is not nine. The tool compares both
with the plan.

### Browse: nobody searched, so the title has to open a gap

| Pattern | Shape | Bakery | Clinic |
|---|---|---|---|
| The belief, corrected | `Why [common advice] [makes it worse] (and what to do instead)` | "Why kneading harder makes a worse loaf (and what we do instead)" | "Why resting a sore shin for a month often brings it back" |
| The warning | `Stop [the habit] before [the cost they already feel]` | "Stop putting your starter in the fridge before you read this" | "Stop adding miles the week after a race" |
| The outcome, in the viewer's words | `[the result they want], without [the thing they dread]` | "A crisp crust at home, without a special oven" | "Run three times a week, without the Monday limp" |
| What changed, explained calmly | `[what changed] [where]: what it means for [who]` | "Flour prices went up again: what it means for your weekly loaf" | "The park path is closed till spring: three flat loops that still work" |
| Two things, side by side | `[A] vs [B]: [how they are judged]` | "Cold oven vs hot oven: same dough, cut open" | "Treadmill vs pavement: what changes in the same runner" |

### Proof: the brand's own experience is the reason to click

These need real evidence on file: a number that traces, a case with permission.

| Pattern | Shape | Bakery | Clinic |
|---|---|---|---|
| What a count of experience taught | `I have [taught / assessed] [N] [things]. [The pattern]` | "We teach 8 beginners every Saturday. They all make the same first mistake" | "What a runner's first appointment usually tells me" |
| A test, run over time | `I [did one thing] for [N days]. [What you will see]` | "I fed one starter rye and one white for 12 days. Here are both loaves" | "I filmed one runner's stride every week for 8 weeks" |
| One real case, before to after | `How [someone, described not named] went from [before] to [after]` | "How one class regular went from bricks to an open crumb" | "How one runner's week changed before her knee did" |
| Looking back, what I would do first | `What I would [do / buy / skip] first if I were [starting] today` | "What I would buy last if I were opening a bakery today" | "What I would do in month one if I took up running at 40" |
| With what you already have | `How to [outcome] with [the thing they think rules them out]` | "How to bake a good loaf with a cheap oven and no scales" | "How to start running when a flight of stairs leaves you winded" |

`hooks.md` ("YouTube titles") walks through four of these shapes in more detail.
`factory.py youtube titles --brand <id> --patterns` prints the whole library with when to use each
and when not to.

### Limits, and what the score measures

- **Length.** YouTube accepts 100 characters. About 50 show in full on a phone, and past about 60
  the end is cut off nearly everywhere. Put what matters first.
- **One word in capitals, at most.** Exact numbers beat round ones. Never a number that is not on file.
- **Say the subject.** A promise of a shock with the subject hidden pulls the wrong viewers, and
  the platform measures how they feel afterwards.
- **A year in a title** helps while it is current and ages the video the day it is not.
- **A regulated brand** titles the demonstration, never the outcome. "What I check first" is a
  title. A promise of a result is not. The brand's own never-publish terms stop a title outright.

The score is out of 100 and you can see every point: length (25), the search phrase kept and
finished early (25), a gap worth closing (25), being specific (25), with points off for anything
that reads as bait. With no search phrase, its share goes to the other two. **The score sorts the
options. A person chooses.**

## 3. The thumbnail: a three-second read

A thumbnail is met at the size of a stamp, for a moment, beside a dozen others. Build it to be
UNDERSTOOD at that size. A beautiful picture that needs a second look has already lost.

**One subject. Three to five words. One contrast.**

- **One subject:** one face or one object, large. The cut loaf. The worn shoe held sole up.
- **Three to five words,** or none. They finish the picture. They never repeat the title: the two
  are read together, so the thumbnail says what the title does not. Title: "How do I know when
  dough has proofed enough?" Thumbnail: "Looked ready. Was not."
- **One contrast:** light on dark, one colour against the rest, two things side by side. One.

Decide the thumbnail **before filming**, because the first seconds of the video have to show the
viewer what the thumbnail promised (see "Agreement" in `youtube-longform.md`).

| Layout the tool draws | Use it when |
|---|---|
| `words` | The words are the picture. No photo needed |
| `photo-right`, `photo-left` | The brand has a real photo of the subject. Used as it is, no cut-out needed |
| `photo-full` | One strong photo, edge to edge, words over its darkened side |
| `versus` | A comparison. A word or two on each side |
| `number` | One figure carries it. The figure has to trace to the brand's facts |

**Photos are the brand's own,** from its brand kit's photos folder. The Factory never generates a
picture, and never a person. A real, slightly rough photo of the real thing beats anything staged.

**Draw two or three that are really different, then look at them small.** The tool saves each one
at 320 pixels wide and measures it there: the words must stand out at least 4.5 to 1 from what is
behind them, and the smallest line must be at least 12 pixels tall. That catches faint and tiny.
Only your eyes catch confusing, so open the small copies and look. Then let YouTube's own test
choose between the finalists (it picks by watch time, not by clicks).

Keep the bottom right corner clear: the running time is drawn there. Use the same colours and
lettering every time, so a regular viewer knows the video is yours before reading a word.

## 4. The first 30 seconds

How an opening earns the watch is covered in `youtube-longform.md` (section 2) and the spoken,
visual and on-screen patterns are in `hooks.md` (Part 2). What packaging adds is a checklist of
the four jobs the opening has to do, in this order, inside half a minute:

| Job | What it means | Bakery | Clinic |
|---|---|---|---|
| Show the payoff | The viewer sees what the thumbnail showed them | The dense loaf, cut open, held to the lens | The runner mid-stride, a line drawn at the hip |
| Say why it matters | The cost of not knowing, in their terms | "It is the difference between this loaf and a brick." | "Guess wrong and a two week niggle becomes a two month one." |
| Say what they leave with | One sentence, concrete | "By the end you can tell with one finger whether dough is ready." | "By the end you will know which shin pain can be run on." |
| Say the route | How many parts, and which one is worth waiting for | "Three checks. The third is the one most people get backwards." | "Two tests you can do at home, then the one sign that means stop." |

Then deliver the first useful thing before the 30 second mark. Credibility is one line, earned by
showing ("these three loaves are from Saturday's class"), never a biography. A regulated brand
demonstrates and explains. It does not promise an outcome.

The record holds the opening as four fields (promise, say, show, on screen) so they can be checked
against each other and against the thumbnail.

## 5. Structure, as shares of the running time

The four skeletons are described in `youtube-longform.md` (section 3). The tool holds the same
four as DATA: each segment has a **share of the running time**, so one skeleton stretches to any
length, and the planned chapters fall out of it.

| Skeleton | Length | Segments and their shares |
|---|---|---|
| `straight-answer` | 5 to 8 min | the question 4, the short answer 12, the full answer 60 (2 to 4 parts), the common mistake 14, what next 10 |
| `worked-example` | 10 to 15 min | the outcome 3, why it matters 6, where it started 10, the changes 55 (3 to 5 parts), the fault that mattered most 15, who it works for 11 |
| `live-test` | 8 to 12 min | the question 4, the method 8, the rounds 60 (2 to 5 parts), what it means 20, what next 8 |
| `countdown` | 8 to 12 min | the pattern 3, what is coming 4, the mistakes 75 (3 to 7 parts), which to fix first 10, one ask 8 |

Rules that hold in all four:

- **The counted parts are the title's promise.** "The 4 reasons" means four parts. The check compares them.
- **One idea per part,** and each part is named as a question or a claim, because those names become the chapters.
- **Hold the most valuable part back** and say early that it is coming.
- **At about half way, win the viewer back:** say what the next part settles and why it outweighs the last.
- **Length comes from the words.** A relaxed talking pace is about 150 words a minute. A seven
  minute video is about a thousand words. The tool estimates the running time from the script and
  tells you when it is far from the plan.

## 6. The ask, by stage

One business ask per video. Where the viewer is decides how direct it may be.

| The viewer is | The ask | Early | Midway | At the close |
|---|---|---|---|---|
| **Learning** the subject | Something that costs nothing and teaches more | None. Earn the right first | At most one passing mention, straight after something useful | The next video. An offer only if it is free and helps them learn |
| **Comparing** ways to solve it | The offer that lets them try the brand with little risk | One sentence that it exists, then back to the subject | Name it inside the section where it is the natural tool | What it is, who it suits, who it does not, where the link is |
| **Ready** to choose | The brand's main offer, said directly | Say the video ends with how to start | Answer price or time with real figures from the brand's files | The direct ask, once |

- **The ask comes only from the brand's own offers** (`Brand/pillars-and-offers.md`, the settings
  file). The tool refuses an offer the brand does not have. A brand with no offers closes on the
  next video.
- **The best ask is the next step of what was just taught.** A video on the poke test ends on the
  Saturday class where people do it with their own hands. Taking the offer should feel like
  carrying on, not like being sold to.
- **The link goes in the first two lines of the description.** The spoken close is "watch this
  next".
- **Build a small cluster:** one whole-subject video, and several straight answers that each point
  to it and to each other. Viewers who watch a second video are the ones who come back.

## 7. The description, with chapters

A description is a search surface, not a caption. It has a fixed order:

1. **Line 1:** the question the video answers. When there is a search phrase, it is here word for
   word, inside the first 150 characters.
2. **Line 2:** the one link that goes with the ask.
3. **The short answer,** written out: 40 to 80 words a person could read aloud.
4. **Chapters.**
5. **Other wordings** of the question that the video also answers (the question slate supplies them).
6. **Who is speaking,** and the brand's standing disclaimer when it is a regulated business.
7. **Three to five hashtags.** Past 60 the platform ignores them all.

**Chapter rules** (the platform's, as of June 2026): the list starts at `00:00`, has at least
three entries, runs in rising order, and no chapter is shorter than ten seconds. Break one and no
chapters show at all, with no warning. Write times as `00:00`, and `1:02:03` past the hour. Name
each chapter for what the viewer gets there ("Why a clock cannot tell you"), never for its
position ("Part 2").

Chapters are planned from the structure before filming, then replaced with the real times from
the edit. Every number in a description traces to the brand's facts, like anywhere else.

## 8. Script, deck, teleprompter

- **The script is the person's own words, tidied for speaking.** They talk the subject through (a
  recording, a voice note, answers in the conversation). The script is that, with repeats removed,
  the order fixed and sentences short enough to say in one breath. Nothing is added that they did
  not say. Every fact carries a `Source:` line into the brand's files.
- **Say the search phrase aloud early.** The platform reads what is spoken.
- **A support deck** is optional. It is the show, never the script: see `slide-decks.md`.
- **The teleprompter** holds only what is said, in short lines. It is made from the script and
  never edited by hand. Change the script, make it again.

## 9. Starting from keyword exports: the question slate

A keyword tool (any of them) exports thousands of phrases. Most are the same few questions in
different words. `factory.py youtube questions build` turns the exports a person supplies into a
slate they can rule on in one sitting:

- phrases that ask the same thing become **one video**, which then answers every one of those wordings
- each group gets a tier: **film**, **batch** (several in one sitting), **text** (answer it in
  writing, never film it) or **parked** (flagged, with the reason showing)
- the person opens one review page, approves, parks, or gives a phrase its own video
- approved groups become video folders with the search phrase locked in

The phrase is never edited, at any step. A phrase too broken to say aloud ("what does proofing")
keeps its written form for the title and gets a repaired spoken form for the camera. The brand's
never-mention names and never-publish terms park a group whatever anyone clicks.

## 10. After it is published: when to change the packaging

- **First week: leave it alone.** A dip in the click rate as the video reaches colder viewers is
  what growth looks like.
- **After that, judge by impressions, not click rate.**
  - Impressions still rising: leave it.
  - Impressions flat, and the people who click stay: the video is good and the package is weak.
    Change the title or the thumbnail, make it a real change, re-match the opening if needed, then
    wait again.
  - Impressions flat, and the people who click leave early: it is the idea or the structure.
    Learn from it and fix the next video. Stop re-dressing this one.

This is working guidance from people who make videos, not a rule the platform has published.

## 11. Honest caveats

What nobody outside the platform really knows, and how to hold the advice above:

1. **Nobody outside YouTube knows the weights.** The platform has described the direction (find
   videos each viewer will choose and be satisfied by). Everything more precise than that is
   inference, including in this file.
2. **Most public advice was learned on entertainment channels with very large audiences.** A
   business channel that trades on trust should take it carefully. Frantic cutting, shock faces, no
   word of who you are, and reach for its own sake can all cost a small expert channel the viewers
   it wants. Pace for clarity. One line of credibility early is fine. The right hundred viewers
   beat the wrong ten thousand.
3. **"Search is dead, chase the home page" is advice for entertainers.** For a business that
   answers questions, the person who typed the question is the best viewer there is. Build for
   search and for suggestion both. Search builds slowly: judge it over months.
4. **Patterns describe what has worked. They do not predict.** A pattern is a starting shape. The
   score is a sorting aid. Neither has seen your audience.
5. **The figures are soft.** Character counts, the 150 words a minute, the first week rule: craft
   and vendor numbers. Trust the direction. Check the exact value against your own analytics.
6. **Words on a thumbnail are not always better.** Draw one with and one without, and test.
7. **A keyword tool's volumes are estimates,** and a demand verdict is a photograph of one week.
   Re-check when the video is actually planned.
8. **Your own channel is the only real evidence.** Change one thing at a time and watch what your
   viewers do.

## Applying this to your brand

| You need | Read |
|---|---|
| The questions people really ask | `Brand/audience.md`, the question slate in `Strategy/youtube-questions/` |
| Facts and figures you may state | `Studio/facts.json`, `Inputs/Research/`, the proof library |
| What you sell, in your own words | `Brand/pillars-and-offers.md` |
| How the presenter talks | `Brand/brand-voice.md`, `Brand/voice-samples.md`, their recordings |
| Colours, lettering, photos | `Brand/brand-kit/` |
| Names never to mention, terms never to publish, the standing disclaimer | the brand's settings |
