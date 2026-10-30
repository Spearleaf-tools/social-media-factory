---
name: make-clips
description: Turn a recording (a podcast, an interview, a talk, a filmed Q&A) into finished short clips. Use when the person says "clip this podcast", "pull shorts from this recording", "turn this interview into clips", "find the hooks in this", "make rough cuts", "fine cut these", "add captions", "make versions for my other accounts", or "I have two cameras". Transcribes with who-said-what, flags compliance, helps the person choose clips from the real transcript, cuts them on the actual words, tightens them, makes captioned versions, checks every file, and hands them to posting. Every hook is a line the person really said.
---

# Make clips

One recording in, finished clips out, in steps you can run together or one at a time:

**transcribe** (costs a little) → **choose** (the person decides) → **rough cut** → **fine cut**
→ **check** → **versions with captions** → **descriptions** → hand to **post**.

## The laws

1. **Every hook is a line from the transcript, word for word.** You never write a hook, and you
   never invent a number. If the recording does not contain a good opening, say so.
2. **The tool flags; a person chooses.** Nothing is ranked. `playbooks/clip-rubric.md` is the
   method: two gates, then six questions. Read it before your first recording.
3. **Off-camera voices stay off.** If a host, coach or interviewer is heard but not the brand's
   on-camera person, nothing they say is a hook or a body. Naming the voices (below) is what
   makes that enforceable.
4. **Regulated claims travel with their disclaimer**, and a clip marked HOLD does not go out
   until the named person has signed it off.
5. **Never delete or move an original recording.** Everything the Factory makes goes in the
   brand's Output folder.

## Needs

The video tools (a second, larger download: use **setup**, `--tier video`) and an ElevenLabs key
for transcription. **Say the cost first: about 22 cents per hour of audio.** Everything after
the transcript is free and runs on this computer. If an editor already made a subtitle file for
the video, that can be used instead of paying for a transcript (`--srt`), with less precision.

## 1. Get the recording in

Each recording gets its own folder inside the brand's Inputs, under Recordings. Put the video
there (copy it; leave the original where it is). `factory.py recordings --brand <id>` lists them.

## 2. Transcribe

`factory.py transcribe --brand <id> --recording <folder> --media <file>` shows the length and
the estimated cost and **sends nothing**. Tell them the cost. On their yes, the same command with
`--confirm`.

Then read the start of the transcript and **name the voices**: ask who each speaker is, and
record it: `factory.py transcribe --brand <id> --recording <folder> --name speaker_0="Ava Lindqvist" --name speaker_1="Jonah Pell"`.
Naming is free. Anyone listed as a host in the brand's settings, and any voice left unnamed in a
recording with several voices, is kept out of clips.

## 3. Find and choose

`factory.py find-clips --brand <id> --recording <folder>` does two things: it flags passages
that break the brand's rules (DROP never ships; HOLD needs the disclaimer and a sign-off), and
it lists stretches worth reading first. It does not score them.

Read the on-camera transcript yourself. Propose clips to the person the way the rubric says:
for each **body** (one idea, complete by itself), two or three candidate **hooks**, each a verbatim
line, often from later in the same answer (the buried lead). Give the person the words and the
times, and let them choose. Then write the cut list in the format `smf/video/cutlist.py`
documents: a reference block (which recording, which exact file, where the times came from),
each body with its hooks, 3 to 7 words of on-screen text (no claims), the credit line, the
gate, and the **boundary words** each cut starts and ends on.

`factory.py check-cut-list --brand <id> --recording <folder>` proves it: every hook and boundary
really is in the transcript, near the time given, said by an on-camera voice. Fix what it finds.
It tells you when a moment sits too close to the host's voice to cut cleanly, and by how much.

## 4. Rough cut, fine cut, check

1. `factory.py rough-cut --brand <id> --recording <folder> --dry-run` shows where every cut would
   land. Then without `--dry-run`. Cuts snap to the boundary **words**, because timestamps drift
   and words do not. If it warns that the cuts are not landing on the words, the video file or
   its offset is wrong: stop and find out, do not pass `--anyway` to silence it.
2. `factory.py fine-cut --brand <id> --recording <folder>` takes out fillers and dead air.
   Smooth, not surgical: it leaves breathing room on purpose.
