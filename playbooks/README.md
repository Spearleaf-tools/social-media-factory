# Playbooks: the rulebooks the writer follows

> last_researched: 2026-06-11 (as of June 2026)

There are two kinds of knowledge in the Factory, and they never mix.

| Kind | Where it lives | What it answers |
|---|---|---|
| **Brand files** | `Client/<brand-id>/` | Who is speaking? To whom? About what? With what proof? |
| **Playbooks** | this folder | How does a good post work on this platform, right now? |

The brand files change from business to business. The playbooks are the same for everyone.
A bakery and a physio clinic follow the same LinkedIn rulebook. What they say inside it is
completely different, because it comes from their own files.

Nothing in this folder names a niche, a customer type or an offer. If you find yourself
wanting to add one, it belongs in a brand file instead.

## What is here

| File | What it is | Who reads it |
|---|---|---|
| `profiles.json` | The platform mechanics in machine-readable form: limits, target lengths, opening pattern, default structure, link, hashtag and call-to-action policy, preferred formats, do and don't | The writer and the planner, on every post |
| `linkedin.md` `facebook.md` `instagram.md` `x.md` | One full rulebook per written platform | The writer, before a batch. You, when you want to know why |
| `short-form-video.md` | Reels, TikTok, Shorts and Facebook Reels under 60 seconds | The script writer |
| `youtube-longform.md` | YouTube videos of roughly 5 to 20 minutes | The YouTube planner and script writer |
| `hooks.md` | First lines and first seconds, as fill-in patterns | The writer, for every opening |
| `why-things-spread.md` | The reasons people save, send and reply | The planner, when choosing an angle |
| `visual-formats.md` | The range of image formats, from polished to raw, and the rotation rule | The planner, when choosing a visual |
| `shapes/` | Eight post shapes (structures) plus `index.json` | The writer, once a shape has been picked |

Every rulebook has the same seven sections, in the same order, so you always know where to look:

1. How reach works there now
2. First lines that earn the click or the watch
3. Post skeletons
4. Length, links, hashtags and calls to action
5. Formats that work
6. What to avoid
7. Applying this to your brand

## How the writer uses them

For each post the planner hands the writer a **contract**: the brand, the identity speaking
(a person or the company), the platform, the topic, the single point to make, the shape, and
the facts, quotes and proof items it may use, each one traced to a file in the brand folder.

The writer then works in this order:

1. Read the platform's entry in `profiles.json` for the hard limits and the default structure.
2. Read the shape file for the beats.
3. Pick an opening pattern from `hooks.md` that the contract can honestly fill.
4. Write, using only what is in the contract.
5. Run the checker. Fix what it flags.

Two rules sit above every playbook:

- **Nothing is invented.** No fact, number, quote, customer or result that is not in the contract.
  If a pattern needs a number and the brand has none, pick a different pattern.
- **The brand's own rules win.** If the brand's style says no hashtags on LinkedIn, there are none,
  whatever the rulebook allows.

## About the examples

Every example in this folder is made up. They use two fictional businesses:
**Maple & Main Bakery** (head baker Ava Lindqvist) and **Stride Physio** (physiotherapist
Tomas Okafor), plus a few obviously generic ones. The names, numbers and stories in the examples
do not describe anyone real. They show the pattern. Your posts carry your real material.

## The `last_researched` convention

Platform rules go stale within months. In the year before these were written, every one of the
six platforms changed something that mattered: how links are treated, how many hashtags are
allowed, what counts as a view, which formats are being pushed.

So every playbook states its age:

- Each `.md` file opens with `last_researched: YYYY-MM-DD` and an "as of" month.
- `profiles.json` and `shapes/index.json` carry the same date in `_meta`.
- A platform fact is always written as something true **as of** that month, never as a law.

The date means "the last time someone checked this against current sources". It is not the
date the file was last edited. Fixing a typo does not change it. Do not move the date forward
unless the facts were actually re-checked.

How much to trust what you read:

| Kind of statement | Trust |
|---|---|
| Hard limits (character caps, the five-hashtag cap, slide counts) | High. The platform enforces them |
| What a platform has said about its own ranking | High for the direction, lower for detail |
| Ordering of signals and formats (saves above likes, carousels above single images) | Good. Several independent large studies agree |
| Exact percentages and multipliers | Low. They come from third-party studies and drift every quarter. Rely on which way they point, never on the exact figure |

## How to refresh them

Ask Claude:

> refresh the playbooks

Claude will then, for each platform:

1. Search the web for the platform's current rules: its own help pages, newsroom and public
   statements first, then recent large studies.
2. Compare what it finds with the rulebook, line by line.
3. Change only what has actually changed, and tell you what changed and why.
4. Update `last_researched` in every file it re-checked, and in `profiles.json`.
5. Leave the structure, the section order and the field names alone, because the tools read them.

You can also ask for one platform: "refresh the Instagram playbook".

A sensible rhythm is every three months, or straight away when a platform announces a change
you have heard about. If the date at the top of a rulebook is more than six months old, treat
its numbers as history and refresh before a big batch.

## If you edit these by hand

- Keep the seven sections and their order.
- Keep `profiles.json` field names exactly as they are. `twitter` stays the key for X.
- Keep the shape ids in `shapes/index.json`. Other parts of the Factory look them up by id.
- No real people, companies, customers or quoted lines from anyone. Invent the example or leave it out.
- No long dashes. Use a comma, a full stop or brackets.
