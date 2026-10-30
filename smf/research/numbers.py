"""numbers.py - the arithmetic behind "what is working", and the guards that keep it honest.

THE ONE IDEA
Raw views mostly measure how big an account already is. To see which VIDEO worked, compare each
video with its own account's normal:

    outlier score = this video's views / that account's median views

A score of 4 means the video did four times what that account usually does, whatever its size.
That isolates the thing worth studying (the idea, the title, the opening) from the thing that
is not transferable (the audience someone already had).

THE GUARDS (each one exists because the bare ratio misleads without it)
  median, not mean     one viral video drags an average up and hides every other outlier.
  sample size          with fewer than MIN_SAMPLE settled videos a median is noise. No score is
                       given; the reason is given instead.
  tiny account         when the normal is under MIN_MEDIAN views, 40 views against a normal of
                       10 is "4x" and means nothing. No score is given.
  recency              a video a few days old is still collecting views. It is kept OUT of the
                       baseline (it would drag the normal down) and its own score is marked
                       provisional, because it understates where the video will end up.
  pinned               pinned videos are hand-picked old hits. They are scored, but kept out of
                       the baseline so they cannot inflate the normal.
  zero / missing       a video with no view count is never scored and never counted as zero.

Everything here is pure: no network, no clock unless one is passed in, the same answer every time.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

MIN_SAMPLE = 8
MIN_MEDIAN = 100
SETTLE_DAYS = 7
OUTLIER_AT = 2.0
UNDER_AT = 0.5
FRESH_DAYS = 365
OLD_DAYS = 730

_SUFFIX = {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}
_UNIT_DAYS = {"second": 0, "minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def to_number(value):
    """12345, "12,345", "12.3K", "1.2M subscribers", "69,916 views" -> a float, else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"(\d[\d,]*\.?\d*)\s*([kmb])?\b", str(value).strip().lower())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "")) * _SUFFIX[m.group(2) or ""]
    except ValueError:
        return None


def utc_now():
    return datetime.now(timezone.utc)


def parse_when(value, now=None):
    """An ISO date, a Unix time (seconds or milliseconds), or "3 months ago" -> an aware datetime."""
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        secs = float(value) / 1000.0 if float(value) > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(secs, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    if re.fullmatch(r"\d{8}", text):
        return datetime(int(text[:4]), int(text[4:6]), int(text[6:]), tzinfo=timezone.utc)
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", text.lower())
    if m:
        return (now or utc_now()) - timedelta(days=int(m.group(1)) * _UNIT_DAYS[m.group(2)])
    return None


def age_days(value, now=None):
    now = now or utc_now()
    when = parse_when(value, now)
    if when is None:
        return None
    return max(0, (now - when).days)


def median(values):
    vals = sorted(v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not vals:
        return None
    mid = len(vals) // 2
    return float(vals[mid]) if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def spread(values):
    vals = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not vals:
        return {"n": 0, "median": None, "mean": None, "low": None, "high": None}
    return {"n": len(vals), "median": median(vals), "mean": round(sum(vals) / len(vals), 2),
            "low": min(vals), "high": max(vals)}


def score_against_own_normal(videos, group_key, now=None, metric="views", when_key="posted_at",
                             when_text_key=None, min_sample=MIN_SAMPLE, min_median=MIN_MEDIAN,
                             settle_days=SETTLE_DAYS):
    """Give every video an outlier score against ITS OWN group's median (group = account/channel).

    Returns (videos, groups). Each video gains: age_days, outlier_score (or None), score_note,
    provisional, standing ("outlier" | "typical" | "under" | None). `groups` maps each group to
    its baseline, how many videos made the baseline, and why there is no score when there is none.
    The input list is not changed.
    """
    now = now or utc_now()
    out, by_group = [], {}
    for v in videos:
        v = dict(v)
        v[metric] = to_number(v.get(metric))
        age = age_days(v.get(when_key), now)
        if age is None and when_text_key:
            age = age_days(v.get(when_text_key), now)
        v["age_days"] = age
        out.append(v)
        by_group.setdefault(str(v.get(group_key) or "unknown"), []).append(v)

    groups = {}
    for name, vids in by_group.items():
        settled = [v[metric] for v in vids
                   if v[metric] is not None and not v.get("pinned")
                   and (v["age_days"] is None or v["age_days"] >= settle_days)]
        base = median(settled)
        why = None
        if len(settled) < min_sample:
            why = ("only %d settled video%s to compare with; at least %d are needed for a normal that means "
                   "anything" % (len(settled), "" if len(settled) == 1 else "s", min_sample))
        elif not base or base < min_median:
            why = ("this account's normal is %s views, too small for a ratio to mean anything (under %d)"
                   % ("{:,}".format(int(base or 0)), min_median))
        groups[name] = {"videos": len(vids), "in_baseline": len(settled), "baseline_median": base,
                        "scored": why is None, "why_not": why}
        for v in vids:
            v["outlier_score"], v["standing"], v["provisional"], v["score_note"] = None, None, False, why
            if why is not None:
                continue
            if v[metric] is None:
                v["score_note"] = "no view count"
                continue
            v["outlier_score"] = round(v[metric] / base, 2)
            v["score_note"] = None
            if v["age_days"] is not None and v["age_days"] < settle_days:
                v["provisional"] = True
                v["score_note"] = ("posted %d day%s ago and still collecting views, so this understates it"
                                   % (v["age_days"], "" if v["age_days"] == 1 else "s"))
            v["standing"] = ("outlier" if v["outlier_score"] >= OUTLIER_AT
                             else "under" if v["outlier_score"] <= UNDER_AT else "typical")
    return out, groups


def cadence(dates, now=None):
    """How often someone posts, from the dates of their posts."""
    whens = sorted(d for d in (parse_when(x, now) for x in dates) if d is not None)
    if len(whens) < 2:
        return {"posts": len(whens), "span_days": 0, "per_week": None, "median_gap_days": None, "by_weekday": {}}
    span = max(1, (whens[-1] - whens[0]).days)
    gaps = [(b - a).total_seconds() / 86400.0 for a, b in zip(whens, whens[1:])]
    by_day = {}
    for d in whens:
        by_day[WEEKDAYS[d.weekday()]] = by_day.get(WEEKDAYS[d.weekday()], 0) + 1
    return {"posts": len(whens), "span_days": span, "per_week": round(len(whens) / (span / 7.0), 2),
            "median_gap_days": round(median(gaps), 2),
            "by_weekday": {d: by_day[d] for d in WEEKDAYS if d in by_day}}


def first_line(text, max_words=40):
    """The opening of a caption or transcript: up to the first sentence end or line break."""
    text = str(text or "").strip()
    if not text:
        return ""
    head = re.split(r"(?<=[.!?])\s+|\n", text, maxsplit=1)[0].strip()
    words = head.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def word_count(text):
    return len(re.findall(r"[^\W_]+(?:['’][^\W_]+)?", str(text or ""), re.UNICODE))
