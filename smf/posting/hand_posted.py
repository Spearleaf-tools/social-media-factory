"""hand_posted.py - results for posts a person put up by hand from a ready-to-post folder.

    mark_posted(brand, post_id, url, when)     "I posted this one, here is its link"
    withdraw(brand, post_id)                    "I didn't post that one after all" (or the link was wrong)
    save_numbers(brand, post_id, {"views": 1200})   the numbers the person read off the post
    write_sheet(brand) / read_sheet(brand, path)    the same, for many posts at once, in a spreadsheet
    for_summary(brand, rows, since)             what results.summary counts

Every function that saves anything is a preview unless `confirm=True`.

WHERE IT IS KEPT
"I posted this" goes in Client/<brand>/_state/hand-posted.jsonl, one line per mark or withdrawal,
lines only ever added. The numbers go into the ordinary results archive (_state/metrics/), as rows
shaped exactly like fetched ones, plus `"source": "typed"`. `post_id` on such a row is the post's
link, because a post put up by hand has no id from a scheduling service, and `provider_post_id` is
always "" so nothing mistakes it for a send. Nothing already written is ever changed: a correction
is a newer row, and the newest row for a post wins.

WHAT IS NEVER TOUCHED
The posting record (ledger) holds only what the Factory itself sent. A post put up by hand was
never sent by the Factory and must never look like it was. The batch file is not changed either:
the post stays `exported`, which already locks it against edits and against being sent.

NEVER A NUMBER NOBODY GAVE
A measure the person did not give is missing, not zero. Numbers must be exact whole numbers: "1.2K"
is a rounded display, and is refused with where to find the exact count.

JOINING A TYPED POST TO A FETCHED ONE
If the brand also uses a scheduling service, results for a post put up by hand may arrive by fetch
too. The fetched numbers then win, and the post is counted once. The two are joined by one of two
exact tests only: the same link (after removing what does not identify a post: the query, the
fragment, "www.", a trailing slash), or the same words on the same platform when exactly one
fetched post and exactly one hand-posted mark have them.
"""
from __future__ import annotations

import csv
import io
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo

from smf.posting import send as SEND
from smf.posting import state as S
from smf.studio import posts as P

