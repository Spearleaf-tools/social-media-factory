---
name: youtube-video
description: Package a long-form YouTube video for a brand, from the topic to the teleprompter. Use when the person says "make a YouTube video", "I want to do a video about ...", "package this video", "write me YouTube titles", "is this title any good", "make a thumbnail", "make slides for my video", "write the description and chapters", "make my teleprompter", "which videos should I make", or hands over a keyword export and asks what to film. Works through a fixed order: is the idea worth making, three to five titles from patterns, thumbnail concepts drawn and looked at small, the first 30 seconds, the structure, the ask, the script in the person's own words, an optional slide deck, the teleprompter, the description with chapters. Everything lands in one folder per video inside the brand. Never invents a fact, a number, a customer or a line, and never reuses someone else's title or words.
---

# YouTube video

You are packaging ONE long video, in a fixed order, with the person making every choice that
matters. You run every tool. They never type a command.

## The law

**Do not invent. Reuse what is proven as a PATTERN, never as someone's words.**

- A sentence shape is free to everyone. A title, a line, a thumbnail idea or a story that belongs
  to somebody else is not reused, adapted or "inspired by". Research shows which STRUCTURES are
  working. You write new words, on this brand's own subject.
- Every fact, number, customer and result comes from the brand's own files or from what the
  person tells you in this conversation. A number that does not trace is recorded as a fact with
  its source first, or it comes out.
- The words spoken on camera are the PERSON'S words. You tidy them. You do not write them.

Read `playbooks/youtube-packaging.md` before your first video (it is the method), and
`playbooks/youtube-longform.md` for how the platform treats long videos. Openings are in
`playbooks/hooks.md`. Decks are in `playbooks/slide-decks.md`.

Always name the brand. If more than one exists and you are not sure which, ask. Everything below
is free and runs on this computer, except the demand check in step 2.

## 1. The topic

Ask: **"What is the video about, and where does that come from?"** A topic comes from one of three places:

- **The brand's approved topics** (the `plan-content` skill owns them):
  `factory.py youtube new --brand <id> --topic-id <topic id> --identity <who presents>`
  (add `--run <run>` when the topic lives in a planning run). Only an approved topic becomes a video.
- **A question slate** built from keyword exports (see "Which videos should I make?" below).
- **The person**, in their own words:
  `factory.py youtube new --brand <id> --topic "<the subject>" --identity <who presents> --source-ref "<where in their material>"`

If the video is meant to be found for a search phrase, add `--keyword "<the phrase, exactly as
people type it>"`. **That phrase is never reworded from here on,** however clumsy it reads.

Add `--stage learning`, `comparing` or `ready`: where the viewer is. It decides the ask in step 6.

Then ask the four questions from the playbook (does anyone ask this, would a stranger get it, can
you picture the title and thumbnail, do several wordings lead to it) and say plainly: make,
reshape or drop. Dropping a weak idea is a good outcome.

## 2. Is there demand?

`factory.py status` tells you whether the research key (`APIFY_API_TOKEN`) is there. **Never open
the keys file and never ask for the key in the chat.**

- **Key present:** use the **research** skill's `youtube --keyword` job (two steps: show the
  price, get a yes, then run). Read the verdict with them: "alive" means recent videos are being
  watched; "stale" means only old ones are. Then record it:
  `factory.py youtube set --brand <id> --video <id> --demand-run "<the run's folder>"`
- **No key:** say so, once, plainly: "I can't check whether people are watching recent videos on
  this, because that needs the research key. We can still make it. It just means we are trusting
  that your customers really ask this." The record notes that the step was skipped. Carry on.

Look at winning titles for their STRUCTURE only (a question, a count, something in brackets).
Count which structures repeat. Never reuse a title.

## 3. Titles: three to five, they pick

`factory.py youtube titles --brand <id> --patterns` prints the pattern library: the shape, when
to use it, when not to, what it needs. Pick patterns the brand's material can fill **honestly**.
If a pattern needs a number and they have no real one, choose another pattern.

Write three to five, from different patterns, and add each one:

    factory.py youtube titles --brand <id> --video <id> --add "<the title>" --pattern <pattern id>
    factory.py youtube titles --brand <id> --video <id> --from-keyword --tail "<a few words in brackets>"

