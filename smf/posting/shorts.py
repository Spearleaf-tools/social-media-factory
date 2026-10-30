"""shorts.py - one short a day, per account, from any folder of finished videos.

    found = discover(brand)                      # what is in the inbox, offline and free
    plan  = plan_shorts(brand)                   # a preview: nothing is written anywhere
    plan  = plan_shorts(brand, save=True)        # writes a batch for review and books the days
    ... a person approves the batch in the review page ...
    send.schedule_batch(brand, plan["batch"], provider, confirm=True)

Planning never sends anything. Sending a shorts batch is the same road as sending any batch:
the gates and the ledger in send.py.

THE INBOX IS JUST A FOLDER
`video.inbox_folder` in the brand's settings is relative to the brand folder, or a full path to
anywhere: a synced cloud-drive folder is simply a folder. There is no default location outside
the brand, and a folder that belongs to another brand is refused. A video that lives outside the
brand folder is COPIED in (to Inputs/Edited) when a plan is saved, because a post may only carry
files from inside its own brand's folder: that is what lets a person see it in the review page
and what the consent rule checks. The original is never moved, renamed or deleted.

HOW FILES BECOME CLIPS
    rye-loaf.mp4                         one clip
    rye-loaf__warm.mp4, rye-loaf__fast.mp4    ONE clip with two versions (two underscores)
The words for a video sit next to it: `rye-loaf.txt` or `.md`. A file named for one platform
(`rye-loaf.linkedin.txt`) is used for that platform only. Words written for one platform are
NEVER borrowed for another; a video with no words for a platform is listed as needing a
description and is left out, because a visible gap is better than the wrong words.
When a clip has several versions, each account gets a different one.

THE BOOKING RULES (checked against everything already booked, not just this run)
  * each account takes at most its daily number of shorts (1, or more where the brand says so)
  * a clip is never on two accounts on the same day
  * a clip goes to each account once
  * new bookings start after what is already booked: gaps left earlier are never back-filled
"Already booked" is read from three places: what this planner booked before, the posting
ledger, and (when a connection is given) the service's own calendar, where an entry counts only
if its words are EXACTLY a video's description on that same account.

THE ROUTING RULE (set September 2026; review it when platforms change their limits)
A video that is wider than it is tall AND longer than three minutes is long-form. It goes to
YouTube as a normal video and is never planned as a short. Everything else is a short. Size and
length are read from the file's own header with no extra program. A file that cannot be read
is listed for a person to look at; it is not guessed.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from smf import brands
from smf.posting import send as SEND
from smf.posting import state as S
from smf.posting.ledger import ACTIVE, Ledger
from smf.posting.provider import ProviderError
from smf.studio import posts as P
from smf.brands import replace_patiently

VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v")
DESCRIPTION_EXTENSIONS = (".txt", ".md")
SHORT_PLATFORMS = ("tiktok", "instagram", "facebook", "youtube", "linkedin")
LONG_PLATFORMS = ("youtube",)
LONG_FORM_MIN_SECONDS = 180
ROUTING_RULE_SET = "2026-09"
VERSION_MARK = "__"
MEDIA_TYPE = {"short": {"instagram": "reel", "facebook": "reel"}, "long": {"youtube": "video"}}
STATE_FILE = "shorts.json"
LANDING = ("Inputs", "Edited")
MAX_PER_DAY = 10
ACCOUNT_STAGGER_MIN = 4
CALENDAR_BACK_DAYS, CALENDAR_FORWARD_DAYS, CALENDAR_CHUNK_DAYS = 30, 150, 60
_MOOV_LIMIT = 64 * 1024 * 1024


class ShortsError(Exception):
    """Worded for the person."""


def state_file(brand):
    return S.StateFile(brand, STATE_FILE, "which shorts are booked on which days", fresh={"bookings": {}})


# ----------------------------------------------------------------------------- reading a video's header
def _boxes(data):
    pos, end = 0, len(data)
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, data[pos + header:pos + size]
        pos += size


def _seconds(mvhd):
    if not mvhd:
        return 0.0
    if mvhd[0] == 1 and len(mvhd) >= 32:
        scale, length = struct.unpack(">IQ", mvhd[20:32])
    elif len(mvhd) >= 20:
        scale, length = struct.unpack(">II", mvhd[12:20])
    else:
        return 0.0
    return float(length) / scale if scale else 0.0


def _picture_size(trak):
    tkhd, is_video = None, False
    for kind, body in _boxes(trak):
        if kind == b"tkhd":
            tkhd = body
        elif kind == b"mdia":
            for k2, b2 in _boxes(body):
                if k2 == b"hdlr" and len(b2) >= 12 and b2[8:12] == b"vide":
                    is_video = True
    if not (tkhd and is_video):
        return None
    at = 52 if tkhd[0] == 1 else 40                      # where the 3x3 display matrix starts
    if len(tkhd) < at + 44:
        return None
    a, b, _u, c, d = struct.unpack(">5i", tkhd[at:at + 20])
    width, height = (v >> 16 for v in struct.unpack(">II", tkhd[at + 36:at + 44]))
    if a == 0 and d == 0 and b != 0 and c != 0:          # filmed upright on a phone: stored sideways, shown turned
        width, height = height, width
    return (width, height) if width and height else None


def probe_video(path):
    """{"width", "height", "seconds"} from an MP4/MOV file's own header, or None when it cannot
    be read. Only the header is read, never the pictures, so a large or cloud-synced file is cheap."""
    try:
        with open(path, "rb") as f:
            total = os.fstat(f.fileno()).st_size
            pos = 0
            while pos + 8 <= total:
                f.seek(pos)
                head = f.read(8)
                if len(head) < 8:
                    return None
                size, kind = struct.unpack(">I4s", head)
                header = 8
                if size == 1:
                    size = struct.unpack(">Q", f.read(8))[0]
                    header = 16
                elif size == 0:
                    size = total - pos
                if size < header:
                    return None
                if kind == b"moov":
                    if size - header > _MOOV_LIMIT:
                        return None
                    seconds, picture = 0.0, None
                    for k, body in _boxes(f.read(size - header)):
                        if k == b"mvhd":
                            seconds = _seconds(body)
                        elif k == b"trak" and picture is None:
                            picture = _picture_size(body)
                    if not picture:
                        return None
                    return {"width": picture[0], "height": picture[1], "seconds": round(seconds, 2)}
                pos += size
    except (OSError, struct.error):
        return None
    return None


def classify(info):
    """'short', 'long' or 'unknown' (never a guess). See THE ROUTING RULE above."""
    if not info or not info.get("seconds") or not info.get("width") or not info.get("height"):
        return "unknown"
    if info["width"] > info["height"] and info["seconds"] > LONG_FORM_MIN_SECONDS:
        return "long"
    return "short"


# ----------------------------------------------------------------------------- the inbox
def _norm_case(path):
    return os.path.normcase(os.path.realpath(path))


def _is_inside(path, folder):
    path, folder = _norm_case(path), _norm_case(folder)
    return path == folder or path.startswith(folder + os.sep)


def inbox_folder(brand):
    """(folder, inside_brand). The folder THIS brand named for finished videos. Never a default
    outside the brand, never another brand's folder."""
    raw = ((brand.data.get("video") or {}).get("inbox_folder") or "").strip()
    if not raw:
        raise ShortsError("%s has not said where its finished videos arrive. Set the video inbox folder in the "
                          "brand's settings: a folder inside the brand, or the full path of any folder." % brand.name)
    expanded = os.path.expanduser(raw)
    absolute = os.path.isabs(expanded) or bool(re.match(r"^[A-Za-z]:[\\/]", expanded))
    if absolute:
        folder = expanded
    else:
        parts = [p for p in re.split(r"[\\/]+", raw) if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            raise ShortsError("The video inbox in %s's settings climbs out of the brand folder. Use a folder "
                              "inside the brand, or the full path of the folder you mean." % brand.name)
        folder = os.path.join(brand.home, *parts)
    inside = _is_inside(folder, brand.home)
    if not inside and _is_inside(folder, brands.CLIENT_DIR):
        raise ShortsError("That video inbox is inside another brand's folder. A brand only ever posts its own "
                          "videos. Nothing was read.")
    if not os.path.isdir(folder):
        raise ShortsError("The video inbox for %s could not be found. If it is on a cloud drive, make sure the "
                          "drive is running and the folder is available on this computer." % brand.name)
    return os.path.realpath(folder), inside


def _read_words(path):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read().replace("\r\n", "\n").replace("\r", "\n").strip()
    except OSError:
        return ""


def description_for(video_path, clip_stem, platform):
    """(words, file_name) for this video on this platform, or ("", "").
    Most specific first: the version's own file for the platform, the version's general file,
    then the clip's. A file written for ANOTHER platform is never used."""
    folder = os.path.dirname(video_path)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    names = [stem + "." + platform, stem]
    if clip_stem != stem:
        names += [clip_stem + "." + platform, clip_stem]
    for name in names:
        for ext in DESCRIPTION_EXTENSIONS:
            candidate = os.path.join(folder, name + ext)
            if os.path.isfile(candidate):
                words = _read_words(candidate)
                if words:
                    return words, os.path.basename(candidate)
    return "", ""


def clip_hash(clip_key):
    return hashlib.sha256(unicodedata.normalize("NFC", clip_key).encode("utf-8")).hexdigest()[:10]


def discover(brand, probe=True):
    """Every finished video in the brand's inbox, grouped into clips. Offline. Opens nothing but
    each file's header, and copies nothing.

    Returns {"inbox", "inside_brand", "clips": [...], "needs_a_look": [...]}. A clip is
    {"key", "title", "kind", "files": [{"rel", "path", "version", "width", "height", "seconds"}]}."""
    folder, inside = inbox_folder(brand)
    groups = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith(".") or os.path.splitext(name)[1].lower() not in VIDEO_EXTENSIONS:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            stem = os.path.splitext(name)[0]
            clip_stem, _mark, version = stem.partition(VERSION_MARK)
            if not clip_stem:
                clip_stem, version = stem, ""
            rel_dir = os.path.dirname(rel)
            key = unicodedata.normalize("NFC", (rel_dir + "/" if rel_dir else "") + clip_stem)
            groups[key].append({"rel": rel, "path": full, "version": version, "clip_stem": clip_stem})
    clips, needs_a_look = [], []
    for key in sorted(groups):
        files = sorted(groups[key], key=lambda f: f["rel"])
        kinds = set()
        for f in files:
            info = probe_video(f["path"]) if probe else None
            f.update(info or {"width": 0, "height": 0, "seconds": 0.0})
            f["kind"] = classify(info) if probe else "short"
            kinds.add(f["kind"])
        title = files[0]["clip_stem"]
        if "unknown" in kinds:
            needs_a_look.append({"clip": key, "why": "its size and length could not be read from the file, so the "
                                                     "Factory cannot tell whether it is a short or a long video"})
            continue
        if len(kinds) > 1:
            needs_a_look.append({"clip": key, "why": "its versions disagree: some are shorts and some are long videos"})
            continue
        clips.append({"key": key, "title": title, "kind": kinds.pop(), "files": files})
    return {"inbox": folder, "inside_brand": inside, "clips": clips, "needs_a_look": needs_a_look}


# ----------------------------------------------------------------------------- what is already booked
class Bookings(object):
    """Everything already booked for one brand, from every place that knows."""

    def __init__(self):
        self.count = defaultdict(int)           # (identity, platform, lane, day) -> posts
        self.clip_days = defaultdict(set)       # clip key or hash -> {day}
        self.done = set()                       # (clip hash, identity, platform)
        self.last_day = {}                      # (identity, platform, lane) -> latest booked day
        self.seen_posts = set()

    def add(self, clip_id, identity, platform, lane, day, occupies=True, post_id=None):
        if post_id is not None:
            if post_id in self.seen_posts:
                return
            self.seen_posts.add(post_id)
        self.done.add((clip_id, identity, platform))
        if not occupies or not day:
            return
        self.count[(identity, platform, lane, day)] += 1
        self.clip_days[clip_id].add(day)
        stream = (identity, platform, lane)
        if day > self.last_day.get(stream, ""):
            self.last_day[stream] = day

    def first_free(self, clip_id, identity, platform, lane, cap, not_before, not_after):
        day = datetime.strptime(not_before, "%Y-%m-%d").date()
        end = datetime.strptime(not_after, "%Y-%m-%d").date()
        while day <= end:
            d = day.strftime("%Y-%m-%d")
            if self.count[(identity, platform, lane, d)] < cap and d not in self.clip_days[clip_id]:
                return d
            day += timedelta(days=1)
        return None


def _local_day(iso, tz):
    try:
        when = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is None:
        return when.strftime("%Y-%m-%d")
    return when.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


def _lane_of(post_id):
    head = (post_id or "").split("-", 1)[0]
    return {"short": "short", "promo": "short", "long": "long"}.get(head)


def _hash_of(post_id):
    parts = (post_id or "").split("-")
    return parts[1] if len(parts) > 2 else ""


def existing_bookings(brand, data, provider=None, words_index=None, today=None):
    """(Bookings, dropped_post_ids, notes). `data` is the planner's own state, already read.
    `words_index` maps (platform, fingerprint of a description) -> clip hash, for reading the
    service's calendar."""
    book, dropped, notes = Bookings(), [], []
    batches = {}

    def post_status(batch_name, post_id):
        if batch_name not in batches:
            path = brand.path("Output", "batches", batch_name)
            try:
                batches[batch_name] = {p.id: p.status for p in P.load_batch(path, brand.id)[0]}
            except (OSError, ValueError):
                batches[batch_name] = None
        found = batches[batch_name]
        return None if found is None else found.get(post_id)

    operations = Ledger(brand).all()
    for op in operations.values():
        lane = _lane_of(op.get("post_id"))
        if lane and op.get("state") in ACTIVE:
            book.add(_hash_of(op["post_id"]), op["identity"], op["platform"], lane,
                     _local_day(op.get("scheduled_time_iso"), brand.timezone), post_id=op["post_id"])
    for post_id, b in sorted((data.get("bookings") or {}).items()):
        if not isinstance(b, dict) or not all(b.get(k) for k in ("clip", "identity", "platform", "lane", "day")):
            raise S.StateError("The record of which shorts are booked has an entry that cannot be understood "
                               "(%s). Nothing was planned, so nothing gets booked twice. Ask Claude to repair it."
                               % post_id)
        status = post_status(b.get("batch") or "", post_id)
        if status is None:
            if post_id not in book.seen_posts:
                dropped.append(post_id)                  # its batch is gone and it was never sent: free the day
            continue
        book.add(b["clip"], b["identity"], b["platform"], b["lane"], b["day"],
                 occupies=(status != "rejected"), post_id=post_id)

    if provider is not None and words_index:
        ours = {str(op.get("provider_post_id")) for op in operations.values() if op.get("provider_post_id")}
        today = today or datetime.now(ZoneInfo(brand.timezone)).date()
        start = datetime.combine(today - timedelta(days=CALENDAR_BACK_DAYS), datetime.min.time())
        end = datetime.combine(today + timedelta(days=CALENDAR_FORWARD_DAYS), datetime.min.time())
        by_account = defaultdict(dict)
        for t in brand.targets(connected_only=True):
            if isinstance(t.get("provider_brand_id"), int) and not isinstance(t.get("provider_brand_id"), bool):
                by_account[t["provider_brand_id"]][t["platform"]] = t["identity"]
        for pbid, platforms in sorted(by_account.items()):
            try:
                cursor = start
                while cursor < end:
                    nxt = min(cursor + timedelta(days=CALENDAR_CHUNK_DAYS), end)
                    for e in provider.calendar(pbid, cursor.strftime("%Y-%m-%dT%H:%M:%S"),
                                               nxt.strftime("%Y-%m-%dT%H:%M:%S"), brand.timezone):
                        if e.get("draft") or str(e.get("id")) in ours:
                            continue
                        for platform in [n for n in (e.get("network") or "").split(",") if n in platforms]:
                            found = words_index.get((platform, SEND.text_sha(e.get("text"))))
                            if found:
                                lane, clip_id = found
                                book.add(clip_id, platforms[platform], platform, lane,
                                         (e.get("when") or "")[:10], post_id="calendar:%s:%s" % (pbid, e.get("id")))
                    cursor = nxt
            except ProviderError as e:
                notes.append("The scheduling service's calendar could not be read, so this plan only knows what "
                             "this computer has booked. %s" % e)
                break
    return book, dropped, notes


# ----------------------------------------------------------------------------- planning
def per_day_counts(brand, override=None):
    counts = {p: 1 for p in SHORT_PLATFORMS}
    for source in ((brand.data.get("video") or {}).get("shorts_per_day") or {}, override or {}):
        if not isinstance(source, dict):
            raise ShortsError("The shorts-per-day setting should list platforms and whole numbers, "
                              "for example tiktok: 3.")
        for platform, n in source.items():
            if platform not in SHORT_PLATFORMS:
                raise ShortsError("Shorts go to %s. '%s' is not one of them." % (", ".join(SHORT_PLATFORMS), platform))
            if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_PER_DAY:
                raise ShortsError("Shorts per day on %s must be a whole number from 1 to %d." % (platform, MAX_PER_DAY))
            counts[platform] = n
    return counts


def video_accounts(brand):
    """(accounts, left_out). Accounts are THIS brand's connected, linked targets on platforms that
    take shorts, in the order the brand's settings list them."""
    accounts, left_out = [], []
    for t in brand.targets():
        if t["platform"] not in SHORT_PLATFORMS:
            continue
        linked = isinstance(t.get("provider_brand_id"), int) and not isinstance(t.get("provider_brand_id"), bool)
        if t.get("connected") is True and linked:
            accounts.append((t["identity"], t["platform"]))
        else:
            left_out.append("%s as '%s' is not connected yet, so nothing was planned for it." % (t["platform"], t["identity"]))
    return accounts, left_out


def _slot(brand, day, account_index, nth_that_day):
    windows = sorted(int(w[:2]) * 60 + int(w[3:]) for w in brand.posting_windows)
    minute = windows[(account_index + nth_that_day) % len(windows)] + (account_index % 12) * ACCOUNT_STAGGER_MIN
    minute = min(minute, 23 * 60 + 59)
    local = datetime.strptime(day, "%Y-%m-%d").replace(hour=minute // 60, minute=minute % 60,
                                                       tzinfo=ZoneInfo(brand.timezone))
    return (local.strftime("%Y-%m-%d %H:%M"), local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def bring_in(brand, source, rel):
    """Copy one outside video into the brand's folder and return its path relative to the brand.
    The copy is written beside its final name and swapped in, so a half-copied video can never
    be posted. An existing copy of the same size is reused; a different one is never overwritten."""
    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
    dest = brand.path(*(LANDING + tuple(parts)))
    if os.path.isfile(dest):
        if os.path.getsize(dest) == os.path.getsize(source):
            return "/".join(LANDING + tuple(parts))
        raise ShortsError("a different video with the same name was brought in earlier. Rename the new one.")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(dest))
    os.close(fd)
    try:
        shutil.copyfile(source, tmp)
        replace_patiently(tmp, dest)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise ShortsError("it could not be copied into the brand's folder (is the drive running, and is there "
                          "room on this computer?)")
    return "/".join(LANDING + tuple(parts))


def media_path_for(brand, found, file_entry, copy):
    if found["inside_brand"]:
        full = os.path.join(found["inbox"], *file_entry["rel"].split("/"))
        return os.path.relpath(full, os.path.realpath(brand.home)).replace(os.sep, "/")
    if copy:
        return bring_in(brand, file_entry["path"], file_entry["rel"])
    return "/".join(LANDING + tuple(p for p in file_entry["rel"].split("/") if p not in ("", ".", "..")))


def loop_is_on(brand):
    return (brand.data.get("video") or {}).get("test_and_promote") is True


def plan_shorts(brand, provider=None, days=14, start=None, per_day=None, save=False, today=None):
    """Plan the next `days` days of shorts for every connected account of THIS brand.

    Without `save` this is a preview: no file is written and nothing is copied. With `save`, the
    posts are written as a batch for review and the days are booked. Nothing is ever sent from
    here. `provider` is optional and only read: with it, the service's calendar is also checked
    for shorts booked from somewhere else."""
    if not isinstance(brand, brands.Brand):
        raise brands.BrandError("no brand was named. Say which brand this is for. Brands here: %s"
                                % (", ".join(brands.list_brands()) or "none yet"))
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 366:
        raise ShortsError("Plan between 1 and 366 days at a time.")
    today = today or datetime.now(ZoneInfo(brand.timezone)).date()
    first_day = today + timedelta(days=1)
    if start:
        try:
            first_day = max(first_day, datetime.strptime(start, "%Y-%m-%d").date())
        except ValueError:
            raise ShortsError("The start date should look like 2030-01-31.")
    caps = per_day_counts(brand, per_day)
    accounts, left_out = video_accounts(brand)
    found = discover(brand)
    result = {"brand": brand.id, "saved": False, "batch": None, "posts": [], "calendar": {},
              "needs_description": [], "needs_a_look": list(found["needs_a_look"]), "held_for_later": 0,
              "left_to_the_loop": [], "notes": list(left_out), "dropped": []}
    if not accounts:
        result["notes"].append("%s has no connected video account yet. Link one in onboarding, then plan again."
                               % brand.name)
        return result

    clips = []
    has_long_home = any(platform in LONG_PLATFORMS for _identity, platform in accounts)
    for clip in found["clips"]:
        if loop_is_on(brand) and clip["kind"] == "short" and len(clip["files"]) > 1:
            result["left_to_the_loop"].append(clip["key"])
            continue
        if clip["kind"] == "long" and not has_long_home:
            result["needs_a_look"].append({"clip": clip["key"], "why": "it is a long video, which only goes to "
                                           "YouTube, and this brand has no connected YouTube account"})
            continue
        clips.append(clip)

    # Which words belong to which clip on which platform (also what the calendar is matched on).
    words, words_index = {}, {}
    for clip in clips:
        lane = clip["kind"]
        platforms = LONG_PLATFORMS if lane == "long" else SHORT_PLATFORMS
        for ai, (identity, platform) in enumerate(accounts):
            if platform not in platforms:
                continue
            f = clip["files"][ai % len(clip["files"])]
            text, _name = description_for(f["path"], f["clip_stem"], platform)
            words[(clip["key"], identity, platform)] = (f, text)
            if text:
                words_index.setdefault((platform, SEND.text_sha(text)), (lane, clip_hash(clip["key"])))

    store = state_file(brand)

    def work(data):
        book, dropped, notes = existing_bookings(brand, data, provider, words_index, today)
        result["notes"].extend(notes)
        result["dropped"] = dropped
        resume = {}
        for identity, platform in accounts:
            for lane in ("short", "long"):
                last = book.last_day.get((identity, platform, lane))
                begin = first_day.strftime("%Y-%m-%d")
                resume[(identity, platform, lane)] = max(begin, last) if last else begin
        posts, new_bookings, missing = [], {}, defaultdict(list)
        for ci, clip in enumerate(clips):
            lane, cid = clip["kind"], clip_hash(clip["key"])
            order = accounts[ci % len(accounts):] + accounts[:ci % len(accounts)]
            for identity, platform in order:
                if (clip["key"], identity, platform) not in words:
                    continue
                if (cid, identity, platform) in book.done:
                    continue
                f, text = words[(clip["key"], identity, platform)]
                if not text:
                    missing[clip["key"]].append(platform)
                    continue
                begin = resume[(identity, platform, lane)]
                until = (datetime.strptime(begin, "%Y-%m-%d").date() + timedelta(days=days - 1)).strftime("%Y-%m-%d")
                cap = caps[platform] if lane == "short" else 1
                day = book.first_free(cid, identity, platform, lane, cap, begin, until)
                if day is None:
                    result["held_for_later"] += 1
                    continue
                try:
                    media = media_path_for(brand, found, f, copy=save)
                except ShortsError as e:
                    result["needs_a_look"].append({"clip": clip["key"], "why": str(e)})
                    continue
                nth = book.count[(identity, platform, lane, day)]
                local, iso = _slot(brand, day, accounts.index((identity, platform)), nth)
                post_id = "%s-%s-%s-%s" % (lane, cid, identity, platform)
                book.add(cid, identity, platform, lane, day, post_id=post_id)
                posts.append(P.Post(id=post_id, brand=brand.id, identity=identity, platform=platform, text=text,
                                    media_paths=[media], topic_id=clip["key"],
                                    shape="long-video" if lane == "long" else "short-video",
                                    media_type=MEDIA_TYPE[lane].get(platform, ""),
                                    scheduled_time_local=local, scheduled_time_iso=iso))
                new_bookings[post_id] = {"clip": cid, "clip_key": clip["key"], "identity": identity,
                                         "platform": platform, "lane": lane, "day": day, "file": f["rel"]}
        for key, platforms in sorted(missing.items()):
            result["needs_description"].append({"clip": key, "platforms": sorted(set(platforms))})
        posts.sort(key=lambda p: (p.scheduled_time_iso, p.identity, p.platform))
        if posts:
            P.check_batch(posts, brand)
            P.assert_drip(posts)                         # the hard guard: a clip on two accounts in one day stops here
        result["posts"] = posts
        for p in posts:
            result["calendar"].setdefault(p.scheduled_time_local[:10], []).append(
                {"id": p.id, "time": p.scheduled_time_local[-5:], "identity": p.identity, "platform": p.platform,
                 "clip": p.topic_id, "video": os.path.basename(p.media_paths[0]), "status": p.status})
        if save and posts:
            name = "shorts-%s.json" % datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            path = brand.path("Output", "batches", name)
            n = 1
            while os.path.exists(path):
                n += 1
                path = brand.path("Output", "batches", name[:-5] + "-%d.json" % n)
            P.save_batch(posts, path, {"kind": "shorts", "made_by": "shorts planner",
                                       "routing_rule_set": ROUTING_RULE_SET})
            for post_id, b in new_bookings.items():
                data["bookings"][post_id] = dict(b, batch=os.path.basename(path))
            result["saved"], result["batch"] = True, path
        if save:
            for post_id in dropped:
                data["bookings"].pop(post_id, None)

    if save:
        with store.edit() as data:
            work(data)
    else:
        work(store.read())
    return result


def describe(plan):
    lines = []
    n = len(plan["posts"])
    if plan["saved"]:
        lines.append("%d short(s) planned and saved for review. Nothing has been sent." % n)
    elif n:
        lines.append("PREVIEW: %d short(s) could be planned. Nothing was saved or sent." % n)
    else:
        lines.append("Nothing new to plan.")
    for day in sorted(plan["calendar"]):
        for row in plan["calendar"][day]:
            lines.append("  %s %s  %s as '%s'  %s%s" % (day, row["time"], row["platform"], row["identity"], row["video"],
                                                       "" if row["status"] == "lint_pass" else "  (the copy check found a problem)"))
    for item in plan["needs_description"]:
        lines.append("  '%s' needs a description for %s: put a text file with the same name next to the video."
                     % (item["clip"], ", ".join(item["platforms"])))
    for item in plan["needs_a_look"]:
        lines.append("  '%s' was left out: %s." % (item["clip"], item["why"]))
    if plan["left_to_the_loop"]:
        lines.append("  %d clip(s) with several versions are left to the test-and-promote loop." % len(plan["left_to_the_loop"]))
    if plan["held_for_later"]:
        lines.append("  %d more booking(s) did not fit in this many days and will be planned next time." % plan["held_for_later"])
    lines.extend("  " + note for note in plan["notes"])
    if plan["saved"]:
        lines.append("Next: approve them in the review page, then schedule the batch.")
    return "\n".join(lines)


__all__ = ["ShortsError", "discover", "plan_shorts", "describe", "probe_video", "classify", "inbox_folder",
           "description_for", "per_day_counts", "video_accounts", "existing_bookings", "Bookings", "bring_in",
           "clip_hash", "state_file", "loop_is_on", "SHORT_PLATFORMS", "LONG_PLATFORMS", "LONG_FORM_MIN_SECONDS",
           "VERSION_MARK"]
