---
name: talking-points
description: Prepare someone to talk about a subject on camera, on a podcast or on stage, with points they can say out loud and numbers they can stand behind. Use when the person says "talking points on X", "prep me for a podcast", "prep me for an interview about X", "what should I say about X", "make me a run-sheet", "I'm recording tomorrow about X", or hands over a subject and wants speakable points. Needs no key and costs nothing: you do the research yourself with your own web tools. Built around the brand: its pillars, its audience and its own point of view. Every number carries a named source and a link. Saves one run-sheet in the brand's Strategy folder. It does not write posts.
---

# Talking points

The goal: a single page the person can glance at while recording. Each point is something they
can say in their own voice, that matters to THEIR audience, with figures they could defend if
challenged.

No key is needed. You do the digging with your own web search and page-reading tools.

## What this is not

- Not finished posts or scripts. That is `write-posts` and `write-scripts`. Offer them afterwards.
- Not a report to read. If it cannot be said aloud in a breath or two, it is too long.
- Not a place to give the brand opinions it does not hold. See step 4.

## 1. Start from the brand, not from the news

Name the brand. If there is more than one and you are unsure, ask.

Read the brand's settings and its files in the Brand folder before searching for anything:

- **its pillars**: the few subjects it wants to be known for
- **its audience**: who they are, what is in their way, the questions they really ask
- **how it sounds**: its own voice samples
- **its rules**: anyone never to be named, and whether it works in a regulated field

Then ask, one at a time, offering a default each time:

1. "What's the subject?" (required)
2. "Where will you be saying this, and to whom?" (default: the brand's usual audience)
3. "How many points?" (default: six to eight)

## 2. Research: go to where the number was born

For each angle, search, then **open the pages and read them**. A search snippet is not a source.

Prefer, in this order:

1. **The original**: the study, the survey, the official figures, the company's own announcement.
2. **Specialist trade press** that names and links the original.
3. General news, only when it links to the original.

Avoid roundup pages ("87 statistics about..."). They copy each other, drop the dates and often
mangle the figure. If a roundup is the only place a number appears, either follow its link back
to the original or treat the number as unconfirmed.

For every figure, note five things while the page is open:

- the number **exactly as written** (never rounded, never converted)
- what it measures, in whom, and how many people or cases
- who published it
- when (a year at least)
- the link to the page where you saw it

## 3. Keep a point only if it passes all three

1. **Their audience has a stake in it.** Check it against the audience's own problems and
   questions in the brand file. News for its own sake is cut.
2. **It has something checkable**: a figure, a date, a named ruling, a before and after.
3. **Its source can be named out loud and linked.** "Studies show" is not a source.

Aim for points that do not overlap, in an order that builds: what changed, what it means for
them, what to do about it.

If the subject does not yield enough points that pass, **say so and deliver fewer.** Never pad.

## 4. Write each point in five parts

| Part | What goes in it |
|---|---|
| **What it is** | A plain label so they know at a glance what this point covers. Informative, not clever. |
| **Say it like this** | One sentence to open the point, written to be SPOKEN, in the brand's own voice (echo its voice samples). Aimed at the listener: "if you...", "most of us...". |
| **Why your audience cares** | One or two sentences tying it to a problem or question from the brand's audience file. Name which one. |
| **Where you stand** | The brand's own view. **This comes from the person, not from you.** |
| **The numbers** | One to three figures. Each one: the number exactly as published · what it measures · who published it · the year · the link. |

**About "Where you stand".** Do not give the brand an opinion. If the brand's files or the person
have already said what they think, use that, close to their wording. If not, offer one or two
directions tied to a pillar, marked clearly as **a suggestion for them to accept, change or
replace**, and ask. A run-sheet full of views the person does not hold is worse than none: they
will be asked to defend them.

Add three or four **spare questions** at the end for when a topic runs dry. Open-ended, aimed at
the audience.

## 5. Check every number before it goes on the page

For each figure, confirm all of these with the page open:

- The number appears on the linked page **as you have written it**.
- The link goes to that page, not to a search result or a home page.
- You can say who published it and when.

Then label it:

- **confirmed**: seen on the original source, as quoted.
- **secondary**: seen only in an article reporting it; the original could not be reached. Name
  both. Tell them to say "according to [the article]" and not to state it as settled.
- **unverified**: anything else. It stays off the run-sheet, or goes in a clearly separate list
  at the bottom headed "Not confirmed, do not say on air".

Never invent a figure, a source, a quote or a date. Never "fix" a number to make it rounder. If
two sources disagree, show both and say so; that disagreement is often the most interesting
point on the sheet.

**If the brand works in a regulated field** (health, finance, legal): a statistic is not
permission to make a claim. Keep points about results, treatments, returns or advice as
"here is what this study found", never "this will work for you". Put a line at the top of the
sheet saying it needs the brand's usual sign-off before anything is said publicly.

Leave out anyone on the brand's never-mention list, even if a source names them.

## 6. Save it in the brand's Strategy folder

Write one Markdown file:

    Client/<brand-id>/Strategy/talking-points/<YYYY-MM-DD>-<short-subject>.md

Use only lowercase letters, numbers and dashes in the file name. If a file with that name
exists, add `-2`; never overwrite an earlier sheet. Save inside the named brand's folder and
nowhere else.

Lay it out like this:

    # Talking points: <subject>
    For <brand name> · prepared <date> · for <where they will say it>

    ## 1. <What it is>
    **Say it like this:** ...
    **Why your audience cares:** ... (from: "<the audience question or problem it answers>")
    **Where you stand:** ...   [or]   **Where you might stand (a suggestion, yours to change):** ...
    **The numbers**
    - **<number exactly as published>**: <what it measures>. <Publisher>, <year>. <link>  `confirmed`

    ## Spare questions
    ## Sources
    ## Not confirmed, do not say on air

End the file with every source listed once, with its link, and the date you read it. Platform
facts and statistics go stale: a sheet more than a few months old should be re-checked before
it is reused.

## 7. Hand it over

Tell them it is in the Strategy folder inside their brand's folder, under talking-points. Then,
in two or three sentences: how many points there are, which one is strongest, and anything you
could not confirm. If any "Where you stand" is still a suggestion, ask about those now.

Then offer the next step in one line: "Want me to turn any of these into posts or a script?"
If a point is worth keeping, offer to add it to the brand's topic bank with this file as its
`source_ref`.
