"""posts.py - the Post, the batch file, the drip schedule, and the checks before review.

A batch is one reviewable JSON file under the brand's Output/batches/. Nothing here talks to a
network. Writing the copy is a separate creative step; this module validates, schedules and saves.

    draft -> lint_pass -> approved -> scheduled | posted | exported
                       \\-> rejected | regen_queued | blocked

Rules of the state machine:
  * lint() never changes a status. It only fills lint_errors / lint_warnings.
  * check_batch() sets draft (has errors) or lint_pass (clean), and leaves decided posts alone.
  * approval happens in the review page; sending happens in posting/, never here.

THE DRIP (why the schedule looks the way it does)
A topic gets a different post per platform. Those posts must NOT all go out the same day: each
topic occupies ONE platform per day and rotates, so a brand's feeds read as a series rather than
the same thing shouted everywhere at once. `assign_drip_slots` builds that rotation as a Latin
square per identity, and `assert_drip` is the hard guard that refuses a batch that breaks it.
"""
from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date as _date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from smf.studio.lint import Finding, Rules, lint_caption
from smf.brands import replace_patiently

ALLOWED_STATUSES = frozenset({"draft", "lint_pass", "approved", "rejected", "regen_queued", "blocked",
                              "scheduled", "posted", "exported"})
DECIDED = frozenset({"approved", "rejected", "regen_queued", "blocked", "scheduled", "posted", "exported"})
MEDIA_REQUIRED = frozenset({"instagram", "tiktok", "youtube", "pinterest"})
SLOT_STAGGER_MIN = 4
SLOT_MAX_SPAN_MIN = 49
FUTURE_SLOT_BUFFER_MIN = 30


class DripError(Exception):
    """The schedule repeats a subject in a way the brand's audience would notice."""


@dataclass
class Post:
    id: str
    brand: str                  # brand id. Required. A post without a brand cannot exist.
    identity: str               # one of THAT brand's identities
    platform: str
    text: str
    media_paths: list = field(default_factory=list)      # files relative to the brand folder, or absolute
    proof_ids: list = field(default_factory=list)
    pillar: str = ""
    topic_id: str = ""
    shape: str = ""
    lane: str = "evergreen"     # evergreen (dripped) | news (same or next day) | opinion
    drip_day: int = -1
    scheduled_time_local: str = ""      # "YYYY-MM-DD HH:MM" in the brand's timezone
    scheduled_time_iso: str = ""        # UTC ISO8601
    status: str = "draft"
    lint_errors: list = field(default_factory=list)
    lint_warnings: list = field(default_factory=list)
    sourcing: str = "unverified"        # passed | unverified | blocked  (never "passed" by default)
    feedback: str = ""
    approved_at: str = ""
    approved_text_sha: str = ""         # what exactly was approved; an edit after approval voids it
    rev: int = 0
    # per-network extras
    thread: list = field(default_factory=list)   # X: the tweets after `text`
    alt_text: str = ""
    media_type: str = ""        # "reel" | "story" for Instagram/Facebook video
    link: str = ""
    first_comment: str = ""
    # what the fact check found, and what it looked at (see settle_sourcing)
    facts_check: dict = field(default_factory=dict)
    # filled by posting/
    provider_post_id: str = ""

    def lint(self, rules):
        findings = lint_caption(self.text, self.platform, rules)
        if self.thread:
            if self.platform != "twitter":
                findings.append(Finding("ERROR", "thread-platform", "A thread only works on X, not %s." % self.platform,
                                        self.thread[0][:60]))
            for i, seg in enumerate(self.thread, start=2):
                for f in lint_caption(seg, self.platform, rules):
                    findings.append(Finding(f.severity, f.rule, "[tweet %d] %s" % (i, f.detail), f.excerpt))
        # The first comment and the alt text publish with the post, so the brand's rules apply to
        # them too. Their own length limits are set per network and are not the caption's, so the
        # character count is the one check that is not carried across.
        for label, words in (("first comment", self.first_comment), ("alt text", self.alt_text)):
            for f in lint_caption(words or "", self.platform, rules):
                if f.rule != "char-limit":
                    findings.append(Finding(f.severity, f.rule, "[%s] %s" % (label, f.detail), f.excerpt))
        self.lint_errors = [str(f) for f in findings if f.severity == "ERROR"]
        self.lint_warnings = [str(f) for f in findings if f.severity == "WARN"]
        return findings


_POST_FIELDS = frozenset(f.name for f in dataclasses.fields(Post))


