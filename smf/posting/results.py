"""results.py - did it go out, and how did it do. Every call here only READS from the service.

    reconcile(brand, provider)              settle sends that never got a clear answer
    publish_health(brand, provider, 14)     posts past their time that the network refused
    harvest_metrics(brand, provider, 30)    save today's numbers into the brand's own archive
    summary(brand, 30)                      plain numbers from the archive; works offline

All of it runs when asked. Nothing here installs a timer or a background job.

WHY A HEALTH CHECK EXISTS AT ALL
A scheduling service saying "accepted" means the post is on its calendar. It says nothing about
what the network does when the time comes, and a network can refuse for reasons nobody sees
from here: an expired login, a locked account, a video it does not like. The refusal is written
in one place only, the status on the calendar entry. Looking at results cannot find it either,
because a post that never went out has no results: it is missing, not failing. So this module
reads the calendar for posts whose time has passed and reports the ones that did not go out,
with the network's own reason.

"I COULD NOT LOOK" IS NOT "ALL CLEAR"
If the calendar cannot be read for ANY of the brand's accounts, the check raises instead of
returning an empty list. An empty list from a check that never ran is the most dangerous answer
this module could give.

WHY A LOCAL ARCHIVE
Scheduling services show a short window of results and keep the rest only while the plan is
paid for. Numbers also keep moving after a post goes out. So each harvest adds one snapshot per
post per day to Client/<brand>/_state/metrics/<YYYY-MM>.jsonl: one file per month, lines only
ever added, already-written lines never touched. A post's series of snapshots is its growth curve.
Young posts are captured every time; older ones at most weekly, since their numbers barely move.

TWO KINDS OF ID (read this before trusting a join)
`provider_post_id` is the scheduling service's id for a calendar entry. The `post_id` on a
results row is usually the NETWORK's own id for the published post. They are different numbering
systems, so comparing them finds nothing. Each harvested row is therefore linked back to the
send it came from, and stamped with that send's `provider_post_id`, by one of two EXACT tests:
the ids are equal (for a service that uses one numbering), or the row's words are exactly the
words of one and only one send to that same account. Words that match two sends link to
neither. Nothing is ever matched on similar or partial words. Rows that cannot be linked are
still archived; they simply carry no `provider_post_id`.
"""
from __future__ import annotations

import glob
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from smf.posting import send as SEND
from smf.posting import state as S
from smf.posting.ledger import Ledger, operation_key
from smf.posting.provider import ProviderError
from smf.studio import posts as P

METRICS_DIR = "metrics"
NUMBERS = ("views", "likes", "comments", "shares", "saves", "reach", "impressions", "clicks", "watch_minutes")
FRESH_DAYS = 30                 # younger than this: one snapshot on every day a harvest runs
OLDER_EVERY_DAYS = 7            # older: at most one snapshot a week
CALENDAR_CHUNK_DAYS = 60        # long calendar windows are slow and flaky; ask in pieces
STALL_GRACE = timedelta(hours=1)
JUDGE_AFTER = timedelta(days=2)  # a post measured sooner than this has not had its chance yet
WENT_OUT = frozenset({"PUBLISHED"})
STILL_FINE = frozenset({"PENDING", "DRAFT"})
WAITING_ON_A_PERSON = frozenset({"AWAITING_CONFIRMATION"})
FALLBACK_REASON = {
    "refused": "The network refused it and gave no reason. Open the scheduling service to see more.",
    "stalled": "Its time has passed and it has not gone out. The scheduling service may be stuck, or the "
               "account may need to be connected again.",
    "needs-confirmation": "The network is waiting for someone to confirm it in the network's own app.",
    "unclear": "Its time has passed and the scheduling service gave no status for it. Check it there.",
}


class ResultsError(Exception):
    """Worded for the person."""


def _utc_now(now=None):
    now = now or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _accounts(brand):
    """{account id: {platform: identity}} for every target of THIS brand that has an id."""
    out = defaultdict(dict)
    for t in brand.targets():
        pbid = t.get("provider_brand_id")
        if isinstance(pbid, int) and not isinstance(pbid, bool):
            out[pbid][t["platform"]] = t["identity"]
    return out


