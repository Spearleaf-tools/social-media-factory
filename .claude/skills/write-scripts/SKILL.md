---
name: write-scripts
description: Write short-form video scripts for a brand, each with its visual directions and a teleprompter file. Use when the person says "write me some video scripts", "scripts for Reels / TikTok / Shorts", "I need something to film", "a teleprompter script", "turn this podcast into scripts", "what should I film this week", or "how did my last batch of videos do". Works from the brand's topics or a topic list, or from a recording's cut list. Always staged: a pitch sheet first, the person approves, then the scripts are written, checked, given teleprompter files and indexed.
---

# Write scripts

The goal: the person ends up with a folder they can film from. Every script in it says what to
say, what to show, and where each fact came from. Every script has a teleprompter file beside it.
One index page tells them what is ready.

## How to run this conversation

- **You run every command. They never see one.** No JSON, no file names, no status words. Say
  "three are ready to film, one needs a fix from you".
- **One question at a time**, with a default so "yes" is a full answer.
- **Nothing is written before they approve the pitch sheet.** This is the one hard stop.
- **Never invent.** A script is built only from the brand's own material and what the person
  tells you here. If the material is thin, say so and ask. Do not fill the gap.

Read `playbooks/short-form-scripts.md` before your first batch. It is the craft this skill
applies. `playbooks/short-form-video.md` holds the platform rules and `playbooks/hooks.md` the
opening patterns.

## The sourcing law

1. A spoken line may be **refined** so it sounds natural when spoken. The **fact** inside it may
   not be changed, rounded or invented.
2. **Every fact traces to the brand's own material**: a recorded fact, a proof item, a research
   file, their transcript, their own files. The script carries a source note for each one.
3. **The opening is never a fact the brand cannot back.** If the strongest opening needs a number
   they cannot show, use a different opening.
4. Anything that cannot be traced is labelled **unverified**, and you tell them which line and why.
5. Write every real fact with digits (18 hours, not eighteen), so it can be checked.

## Step 1. Which brand, and which track

Confirm the brand by name. Never assume it, and never carry one over from an earlier request.

Run `factory.py scripts status --brand <id> --json` to see what batches exist and what is already
in progress. If a batch is half done, offer to carry on with it before starting another.

Then pick the track:

| They have | Track |
|---|---|
| Topics: an approved plan from `plan-content`, or a list of subjects they give you now | **Topics** |
| A recording that `make-clips` has already turned into a cut list | **Recording** |
| A recording with no cut list yet | Use `make-clips` first, then come back |

A cut list groups its clips by **body**: one stretch of the recording that makes one point. One
body gets one pitch, however many clips were cut from it.

Ask two short questions, each with a default:

- **How many can you film in one go?** (Default: five.) This sets the batch size. Pitch a few
  more than that so they have something to turn down.
- **Who is on camera?** One of the brand's identities. If there is only one, just say who.

Start the batch. Give it a plain name such as `october-week-1`:

- Topics: `factory.py scripts new-batch --brand <id> --name <name>`
- Recording: `factory.py scripts new-batch --brand <id> --name <name> --track recording --source "<the cut list, as a path inside the brand's folder>"`

## Step 2. The pitch sheet (then STOP)

Read before you pitch: the brand's `Brand/` files (above all `voice-samples.md` and
`audience.md`), `Studio/facts.json`, its pillars and offers, and for the recording track the cut
list and the transcript it points to.

For each pitch decide:

| | |
|---|---|
| **Subject** | A few words |
| **Job** | `reach`, `leads` or `trust`. See section 1 of the scripts playbook. Most should be trust |
| **Who speaks** | One of the brand's identities |
| **Words on screen at the start** | The opening, in a few words. Engineered fresh, not lifted from the transcript |
| **The angle** | The one thing this video will say about the subject |
| **Opening pattern** | Which pattern from the playbook, in a few words |
| **Where it comes from** | A pointer into the brand's material: `audience.questions_they_ask[0]`, `pillar:<id>`, `offer:<id>`, `fact:<id>`, `proof:<id>`, or a file inside the brand's folder |
| **Topic or body** | The topic's id, or the body of the cut list |

Write the pitches to a JSON file under `.factory/tmp/`:

```json
[{"title": "Why a loaf comes out dense", "job": "trust", "speaker": "person",
  "hook": "Dense loaf? Check the proof", "angle": "It is the proof, not the flour",
  "hook_pattern": "the fault on the bench", "pillar": "fix-my-loaf", "length": 40,
  "source_ref": "audience.questions_they_ask[0]", "topic_id": "dense-loaf"}]
```

