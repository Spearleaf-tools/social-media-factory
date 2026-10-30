---
name: make-a-film
description: Make a narrated film (an ad, a product film, a brand story) from many pieces of footage under one voiceover. Use when the person says "make a video ad", "make a film about ...", "cut my footage to a voiceover", "use all my footage", "make a promo from these clips", "put a narration over this", or has footage from several places and no single recording to clip. Collects the footage (their own, their computer, public sources with a clear licence), writes the narration from the brand's own material for them to approve, voices it (ElevenLabs, or their own read), matches every shot to the line it sits under, checks every shot against its source, renders, and shows the finished film back as a contact sheet. Not for cutting one recording into clips: that is make-clips.
---

# Make a film

A film is many shots under one narration. The narration is the spine; **every shot has to prove
the line it sits under.** The person watches the result and tells you what is wrong by timestamp.
Your job is to make that list short.

`factory.py montage` does the mechanical part and refuses the mistakes that are easy to miss:
shots that run past the end of their source (every later cut slides out of step), shots that
cross a scene change inside their source (a one-frame blip), shots that barely move (they read as
a frozen frame), numbers with no source, and footage with no credit.

## The laws

1. **Never invent.** Every fact, number, customer and claim in the narration comes from the
   brand's own files or from what the person tells you in this conversation. A line with a number
   carries a `fact_source`, or `check` reports it as unverified and the person decides. Plans,
   roadmaps and "coming soon" pages are not features: never narrate one as if it ships.
2. **The person approves the script before anything is spent.** You draft; they change and say
   yes, line by line. Voicing costs a little; so does finding word times.
3. **Only footage they may use.** Their own, their client's with a yes, or public material whose
   licence you can name. Never a download of someone else's video, and never a way around a
   site's download limits (no browser cookies, no ripping tools pointed at other people's work).
4. **Never move or delete an original.** The plan points at files where they are; everything the
   Factory makes goes in the film's folder inside the brand's Output.
5. **Look at the finished film, not the plan.** When the person names a moment, take the frame
   from the rendered film at that time and look at it before changing anything. The plan says
   what you meant; the film says what happened.
6. **Nothing is posted.** When they have watched it and said yes, hand over to **post**.

## Needs

The video tools (**setup**, `--tier video`). An ElevenLabs key only if the voice is synthesised
or you need word times; a person's own recorded read needs no key. Say the cost before either
paid step: voicing uses characters from their ElevenLabs plan (the command says how many);
finding word times costs about 22 cents per hour of audio (the command says how much); a music
bed made to order uses credits from their ElevenLabs plan (the command says what it would send).

## 0. The footage folder: the one rule for every brand

Everything a film may cut from goes in **one folder inside the brand: `Inputs/Footage`** (the
Footage folder inside the Inputs folder of their brand). Not a downloads folder, not the desktop,
not a temp folder that will be wiped. Ask them to put their footage and pictures there, or copy
what they point you at into it (never move or delete an original). Then:

`factory.py montage footage --brand <id>` lists what is there, with each file's length, in a list
kept beside the files. For every file it reports as having no note yet, look at a few frames with
the person and write, in the list, **what is in it** (`"shows"`, in plain words) and **whose it
is** (`"credit"`: their own, or whose and under what licence). A file that disappears is marked
missing, never forgotten. Run it again whenever they add something.

A draft plan (step 4) takes its sources from this list and suggests shots from those notes, so
the better the notes, the less placing there is to do by hand.

## 1. Their own footage

Ask what they have and where it lives: finished videos, raw recordings, screen captures,
renders, event footage, logo animations. Ask which of it is cleared for marketing. A client's
project footage needs the client's yes; say so.

Their own tutorials, demos and launch videos are often the best material: clean interface
footage at full resolution, and usually a logo animation at the start that can open the film.
Ask for the **original files**. A copy from a video site is often far lower resolution than what
was uploaded. Put them in the footage folder.

## 2. Look through their computer (only where they say)

Search only the folders they name. List what you find in plain words: file, length, size of the
picture, and a guess at what is in it. Say which files are not the brand's (other projects, a
webcam call, a game) and leave them out. Look at a few frames of each before calling anything
"footage of X": names lie.

## 3. Public footage, with its licence

When their own footage cannot show something the story needs (the planet from orbit, a flood, a
storm), public sources can. Name the licence of everything you bring in, and record it as the
source's `credit`. Before bringing anything in:

- **Government work is often public domain, with conditions.** Space-agency and science-agency
  imagery usually asks for a credit line. Military media archives are public domain but forbid
  any suggestion that the military endorses the product: leave out shots of people in uniform.
- **Stock sites and news footage are licensed, not free.** Do not use them unless the person has
  the licence.
- **Real damage and real people.** Footage of destroyed homes, disasters and grieving
  communities is someone's life. Keep faces, house numbers and addresses out, and ask the person
  whether it belongs in a commercial film at all.
- **Download the original file** from the source's own download link, and check its size and
  length before using it.

