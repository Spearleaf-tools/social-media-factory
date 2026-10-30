"""creator_study.py - study how one short-form creator works, without copying a word of theirs.

What a study is for: a brand picks a creator whose videos hold attention and asks "what is the
STRUCTURE under this?" How do they open, how long do they run, what do the videos that beat
their own normal have in common that the weak ones lack?

What this tool does, and where it stops:
  * fetches the creator's recent videos (numbers, captions, and transcripts where the platform's
    actor offers them and the person agreed to pay for them);
  * works out what numbers CAN say: the account's normal, which videos beat it, which fell short,
    how often they post, how long videos run, how long the opening line is;
  * lays the material out side by side, strongest against weakest, with a worksheet.

It stops there on purpose. Naming the hook type, the structure and the reason a video held
attention is reading, not arithmetic, and Claude does that in the conversation from these files.
This tool never calls a language model.

Two layers of a video are not in the numbers: what is SAID in the first seconds (when there is
no transcript) and what is SHOWN. For those, run the video miner on the two or three videos that
matter most; its `opening_seconds` setting captures the first frames one per second.

The rule that governs every study: learn the structure, never copy the words.
"""
from __future__ import annotations

import os
import re

from smf.research import numbers, store
from smf.research.apify import Apify, NotConfirmed

JOBS = {"instagram": "creator_instagram", "tiktok": "creator_tiktok", "youtube": "creator_youtube_shorts"}
TOP_N = 8
OPENING_WORDS = 15          # roughly what is said in the first five seconds at a normal pace


def clean_handle(text):
    """'@maple.and.main', a profile link, or a bare name -> what the actors expect. Links pass through."""
    s = str(text or "").strip()
    if re.match(r"^https?://", s, re.I):
        return s
    return s.lstrip("@").strip()


def analyse(videos, now=None):
    """Pure: normalised videos in, the study out. No network, no clock unless `now` is given."""
    scored, groups = numbers.score_against_own_normal(videos, "creator", now=now, when_text_key="posted_text")
    for v in scored:
        v["opening_line"] = numbers.first_line(v.get("caption"))
        v["opening_words"] = numbers.word_count(v["opening_line"])
        v["caption_words"] = numbers.word_count(v.get("caption"))
        spoken = " ".join(str(v.get("transcript") or "").split()[:OPENING_WORDS])
        v["spoken_opening"] = spoken
        v["duration_sec"] = numbers.to_number(v.get("duration_sec"))
        tags = v.get("hashtags") or []
        v["hashtags"] = [str(t).lstrip("#").lower() for t in tags if t] if isinstance(tags, list) else []

    ranked = sorted((v for v in scored if v["outlier_score"] is not None),
                    key=lambda v: (-v["outlier_score"], str(v.get("url") or "")))
    strong = [v for v in ranked if v["standing"] == "outlier"][:TOP_N]
    weak = [v for v in reversed(ranked) if v["standing"] == "under"][:TOP_N]

    def side(group):
        return {"videos": len(group),
                "median_duration_sec": numbers.median([v["duration_sec"] for v in group]),
                "median_opening_words": numbers.median([v["opening_words"] for v in group if v["opening_words"]]),
                "median_caption_words": numbers.median([v["caption_words"] for v in group]),
                "opens_with_a_question": sum(1 for v in group if v["opening_line"].rstrip("…").endswith("?")),
                "opening_has_a_number": sum(1 for v in group if re.search(r"\d", v["opening_line"]))}

    tag_count = {}
    for v in scored:
        for t in set(v["hashtags"]):
            tag_count[t] = tag_count.get(t, 0) + 1
    tags = sorted(tag_count.items(), key=lambda kv: (-kv[1], kv[0]))[:15]

    return {"videos": scored, "accounts": groups,
            "views": numbers.spread([v["views"] for v in scored]),
            "duration_sec": numbers.spread([v["duration_sec"] for v in scored]),
            "opening_words": numbers.spread([v["opening_words"] for v in scored if v["opening_words"]]),
            "cadence": numbers.cadence([v.get("posted_at") for v in scored], now),
            "with_transcript": sum(1 for v in scored if v.get("transcript")),
            "strong": strong, "weak": weak, "strong_side": side(strong), "weak_side": side(weak),
            "common_hashtags": [{"tag": t, "videos": n} for t, n in tags]}


def _row(v):
    score = "%sx%s" % (v["outlier_score"], " (provisional)" if v["provisional"] else "")
    length = "%ds" % int(v["duration_sec"]) if v.get("duration_sec") else "-"
    return [score, store.fmt_int(v.get("views")), length, v["opening_line"] or "(no caption)",
            v["spoken_opening"] or "-", v.get("url") or "-"]


