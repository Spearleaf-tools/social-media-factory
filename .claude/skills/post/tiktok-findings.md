# TikTok through Metricool: what we know before the first real post

**Last researched:** 2026-10-28, by reading Metricool's own help pages. No account was connected
and nothing was previewed or sent. Check again when this is more than four months old, the same
rule as the playbooks.

Read this whenever a send, a preview or a results check involves TikTok. Where an answer is
"not confirmed", say so to the person. Never present it as fact.

Sources, all opened on 2026-10-28 (Metricool's "updated" dates are relative, as shown then):

| | Page | Updated |
|---|---|---|
| A | [Schedule and Post on TikTok](https://help.metricool.com/schedule-and-post-on-tiktok-bkepi) | about 3 months ago |
| B | [Scheduling and Posting Options by Social Network](https://help.metricool.com/en/article/scheduling-and-posting-options-by-social-network-127eukv) | about 3 weeks ago |
| C | [Why can't I enable auto-publishing?](https://help.metricool.com/why-cant-i-enable-auto-publishing-66gg0) | not shown |
| D | [Why does my post appear as sent and not auto-published?](https://help.metricool.com/why-does-my-post-appear-as-sent-in-metricool-and-not-auto-published-467xf) | about 4 months ago |
| E | [How to manually publish via notification](https://help.metricool.com/how-to-manually-publish-via-notification-5ds3m) | about 5 months ago |
| F | [TikTok metrics](https://help.metricool.com/tiktok-metrics-fe7io) | about 2 months ago |
| G | [How to schedule TikTok posts](https://metricool.com/tiktok-carousels) (Metricool's blog) | published 2026-01-01 |
| H | [Basic guide for API integration](https://help.metricool.com/en/article/basic-guide-for-api-integration-abukgf/) | about 2 weeks ago |

Could not be read: Metricool's
[API limitations per social network](https://help.metricool.com/en/article/api-limitations-per-social-network-n7zlr)
page (gone: "not found"), and the TikTok parts of its full API reference (the Swagger file and the
API manual PDF were too large to read). So **nothing below is confirmed for posts sent through
the API**, which is how the Social Media Factory sends. The help pages describe the Metricool app.

---

## 1. Does a scheduled TikTok post publish by itself?

**Answer: yes for a plain video with auto-publish on, but not always.** Fairly sure for the app,
not confirmed for the API.

- With auto-publish on, Metricool can "schedule and automatically publish" TikTok videos, for
  personal and business accounts (A, B).
- With auto-publish off, at the scheduled time Metricool sends a notification. Tapping it
  downloads the video, copies the caption and opens TikTok, where someone finishes the post (A, E).
- Some posts can never auto-publish and fall back to that notification (A, E): videos with music
  outside TikTok's Top 100 trending songs, anything needing effects, stickers or other features
  only the TikTok app has, and "any post that doesn't meet the autopublishing requirements". The
  pages don't list those requirements in full.
- A post that went to the notification route shows as **"sent"** in Metricool, which means
  "configured for manual publishing", not published (D). Once that notification has gone out, the
  post can't be switched to auto-publish. It has to be duplicated (C).
- Metricool sends no message when an auto-published post succeeds, only for manual posts and for
  errors (A, E).

**What it means for Kor:** a plain video with the caption written in the Social Media Factory should go
out by itself. A video with added music from TikTok's library, or one that needs a TikTok effect,
means someone must tap publish in the TikTok app at the scheduled time, on a phone with the
Metricool app and notifications turned on. A "sent" post is not a published post. Run
check-results a day later and believe only what it finds.

## 2. Picture and carousel posts, or only video?

**Answer: both, according to Metricool.** Fairly sure that the app schedules them. Whether picture
posts auto-publish is likely but not stated outright.

- TikTok photo carousels of up to 35 images can be scheduled (A, B, G), for personal and
  creator/business accounts (G). Metricool's blog says to "toggle Auto-publish" for them (G). The
  help page's table gives an auto-publish length only for videos (A).
- Pictures: JPEG or WebP, up to 20 MB each. PNG files are converted by Metricool "since the API does
  not support them" (A). The Social Media Factory's pictures are PNG, so they rely on that conversion.
- Video: MP4 (recommended) or MOV, up to 500 MB, 3 seconds to 10 minutes for auto-publishing,
  540px to 1080p (A, B).
- Caption: up to 2,000 characters with auto-publish, 2,200 by hand (B). **TikTok's API doesn't
  accept line breaks**, so paragraphs run together (A).
- Pages A and B disagree about privacy settings: B says privacy can be chosen on personal accounts
  only, and A says they appear "if activated on the TikTok account".

**What it means for Kor:** his shorts are videos, which is the best-supported case. Write TikTok
descriptions as one paragraph, since line breaks won't survive. Picture carousels for TikTok are
possible, but untested here. Don't promise them until the live test has tried one.

## 3. Which numbers come back?

**Answer: per video, Metricool shows views, likes, comments, shares, reach, total and average watch
time, and the share of views watched to the end, plus where the views came from.** Fairly sure
for the app. The API's field names are not confirmed.

- Per post (F): views (with a split by source: For You, Following, hashtag, sound, profile,
  search), likes, comments, shares, reach, duration, engagement, **full video views** (a
  percentage), **total watch time**, **average watch time**.
- **Saves are not listed** (F).
- Account level only (F): followers, profile views, and audience details (business accounts
  with at least 100 followers).
- Caveats (F): personal accounts get fewer numbers than business ones. Reach and watch time can
  come back blank for a video that has been inactive for more than 7 days. Switching between a
  personal and a business account can lose earlier numbers. A post TikTok filtered (for example
  over music rights) can't be read at all. The numbers cover organic activity only, not ads.

**What the Social Media Factory keeps today:** `metricool.py` asks Metricool's TikTok post statistics for
views, likes, comments and shares only, so TikTok saves never come back. Reach, watch time,
full video views and the traffic sources are not kept (they are not in the TikTok fields read
by `metricool.py`), so they are noted here, not added.

**What it means for Kor:** views, likes, comments and shares will come back. Saves won't. If
his account is personal, expect fewer numbers than a business account gets.

## 4. Does it depend on the kind of account?

**Answer: partly.** Auto-publish is available on both personal and business accounts (A, B).
Differences listed: trending music (business only), privacy choices (see the conflict above), which
presets appear, and how many numbers come back (business gets more, F). Page F also says image
posts are "only available for personal accounts" in its analytics list, which conflicts with G.

**Kor's account:** **not known.** His brand settings record a TikTok account for the person, not yet
linked, and don't say which kind it is. This goes on the live-test list.

---

## What this means for the test-and-promote loop (post skill, section D)

That loop posts every version of a clip to TikTok, staggered through the day, then judges them a
day later by views per hour.

- If every version is a plain video with the Social Media Factory's own caption and no TikTok music, they
  should auto-publish at their set times, and views per hour is a fair comparison.
- If any version falls to the notification route, it goes live only when someone taps publish. Its
  clock starts later than recorded, and views per hour is measured from the wrong time. That
  version's result can't be trusted. The loop would also need someone ready to tap publish several
  times in one day.
- A version that shows as "sent" was not published. It must not be judged as a flop.

The fix is a later card, not this one (see below).

## What this means for the code that already exists (later cards, not edits)

1. **"Sent" vs published.** `results.py` already understands `AWAITING_CONFIRMATION` ("waiting for
   someone to confirm it in its own app"). This research says that is a normal case for TikTok, not
   a rare one. Confirm in the live test which status Metricool's API really reports for a TikTok
   post sent to the notification route, and that the summary and the promote loop treat it as
   "not published yet".
2. **The TikTok request.** `metricool.py` sends `autoPublish: true` and a `tiktokData` block
   (`privacyOption: PUBLIC_TO_EVERYONE`, comments, duet and stitch allowed). Those field names and
   values could not be checked against Metricool's API reference. Confirm them before or during the
   live test.
3. **Line breaks.** TikTok descriptions lose their line breaks. A preview could warn, or turn them
   into spaces, so the person sees what TikTok will show.
4. **Caption length.** 2,000 characters for auto-published TikTok posts. The preview could check it.
5. **Numbers not kept.** Reach, total and average watch time, full video views and the traffic
   sources are available but not saved. Adding them changes the saved row, which Jack's script
   audit (C1) reads, so it needs a word with Jack first.
6. **Test-and-promote timing.** The loop could refuse, or warn about, versions that can't
   auto-publish, and measure views per hour from the real publish time once results report it.

## List for the supervised live test (the project lead chooses the account and says yes to the posts)

1. Which kind of account is Kor's TikTok: personal, creator or business? Check it in the TikTok
   app before linking.
2. Does one plain video sent through the Social Media Factory (the API, not the Metricool app) publish by
   itself at its time, with no tap in the TikTok app?
3. What does Metricool's API report for that post before and after it publishes, and for a post
   that falls to the notification route?
4. Does a picture carousel auto-publish through the API, and do the Social Media Factory's PNG pictures
   convert without problems?
5. Which numbers does the results check really bring back after two days, and are any blank?
6. Are the `tiktokData` settings accepted as they are, and does the post come out public with
   comments, duets and stitches allowed?

## For PRD D (pulling back or moving a scheduled post): partly answered

Metricool's API guide (H) lists actions to read, update (`PUT` and `PATCH`) and delete
(`DELETE /v2/scheduler/posts/{id}`) a scheduled post. It doesn't say which fields an update can
change (for example the time), what happens to a post that has already gone out, or how it shows on
the calendar afterwards. Card P7 does the rest of that reading.