3. `factory.py validate-cuts --brand <id> --recording <folder>` listens to every finished clip
   with a second, independent speech model and checks the first words, the joins and the last
   words. A clip that fails is fixed and cut again, not shipped. A clip it could not check is not a pass either: watch that one yourself before it goes anywhere.

Show the person the clips. Rough and fine cuts are deliberately plain: full frame, no text.

## 5. Two cameras (optional)

If the conversation was filmed on two cameras, the Factory can make one video that shows whoever
is talking, and cut the clips from both cameras. Put both camera files in the recording's folder.
The transcript and the cut list are made the same way as for one camera (steps 2 and 3).

1. **Line the cameras up.**
   `factory.py sync --brand <id> --recording <folder> --camera-a <file> --camera-b <file>` listens
   to both files and measures how far apart they are, and which way. Add `--sound A`, `--sound B`
   or `--sound <file>` to say whose sound the finished video uses (a separate recorder is usually
   the best one). The answer is saved with the recording. If one person's lips run ahead of their
   voice, `--nudge B=0.08` delays that camera's picture; the sound never moves.
2. **Say who is on which camera. Ask the person; never work it out from a name.**
   `factory.py multicam plan --brand <id> --recording <folder> --speaker "Ava Lindqvist=A" --speaker "Jonah Pell=B"`
   prints the list of shots and makes nothing. A voice that is on neither camera is named with
   `--off-camera "Their Name"` and is never cut to. Read the shots with the person.
3. **Make the full video:** `factory.py multicam render` with the same options (`--dry-run` first
   if you want to see the shots again). This is the long-form edit.
4. **Make the clips:** `factory.py multicam clips --brand <id> --recording <folder>` with the same
   `--speaker` options. It uses the same cut list and the same rules as step 4, and the picture
   follows the speaker inside each clip.
5. **Check:** `factory.py multicam verify --brand <id> --recording <folder>` for the full video,
   and again with `--clips` for the clips. It opens what was made and checks pictures, sound and
   length. Then `factory.py validate-cuts` listens to the clips, exactly as for one camera.

Two-camera clips **skip the fine cut**: that step works from one video file and says so if you
try. They go straight to versions and captions.

## 6. Versions, captions, descriptions

One finished clip becomes several versions that look and sound different (framing, caption
style, pace, colour), so the same clip can go on more than one account without being an identical
upload. All text on screen is drawn from the clip's own record: the on-screen words, the credit
line, word-by-word captions in the brand's accent, and the disclaimer band on any HOLD clip for
its full length. Every command here takes `--brand <id> --recording <folder>`.

1. **Plan.** `factory.py variants plan` decides each clip's versions and makes no video. Three
   versions each unless you say `--versions <n>`. A wide video is cropped tall around the
   speaker's face, which it finds by itself; if it says it could not find one, look at a frame
   and tell it where the person is, left (0) to right (1): `--centre-on A1=0.3`.
   Flipped versions are off unless the brand allows them in its settings **and** the person
   confirms nothing readable is in this recording's picture (`--no-text-in-picture`). Ask; never
   assume.
2. **Make them.** `factory.py variants render`. A HOLD clip with no sign-off is made only as a
   stamped preview for the named person to watch: add `--preview`.
3. **Look.** Open a few versions with the person. Captions should match the words; text should
   sit clear of the face.
4. **Check.** `factory.py variants verify` opens every finished file and checks what is in it. A
   check that looked at nothing counts as a failure, on purpose.
5. **Write the words under each video.** `factory.py describe contract` writes a page per clip:
   the clip's exact words, the brand's voice, each platform's rules, the facts allowed, and where
   to save what you write. You write each version its own words from that page. Then
   `factory.py describe check` reads them against the clip's own transcript and the brand's facts:
   passed, unverified (the person decides) or blocked (fix it).
6. **Deliver.** `factory.py variants deliver --dry-run` says what would happen; without it, the
   checked versions and their words are copied into the brand's video inbox, named so posting
   understands them. A version that has not passed its check goes only if a person watched it
   (`--watched-by "Their Name"`). `factory.py variants status` shows where every clip stands.

## 7. Hand off

"Your clips are in the inbox. Shall I plan one a day?" Then **post** (section C).

## Reporting

Say what came out in two or three sentences: how many clips, which were held and why, what
needs their sign-off. Never describe a clip as checked if its check did not run.