For the recording track each pitch carries `"body": "<the body's label>"` instead of a topic id.

Then: `factory.py scripts pitch --brand <id> --batch <name> --from <file>`
(add `--run <run>` when the topics come from an approved plan, so only approved topics get in).

A pitch is refused if it does not say where in the brand's material it comes from, and a subject
an earlier batch already covered is left out and named. Tell them what was left out and why.

**Show them the pitch sheet as a short plain table** (subject, the words on screen, the angle,
what the video is for) and ask: "Which of these shall I write? You can say all, pick some, or
change any." **Stop here and wait.**

## Step 3. Record their answer

`factory.py scripts approve --brand <id> --batch <name> --scripts 01 02 04 --cut 03`
(or `--all`). Only what they said yes to.

Each approved script now has a starter file in the batch folder. Its header is filled in and its
ending is already chosen to fit its job, from the brand's own offers and wording. If a leads
script has no offer to point to, the command says so: pass that on in one sentence.

## Step 4. The writing

- **Four or fewer:** write them yourself, one at a time.
- **Five or more:** start one `script-writer` agent per script, **all in the same message** so
  they run side by side. Give each one only: the brand id, the batch name, its script number, the
  starter file's path, and its row from the pitch sheet. They do not need this conversation.

Whoever writes, the rules are the same:

- Fill in the starter file. Keep its labels exactly: `Promise:`, `On screen:`, `Show:`, `Say:`,
  `Source:`. One line per field.
- **One idea**, in one sentence, at the top.
- The **opening's three parts agree**: the words on screen, the first picture and the first
  spoken line all make the same promise, and each one names its subject.
- **Every `Say:` has a `Show:` beside it.** A script never ships without its visual directions.
- Sound like the brand's voice samples read aloud. Keep each spoken sentence inside the brand's
  limit.
- Add a `Source:` line to every line that states a fact.
- Fill in "To shoot this": what they need to hand when filming.

## Step 5. Check every script

`factory.py scripts validate --brand <id> --batch <name>` (or `--script 03` for one; add `--json`
to read the result yourself).

Fix what it reports and run it again until each script passes. Do not argue with a check and do
not work around one:

- **A never-mention name, a banned word, a term that must never publish:** rewrite the line.
- **The opening disagrees:** bring the subject of the promise into the part that is missing it.
- **A fact with no source:** find it in their material and add the note. If it is not there, ask
  them. If they confirm it and are happy to say it in public, record it in the brand's facts with
  where it comes from. If not, take it out.
- **Unverified:** tell them which line, and let them decide: back it up, or cut it.
- **Needs sign-off** (regulated brands): tell them the script needs the brand's disclaimer and a
  yes from the named person before it is published. Do not treat it as approved.

**A script that passes gets its teleprompter file made in the same step.** A script never ships
without one. If a script is edited later, it goes back to draft and its teleprompter is marked
out of date, so run the check again after any change.

## Step 6. The index, and hand over

`factory.py scripts index --brand <id> --batch <name>`

Tell them, in a few lines:

- How many are ready to film, and where the folder is ("the scripts folder inside your brand's
  Studio folder, in the batch called ...").
- That each script has two files: the script itself, and a teleprompter file with only the words
  to say.
- What to have to hand when filming (from the index).
- Anything still open, and what you need from them.

Offer one line of help for the shoot: section 7 of the scripts playbook is written for someone
new to a camera. Read them the three or four points that fit.

## Later: filmed, and how it went

- **"I filmed them":** `factory.py scripts status --brand <id> --batch <name> --recorded 01 02`.
  Only scripts that passed their checks can be marked as filmed.
- **Captions and cutting** belong to `make-clips`. **Posting** belongs to `post`.
- **"How did they do?"** Wait until the videos have been out about a week and at least four have
  numbers. Ask for each video's views, saves and sends, and if they have them how many were still
  watching at three seconds and how much of the video people watched. Put them in a small file
  (script number plus the numbers) and hand the batch to the `script-audit` agent, or run
  `factory.py scripts audit --brand <id> --batch <name> --numbers <file>` yourself. If
  `check-results` has already saved numbers for this brand, the audit reads those too.
  The audit ends in **one** thing to test in the next batch. Pass on that one thing. Do not add
  to it.

## Done means

- Every script they approved passes its checks, or they know exactly what it is waiting for.
- Every passing script has its visual directions and a current teleprompter file.
- The index is rebuilt and they know where it is.
- Nothing in any script was made up by you, and anything unverified has been named to them.
