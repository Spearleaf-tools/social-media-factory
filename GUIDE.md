# Social Media Factory: the guide

This is the map of everything the Social Media Factory does, section by section. You do not need to read it
to use the Social Media Factory: open the folder in Claude and say **start**. Read it when you want to know
what is possible, what each part needs, or how to split the work across a team.

Installing it is covered in [README.md](README.md). This guide is made from the same table the
Social Media Factory's own menu uses, so if it is listed here, it is in your copy.

## How it works, in one minute

1. **You talk, Claude runs the tools.** You never type a command. Say what you want in your own
   words; the phrases under "You can say" are examples, not passwords.
2. **Everything starts from your brand.** The onboarding interview captures who you are, in your
   own words. Every post, script, picture and clip is made from that, for that brand only.
3. **It never invents.** No made-up facts, numbers, quotes, customers or results. It writes from
   your files and what you tell it. What it cannot trace to your material is labelled
   *unverified*, and you decide.
4. **Nothing goes out without your yes.** A preview sends nothing at all. You approve exact words
   and pictures; change them and you approve again.
5. **Your brand stays on your computer.** Your keys too.

## The order most people work in

**Set up** once → **onboard** your brand once → then, each week: **decide** what to talk about →
**write** → **make visuals** (and **clips**, if you record) → **approve** → **post** → **check
results**, which feeds next week's topics.

One person can do all of it. On a team, each section below says who usually owns it.

## What it costs

The Social Media Factory is free. Writing, scripts, visuals, review and the ready-to-post folder need **no
account at all** beyond Claude. The outside services (Metricool, Apify, ElevenLabs, and OpenAI for
AI-made pictures) are optional, and Claude tells you the cost before you sign up for any of them.

What each is for, what it costs (with the date the price was checked), how to limit what you spend,
and how to set it up step by step: **[SERVICES.md](SERVICES.md)**. Ask Claude for **"my accounts
checklist"** and it lists only what your choices need, or say **"walk me through Metricool"** (or any
of the others) to set one up together.

---

## 0. Set up

Install what this computer needs, add keys only for what you choose, and see what is ready.

**Who usually owns it:** Whoever looks after the computer. Once per computer, about ten minutes.

### Set up this computer

- **You can say:** "set this up", "check my setup", "is everything working"
- **You get:** A working Social Media Factory on this computer, and a self-test that proves each piece by using it.
- **It needs:** nothing
- **Behind it:** skill `setup`; commands `setup`, `doctor`

### See what is ready

- **You can say:** "start", "what can you do", "what's ready"
- **You get:** A plain list of what works now and the next step for anything that does not.
- **It needs:** nothing
- **Behind it:** skill `start`; commands `status`

---

## 1. Onboard a brand

Teach the Social Media Factory who the brand is: what it does, who it talks to, how it sounds in its own words, its offers, colours, rules and accounts. Everything else is built on this.

**Who usually owns it:** The person who knows the brand best: the owner, or the account lead for a client.

### Onboard or update a brand

- **You can say:** "onboard my brand", "set up my brand on a page", "add a client", "change my colours", "add a testimonial", "update my checklist"
- **You get:** A brand folder: settings, the brand's own words, brand kit, rules, a proof library, and a checklist of only the accounts its choices need.
- **It needs:** nothing
- **Behind it:** skill `onboard-brand`; commands `new-brand`, `update-brand`, `check-brand`, `sync-brand`, `checklist`, `proof`, `facts`, `onboard-page`

---

## 2. Decide what to talk about

Topics come from the brand's own pillars, its audience's real questions, its offers and its proof. The person approves topics before anything is written. Research is there when you want to look outward.

**Who usually owns it:** A strategist or the owner. Weekly.

### Plan topics from the brand

- **You can say:** "plan my week", "what should I post about", "give me topic ideas"
- **You get:** Approved topics, each pointing at where in the brand's material it came from, and a plan: a different angle per platform, a job for each post, a visual kind, an ending.
- **It needs:** an onboarded brand
- **Behind it:** skill `plan-content`; commands `topics`, `plan`, `journal`

### Talking points with web research

- **You can say:** "talking points on ...", "prep me for a podcast about ..."
- **You get:** A run-sheet of talking points, every number with a named source and a link.
- **It needs:** an onboarded brand
- **Behind it:** skill `talking-points`

### Research what is working

- **You can say:** "what's working on YouTube for ...", "study this creator", "what are people asking about ...", "pull the facts out of this video"
- **You get:** Creator studies, YouTube demand and outliers, Reddit and X listening, demand reports, search results, a mined video. The cost is shown before every run.
- **It needs:** an account: Apify (free plan to start, then fractions of a cent per result), an onboarded brand
- **Behind it:** skill `research`; commands `research`

---

## 3. Write

Posts for each platform, short-form video scripts with teleprompter files, and long-form YouTube packages. Written from a brief built from the brand's own files, then checked against the platform's rules, the brand's rules and the brand's facts.

**Who usually owns it:** A writer or social media manager.

