# Instagram rulebook

> last_researched: 2026-06-11 (as of June 2026). Confidence: high
> Basis: Instagram's leadership has said publicly which signals matter most, and the platform
> documents features such as Trial Reels and the hashtag cap. Format comparisons come from large
> third-party benchmark studies (Q1 2026) and drift every quarter.
> Every example is invented. See `README.md`.

## 1. How reach works there now

**There is no single algorithm.** Feed, Reels, Explore and Stories are each ranked by their own
system.

| Surface | What it mostly weighs | What it is for |
|---|---|---|
| Feed | Your history with the account, time spent on the post | People who already follow you, plus some recommendations |
| Reels | Watch time and sends | Being found by strangers |
| Explore | How fast a post is gathering interest | Being found by strangers |
| Stories | How close the viewer is to you | Keeping warm the people who already know you |

**The signals, strongest first.**

1. **Sends per reach.** How many people forwarded the post in a message, as a share of those who
   saw it. Instagram's leadership has singled it out as a top-tier signal, and the
   strongest of all for reaching new people. Write something a person would send to a friend.
2. **Watch time and time on post.** First for Reels. For feed posts, seconds spent counts.
   Carousels gain here by design: every swipe adds time.
3. **Saves.** The "I will come back to this" signal. The natural measure for teaching posts.
4. **Likes per reach, and how quickly engagement arrives.** Matters more for reaching existing followers.

The pattern to notice: these are **ratios, not totals**. A post that reaches 2,000 people and is
saved by 90 of them is doing better than one that reaches 50,000 and is saved by 100.

**What each format does** (observed results, not a stated bonus):

| Format | Strength | Figures (Q1 2026 benchmarks, directional) |
|---|---|---|
| Reel | Reach. More than half of Reel views come from non-followers | About 2.2 times the reach of a single image |
| Carousel | Engagement and saves. Saved more often than anything else | Engagement just ahead of Reels, well ahead of images |
| Single image | Weakest on both | Falling year on year |

**The carousel's second chance.** If someone scrolls past your carousel without swiping, Instagram
will often show it to them again later, opened at slide 2. No other format gets two appearances.
This is why slide 2 has to work as an opening in its own right. Carousels hold up to 20 slides.

**Trial Reels.** A Trial Reel is shown only to people who do not follow you. You see the results
after about a day, and can have it shared to followers automatically if it does well within 72
hours. Public accounts with 1,000 or more followers can use it, and since February 2026 trials
can be scheduled. It is a free way to test an opening without spending your followers' patience.

**Hashtags and search.** Instagram's leadership has said repeatedly that hashtags do not increase
reach. Hashtag following was removed in December 2024. Since December 2025 there is a **hard cap of
five hashtags** per post or Reel. Discovery now comes from words: the caption, the text on screen,
the alt text and what is said aloud.

**A Reel view** is counted at about three seconds of watching.

## 2. First lines that earn the click

**On Instagram the opening is a picture.** The carousel cover, or the first frame of the Reel, is
judged in one to three seconds. The caption opening comes second.

**Cover rules.**

- A headline of 5 to 10 words, the largest type on the slide.
- Legible at a glance, with no pinching to zoom. Strong contrast.
- One open question in the reader's mind. Not two.
- About 12 words on the slide in total.

**Caption rules.** The caption is cut at about 125 characters and most people never tap "more".
The first line must work alone, should extend the cover rather than repeat it, and should contain
the phrase people would type into search ("sourdough starter", "runner's knee").

**Cover patterns** (templates in `hooks.md`):

| Pattern | Invented example |
|---|---|
| A specific result | "From flat loaves to this, in 3 bakes" |
| A small mistake with a real cost | "The shoe habit behind most shin pain I see" |
| The unfinished picture | Half a cut loaf, the crumb cropped out: "What 14 hours does to the inside" |
| A belief reversed | "Kneading is optional. Here is what I do." |
| Already under way (Reels) | Hands folding dough, mid-fold: "This is the only fold you need" |
| The reader named | "If you started running after 35, read this" |

Naming the reader costs raw reach and buys the right audience. With ratios deciding the ranking,
a smaller, right audience can out-rank a bigger, wrong one.

## 3. Post skeletons

### A. The Teaching Carousel (7 to 10 slides, 1080 by 1350)
*Use it when the idea has steps, parts or a list. This is the workhorse.*

```
Slide 1   Cover: the claim plus a visibly unfinished picture. 5 to 10 words.
Slide 2   The second opening. The result or the single most interesting thing, complete
          on its own. Someone may see this slide first.
Slides 3-7  A single point on each. A headline under 12 words plus 1 or 2 support lines.
          Pair each point with something shown: a photo, a number, an example.
          Number them ("Step 2 of 5"). Numbering pulls people forward.
Slide 8   The plain comparison: the idea put in everyday terms a reader would repeat
          to someone else. This is the slide that gets SENT.
Slide 9   The recap: everything on one slide, built like a reference card.
          This is the slide that gets SAVED.
Slide 10  One soft ask.
```
Six to ten slides is the dependable range. Swiping through to slide 3 is the behaviour that
triggers the second showing.