def render(brand, creators, platform, study):
    s, lines = study, []
    lines += ["# Creator study: %s on %s" % (", ".join(creators), platform), "",
              "For **%s**. %d videos studied." % (brand.name, len(s["videos"])), "", store.RULES_OF_USE, ""]

    lines += ["## What the numbers say", ""]
    for name, g in sorted(s["accounts"].items()):
        if g["scored"]:
            lines.append("- **%s**: normal is **%s views** (the median of %d settled videos). Every score below is a "
                         "video's views divided by that." % (name, store.fmt_int(g["baseline_median"]),
                                                              g["in_baseline"]))
        else:
            lines.append("- **%s**: no scores, because %s." % (name, g["why_not"]))
    c = s["cadence"]
    if c["per_week"]:
        busiest = sorted(c["by_weekday"].items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        lines.append("- Posts about **%s a week** (a median of %s days apart, over %d days). Busiest days: %s."
                     % (c["per_week"], c["median_gap_days"], c["span_days"],
                        ", ".join("%s (%d)" % kv for kv in busiest)))
    if s["duration_sec"]["n"]:
        lines.append("- Videos run a median of **%d seconds** (shortest %d, longest %d)."
                     % (s["duration_sec"]["median"], s["duration_sec"]["low"], s["duration_sec"]["high"]))
    if s["opening_words"]["n"]:
        lines.append("- The first line of the caption is a median of **%d words**." % s["opening_words"]["median"])
    lines.append("- Transcripts: %d of %d videos." % (s["with_transcript"], len(s["videos"])))
    lines.append("")

    a, b = s["strong_side"], s["weak_side"]
    if a["videos"] and b["videos"]:
        lines += ["## Strong against weak, counted", "",
                  "Only things that can be counted. A pattern that shows up on one side and not the other is "
                  "worth a closer look; one that shows up equally on both explains nothing.", "",
                  store.md_table(["", "Beat their normal (2x or more)", "Fell short (half or less)"], [
                      ["Videos", a["videos"], b["videos"]],
                      ["Median length (seconds)", a["median_duration_sec"], b["median_duration_sec"]],
                      ["Median words in the opening line", a["median_opening_words"], b["median_opening_words"]],
                      ["Median words in the whole caption", a["median_caption_words"], b["median_caption_words"]],
                      ["Open with a question", a["opens_with_a_question"], b["opens_with_a_question"]],
                      ["A number in the opening line", a["opening_has_a_number"], b["opening_has_a_number"]]]), ""]

    heads = ["Score", "Views", "Length", "Opening line of the caption", "First words spoken", "Link"]
    if s["strong"]:
        lines += ["## The videos that beat their own normal", "", store.md_table(heads, [_row(v) for v in s["strong"]]),
                  ""]
    if s["weak"]:
        lines += ["## The videos that fell short", "", store.md_table(heads, [_row(v) for v in s["weak"]]), ""]
    if s["common_hashtags"]:
        lines += ["## Hashtags used most", "",
                  ", ".join("#%s (%d)" % (t["tag"], t["videos"]) for t in s["common_hashtags"]), ""]

    lines += ["## Worksheet (Claude fills this in with you, from the tables above and `videos.json`)", "",
              "Answer from the evidence. For every pattern, give the count on each side (\"6 of 8 strong videos, "
              "1 of 8 weak\"). If it cannot be counted, leave it out.", "",
              "1. **How do the strong videos open?** Name the kind of opening (a question, a bold claim, a number, "
              "a mistake, a before-and-after), not the words.",
              "2. **What is the skeleton?** The order of beats in a strong video, as a reusable outline.",
              "3. **What keeps people watching?** An unanswered question, a list being counted down, a reveal held "
              "back.",
              "4. **How do they end?** What the viewer is asked to do, and when.",
              "5. **What do the weak videos do differently?**",
              "6. **What would %s do with this structure, on its own subject, in its own words?** Two or three "
              "ideas, each tied to one of the brand's pillars." % brand.name, "",
              "What is missing: what is shown on screen in the first seconds, and what is said when there is no "
              "transcript. Run the video miner on the two or three strongest links to see both.", ""]
    return "\n".join(lines)


def study(brand, creators, platform="instagram", max_items=None, transcripts=False, confirm=False,
          client=None, today=None, now=None):
    """Fetch, analyse and save a study. Without confirm=True it returns the cost and saves nothing."""
    brand = store.as_brand(brand)
    if platform not in JOBS:
        raise store.ResearchError("A creator study works on: %s." % ", ".join(sorted(JOBS)))
    job = JOBS[platform]
    handles = [clean_handle(h) for h in ([creators] if isinstance(creators, str) else creators or [])]
    client = client or Apify(allow_runs=confirm)
    options = ["transcripts"] if transcripts else []
    if transcripts and "transcripts" not in (client.job(job).get("options") or {}):
        raise store.ResearchError("Transcripts are not offered for %s. Run the video miner on the videos that "
                                  "matter instead." % platform)
    try:
        result = client.run(job, handles, max_items=max_items, options=options, confirm=confirm)
    except NotConfirmed as e:
        return {"ran": False, "estimate": e.plan["estimate"], "plan": e.plan}

    analysis = analyse(result["items"], now=now)
    run_dir = store.new_run_dir(brand, "creator-study", "%s-%s" % (platform, "-".join(result["inputs"])), today)
    store.write_json(brand, os.path.join(run_dir, "videos.json"), analysis["videos"])
    store.write_json(brand, os.path.join(run_dir, "study.json"), {k: v for k, v in analysis.items() if k != "videos"})
    store.write_text(brand, os.path.join(run_dir, "summary.md"), render(brand, result["inputs"], platform, analysis))
    store.write_record(brand, run_dir, "creator-study",
                       {"creators": result["inputs"], "platform": platform, "limit": result["max_items"],
                        "transcripts": bool(transcripts)}, result)
    return {"ran": True, "folder": store.rel(brand, run_dir), "count": result["count"],
            "warnings": result["warnings"], "partial": result["partial"], "estimate_usd": result["estimated_usd"],
            "accounts": analysis["accounts"]}