### Write posts for each platform

- **You can say:** "write posts about ...", "write this week's posts", "write a LinkedIn post about ..."
- **You get:** A batch of posts in the brand's voice, each checked against the platform's rules, the brand's rules and the brand's facts, planned across days so no two accounts repeat a subject.
- **It needs:** an onboarded brand
- **Behind it:** skill `write-posts`; commands `contract`, `validate-draft`, `posts`

### Write short-form video scripts

- **You can say:** "write me ten short video scripts", "scripts from this podcast", "audit my last batch"
- **You get:** Scripts with a text, visual and spoken hook that agree, visual directions, a teleprompter file for each, a batch index to film from, and an audit of results.
- **It needs:** an onboarded brand
- **Behind it:** skill `write-scripts`; commands `scripts`

### Package a long-form YouTube video

- **You can say:** "package a YouTube video about ...", "give me titles for ...", "make a thumbnail", "build a slide deck"
- **You get:** A folder per video: title options, thumbnail, hook, structure, description with chapters, a slide deck and a teleprompter file.
- **It needs:** an onboarded brand
- **Behind it:** skill `youtube-video`; commands `youtube`

---

## 4. Record and clip

A recording becomes finished clips: transcript, the person's choice of moments, cuts made on the actual words, fillers tightened, captioned versions, a description for each.

**Who usually owns it:** A video editor or producer.

### Turn a recording into clips

- **You can say:** "clip this podcast", "pull shorts from this recording", "fine cut these"
- **You get:** A transcript with who said what, a cut list of moments you chose, rough cuts, fine cuts, and a check that every clip holds the right words.
- **It needs:** an account: ElevenLabs (about 22 cents per hour of audio), the video tools (a second download; Claude installs them when you first ask for video), an onboarded brand
- **Behind it:** skill `make-clips`; commands `recordings`, `transcribe`, `find-clips`, `check-cut-list`, `rough-cut`, `fine-cut`, `validate-cuts`

### Captioned versions and descriptions

- **You can say:** "add captions", "make versions for my other accounts", "write the descriptions"
- **You get:** Several different-looking versions of each clip with on-screen text, word-by-word captions and any disclaimer, a description for each, checked before delivery.
- **It needs:** the video tools (a second download; Claude installs them when you first ask for video), an onboarded brand
- **Behind it:** skill `make-clips`; commands `variants`, `describe`

### Switch between two cameras automatically

- **You can say:** "I filmed this on two cameras", "sync these two files"
- **You get:** One edited video that cuts to whoever is speaking, and clips from it.
- **It needs:** the video tools (a second download; Claude installs them when you first ask for video), an onboarded brand
- **Behind it:** skill `make-clips`; commands `sync`, `multicam`

### Cut a narrated film from many sources

- **You can say:** "make a video ad from my footage", "make a film about ...", "cut these clips to a voiceover", "turn my brand story into a film"
- **You get:** A film whose every shot is matched to a line of narration (a synthesised voice or your own read), drafted from your own onboarding answers or a finished script and cut from the footage folder in your brand, with an optional music bed (a track you have the rights to, the built-in quiet bed, or one made to order from your brand's own settings), a contact sheet taken from the finished film, and a credits list for every source.
- **It needs:** the video tools (a second download; Claude installs them when you first ask for video), an onboarded brand, ElevenLabs only for voicing the narration and a music bed made to order (your own recorded read and the built-in bed need no key)
- **Behind it:** skill `make-a-film`; commands `montage`

### Motion titles in your brand's colours

- **You can say:** "add titles to my film", "put the words on screen", "make an opening title and an end card"
- **You get:** A short title clip for every piece of on-screen text a film's plan already carries (its title, each line's words on screen, your wordmark and handle), drawn in your own colours, fonts and logo with one simple entrance and exit, added to the plan as a source you place like any other shot. Drawn on this computer by HyperFrames, which setup installs with the video tools.
- **It needs:** the video tools (a second download; Claude installs them when you first ask for video), an onboarded brand
- **Behind it:** skill `make-a-film`; commands `montage`

---

## 5. Make visuals

Carousels, cards and PDFs drawn on this computer in the brand's colours. No account and no photos needed.

**Who usually owns it:** A designer, or the writer.

### Make carousels and cards

- **You can say:** "make a carousel for this", "make a stat card", "make visuals for these posts", "make a LinkedIn PDF"
- **You get:** Carousels, stat cards, before-and-after, alert, headline, note, post-style and bold text cards, plus PDFs, in the brand's colours.
- **It needs:** an onboarded brand
- **Behind it:** skill `make-visuals`; commands `visuals`

### Make an AI picture

- **You can say:** "make a picture of a warm loaf on a floured board", "generate a photo for this post"
- **You get:** One picture made to order with your own OpenAI key, saved to the brand's pictures. An estimated cost is shown and you say yes before each one.
- **It needs:** an account: OpenAI (a separate developer account; roughly 1 to 20 cents per picture), an onboarded brand
- **Behind it:** skill `make-visuals`; commands `visuals`