def _require_provider_matches(brand, provider):
    configured = (brand.data.get("accounts") or {}).get("provider") or "none"
    if configured == "none":
        raise ResultsError("%s is not linked to a scheduling service, so there is nothing to check." % brand.name)
    if provider.name != configured:
        raise ResultsError("%s posts through %s, but this check was started with %s."
                           % (brand.name, configured, provider.name))


# ----------------------------------------------------------------------------- reconcile
def batch_files(brand):
    folder = brand.path("Output", "batches")
    return sorted(p for p in glob.glob(os.path.join(glob.escape(folder), "*.json")) if os.path.isfile(p))


def heal_batches(brand, operations=None):
    """Bring the brand's batch files in line with the posting record: a post the record says was
    scheduled becomes `scheduled`; a parked post the record has freed goes back to `approved`.
    Returns [(post_id, new_status)]."""
    operations = Ledger(brand).all() if operations is None else operations
    healed = []
    for path in batch_files(brand):
        try:
            posts, _meta = P.load_batch(path, brand.id)
        except (ValueError, OSError):
            continue                                    # another brand's file, or not a batch: not ours to touch
        for post in posts:
            parked = post.status == "blocked" and SEND.UNCLEAR_MARK in (post.feedback or "")
            if not (parked or post.status == "approved"):
                continue
            op = operations.get(operation_key(post))
            if not op:
                continue
            if op["state"] in ("sent", "confirmed"):
                ppid = op.get("provider_post_id") or ""
                SEND._save_post_outcome(brand, path, post, lambda p, ppid=ppid: SEND._mark_scheduled(p, ppid),
                                        note_if_changed=SEND.WENT_OUT_NOTE % ppid)
                healed.append((post.id, "scheduled"))
            elif op["state"] == "failed" and parked:
                SEND._save_post_outcome(brand, path, post, SEND.free_for_retry)
                healed.append((post.id, "approved"))
    return healed


def reconcile(brand, provider, now=None):
    """Settle every send that never got a clear answer by looking at the service's calendar.
    Found there -> scheduled. Not there, on a calendar read long enough after the send -> freed,
    and safe to send again. Not there but read too soon -> left unclear and checked again next
    time, because a calendar can lag behind a post it has already taken. Reads only.

    One extra rule on top of the ledger's own matching: a calendar entry is ONE post. If a send
    is "found" as an entry that another send already owns, nobody can tell the two apart from
    here, so it goes back to unclear and a person settles it by looking (see settle_by_hand).
    `now` is for tests; left out, it is the time of the call."""
    _require_provider_matches(brand, provider)
    led = Ledger(brand)
    before = led.all()
    report = led.reconcile(provider, brand.timezone, now=now)
    after = led.all()
    owners = defaultdict(list)
    for key, op in after.items():
        if op["state"] in ("sent", "confirmed") and op.get("provider_post_id"):
            owners[(str(op.get("provider_brand_id")), str(op["provider_post_id"]))].append(key)
    unclear = []
    for keys in owners.values():
        if len(keys) < 2:
            continue
        for key in keys:
            if before.get(key, {}).get("state") in ("unknown", "reserved"):
                led.mark_unknown(key, "it looks the same as another post on the service's calendar, so it could "
                                      "not be told apart. A person has to look.")
                unclear.append(after[key]["post_id"])
    report["found"] = [p for p in report["found"] if p not in unclear]
    report["unclear"] = unclear
    report["too_soon"] = list(report.get("too_soon") or [])
    report["could_not_check"] = list(report.get("could_not_check") or [])
    report["still_waiting"] = [op["post_id"] for op in led.unresolved().values() if op["post_id"] not in unclear]
    report["healed"] = heal_batches(brand, led.all())
    return report


def settle_by_hand(brand, post_id, arrived, provider_post_id=""):
    """A person looked at the service's calendar and says whether this post is there.
    Only for sends the calendar check could not settle. Changes this computer's record only."""
    led = Ledger(brand)
    keys = [k for k, op in led.unresolved().items() if op.get("post_id") == post_id]
    if not keys:
        raise ResultsError("There is no unclear send for a post called '%s'. Nothing was changed." % post_id)
    if len(keys) > 1:
        raise ResultsError("More than one unclear send is called '%s', so it is not safe to settle them "
                           "together. Ask Claude to look at the posting record." % post_id)
    if arrived:
        led.mark_sent(keys[0], provider_post_id or "confirmed-by-hand")
    else:
        led.mark_failed(keys[0], "a person checked the service's calendar and it was not there")
    return heal_batches(brand, led.all())


