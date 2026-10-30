"""youtube_now.py - what is working on YouTube NOW, in two questions.

1. `search`: is this topic alive? For each keyword, look at what YouTube is showing today and ask
   whether RECENT videos are winning, or only old ones are. A keyword whose top results are all
   years old is either saturated or fading, and a new video has little room. Demand goes stale,
   so this is run fresh each time a video is being planned; an old report is not evidence.

2. `channels`: which videos beat their own channel? Every video is scored against its own
   channel's median (see numbers.py for the score and its guards). Those outliers are where a
   title, a topic or an angle did something the rest of the channel did not.

Signals reported per keyword, all of them counts or ratios a person can check:
    fresh / old          how many results are under a year old, how many over two years
    median views         the field a new video is up against
    small-channel wins   videos with at least SMALL_WIN times more views than the channel has
                         subscribers: proof that the TOPIC pulled the views, not the audience
    one channel owns it  when a single channel holds a large share of the results, the keyword
                         belongs to them and a different angle is needed
    verdict              alive | stale | too thin to say

The tool counts. Claude, in the conversation, reads the winning titles for their STRUCTURE and
helps the person write their own title on their own subject. Titles are never reused.
"""
from __future__ import annotations

import os
import re

from smf.research import numbers, store
from smf.research.apify import Apify, NotConfirmed

MIN_RESULTS = 8         # fewer ranked videos than this and no verdict is given
MIN_FRESH = 3
SMALL_WIN = 1.5         # views per subscriber that marks a small-channel win
OWNS_SHARE = 0.4        # one channel holding this share of a keyword's results
TABLE_ROWS = 10


def _title_facts(title):
    t = str(title or "")
    return {"chars": len(t), "has_number": bool(re.search(r"\d", t)), "is_question": t.strip().endswith("?"),
            "has_brackets": bool(re.search(r"[\(\[].+[\)\]]", t))}


def analyse_search(items, now=None):
    """Pure: normalised search results in, a demand reading per keyword out."""
    now = now or numbers.utc_now()
    by_kw = {}
    for it in items:
        v = dict(it)
        v["views"] = numbers.to_number(v.get("views"))
        v["subscribers"] = numbers.to_number(v.get("subscribers"))
        age = numbers.age_days(v.get("published_at"), now)
        v["age_days"] = age if age is not None else numbers.age_days(v.get("published_text"), now)
        v["views_per_day"] = (round(v["views"] / max(v["age_days"], 1), 1)
                              if v["views"] and v["age_days"] is not None else None)
        v["views_per_subscriber"] = (round(v["views"] / v["subscribers"], 2)
                                     if v["views"] and v["subscribers"] else None)
        v["title_facts"] = _title_facts(v.get("title"))
        by_kw.setdefault(str(v.get("keyword") or "unknown"), []).append(v)

    out = {}
    for kw in sorted(by_kw):
        ranked = [v for v in by_kw[kw] if v["views"]]
        fresh = [v for v in ranked if v["age_days"] is not None and v["age_days"] <= numbers.FRESH_DAYS]
        old = [v for v in ranked if v["age_days"] is not None and v["age_days"] > numbers.OLD_DAYS]
        undated = sum(1 for v in ranked if v["age_days"] is None)
        med = numbers.median([v["views"] for v in ranked]) or 0
        small_wins = [v for v in fresh if (v["views_per_subscriber"] or 0) >= SMALL_WIN]
        beating = [v for v in fresh if v["views"] >= med]

        owner, share = None, 0.0
        counts = {}
        for v in ranked:
            name = str(v.get("channel") or "unknown")
            counts[name] = counts.get(name, 0) + 1
        if counts:
            owner, top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            share = top / float(len(ranked))

        if len(ranked) < MIN_RESULTS:
            verdict, why = "too thin to say", ("only %d results had view counts; at least %d are needed"
                                               % (len(ranked), MIN_RESULTS))
        elif undated > len(ranked) / 2:
            verdict, why = "too thin to say", "most results had no readable date, so recency cannot be judged"
        elif len(fresh) >= MIN_FRESH and (small_wins or beating):
            verdict = "alive"
            why = ("%d of %d results are under a year old; %d of those match or beat the median, and %d are "
                   "small-channel wins" % (len(fresh), len(ranked), len(beating), len(small_wins)))
        else:
            verdict = "stale"
            why = ("only %d of %d results are under a year old and %d are over two years old, so recent videos "
                   "are not winning here" % (len(fresh), len(ranked), len(old)))

        winners = sorted(set(id(v) for v in small_wins + beating))
        pool = [v for v in fresh if id(v) in winners]
        pool.sort(key=lambda v: (-(v["views_per_subscriber"] or 0), -(v["views_per_day"] or 0), str(v.get("url"))))
        out[kw] = {"verdict": verdict, "why": why, "results": len(ranked), "fresh": len(fresh), "old": len(old),
                   "median_views": med, "small_channel_wins": len(small_wins),
                   "owner": owner if share >= OWNS_SHARE and len(ranked) >= MIN_RESULTS else None,
                   "owner_share": round(share, 2), "winners": pool[:TABLE_ROWS]}
    videos = [v for kw in sorted(by_kw) for v in by_kw[kw]]
    return {"keywords": out, "videos": videos}


