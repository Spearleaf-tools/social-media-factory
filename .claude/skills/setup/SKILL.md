---
name: setup
description: Install Social Media Factory on this computer, add keys, and check what is ready. Use when the person says "set this up", "install", "get started", "check my setup", "is everything working", "add my keys", "why isn't X working", "walk me through Metricool" (or Apify, ElevenLabs, AI pictures), "help me set up ElevenLabs", "check my keys online", "what does X cost", or when any other skill reports that the Social Media Factory is not set up. Works on a computer with nothing installed, Mac or Windows, with no admin password.
---

# Setup

You are setting this up for someone who may never have opened a terminal. **You run every
command. They never type one.** Say what is happening in one plain sentence per step, never paste
raw output at them, and never show a file path unless they ask where something is.

## The rules of this skill

1. Every tool runs through `factory.py`. No pipes, no `&&`, no shell tricks: the shell here may
   be zsh, Git Bash or PowerShell, and only plain commands behave the same in all three.
2. **Never open, read, print or search `keys.env`.** Never ask for a key in the chat. If they
   paste one anyway, tell them to delete that message's key from wherever it came from, make a
   new one, and put the new one in the file.
3. Setup is safe to repeat. If anything is interrupted, run the same command again.

## Step 1. Is there any Python on this computer?

Try these one at a time until one prints a version of 3.8 or newer. Stop at the first that works.

- `python3 --version`
- `python --version`
- `py --version` (Windows)

**If one works** (call it PY), run: `PY factory.py setup`

**If none works**, the computer has no Python. Run the first-run script for its system. It
downloads one small installer program into this folder, which then fetches a private Python and
runs the normal setup. It needs no admin password and changes nothing else on the computer.

- Mac or Linux: `sh install/first-run.sh`
- Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File install\first-run.ps1`

On a Mac, if `python3 --version` opens a pop-up asking to install "command line developer
tools", tell them to click Cancel. That pop-up is Apple's, it is a large unrelated download, and
the first-run script does not need it.

Setup prints five short steps. The fourth (the page renderer) is the big download, a couple of
hundred megabytes. Tell them that is normal and roughly how long it may take on their connection.

**If setup stops with an error:** read the message, it is written in plain words. The usual
cause is a blocked or dropped download. Run the same command again once. If it fails the same
way on a work computer, tell them plainly: "Your company's security software is blocking the
download. IT needs to allow these sites," and read them the site list from the message. The full
log is `.factory/setup.log`; read it yourself, do not show it to them.

## Step 2. From now on, use the Social Media Factory's own Python

After setup, run everything with the Social Media Factory's Python so every computer behaves the same:

- Mac or Linux: `.venv/bin/python factory.py <verb>`
- Windows: `.venv\Scripts\python.exe factory.py <verb>`

If that file does not exist, the environment was placed somewhere short because this folder's
path is long (a Windows limit). Run `PY factory.py where` and use the path it prints.
`factory.py` also finds its own Python if you start it with any other one.

## Step 3. Prove it works

Run `factory.py doctor`. It draws a test card and checks the pieces by actually using them.
Tell them the result in one sentence. If something shows PROBLEM, fix it before moving on
(re-run setup with `--force`, then doctor again).

## Step 4. What do they want to make? Then, and only then, keys.

Run `factory.py status`. Do not read the list to them. Ask what they want to do, then tell them
what that needs. Writing posts and scripts, making carousels, reviewing and saving a ready-to-post
folder need **nothing** beyond Claude: say so first.

**Every service, what it's for, what it costs and how to set it up is in `smf/services.json`**
(the same words, laid out for people, are in `SERVICES.md`). Read it there; never quote a price
from memory. If a service's `checked` date is more than 90 days old, don't state the price: say when
it was last checked and give them the price page (`source`) to look at.

Say the cost **before** they go and sign up, and what kind of spending it is (`spending`): a
**subscription** charges on a date whatever they use (Metricool, Claude); a **free plan** is never
charged, but **paid plans** renew monthly whatever they use (Apify, ElevenLabs); **prepaid credit**
runs out, possibly slightly over (OpenAI). Never call a reminder or an alert a limit. Nobody should
discover a paid plan halfway through.

For video, also run: `factory.py setup --tier video` (another download; tell them first).

**"Walk me through Metricool"** (or Apify, ElevenLabs, AI pictures, or "help me set up X"): take
that service from `smf/services.json` and go **one step at a time**, waiting for "done" after each:
1. What it does for them, in one sentence about their business, and which of their features need it.
2. What it costs and how spending is limited (`cost`, `limit`). Ask if they want to go ahead.
3. For Metricool, check the `before` list with them first, so they don't pay before their social
   accounts can connect.
4. Each of the `steps`, in order. Say what they should see after it. Screens change: if what they
   see doesn't match, ask for a screenshot with nothing private showing.
5. Adding the key (below), then checking it.
6. Tell them `remove`: how to take the access away later.
The `always` rules hold throughout. If they're setting it up for someone else, the business owns the
account; a helper gets their own login where the service has one, never the owner's password.

**Adding a key:** open `keys.env` for them in their editor (on Mac `open -t keys.env`, on Windows
`notepad keys.env`). Tell them: paste the key after the equals sign, no spaces, no quotes, save,
and say "done". Where a service has two values (Metricool), say which goes where (`key_words`):
the token after `METRICOOL_USER_TOKEN=`, the user id after `METRICOOL_USER_ID=`. Then run `factory.py status` again. Status shows only whether each key is
present and where it came from, never the key. **"Check my keys online"** runs
`factory.py status --verify`: each key is checked with one harmless read. A key that is replaced is
unverified again until it is checked or used. The OpenAI key has no free check, so it shows as
unverified; tell them that's expected.

If they already keep keys in Doppler, they can put `FACTORY_USE_DOPPLER=1` in `keys.env` and
leave the rest blank.

## Step 5. Hand off

When the thing they want shows as ready, say so in one sentence and offer the next step:
onboarding their brand. **Offer to open the onboarding page** (spec rev 12, N8): "Want me to open the page
that sets up your brand? It asks one question at a time." On yes, follow the `onboard-brand` skill (it asks
what the business is and where, then opens the page). Never open it without asking. If the page can't open,
give them the command to run themselves, `factory.py onboard-page`, and carry on in the chat.
Do not list features they did not ask about.

## What "done" looks like

- `factory.py doctor` reports no problems.
- The feature they came for shows **ready** (or **unverified**, which means the key is there and
  will be checked the first time it is used).
- They never saw a stack trace, and they never pasted a key into the chat.
