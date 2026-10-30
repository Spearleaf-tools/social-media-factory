# Results for posts put up by hand

For people who post from the ready-to-post folder themselves (no Metricool, or a network it does
not reach). The Factory cannot see those posts, so the person tells it. Free, and works offline.

## When to offer it

- They used a ready-to-post folder, and say they have posted some or all of it.
- They ask "how did it do" and the brand has no scheduling service.
- The summary says posts put up by hand have no numbers yet.

## 1. Record that it went up (once per post)

They need: which post, its link, and roughly when. Ask for the link one post at a time; they copy
it from the post itself (the share button, "Copy link").

`factory.py results --brand <id> --by-hand <post id> --url "<link>" --when "YYYY-MM-DD HH:MM"`

- `--when` can be just the date if that is all they know, or left out to use the post's planned
  time. **Never make a time up.** The preview says which it used.
- If two batches have a post with that id, add `--batch <batch file name>`.
- Read the preview back in plain words ("Instagram, Monday at 9:15, this link, the post about
  rye"). Only after a yes, run it again with `--confirm`.

It is refused, with a reason, when: the post belongs to another brand, it was never saved to a
ready-to-post folder, or the link is not on that post's network. Pass the reason on; do not work
around it.

**Wrong post or wrong link?** `factory.py results --brand <id> --withdraw <post id>`, preview,
yes, `--confirm`. Then record it again. Nothing is deleted; the old record stops counting.

## 2. Their numbers (any time later; best after two days)

`factory.py results --brand <id> --numbers <post id> views=1200 likes=40`

Measures it keeps: views, likes, comments, shares, saves, reach, impressions, clicks,
watch_minutes. Whole numbers only.

- **Read the numbers back before saving**, then `--confirm` after a yes.
- **Only numbers they gave.** A number they did not give stays missing. Never estimate, never carry
  one over from another post.
- **Rounded numbers ("1.2K") are refused.** Tell them where the exact count is: the post's
  Insights on Instagram and Facebook, Analytics on TikTok, LinkedIn and X, or YouTube Studio.
- **A correction** is the same command with the new numbers. The newest save wins. The preview
  names any number given before but not now, which would stop counting; if they still want it,
  include it again.

**Many posts:** `factory.py results --brand <id> --numbers-sheet` writes a spreadsheet to the
brand's Output folder, under results-to-fill. Tell them the sheet's name as the command gives it: a
second sheet made the same day ends in `-2`, and an earlier one is never replaced. They fill in what
they know and leave the rest empty.
Then `factory.py results --brand <id> --numbers-sheet "<path of the filled sheet>"` previews, and
`--confirm` saves. One problem anywhere in the sheet and nothing is saved; tell them which line.

## 3. The summary

`factory.py results --brand <id>` (it needs no scheduling service). Posts with typed-in numbers
count like any other and are marked "(typed in)". Say so when you report them: "Your numbers say
the rye post did best."

If the brand also uses Metricool and fetched numbers arrive for the same post, the fetched ones are
used and the post is counted once.