# ----------------------------------------------------------------------------- batch files
def save_batch(posts, path, meta=None):
    """Atomic write. Every post must belong to the same brand as the batch."""
    brands_in = {p.brand for p in posts}
    if len(brands_in) > 1:
        raise ValueError("a batch holds one brand's posts; this one mixes: %s" % ", ".join(sorted(brands_in)))
    for p in posts:
        if p.status not in ALLOWED_STATUSES:
            raise ValueError("post %s has an unknown status '%s'" % (p.id, p.status))
    payload = {"meta": dict(meta or {}), "posts": [asdict(p) for p in posts]}
    if brands_in:
        payload["meta"]["brand"] = next(iter(brands_in))
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    replace_patiently(tmp, path)
    return path


def load_batch(path, brand_id):
    """Load a batch for ONE named brand. A batch that belongs to another brand is refused."""
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    meta = data.get("meta", {})
    posts = []
    for raw in data.get("posts", []):
        known = {k: v for k, v in raw.items() if k in _POST_FIELDS}     # tolerate older/newer files
        posts.append(Post(**known))
    owners = {p.brand for p in posts} | ({meta["brand"]} if meta.get("brand") else set())
    if owners - {brand_id}:
        raise ValueError("this batch belongs to %s, not to %s. Nothing was loaded."
                         % (", ".join(sorted(owners - {brand_id})), brand_id))
    return posts, meta


# ----------------------------------------------------------------------------- checks before review
def media_findings(post):
    if post.media_paths:
        return []
    if post.platform in MEDIA_REQUIRED:
        return ["[ERROR] media-required: %s needs an image or a video; text alone is not a valid post there."
                % post.platform]
    if post.platform == "twitter":
        return [] if post.thread else ["[WARN] media-recommended: a single post on X does better with a visual. "
                                       "Only a thread should be text alone."]
    return ["[WARN] media-recommended: no image or video attached. A carousel usually beats a single image."]


# ----------------------------------------------------------------------------- what was checked
SOURCING_RANK = {"passed": 0, "unverified": 1, "blocked": 2}
WORDS_CHANGED_NOTE = ("[WARN] facts-stale: the words changed after the facts were checked, so this post is "
                      "unverified again. Check the new words before it goes out.")
PICTURES_CHANGED_NOTE = ("[WARN] facts-stale: the pictures changed after the words on them were checked, so this "
                         "post is unverified again. Attach them again to check them.")


def publishable_parts(post):
    """(what it is, the words) for every part of a post that publishes, in posting order. The
    labels are what a person calls these things, so a check can say where it found something."""
    parts = [("the caption", post.text or "")]
    parts += [("tweet %d" % i, seg) for i, seg in enumerate(post.thread or [], start=2)]
    parts += [("the first comment", post.first_comment or ""), ("the alt text", post.alt_text or "")]
    return [(label, text) for label, text in parts if str(text).strip()]


def publishable_text(post):
    """Every word this post would publish, in posting order: the caption, each tweet of a thread,
    the first comment and the alt text. One check reads them together, so a claim cannot hide in
    a field nobody thought to check."""
    return "\n\n".join(text for _label, text in publishable_parts(post))


def publishable_sha(post):
    """A fingerprint of exactly the words a fact check would read, so a later edit is noticed."""
    import hashlib
    return hashlib.sha256(publishable_text(post).encode("utf-8")).hexdigest()


def link_words(post):
    """The readable words in a post's link. A link here has no separate label: what a reader sees
    is the address, so its words are read for claims written in words ("/best-bakery-in-town").
    Its digits are left alone, because a date or an id in an address is not a claim."""
    import re
    return re.sub(r"[^A-Za-z]+", " ", re.sub(r"^[A-Za-z]+://", "", post.link or "")).strip()


def settle_sourcing(post):
    """Set `sourcing` from everything that has been checked, and return the notes worth showing.

    Two things carry claims: the words, and the words drawn inside the pictures. Each is checked
    by the step that produces it and the answer is kept in `facts_check`; this puts them together.
    The strictest answer wins, because a post is only as checked as its least checked part, and a
    change to either since it was checked takes the post back to unverified."""
    check = dict(post.facts_check or {})
    notes = []
    words = check.get("words") or post.sourcing or "unverified"
    if check.get("words_sha") and check["words_sha"] != publishable_sha(post):
        notes.append(WORDS_CHANGED_NOTE)
        words = "blocked" if words == "blocked" else "unverified"
    pictures = check.get("pictures") or "passed"
    if check.get("media") is not None and list(check["media"]) != list(post.media_paths):
        notes.append(PICTURES_CHANGED_NOTE)
        pictures = "unverified"
    notes.extend("[WARN] picture-facts: " + n for n in check.get("picture_notes") or [])
    post.sourcing = max((words, pictures), key=lambda s: SOURCING_RANK.get(s, 1))
    return notes


