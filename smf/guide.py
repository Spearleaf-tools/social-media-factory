"""guide.py - GUIDE.md is made from the same table as the menu and the status screen.

    python factory.py guide            write GUIDE.md
    python factory.py guide --check    exit 1 if GUIDE.md is out of date (the tests run this)

The words that explain each section live in smf/features.json (sections[].about / .owner and
each feature's name, say, output, needs). This file only lays them out, so the guide cannot
promise something the Social Media Factory does not do.
"""
from __future__ import annotations

import os

from smf import bootstrap, brands, keys, services, status

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(ROOT, "GUIDE.md")

# Which outside service each key belongs to, in a few words; from smf/services.json, the one price list.
SERVICE_FOR_KEY = {k: "%s (%s)" % (s["name"].split(" (")[0], s["short"])
                   for s in services.load()["services"] for k in s["keys"]}

INTRO = """# Social Media Factory: the guide

This is the map of everything the Social Media Factory does, section by section. You do not need to read it
to use the Social Media Factory: open the folder in Claude and say **start**. Read it when you want to know
what is possible, what each part needs, or how to split the work across a team.

Installing it is covered in [README.md](README.md). This guide is made from the same table the
Social Media Factory's own menu uses, so if it is listed here, it is in your copy.

## How it works, in one minute

1. **You talk, Claude runs the tools.** You never type a command. Say what you want in your own
   words; the phrases under "You can say" are examples, not passwords.
2. **Everything starts from your brand.** The onboarding interview captures who you are, in your
   own words. Every post, script, picture and clip is made from that, for that brand only.
3. **It never invents.** No made-up facts, numbers, quotes, customers or results. It writes from
   your files and what you tell it. What it cannot trace to your material is labelled
   *unverified*, and you decide.
4. **Nothing goes out without your yes.** A preview sends nothing at all. You approve exact words
   and pictures; change them and you approve again.
5. **Your brand stays on your computer.** Your keys too.

## The order most people work in

**Set up** once → **onboard** your brand once → then, each week: **decide** what to talk about →
**write** → **make visuals** (and **clips**, if you record) → **approve** → **post** → **check
results**, which feeds next week's topics.

One person can do all of it. On a team, each section below says who usually owns it.

## What it costs

The Social Media Factory is free. Writing, scripts, visuals, review and the ready-to-post folder need **no
account at all** beyond Claude. The outside services (Metricool, Apify, ElevenLabs, and OpenAI for
AI-made pictures) are optional, and Claude tells you the cost before you sign up for any of them.

What each is for, what it costs (with the date the price was checked), how to limit what you spend,
and how to set it up step by step: **[SERVICES.md](SERVICES.md)**. Ask Claude for **"my accounts
checklist"** and it lists only what your choices need, or say **"walk me through Metricool"** (or any
of the others) to set one up together.
"""

OUTRO = """## Words used in this guide

| Word | Meaning |
|---|---|
| **Brand** | One business or person the Social Media Factory makes content for. Each has its own folder, voice, colours, accounts and records. There is no default brand |
| **Identity** | Who is speaking inside a brand: a person (says "I") or the company (says "you" and "we") |
| **Brand kit** | The brand's colours, name stamp, fonts, logo and photos |
| **Pillar** | A subject the brand could talk about for a year |
| **Topic** | One thing to talk about this week, always pointing at where in the brand's material it came from |
| **Shape** | The structure of a post (three tips, a myth against reality, five lessons). A topic gets a different shape on each platform |
| **Job** | What a post is for: reach, trust or leads. It decides how the post may end |
| **Contract** | The brief for one post: who is speaking, to whom, the platform's rules, the shape, and every fact that may be used |
| **Sourcing** | Whether a post's facts were checked against the brand's own material: passed, unverified or blocked |
| **Batch** | A set of posts reviewed and scheduled together |
| **Drip** | The schedule rule: one subject, one account per day, rotating, so feeds never all say the same thing at once |
| **Proof** | Results, testimonials, screenshots, photos and facts, each with a source and a "may we publish this" answer |
| **Cut list** | The clips chosen from a recording: each body with its hooks, the exact words the cuts start and end on |
| **Hook** | The opening of a clip or post. In clips it is always a line the person really said |
| **Version (variant)** | One of several different-looking renders of the same clip |
| **Preview (dry run)** | Showing exactly what would be sent while sending nothing at all |

## When something goes wrong

Say **"check my setup"**. Claude runs a self-test that actually uses each piece, and fixes what
it finds. If a posting record, a brand file or a batch is reported as damaged, the Social Media Factory stops
on purpose so nothing goes out twice; tell Claude and it will repair it from the scheduler's own
calendar. It will never delete something to make an error go away.

## Keeping it current

Platform rules change every few months. Each rulebook in `playbooks/` carries the date it was
last researched. Ask Claude to **"refresh the playbooks"** and it re-checks each platform's
current rules with web research and updates them.

"""