# ----------------------------------------------------------------------------- publish health
def _calendar(provider, pbid, start, end, tz):
    entries, cursor = {}, start
    while cursor < end:
        nxt = min(cursor + timedelta(days=CALENDAR_CHUNK_DAYS), end)
        for e in provider.calendar(pbid, cursor.strftime("%Y-%m-%dT%H:%M:%S"), nxt.strftime("%Y-%m-%dT%H:%M:%S"), tz):
            entries[str(e.get("id"))] = e
        cursor = nxt
    return list(entries.values())


def _local_naive(text):
    try:
        return datetime.fromisoformat((text or "").strip().replace(" ", "T")[:19])
    except ValueError:
        return None


def publish_health(brand, provider, days_back=14, now=None):
    """Posts on THIS brand's accounts whose time has passed and that did not go out.

    Returns {"checked", "problems": [...], "groups": [...], "could_not_check": [...]}. Each
    problem has: kind (refused | stalled | needs-confirmation | unclear), platform, when,
    provider_post_id, post_id (the Factory's, when this computer sent it), reason, text_start.
    Raises ResultsError when none of the brand's accounts could be read."""
    _require_provider_matches(brand, provider)
    accounts = _accounts(brand)
    if not accounts:
        raise ResultsError("%s has no accounts linked yet, so there is nothing to check." % brand.name)
    tz = brand.timezone
    now_local = _utc_now(now).astimezone(ZoneInfo(tz)).replace(tzinfo=None)
    start = now_local - timedelta(days=max(1, int(days_back)))
    ours = {str(op.get("provider_post_id")): op.get("post_id")
            for op in Ledger(brand).all().values() if op.get("provider_post_id")}
    problems, could_not, checked = [], [], 0
    for pbid, platforms in sorted(accounts.items()):
        try:
            entries = _calendar(provider, pbid, start, now_local, tz)
        except ProviderError as e:
            could_not.append({"provider_brand_id": pbid, "why": str(e)})
            continue
        for e in entries:
            if e.get("draft"):
                continue
            networks = [n for n in (e.get("network") or "").split(",") if n]
            platform = next((n for n in networks if n in platforms), None)
            when = _local_naive(e.get("when"))
            if platform is None or when is None or when > now_local - STALL_GRACE:
                continue
            checked += 1
            statuses = {s.strip().upper() for s in (e.get("status") or "").split(",") if s.strip()}
            if not statuses:
                kind = "unclear"
            elif statuses - WENT_OUT - STILL_FINE - WAITING_ON_A_PERSON:
                kind = "refused"
            elif statuses & WAITING_ON_A_PERSON:
                kind = "needs-confirmation"
            elif statuses & STILL_FINE and not statuses & WENT_OUT:
                kind = "stalled"
            else:
                continue
            problems.append({"kind": kind, "platform": platform, "identity": platforms[platform],
                             "when": when.strftime("%Y-%m-%d %H:%M"), "provider_post_id": str(e.get("id")),
                             "post_id": ours.get(str(e.get("id")), ""), "status": ",".join(sorted(statuses)),
                             "reason": (e.get("detail") or "").strip() or FALLBACK_REASON[kind],
                             "text_start": " ".join((e.get("text") or "").split())[:80]})
    if could_not and len(could_not) == len(accounts):
        raise ResultsError("The scheduling service could not be read for any of this brand's accounts, so whether "
                           "posts went out is UNKNOWN, not fine. %s" % could_not[0]["why"])
    problems.sort(key=lambda p: (p["platform"], p["when"]))
    grouped = defaultdict(list)
    for p in problems:
        grouped[(p["kind"], p["platform"], p["reason"])].append(p)
    groups = []
    for (kind, platform, reason), items in sorted(grouped.items()):
        days = sorted(i["when"][:10] for i in items)
        groups.append({"kind": kind, "platform": platform, "count": len(items), "reason": reason,
                       "from": days[0], "to": days[-1]})
    return {"brand": brand.id, "checked": checked, "problems": problems, "groups": groups,
            "could_not_check": could_not}


# ----------------------------------------------------------------------------- the archive
def metrics_dir(brand):
    return os.path.join(brand.state_dir, METRICS_DIR)