LOG = "hand-posted.jsonl"
SHEET_DIR = ("Output", "results-to-fill")
SHEET_FIRST = ("batch", "post_id", "platform", "url", "posted", "first_line")
# The web addresses each network's own links live on. Short links ("vm.tiktok.com", "youtu.be")
# are the network's own too. A link anywhere else is refused, never guessed at.
DOMAINS = {
    "instagram": ("instagram.com", "instagr.am"),
    "facebook": ("facebook.com", "fb.com", "fb.watch"),
    "linkedin": ("linkedin.com", "lnkd.in"),
    "twitter": ("x.com", "twitter.com"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "threads": ("threads.net", "threads.com"),
    "bluesky": ("bsky.app",),
    "pinterest": ("pinterest.com", "pin.it"),
    "gmb": ("google.com", "g.page", "goo.gl"),
}
NETWORK_NAMES = {"twitter": "X", "gmb": "Google Business Profile", "linkedin": "LinkedIn", "tiktok": "TikTok",
                 "youtube": "YouTube"}
FUTURE_GRACE = timedelta(minutes=5)


class HandPostedError(Exception):
    """Worded for the person. Nothing was saved."""


def _results():
    from smf.posting import results as R          # results reads this module too, so import it when used
    return R


def log_path(brand):
    return os.path.join(brand.state_dir, LOG)


def _network(platform):
    return NETWORK_NAMES.get(platform, (platform or "").capitalize())


def _utc_now(now=None):
    now = now or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _z(when):
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------- links
# The parts of a query that ARE the post on these sites ("watch?v=", "permalink.php?story_fbid=").
# Everything else in a query (share and tracking tags) is dropped.
POST_IN_QUERY = {"youtube.com": ("v",),
                 "facebook.com": ("story_fbid", "fbid", "id", "v"), "fb.com": ("story_fbid", "fbid", "id", "v")}


def same_link(url):
    """One comparable shape for a link: no fragment, no "www."/"m.", no trailing slash, no query
    except the parts that name the post (POST_IN_QUERY), and Instagram's /reel/ and /p/ treated as
    the same post. Used only to compare, never saved."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    path = parts.path.rstrip("/")
    if host in ("instagram.com", "instagr.am"):
        path = re.sub(r"^/(?:[^/]+/)?(?:reel|reels|tv|p)/", "/p/", path)
    keep = POST_IN_QUERY.get(host, ())
    named = sorted((k, v) for k, v in parse_qsl(parts.query) if k in keep)
    return "%s%s%s" % (host, path, ("?" + urlencode(named)) if named else "")


def check_link(platform, url):
    """The link, tidied, or HandPostedError saying why it cannot be this platform's post."""
    url = (url or "").strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        parts = None
    if not parts or parts.scheme not in ("http", "https") or not parts.hostname:
        raise HandPostedError("'%s' is not a web address. Copy the post's link from %s (it starts with https://)."
                              % (url, _network(platform)))
    host = parts.hostname.lower()
    allowed = DOMAINS.get(platform)
    if allowed is None:
        raise HandPostedError("The Factory does not know where %s's links live, so it cannot check this one."
                              % _network(platform))
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise HandPostedError("That link is on %s, but this post was for %s. Nothing was saved. Copy the link "
                              "from the post itself on %s." % (host, _network(platform), _network(platform)))
    return url


# ----------------------------------------------------------------------------- numbers
def _whole_number(name, text):
    t = str(text).strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", t):
        return int(t.replace(",", ""))
    if re.fullmatch(r"\d+\.0+", t):                               # a spreadsheet's way of writing 1200
        return int(t.split(".")[0])
    raise HandPostedError("'%s=%s' is not an exact whole number. Numbers shown on a post are often rounded "
                          "(1.2K); use the exact count from the post's insights or analytics, for example "
                          "%s=1234." % (name, t, name))


def parse_measures(pairs):
    """{"views": 1200, ...} from ["views=1200", ...] or a {name: text} map. Unknown names and numbers
    that are not exact whole numbers are refused, all of them at once."""
    known = _results().NUMBERS
    items = list(pairs.items()) if isinstance(pairs, dict) else []
    if not isinstance(pairs, dict):
        for item in pairs or []:
            name, sep, value = str(item).partition("=")
            if not sep:
                raise HandPostedError("Write each number as name=number, for example views=1200.")
            items.append((name, value))
    out, unknown, problems = {}, [], []
    for name, value in items:
        key = re.sub(r"[^a-z]+", "_", str(name).strip().lower()).strip("_")
        if key not in known:
            unknown.append(str(name).strip())
            continue
        try:
            out[key] = _whole_number(key, value)
        except HandPostedError as e:
            problems.append(str(e))
    if unknown:
        problems.insert(0, "The Factory does not keep %s. It keeps: %s." % (", ".join("'%s'" % u for u in unknown),
                                                                         ", ".join(known)))
    if problems:
        raise HandPostedError(" ".join(problems) + " Nothing was saved.")
    if not out:
        raise HandPostedError("No numbers were given, so there is nothing to save.")
    return out


# ----------------------------------------------------------------------------- the marks
def read_marks(brand):
    """({(batch, post_id): mark}, unreadable_lines): every post currently recorded as put up by hand.
    A later withdrawal cancels an earlier mark. Lines of another brand are never returned."""
    rows, bad = S.read_lines(log_path(brand))
    active = {}
    for r in rows:
        if r.get("brand") != brand.id:
            continue
        key = (r.get("batch") or "", r.get("post_id") or "")
        if r.get("action") == "posted":
            active[key] = r
        elif r.get("action") == "withdrawn":
            active.pop(key, None)
    return active, bad


def _find_mark(brand, post_id, batch=None):
    active, _bad = read_marks(brand)
    found = [m for (b, p), m in active.items() if p == post_id and (not batch or b == os.path.basename(batch))]
    if not found:
        raise HandPostedError("'%s' is not recorded as put up by hand yet. Record it first, with its link."
                              % post_id)
    if len(found) > 1:
        raise HandPostedError("More than one post called '%s' is recorded as put up by hand (in %s). Say which "
                              "batch with --batch." % (post_id, ", ".join(sorted(m["batch"] for m in found))))
    return found[0]


def _find_post(brand, post_id, batch=None):
    """(batch file name, post) for THIS brand's post, or a plain refusal."""
    found = []
    for path in _results().batch_files(brand):
        if batch and os.path.basename(path) != os.path.basename(batch):
            continue
        try:
            posts, _meta = P.load_batch(path, brand.id)
        except (ValueError, OSError):
            continue                                    # another brand's file, or not a batch: never ours
        found.extend((os.path.basename(path), p) for p in posts if p.id == post_id and p.brand == brand.id)
    if not found:
        raise HandPostedError("%s has no post called '%s'%s. Nothing was saved."
                              % (brand.name, post_id, " in %s" % batch if batch else ""))
    if len(found) > 1:
        raise HandPostedError("More than one batch has a post called '%s' (%s). Say which batch with --batch. "
                              "Nothing was saved." % (post_id, ", ".join(sorted(b for b, _p in found))))
    return found[0]


def _when(brand, post, text, now):
    """(published_at in UTC, as the person would read it, how it was known)."""
    tz = ZoneInfo(brand.timezone)
    text = (text or "").strip()
    if not text:
        planned = (post.scheduled_time_iso or "").replace("Z", "+00:00")
        try:
            when = datetime.fromisoformat(planned)
        except ValueError:
            raise HandPostedError("Say when it went up, as YYYY-MM-DD HH:MM (or just the date). The post has no "
                                  "planned time to go by.")
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        if when > now + FUTURE_GRACE:
            raise HandPostedError("Its planned time (%s) has not come yet. Say when it really went up, as "
                                  "YYYY-MM-DD HH:MM." % when.astimezone(tz).strftime("%Y-%m-%d %H:%M"))
        return _z(when), when.astimezone(tz).strftime("%Y-%m-%d %H:%M"), "planned"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            # Only the day is known. Count it from the end of that day, so it is never judged too early,
            # but a day that has not begun yet is still to come.
            day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=tz)
            if day > now + FUTURE_GRACE:
                raise HandPostedError("%s is still to come. Say when it really went up." % text)
            when = day.replace(hour=23, minute=59)
            when, how, shown = min(when, now), "date-only", text
        else:
            when = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            how, shown = "given", text
    except ValueError:
        raise HandPostedError("'%s' is not a time the Factory can read. Write it as YYYY-MM-DD HH:MM, for example "
                              "2030-01-30 09:15, or just the date." % text)
    if when > now + FUTURE_GRACE:
        raise HandPostedError("%s is still to come. Say when it really went up." % text)
    return _z(when), shown, how


