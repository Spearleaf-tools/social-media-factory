---
name: onboard-brand
description: Capture a brand so the Social Media Factory can write and design for it. Use when the person says "onboard my brand", "set up my brand", "add a client", "add a brand", "tell you about my business", "change my colours / voice / audience / offers", or when another skill reports that no brand exists yet. Interviews them one question at a time, can read their website first to draft the answers, captures their voice from their own words, and ends with a working brand plus a first sample post and carousel.
---

# Onboard a brand

The goal: in about fifteen minutes, this person has a brand the Social Media Factory can write and design
for, and has **seen it work** on their own brand. Everything after that is optional depth.

## How to run this conversation

- **One question at a time.** Short. Plain. Offer a default or an example so they are never
  staring at a blank.
- **They can skip anything.** Say "skip" is fine and move on. A skipped answer stays a
  placeholder, and `check-brand` lists what is still open. They can come back any time: "continue
  onboarding".
- **Never invent an answer.** If you drafted something from their website, show it and ask
  "is this right?". If they have not told you, it stays blank.
- **Their voice comes from their own words.** You do not describe a voice for them and then write
  in it. You collect real samples and echo those.
- Do not show JSON, file names or commands. Talk about "your brand's settings".

## Step 0. Ask for their material, then open the page

Don't ask "page or chat?" first: the page is the default and the chat is the fallback. The first thing they get
is the question about their material, because what you read from it fills the page in for them.

**Bring what you have (spec rev 13, M2).** Make the folder with `factory.py onboard-page --material` (for an
existing brand, `--material <id>`); it prints the folder's path. Open it for them (Mac `open "<folder>"`, Windows
`explorer "<folder>"`). Both are git-ignored: their files never go to GitHub. Then say, in one message:

> Let's set up your brand. Start with whatever you have, and add more whenever you like. Nothing is required.
> - **On your computer:** a book you wrote, brochures, documents, posts, your logo, photos. I've opened a folder
>   for them: drop them in.
> - **Online:** your website, and links to anything else of yours: a book's page, your YouTube channel, a
>   podcast, a blog, your social profiles, interviews or articles about you. Paste the links here.
>
> Tell me when you're done, or say "skip" and we'll go straight to the questions.

Before reading anything, say: "The Social Media Factory keeps your original files on your computer. What I
read is sent to the AI service running this chat. Nothing is uploaded to GitHub." Then ask: "Is anything
here private, or not for posts?" A file they mark **"don't use"** is never read, and nothing from it may
appear anywhere. The mark is for a whole file: a file mixing public and private parts is split first, or
marked "don't use" as a whole.

**Read what you can, and record it.** PDFs, Word, text, Markdown and web pages: read them (long books in
parts). Spreadsheets as far as you can. Logo and headshot: offered for the look. Photos: listed as "photos
you can use", never as proof. Scanned pages you can't read, audio and video: listed, not read
("recordings can be turned into text after onboarding"). Never say a question is missing from parts you
didn't read.

**Things online.** Public pages only, with your web tools, and never anything that needs a login. Save a
plain-text copy of each page you used into the material folder (named after the site and the page), so it is in
the inventory as `"kind": "web"` and stays with the brand for later.
- **A book:** ask for their own file (the PDF or Word file it was written in, or an ebook they can export) and
  have them drop it in the folder. From a shop's page you can read only the public description; say so.
  Never download a copy from anywhere else, and never buy anything.
- **YouTube, podcasts, other recordings:** list each link in the inventory as `"not read yet"`. Their public
  titles and descriptions can be read. The recordings themselves can be turned into text after onboarding.
- **Their blog and social profiles:** what they wrote themselves is the best voice material there is, used only
  as their exact words, each offered for a yes.
- **Interviews and articles about them:** a fact from one counts only once they confirm it. Only lines they said
  themselves may be quoted, never the writer's words.

**Then one question, only if the material didn't answer it** (show what it said, to confirm, instead of asking
again): "What's your business, and where are you?" (for example "auto repair in Leeds",
"breathwork coaching, online"). It picks the starter pack and fills the page's first screen.

