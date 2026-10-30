---
name: post
description: Get approved posts and finished videos out. Use when the person says "schedule these", "post the approved ones", "send them to my accounts", "save them so I can post by hand", "make me a ready-to-post folder", "link my accounts", "I have new shorts to schedule", "one short a day", or asks about the TikTok test-and-promote loop. Always shows exactly what would go out and sends nothing until the person says yes. Works with no account at all by saving a ready-to-post folder.
---

# Post

Two ways out. Both only ever take posts the person has **approved**, exactly as approved.

| | Needs | Good for |
|---|---|---|
| **A ready-to-post folder** | nothing | Posting by hand, or handing to someone who does |
| **Scheduling through Metricool** | Metricool's Advanced plan or higher, and its two key values | Set it and leave it |

If they have no Metricool key, do not send them to buy a plan. Offer the folder. If they want
scheduling, **say the cost first**, then use **setup** to add the key.

## The rule of this skill

**Preview, then an explicit yes, then send.** Every command here previews unless you add
`--confirm`. A preview makes no changes anywhere: nothing is uploaded, nothing is drafted,
nothing is scheduled. You never add `--confirm` until the person has seen the preview in plain
words and said yes to it. "Schedule them" at the start of the conversation is not that yes.

## A. The ready-to-post folder

`factory.py export --brand <id>` (add `--check` to see what would be written without writing).

It writes a dated folder inside the brand's Output, under ready-to-post: one subfolder per
post in posting order, with the exact words, the pictures numbered in order, alt text and first
comment when there are any, a schedule sheet, and a plain read-me that says where to paste what
on each network. Running it twice never duplicates anything. Tell them where the folder is, the
way they would find it, and offer to open it. Then say: "Once they're up, tell me which ones and
send me their links, and I'll keep track of how they do" (see check-results, `by-hand.md`).

## B. Scheduling

**First time only: link the accounts.**
`factory.py accounts --brand <id>` lists the brands in their Metricool account and which
networks each has connected. Ask which one is **this** brand. Then ask which voice posts where,
and save it: `factory.py accounts --brand <id> --provider-brand-id <id from the list> --map person=instagram,linkedin --map company=facebook --confirm`.
**Never guess a match from a similar name.** If a network is not connected in Metricool, they
connect it there; the Factory cannot. An account that is not linked is simply not posted to.

**Then, each time:**
1. `factory.py schedule --brand <id> --batch <batch>` previews. Read it and tell them, plainly:
   how many posts, to which accounts, on which days and times, and **anything held back and
   why**. The gates, each with its own plain reason: not approved; changed since it was
   approved; a rule broken; the time is in the past; facts unverified and not acknowledged; a
   picture missing or not cleared for publishing; an account not linked or not connected.
2. Fix what they want fixed (an expired time means re-planning the days with
   `factory.py posts schedule`; a changed post means another look in **review**).
3. When they say yes to what you described: the same command with `--confirm`. For a first run
   with a new account, suggest `--limit 2`, check those two appear in Metricool, then send the rest.
4. Report what was scheduled and what was not, in one short list.

**If a send comes back unclear** (the connection dropped at the wrong moment), that post is
parked and will not be retried by guesswork. Run `factory.py results --brand <id> --only reconcile`:
it looks at Metricool's own calendar, marks the ones that arrived, and frees the ones that did
not. Then preview and send again. This is what makes a double post impossible.

## C. One short a day, from a folder of finished videos

Finished videos go in the brand's video inbox (by default the Edited folder inside the brand's
Inputs; any folder can be set in the brand's settings, including one inside a synced drive).
A description sits next to each video as a text file with the same name; add the platform to the
name for a platform-specific one (`my clip.tiktok.txt`). A video with no description is listed
as needing one: write it from the video's transcript, in the brand's voice, with the same
no-inventing rule, and save it beside the video.

`factory.py shorts --brand <id>` previews a plan: one short per day per account, carrying on
after whatever is already booked, never the same video on two accounts on the same day. Long
horizontal videos are routed as YouTube videos, never as shorts. `--per-day tiktok=3` raises one
platform. `--save` writes the plan as a batch, which goes through **review** like everything
else, then `factory.py shorts --brand <id> --send <batch>` previews the send and `--confirm`
sends it.

## D. Test on TikTok, promote the winner (advanced, off by default)

Only if the brand's settings turn it on (`video.test_and_promote`). It posts **every version of
a clip** to one TikTok account, staggered, waits a day for results, picks the winner by a rule
it shows you (a minimum number of views, then views per hour, then saves and shares), and
schedules the winner to the brand's other accounts. Each step previews first and needs its own
yes: `factory.py promote --brand <id> --step test`, later `--step results`, `--step decide`,
`--step winners`.

Say this plainly before they turn it on: **it posts the same clip several times on purpose.**
That is the point, and it is not for everyone. Each version needs its own description so results
can be matched exactly. It never guesses which result belongs to which version.

## Afterwards

Offer **check-results** a day later: a scheduler accepting a post does not mean the network
published it.

## When you need more

- TikTok is involved (a send, a preview, test-and-promote or its results): read `tiktok-findings.md`.