---

## 6. Approve

One page, on your own computer, with every post and picture. Approve, edit, turn down or ask for a remake. Approval is of exact words and pictures.

**Who usually owns it:** Whoever signs off: the owner, the client, a compliance lead.

### Review and approve on this computer

- **You can say:** "let me review", "show me the posts", "remake the ones I flagged"
- **You get:** One page with every post and picture. Nothing leaves the computer.
- **It needs:** an onboarded brand
- **Behind it:** skill `review`; commands `review`

---

## 7. Post

Schedule approved posts to the brand's accounts, or save a ready-to-post folder and upload by hand. Always a preview first; nothing is sent without a yes.

**Who usually owns it:** A social media manager.

### Save a ready-to-post folder

- **You can say:** "save them so I can post by hand", "make me a ready-to-post folder"
- **You get:** A dated folder with each approved post's words and pictures in posting order, a schedule sheet and a plain read-me.
- **It needs:** an onboarded brand
- **Behind it:** skill `post`; commands `export`

### Schedule through Metricool

- **You can say:** "schedule the approved ones", "link my accounts"
- **You get:** Approved posts scheduled to the brand's linked accounts, after a preview and a yes.
- **It needs:** an account: Metricool (Advanced plan or higher), an onboarded brand
- **Behind it:** skill `post`; commands `accounts`, `schedule`

### One short a day from a folder of videos

- **You can say:** "I have new shorts to schedule", "one short a day"
- **You get:** Finished videos planned one per day per account, carrying on after what is already booked.
- **It needs:** an account: Metricool (Advanced plan or higher), an onboarded brand
- **Behind it:** skill `post`; commands `shorts`

### Test on TikTok, promote the winner (advanced, off by default)

- **You can say:** "turn on test and promote"
- **You get:** Every version of a clip goes to TikTok first; the best one is scheduled to the other accounts after you say yes. It posts the same clip several times on purpose.
- **It needs:** an account: Metricool (Advanced plan or higher), an onboarded brand
- **Behind it:** skill `post`; commands `promote`

---

## 8. Check results

Did it really go out, and how did it do. Keeps a permanent copy of the numbers on your computer.

**Who usually owns it:** A social media manager or analyst. Weekly.

### Did my posts go out, and how did they do

- **You can say:** "did my posts go out", "how did last week do", "what's working"
- **You get:** Posts the networks refused and why, the numbers for the ones that went out, and a permanent local copy of those numbers.
- **It needs:** an account: Metricool (Advanced plan or higher), an onboarded brand
- **Behind it:** skill `check-results`; commands `results`

### Results for posts you put up by hand

- **You can say:** "I posted these by hand", "here are my numbers"
- **You get:** Posts from your ready-to-post folder, with the links and numbers you give, counted in the summary and marked as typed in. Nothing is estimated.
- **It needs:** an onboarded brand
- **Behind it:** skill `check-results`; commands `results`

---

## Words used in this guide

| Word | Meaning |
|---|---|
| **Brand** | One business or person the Social Media Factory makes content for. Each has its own folder, voice, colours, accounts and records. There is no default brand |
| **Identity** | Who is speaking inside a brand: a person (says "I") or the company (says "you" and "we") |
| **Brand kit** | The brand's colours, name stamp, fonts, logo and photos |
| **Pillar** | A subject the brand could talk about for a year |
| **Topic** | One thing to talk about this week, always pointing at where in the brand's material it came from |
| **Shape** | The structure of a post (three tips, a myth against reality, five lessons). A topic gets a different shape on each platform |
| **Job** | What a post is for: reach, trust or leads. It decides how the post may end |
| **Contract** | The brief for one post: who is speaking, to whom, the platform's rules, the shape, and every fact that may be used |
| **Sourcing** | Whether a post's facts were checked against the brand's own material: passed, unverified or blocked |
| **Batch** | A set of posts reviewed and scheduled together |
| **Drip** | The schedule rule: one subject, one account per day, rotating, so feeds never all say the same thing at once |
| **Proof** | Results, testimonials, screenshots, photos and facts, each with a source and a "may we publish this" answer |
| **Cut list** | The clips chosen from a recording: each body with its hooks, the exact words the cuts start and end on |
| **Hook** | The opening of a clip or post. In clips it is always a line the person really said |
| **Version (variant)** | One of several different-looking renders of the same clip |
| **Preview (dry run)** | Showing exactly what would be sent while sending nothing at all |

## When something goes wrong

Say **"check my setup"**. Claude runs a self-test that actually uses each piece, and fixes what
it finds. If a posting record, a brand file or a batch is reported as damaged, the Social Media Factory stops
on purpose so nothing goes out twice; tell Claude and it will repair it from the scheduler's own
calendar. It will never delete something to make an error go away.

## Keeping it current

Platform rules change every few months. Each rulebook in `playbooks/` carries the date it was
last researched. Ask Claude to **"refresh the playbooks"** and it re-checks each platform's
current rules with web research and updates them.


---

Built by Spearleaf.
