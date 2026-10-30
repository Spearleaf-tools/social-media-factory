# Something not working?

**Tell Codex (or Claude):** "Something isn't working. Please use HELP.md to troubleshoot it with me."

You don't need to work out the problem yourself. It will check the Social Media Factory, explain what it finds
in plain words, and ask you one question at a time if it needs you.

**If Codex itself won't open, or can't find your Social Media Factory folder:** start a normal ChatGPT chat,
attach this file (it's in your `social-media-factory` folder), and say what you see. A screenshot
helps: on a Mac press ⌃⇧⌘4 and drag a box around it; on Windows press the Windows key + Shift + S
and drag a box. Then paste it into the chat (⌘V on a Mac, Ctrl+V on Windows).

**If it gets fixed smoothly, you're done.** If it doesn't get fixed, or anything along the way was
confusing, it writes a short report, saves it in the `Feedback` folder inside your Social Media Factory folder,
and shows it to you. Please send it to Joe. That's how the Social Media Factory gets better. Reports stay on
your computer until you choose to send one, and they never contain keys or passwords.

---

## For the assistant: how to troubleshoot

You are helping a non-technical person. Follow `AGENTS.md` (or `CLAUDE.md`) the whole time. Its
rules still apply, especially: never read, print, search or inspect `keys.env` or any `.env` file,
never print environment-variable values, and never ask for a key.

Plain words, one question at a time. No raw output, stack traces or file paths at the person.

**Ground rules while troubleshooting:**
- **Diagnose behind the scenes.** This file is for you. Don't read the steps or the table out to
  the person; tell them only what you found and the one thing you need from them next.
- **Use the Social Media Factory's own commands** (`factory.py status`, `factory.py doctor`, setup) rather
  than ad-hoc shell commands whenever one exists.
- **A missing or broken key is checked only with `factory.py status`.** Never look inside
  `keys.env` to "check the formatting" or for any other reason.
- **Read logs yourself and explain them.** Never show the setup log or raw output to the person.
- **Never loosen the project's permissions** because something failed. Ask for the one specific
  approval instead.
- **Never send, upload or share a report yourself.** The person decides whether to send it.
- **Keep brand material out of the report.** No post text, client details or file contents,
  only a few words describing where it happened.

### Step 1. What were they trying to do?

Ask, unless it's already clear, and offer these choices: install or setup · adding a key ·
writing or planning · pictures (carousels, cards) · research · clips from a recording · the review
page · scheduling or posting · something else.

### Step 2. Run the safe checks, in this order

Use the Social Media Factory's own Python (see "How to run tools" in `AGENTS.md`). Stop at the first check
that explains the problem.

1. `factory.py status`: what is ready, and which keys are present. It never shows a key's value.
2. `factory.py doctor`: proves each piece works by using it (it draws a test card).
3. Only if setup failed or the Social Media Factory's Python is missing: read `.factory/setup.log` yourself.
   Don't show it to them.

If the Social Media Factory's Python doesn't exist yet, the computer isn't set up: follow the setup workflow.

### Step 3. Match it to a known problem

| What they see | What it means and what to do |
|---|---|
| Codex asks permission to use the internet, or to reach outside the folder | Expected: setup downloads, research, transcripts and scheduling need it. Approve only the specific step, and say why in one sentence. Never switch to full access or turn off the sandbox |
| The drawing tool or review page fails inside the sandbox | Ask to run that one command outside the sandbox, explaining why. Don't change the project's settings |
| No Python on the computer | Setup handles it: run the first-run installer as the setup workflow describes. Nothing to install by hand |
| Apple offers "command line developer tools" | Tell them to click Cancel. The Social Media Factory doesn't need it |
| A download failed or setup stopped | Run setup again (it's safe to repeat). If it fails twice the same way, it's likely the network or a blocked site: say so plainly |
| Status says a key is missing | Expected until a key is added. Carry on with anything that doesn't need it. If they want to add one: open `keys.env` in their editor for them (setup workflow), never read it yourself |
| A check says PROBLEM | Run setup again with `--force`, then doctor. Never delete files or folders to make it pass |
| The review page seems stuck | It's meant to keep running while they review. Give them the address to open in their browser; stop it when they say they're done |
| "Can't be opened" or "is damaged" messages from the Mac, or a Windows "protected your PC" warning | Don't change security settings or bypass the warning. Run the Social Media Factory's normal setup and doctor checks, and follow the setup workflow if it has a documented fix. If it's still blocked, stop and note the exact message in the report for Joe |
| A posting record, brand file or batch is reported damaged | Stop. Don't repair, delete or overwrite anything. It goes in the report for Joe |
| The Social Media Factory wrote something untrue or not in their voice | Fix it with them, and note it in the report. Inventing facts is never acceptable |
| Anything that would need a key's value, or reading `keys.env` | Refuse, and note it in the report |

### Step 4. Finish with one of two outcomes

- **Resolved smoothly:** explain in a sentence or two what was wrong and what you did, and carry
  on with what they were doing. No report needed.
- **Not resolved, or there was friction:** say plainly what you found and that Joe will take it
  from here. Then write the report below. Friction counts even when things worked, for example:
  a confusing screen, several permission prompts, a question they had to ask you, a step the guide
  described differently, or not understanding why something was still running.

### If you are a help chat without access to their Social Media Factory folder

You can't run the checks, so work from what they describe and their screenshots. Use the table
above. Give them the exact sentence to type to Codex for each step (for example: "check my setup",
"try the setup again", "the review page didn't open, what's the address?"). If Codex won't start
at all, suggest updating the ChatGPT app and checking that Codex has opened the
`social-media-factory` folder on their computer. If that still doesn't work, use Plan B: the Claude
desktop app's Code tab, with the same folder.
Never suggest Terminal commands, deleting anything, or turning off security settings, and never accept a
key or password in the chat.

---

## Keys

### How keys are kept private
- **The rules** in `AGENTS.md` and `CLAUDE.md`: never read, print, search or copy `keys.env`.
- **A check before every command** (`.claude/hooks/guard-keys.sh`) stops commands that would show
  a key: naming the keys file, a wildcard that could pick it out, searching the whole folder,
  printing the environment, or using the Social Media Factory's key reader from a one-liner.
- **A check after every command** (`.claude/hooks/guard-output.sh`) notices a key that shows up in
  the output anyway and tells the assistant to stop and tell you which key to replace.
- **ChatGPT (Codex) runs the same two checks**, but only after you trust them once: type `/hooks`
  in Codex and trust both. Claude runs them once you have trusted the Social Media Factory folder. When the
  second check finds a key, Codex hides that output, so the key never reaches ChatGPT; Claude has
  already seen it, so there the check can only warn.
- **Keep Claude up to date.** From Claude Code 2.1.295, a check that can't start (for example a
  missing file) stops the command instead of letting it run. Older versions let it run.

**What these checks can't do** (written down on purpose): they stop accidents and plain attempts,
not an assistant that is set on finding a key. A file name built from pieces at run time, a script
file that reads the keys and is then run, copying or zipping the folder, an encoded copy of a key,
very long output that is cut short, text typed into a command that is still running (Codex), keys
kept only in Doppler, and a check that can't start (in Codex, or in Claude before 2.1.295) can all
get past them. That is why a leaked key must be quick to replace, below.

### Replace a key
If a key was shown, pasted into a chat or sent anywhere it shouldn't be, replace it now. Make the
new one first, put it in `keys.env` (open it in your own editor: Mac `open -t keys.env`, Windows
`notepad keys.env`), then run `factory.py status --verify` to check it works.
- **Apify** (research): Apify Console, **API & Integrations**, **Rotate token**. Don't keep the
  old token active when it has leaked. When you make a token, **Limit token permissions** lets it
  reach only what the Social Media Factory needs, and your account's usage limit caps the monthly spend.
- **ElevenLabs** (transcribing): your personal API keys settings
  (elevenlabs.io/app/settings/api-keys). Delete the old key and create a new one. A key can be
  limited to certain features and given a credit limit; give it only speech to text.
- **Metricool** (posting): **Settings**, the **API** tab, **REST API Accesstoken**, the ⋮ menu,
  **Regenerate token**. The old one stops working at once. Whether a Metricool token can be
  limited is not known, so treat a leaked one as able to post until it is replaced: do this first.
- **Someone else's key** (for example the project owner's): tell them straight away; only they
  can replace it.

