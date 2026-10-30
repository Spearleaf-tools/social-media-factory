# Daily spark

Once a day: find one fresh thing in one of the brand's pillars, ask the owner one good question
about it, and save their answer to the journal so it can become a topic. The point is to keep
them talking about their subject every day, curious and in flow, so new material never runs out.

It takes two minutes of their time and costs nothing. You do the research with your own web
tools, the same way as the **talking-points** skill, and no key is needed. If a step ever needs a
paid service (an Apify search, for instance), say what it costs and wait for a yes first.

## 1. Pick today's pillar

Name the brand. If there's more than one and you aren't sure which, ask.

Read `factory.py topics inputs --brand <id>`. Take the pillars in turn, a different one each day.
To see which came last, look at the newest notes from Claude in the journal
(`factory.py journal list --brand <id>`). Favour a pillar the journal has said little about lately.

## 2. Find one fresh thing

Search for something from the last few weeks in that pillar: a study, a ruling, a launch, a
number that moved, a debate that's live. Follow **talking-points** step 2: open the page and read
it, go to where the figure was born, and skip roundup pages. Keep:

- what happened, in one sentence, with any figure exactly as published
- who published it, when, and the link

If nothing fresh holds up, use an older, solid source and say it isn't news. Never invent a
finding, a figure or a source to have something to say.

## 3. Ask one good question

Show them, in four lines at most:

> **Today's spark: <pillar name>**
> <what happened, one sentence>. (<publisher>, <date>, <link>)
> <one question>

A good question:
- asks where **they** stand, from their experience. Not a quiz, and not "what do you think about X?"
- connects to their audience or to something they've said before in the journal ("you said
  last week that...")
- can be answered in a minute, out loud or typed, roughly
- has no answer built in. Never put words in their mouth.

Save the spark itself as yours, so tomorrow can pick a different pillar:
`factory.py journal add --brand <id> --note-from-claude --text "Daily spark (<pillar id>): <what happened> (<publisher>, <date>, <link>). Asked: <question>"`

## 4. When they answer

Save their answer exactly as they wrote or said it:
`factory.py journal add --brand <id> --text "<their words>" --asked "<the question>"`
(use `--text-file` for anything long). Ask if any of it is private. Never tidy it, and never
save your follow-up thoughts as theirs.

Then, in one line, say what it could become: "That could be a LinkedIn post on <pillar>. Want me
to add it as a topic?" If yes, add it with `--source-ref journal:<entry id>` (see the main skill,
step 3). If they want to keep going, ask one follow-up question; their second answer gets saved
the same way.

If they skip a day, that's fine. Don't pile up questions or remind them about missed ones.

## Every day, on a schedule

If they want it to arrive by itself every morning, offer to set it up as a scheduled task in
their own Claude app, if this app can do that: a daily task, at a time they choose, whose
instruction is "Use the plan-content skill's daily spark for the brand <id>." Tell them first:

- it runs on their own computer, through their own Claude plan, and uses some of that plan's
  usage each day. There's no other cost
- they can pause or delete it at any time

A scheduled run only does steps 1 to 3: it researches, saves the spark as Claude's note, and asks.
It never answers for them. Their words go into the journal only when they reply themselves. If
this app can't schedule tasks, say so and suggest they just say "daily spark" each morning.

The scheduler for posting (Metricool, the **post** skill) has nothing to do with this. A daily
spark never posts anything.
