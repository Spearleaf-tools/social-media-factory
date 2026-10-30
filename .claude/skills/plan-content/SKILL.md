---
name: plan-content
description: Decide what a brand should post about. Use when the person says "plan my week", "what should I post about", "give me topic ideas", "I don't know what to talk about", "plan content for ...", or before writing when no topics have been approved. Also the owner's thinking journal ("save this", "add that to my journal", "keep this private", or whenever they think out loud about their subject), their influences ("who inspires me", "who should I learn from"), and the daily spark ("daily spark", "give me today's question", "keep me in flow", "prompt me every day"). Proposes topics from the brand's OWN pillars, audience questions, offers, facts and proof, gets the person's approval topic by topic, then plans which platform gets which angle, with which visual and which ending.
---

# Plan content

Topics are decided **before** anything is written, and the person decides them. You propose;
they approve, cut or ask for a change. Nothing is written from a topic they have not approved.

## The rule

Every topic comes from the brand's own material and carries a pointer to where (`source_ref`).
You do not invent topics from general knowledge of their industry, and you never invent a
customer, a number or a story to make a topic work. If the material is thin, say what is missing
("you have no audience questions recorded yet; tell me three things customers ask you") and get
it from them. That is the fastest way to better topics.

## 1. Read the brand

`factory.py topics inputs --brand <id>` prints one page: the business, pillars, audience
problems and real questions, offers, verified facts, proof, and research already gathered. Read
it yourself. It labels every line with the pointer to use as `source_ref`.

If they bring their own topic ("write about our new class"), skip to step 3 with that topic.
You still look in the inputs for the facts and proof that back it up.

## 2. Propose

Offer about ten topics as a short plain list: a working title, one line on why this audience
cares, and which pillar it sits under. Spread them across the pillars. Favour real questions
the audience asks: each one is a topic that already has demand.

Want fresh outside material first? Two options, both optional:
- **talking-points** skill: research-backed talking points with named sources. Needs no key.
- **research** skill: what is working on YouTube, what people ask on Reddit and X. Needs an
  Apify key, and tells them the cost first.

## 3. Get a decision on each

Pick a short run name (for example `2026-10-week1`). For each topic they like:
`factory.py topics add --brand <id> --run <run> --title "<title>" --source-ref "<pointer>" --pillar <pillar>`
Add `--lane news` for anything timely (it skips the drip and goes out at once) or `--lane opinion`
for a stance that needs no receipt. Add `--proof PRF-0003` to tie it to proof items.

Then record their decision, one of:
- `factory.py topics approve --brand <id> --run <run> --id <topic id>`
- `factory.py topics cut --brand <id> --run <run> --id <topic id>`
- `factory.py topics revise --brand <id> --run <run> --id <topic id> --note "<what to change>"`

After a `revise`, rework only that topic and show it again. Finish with
`factory.py topics check --brand <id> --run <run>`: it refuses any approved topic with no
source, or whose pointer leads nowhere.

Three approved topics is a good week for one person. More is fine.

## 4. Plan the week

`factory.py plan --brand <id> --identity <identity> --run <run>` gives every approved topic:

- a **different angle (shape) on each platform**, so LinkedIn, Instagram and Facebook each get a
  real post, not one post copied three times;
- a **job** for each slot (reach, trust or lead-gen), mixed so it never asks for the sale three
  times running;
- a **visual kind** that rotates from polished to raw so the feed does not look the same every
  day. A brand with no photos of its own is only given visuals the Factory can draw;
- an **ending** that fits the job: reach asks for a save or a share, trust asks for nothing,
  lead-gen points at one of the brand's real offers.

Show them the plan as a small table in plain words and ask if it looks right. Change what they
want changed. If the brand has two identities (a person and the company), plan each.

If `plan` warns that the platform rules are old, tell them once: "My platform rulebooks were
last checked in <month>. Want me to refresh them first?" Refreshing means re-checking each
platform's current rules with web research and updating the files in `playbooks/`.

## 5. Hand off

"Your week is planned. Shall I write the posts?" Then use **write-posts**.

## The thinking journal

Owners think out loud in the chat. That thinking is the best topic material there is, so keep it.

**When to offer.** When the owner says something about their subject in their own words (a view,
a story, a half-formed idea, a "what I really believe is..."), ask once, briefly: "Want me to save
that to your journal?" Don't ask after every message, and never about something you wrote. If they
say "save this", save it without asking again.

**How to save.** Their words exactly as they said them: same spelling, same rough edges, same
lowercase. Never tidy, summarise, join sentences or fix typos. If you aren't sure which words they
mean, show them what you'd save and ask.
- Short: `factory.py journal add --brand <id> --text "<their words>"`
- Long, or more than one line: write their words to a file under `.factory/tmp/` and use
  `--text-file <file>` instead of `--text`.
- Their answer to a question you asked: add `--asked "<your question>"`. The question is kept apart
  from their words.
- Anything they say is private, or anything personal about other people, money, health or plans
  not yet announced: add `--private`, and ask if you're not sure. Private entries never reach
  planning or a post. `factory.py journal private --brand <id> --id <entry id>` (or `public`)
  changes it later.

**Never save your own words as theirs.** A summary, a suggestion or a question of yours is not
their words. If something of yours is worth keeping (a list of influences to explore, today's
question), save it with `--note-from-claude`, which labels it as yours. Paraphrasing them and
saving the paraphrase as theirs is the one thing this journal must never do.

Tell them in one line what was saved: "Saved to your journal (Oct 23, entry 2)."

**In planning.** `topics inputs` shows each public entry with its date and a pointer such as
`journal:2026-10-23-2`. Use that pointer as the topic's `source_ref`. Older, hand-written journal
pages show as "older notes": cite them as `Brand/journal.md` and quote only what is in quotation
marks. A topic can't come from a private entry; the tools refuse it.

`factory.py journal list --brand <id>` shows them their whole journal, private entries included.

## Influences

If the brand has influences (the people who inspire the owner), `topics inputs` lists them. They
are **reference for structure and format only**: how those people open, pace and lay out a piece.
Never copy their words, titles, catchphrases or frameworks, never present their ideas as the
owner's, and never name them in a post unless the owner asks.

**Suggesting more.** If the owner wants people to explore, offer three to five, each with one line
on what to look at (a format, a structure, a way of opening). Label them every time as
**suggestions from Claude**. Don't add them to the brand settings or present them as the owner's
influences. If the owner wants the list kept, save it with `--note-from-claude`. Only the owner
adds someone to their own influences, during onboarding or by telling you. A change to the
settings goes through the **onboard-brand** skill.

## Daily spark

One fresh thing and one good question a day, so the owner always has new material. Read
[daily-spark.md](daily-spark.md) and follow it.
