---
name: check-results
description: Find out whether scheduled posts really went out and how they performed. Use when the person says "did my posts go out", "check my posts", "how did last week do", "what's working", "show me my numbers", "why didn't that post", or a day or two after scheduling. Also when they posted by hand from a ready-to-post folder: "I posted these", "here are my numbers". Only ever reads from the scheduling service. Also settles any send whose outcome was unclear, so nothing is ever posted twice.
---

# Check results

A scheduler saying "accepted" is not a network saying "published". Accounts get disconnected,
videos get refused, a login expires. This skill looks, and tells the person what it found in
plain numbers. It only ever **reads** from the scheduling service.

Checking what went out and fetching numbers needs the Metricool key. **People who post by hand
from a ready-to-post folder need no key:** they tell the Factory which posts went up and type in
their numbers. Read `by-hand.md` in this folder for that.

## Run it

`factory.py results --brand <id>` does four things (`--days 30` by default; `--only` runs one):

1. **Settles unclear sends.** Any post whose send never got a clear answer is looked up on
   Metricool's own calendar: there means it is marked as scheduled, not there means it is freed
   to send again. Until this runs, those posts stay parked, which is how a double post is avoided.
2. **Did it go out?** Posts whose time has passed but which the network refused, each with the
   network's reason. "Could not look" is reported as exactly that, never as "all fine".
3. **Saves the numbers on this computer.** Schedulers only keep a short window of post results.
   Each run adds to a permanent local record inside the brand's folder. Nothing is ever rewritten.
4. **The summary.** Plain numbers per account: what went out, views, saves, shares, comments,
   the three most viewed and the three least viewed. Posts up less than two days when measured,
   and posts with no view count, are left out of the least viewed, and the summary says how many.

## How to report it

Lead with what it means, not with a table.

- "All 12 went out. Two did clearly better than the rest, both about fixing a dense loaf."
- "Nine went out. Three Instagram posts were refused because the Instagram account is
  disconnected in Metricool. Reconnect it there and I will reschedule them."

Then one or two numbers they can act on, and what you suggest doing next. Never pad with
telemetry. If a number is missing for a platform (some networks do not report saves through the
scheduler), say it is missing; do not estimate it.

## If something was refused

Tell them the network's reason in plain words and what fixes it. Re-sending is always a new
preview and a new yes in **post**. Never resend automatically.

## If a send cannot be settled

Very rarely the calendar cannot tell two posts apart. The post stays parked. Ask the person to
look in Metricool and tell you whether it is there, then record their answer:
`factory.py results --brand <id> --settle <post id> --arrived yes --confirm`
or the same with `--arrived no`. This changes only this computer's record.

## Turning results into better content

After a few weeks there is enough to learn from. Look for what the best posts share (the
subject, the shape, the first line, the kind of picture) and say it as **one** thing to try more
of next week. Feed that into **plan-content**. For short-form video, the **write-scripts**
skill's audit does this properly, one variable at a time.

This runs when they ask. If they want it every morning, the Claude desktop app can schedule a
task that says "check my results for <brand>"; offer to set that up rather than installing
anything on their computer.
