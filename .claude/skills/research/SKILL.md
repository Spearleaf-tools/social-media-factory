---
name: research
description: Find out what is working and what people are asking for, so a brand's content is built on real demand instead of guesses. Use when the person says "research", "what's working", "what should I post about", "what are people asking", "study this creator", "how does this account do it", "is this topic worth a video", "find YouTube outliers", "what's on Reddit about X", "what does Google show for X", "pull the facts out of this video", "mine this video", or "find studies on X". Says the cost before spending anything, saves the results inside the brand's own folder, then reads them WITH the person and turns what they choose into topics. Research is for learning structure and demand, never for copying someone's words.
---

# Research

You are helping someone find out what their audience wants and what is working, then turning
that into topics for their own brand. You run every tool. They never type a command.

## The one rule that governs all of it

**Learn the structure and the demand. Never copy the words.**

Research shows HOW a strong video is built, WHAT people are asking, and WHICH topics are alive.
It is never a source of lines, titles, jokes, stories or numbers to reuse. Anything quoted in a
research file is quoted so it can be understood, and it keeps its link.

Say this once, plainly, the first time someone uses research: **they are responsible for how
they use material collected from other people's public posts**, including the rules of the site
it came from and the law where they live. Then carry on. Do not lecture.

## 1. Work out which job they need

Ask one question: **"What do you want to find out?"** Then map it yourself.

| They want to know | Job | Costs money? |
|---|---|---|
| How a short-form creator builds their videos (Instagram, TikTok, YouTube Shorts) | `creator` | a little |
| Whether a topic is worth a YouTube video right now | `youtube --keyword` | a little |
| Which of a channel's videos beat its own normal | `youtube --channel` | a little |
| What people say, ask and complain about, in their own words (Reddit, X) | `listen` | a little |
| A "what people are asking for" report from that listening | `demand` | free |
| What Google shows for a question, and the follow-up questions people ask | `serp` | a little |
| The facts, numbers and lessons inside ONE video | `video` | free |
| Published studies on a question | `papers` | free |

If they are vague ("I don't know what to post"), start with `listen` on two or three words their
customers would use, then `demand`. That is the shortest road from nothing to a list of topics.

Always name the brand. If more than one brand exists and you are not certain which, ask.

## 2. Check it can run

The paid jobs need one key: `APIFY_API_TOKEN`. `factory.py status` tells you whether it is
there. **Never open the keys file and never ask for the key in the chat.**

If it is missing, say: "This needs a free Apify account. Apify has a free plan with a small
monthly credit, which is enough to try all of this. Add the token to your keys file and tell me
when it's done." The `setup` skill walks them through it. Meanwhile `video`, `papers` and
`demand` need no key at all, so offer those.

## 3. Say the cost BEFORE running. Always two steps.

Every paid job is run twice, on purpose.

**First, without `--confirm`.** It prints an estimate and stops. Nothing is spent and nothing is
fetched:

    .venv/bin/python factory.py research listen --brand <id> --term "sourdough starter" --limit 60

**Tell them the price in plain words and wait for a yes:** "Listening on Reddit and X for that
will cost about 15 cents, and can't go over 36. Shall I run it?" It is an estimate, not a quote;
say so if they ask. Most jobs cost a few cents.

**Only after an explicit yes**, run the same command again with `--confirm` added.

Never add `--confirm` on your own judgement, not even for one cent. A yes to one job is not a
yes to the next one. If they change what they asked for, show the new price first.

Keep limits small. The defaults are sensible; a first look rarely needs more. One paid extra
deserves its own warning: `creator --transcripts` (Instagram only) costs roughly eighteen times
as much as the study itself. Prefer running `video` on the two or three videos that matter.

Use plain commands only: no pipes, no `&&`. Quote anything with a space in it.

## 4. The jobs

    research creator  --brand <id> --platform instagram --handle <name> [--limit 30]
    research youtube  --brand <id> --keyword "<topic>" [--keyword "<another>"] [--limit 40]
    research youtube  --brand <id> --channel @<handle> [--limit 40]
    research listen   --brand <id> --term "<words>" [--source reddit] [--community <name>] [--since year]
    research demand   --brand <id> [--latest 3]
    research serp     --brand <id> --query "<question>" [--query "<another>"] [--country us]
    research video    --brand <id> --source "<link or file>" [--opening-seconds 5] [--keep-every-change]
    research papers   --brand <id> --query "<question>" [--since-year 2020] [--contact-email <theirs>]