def render_search(brand, reading):
    reading = reading["keywords"]
    lines = ["# What is working on YouTube now", "", "For **%s**." % brand.name, "", store.RULES_OF_USE, "",
             "Read a verdict as a starting point, not a ruling. **alive** means recent videos are winning, so "
             "there is room. **stale** means only old videos rank. Demand moves: run this again when you plan the "
             "next video rather than trusting an old report.", ""]
    lines += [store.md_table(["Keyword", "Verdict", "Results", "Under a year", "Over two years", "Median views",
                              "Small-channel wins"],
                             [[kw, r["verdict"], r["results"], r["fresh"], r["old"], store.fmt_int(r["median_views"]),
                               r["small_channel_wins"]] for kw, r in reading.items()]), ""]
    for kw, r in reading.items():
        lines += ["## \"%s\": %s" % (kw, r["verdict"]), "", "Why: %s." % r["why"]]
        if r["owner"]:
            lines.append("One channel (**%s**) holds %d%% of these results. The keyword is theirs; look for an angle "
                         "they have not covered." % (r["owner"], round(r["owner_share"] * 100)))
        lines.append("")
        if r["winners"]:
            lines += ["Recent videos that are winning (strongest small-channel wins first):", "",
                      store.md_table(["Views", "Days old", "Subscribers", "Views per subscriber", "Views per day",
                                      "Title", "Channel", "Link"],
                                     [[store.fmt_int(v["views"]), v["age_days"], store.fmt_int(v["subscribers"]),
                                       v["views_per_subscriber"] or "-", store.fmt_int(v["views_per_day"]),
                                       v.get("title"), v.get("channel"), v.get("url")] for v in r["winners"]]), ""]
    lines += ["## Worksheet (Claude fills this in with you)", "",
              "1. Which keyword is alive AND close to what %s is known for?" % brand.name,
              "2. Look at the winning titles as STRUCTURES, not sentences: a number, a promise, a question, a "
              "time frame, something in brackets. Which structures repeat? Count them.",
              "3. Write new titles for %s's own subject using a structure that is winning. Never reuse a title."
              % brand.name,
              "4. Anything chosen here becomes a topic in the brand's topic bank, with this report as its source.",
              ""]
    return "\n".join(lines)


def analyse_channels(items, now=None):
    videos, groups = numbers.score_against_own_normal(items, "channel", now=now, when_key="published_at",
                                                      when_text_key="published_text")
    for v in videos:
        v["title_facts"] = _title_facts(v.get("title"))
    ranked = sorted((v for v in videos if v["outlier_score"] is not None),
                    key=lambda v: (-v["outlier_score"], str(v.get("url") or "")))
    return {"videos": videos, "channels": groups,
            "outliers": [v for v in ranked if v["standing"] == "outlier"],
            "under": [v for v in reversed(ranked) if v["standing"] == "under"][:TABLE_ROWS]}