### B. The Demonstration Reel (30 to 60 seconds)
*Use it when you can show the thing happening. This is the reach format.*

```
0-3s     The outcome, already moving, with text on screen. Never a logo or a hello.
3-10s    Show the result properly: the finished loaf, the full movement, the chart.
10-40s   The demonstration. Three steps at most, each with a text headline on screen.
         Burn the captions in: a large share of video here is watched without sound.
40-55s   The plain comparison: one sentence someone would repeat.
55-60s   One soft ask, then cut back to the opening picture so the loop invites a second watch.
```
Try a new opening as a Trial Reel first. Promote the winner to everyone. More in `short-form-video.md`.

### C. The Single Image With a Story
*Use it occasionally, when one picture is the whole argument.*

```
Image    One photo or screenshot that needs no explanation. One arrow or label at most.
Line 1   125 characters or fewer. State the point. Include a figure only if the brand has a real one.
Lines 2-6  A three sentence story: the situation, what changed, what happened.
Last line  Ask something that people who have been through it can answer.
```
Expect lower reach. Its job is to sit on your profile as evidence, and to be forwarded to whoever is deciding.

### D. The Two-Slide Correction
*Use it when the point is a single wrong belief, and you want something fast to make and easy to forward.*

```
Slide 1   The belief, in the words people actually use. Large type.
Slide 2   What is true instead, plus the one reason. This slide must also work alone.
Caption   Line 1 names who this is for. Then 2 to 4 lines of evidence or example. One ask.
```
Pairs with the `myth-vs-reality` shape.

## 4. Length, links, hashtags and calls to action

**Length.** The caption cap is 2,200 characters. Short captions lean toward likes. Longer ones,
around 300 to 800 characters, lean toward saves and comments. (The evidence here is directional.)
Working rule: make the opening 125 characters earn their place, then follow with 300 to 800
characters when the post teaches. Reel captions: one or two lines plus the search phrase.

**Links.** Captions do not carry live links. Do not point at the link in the bio on every post.

**Hashtags.** Five is the platform's limit. Use three to five specific labels
(`#sourdoughbaking`, not `#food`). They label the post. They do not spread it.

**Calls to action.** One per post.

| The ask | When | Why |
|---|---|---|
| "Save this for [a specific moment]" | Teaching posts | Feeds the save ratio |
| "Send this to [a specific kind of person]" | Anything relatable | Feeds the send ratio, the strongest signal |
| A question at the end of the caption | Any post | Reliably lifts comments |
| Book, buy, message | About one post in four or five | People do not pass on sales posts |

## 5. Formats that work

A sound mix for an account that teaches:

- **Carousels, 40 to 50 percent.** Saves and authority.
- **Reels, 35 to 45 percent.** Reach. Use Trial Reels to test openings.
- **Single images and Stories, 10 to 15 percent.** For the people who already know you. Stories
  rank by closeness, not discovery.

Video is vertical, 9 by 16. Never post a video carrying another app's watermark: Instagram
holds those back.

## 6. What to avoid

1. **Reach from the wrong people.** Trend audio and generic tips pull in viewers who will never be
   customers. Instagram then learns that those viewers are your audience and keeps finding more of
   them. A post that takes off with the wrong crowd is a setback.
2. **Advice with nothing shown.** A tips carousel with no photo, example or result looks like
   every other tips carousel. What you can show is what earns the save.
3. **A hard sales slide on every post.** It kills sends and reads as spam.
4. **Hashtag stuffing and engagement bait.** Capped, useless for reach, and bad for trust.
5. **Logo openings and slow introductions on Reels.** The decision happens in the first one to three seconds.
6. **Judging by reach.** Check saves, sends, follows and profile visits as a share of reach.
7. **One-opening carousels.** A weak slide 2 throws away the second showing, in the only format
   that gets shown twice.

## 7. Applying this to your brand

| You need | Read |
|---|---|
| Who speaks, and how | `Brand/brand-voice.md`, `Brand/voice-samples.md`, identities in `brand-master.json` |
| Who to name on the cover, and the phrases they search | `Brand/audience.md`, especially "Questions they really ask" |
| Subjects for a month of carousels | `Brand/pillars-and-offers.md` |
| What can be shown on slide 2 | The proof in `Inputs/` and `Studio/`, the facts table in `Brand/business-profile.md` |
| Colours, fonts and logo for slides | `Brand/brand-kit/` and the colours in `brand-master.json` |
| Which visual to use, and when there are no photos | `visual-formats.md` |

Decisions to make per brand:

- **The "send it to" person.** Who does your customer talk to before they decide? A partner, a
  running friend, a colleague. Give that person a slide of their own in every post.
- **The save moment.** When will they need this again? Name that moment in the ask.
- **Instagram needs an image or a video on every post.** If the brand has no approved photos
  and no image key, the planner keeps to the formats in `visual-formats.md` that need neither.
- **Regulated brand?** Show and describe. Never promise an outcome. Use only approved claims.