---

## Report for Joe

Fill this in with short, plain answers. **Never include keys, passwords, environment-variable
values, stack traces or long technical output.**

Save it as a new file in the `Feedback` folder at the top of the Social Media Factory folder (create the folder
if it isn't there), named with the date and a few words, for example
`Feedback/2026-09-26-setup-download-stopped.md`. Never overwrite an earlier report. Show them the
report, and tell them it's saved in the Feedback folder, to send to Joe when they're ready. It
stays on their computer unless they choose to send it. A help chat without access to their folder
shows the report for them to copy instead.

```
REPORT FOR JOE: Social Media Factory
Date:
Trying to do:
What happened:            (the message they saw, in a sentence)
Social Media Factory status:           Ready / Problem / Couldn't run
Social Media Factory doctor:           Passed / Problem / Couldn't run
Where it stopped:         (e.g. setup step, drawing a card, the review page)
Permission prompts:       Yes / No. About how many, and were any confusing?
What was tried:
Outcome:                  Resolved / Not resolved / Partly
Confusing moments:        (anything confusing, or questions they had to ask, even if it worked)
Likely type:              Social Media Factory problem / Setup or onboarding experience / Instructions (the guide, AGENTS.md or HELP.md)
Time lost:                (about how many minutes)
How it felt, 1-5:         (1 = stuck, 5 = easy)
What they need help with:
Anything they liked or want:
```

"Likely type" helps Joe route it: a **Social Media Factory problem** means the software misbehaved; **setup
or onboarding experience** means it worked but was confusing or slow; **instructions** means the
guide or the assistant's instructions led them the wrong way.

### First-run notes (during installation only)

While they're installing, jot anything unexpected in the report's "What happened" line, even if
it worked: a confusing screen, a long wait, a prompt they didn't understand, a step the guide
described differently. Real first-run notes are what make the next install smoother.