If they gave a website: read the home page, the about page, and the services or products page with your
web tools. Draft: what the business does and for whom, the audience, the offers, the brand name as written,
and its colours (from the site's styles: background, main text, the one accent colour). **Anything you
drafted is a guess until they confirm it.** Never copy testimonials, customer names or numbers from the site
into the brand's facts without asking: "Are you happy to state this in public, and where does it come from?"
Never read private or logged-in pages unless they ask.

**Starter pack.** Pick the closest bundled pack in `smf/onboarding_page/starter_packs.json` from what
they said (by its `matches`), or none. A pack suggests only what's general to their trade, and only for the
allowlisted questions (who they reach, what's in their way, myths, mistakes, rule starters, platforms, plus
palettes and a font pair). It never answers the questions customers really ask, the objections they hear,
their own steps, their beliefs, story, offers or proof. **No pack fits?** You may suggest from their own short
description, but only for those same allowlisted questions, never anything you'd have to invent about them.

**Open the page (spec rev 12, N8).** As soon as the draft is written, open the page as "On the page" says,
without asking which they prefer, and say in one line: "I've opened a page in your browser that asks one
question at a time, with what I found ready for you to check. Prefer to do it here in the chat? Just say so."
If the page cannot open, carry on in the chat.

If they chose the chat, carry on with Step 1 and offer pack suggestions there the same way ("Want some
suggestions for auto repair? They're general, so tell me which are true for you"). Myths and mistakes are
kept only when they say they've really seen them; otherwise they're post ideas.

## On the page

1. Write the draft to `.factory/tmp/` in the answers file's shape (`smf/onboarding_page/intake.schema.json`),
   then start the page so it keeps running: `factory.py onboard-page --draft <file>` (add `--brand <id>` to
   update an existing brand). Run it in the background; it never ends on its own. Tell them the page is open.
   The page is design B, one question at a time; `--layout one-page` opens design A only when they ask.
   - **The first screen:** `business_start` with `what`, `where` and `website` as they told you
     (`"source": "draft", "origin": "chat"`). The page shows them filled in, to edit.
   - **The pack:** `starter_pack` = `{"id": "<pack id>", "version": <file version>}`. No pack fits but
     you suggested from their description: `{"id": "custom", "suggestions": {"suggestions": {...},
     "topic_ideas": {...}, "palettes": [...], "font_pair": {...}, "video_ideas": [...]}}`, with
     `suggestions` keyed only by the allowlisted question ids (`audience_who`, `audience_way`, `myths`,
     `mistakes`, `rules`, `platforms`). The page shows these behind "Draft this for me", marked "Suggested
     from what you told us". Nothing else may carry `"origin": "description"` or `"starter-pack"`: the page
     refuses the draft.
   - **The inventory (rev 13, M3):** put `answers.inventory` in the draft: `sources` (each `{"id": "src-1",
     "name", "kind": "pdf|document|text|spreadsheet|web|image|audio|video|other", "status": "read|partly
     read|couldn't read|not read yet", "covered": "pages 1-48 of 52", "revision": "<fingerprint>",
     "dont_use": true|false, "note"}`), `fields` (by the page's field id: `{"coverage": "found|partly|missing|
     your words needed"}`; a question the material can't honestly answer for them, like why they started, is
     "your words needed"; a pack suggestion is never "found") and `made`. The page then opens on "What we
     found" and asks what's missing first.
   - **Drafts from a document** carry `"origin": "document"` and `"refs"` (`"src-1 rev <revision> p.12
     (printed 10)"`, a heading and paragraph for a document, sheet and range for a spreadsheet). Without refs
     the page refuses the draft. Nothing may point at a "don't use" source.
   - **Their own writing for beliefs, others/us and non-negotiables (questions 14, 16, 17; F8 change, M6):**
     only as quotes or close extracts of what **they** wrote or said (or the brand in its own voice), never
     a testimonial, another author, an employee or anyone unclear. Each item: `"source": "draft", "origin":
     "document"` (or `"website"`), `"quoted": true, "said_by": "owner"` (or `"brand"`), `"excerpt": "<the exact
     words>"`, `"refs": [...]`, `"generator": "claude-from-document"` (or `"claude-from-website"`). Never
     reword into a new claim; if the material supports only part (the "others" side but not the "us" side),
     leave the rest empty and mark the question "partly". Never from a pack, their description or your own idea.
     The page shows "From <your book>, page 12. Your own words, quoted. Please confirm each one."
   - **When the brand is built,** run `factory.py onboard-page --keep-answers <id>`. It keeps the whole
     answers file (confirmed, skipped and waiting) and the inventory in `Client/<id>/_state/`, and moves the
     material into `Client/<id>/Inputs/Material/` without overwriting anything.
   - **Website drafts** go in the answers as today (`"origin": "website"`); add `"refs": ["website: /about#our-story"]`
     (the page's address and the section, spec M2) so the page can say where.
   - The page asks five steps first (spec rev 14: `five_steps` and `one_more` in `smf/onboarding_page/fields.json`);
     every other question is in "Make it better", any time. Every core answer they leave unconfirmed is a placeholder.
   - **Colours:** put every distinct colour you found in the site's styles in `colours.found`
     (hex codes, at most 12), as well as your best guess for background, text and accent. The page
     offers them as swatches; the person decides which plays which part.
   - **Follow-up notes:** for each drafted answer that could belong to anyone ("we care about
     quality"), add one short question under `followups`, keyed by the page's field id
     (`smf/onboarding_page/fields.json`), next to `answers`. Match it to what's missing: a belief
     with no reason, "What happened that convinced you?"; advice with no situation, "Can you describe
     one real example?"; a result with no evidence, "What changed, and how do you know?"; anything
     else, "Give one example from your own work." Ask about a real past time, never "usually" or
     "would", and never hint at the answer. At most one per answer.
   - Don't mention paid services while they're answering. If they want to answer by talking, the page's
     Talk button explains it; set-up of anything paid waits for Step 4.
2. Run `factory.py onboard-page --wait` and let it wait. It returns `complete` the moment they
   click Finish, or `still answering` after about nine minutes: then simply run it again. Do not
   ask them to come back and say "done".
3. On `complete`: `factory.py onboard-page --brand-answers .factory/tmp/brand-answers.json`. It
   prints the name, the voice samples file, the placeholders and anything to settle in the chat.
   Settle those in the chat first. **A placeholder stays a placeholder: never fill it yourself.**
   If a confirmed answer still reads generic and had no follow-up note on the page, ask its one
   follow-up now (the same rules as above); they can keep the answer as it is.
4. Do Step 2 with that answers file (`new-brand --name "<the confirmed name>" --answers ...`, or
   `update-brand`). The voice samples file IS `voice-samples.md`, word for word: copy it, do not
   tidy it. If step 3 printed a proof file, add each item to the proof library with
   `factory.py proof add --brand <id> --kind ... --title ... --detail ... --source ... --may-publish ...`
   exactly as listed (add `--names-third-party` where it says true); never change what they said may
   be published. After each `proof add`, record it: `factory.py onboard-page --proof-added <item id> <PRF id>
   --brand <id>` (the item id is the `id` in the proof file). Items already recorded are left out of the proof file,
   so nothing is added twice. Then Step 3's demo. **No starter pack fitted?** Write up to three possible video topics from their
   confirmed answers into the brand's `topic_ideas` with `update-brand` (each `{"id", "field", "text", "generator":
   "claude-from-answers"}`, a topic to ask them about, never a fact); fewer is fine, never invent to reach three. Then
   `factory.py onboard-page --summary <id>`, and open the summary page it prints for them.
5. Hand the page the result: a small JSON file with `{"version": 1, "ok": true, "brand": "<id>",
   "demo_image": "<path of the first demo picture, from the Social Media Factory folder>", "summary":
   "Client/<id>/brand-summary.html", "steps": {"saved": true, "checked": true, "sample": true},
   "message": "Your brand is ready."}`, then `factory.py onboard-page --result <file>`. Set a step
   to true only if it really happened. If something needs them, send `"ok": false` and a one-line
   `message` instead, and talk to them in the chat.
6. Run `factory.py onboard-page --wait` once more. It returns `first-post` (offer to write their
   first post now) or `done`. Then `factory.py onboard-page --stop`, and carry on with Step 4 in
   the chat.

**A file marked "don't use" after it was read:** run `factory.py onboard-page --dont-use <source id> --brand
<id>` straight away, before anything else. It takes everything from that file out of the kept answers (and an open
page), out of the brand's settings, remakes the brand files and checks them; it never prints the old wording.
Settle anything it lists in the chat (a person or an offer, which the brand never removes by an update), and remove
any proof library items it names by hand, then run it again with `--settled`. If a step failed it stays pending;
fix that and run it again (it finishes the same plan). Until it says "Done", the brand won't be built.

**Add more, any time (rev 13, M5).** When they say "add more to my brand" or "continue onboarding": open
their folder (`--material <id>`), read only new or changed files (and rereads they ask for; never a "don't
use" file), update the inventory, and write a draft of only what's new. Then `factory.py onboard-page --brand
<id> --draft <file>`. The page opens with the brand's kept answers: confirmed stay confirmed, waiting stay
waiting. New material never replaces an answer: where there is one, the page shows the new words beside it
("Your new material says…") and the owner decides. The page leads with the five steps (anything new in them first),
then anything new in Make it better. With no new material, `--brand <id>` alone reopens it to answer what's missing.

**"Make my brand better"** (the last screen and the summary say this): `factory.py onboard-page --brand <id>`
and point them to Make it better on the page, or ask those questions here, one at a time, under the same rules.
They're all optional. Finish as usual: build with `update-brand`
from `--brand-answers`, then `--keep-answers <id>` again.

**Who inspires them** (`influences`, in Make it better after signature phrases): "Who inspires you, or whose content
do you love? A name is enough; add what you like about them if you want." Only their own answers go there, or a
labelled quote of their own writing they say yes to, one by one. If they ask you to suggest people, give three to five,
each labelled as **a suggestion from Claude**, and say none is saved as theirs unless they name it themselves. Never
put a suggestion into `influences`. Planning and writing use the list for structure and format only, never words.

If they click **Finish in chat**, `--wait` still returns `complete`: build from what they confirmed
and ask what's left of the five steps and the rules question in the chat; offer Make it better, never insist. If
the page cannot open, carry on in the chat; nothing is lost.

## Step 1. The chat route: the same five steps as the page

If they chose the chat, ask the page's own questions (`smf/onboarding_page/fields.json`, each with its `ask`, `why`
and `example`) in the page's five steps (spec rev 14, `five_steps`): 1 your business (name, what you do and for whom,
and, optional, the website or handle (their @name) for pictures); 2 your ideal customer; 3 what you sell (the main
offer); 4 what you want to make (who speaks first, then what to make and where they'll post; the goal is optional); 5
how you sound (a few things they really wrote or said). Then "one more thing" (`one_more`): any rules their posts must
follow, short and skippable. One at a time. Everything else is "Make it better" (including "How do people find you
today?"): offer it after the brand is built, never as more
required questions. Five answers are **needed to write their first post** (`needed`: name, what you do, who they're
trying to reach, who speaks, a few things they've written or said); say so when you ask them, and if any is skipped,
name what's still needed before you build. They can still skip. Use the platforms' own words (carousel, handle, Reels); explain one in a few words only if they ask. The same rules
as the page, word for word:

- **A draft from their website or material** is shown with where it came from ("From your website's About page:
  … Is this right?"); it counts only when they say yes or change it.
- **Their own quotes** (beliefs, what they do differently, non-negotiables): read each one with its file and page,
  and ask for a yes on each, one at a time. Never a quote they didn't write or say; never anything made up.
- **Pack suggestions** only for the allowlisted questions, and only when they ask ("Want some suggestions for auto
  repair?").
- **Skip** is always fine; a skipped question stays a placeholder.
- **Voice samples:** ask for three to five things they really wrote or said, pasted word for word, never tidied.
- "One more thing", the rules question: anyone they must never name, claims to avoid, and words they hate seeing.
  Short and skippable.

Keep their answers in `.factory/tmp/chat-answers.json`, in the answers file's shape
(`smf/onboarding_page/intake.schema.json`, the same as the page writes): an answer is `"status": "confirmed"` only
when they said yes; a draft they haven't confirmed stays `"unconfirmed"` with its `refs`; a quote carries its own
`"accepted": true` only after its own yes. Keep `"state": "in_progress"` while asking, and set it to `"complete"`
only when you have been through the five steps and the rules question. "Make it better" and Go deeper are offered
at the end, the same as the page.

## Step 2. Create the brand

**Chat route only** (the page route already has its answers file from its step 3): turn the chat's answers into
the brand's answers, through the same checks as the page:
`factory.py onboard-page --brand-answers .factory/tmp/brand-answers.json --answers-file .factory/tmp/chat-answers.json`.
It prints the name, the voice samples file, the placeholders and anything to settle; settle those first. Then, on
either route:

- New brand: `factory.py new-brand --name "<the confirmed name>" --answers .factory/tmp/brand-answers.json`
- Existing brand: `factory.py update-brand --brand <id> --answers .factory/tmp/brand-answers.json`

The voice samples file it printed IS `voice-samples.md`, word for word. On the chat route, keep the answers next
(for adding more later, and so proof knows where it came from):
`factory.py onboard-page --keep-answers <id> --answers-file .factory/tmp/chat-answers.json`. Only then add any proof
it printed with `factory.py proof add` and record each with `--proof-added`, as on the page route.

Fill the long-form files in their brand's `Brand/` folder from the conversation (`business-profile.md`,
`brand-voice.md`, `audience.md`, `pillars-and-offers.md`). Any fact they are happy to state in public goes into
`Studio/facts.json` with where it comes from. A number with no source does not go in.

Run `factory.py check-brand <id>` and `factory.py sync-brand <id>`. If check-brand reports a problem, fix the settings
and tell them only if you need something from them.

The same ending as the page route: **no starter pack fitted?** Write up to three possible video topics from their
confirmed answers into `topic_ideas`, exactly as the page route's step 4 says (`"generator": "claude-from-answers"`,
never a fact). Then `factory.py onboard-page --summary <id>`, and open the summary page it prints for them.

## Step 3. Show them it works

Run `factory.py visuals --brand <id> --demo` and show them the result: their name and real layouts, in their
colours if they chose them, otherwise the default colours (say so: "these are the starter colours until you pick
yours"). Then offer the first real thing: "Want me to write your first post now?"

## Step 4. Accounts, only for what they chose

Run `factory.py checklist --brand <id>`. Tell them, in one short list, which accounts their
choices need, **what each costs**, and that writing, visuals and review need none at all. The
full page is saved in their brand's folder. Do not send them to sign up for anything they did
not ask for. When they have a key, use the `setup` skill's "adding a key" steps.

If they chose scheduling and the Metricool key is in place, link their accounts:
`factory.py accounts --brand <id>` lists the brands and connected networks in their Metricool
account. Ask which one is this brand, and which identity posts to which network, then save that
with `update-brand`. **Never guess a match from a similar name.** An account that is not linked
is simply not posted to.

## Step 5. Optional depth (offer, never push)

- **Pillars:** three to five subjects they could talk about for a year.
- **Offers:** what they sell, who for, and the next step they ask people to take.
- **Proof:** results, testimonials, screenshots, photos. Each gets a source and a clear answer
  to "may we publish this, anonymised or not at all?". Use `factory.py proof add`.
- **Recordings:** where their podcasts or videos live. Their transcripts become the best source
  of both voice and topics.

## Done means

- `check-brand` reports the brand ready, or lists only things they chose to skip.
- They have seen their own brand rendered.
- They know what is free, what costs money, and what to do next.
- Nothing in the brand's files was made up by you.
