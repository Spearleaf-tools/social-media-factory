---
name: write-posts
description: Write social posts in a brand's own voice for Facebook, Instagram, LinkedIn and X. Use when the person says "write posts", "write a LinkedIn post about ...", "build a batch of posts", "write this week's content", "turn this into posts", or after plan-content. Writes each post from a contract built from the brand's own files, checks every draft against the platform's rules, the brand's rules and the brand's facts, and files the good ones into a batch ready for review. Never invents a fact, number, quote or customer.
---

# Write posts

You are the writer. The Factory gives you a **contract** for each post and **checks** what you
write. You never write from a blank page, and you never write from general knowledge of the
person's industry.

## Before you write

You need approved topics and a plan. If there are none, use **plan-content** first (or, if they
gave you one specific topic, add and approve just that one, then plan it).

## For each post in the plan

**1. Get the contract.**
`factory.py contract --brand <id> --identity <identity> --platform <platform> --run <run> --topic <topic id>`

It tells you, for this one post: who is speaking and how they sound, **their own words** to echo
(from their voice samples and transcripts), who they are talking to on this platform, the
platform's mechanics (length, how the first line works, links, hashtags), the shape to fill beat
by beat, the ending that fits the job, the brand's style rules and never-mention list, and
**every fact you are allowed to use** with its source.

**2. Write it. The contract is the whole world.**
- Use only facts, numbers, names and stories that are in the contract or that the person told
  you in this conversation. If you need something that is not there, **ask them**; do not fill
  the gap. A strong post with no number beats a post with an invented one.
- Sound like their samples: their sentence length, their words, their habits. Do not improve
  them into marketing language.
- One thought per line where the platform rewards it. First line does the work: most readers
  only ever see that.
- A person says "I". A company says "you" and "we". The contract says which.
- A topic from their **journal** comes with the entry in the contract. Echo their words, but only
  entries marked as their words count as theirs; a note from Claude is context, never a quote.
  Private entries are never in a contract, and a draft that repeats one is stopped.
- **Who inspires them** (when the contract lists anyone) is for structure and format only. Never
  copy their words, titles, catchphrases or frameworks, and don't name them unless the owner asked.
- The same topic on another platform is a **different post** with a different shape, not a trim
  of this one.

**3. Check and file it.** Save the draft as a text file under `.factory/tmp/`, then:
`factory.py posts add --brand <id> --batch <batch name> --identity <identity> --platform <platform> --draft <file> --run <run> --topic <topic id> --shape <shape id>`

For an X thread, put the following tweets in a second file separated by lines of `---` and add
`--thread <file>`.

The check reads the draft against: the platform's limits, the brand's rules (never-mention
names, banned words, its punctuation rules, regulated terms), **every number against the brand's
facts, research files and proof**, repeats of things already written, and whether the ending
suits the job.

- **Problems** mean it was not filed. Fix them and add it again. If a number "does not trace",
  either it is true and unrecorded (ask them where it comes from, then
  `factory.py facts add --brand <id> ...` so it is on file), or it is not supportable: take it out.
- **Craft notes** are advice (a first line that promises nothing, no concrete step). Take them
  seriously; they do not block.
- **Sourcing** comes back `passed`, `unverified` or `blocked`. `unverified` means nothing is
  wrong but something could not be checked (a customer story with no proof item, for instance).
  It is filed, it is labelled on the review page, and the person must tick an acknowledgement to
  approve it. Tell them which posts are unverified and why. Never describe an unverified post as
  checked.

## When the batch is written

1. `factory.py posts schedule --brand <id> --batch <batch> --start <YYYY-MM-DD>` plans the days:
   one subject, one account per day, rotating, so their feeds never all say the same thing at
   once. Timely (news lane) posts go out on the first day. Nothing is sent; these are planned
   times only.
2. Instagram posts need a picture before they can be approved. Offer visuals for the batch
   (**make-visuals**), then attach them:
   `factory.py posts attach --brand <id> --batch <batch> --id <post id> --media <files>`
3. Tell them in two or three sentences what you wrote: how many posts, for which accounts, across
   which days, and anything unverified. Then: "Ready to look them over?" (**review**).

## Writing five or more

Write them one platform-and-topic at a time, each from its own contract. Do not batch-generate
variations from one draft. If you use subagents to go faster, each one gets exactly one
contract and the rule above: the contract is the whole world.

## What good looks like

Every post could only have come from this brand. Every number has a source on file. Nothing
names anyone on the never-mention list. The person reads it and says "that sounds like me".
