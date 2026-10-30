# X rulebook

> last_researched: 2026-06-11 (as of June 2026). Confidence: high on mechanics, medium on craft
> Basis: X published the code for its main feed in January 2026 and updates it about once a month.
> The mechanics below rest on that release, on public statements from the company, and on one very
> large third-party study of posts from paid and free accounts. Writing advice comes from
> practitioner consensus and is marked as such. In `profiles.json` the key for X is `twitter`.
> Every example is invented. See `README.md`.

## 1. How reach works there now

**The feed is ranked by a model that reads your post.** X's published code describes a learned
model with almost no hand-written rules left. It reads the content of a post, compares it with
what each user has engaged with before, and predicts how likely that user is to take each of a
list of actions. The score is the weighted sum of those predictions.

| Predicted action | Direction |
|---|---|
| Reply, repost, quote, share | Up |
| Like | Up |
| Click, profile click, follow the author | Up |
| Photo opened, video watched | Up |
| Time spent reading (dwell) | Up |
| "Not interested", mute, block, report | **Down. These carry negative weights** |

**What is not known.** The weights themselves are not published. The numbers still passed around
("a reply is worth 13 likes") come from a 2023 release and are out of date. Anyone quoting exact
2026 weights is guessing.

**What is dependable.**

1. **Conversation ranks highly.** Replies, profile clicks and follows are all first-class actions.
2. **Reading time is scored.** Posts people actually read do better.
3. **Annoying people costs you.** Predicted mutes, blocks and reports push a post down. Bait that
   irritates non-fans has a real price.
4. **One account cannot flood the feed.** A diversity step reduces repeat appearances by the same
   author. Ten posts a day do not buy ten slots.
5. **Tone.** Since early 2025 the company's stated aim is time that users do not regret, with less
   negativity and more informational and entertaining posts.
6. **Subject consistency compounds.** Because the model matches content to interests, an account
   that stays on its subjects is shown to more of the right people over time.

**The Following tab is ranked too.** Since November 2025 the Following tab is sorted by the model
by default. Chronological order still exists in a menu. Even your own followers do not reliably
see you. Every post competes.

**Paid accounts.** The largest recent study (close to 19 million posts, published late 2025)
found paid accounts reaching about ten times as many people per post as free ones. By March 2025
the median free account's engagement rate was zero: at least half its posts got no likes, replies
or reposts at all. Paid tiers also get their replies shown higher. If X matters to the brand,
the account needs to be a paid one. Without it, the rest of this rulebook does very little.

**Links.** The company's head of product has said links are not deliberately pushed down, only
that they get less engagement, and X shipped a new way of opening links in late 2025 to help.
The measured result is the same either way: posts that carry a link do worse than every other kind. Lead with
native content. Put the link in a reply.

## 2. First lines that earn the click

**The opening line has to sell the post by itself.** People decide in a few words, and
the model is predicting whether they will stop. (This section is practitioner consensus, not
platform data. It changes slowly.)

| Pattern | Invented example |
|---|---|
| A specific result, with an exact number | "We cut bread waste from 22 loaves a day to 3. The fix was a whiteboard." |
| The line that frames an image | "This is the same dough at 4 hours and at 14. Look at the holes." [photo] |
| A belief corrected, evidence next | "Stretching before a run is not what protects your calf. Here is what I see work instead:" |
| How something works, plainly | "A sourdough starter is flour, water and whatever is living in your kitchen. That is the whole ingredient list." |
| The reader's frustration, said back | "You rested for three weeks, the knee felt fine, and it hurt again on the second run." |

**Rules of thumb.**

- Exact, unrounded numbers read as true. Round ones read as made up. Use only real ones.
- Start with the result or the reader. Openings about yourself are weaker.
- Three openings to drop: a thread label, a link, and a vague promise with no subject in it.
- Anger and mockery are now a ranking problem as well as a taste problem.

Templates for each pattern are in `hooks.md`.

## 3. Post skeletons

### A. The Shown Post (one post plus a native image). The default.
*Use it when you have one idea and something to look at. Most posts are this.*

```
[The point, in one line, with a real number if there is one]

[1 to 3 lines: what the image shows, and the ONE reason behind it]

[Optional: one line the reader can use today]
[ATTACH: a photo, chart or screenshot, uploaded directly]
[Any link goes in the first reply]
```
An opened photo, reading time and a bookmark are all scored actions. 280 characters.

### B. The Plain Take (text only)
*Use it when the idea is an observation or a rule and the sentence itself is the content.*

```
[Line 1: the claim]

[Line 2 or 3: the reason, or the example that proves it]

[Last line: the turn. What to do, or what follows.]
```
In the large study of paid accounts, plain text drew more engagement per view than anything else.

### C. The Thread
*Use it only when the idea is a true sequence: a step by step, a walkthrough with several pictures, a case story told in order.*

