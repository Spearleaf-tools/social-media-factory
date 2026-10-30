# Slide decks: the show, never the script

> last_researched: 2026-06-11 (as of June 2026)
> How to build a support deck for a talking video or a lesson: the slides that sit beside a person
> while they speak. This is craft, not platform rules, so it ages slowly. The tool that draws decks
> is `factory.py youtube deck`. Every example is invented. See `README.md`.

## The one law

**The person talks. The slide shows.** Whoever is watching is listening to a voice. A slide is
there to back that voice up with ONE thing the eye can take in without effort. It is not the
voice written down, and it is not a notice board for the people making the video.

Hold a slide up against three tests. Fail any one and the slide goes back:

1. **Who is it for?** Only the viewer. A timecode, the word "Hook", "B-roll", "Slide 4", a note to
   the editor, anything in [brackets]: all of that belongs in the script. Slides get screenshotted
   and passed around, so whatever is on one has been published.
2. **How much is on it?** One thing: a few words, a figure, a picture, a small diagram. If a viewer
   can read a sentence off the slide faster than the speaker can say it, they read, and they stop
   listening. So the spoken line never appears on screen.
3. **What is its heading doing?** Naming the idea ("Time is an ingredient"), not announcing the
   moment ("Now watch what happens overnight"). A useful test: cover everything except the
   headings and read them in order. If they make the case without a narrator, the deck has a spine.

A good-looking slide that fails one of these is still a bad slide.

## What makes a deck better

Not movement. Slides change whole, one to the next; nothing flies in piece by piece, because
that leaves half-built frames in the edit. A deck improves in this order:

| First | It is for the right person: notes gone, one thing per slide, nothing read aloud |
|---|---|
| Then | It is clear: headings that name ideas, every spare word cut |
| Then | It is well made: one focal point, real spacing, the brand's own colours and lettering |
| Then | **It shows instead of stating**, and every point the speaker makes has a slide |

The last row is the one to aim for. Wherever an idea CAN be seen, draw it: a proportion as lit
dots, two options side by side, steps in a row, the brand's own picture with one mark on it. A
plain deck that covers every point is worth more than a polished one that covers half.

## The process

1. **List the points.** Go through the script and write down each point the speaker makes. A
   point with no slide is a stretch of video with nothing to look at.
2. **Give each point its slide:** a heading, and the one thing that slide is there to land.
3. **Choose a kind of slide for each** (below). Try a kind that shows before settling for one that states.
4. **Take things away.** Any slide, and any word, that is there for you and not for the viewer.
   Removing comes before adding.
5. **Write the spec.** A small file listing the slides. Never page code, never a colour or a font:
   those come from the brand's settings.
6. **Draw it** in the brand's look: `factory.py youtube deck --brand <id> --video <id> --spec <file>`.
7. **Open the pictures and go through them** (the loop below). Judge what is on the page, not the effort that went in.
8. **Check each figure** against the brand's facts, or give it its source.

## The kinds of slide

| Kind | What it is | Reach for it when | It holds |
|---|---|---|---|
| `title` | The subject, large, with an optional line under it | The first slide | 9 words, 12 under it |
| `statement` | One bold sentence, one word coloured | A change of mind with nothing to show for it | 12 words |
| `number` | One very large figure and what it measures | A single figure carries the point | 8 characters, a 10 word label, a source |
| `share` | A hundred dots, some of them lit | "About a third of..." A proportion the eye can see | a percentage, a 10 word label, a source |
| `compare` | Two panels side by side, the better one marked | Two ways, two results, before and after | 5 word titles, 3 points a side, 7 words each |
| `steps` | Two to five numbered cards in a row | A short process, in order | 6 words a step |
| `list` | A heading and two to four short lines | A few things to remember | 7 words a line |
| `ranking` | Three to five rows, one highlighted | An order that matters, and one row is the point | 5 words a row |
| `progress` | A long bar, mostly filled, the rest in the accent colour | "Nearly there, and the last part is what matters" | a percentage, an 8 word label |
| `picture` | The brand's own photo or screenshot in a frame, with one ring on it | Real proof | a 9 word caption, one mark |
| `quote` | Someone's words, who said them, where | A real person said it and the brand may repeat it | 24 words, a name, a source |
| `ask` | The next step, with one button | Near the close | 8 words, 12 under it, a 5 word button |
| `next` | The video to watch after this one | The last slide | 9 words |

