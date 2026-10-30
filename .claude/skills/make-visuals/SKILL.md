---
name: make-visuals
description: Make a brand's pictures for social posts, in its own colours and name. Use when the person says "make a carousel", "make visuals for these posts", "I need an image for this", "make a stat card", "turn this post into a carousel", "make a LinkedIn PDF", or after write-posts when posts need pictures (Instagram always does). Draws carousels, stat cards, before-and-after cards, alert and headline cards, note cards, post-style cards and bold text cards on this computer, with no key and no photos needed.
---

# Make visuals

The Factory draws pictures on this computer, in the brand's colours, with its name stamped on
them. No account, no key, no internet. You write a small description of each picture (a
**spec**); the renderer draws it and makes sure the text fits.

## What it can draw

| Kind | Use it when |
|---|---|
| `carousel` | Teaching something in steps. Cover, 2 to 8 middle slides, a closing slide. Best for saves. Add `"pdf": true` for a LinkedIn document |
| `stat` | One number carries the point. The number needs a source |
| `split` | A before and an after |
| `alert` | A warning or a mistake to avoid |
| `headline` | One strong claim |
| `notes` | A short list that should feel jotted down |
| `post-screenshot` | A thought that reads like a post. Shows the identity's initials unless the brand has supplied its own photo |
| `bold-text` | One line, big. Layout `ad` or `statement` |

| `free` | None of the above looks like this brand, or the person wants something different. You design the picture yourself; see "Free design" below |

`playbooks/visual-formats.md` explains when each works and why the look should rotate. The plan
for the week already names a kind for each post (`visual_format.draws_as` lists the formats that
fit). Follow it unless the person asks otherwise, and never use the same look twice running.

The eight fixed kinds are drawn without photos. A brand's own photos can be attached to a post
as they are (`posts attach`). A **free design** can hold pictures: the brand's own photos, stock
photos, and images generated with the person's own OpenAI key. See "Pictures inside a free
design" below.

**The person decides what goes in their pictures.** If they ask for a stock photo of a person,
or a generated person, make it. The only time you do not is when they have told you this brand
does not want generated people. What does not change is rule 2 on the **words**: a stock or
generated person is never captioned as a named customer, and no quote or result is put beside
them unless it is real.

## How to make one

**1. Write the spec** as a JSON file in `.factory/tmp/`. The full field list for every format is
at the top of `smf/studio/render/__init__.py`; read it the first time. The essentials:

```json
{
  "format": "carousel",
  "identity": "person",
  "name": "why-sourdough-is-dense",
  "slides": [
    {"headline": "Why your sourdough is dense", "accent": "dense", "kicker": "One cause. One fix."},
    {"kind": "point", "headline": "Your dough is not late. It is cold.", "accent": "cold"},
    {"kind": "checklist", "title": "Ready when", "items": ["It has grown by half", "It wobbles like set custard"]},
    {"kind": "cta", "headline": "Save this for Saturday", "accent": "Saturday"}
  ]
}
```

**2. The words on a picture follow the same rules as the post.** They come from the post and
the brand's material. Nothing invented. Every number on a picture needs a `"source"`; a stat
with no source is still drawn, but the report flags it as unverified and you must tell the
person. Keep the brand's never-mention names and banned words off pictures too: run the text
through the same check as a caption if you are unsure.

**3. Pictures are not captions.** One idea per slide. A headline is a line, not a paragraph. If
the renderer says a line is too long, **shorten the words**; do not fight the layout. It names
the slide and the line.

**4. Draw it.**
`factory.py visuals --brand <id> --spec <file>` (add `--check` to validate without drawing).
Pictures land in the brand's Output folder under visuals, in slide order, with a report beside
them (what was shrunk to fit, any number without a source). A brand that posts only to TikTok
gets tall pictures (9:16) unless the spec names a size; tall pictures keep their words clear of
the app's own buttons and caption. A dark brand keeps its dark look on every slide; asking for
`"ground": "bold"` by name still gets the headline colour as the background.

**5. Look at what you made.** Open the phone-size overview first: the command prints where it
is (a `phone-size` folder beside the pictures, never one of the pictures). That is the size
people meet it. Is the headline the biggest thing, does each slide make sense alone, does
anything look cramped? Then open any picture that looks wrong at full size. Fix the spec and draw
again. Then show the person, starting with the overview.

**6. Attach them to the post.**
`factory.py posts attach --brand <id> --batch <batch> --id <post id> --media <files in order>`
Changing the pictures on a post that was already approved cancels the approval, by design.

## Free design

The eight kinds above are fixed layouts: every brand gets the same shapes in its own colours.
A **free design** has no layout. You design the picture for this brand and this post, and the
Factory draws it and checks it.

**Ask once per set, with a default.** Propose one direction in a sentence and say why it suits
this brand and this post ("a recipe-card look, because this is from Ava's class handout"). "Yes"
is a complete answer. Do not ask picture by picture. If the person wants the same look as before,
read the last design back: every free design is saved beside its pictures as
`<name>-design.json`.

**Write the spec.** `"format": "free"`, and each slide has `html` (what goes inside the picture)
and `css` (its styling). The full contract is at the top of `smf/studio/render/free.py`; read it
the first time. In short:

- Fonts are `smf-display`, `smf-body`, `smf-mono` and `smf-poster`. No other font can load.
- The brand's colours arrive as `var(--ground)`, `var(--ink)`, `var(--accent)` and so on. Start
  from them and vary which one leads. Use a colour outside the brand's own only when the person
  asks for it or agrees to it.
- No scripts, no links, no web addresses. Type, colour, boxes, simple SVG shapes, and pictures
  from the brand's own photos folder (next section).
- Leave off small extras (labels, page dots, a footer line, the brand's name) unless the person
  asks for them. Fewer words, bigger.
- A number still needs `"source"` on its slide, pointing at the brand's fact (`fact:<id>`).

**What the Factory checks on the drawn picture.** Every word is on the picture and not cut off,
is at least 24 pixels on a 1080-wide picture, is in one of the four fonts, and can be read
against what is really behind it. Names the brand never mentions and words it has banned stop
the picture. Numbers are read from the picture itself and traced to the brand's facts. If a
check fails, nothing is saved and the message names the picture and the words.

**Fixing a failure.** Change the size, the spacing or the layout. **Never change the person's
words to make a picture pass**; if only shorter words would fit, say so and ask. After two failed
tries, stop: tell them in a sentence or two what would not fit, and offer the nearest fixed kind.

**Look before you show.** Open every picture, and look at it small (about a third of full size)
as well. Then show the person. If they do not like it, ask what to change and redraw with the
same words.

## Pictures inside a free design

A design names a picture from the brand's folder with `brand:` in front:
`<img src="brand:Brand/brand-kit/photos/loaf.jpg">`, or `url(brand:...)` in the styling.
`factory.py visuals --brand <id> --images` lists what the brand has and where each came from.
Three sources:

**Their own photos.** They drop files into the photos folder inside their brand kit. Free.

**Stock photos.** Free. Give them a ready search link on Unsplash or Pexels (or another free
site they prefer) for what the picture needs, ask them to download the one they like, then file
it for them:
`factory.py visuals --brand <id> --add-image "<the downloaded file>" --source stock --from "<the photo's page>" --licence "<one sentence>" --shows-person yes`
Say the licence in one sentence when you file it. Unsplash: free to use, including for business,
no credit needed; it cannot be resold as it is. Pexels: free to use, no credit needed; do not
show an identifiable person in a bad light, and do not suggest the people or brands in the photo
endorse the product. Those two were read on 9 October 2026; for any other site, read its licence
page first and tell the person what it says.

**Generated images.** The main route for most people: realistic, and made to order. It uses the
person's own OpenAI key and costs them money per image, so:

1. `factory.py visuals --brand <id> --generate "<what it should show>"` (add `--shape tall`,
   `square` or `wide`, and `--quality low`, `medium` or `high`). This **spends nothing**. It
   prints the price and the exact words that would be sent to OpenAI. Read both to the person.
2. Only after they say yes, run the same command again with `--confirm`. Add `--shows-person yes`
   or `no`, and `--image-name` for a short name.
3. Show them the image **on its own** before putting it on a picture. Every other try is
   another charge and needs another yes; `--images` shows the running total.

If there is no OpenAI key, the command says so. They add `OPENAI_API_KEY=<their key>` to the
keys file themselves. Never ask for the key in the chat.

**Be straight about what a picture is.** When a stock or generated picture shows something the
brand sells, say plainly that it is not their product and ask before using it. The render report
lists every stock or generated picture used, and adds a note when one that may show a person
sits beside a claim or a quote; read those notes to the person. Words that are part of a
generated image cannot be checked by the Factory, so read them yourself.

## Keeping a look

When the person is happy with a set, ask once: **"Do you want to keep this as a template going
forward?"** If yes:
`factory.py visuals --brand <id> --save-look "<their name for it>" --design <the design file beside the pictures> --about "<one line>"`

Before designing, run `factory.py visuals --brand <id> --looks`. It lists the brand's saved
looks and its three most recent free designs with their pictures. Open those pictures. If the
person asks for a saved look, start from its design, write the new words into it and draw it;
every check runs again. If your new design would repeat the layout and colour treatment of the
recent ones and they did not ask for the same, change it or say so in one sentence. The same
look every time is how followers stop seeing a brand's posts.

## Making them for a whole batch

Go post by post. Vary the kind down the batch (polished, then native-looking, then raw) the way
the plan laid it out. For each Instagram post, a picture is required. For LinkedIn, a carousel
saved as a PDF usually beats a single image.

## Showing a new brand what it looks like

`factory.py visuals --brand <id> --demo` draws one of every kind with obviously fake sample
words, in their colours. Use it at the end of onboarding, and whenever they change their colours.

## If the look is wrong

Colours, the name stamp, the footer line and fonts come from the brand's settings, never from
the spec. Change them with **onboard-brand** ("change my colours"), which updates the settings
and re-syncs. A brand can drop its own font files into its brand kit's fonts folder and name
them in its settings; otherwise the bundled open-licence fonts are used. Nothing is ever fetched
from the internet while drawing.