def check_batch(posts, brand):
    """Lint every undecided post against THIS brand's rules and set draft / lint_pass."""
    rules = Rules.for_brand(brand)
    clean = dirty = 0
    for p in posts:
        if p.brand != brand.id:
            raise ValueError("post %s belongs to %s, not %s" % (p.id, p.brand, brand.id))
        brand.identity(p.identity)                       # unknown identity = error, never a guess
        if p.status in DECIDED:
            continue
        p.lint(rules)
        for finding in list(media_findings(p)) + settle_sourcing(p):
            (p.lint_errors if finding.startswith("[ERROR]") else p.lint_warnings).append(finding)
        p.status = "draft" if p.lint_errors else "lint_pass"
        dirty += 1 if p.lint_errors else 0
        clean += 0 if p.lint_errors else 1
    return {"total": len(posts), "clean": clean, "blocked": dirty}


def future_time_problem(post, buffer_minutes=FUTURE_SLOT_BUFFER_MIN, now=None):
    if not post.scheduled_time_iso:
        return "it has no scheduled time"
    try:
        when = datetime.fromisoformat(post.scheduled_time_iso.replace("Z", "+00:00"))
    except ValueError:
        return "its scheduled time is not a valid date"
    now = now or datetime.now(tz=timezone.utc)
    if when <= now:
        return "its scheduled time is in the past"
    if when <= now + timedelta(minutes=buffer_minutes):
        return "its scheduled time is less than %d minutes away" % buffer_minutes
    return None