def render_channels(brand, reading):
    lines = ["# YouTube outliers", "", "For **%s**." % brand.name, "", store.RULES_OF_USE, "",
             "An outlier score is a video's views divided by its own channel's median. A score of 3 means three "
             "times what that channel normally gets, whatever the channel's size.", "", "## The channels", ""]
    for name, g in sorted(reading["channels"].items()):
        if g["scored"]:
            lines.append("- **%s**: normal is **%s views** (median of %d settled videos out of %d)."
                         % (name, store.fmt_int(g["baseline_median"]), g["in_baseline"], g["videos"]))
        else:
            lines.append("- **%s**: not scored, because %s." % (name, g["why_not"]))
    lines.append("")
    heads = ["Score", "Views", "Days old", "Title", "Channel", "Link", "Note"]

    def row(v):
        return ["%sx" % v["outlier_score"], store.fmt_int(v["views"]), v["age_days"], v.get("title"),
                v.get("channel"), v.get("url"), v["score_note"] or ""]
    if reading["outliers"]:
        lines += ["## Videos that beat their channel's normal (2x or more)", "",
                  store.md_table(heads, [row(v) for v in reading["outliers"][:TABLE_ROWS * 2]]), ""]
    else:
        lines += ["## No outliers found", "",
                  "No video reached twice its channel's normal. That is a real answer: these channels are steady "
                  "rather than spiky. Try more videos per channel, or different channels.", ""]
    if reading["under"]:
        lines += ["## Videos that fell well short (half or less)", "",
                  store.md_table(heads, [row(v) for v in reading["under"]]), ""]
    lines += ["## Worksheet (Claude fills this in with you)", "",
              "1. What do the outliers have in common that the weak videos lack? Topic, title structure, length. "
              "Give counts.",
              "2. Which of those is a fit for %s's own subject and audience?" % brand.name,
              "3. To see HOW an outlier is built (its opening, its proof, its close), run the video miner on it.", ""]
    return "\n".join(lines)


def _go(brand, job, folder, label_prefix, inputs, max_items, extra, confirm, client, today, now, analyse, render,
        asked):
    brand = store.as_brand(brand)
    client = client or Apify(allow_runs=confirm)
    try:
        result = client.run(job, inputs, max_items=max_items, extra=extra, confirm=confirm)
    except NotConfirmed as e:
        return {"ran": False, "estimate": e.plan["estimate"], "plan": e.plan}
    reading = analyse(result["items"], now=now)
    run_dir = store.new_run_dir(brand, folder, "%s-%s" % (label_prefix, "-".join(result["inputs"])), today)
    store.write_json(brand, os.path.join(run_dir, "videos.json"), reading["videos"])
    store.write_json(brand, os.path.join(run_dir, "reading.json"), {k: v for k, v in reading.items() if k != "videos"})
    store.write_text(brand, os.path.join(run_dir, "summary.md"), render(brand, reading))
    store.write_record(brand, run_dir, folder, dict(asked, inputs=result["inputs"], limit=result["max_items"]), result)
    return {"ran": True, "folder": store.rel(brand, run_dir), "count": result["count"],
            "warnings": result["warnings"], "partial": result["partial"], "estimate_usd": result["estimated_usd"],
            "reading": reading}


def search(brand, keywords, max_items=None, within_days=None, confirm=False, client=None, today=None, now=None):
    extra = {"publishedWithinDays": int(within_days)} if within_days else None
    return _go(brand, "youtube_search", "youtube-now", "search", keywords, max_items, extra, confirm, client, today,
               now, analyse_search, render_search, {"kind": "keyword search", "within_days": within_days})


def channels(brand, channel_list, max_items=None, confirm=False, client=None, today=None, now=None):
    return _go(brand, "youtube_channel", "youtube-now", "channels", channel_list, max_items, None, confirm, client,
               today, now, analyse_channels, render_channels, {"kind": "channel outliers"})