WHEN_WORDS = {"given": "%s", "date-only": "%s (only the day; counted from the end of it)",
              "planned": "%s (its planned time; say if it went up at a different time)"}


def mark_posted(brand, post_id, url, when=None, batch=None, confirm=False, now=None):
    """Record that the person put this post up by hand. A preview unless confirm=True."""
    now = _utc_now(now)
    batch_name, post = _find_post(brand, post_id, batch)
    if post.status != "exported":
        why = {"scheduled": "it was scheduled through the scheduling service, so its results come from there",
               "posted": "it is already marked as posted"}.get(
            post.status, "it is marked '%s'. Only a post saved to a ready-to-post folder can be recorded as put up "
                         "by hand" % post.status)
        raise HandPostedError("'%s' cannot be recorded as put up by hand: %s. Nothing was saved." % (post_id, why))
    url = check_link(post.platform, url)
    active, _bad = read_marks(brand)
    if (batch_name, post.id) in active:
        raise HandPostedError("'%s' is already recorded as put up by hand, at %s. If that is wrong, withdraw it "
                              "first, then record it again." % (post_id, active[(batch_name, post.id)]["url"]))
    for (b, p), m in active.items():
        if same_link(m["url"]) == same_link(url):
            raise HandPostedError("That link is already recorded for '%s' (in %s). One link is one post. Nothing "
                                  "was saved." % (p, b))
    published_at, shown, how = _when(brand, post, when, now)
    line = {"action": "posted", "brand": brand.id, "batch": batch_name, "post_id": post.id,
            "identity": post.identity, "platform": post.platform, "url": url, "published_at": published_at,
            "when_local": shown, "when_from": how, "recorded_at": _z(now),
            "text": post.text or "", "text_sha256": SEND.text_sha(post.text),
            "text_start": " ".join((post.text or "").split())[:60]}
    lines = ["%s '%s' as put up by hand:" % ("Recorded" if confirm else "This would record", post.id),
             "  %s as '%s', %s" % (_network(post.platform), post.identity, WHEN_WORDS[how] % shown),
             "  link: %s" % url, "  \"%s\"" % line["text_start"]]
    if confirm:
        S.append_lines(log_path(brand), [line], lock_path=os.path.join(brand.state_dir, "hand-posted.lock"))
    else:
        lines.append("Nothing was saved. Run this again with --confirm to save it.")
    return {"mark": line, "saved": bool(confirm), "lines": lines}