Every source outside the brand's folder without a credit is flagged by `check`.

## 4. The narration

Read the brand's files first (`Brand/`, `Studio/facts.json`, their transcripts). Ask who the
film is for and what it should make them do.

**Start from words that already exist, never from a blank page:**

- **A brand story or ad:** `factory.py montage draft --brand <id> --film "<name>" --from-brand`
  writes a plan whose lines are the person's **own onboarding answers**, in a story arc: why they
  started, what changed in the world, the problems, the truth they hold and its proof, what they
  do and how that differs, the myth and the mistake they correct, the steps, the offer. Every line
  says where its words came from. It also lists what the brand has **not** said yet: ask for
  those in the chat, never fill them in.
- **A film from a script the writer finished** (write-scripts): the same with
  `--from-script <the script's path inside the brand folder>`. Say becomes the line, Show what it
  wants, Source its fact source.

A draft has **no shots**: check refuses to render it until a person has placed them. Each line
carries `"wants"` (what it should show) and, when the footage list has notes, `"suggested"`
footage to look at first.

Then make it a narration: **a list of lines, each one sentence or less, each one something a shot
can prove.** The person's answers were typed in a form, not spoken; read them aloud with the
person and take their changes until each line sounds like them. Aim for the audience: a technical
audience wants the real specifics (what it runs on, what it connects to, what it does), said
plainly; nobody wants brochure words. Never add a fact the draft did not carry.

Show the lines, with the footage you have in mind for each. Take their changes. Keep going until
they say yes to the words. If they would rather read it themselves, go to step 6.

## 5. Voice it with ElevenLabs

