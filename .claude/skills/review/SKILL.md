---
name: review
description: Open the review page so the person can read every post and picture, then approve, edit, turn down or ask for a remake. Use when the person says "let me review", "show me the posts", "I want to approve these", "open the review page", "what did you write", or after write-posts and make-visuals. Runs only on this computer; nothing is sent anywhere. Also handles "remake the ones I flagged".
---

# Review

Nothing the Factory writes goes anywhere until a person has read it and said yes. The review
page is where that happens. It runs on this computer only, in their browser, and sends nothing.

## Open it

`factory.py review --brand <id>` opens the newest batch. Name batches after the command to open
particular ones; several batches open as one session. It prints a local address and opens the
browser. Leave it running while they review; stop it when they say they are done.

Tell them, in plain words, what they will see:

- One card per post: the words as they will appear, where the platform cuts the text off
  ("see more"), the character count, the pictures in order, the day and time planned.
- **Must fix** items in red. A post with these cannot be approved until they are fixed; they can
  press Edit and fix the words right there, and the check re-runs as they type.
- A yellow **unverified** note when the facts in a post could not be checked against their own
  material. They can still approve it, one at a time, by ticking that they have checked it
  themselves. A post whose facts **failed** the check cannot be approved until it is edited.
- Buttons: **Approve**, **Edit**, **Ask for a remake** (with a note saying what to change),
  **Turn down**, **Undo**. "Approve all I have seen" only takes posts they have actually
  scrolled through, never unverified ones.
- Keyboard shortcuts are listed under the button at the top. It works on a phone too.

## What approval means

They approve **exact words and exact pictures**. If anything changes afterwards (an edit, a
different picture, a new first comment), the approval is cancelled and the post needs another
look. Tell them this once; it is why they can trust what goes out.

## After they review

`factory.py posts list --brand <id> --batch <batch>` shows where every post stands.

- **Asked for a remake:** read their note on each (it is saved with the post), rewrite that post
  from its contract with the note in mind (**write-posts**), and add the new version. Do not
  edit an approved post behind their back.
- **Turned down:** leave it. Ask whether the topic should be dropped or tried another way.
- **Approved:** offer the next step in one line: "Schedule these to your accounts, or save a
  folder you can post by hand?" (**post**).

## If the page will not open

Run `factory.py doctor`. If the core packages are missing, use **setup**. If the page says the
batch belongs to another brand, you named the wrong brand; never work around that message.