def withdraw(brand, post_id, batch=None, confirm=False, now=None):
    """Take back a mark (the post was not put up after all, or the link was wrong). Nothing is
    deleted: a withdrawal line is added, and any numbers typed for it stop counting."""
    mark = _find_mark(brand, post_id, batch)
    line = {"action": "withdrawn", "brand": brand.id, "batch": mark["batch"], "post_id": mark["post_id"],
            "url": mark["url"], "recorded_at": _z(_utc_now(now))}
    lines = ["%s the record that '%s' was put up by hand at %s. Numbers typed in for it will stop counting."
             % ("Withdrew" if confirm else "This would withdraw", post_id, mark["url"])]
    if confirm:
        S.append_lines(log_path(brand), [line], lock_path=os.path.join(brand.state_dir, "hand-posted.lock"))
    else:
        lines.append("Nothing was saved. Run this again with --confirm to save it.")
    return {"saved": bool(confirm), "lines": lines}


# ----------------------------------------------------------------------------- saving numbers
def _typed_row(brand, mark, measures, now):
    return {"captured_at": _z(now), "capture_date": _z(now)[:10], "brand": brand.id, "identity": mark["identity"],
            "platform": mark["platform"], "provider_brand_id": None, "post_id": mark["url"],
            "provider_post_id": "", "factory_post_id": mark["post_id"], "linked_by": "",
            "published_at": mark["published_at"], "url": mark["url"], "text": mark.get("text") or "",
            "metrics": dict(measures), "source": "typed", "batch": mark["batch"]}


def _last_typed(brand, mark):
    R = _results()
    rows, _bad = R.load_archive(brand)
    mine = [r for r in rows if r.get("source") == "typed" and r.get("url") == mark["url"]
            and r.get("factory_post_id") == mark["post_id"] and r.get("batch") == mark["batch"]]
    return max(mine, key=lambda r: r.get("captured_at") or "") if mine else None


def _save_rows(brand, rows):
    R = _results()
    by_month = defaultdict(list)
    for r in rows:
        by_month[r["capture_date"][:7]].append(r)
    for month, group in by_month.items():
        S.append_lines(os.path.join(R.metrics_dir(brand), month + ".jsonl"), group,
                       lock_path=os.path.join(brand.state_dir, "metrics.lock"))


def _describe(mark, measures, before):
    out = ["  %s  %s  %s" % (mark["post_id"], _network(mark["platform"]),
                             ", ".join("%s %s" % (format(v, ","), k) for k, v in measures.items()))]
    dropped = sorted(set((before or {}).get("metrics") or {}) - set(measures))
    if dropped:
        out.append("    Given before but not now, so no longer counted: %s. Give them again to keep them."
                   % ", ".join("%s %s" % (k, format(before["metrics"][k], ",")) for k in dropped))
    return out


def save_numbers(brand, post_id, pairs, batch=None, confirm=False, now=None):
    """Save the numbers the person read off one post put up by hand. A preview unless confirm=True.
    A second save for the same post replaces the first in the summary; the first stays saved."""
    now = _utc_now(now)
    mark = _find_mark(brand, post_id, batch)
    measures = parse_measures(pairs)
    row = _typed_row(brand, mark, measures, now)
    lines = ["%s for a post put up by hand:" % ("Saved these numbers" if confirm else "This would save these numbers")]
    lines.extend(_describe(mark, measures, _last_typed(brand, mark)))
    if confirm:
        _save_rows(brand, [row])
    else:
        lines.append("Nothing was saved. Run this again with --confirm to save it.")
    return {"row": row, "saved": bool(confirm), "lines": lines}


# ----------------------------------------------------------------------------- the spreadsheet
def write_sheet(brand, now=None):
    """Write a spreadsheet with one line per post put up by hand, to fill in. Changes no record.
    Saved in the brand's Output folder, never beside the results archive."""
    active, _bad = read_marks(brand)
    if not active:
        raise HandPostedError("No post of %s is recorded as put up by hand yet, so there is nothing to fill in."
                              % brand.name)
    known = _results().NUMBERS
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(SHEET_FIRST + tuple(known))
    for m in sorted(active.values(), key=lambda m: m.get("published_at") or ""):
        w.writerow([m["batch"], m["post_id"], _network(m["platform"]), m["url"], m.get("when_local") or "",
                    m.get("text_start") or ""] + [""] * len(known))
    folder = brand.path(*SHEET_DIR)
    os.makedirs(folder, exist_ok=True)
    stem = "numbers-%s" % _utc_now(now).astimezone(ZoneInfo(brand.timezone)).strftime("%Y-%m-%d")
    n = 1
    while True:                       # never replace a sheet the person may already have filled in
        path = os.path.join(folder, "%s%s.csv" % (stem, "" if n == 1 else "-%d" % n))
        try:
            with open(path, "x", encoding="utf-8-sig", newline="") as f:  # the mark lets Excel read accents
                f.write(buf.getvalue())
            break
        except FileExistsError:
            n += 1
    return {"path": path, "posts": len(active),
            "lines": ["A sheet with %d post(s) to fill in is in the brand's Output folder, under results-to-fill, "
                      "named %s. Leave a box empty when the number is not known."
                      % (len(active), os.path.basename(path))]}