The second form builds the title around the search phrase without touching it. A title is refused,
with the reason, when it rewords the search phrase, states a number that does not trace, names
someone on the never-mention list, uses a term the brand must never publish, or promises a
running time or a count the plan does not deliver. Fix the cause. Do not argue with the check.

Show them the options with their scores and say what each score is made of (length, the search
phrase, a gap worth closing, being specific). **The score sorts. They choose:**
`factory.py youtube titles --brand <id> --video <id> --choose <number>`

## 4. Thumbnails: draw two or three, LOOK at them small, they pick

One subject, three to five words, one contrast. The words ADD to the title; they never repeat it.
Write two or three concepts that are really different, as a JSON list in `.factory/tmp/`:

```json
[{"name": "a", "layout": "words", "text": "Looked ready.\nWas not.", "accent": "not"},
 {"name": "b", "layout": "photo-right", "text": "Poke it first", "photo": "Brand/brand-kit/photos/dense-loaf.jpg"}]
```

Layouts: `words`, `photo-right`, `photo-left`, `photo-full`, `versus`, `number`. The full field
list is at the top of `smf/youtube/thumbnail.py`. **A photo always comes from the brand's own
photos folder,** used as it is. That folder can hold their own photos, stock photos filed there,
and images generated with their own OpenAI key (the **make-visuals** skill, "Pictures inside a
free design", has the steps and the cost). If the person asks for a generated person, make it,
unless they have said this brand does not want generated people. With no photos at all, use
`words`, `versus` or `number`.

`factory.py youtube thumbnail --brand <id> --video <id> --spec <file>`

It draws each one at full size and at 320 pixels wide, and measures the small one: do the words
stand out, are they tall enough. **Then open the small copies and actually look.** Is the subject
obvious in one second? Do the words read? Would it stand out beside a dozen others? Fix the spec
and draw again if not. Show the person the finalists and let them choose:
`factory.py youtube thumbnail --brand <id> --video <id> --choose <name>`

Tell them YouTube can test up to three thumbnails against each other and picks by watch time.

## 5. The first 30 seconds, and the structure

**The opening.** Four fields, saved as a small JSON file: `promise`, `say`, `show`, `on_screen`.
Within 30 seconds the viewer must be looking at what the thumbnail showed them. It does four
jobs, in order: show the payoff, say why it matters, say what they leave with, say the route.
Patterns are in `playbooks/hooks.md`. No greeting, no biography, no "in this video".

**The structure.** Pick a skeleton and a length, and name the counted parts as questions or claims
(they become the chapters):

    factory.py youtube set --brand <id> --video <id> --hook <file> --structure straight-answer --minutes 7 --parts "Why a clock cannot tell you|The poke test, step by step|When the test misleads you"

Skeletons: `straight-answer` (a searched question), `worked-example` (a real case), `live-test`
(seeing is believing), `countdown` (mistakes you have watched many times). If the title promises
"The 4 reasons", there are four parts.

## 6. The ask

One ask per video, matched to where the viewer is, from the brand's OWN offers:

    factory.py youtube set --brand <id> --video <id> --stage comparing --offer <offer id>

`learning`: no offer needed, close on the next video. `comparing`: the low-risk offer.
`ready`: the main offer, said directly. An offer the brand does not have is refused. If they have
none, close on the next video and suggest adding an offer with **onboard-brand**.

## 7. The script: their words, refined for speaking

**Get them talking.** Ask them to talk the video through: a voice note, a recording, or answers
here, part by part. Use their recordings and `Brand/voice-samples.md`. Then:

1. `factory.py youtube teleprompter --brand <id> --video <id> --starter` writes an empty
   `script.md` laid out from the structure. Every spoken line in it is a TODO on purpose.
2. Fill it from what they SAID. Remove repeats, fix the order, shorten sentences until each can
   be said in one breath. **Add nothing they did not say.** If a part is thin, ask them; do not pad it.
3. Each section has `Say:` (spoken), `Show:` (what the viewer sees) and, for any fact, `Source:`
   pointing into the brand's files (`fact:<id>`, `proof:<id>`, a file). If a number is true and
   not on file: `factory.py facts add --brand <id> ...` first.
4. Say the search phrase aloud in the opening, in the words people type.

## 8. A slide deck, if they want one

Ask. Many talking videos are better with one. **A deck is the show, never the script:** each
slide backs the speaker up with one thing the eye takes in without effort. Read `playbooks/slide-decks.md`.
`factory.py youtube deck --brand <id> --types` lists the kinds of slide and how much each holds.
Write the spec as JSON, one slide per point the speaker makes, then:

    factory.py youtube deck --brand <id> --video <id> --spec <file>

It refuses, naming the slide, anything over its word limit, any production note (a timecode,
"B-roll", brackets), any slide that repeats a spoken line, and any number with no source. It
writes every slide as a picture, one PDF, and a contact sheet. **Open the contact sheet and
look:** read the headings top to bottom (the argument should hold with nobody talking), find the
crowded slide and the empty one, fix the spec, draw again. Tell them about anything reported as unverified.

## 9. The teleprompter

`factory.py youtube teleprompter --brand <id> --video <id>`

It checks the script first (a TODO left in, a number that does not trace, a never-mention name, a
greeting for an opening, a running time far from the plan), then writes `teleprompter.txt`: only
what is said, in short lines. It is made from the script and never edited by hand. If they
change a line, change the script and make it again.

## 10. The description, with chapters

Save a small JSON file: `answer` (the short answer, 40 to 80 words, from the script), optional
`opening`, `also_answers`, and three to five `hashtags`. Then:

    factory.py youtube set --brand <id> --video <id> --description <file> --tags "a, b, c"
    factory.py youtube check --brand <id> --video <id> --final

The description is laid out in a fixed order: the question (the search phrase word for word), the
link for the ask, the short answer, the chapters, other wordings, who is speaking, the brand's
disclaimer when it is a regulated business, the hashtags. Chapters are planned from the structure.
**After the edit, replace them with the real times** (a text file of lines like `00:00 The
question`): `--chapters <file>`. The first is always `00:00`, there are at least three, and none is
under ten seconds, or YouTube shows none at all.

When `check --final` is clean: `factory.py youtube status --brand <id> --video <id> --set packaged`
(then `scripted` once the teleprompter is made, `filmed`, `published`).

## Telling them where things are

Everything for the video is "in the youtube folder inside your brand's Output folder, in a folder
named for the video". `brief.md` there is the whole package on one page. Lead with what it means:
"The title keeps the exact question people type. The thumbnail says the part the title doesn't.
Your script runs about seven minutes." Never paste tool output at them.

## Which videos should I make? (keyword exports)

If they have a keyword export from any tool (a CSV), it becomes a slate:

1. `factory.py youtube questions build --brand <id> --file "<export.csv>"` (repeat `--file` for more).
   Phrases asking the same thing are grouped into one video. Each group is tiered: **film**,
   **batch** (several in one sitting), **text** (answer in writing, never film) or **parked**
   (flagged, with the reason). The search phrase is never edited, at any step.
2. Tell them to open the review page ("in your brand's Strategy folder, under youtube-questions"),
   approve, park, or give a phrase its own video, then press **Save decisions to a file** and tell
   you where it saved.
3. `factory.py youtube questions apply --brand <id> --decisions "<that file>"`
4. `factory.py youtube questions briefs --brand <id> --tier film --identity <who presents>`
   starts a video folder for each approved group, with the search phrase locked in. Then package
   each one from step 2 above.

Optional, with the research key: run the research skill's `serp` job on the top few phrases, then
`factory.py youtube questions enrich --brand <id> --run "<that run's folder>"`. It records where a
video already shows on the results page, and suggests a split when two phrases in one group bring
up different pages.

Brand tuning (words that mean the same thing in their trade, words that are not their subject)
goes in `Strategy/youtube-questions/settings.json`; the top of `smf/youtube/questions.py` shows the shape.

## What good looks like

The idea was checked before anything was written. The title keeps the viewer's own words and makes
a promise the video keeps. The thumbnail reads at the size of a stamp and says something the title
does not. Every number has a source on file. The script sounds like them. Nothing in it belongs to
anyone else.
