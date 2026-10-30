"""promote.py - the OPTIONAL test-and-promote loop. Off unless the brand turns it on.

    "video": {"test_and_promote": true}        in the brand's settings switches it on

THE IDEA
A clip cut several ways (rye-loaf__warm.mp4, rye-loaf__fast.mp4, ...) is one clip with several
versions. One platform tolerates volume better than the rest, so it is the test bed: every
version goes to TikTok on one day, staggered through the day. A day or more later the numbers
are read, a winner is picked by a rule anyone can check, and only the winner goes to the brand's
OTHER connected platforms.

    plan_test_wave(brand, save=True)   -> a batch for review        (nothing is sent)
    ... approve, then send(brand, batch, provider, confirm=True) ...
    results.harvest_metrics(brand, provider)                         (a day or more later)
    read_results(brand)                -> the numbers per version
    pick_winner(brand, clip)           -> a winner, or a plain reason there is none yet
    plan_promotion(brand, save=True)   -> a batch for review        (nothing is sent)
    ... approve, then send(brand, batch, provider, confirm=True) ...

Every step that sends takes an explicit confirm and is the same road as any other send: the
gates and the ledger in send.py. A person approves every post in the review page first.

THIS POSTS THE SAME CLIP SEVERAL TIMES, ON PURPOSE. That is the whole mechanism, and it is why
the loop is off by default and says so every time it runs.

WHAT KEEPS THE TEST HONEST
  * ONE test account. Versions shown to two audiences of different sizes would measure the
    audience, not the edit. A brand with two TikTok accounts must say which one; it is never chosen
    for it.
  * Every version needs its OWN words. Identical words on one account in one day read as spam,
    and they would make the versions impossible to tell apart in the results.
  * The time slots rotate from clip to clip, so no version name always owns the best hour.
  * A clip only takes a day when every version is ready. A half-filled day cannot produce a winner.
  * No winner until every version has at least a day of results. Early numbers mostly show who
    the platform chose to test it on.

THE RULE FOR PICKING A WINNER (shown with its numbers every time)
  1. A version needs at least the floor of views to count at all (default 100; a starting point
     to tune, set `video.promote_min_views`). Below the floor nothing is promoted.
  2. Among those, the most views per hour since it went out wins.
  3. A tie there is broken by saves, then by shares. Still level: no winner is declared.
Results are matched to versions by the scheduling service's post id, never by similar words.
Each winner is promoted to each account once.
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from smf import brands
from smf.posting import results as R
from smf.posting import send as SEND
from smf.posting import shorts as SH
from smf.posting import state as S
from smf.posting.ledger import Ledger
from smf.studio import posts as P

TEST_PLATFORM = "tiktok"
STATE_FILE = "promote.json"
DECISIONS_FILE = "promote-decisions.jsonl"
MIN_TEST_HOURS = 24
DEFAULT_MIN_VIEWS = 100
MAX_VERSIONS = 6
SPREAD_MINUTES = 150
WARNING = ("Test-and-promote posts the same clip several times on purpose: every version goes to TikTok, then the "
           "best one goes to the other platforms. It is only on because this brand's settings turned it on.")
RULE = ("needs at least %d views to count; then most views per hour since it went out; ties broken by saves, "
        "then shares")


class PromoteError(Exception):
    """Worded for the person."""


def is_on(brand):
    return SH.loop_is_on(brand)


def _off(brand):
    return {"enabled": False, "brand": brand.id, "posts": [], "batch": None, "saved": False,
            "message": "Test-and-promote is off for %s, so nothing was planned, read or sent. To use it, set "
                       "\"test_and_promote\": true under \"video\" in the brand's settings." % brand.name}


def _need_brand(brand):
    if not isinstance(brand, brands.Brand):
        raise brands.BrandError("no brand was named. Say which brand this is for. Brands here: %s"
                                % (", ".join(brands.list_brands()) or "none yet"))


def state_file(brand):
    return S.StateFile(brand, STATE_FILE, "where each clip is in the test-and-promote loop", fresh={"clips": {}})


def min_views(brand):
    n = (brand.data.get("video") or {}).get("promote_min_views", DEFAULT_MIN_VIEWS)
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise PromoteError("The views floor in the brand's settings should be a whole number, for example 100.")
    return n


def test_account(brand, identity=None):
    """The ONE account the test runs on. Named explicitly when the brand has more than one."""
    choices = [i for i, p in SH.video_accounts(brand)[0] if p == TEST_PLATFORM]
    if not choices:
        raise PromoteError("%s has no connected TikTok account, and the test runs on TikTok. Link one first."
                           % brand.name)
    if identity is None:
        if len(choices) > 1:
            raise PromoteError("%s has more than one TikTok account (%s). Say which one the test runs on; the test "
                               "only means something on a single account." % (brand.name, ", ".join(choices)))
        return choices[0]
    if identity not in choices:
        raise PromoteError("'%s' has no connected TikTok account for %s. It has: %s"
                           % (identity, brand.name, ", ".join(choices)))
    return identity


def _version_hash(rel):
    return hashlib.sha256(rel.encode("utf-8")).hexdigest()[:6]


def _wave_times(brand, day, n, turn):
    """n times spread through the day, rotated by `turn` so version 1 is not always first."""
    windows = sorted(int(w[:2]) * 60 + int(w[3:]) for w in brand.posting_windows)
    if n <= len(windows):
        picks = [windows[round(i * (len(windows) - 1) / (n - 1))] if n > 1 else windows[0] for i in range(n)]
    else:
        picks = [windows[0] + i * SPREAD_MINUTES for i in range(n)]
    picks = sorted(set(min(m, 23 * 60 + 45) for m in picks))
    while len(picks) < n:                                # windows too close together: push later ones apart
        picks.append(min(picks[-1] + 20, 23 * 60 + 59))
    out = []
    for i in range(n):
        minute = picks[(i + turn) % n]
        local = datetime.strptime(day, "%Y-%m-%d").replace(hour=minute // 60, minute=minute % 60,
                                                           tzinfo=ZoneInfo(brand.timezone))
        out.append((local.strftime("%Y-%m-%d %H:%M"), local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    return out


def _batch_path(brand, prefix):
    name = "%s-%s.json" % (prefix, datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    path, n = brand.path("Output", "batches", name), 1
    while os.path.exists(path):
        n += 1
        path = brand.path("Output", "batches", name[:-5] + "-%d.json" % n)
    return path


# ----------------------------------------------------------------------------- step 1: the test wave
def plan_test_wave(brand, identity=None, days=7, start=None, save=False, today=None):
    """One clip per day: every version of it to the test account, staggered. A preview unless
    `save`; never sends. Returns {"enabled", "warning", "posts", "batch", "waves", "deferred", ...}."""
    _need_brand(brand)
    if not is_on(brand):
        return _off(brand)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 120:
        raise PromoteError("Plan between 1 and 120 days of tests at a time.")
    identity = test_account(brand, identity)
    today = today or datetime.now(ZoneInfo(brand.timezone)).date()
    first_day = today + timedelta(days=1)
    if start:
        try:
            first_day = max(first_day, datetime.strptime(start, "%Y-%m-%d").date())
        except ValueError:
            raise PromoteError("The start date should look like 2030-01-31.")
    found = SH.discover(brand)
    result = {"enabled": True, "brand": brand.id, "warning": WARNING, "identity": identity, "saved": False,
              "batch": None, "posts": [], "waves": [], "deferred": [], "needs_a_look": list(found["needs_a_look"])}
    store = state_file(brand)

    def work(data):
        taken = sorted(c["test"]["day"] for c in data["clips"].values() if c.get("test"))
        day = first_day
        if taken:
            day = max(day, datetime.strptime(taken[-1], "%Y-%m-%d").date() + timedelta(days=1))
        last_allowed = day + timedelta(days=days - 1)
        posts, records = [], {}
        for index, clip in enumerate(found["clips"]):
            if clip["kind"] != "short" or len(clip["files"]) < 2:
                continue
            if (data["clips"].get(clip["key"]) or {}).get("test"):
                continue
            if len(clip["files"]) > MAX_VERSIONS:
                result["deferred"].append({"clip": clip["key"], "why": "it has more than %d versions; a test that "
                                           "wide cannot be spaced through one day" % MAX_VERSIONS})
                continue
            words = [SH.description_for(f["path"], f["clip_stem"], TEST_PLATFORM)[0] for f in clip["files"]]
            if not all(words):
                result["deferred"].append({"clip": clip["key"], "why": "%d of its %d versions have no description "
                                           "for TikTok yet" % (sum(1 for w in words if not w), len(words))})
                continue
            if len({SEND.text_sha(w) for w in words}) < len(words):
                result["deferred"].append({"clip": clip["key"], "why": "two of its versions have the same words. "
                                           "Give each version its own description, or their results cannot be "
                                           "told apart"})
                continue
            if day > last_allowed:
                result["deferred"].append({"clip": clip["key"], "why": "no test day left in this plan; it will be "
                                           "planned next time"})
                continue
            day_text = day.strftime("%Y-%m-%d")
            cid = SH.clip_hash(clip["key"])
            try:
                media = [SH.media_path_for(brand, found, f, copy=save) for f in clip["files"]]
            except SH.ShortsError as e:
                result["needs_a_look"].append({"clip": clip["key"], "why": str(e)})
                continue
            wave = {"clip": clip["key"], "day": day_text, "posts": []}
            entries = {}
            for i, (f, (local, iso)) in enumerate(zip(clip["files"], _wave_times(brand, day_text, len(words), index))):
                post_id = "test-%s-%s-%s-%s" % (cid, _version_hash(f["rel"]), identity, TEST_PLATFORM)
                posts.append(P.Post(id=post_id, brand=brand.id, identity=identity, platform=TEST_PLATFORM,
                                    text=words[i], media_paths=[media[i]], topic_id=clip["key"],
                                    shape="short-video", scheduled_time_local=local, scheduled_time_iso=iso))
                entries[post_id] = {"file": f["rel"], "version": f["version"] or os.path.basename(f["rel"]),
                                    "media": media[i], "when_iso": iso}
                wave["posts"].append({"id": post_id, "time": local[-5:], "video": os.path.basename(f["rel"])})
            records[clip["key"]] = {"clip": cid, "clip_stem": clip["files"][0]["clip_stem"],
                                    "test": {"identity": identity, "day": day_text, "posts": entries}}
            result["waves"].append(wave)
            day += timedelta(days=1)
        if posts:
            P.check_batch(posts, brand)
        result["posts"] = posts
        if save and posts:
            path = _batch_path(brand, "promote-test")
            P.save_batch(posts, path, {"kind": "promote-test", "made_by": "test-and-promote", "warning": WARNING})
            for key, record in records.items():
                record["test"]["batch"] = os.path.basename(path)
                data["clips"][key] = record
            result["saved"], result["batch"] = True, path

    if save:
        with store.edit() as data:
            work(data)
    else:
        work(store.read())
    return result


# ----------------------------------------------------------------------------- step 2: read the numbers
def _hours_between(earlier_iso, later_iso):
    try:
        a = datetime.fromisoformat(earlier_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(later_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (b - a).total_seconds() / 3600.0


def read_results(brand, clip_key=None):
    """The numbers for every version under test, from this computer's results archive. Offline.

    A version's row is found by the scheduling service's post id that the ledger recorded when
    it was sent. No id, or no archived row carrying that id, means no numbers: never a guess."""
    _need_brand(brand)
    if not is_on(brand):
        return _off(brand)
    data = state_file(brand).read()
    sends = {}
    for op in Ledger(brand).all().values():
        if op.get("state") in ("sent", "confirmed") and op.get("provider_post_id"):
            sends[op["post_id"]] = str(op["provider_post_id"])
    rows, _bad = R.load_archive(brand)
    latest = {}
    for r in rows:
        ppid = str(r.get("provider_post_id") or "")
        if not ppid or r.get("platform") != TEST_PLATFORM:
            continue
        if ppid not in latest or (r.get("captured_at") or "") > (latest[ppid].get("captured_at") or ""):
            latest[ppid] = r
    out = []
    for key, clip in sorted(data["clips"].items()):
        if clip_key is not None and key != clip_key:
            continue
        if not clip.get("test"):
            continue
        versions = []
        for post_id, v in sorted(clip["test"]["posts"].items()):
            ppid = sends.get(post_id, "")
            row = latest.get(ppid) if ppid else None
            m = (row or {}).get("metrics") or {}

            def number(name, m=m):
                v = m.get(name)
                return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0

            hours = _hours_between(row.get("published_at") or "", row.get("captured_at") or "") if row else None
            measured = bool(row and hours is not None and hours > 0)
            versions.append({"post_id": post_id, "version": v.get("version"), "file": v.get("file"),
                             "sent": bool(ppid), "provider_post_id": ppid, "measured": measured,
                             "views": number("views"), "saves": number("saves"), "shares": number("shares"),
                             "likes": number("likes"), "comments": number("comments"),
                             "hours_live": round(hours, 1) if measured else None,
                             "views_per_hour": round(number("views") / max(hours, 1.0), 2) if measured else None,
                             "url": (row or {}).get("url") or ""})
        out.append({"clip": key, "day": clip["test"]["day"], "versions": versions,
                    "winner": (clip.get("winner") or {}).get("post_id"),
                    "promoted": bool(clip.get("promotion"))})
    return {"enabled": True, "brand": brand.id, "clips": out}


# ----------------------------------------------------------------------------- step 3: pick a winner
def pick_winner(brand, clip_key, floor=None, min_hours=MIN_TEST_HOURS, allow_partial=False):
    """Decide one clip. Returns {"winner": post_id or None, "reason", "numbers": [...], "rule"}.
    A decision is written down once, with its numbers, and is never re-made."""
    _need_brand(brand)
    if not is_on(brand):
        return _off(brand)
    floor = min_views(brand) if floor is None else floor
    read = read_results(brand, clip_key)
    if not read["clips"]:
        raise PromoteError("'%s' has no test wave on record for %s." % (clip_key, brand.name))
    clip = read["clips"][0]
    numbers = clip["versions"]
    rule = RULE % floor
    answer = {"enabled": True, "brand": brand.id, "clip": clip_key, "winner": None, "numbers": numbers, "rule": rule}
    if clip["winner"]:
        return dict(answer, winner=clip["winner"], reason="a winner was already picked for this clip")

    unsent = [v for v in numbers if not v["sent"]]
    measured = [v for v in numbers if v["measured"]]
    if unsent and not allow_partial:
        return dict(answer, reason="%d of %d versions have not been scheduled yet" % (len(unsent), len(numbers)))
    if len(measured) < len(numbers) and not allow_partial:
        return dict(answer, reason="%d of %d versions have no results yet. Run a results check a day after the "
                                   "last one went out" % (len(numbers) - len(measured), len(numbers)))
    if len(measured) < 2:
        return dict(answer, reason="a winner needs at least two versions with results; there %s %d"
                                   % ("is" if len(measured) == 1 else "are", len(measured)))
    youngest = min(v["hours_live"] for v in measured)
    if youngest < min_hours:
        return dict(answer, reason="the newest version has only %.1f hours of results; it needs %d"
                                   % (youngest, min_hours))
    eligible = [v for v in measured if v["views"] >= floor]
    if not eligible:
        return dict(answer, reason="no version reached %d views (the best has %d), so nothing will be promoted"
                                   % (floor, max(v["views"] for v in measured)))
    ranked = sorted(eligible, key=lambda v: (v["views_per_hour"], v["saves"], v["shares"]), reverse=True)
    if len(ranked) > 1 and all(ranked[0][k] == ranked[1][k] for k in ("views_per_hour", "saves", "shares")):
        return dict(answer, reason="the top two versions are level on views per hour, saves and shares, so no "
                                   "winner is declared")
    best = ranked[0]
    decided_at = time.strftime("%Y-%m-%d %H:%M:%S")
    with state_file(brand).edit() as data:
        record = data["clips"][clip_key]
        if not record.get("winner"):
            record["winner"] = {"post_id": best["post_id"], "file": best["file"], "version": best["version"],
                                "decided_at": decided_at, "rule": rule, "numbers": numbers}
    S.append_lines(os.path.join(brand.state_dir, DECISIONS_FILE),
                   [{"at": decided_at, "brand": brand.id, "clip": clip_key, "winner": best["post_id"],
                     "rule": rule, "allow_partial": bool(allow_partial), "numbers": numbers}])
    return dict(answer, winner=best["post_id"],
                reason="%s won with %.2f views per hour (%d views in %.1f hours, %d saves, %d shares)"
                       % (best["version"], best["views_per_hour"], best["views"], best["hours_live"],
                          best["saves"], best["shares"]))


# ----------------------------------------------------------------------------- step 4: promote the winner
def plan_promotion(brand, clip_key=None, provider=None, days=30, save=False, today=None):
    """The winner of each decided clip to the brand's OTHER connected platforms, booked on the same
    calendar as the daily shorts: one per account per day, never two accounts on one day, and
    each winner to each account once. A preview unless `save`; never sends."""
    _need_brand(brand)
    if not is_on(brand):
        return _off(brand)
    today = today or datetime.now(ZoneInfo(brand.timezone)).date()
    begin = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    accounts = [(i, p) for i, p in SH.video_accounts(brand)[0] if p != TEST_PLATFORM]
    caps = SH.per_day_counts(brand)
    result = {"enabled": True, "brand": brand.id, "warning": WARNING, "saved": False, "batch": None, "posts": [],
              "needs_description": [], "needs_a_look": [], "notes": []}
    if not accounts:
        result["notes"].append("%s has no other connected video account to promote to." % brand.name)
        return result
    inbox, inside = SH.inbox_folder(brand)
    found = {"inbox": inbox, "inside_brand": inside}
    all_accounts = SH.video_accounts(brand)[0]
    store, shorts_store = state_file(brand), SH.state_file(brand)

    def work(data, shorts_data):
        wanted, words_index = [], {}
        for key, clip in sorted(data["clips"].items()):
            if (clip_key is not None and key != clip_key) or not clip.get("winner"):
                continue
            rel = clip["winner"]["file"]
            source = os.path.join(inbox, *rel.split("/"))
            if not os.path.isfile(source):
                result["needs_a_look"].append({"clip": key, "why": "the winning video is no longer in the inbox"})
                continue
            for identity, platform in accounts:
                words, _name = SH.description_for(source, clip.get("clip_stem") or "", platform)
                wanted.append((key, clip, rel, source, identity, platform, words))
                if words:
                    words_index.setdefault((platform, SEND.text_sha(words)), ("short", clip["clip"]))
        book, _dropped, notes = SH.existing_bookings(brand, shorts_data, provider, words_index, today)
        result["notes"].extend(notes)
        posts, promotions, bookings = [], {}, {}
        for key, clip, rel, source, identity, platform, words in wanted:
            cid = clip["clip"]
            if (cid, identity, platform) in book.done:
                continue                                 # each winner goes to each account once
            if not words:
                result["needs_description"].append({"clip": key, "platform": platform})
                continue
            resume = max(begin, book.last_day.get((identity, platform, "short"), begin))
            until = (datetime.strptime(resume, "%Y-%m-%d").date() + timedelta(days=days - 1)).strftime("%Y-%m-%d")
            day = book.first_free(cid, identity, platform, "short", caps[platform], resume, until)
            if day is None:
                result["notes"].append("'%s' did not fit on %s in the next %d days." % (key, platform, days))
                continue
            try:
                media = SH.media_path_for(brand, found, {"rel": rel, "path": source}, copy=save)
            except SH.ShortsError as e:
                result["needs_a_look"].append({"clip": key, "why": str(e)})
                continue
            nth = book.count[(identity, platform, "short", day)]
            local, iso = SH._slot(brand, day, all_accounts.index((identity, platform)), nth)
            post_id = "promo-%s-%s-%s" % (cid, identity, platform)
            book.add(cid, identity, platform, "short", day, post_id=post_id)
            posts.append(P.Post(id=post_id, brand=brand.id, identity=identity, platform=platform, text=words,
                                media_paths=[media], topic_id=key, shape="short-video",
                                media_type=SH.MEDIA_TYPE["short"].get(platform, ""),
                                scheduled_time_local=local, scheduled_time_iso=iso))
            bookings[post_id] = {"clip": cid, "clip_key": key, "identity": identity, "platform": platform,
                                 "lane": "short", "day": day, "file": rel}
            promotions.setdefault(key, {})[post_id] = {"identity": identity, "platform": platform, "day": day}
        posts.sort(key=lambda p: (p.scheduled_time_iso, p.identity, p.platform))
        if posts:
            P.check_batch(posts, brand)
            P.assert_drip(posts)
        result["posts"] = posts
        if save and posts:
            path = _batch_path(brand, "promote-winners")
            P.save_batch(posts, path, {"kind": "promote-winners", "made_by": "test-and-promote", "warning": WARNING})
            name = os.path.basename(path)
            for post_id, b in bookings.items():
                shorts_data["bookings"][post_id] = dict(b, batch=name)
            for key, planned in promotions.items():
                record = data["clips"][key].setdefault("promotion", {"posts": {}})
                for post_id, p in planned.items():
                    record["posts"][post_id] = dict(p, batch=name)
            result["saved"], result["batch"] = True, path

    if save:
        with store.edit() as data:
            with shorts_store.edit() as shorts_data:
                work(data, shorts_data)
    else:
        work(store.read(), shorts_store.read())
    return result


# ----------------------------------------------------------------------------- sending, and where things stand
def send(brand, batch_path, provider, confirm=False, limit=None):
    """Send a test-wave or promotion batch. The same gates and ledger as every other send; the
    only difference is that it refuses outright while the loop is off."""
    _need_brand(brand)
    if not is_on(brand):
        return _off(brand)
    report = SEND.schedule_batch(brand, batch_path, provider, confirm=confirm, limit=limit)
    report["enabled"], report["warning"] = True, WARNING
    return report


def status(brand):
    _need_brand(brand)
    if not is_on(brand):
        return _off(brand)
    read = read_results(brand)
    lines = [WARNING]
    for clip in read["clips"]:
        sent = sum(1 for v in clip["versions"] if v["sent"])
        measured = sum(1 for v in clip["versions"] if v["measured"])
        if clip["promoted"]:
            where = "winner picked and its promotion is planned"
        elif clip["winner"]:
            where = "winner picked; promotion not planned yet"
        elif sent < len(clip["versions"]):
            where = "test planned for %s (%d of %d versions scheduled)" % (clip["day"], sent, len(clip["versions"]))
        else:
            where = "testing since %s (%d of %d versions have results)" % (clip["day"], measured, len(clip["versions"]))
        lines.append("  %s: %s" % (clip["clip"], where))
    if not read["clips"]:
        lines.append("  No clips are in the loop yet.")
    return {"enabled": True, "brand": brand.id, "clips": read["clips"], "lines": lines}


def describe_numbers(answer):
    """A decision with the numbers behind it, as lines a person can read."""
    lines = ["%s: %s." % (answer["clip"], answer["reason"]), "  The rule: %s." % answer["rule"]]
    for v in answer["numbers"]:
        if v["measured"]:
            lines.append("  %s%s: %d views in %.1f hours = %.2f per hour, %d saves, %d shares"
                         % ("WINNER " if v["post_id"] == answer["winner"] else "", v["version"], v["views"],
                            v["hours_live"], v["views_per_hour"], v["saves"], v["shares"]))
        else:
            lines.append("  %s: %s" % (v["version"], "no results yet" if v["sent"] else "not scheduled yet"))
    return "\n".join(lines)