def read_sheet(brand, path, confirm=False, now=None):
    """Read a filled-in sheet. Every line is checked first; one problem anywhere and nothing is saved.
    Empty boxes are numbers nobody gave, and stay missing."""
    now = _utc_now(now)
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            table = list(csv.DictReader(f))
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        raise HandPostedError("That sheet could not be read (%s). Nothing was saved." % type(e).__name__)
    known = _results().NUMBERS
    active, _bad = read_marks(brand)
    rows, out, problems = [], [], []
    for n, line in enumerate(table, start=2):                      # line 1 is the headings
        line = {(k or "").strip(): (v or "").strip() for k, v in line.items() if k is not None}
        filled = {k: line[k] for k in known if line.get(k)}
        if not filled:
            continue
        mark = active.get((line.get("batch") or "", line.get("post_id") or ""))
        if mark is None:
            problems.append("Line %d (%s): not recorded as put up by hand." % (n, line.get("post_id") or "no post id"))
            continue
        if (line.get("url") or "") != mark["url"]:
            problems.append("Line %d (%s): its link was changed in the sheet. Change a link by withdrawing the post "
                            "and recording it again." % (n, mark["post_id"]))
            continue
        try:
            measures = parse_measures(filled)
        except HandPostedError as e:
            problems.append("Line %d (%s): %s" % (n, mark["post_id"], str(e).replace(" Nothing was saved.", "")))
            continue
        rows.append(_typed_row(brand, mark, measures, now))
        out.extend(_describe(mark, measures, _last_typed(brand, mark)))
    if problems:
        raise HandPostedError("The sheet has problems, so nothing was saved:\n  " + "\n  ".join(problems))
    if not rows:
        raise HandPostedError("No numbers were filled in, so there is nothing to save.")
    lines = ["%s for %d post(s) put up by hand:" % ("Saved numbers" if confirm else "This would save numbers",
                                                   len(rows))] + out
    if confirm:
        _save_rows(brand, rows)
    else:
        lines.append("Nothing was saved. Run this again with --confirm to save it.")
    return {"rows": rows, "saved": bool(confirm), "lines": lines}


# ----------------------------------------------------------------------------- what the summary counts
def for_summary(brand, rows, since):
    """(rows to count, notes). Typed rows count only while their mark stands and its link is the same.
    A post that also has fetched results is counted once, from the fetched numbers. `notes` has
    "hand_posted" (marks in the period), "waiting" (those of them with no numbers at all) and
    "unreadable" (lines of the record that could not be read)."""
    active, bad = read_marks(brand)
    fetched = [r for r in rows if r.get("source") != "typed"]
    fetched_links = {same_link(r.get("url")) for r in fetched if r.get("url")}
    by_words = defaultdict(set)
    for r in fetched:
        if (r.get("text") or "").strip():
            by_words[(r.get("platform"), SEND.text_sha(r.get("text")))].add(str(r.get("post_id")))
    marks_by_words = defaultdict(int)
    for m in active.values():
        marks_by_words[(m["platform"], m.get("text_sha256"))] += 1

    def joined(m):
        if same_link(m["url"]) in fetched_links:
            return True
        words = (m["platform"], m.get("text_sha256"))
        return len(by_words.get(words, ())) == 1 and marks_by_words[words] == 1

    standing = {(m["batch"], m["post_id"], m["url"]) for m in active.values() if not joined(m)}
    typed = [r for r in rows if r.get("source") == "typed"
             and (r.get("batch"), r.get("factory_post_id"), r.get("url")) in standing]
    have_numbers = {(r.get("batch"), r.get("factory_post_id")) for r in typed}
    in_period = [m for m in active.values() if (m.get("published_at") or "") >= since]
    waiting = [m for m in in_period if not joined(m) and (m["batch"], m["post_id"]) not in have_numbers]
    return fetched + typed, {"hand_posted": len(in_period), "waiting": len(waiting), "unreadable": bad}