A word in \*stars\* takes the brand's accent colour. One per slide is plenty.

**Invented examples.** For the bakery: a `share` slide lighting the part of a day the dough spends
fermenting; a `compare` of "Cold oven" and "Hot oven" with three short results each; a `picture` of
the under-proofed loaf with a ring on the tight crumb. For the clinic: a `steps` slide for a home
test ("Stand on one leg", "Close your eyes", "Count to ten"); a `ranking` of what Tomas looks at
first in a training diary, with the top row highlighted.

## Density limits

The tool refuses a slide that breaks these, and names the slide:

- each kind of slide has its own word limits (the last column above)
- no slide holds more than **28 words in all**: that is the most a viewer takes in while someone is talking
- a list has at most four lines, steps at most five, a comparison three points a side
- **seven spoken words in a row** copied from the script onto a slide is the script, not a slide
- a number that traces to nothing and gives no source is refused. A number with a written source
  that the brand's files cannot confirm is drawn, and reported as **unverified**, so the person
  approving the deck sees that
- text that still does not fit after the renderer has shrunk it to the smallest readable size
  stops the draw, with the slide and the line named. **Shorten the words. Do not fight the layout**

When a slide is over its limit there are only two honest fixes: keep the one idea and cut the
rest, or split it across two slides.

## Showing, and staying honest

- **Draw the real thing.** If the point is "one dough, two ovens", show two loaves, not two grey boxes.
- **Proof is a real picture,** and a small one. Take the brand's own photo or screenshot, from its
  own folder, and crop until the thing that proves the point fills the frame. Put one ring on it so
  the eye knows where to go. A whole screen dropped onto a slide asks the viewer to find the proof
  themselves, and they will not.
- **Show the picture as it is.** Do not dress it up inside a drawn phone, a drawn browser window or
  a drawn chat bubble. Viewers can tell, and it makes the real thing look staged.
- **Nothing invented.** No made-up figure, logo, customer or quotation. If the brand does not have
  it, change the slide.
- **Colours and lettering come from the brand's settings,** never from the spec.
- **Decks are watched small:** in the corner of a screen share, on a phone. One dominant thing per
  slide, large enough to read at a quarter of the size.

## The look-at-it loop

Drawing a deck writes every slide as a picture (1920x1080), one PDF of all of them, and a
**contact sheet**: every slide small, in order, on one page.

1. **Open the contact sheet first.** At that size you see what a viewer sees in a corner of the
   screen. Anything you cannot read there is too small or too crowded.
2. **Read the headings in order** (the tool prints them too). Do they make the case without a
   narrator? Is any point missing?
3. **Look for the odd one out:** the slide that is crowded, the one that is nearly empty, the one
   that looks like a different deck.
4. **Open those at full size,** fix the SPEC, and draw again.
5. **Read the report:** anything shrunk to fit, anything unverified.

Two or three turns of the loop is normal. A deck that was never looked at is a draft.

## Applying this to your brand

| You need | Read |
|---|---|
| The points the speaker makes | the video's `script.md` |
| Figures you may show | `Studio/facts.json`, `Inputs/Research/`, the proof library |
| Pictures you may show | `Brand/brand-kit/photos/`, `Inputs/Proof/` (with permission for anything showing a customer) |
| Colours, lettering, the name in the corner | the brand's settings (change them with onboarding, never in a spec) |
| Names never to mention, terms never to publish | the brand's settings. They are checked on every slide |
