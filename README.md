# Social Media Factory

A complete content system for your own brand, run by Claude on your computer.

You tell it about your brand once. After that you ask for things in plain words:
"plan my week", "write LinkedIn posts about this", "make carousels for those", "turn this
recording into clips", "schedule the approved ones". It writes in **your** voice from **your**
material, shows you everything before anything goes out, and never makes up a fact.

Built by Spearleaf. Free to use. Not to be resold. Agencies may use it for their own clients.

---

## What it does

| | |
|---|---|
| **Onboard a brand** | An interview (it can read your website first) that captures your voice, audience, offers, colours, rules and accounts |
| **Decide what to talk about** | Pillars, topics and a weekly plan from your own brand; talking points with web research; research into what is working |
| **Write** | Posts for each platform, short-form video scripts with teleprompter files, descriptions, long-form YouTube packages |
| **Record and clip** | A recording becomes a cut list, rough cuts, fine cuts and captioned variants; two-camera switching |
| **Make visuals** | Carousels, stat cards, note and quote styles, LinkedIn PDFs, thumbnails, slide decks, in your colours |
| **Approve** | One page on your own computer: approve, reject or edit. Nothing leaves your computer |
| **Post** | Schedule to your accounts, or save a ready-to-post folder and upload by hand |
| **Check results** | Did it go out, and how did it do |

## What it costs

The Social Media Factory is free. Some of the services it can use are not. **You need none of them to write
posts, make carousels, review them, and save a ready-to-post folder.**

| To do this | You need | What that costs |
|---|---|---|
| Use the Social Media Factory at all | Claude (the desktop app or Claude Code) | A paid Claude plan |
| Write, make visuals, review, save a ready-to-post folder | nothing else | free |
| Schedule posts to your accounts | Metricool | Their **Advanced plan or higher** (the smaller plans have no API) |
| Turn recordings into clips | ElevenLabs | Pay as you go, about 22 cents per hour of audio |
| Research what is working | Apify | Free plan with a small monthly credit, then fractions of a cent per result |
| AI-made pictures (optional) | OpenAI | A separate developer account; roughly 1 to 20 cents per picture |

Claude tells you the cost before you sign up for anything, and builds you a checklist of only
the accounts your choices need. Every service, its current price, how to limit what you spend and
step-by-step setup: **[SERVICES.md](SERVICES.md)**.

---

## Install (about ten minutes, no technical knowledge needed)

**1. Get Claude.** Install the Claude desktop app from claude.ai/download and sign in.
(If you already use Claude Code in a terminal, that works too.)

**2. Download the Social Media Factory.** Open the
[latest release](https://github.com/Spearleaf-tools/social-media-factory/releases/latest), and under
**Assets** download the file whose name starts with `social-media-factory`. Unzip it somewhere easy to
find, such as your Documents folder.
*On Windows, keep it near the top of your drive (for example `Documents\social-media-factory`).
Very long folder paths cause trouble on Windows.*

**3. Open the folder in Claude.** In the desktop app, go to the **Code** tab, choose
**Open folder**, and pick the folder you just unzipped. If it asks whether you trust the
folder, say yes.

**4. Type:** `set this up`
Claude installs everything the Social Media Factory needs, inside this folder. It needs no admin password
and changes nothing else on your computer. The first time takes a few minutes because it
downloads about 450 MB (the part that draws your carousels is the big one). If you later ask for
video, it downloads roughly another 700 MB.

**5. Type:** `start`
Claude asks about your brand (about fifteen minutes, skip anything you like), shows you your
first visuals in your own colours, and asks what you want to make.

That is the whole install. You never type a command, and you never paste a key into the chat.

### If something goes wrong

Type `check my setup`. Claude runs a self-test that actually draws a card and, if you have the
video tools, makes and cuts a test video, then fixes what it finds.

- **On a work computer**, company security software sometimes blocks the downloads. Claude will
  tell you exactly which websites your IT team needs to allow.
- **Windows is in beta.** Every piece is tested automatically on a clean Windows computer on
  every change (from a ZIP, in a folder with spaces and accents, with nothing pre-installed). It
  has not yet been run by many real people on many real laptops. If you hit a problem, tell
  Claude what you see.

### To remove it

Delete the folder. Everything it installed lives inside it, apart from two shared download
caches that are safe to delete: the page renderer (`ms-playwright`) and the speech model
(`huggingface`), both in your user cache folder.

---

## Using it

Open the folder in Claude and say what you want. You can always just say **`start`**.

| Say something like | What happens |
|---|---|
| "onboard my brand" | The brand interview. Add a second brand the same way |
| "plan my week" | Topics from your pillars and your audience's real questions. You approve the topics before anything is written |
| "write posts about ..." | A different angle per platform, in your voice, checked against each platform's rules and your own |
| "make carousels for these" | Visuals in your colours and fonts |
| "let me review" | Opens the review page on your computer |
| "schedule the approved ones" | Shows you exactly what will go where and when, sends nothing until you say yes |
| "save them so I can post by hand" | A dated folder with each post's text and images, in posting order |
| "turn this recording into clips" | Transcript, cut list (you choose the clips), rough cuts, fine cuts, captioned variants |
| "I filmed this on two cameras" | Lines the two files up by their sound and makes one video that shows whoever is talking |
| "write me a video script" | A short-form script from your own material, with a clean teleprompter file |
| "package this YouTube video" | Titles, a description with chapters, thumbnails and a slide deck, checked against your own facts |
| "test my shorts before I promote them" | Optional: a short goes to TikTok first, and only the ones that earn their views move on to your other accounts |
| "what's working on YouTube for ..." | Research, with the cost shown before it runs |
| "did my posts go out?" | Checks the schedule for anything the networks refused, and shows the numbers |

Everything it can do, section by section, with who on a team might own each part: **[GUIDE.md](GUIDE.md)**.

## The promises it keeps

- **It never invents.** No made-up facts, numbers, quotes, customers or results. It writes from
  your files and what you tell it. Anything it cannot trace is labelled unverified, and you decide.
- **Nothing goes out without your yes.** A preview sends nothing at all. You approve exact words
  and images; if they change, you approve again.
- **There is no default brand.** Every action names the brand, so one brand's words cannot reach
  another brand's accounts.
- **Your brand stays on your computer.** The `Client` folder is kept out of version control on
  purpose. Your keys live in one file that is never uploaded, and Claude is told not to read it.
- **It tells you the cost first.**

## Your keys

You only need keys for the paid services you choose. Claude opens a file called `keys.env` for
you; you paste each key after its equals sign, save, and say "done". Never paste a key into the
chat. If you already keep keys in Doppler, the Social Media Factory can read them from there instead.

## Updating

Download the newest file from the
[latest release](https://github.com/Spearleaf-tools/social-media-factory/releases/latest), unzip it, and
copy your `Client` folder and your `keys.env` file from the old folder into the new one. Then type
`set this up` once.

To report a security problem, see [SECURITY.md](SECURITY.md). Never put a key in an issue.

## Licence and credit

Free to use, including for client work. Not to be sold, rented or repackaged as a product.
See [LICENSE](LICENSE) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

Built by Spearleaf.