1. The draft from step 4 is the film's plan. (With no draft, `factory.py montage new --brand <id>
   --film "<name>"` starts an empty one.) Put the approved lines in it and, if the footage folder
   did not supply them, the sources.
2. **The brand's own voice, saved once.** A brand keeps its narration voice in its settings
   (`video.voice` in `brand-master.json`, then `sync-brand`), and every new or drafted plan speaks
   with it: the ElevenLabs voice id, the model, its settings, its **styles** and how its own words
   are said. The person chooses the voice (their own clone, with their consent, or one from their
   library) and the model:
   - `eleven_v4`: the most expressive, takes **audio tags** and a cloned voice well. The one to
     start with for a personal voice. Its stability is a word: `creative`, `natural` or `robust`.
   - `eleven_v3`: expressive, takes tags; a professional clone sounds less like them on it.
   - `eleven_flash_v2` / `eleven_turbo_v2`: plain, fast, no tags; the only ones that honour
     phoneme tags.
   `montage check` refuses a plan whose text its model would get wrong: a tag on a model that would
   read it aloud, a phoneme tag on a model that leaves the word out.
3. **Styles.** A style is a named delivery, an audio tag the voice gets in front of the words:
   `"styles": {"confident": "[confident]", "warm": "[warm, unhurried]"}`, with `"style":
   "confident"` for the whole film and `"style": "warm"` on any line that should differ. Agree
   two or three with the person from what they really sound like; do not invent a character for
   them. Changing a line's style re-voices that line only.
4. **Words the voice will get wrong:** the brand's name, product names, acronyms. Put each in
   `"say_as"` with how it is said: a respelling (`"SQL": "S-Q-L"`); on v4, IPA between slashes
   (`"brioche": "/briˈɔʃ/"`); a phoneme tag only on `eleven_flash_v2` or `eleven_turbo_v2`.
5. `factory.py montage voice --brand <id> --film "<name>"` says how many lines need a take and how
   much text that is (tags count), and sends nothing. On their yes, the same with `--confirm`.
6. **Ask them to listen to the brand name and to one tagged line.** Speech-to-text cannot hear a
   wrong vowel: it writes the right word either way. A tag the voice ignores is silent, not wrong.

Each take is saved under a name made from its words and voice settings, not its place in the
list. Adding a line, or fixing how one word is said, re-voices only the lines that changed, so
nothing already timed moves.

A key that can make speech may not be allowed to list voices. If so, ask the person for the voice
ID from their ElevenLabs account. Copying a real person's voice needs that person's consent.

## 6. Or their own read

They record the narration in one file (a quiet room, the phone close). Transcribe it with
`factory.py transcribe --brand <id> --recording <folder> --media <file>` (shows the cost; sends
only with `--confirm`) to get where each line starts and ends. The plan's voice is then
`{"recording": "<file>"}`, and each line has `"from"` and `"to"`, in seconds. Nothing to voice.

## 7. Match the footage to the words

For each line, choose shots that **show what it says**, not shots that are merely nice. Look at
frames from the source before choosing a time: open a few frames around the moment you mean.
Then:

- `"source"` and `"at"` for each shot. Two or three shots per line keeps the film moving. Leave
  `"seconds"` off and they share the line's time.
- **To land a cut on a word** ("...out of the oven at *five*"): `factory.py montage words --brand <id>
  --film "<name>" --line 12` says where each word falls (it says the cost first; `--confirm`). Pin
  the shots before the word with `"seconds"` so they add up to the word's start, less a tenth of a
  second. At least one shot per line stays unpinned.
- **Crop out what is not the product:** taskbars, editor toolbars, cursors, a tutorial's
  instruction graphics, burned-in captions, watermarks, a helicopter's window frame. Per source
  (`"crop"`) or per shot. **Never crop through a logo:** fit the whole frame instead
  (`"fit": "pad"`).
- An opening logo animation is `"opening"`: shots with `"seconds"`, before the first line.
- Music under the voice, one of three. Their licensed file (`{"file": ...}`). The built-in quiet
  bed (`{"bed": "drone"}`). Or a bed **made to order** by ElevenLabs Music:
  `{"compose": {}, "level_db": -12}`. **The words are the brand's, not yours.** Leave the prompt
  out and `montage music` drafts it from the brand's own settings (how its voice sounds, its
  industry, the looks it likes and dislikes from the deeper onboarding), writes it into the plan
  as `"prompt"` with `"prompt_source"`, and sends nothing on that run. Read the drafted words to
  the person; they change what they like. When the brand's settings say nothing usable, the
  command says so: ask the person for **three words** that describe the music they want and put
  exactly those in `"prompt"`. Never add a mood, an instrument or a pace they did not give you.
  It is instrumental unless they ask for words, and sung words must be the brand's own: put them
  in `"words"` with `"words_source"` naming the file they came from, never words you wrote.
  The bed is cut to the film's length plus a few seconds; `"seconds"` pins it (3 seconds to
  10 minutes). Then `factory.py montage music --brand <id> --film "<name>"` says exactly what
  would be sent (the words, the length, the model) and that it uses credits from their ElevenLabs
  plan, and sends nothing. On their yes, the same with `--confirm`: the bed is saved in the
  film's `music` folder and becomes the plan's `"file"`, so render plays it as it plays any
  track. The same words, length and model are never paid for twice. Make the voice first when
  you can, so the bed is cut to the real length. Never a track they do not have the rights to.

**Titles.** `factory.py montage titles --brand <id> --film "<name>"` makes a short motion-title
clip for every piece of on-screen text the plan already has: the plan's title as an opening title,
each line's `"on_screen"` words, and the brand's wordmark and handle as an end card. Every clip is
unmistakably the brand's: the same colours the card renderer mixes for its grounds (the opening
title and end card on the bold ground, words on screen on the brand's own background, unless the
brand's settings choose otherwise under `visual.titles`), its own fonts with the same fall-backs,
its logo on the end card when it has one, one entrance and one exit and nothing else. Each clip
becomes an ordinary source named `title-<n>` (credited "Made by the Factory", kept in the film's
`.work/titles` folder) and is **suggested** on its line, never placed: look at the clip, then add a
shot from it like any other (`"at": 0`; the opening title can go in `"opening"` with its seconds).
It carries only words already in the plan or the brand's settings; to change the words, change the
line. Running it again makes nothing new unless the words, size, frame rate, colours, fonts or
logo changed. Each clip takes ten to twenty seconds to render. The renderer (HyperFrames, on a
Node the Factory keeps in its own folder) is installed by **setup** with the video tools; if it is
missing the command says so and installs nothing, so run `factory.py setup --tier video`. `check`
will call a title "still-looking": that is right for a title.

`factory.py montage check --brand <id> --film "<name>"` then says, for free, everything that is
wrong before a single frame is made. Fix every error. Read every warning to the person: a
still-looking shot may be fine under a title and wrong under a line about movement.

## 8. Render and look

`factory.py montage render --brand <id> --film "<name>" --dry-run` lists every line and every shot
with its time. Then without `--dry-run`. It makes the film, `shots.jpg` (one frame from the
**finished** film at the middle of every shot), `credits.txt` and a report, and it measures the
picture against the sound.

**Open the contact sheet yourself before telling them it is ready.** Look for a shot that shows the
wrong thing, a frame that is blank or mid-transition, chrome that got through, text cut off at
an edge. Then ask them to watch it.

When they name a problem ("at 30 seconds there's a blip", "the logo is cut off"):

1. Take the frame from the rendered film at that moment and look at it.
2. Work out which shot it is from the report, not from memory.
3. Fix that shot, check, render, and look at the same moment again.

## 9. Finish

- **Length.** A brand film can run two minutes; an ad for a feed wants 30 to 45 seconds. Offer
  the short cut: the strongest lines and their shots.
- **Vertical.** A tall version is a new plan with `"size": [1080, 1920]` and its own crops, shot
  by shot. The middle of a wide shot is rarely the part that matters.
- **Credits.** `credits.txt` lists every source's credit. Public footage usually has to be
  credited where the film is published.

Then hand over to **post**.

## Reporting

Say in two or three sentences how long the film is, how many shots and sources, what the contact
sheet showed, and anything the person must decide: warnings they have not answered, credits that
must be published, a number still unverified. Never call the film checked if you have not looked
at its contact sheet.
