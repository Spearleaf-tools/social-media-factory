# The DM funnel: turning comments into subscribers and customers

Last researched: 2026-09-25. Offer to refresh after four months.

The craft behind the `dm-funnel` skill. Someone comments a word under a post ("SEND", "GUIDE"),
and an automatic Instagram message walks them from that comment to their email address and then to
the brand's offers. This is how creators like Sabrina Ramonov grew past a million followers: a
"comment X" ask on most of her videos, and one message flow behind all of them.

## The model

```
many posts, each asking "comment WORD"  ──►  one message flow  ──►  email list + three choices
```

- **One flow, many words.** Every keyword leads into the same flow. The only per-post work is
  telling the automation which post to watch.
- **The words are doors.** A fresh offer or topic draws comments; the word itself matters less.
- **The email is the point.** Messages can only continue for 24 hours after the person last
  tapped or replied. The email is what lets the brand keep talking to them.

## The flow (six messages)

| Step | What it says | Why |
|---|---|---|
| Public reply | "Hey, thanks for reaching out! Check your DMs 😊" (rotate 3 or 4 versions) | Tells them to look, and shows others it works |
| 1. Opener | "Hey! Thanks for reaching out 😊 I've got something for you 🎁 Tap SEND and I'll send it over 👇" + button **SEND IT 📩** | **A tap button, never a link.** The tap is what opens 24 hours of messaging. No tap, nothing more is sent |
| 2. Follow step | "Well, this is embarrassing... 😳 This is just for my followers 👀 Tap FOLLOW at the top, then hit the button below 👇" + **I'm following ✅** | Grows the account. Optional: platforms' spam rules discourage requiring a follow, and the automation can't check it, so the button continues either way |
| 3. Email ask | "Perfect ✅ Drop your best email below 👇 I'll send everything here in chat, plus add you to my free newsletter." | Asking inside the chat converts far better than sending people to a page |
| 4. All set + bonus | "You're all set! 🚀 ... And here's a bonus for you 🎁" + one link button | Delivers what the post promised |
| 5. Three choices | "What would you like next? Tap one 👇" + three quick replies | Everyone picks their own next step |

**The three choices are the brand's ladder:**

| | Maple & Main Bakery (the demo brand) |
|---|---|
| Something to buy | Order a cake 🎂 |
| A free sample | Free recipe card |
| The big step | Book a tasting |

Each choice replies with one short line and one link button.

## Writing rules

- Short lines, casual, one thought per message, a few emoji. No em-dashes.
- The first message says it is automated if the brand works in health, finance or law, and never
  signs as a licensed professional.
- No claims in the messages. The messages deliver; they don't advise or promise results.
- Instagram allows **2 buttons** per message and quick replies of **20 characters or fewer**.
- The brand approves every word before anything goes live.

## What it needs

A tool that can run Instagram message automation: **GoHighLevel** (the build recipe the skill
follows) or **ManyChat** (Pro plan, about $29 a month billed yearly, one account per brand). Tell
the person the cost before they sign up for anything. Check current prices; they change.

## Build shape in GoHighLevel (the short version)

Two automations, because GoHighLevel can't pause one automation to wait for a typed answer:

1. **Comment automation**: triggered by a comment with the keyword on a chosen post → public reply
   → opener → follow step → email ask → sets a contact field "DM Stage" to `awaiting_email`.
2. **Reply automation**: triggered when the person replies in Instagram messages while DM Stage is
   `awaiting_email` and the message contains `@` → saves the message as their email → all set +
   bonus → three choices → each choice's link.

Gotchas: every message after the first must be set to "Reply to DM" (not "Reply to comment");
wait times are in minutes (23 hours = 1380); turn on "Enable messaging + automation" for the
Instagram account in the integration settings; publish the reply automation first.