def load_archive(brand):
    """(rows, unreadable_lines) from every month file, oldest first. Rows of another brand are
    never returned, whatever a file says."""
    rows, bad = [], 0
    folder = metrics_dir(brand)
    for path in sorted(glob.glob(os.path.join(glob.escape(folder), "*.jsonl"))):
        got, b = S.read_lines(path)
        bad += b
        rows.extend(r for r in got if r.get("brand") == brand.id)
    return rows, bad


def latest_by_post(rows):
    best = {}
    for r in rows:
        k = (r.get("platform"), str(r.get("post_id")))
        if k not in best or (r.get("captured_at") or "") > (best[k].get("captured_at") or ""):
            best[k] = r
    return list(best.values())


def as_iso(value, tz):
    """One comparable shape for a publish time, in UTC: 'YYYY-MM-DDTHH:MM:SSZ'. Networks disagree
    on the format: a space or a T, an offset with or without a colon, or seconds or milliseconds
    since 1970. A time with no offset is taken as the brand's local time."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000.0 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip().replace(" ", "T")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text).replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(tz))
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _days_between(earlier, later):
    try:
        return (datetime.strptime(later[:10], "%Y-%m-%d") - datetime.strptime(earlier[:10], "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return None


def _sends_for_linking(brand):
    """What this computer sent, for linking results back. Returns (by_id, by_words) where
    by_words maps (account, platform, fingerprint of the words) to a send ONLY when exactly one
    send has those words on that account; words used twice are left out on purpose."""
    receipts, _bad = S.read_lines(SEND.sent_log_path(brand))
    by_id, counted = {}, defaultdict(list)
    for r in receipts:
        if r.get("brand") != brand.id:
            continue
        account = (str(r.get("provider_brand_id")), r.get("platform"))
        by_id[account + (str(r.get("provider_post_id")),)] = r
        fingerprint = r.get("title_sha256") if r.get("platform") == "youtube" else r.get("text_sha256")
        if fingerprint:
            counted[account + (fingerprint,)].append(r)
    by_words = {k: v[0] for k, v in counted.items()
                if len({x.get("provider_post_id") for x in v}) == 1}
    return by_id, by_words


def harvest_metrics(brand, provider, days_back=30, now=None):
    """Fetch results for THIS brand's connected accounts and add today's snapshots to the archive.
    Running it twice in a day adds nothing the second time. Reads only.

    Returns {"captured_at", "new_rows", "linked", "by_account": {...}, "errors": [...]}.
    Raises ResultsError when no account at all could be read."""
    _require_provider_matches(brand, provider)
    accounts = _accounts(brand)
    if not accounts:
        raise ResultsError("%s has no accounts linked yet, so there are no results to fetch." % brand.name)
    utc = _utc_now(now)
    captured_at = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    today = captured_at[:10]
    local_today = utc.astimezone(ZoneInfo(brand.timezone)).date()
    start_date = (local_today - timedelta(days=max(1, int(days_back)))).strftime("%Y-%m-%d")
    end_date = (local_today + timedelta(days=1)).strftime("%Y-%m-%d")

    existing, _bad = load_archive(brand)
    have_today, last_capture = set(), {}
    for r in existing:
        k = (r.get("platform"), str(r.get("post_id")))
        have_today.add(k + (r.get("capture_date"),))
        if (r.get("capture_date") or "") > last_capture.get(k, ""):
            last_capture[k] = r.get("capture_date") or ""

    by_id, by_words = _sends_for_linking(brand)
    new_rows, by_account, errors, reached = [], {}, [], 0
    for pbid, platforms in sorted(accounts.items()):
        for platform, identity in sorted(platforms.items()):
            label = "%s as '%s'" % (platform, identity)
            try:
                fetched = provider.metrics(pbid, platform, start_date, end_date, brand.timezone)
            except ProviderError as e:
                errors.append("%s: %s" % (label, e))
                continue
            reached += 1
            kept = 0
            for rec in fetched or []:
                network_id = rec.get("post_id")
                if network_id in (None, ""):
                    continue
                k = (platform, str(network_id))
                if k + (today,) in have_today:
                    continue
                published = as_iso(rec.get("published_at"), brand.timezone)
                last = last_capture.get(k)
                age = _days_between(published, today) if published else None
                if last and age is not None and age > FRESH_DAYS and (_days_between(last, today) or 0) < OLDER_EVERY_DAYS:
                    continue
                words = rec.get("text") or ""
                account = (str(pbid), platform)
                sent = by_id.get(account + (str(network_id),))
                how = "id" if sent else ""
                if not sent and words.strip():
                    sent = by_words.get(account + (SEND.text_sha(words),))
                    how = "words" if sent else ""
                row = {"captured_at": captured_at, "capture_date": today, "brand": brand.id, "identity": identity,
                       "platform": platform, "provider_brand_id": pbid, "post_id": str(network_id),
                       "provider_post_id": str(sent["provider_post_id"]) if sent else "",
                       "factory_post_id": sent["post_id"] if sent else "", "linked_by": how,
                       "published_at": published, "url": rec.get("url") or "", "text": words,
                       "metrics": {n: rec.get(n) for n in NUMBERS if rec.get(n) is not None}}
                have_today.add(k + (today,))
                last_capture[k] = today
                new_rows.append(row)
                kept += 1
            by_account[label] = {"fetched": len(fetched or []), "new": kept}
    if reached == 0:
        raise ResultsError("Results could not be fetched for any of this brand's accounts, so nothing was saved. %s"
                           % (errors[0] if errors else ""))
    path = os.path.join(metrics_dir(brand), today[:7] + ".jsonl")
    S.append_lines(path, new_rows, lock_path=os.path.join(brand.state_dir, "metrics.lock"))
    return {"brand": brand.id, "captured_at": captured_at, "new_rows": len(new_rows),
            "linked": sum(1 for r in new_rows if r["provider_post_id"]), "by_account": by_account, "errors": errors}


# ----------------------------------------------------------------------------- plain numbers
def _number(row, name):
    v = (row.get("metrics") or {}).get(name)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _brief(row):
    return {"platform": row.get("platform"), "views": _number(row, "views"), "url": row.get("url") or "",
            "text_start": " ".join((row.get("text") or "").split())[:60], "typed": row.get("source") == "typed"}


def _has_views(row):
    v = (row.get("metrics") or {}).get("views")
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _age_when_measured(row):
    """How long the post had been up when these numbers were taken, or None when either time is
    missing. A post measured six hours in stays six hours old, however long ago that was."""
    try:
        published = datetime.strptime(row.get("published_at") or "", "%Y-%m-%dT%H:%M:%SZ")
        captured = datetime.strptime(row.get("captured_at") or "", "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return captured - published


def _plural(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def summary(brand, days=30, now=None):
    """Numbers a person can act on, from this computer's own records. No connection needed.

    The weakest posts are only the fair comparisons: never one already among the most viewed, never
    one with no view count (a missing number is not zero), and never one that had been up less than
    JUDGE_AFTER when its numbers were taken."""
    utc = _utc_now(now)
    since = (utc - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_iso = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    sent = upcoming = failed = unclear = 0
    for op in Ledger(brand).all().values():
        when = as_iso(op.get("scheduled_time_iso"), brand.timezone)
        if op["state"] in ("sent", "confirmed"):
            if when > now_iso:
                upcoming += 1
            elif when >= since:
                sent += 1
        elif op["state"] == "failed":
            failed += 1
        elif op["state"] in ("unknown", "reserved"):
            unclear += 1
    rows, unreadable = load_archive(brand)
    from smf.posting import hand_posted          # it reads this module too, so it is imported when used
    counted, by_hand = hand_posted.for_summary(brand, rows, since)
    recent = [r for r in latest_by_post(counted) if (r.get("published_at") or "") >= since]
    typed_in = sum(1 for r in recent if r.get("source") == "typed")
    totals = {n: sum(_number(r, n) for r in recent) for n in ("views", "likes", "comments", "shares", "saves")}
    by_platform = defaultdict(lambda: {"posts": 0, "views": 0})
    for r in recent:
        by_platform[r.get("platform")]["posts"] += 1
        by_platform[r.get("platform")]["views"] += _number(r, "views")
    top = sorted(recent, key=lambda r: _number(r, "views"), reverse=True)[:3]
    fair, too_new, no_views = [], 0, 0
    for r in recent:
        if any(r is t for t in top):
            continue
        age = _age_when_measured(r)
        if not _has_views(r):
            no_views += 1
        elif age is None or age < JUDGE_AFTER:
            too_new += 1
        else:
            fair.append(r)
    weakest = sorted(fair, key=lambda r: _number(r, "views"))[:3]

    def shown(r):
        return "    %d views  %s  %s  \"%s\"" % (_number(r, "views"), r.get("platform"),
                                                (r.get("published_at") or "")[:10],
                                                " ".join((r.get("text") or "").split())[:60]) \
            + ("  (typed in)" if r.get("source") == "typed" else "")

    by_hand_only = (brand.data.get("accounts") or {}).get("provider", "none") == "none"
    lines = ["%s, last %d days:" % (brand.name, days)]
    if not (by_hand_only and sent == upcoming == 0):
        lines.append("  %d post(s) went out through the Factory, %d more are scheduled." % (sent, upcoming))
    if by_hand["hand_posted"]:
        lines.append("  %d post(s) were put up by hand." % by_hand["hand_posted"])
    if unclear:
        lines.append("  %d send(s) never got a clear answer. Run a results check to settle them." % unclear)
    if failed:
        lines.append("  %d send(s) were refused and are waiting to be sent again." % failed)
    if not counted and by_hand_only:
        lines.append("  No results are saved yet. For posts put up by hand, record them and type in their numbers.")
    elif not counted:
        lines.append("  No results are saved yet. Run a results check to fetch them.")
    elif not recent:
        lines.append("  No posts with results in this period.")
    else:
        # A measure no post has is "not given", never a total of zero.
        given = [n for n in totals if any(n in (r.get("metrics") or {}) for r in recent)]
        missing = [n for n in totals if n not in given]
        lines.append("  %d post(s) have results: %s.%s"
                     % (len(recent), ", ".join("%d %s" % (totals[n], n) for n in given) or "no numbers",
                        " Not given: %s." % ", ".join(missing) if missing else ""))
        if typed_in:
            lines.append("  %d of these %d post(s) have numbers you typed in." % (typed_in, len(recent)))
        for platform, n in sorted(by_platform.items(), key=lambda kv: -kv[1]["views"]):
            lines.append("    %s: %d post(s), %d views" % (platform, n["posts"], n["views"]))
        lines.append("  Most viewed:")
        lines.extend(shown(r) for r in top)
        if weakest:
            lines.append("  Least viewed (of the posts that had been up at least two days when measured):")
            lines.extend(shown(r) for r in weakest)
        if too_new:
            lines.append("  %s too new to judge, so left out of the least viewed."
                         % _plural(too_new, "post is", "posts are"))
        if no_views:
            lines.append("  %s no view count, so %s not ranked as weakest."
                         % (_plural(no_views, "post has", "posts have"), "it is" if no_views == 1 else "they are"))
    if by_hand["waiting"]:
        lines.append("  %s you put up by hand %s no numbers yet. Give %s numbers when you have a moment."
                     % (_plural(by_hand["waiting"], "post", "posts"),
                        "has" if by_hand["waiting"] == 1 else "have", "its" if by_hand["waiting"] == 1 else "their"))
    if unreadable:
        lines.append("  %d line(s) of the saved results could not be read and were left out." % unreadable)
    if by_hand["unreadable"]:
        lines.append("  %d line(s) of the record of posts put up by hand could not be read and were left out."
                     % by_hand["unreadable"])
    return {"brand": brand.id, "days": days, "sent": sent, "upcoming": upcoming, "failed": failed,
            "unclear": unclear, "posts_with_results": len(recent), "totals": totals,
            "by_platform": {k: dict(v) for k, v in by_platform.items()},
            "top": [_brief(r) for r in top], "weakest": [_brief(r) for r in weakest],
            "typed_in": typed_in, "hand_posted": by_hand["hand_posted"], "hand_posted_waiting": by_hand["waiting"],
            "unreadable_lines": unreadable, "lines": lines}


def describe_health(health):
    if not health["problems"]:
        lines = ["All clear: %d post(s) past their time were checked and every one went out." % health["checked"]]
    else:
        lines = ["%d post(s) did NOT go out:" % len(health["problems"])]
        for g in health["groups"]:
            span = g["from"] if g["from"] == g["to"] else "%s to %s" % (g["from"], g["to"])
            lines.append("  %s, %d post(s), %s: %s" % (g["platform"], g["count"], span, g["reason"]))
    for c in health["could_not_check"]:
        lines.append("  One account could not be checked, so its posts are UNKNOWN, not fine: %s" % c["why"])
    return "\n".join(lines)