def _attribution():
    """The credit line lives in LICENSE and nowhere else in the code; the guide quotes it."""
    try:
        with open(os.path.join(ROOT, "LICENSE"), "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().lower().startswith("built by"):
                    return line.strip().split(". http")[0].rstrip(".") + "."
    except OSError:
        pass
    return ""


def _needs_line(feature):
    needs = feature.get("needs", {})
    parts = []
    services = []
    for k in needs.get("keys", []):
        s = SERVICE_FOR_KEY.get(k, k)
        if s not in services:
            services.append(s)
    if services:
        parts.append("an account: " + "; ".join(services))
    if "video" in needs.get("tiers", []):
        parts.append("the video tools (a second download; Claude installs them when you first ask for video)")
    if needs.get("brand"):
        parts.append("an onboarded brand")
    for k, what in (needs.get("optional_keys") or {}).items():
        parts.append("%s only for %s" % (SERVICE_FOR_KEY.get(k, k).split(" (")[0], what))
    return ", ".join(parts) if parts else "nothing"


def build():
    data = status.load_features()
    out = [INTRO]
    n = 0
    for section in data["sections"]:
        features = [f for f in data["features"] if f["section"] == section["id"] and f.get("built")]
        if not features:
            continue
        out.append("---\n\n## %d. %s\n\n%s\n\n**Who usually owns it:** %s\n" % (n, section["name"], section["about"], section["owner"]))
        n += 1
        for f in features:
            out.append("### %s\n" % f["name"])
            out.append("- **You can say:** %s" % ", ".join('"%s"' % s for s in f.get("say", [])))
            out.append("- **You get:** %s" % f["output"])
            out.append("- **It needs:** %s" % _needs_line(f))
            tools = "skill `%s`" % f["skill"]
            if f.get("verbs"):
                tools += "; commands " + ", ".join("`%s`" % v for v in f["verbs"])
            out.append("- **Behind it:** %s\n" % tools)
    unbuilt = [f["name"] for f in data["features"] if not f.get("built")]
    if unbuilt:
        out.append("---\n\n## Not in this copy yet\n\n" + "\n".join("- %s" % u for u in unbuilt) + "\n")
    out.append("---\n\n" + OUTRO)
    credit = _attribution()
    if credit:
        out.append("---\n\n" + credit)
    return "\n".join(out).rstrip() + "\n"


USAGE = """
python factory.py guide            write GUIDE.md from smf/features.json
python factory.py guide --check    only check GUIDE.md is current (exit 1 if it is out of date)
"""


def _current(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def main(args):
    opts, _words, rc = bootstrap.read_options(args, "guide", USAGE, flags=("--check",))
    if rc is not None:
        return rc
    text = build()
    services_text = services.markdown()           # SERVICES.md: the outside services, from smf/services.json
    if opts.get("--check"):
        stale = [name for name, path, want in (("GUIDE.md", GUIDE, text), ("SERVICES.md", services.MARKDOWN, services_text))
                 if _current(path) != want]
        if stale:
            print("%s out of date. Run: python factory.py guide" % (" and ".join(stale) + (" are" if len(stale) > 1 else " is")))
            return 1
        print("GUIDE.md is up to date.")
        return 0
    brands.write_text_atomic(GUIDE, text, newline="\n")
    brands.write_text_atomic(services.MARKDOWN, services_text, newline="\n")
    print("Wrote GUIDE.md (%d lines) and SERVICES.md (%d lines)." % (text.count("\n"), services_text.count("\n")))
    return 0