```
Post 1     Stands alone. The result and the promise.
           ("Our Saturday class went from 4 bookings to a waiting list. Here is what we changed, in the order we changed it:")
Posts 2-6  ONE step per post, each readable on its own, with its own image where possible.
Last post  One line of recap, then the only ask: follow, bookmark, or the link.
```
Four to seven posts. The feed scores post 1 exactly as it would a single post. If it does not earn attention, the
rest is barely shown. Put everything into it.

### D. The Useful Reply
*Use it daily. It is the cheapest way to be seen by the right people.*

```
[Under a post by a larger account that talks about your subjects:]
[Add one thing the post did not say: a number, an exception, a short example from your own work.]
[2 to 4 lines. No link, no pitch, no "great post".]
```
Replies are a scored action, and paid accounts have their replies shown higher.

**Which one?**

- One idea, one thing to look at: **A**.
- One idea, nothing to show: **B**.
- A real sequence with several images: **C**.
- Anything that fits in a single good post stays a single post. A thread splits the reading time
  across posts that are each scored alone.

**A note on long posts.** Paid accounts can publish single posts far beyond 280 characters, and
a long single post usually does better than a thread because all the reading time lands on one
scored post. The Factory's checker holds every X post to 280 characters so that posts work on any
account. Inside the Factory a longer idea therefore becomes a short thread. If you post long
single posts by hand, 500 to 1,500 characters is the useful range. Past about 2,000 people
stop expanding them.

## 4. Length, links, hashtags and calls to action

**Length.** 280 characters per post. Aim for 100 to 280. A thread is four to seven posts.

**Links.** Never in the first post. First reply, or added after the post has found an audience.

**Hashtags.** None by default. The model reads meaning, so write the subject into the sentence
("sourdough", "running injuries"). One at most, for a real event or community tag. The 2025
ban on hashtags applies to paid adverts only. Organic hashtags are allowed, they are simply not needed.

**Calls to action.**

| Allowed | Not allowed |
|---|---|
| A real question people in the field can answer | "Repost if you agree" |
| "Bookmark this for [a specific moment]", after a dense, useful post | "Comment YES" |
| "Follow for [a specific promise]", only in the last post of a thread | Fake polls |
| A plain statement of what you offer, now and then, in its own post | A link as the opening |

X has changed how creators are paid to stop rewarding engagement farming, and has cut off apps
that paid people to post. Bait also raises the predicted mutes and reports that push a post down.

**What each action is earned by.**

| You want | Write |
|---|---|
| Bookmarks (the measure that matters for teaching posts) | Dense reference: checklists, settings, steps |
| Reposts | Something that makes the sharer's own followers better off |
| Quotes | A clear claim or a surprising number people want to add to |
| Replies | A question that is easy to answer from experience. Then answer every reply |

**Rhythm.** Two or three strong posts a day at most. Answer the replies under your own posts within the hour.

## 5. Formats that work

In order for a brand that teaches:

1. **Text plus a native image.** Text alone scores a higher engagement rate, but the image is what
   makes a claim believable. This is the right trade for most brands.
2. **Plain text.**
3. **Short native video.** A screen recording or a quick demonstration. Video watched is a scored action.
4. **Thread.** Walkthroughs and case stories only.
5. **Link post.** Last resort, link in a reply.

Long-form articles exist for the top paid tier. Evidence that they are distributed well is thin.
Treat them as an experiment.

## 6. What to avoid

- **Reach from the wrong people.** On a platform that matches content to interests, an
  off-subject post that travels changes who the account is shown to. Your later, on-subject posts
  then go to the wrong people. It is a cost, not a bonus.
- **Engagement bait and fake polls.**
- **Mocking a business or a person by name.** Blocks, mutes and reports count against you, and the
  people watching include your customers. Criticise a practice. Never a person.
- **Leading with a link.**
- **Threads by default.**
- **Claims with nothing attached.** A big number with no picture reads as unverifiable.
- **Posting past the diversity limit.** Two or three good posts beat ten thin ones.
- **Running a free account and expecting reach.**

## 7. Applying this to your brand

| You need | Read |
|---|---|
| Who speaks, and how they sound in one or two lines | `Brand/brand-voice.md`, `Brand/voice-samples.md`. X rewards a recognisable voice more than any other platform |
| The reader's own frustrations, in their words | `Brand/audience.md` |
| The few subjects to stay on | `Brand/pillars-and-offers.md` |
| Real numbers, photos and screenshots to attach | The facts table in `Brand/business-profile.md`, the proof in `Inputs/` and `Studio/` |

Decisions to make per brand:

- **Is X worth it?** If the brand's customers are not there, or the account will not be a paid one, skip X.
- **Which larger accounts?** List five to ten that talk about the brand's subjects. The Useful Reply happens there.
- **What is bookmark-worthy?** Pick the two or three checklists or processes the brand knows best.
- **Regulated brand?** Short posts tempt absolutes. Write "often" and "can", never "always" or "will". Use only approved claims.