**Before `video`, ask one thing:** "Is it mostly slides or a screen, or mostly a person
talking?" For slides where numbers matter, add `--keep-every-change` so no changed figure is
missed. For a person talking, leave it off, or the folder fills with near-identical stills.
A long video takes a while to transcribe; tell them it will be a few minutes.

**`papers` and the email.** The wider search for free copies needs a contact email, and it must
be THEIR OWN, given by them. Never make one up and never reuse one from somewhere else. Without
it the search still works.

## 5. Read the results WITH them

Every run lands in its own dated folder inside the brand's folder, under Inputs, then Research,
then the job's name. Tell them it is "in the Research folder inside your brand's Inputs folder"
only if they ask. **Read `summary.md` first.** Then:

- **Lead with what it means**, in two or three sentences. Not the table. "The thing people ask
  most is why their loaf is dense. Three different posts, all stuck on the same point."
- Every summary ends with a **worksheet**. Go through it with them, one question at a time. You
  do the reading; they make the calls.
- **Count, don't vibe.** For every pattern you claim, give the count on each side ("6 of the 8
  strong videos open with a question, 1 of the 8 weak ones"). If you cannot count it, do not
  claim it.
- A score or a verdict is a starting point. "Too thin to say" and "not scored" are real answers;
  never fill that gap with a guess.
- If a note says a tool **needs attention**, tell them that part of the research is unreliable
  today and why, and carry on with the rest.

### Reading a mined video

This is where exactness matters most. **A number is quoted exactly, with its time, or it is left
out.**

1. Open `index.md`. It pairs every kept still with what was being said around it.
2. **Open the stills and read them yourself.** The on-screen text is not written out anywhere,
   on purpose: a machine reading of small type gets numbers wrong. Start with rows marked as
   having a number spoken, then every new scene.
3. Fill in `FACTS.md`. Never round a number, never rebuild one from memory, never combine two
   into a new one.
4. A number that was only SPOKEN is marked "heard, check the audio at [time]". The speech model
   can hear "fifteen" as "fifty".
5. If the video gives a figure without saying where it comes from, write **source not stated**.
   That is the speaker's claim, not a fact, and it stays `unverified`.

## 6. Turn what they choose into topics

Research is only useful once it becomes something to talk about. For each idea they keep, add a
topic to the brand's topic bank (the `plan-content` skill owns the bank) and **give it a
`source_ref`** so anyone can see where it came from:

- From a demand report: `topic_candidates.json` in the report's folder already has one entry
  per theme with its `source_ref` filled in (for example
  `Inputs/Research/demand-report/2030-06-01-sourdough#t01`). Use it as it is.
- From anything else: the run's folder, as written inside the brand's folder.

A topic from research carries **the question or the structure, never the wording.** Their word
for the problem is useful in a title ("dense crumb"). Their sentences are not yours to use. The
brand's ANSWER comes from the brand's own files and what the person tells you, never from the
posts.

## 7. What never happens

- **Nothing is invented.** No made-up statistic, quote, result or source. Thin research is
  reported as thin.
- **What people say online is not evidence.** A popular complaint is a topic, not a fact.
- **A regulated brand** (health, finance, legal) gets a warning at the top of its reports. Nothing
  found in research is permission to make a claim. It goes through that brand's sign-off like
  everything else.
- **One brand's research is never used for another.** The tools refuse it. Do not work around
  that by copying folders.
- **Research stays on their computer.** It is never committed, uploaded or shared unless they ask.

## When something goes wrong

Say what happened and what you are doing about it, in a sentence or two.

| What the tool says | What it means | What you do |
|---|---|---|
| Research is not set up yet | No Apify key | Step 2 |
| Did not accept the key | The token was pasted wrong | Ask them to re-copy the whole token |
| Out of credit | The monthly credit is used up | Tell them; offer the free jobs meanwhile |
| Needs attention | A tool was renamed, repriced or changed | Run `research actors --brand <id>` and tell them which job is affected. The fix is one entry in the actor list; offer to make it |
| Took too long | The run was stopped at its time limit | Try again with a smaller limit |
| It is unclear whether a run started | The connection dropped at the wrong moment | Have them check their Apify console BEFORE you retry, so they do not pay twice |

`research actors --brand <id>` is free, needs no key, and checks every tool against its live
price. Run it if research has not been used for a few months.