# ----------------------------------------------------------------------------- time of day
def _local_to_utc_iso(date_str, hhmm, tz):
    dt = datetime.strptime("%s %s" % (date_str, hhmm), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assign_one_day(posts, date_str, windows, tz):
    """Spread one day's posts over the brand's posting windows. One account never lands twice in
    the same window while windows are free, each account's first post starts in a different
    window so the whole day is used, and posts sharing a window are staggered by a few minutes."""
    mins = sorted(int(w[:2]) * 60 + int(w[3:]) for w in windows)
    if not mins or not posts:
        return
    groups = defaultdict(list)
    for p in posts:
        groups[(p.platform, p.identity)].append(p)
    buckets = defaultdict(list)
    for g, key in enumerate(sorted(groups)):
        for i, p in enumerate(groups[key]):
            buckets[(g + i) % len(mins)].append(p)
    for wi, bucket in buckets.items():
        step = SLOT_STAGGER_MIN
        if len(bucket) > 1 and (len(bucket) - 1) * step > SLOT_MAX_SPAN_MIN:
            step = max(1, SLOT_MAX_SPAN_MIN // (len(bucket) - 1))
        for j, p in enumerate(bucket):
            m = mins[wi] + j * step
            hhmm = "%02d:%02d" % (m // 60, m % 60)
            p.scheduled_time_local = "%s %s" % (date_str, hhmm)
            p.scheduled_time_iso = _local_to_utc_iso(date_str, hhmm, tz)


# ----------------------------------------------------------------------------- the drip
def assign_drip_slots(posts, brand, start_date=None, days=None, topic_order=None):
    """Give every post a day and a time. Mutates posts. Deterministic.

    For a topic at offset o (its position among that identity's topics) on platform j of that
    identity's rotation, the ideal day is (j - o) mod n: a Latin square, so two topics never
    share a (platform, day) and a topic never appears on two platforms the same day.
    A collision (more topics than platforms, or a partial platform set) moves to the next free day.
    lane="news" skips the drip and goes out on day 0. start_date defaults to TOMORROW.
    """
    if not posts:
        return {"calendar": {}, "span_days": 0, "overflow": []}
    if start_date is None:
        start_date = (_date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    start = datetime.strptime(start_date, "%Y-%m-%d")

    for p in posts:
        if p.brand != brand.id:
            raise ValueError("post %s belongs to %s, not %s" % (p.id, p.brand, brand.id))
        if (p.lane or "evergreen") == "news":
            p.drip_day = 0

    by_identity = defaultdict(list)
    for p in posts:
        if (p.lane or "evergreen") != "news":
            by_identity[p.identity].append(p)

    taken_topic_day = set()              # one topic, one ACCOUNT per day, across all of the brand's identities
    for identity, iposts in sorted(by_identity.items()):
        rotation = brand.platforms_for(identity)
        for p in iposts:
            if p.platform not in rotation:
                raise ValueError("%s does not post on %s as '%s' (it has: %s). Link the account or drop the post."
                                 % (brand.name, p.platform, identity, ", ".join(rotation)))
        n = len(rotation)
        seen = []
        for p in iposts:
            if p.topic_id not in seen:
                seen.append(p.topic_id)
        order = [t for t in (topic_order or seen) if t in seen] + [t for t in seen if t not in (topic_order or seen)]
        taken_platform_day = set()       # one account, one evergreen post per day
        for offset, tid in enumerate(order):
            tposts = sorted((p for p in iposts if p.topic_id == tid), key=lambda p: rotation.index(p.platform))
            for p in tposts:
                day = (rotation.index(p.platform) - offset) % n
                while (p.platform, day) in taken_platform_day or (tid, day) in taken_topic_day:
                    day += 1
                taken_platform_day.add((p.platform, day))
                taken_topic_day.add((tid, day))
                p.drip_day = day

    # The rotation can leave day 0 empty (every topic's first platform may sit later in its
    # identity's rotation). Shifting every dripped post by the same amount keeps every rule and
    # means the first post goes out on the start date, not a day or two after it.
    dripped = [p for p in posts if (p.lane or "evergreen") != "news" and p.drip_day >= 0]
    if dripped:
        shift = min(p.drip_day for p in dripped)
        for p in dripped:
            p.drip_day -= shift

    by_day = defaultdict(list)
    for p in posts:
        by_day[max(0, p.drip_day)].append(p)
    calendar, overflow = {}, []
    for d, dposts in sorted(by_day.items()):
        date_str = (start + timedelta(days=d)).strftime("%Y-%m-%d")
        _assign_one_day(dposts, date_str, brand.posting_windows, brand.timezone)
        calendar[date_str] = [{"id": p.id, "identity": p.identity, "platform": p.platform,
                               "topic_id": p.topic_id, "lane": p.lane, "time": p.scheduled_time_local[-5:]}
                              for p in sorted(dposts, key=lambda p: p.scheduled_time_local)]
        if days is not None and d >= days:
            overflow.extend(p.id for p in dposts)
    return {"calendar": calendar, "span_days": (max(by_day) + 1) if by_day else 0, "overflow": overflow}


def assert_drip(posts):
    """The hard guard. Raises DripError when, within one brand, the same topic is scheduled on two
    accounts on the same day, or on the same account two days running. News is exempt."""
    by_topic_day = defaultdict(list)
    by_account_topic = defaultdict(list)
    for p in posts:
        if (p.lane or "evergreen") == "news" or not p.topic_id or not p.scheduled_time_local:
            continue
        day = p.scheduled_time_local[:10]
        by_topic_day[(p.brand, p.topic_id, day)].append(p)
        by_account_topic[(p.brand, p.identity, p.platform, p.topic_id)].append(day)
    problems = []
    for (_b, topic, day), group in by_topic_day.items():
        if len(group) > 1:
            where = ", ".join("%s/%s" % (p.identity, p.platform) for p in group)
            problems.append("'%s' is scheduled on %s all on %s" % (topic, where, day))
    for (_b, identity, platform, topic), days_list in by_account_topic.items():
        ds = sorted(datetime.strptime(d, "%Y-%m-%d") for d in set(days_list))
        for a, b in zip(ds, ds[1:]):
            if (b - a).days == 1:
                problems.append("'%s' runs on %s/%s two days in a row (%s, %s)"
                                % (topic, identity, platform, a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")))
    if problems:
        raise DripError("The schedule repeats itself:\n  - " + "\n  - ".join(problems))
    return True


# ----------------------------------------------------------------------------- approval
HASH_CHUNK_BYTES = 1024 * 1024
SETTLED_SECONDS = 3                     # a file changed more recently than this is read again every time
UNREADABLE = "unreadable"               # stands in for a file that is missing, outside the brand, or not media
_DIGESTS = {}                           # (real path, size, time last changed) -> sha256, for files that have settled

# Why an approval stopped counting, as the end of a sentence that starts "This post ..." or "it ...".
APPROVAL_VOID_WORDS = {
    "changed": "was changed after it was approved, so that approval no longer counts. Approve the new version",
    "media-changed": "has a picture or video that changed after you approved it, so that approval no longer "
                     "counts. Look at it on the review page and approve it again",
    "media-unchecked": "was approved before the Factory started checking what is inside a picture or video and "
                       "not just its name. Nothing is wrong with it: look at it on the review page and approve "
                       "it once more",
}


def file_sha256(path):
    """The sha256 of a file's bytes, read a piece at a time so a large video never has to fit in
    memory. A file that has not changed for a few seconds is remembered by its size and the time
    it was last changed, so a page full of videos is not read again for every click. A file that
    only just changed is never remembered: on some disks two saves in the same moment carry the
    same time, and the second one must not be mistaken for the first."""
    import hashlib
    import time
    before = os.stat(path)
    key = (path, before.st_size, before.st_mtime_ns)
    if key in _DIGESTS:
        return _DIGESTS[key]
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(HASH_CHUNK_BYTES), b""):
            digest.update(piece)
    after = os.stat(path)
    settled = time.time() - before.st_mtime > SETTLED_SECONDS
    if settled and (after.st_size, after.st_mtime_ns) == key[1:]:
        if len(_DIGESTS) > 4096:
            _DIGESTS.clear()
        _DIGESTS[key] = digest.hexdigest()
    return digest.hexdigest()


def media_digests(post):
    """One fingerprint per attached file, in posting order: the sha256 of the bytes the review
    page shows and a send or an export would use. The file is found the same way they find it
    (`review.store.resolve_media`, inside the post's own brand folder), so they cannot disagree
    about which file is meant. A file that cannot be used gets UNREADABLE, never an error."""
    if not post.media_paths:
        return []
    from smf import brands
    from smf.studio.review.store import resolve_media
    plain_id = isinstance(post.brand, str) and post.brand not in ("", ".", "..") \
        and os.path.basename(post.brand) == post.brand
    owner = brands.Brand(post.brand, os.path.join(brands.CLIENT_DIR, post.brand), {}) if plain_id else None
    out = []
    for raw in post.media_paths:
        real, problem = resolve_media(owner, raw) if owner else (None, "outside")
        try:
            out.append(UNREADABLE if problem else file_sha256(real))
        except OSError:
            out.append(UNREADABLE)
    return out


def _shown_sha(post):
    """The words, and the media by NAME. Until media contents were covered this was the whole
    fingerprint, which is how an approval from before that change is recognised."""
    import hashlib
    shown = {"text": post.text, "thread": list(post.thread), "media": list(post.media_paths),
             "first_comment": post.first_comment, "alt_text": post.alt_text, "link": post.link}
    return hashlib.sha256(json.dumps(shown, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def approval_sha(post, digests=None):
    """A fingerprint of everything a reader would see: the words (every tweet of a thread, the
    first comment, the alt text, the link) and the media, in posting order. The media counts by
    what is IN each file, not by its name: a picture remade under the same name is a different
    picture. Approving stores it in `approved_text_sha`; a different value later means the post
    changed after it was approved.
    This is the ONE definition. Review, export and posting all call it, so they cannot disagree.

    It has two halves joined by a dot: what the post says, then what its files contain. A post
    with no media has only the first half. `digests` is `media_digests(post)` when the caller
    already has it (a send keeps it, to check the very bytes it uploads)."""
    import hashlib
    shown = _shown_sha(post)
    if not post.media_paths:
        return shown
    digests = media_digests(post) if digests is None else list(digests)
    return shown + "." + hashlib.sha256(json.dumps(digests).encode("utf-8")).hexdigest()


def approval_state(post, digests=None):
    """Where a post's approval stands: "current", "none" (never approved), or why it stopped
    counting: "changed" (the words, or which files), "media-changed" (what is inside a file), or
    "media-unchecked" (approved before file contents were part of the fingerprint)."""
    stamped = post.approved_text_sha
    if not (post.approved_at and stamped):
        return "none"
    shown, _dot, contents = stamped.partition(".")
    if shown != _shown_sha(post):
        return "changed"
    if not post.media_paths:
        return "current" if not contents else "changed"
    if not contents:
        return "media-unchecked"
    return "current" if stamped == approval_sha(post, digests) else "media-changed"


def approval_is_current(post, digests=None):
    """True only when a person approved exactly what the post says and shows now."""
    return approval_state(post, digests) == "current"
