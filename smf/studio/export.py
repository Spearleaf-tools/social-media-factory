"""export.py - the ready-to-post folder: approved posts laid out for posting by hand.

    from smf.studio.export import export_ready_folder
    folder = export_ready_folder(brand, ["Client/maple-and-main/Output/batches/week 1.json"])

Writes `Client/<brand>/Output/ready-to-post/<date of the run>/`:

    README.txt                      what this is, the order to post in, where to paste on each network
    schedule.csv                    the same order as a table (opens in Excel, Numbers, Sheets)
    manifest.json                   what this folder holds, so a second run never makes duplicates
    2026-10-05 0630 instagram person a1/
        post.txt                    the exact words; for a thread on X, the tweets numbered [1/3] ...
        1.png  2.png  ...           the media, in posting order
        alt-text.txt                only when the post has one
        first-comment.txt           only when the post has one
        link.txt                    only when the post has one

It sends nothing anywhere. It only copies a brand's own files into that brand's own folder.

WHAT IT REFUSES
Only approved posts are exported, and "approved" means a person approved exactly what the post
says and shows now: `posts.approval_state`, which covers what is INSIDE every picture and video,
not just its name. A post that was changed after it was approved, whose picture was remade
after it was approved, that no longer passes this brand's checks, or whose media is missing or
outside the brand's folder, is left out and named in the report with the reason. Each file is
fingerprinted again as it is copied, on the very bytes that land in the folder, so a file
swapped at the last moment is caught too. A post the posting record says is on its way out
through the scheduling service is left out as well: posting it by hand would post it twice.

SAFE TO RUN TWICE
Each post folder is built under a temporary name and renamed into place, so a folder with a
real name is always complete. Then the manifest is written, then the posts are marked `exported`
in their batch (one atomic write per batch), then the README and the table. If the run stops
anywhere in between, the next run finds what is already there, finishes the marking, and copies
nothing twice. Nothing in a ready-to-post folder is ever overwritten or deleted.

NAMES
Every file and folder name is safe on Windows as well as on a Mac: none of <>:"/\\|?*, no
trailing dot or space, no reserved device name, under 120 characters, accents kept.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from smf.studio import posts as P
from smf.studio.files import StudioError, read_json, write_json
from smf.studio.review.store import BatchStore, append_history, now_iso, resolve_media
from smf.brands import replace_patiently

EXPORTABLE = ("approved",)
MANIFEST = "manifest.json"
NAME_LIMIT = 110                      # the promise is "under 120"; leave room
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}
_TMP_PREFIX = ".tmp-export-"

# How to paste on each network, kept general on purpose: apps move their buttons, the steps stay.
PASTE_NOTES_AS_OF = "June 2026"
PASTE_NOTES_LAST_RESEARCHED = "2026-06-11"
PASTE_NOTES = {
    "instagram": "Start a new post and choose the images in number order (1 first). Paste post.txt as the caption. "
                 "The alt text goes in the post's accessibility setting. Once the post is up, add "
                 "first-comment.txt as a comment.",
    "facebook": "On your Page, start a new post. Paste post.txt, then add the images in number order.",
    "linkedin": "Start a post. Paste post.txt, then add the images in number order (a PDF goes in as a document). "
                "Add the alt text on the image before you post.",
    "twitter": "On X, start a post, paste the first tweet and add the images. For a thread, add each next tweet "
               "before you post (or reply to your own post, one tweet at a time, in order). Leave the [1/3] labels out.",
    "tiktok": "Start a new post and upload the clip (in the app, or on tiktok.com from a computer). Paste post.txt "
              "as the description. Check who can view the post, because TikTok reuses the setting from your last "
              "post. Once it is up, add first-comment.txt as a comment.",
    "youtube": "In YouTube Studio, upload the video. Give it a title (up to 100 characters), then paste post.txt as "
               "the description. Add your thumbnail if you have one, say whether the video is made for kids (YouTube "
               "requires an answer), and choose who can see it: public now, or scheduled for later.",
}
PASTE_FALLBACK = "Start a new post, paste post.txt, and add the files in number order."
NETWORK_NAMES = {"twitter": "X", "linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram",
                 "threads": "Threads", "bluesky": "Bluesky", "tiktok": "TikTok", "youtube": "YouTube",
                 "pinterest": "Pinterest", "gmb": "Google Business Profile"}


class ExportError(StudioError):
    """The ready-to-post folder could not be made, in words for the person."""


class MediaChanged(ExportError):
    """A file's bytes are no longer the ones the person approved. Only that post is left out."""


@dataclass
class ExportReport:
    folder: str = ""                                   # where this run's posts are (or already were)
    exported: list = field(default_factory=list)       # [{"post_id", "folder"}] written by THIS run
    already: list = field(default_factory=list)        # [{"post_id", "folder"}] exported by an earlier run
    refused: list = field(default_factory=list)        # [{"post_id", "reason"}] approved, but not safe to export
    waiting: dict = field(default_factory=dict)        # {status: how many} posts that are not approved
    checked_only: bool = False


# ----------------------------------------------------------------------------- names
def safe_name(text, limit=NAME_LIMIT):
    """A file or folder name that works on Windows, macOS and Linux, from any text at all."""
    s = unicodedata.normalize("NFC", str(text or ""))
    s = _FORBIDDEN.sub("-", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"-{2,}", "-", s).strip(" .-")
    if len(s) > limit:
        s = s[:limit].rstrip(" .-")
    if not s:
        s = "post"
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s


def short_id(post_id):
    """The post's id if it is already short and safe; otherwise a short safe form of it plus a few
    characters of fingerprint, so two long or odd ids can never land on the same name."""
    raw = str(post_id)
    safe = re.sub(r"-{2,}", "-", safe_name(raw, 24).replace(" ", "-"))
    if safe == raw:
        return safe
    return "%s-%s" % (safe[:14].rstrip(" .-") or "post", hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6])


def folder_name(post, fingerprint=False):
    """`<date> <time> <platform> <identity> <short id>`. With fingerprint=True a few characters of
    the id's fingerprint are added: used when two ids differ only in a way a file system ignores."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})$", post.scheduled_time_local or "")
    when = "%s %s%s" % (m.group(1), m.group(2), m.group(3)) if m else "no-date"
    tail = short_id(post.id)
    if fingerprint:
        tail = "%s-%s" % (tail[:20], hashlib.sha1(str(post.id).encode("utf-8")).hexdigest()[:6])
    return safe_name("%s %s %s %s" % (when, safe_name(post.platform, 20), safe_name(post.identity, 30), tail))


# ----------------------------------------------------------------------------- what a post folder holds
def post_text(post):
    """The words exactly as approved. A thread is numbered so each tweet can be pasted on its own."""
    if not post.thread:
        return post.text
    tweets = [post.text] + list(post.thread)
    return "\n\n".join("[%d/%d]\n%s" % (i, len(tweets), t) for i, t in enumerate(tweets, start=1)) + "\n"


def _write_text(path, text, encoding="utf-8"):
    """Atomic, and newline-exact: what was approved is what lands in the file."""
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
        f.write(text)
    _open_up(tmp, 0o644)
    replace_patiently(tmp, path)


def _open_up(path, mode):
    try:                                                  # temporary files start private; these are the person's
        os.chmod(path, mode)                              # own posts, so give them ordinary permissions
    except OSError:
        pass


def _copy_verified(source, dest, approved_sha256):
    """Copy a file a piece at a time and fingerprint the pieces as they are written, so the check
    is made on the bytes that really landed in the folder and a large video never sits in memory."""
    digest = hashlib.sha256()
    with open(source, "rb") as src, open(dest, "wb") as out:
        for piece in iter(lambda: src.read(P.HASH_CHUNK_BYTES), b""):
            digest.update(piece)
            out.write(piece)
    if digest.hexdigest() != approved_sha256:
        raise MediaChanged("'%s' changed after you approved this post, so it was left out. Look at it on the "
                           "review page and approve it again" % os.path.basename(source))


def _build_post_folder(brand, post, run_dir, name, digests):
    """`digests` are the approved fingerprints of the post's files, one per path, in order."""
    tmp = tempfile.mkdtemp(prefix=_TMP_PREFIX, dir=run_dir)
    _open_up(tmp, 0o755)
    try:
        _write_text(os.path.join(tmp, "post.txt"), post_text(post))
        for n, (raw, digest) in enumerate(zip(post.media_paths, digests), start=1):
            real, problem = resolve_media(brand, raw)
            if problem:                                   # checked before we got here; check again anyway
                raise ExportError("a media file went missing while the folder was being made")
            _copy_verified(real, os.path.join(tmp, "%d%s" % (n, os.path.splitext(real)[1].lower())), digest)
        for fname, value in (("alt-text.txt", post.alt_text), ("first-comment.txt", post.first_comment),
                             ("link.txt", post.link)):
            if value and value.strip():
                _write_text(os.path.join(tmp, fname), value)
        os.replace(tmp, os.path.join(run_dir, name))      # a folder with a real name is always complete
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# ----------------------------------------------------------------------------- the manifest
def _ready_root(brand):
    return brand.path("Output", "ready-to-post")


def _manifests(brand):
    """{run folder: manifest} for every earlier run. A damaged manifest is skipped, not fatal."""
    root, out = _ready_root(brand), {}
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name, MANIFEST)
        if os.path.isfile(path):
            try:
                data = read_json(path, "An earlier ready-to-post list")
            except StudioError:
                continue
            if isinstance(data, dict) and data.get("brand") == brand.id and isinstance(data.get("posts"), list):
                out[os.path.join(root, name)] = data
    return out


def _entry(brand, post, name, batch_path, sha):
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})$", post.scheduled_time_local or "")
    first = next((ln.strip() for ln in post.text.splitlines() if ln.strip()), "")
    return {"post_id": post.id, "folder": name, "sha": sha, "batch": os.path.basename(batch_path),
            "exported_at": now_iso(), "date": m.group(1) if m else "", "time": m.group(2) if m else "",
            "platform": post.platform, "identity": post.identity,
            "identity_name": brand.identity(post.identity).get("display_name") or post.identity,
            "files": len(post.media_paths), "tweets": (len(post.thread) + 1) if post.thread else 0,
            "first_comment": bool(post.first_comment.strip()), "alt_text": bool(post.alt_text.strip()),
            "link": bool(post.link.strip()), "facts_checked": post.sourcing == "passed",
            "subject": post.pillar or post.topic_id, "first_line": first[:120]}


# ----------------------------------------------------------------------------- README and table
def _in_posting_order(entries):
    return sorted(entries, key=lambda e: (e.get("date") or "9999", e.get("time") or "99:99", e.get("folder", "")))


def _cell(value):
    """A spreadsheet must show this text, never run it as a formula."""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _schedule_csv(brand, entries):
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["order", "date", "time", "timezone", "network", "voice", "folder", "files", "tweets",
                "first_comment", "alt_text", "link", "facts_checked", "subject", "first_line", "post_id", "batch"])
    for n, e in enumerate(_in_posting_order(entries), start=1):
        w.writerow([_cell(v) for v in (
            n, e.get("date", ""), e.get("time", ""), brand.timezone, NETWORK_NAMES.get(e["platform"], e["platform"]),
            e.get("identity_name", ""), e["folder"], e.get("files", 0), e.get("tweets", 0) or "",
            "yes" if e.get("first_comment") else "", "yes" if e.get("alt_text") else "",
            "yes" if e.get("link") else "",
            "yes" if e.get("facts_checked") else "no: approved on the reviewer's own word",
            e.get("subject", ""), e.get("first_line", ""), e["post_id"], e.get("batch", ""))])
    return buf.getvalue()


def _readme(brand, run_name, entries):
    ordered = _in_posting_order(entries)
    lines = [
        "READY TO POST: %s" % brand.name,
        "Made by Social Media Factory. This folder is for the run of %s." % run_name,
        "",
        "WHAT THIS FOLDER IS",
        "Every post you approved, laid out so you can post it by hand. Nothing here has been posted or",
        "scheduled for you, and nothing was sent anywhere. Each folder below is one post.",
        "",
        "IN EACH POST FOLDER",
        "  post.txt            The words, exactly as you approved them. Copy all of it and paste it in.",
        "                      A thread on X is numbered [1/3], [2/3] ...: post the tweets one after",
        "                      another in that order, and leave the [1/3] labels out.",
        "  1, 2, 3 ...         The images or clips, numbered in the order to add them.",
        "  alt-text.txt        When there is one: the description of the image for people who cannot see it.",
        "  first-comment.txt   When there is one: add it as the first comment, straight after the post goes up.",
        "  link.txt            When there is one: the link that goes with the post.",
        "",
        "THE ORDER TO POST IN",
        "Work down this list. The times are in %s time and are the ones you approved. If a time has" % brand.timezone,
        "already passed, post at the next good moment and carry on. schedule.csv holds the same list as a",
        "table (it opens in Excel, Numbers or Google Sheets), with a column to tick posts off if you add one.",
        "",
    ]
    for n, e in enumerate(ordered, start=1):
        when = ("%s %s" % (e.get("date"), e.get("time"))) if e.get("date") else "no time set"
        lines.append("  %2d. %-16s  %-10s  %s" % (n, when, NETWORK_NAMES.get(e["platform"], e["platform"]),
                                                  e.get("identity_name", "")))
        lines.append("      folder: %s" % e["folder"])
        if not e.get("facts_checked"):
            lines.append("      note: the facts in this one were not checked against your own material; "
                         "you approved it on your own word.")
    lines += ["", "WHERE TO PASTE, NETWORK BY NETWORK",
              "(These steps were last researched in %s. Apps move their buttons around; the steps stay similar.)"
              % PASTE_NOTES_AS_OF, ""]
    for plat in sorted({e["platform"] for e in ordered}):
        lines.append("  %s" % NETWORK_NAMES.get(plat, plat))
        lines.append("      %s" % PASTE_NOTES.get(plat, PASTE_FALLBACK))
    lines += ["", "IF SOMETHING NEEDS TO CHANGE",
              "Change the words in post.txt yourself before you paste. Running the export again is always safe:",
              "it adds newly approved posts, never copies a post twice, and never overwrites what is here.", ""]
    return "\r\n".join(lines)                             # opens cleanly in Notepad as well as everywhere else


# ----------------------------------------------------------------------------- the export
def export_posts(brand, batch_paths, only_status="approved", run_date=None, check_only=False):
    """Do the export (or, with check_only, only work out what it would do). Returns an ExportReport."""
    if only_status not in EXPORTABLE:
        raise ExportError("Only approved posts can go into a ready-to-post folder. Approve them on the review "
                          "page first. (Asked for: '%s'.)" % only_status)
    store = BatchStore(brand, batch_paths)                # no brand, wrong brand, no batch: refused here
    brand = store.brand
    run_name = safe_name(run_date or datetime.now().strftime("%Y-%m-%d"))
    run_dir = os.path.join(_ready_root(brand), run_name)
    report = ExportReport(folder=run_dir, checked_only=check_only)

    earlier = {}                                          # post_id -> (run folder, manifest entry)
    for folder, data in _manifests(brand).items():
        for e in data["posts"]:
            if isinstance(e, dict) and e.get("post_id"):
                earlier[e["post_id"]] = (folder, e)

    todo, to_mark = [], {}
    taken = {str(e.get("folder", "")).lower() for folder, data in _manifests(brand).items()
             if os.path.normcase(folder) == os.path.normcase(run_dir) for e in data["posts"] if isinstance(e, dict)}
    for path in store.files:
        posts, _meta, _stamp = store.read(path)
        for post in posts:
            known = earlier.get(post.id)
            if post.status == "exported":
                report.already.append({"post_id": post.id, "folder": os.path.join(known[0], known[1]["folder"])
                                       if known else ""})
                continue
            if post.status != only_status:
                report.waiting[post.status] = report.waiting.get(post.status, 0) + 1
                continue
            digests = P.media_digests(post)
            sha = P.approval_sha(post, digests)
            reason = _why_not(store, post, path, digests)
            if not reason and known and known[1].get("sha") != sha:
                reason = ("it was exported before with different words (folder '%s'). Rename or remove that folder "
                          "yourself if the new version should replace it, then run this again" % known[1]["folder"])
            if reason:
                report.refused.append({"post_id": post.id, "reason": reason})
                continue
            if known:                                     # an earlier run wrote the folder but never got to mark it
                report.already.append({"post_id": post.id, "folder": os.path.join(known[0], known[1]["folder"])})
                to_mark.setdefault(path, {})[post.id] = sha
                continue
            name = folder_name(post)
            if name.lower() in taken:                     # "A1" and "a1" are one name to Windows and to a Mac
                name = folder_name(post, fingerprint=True)
            if name.lower() in taken:
                report.refused.append({"post_id": post.id, "reason": "another post in this run would get the same "
                                       "folder name. Give the two posts different ids"})
                continue
            taken.add(name.lower())
            todo.append((path, post, name, digests))

    if not (todo or report.already or to_mark):
        if report.refused:
            raise ExportError("Nothing could be exported:\n  - " + "\n  - ".join(
                "%s: %s." % (r["post_id"], r["reason"]) for r in report.refused))
        raise ExportError("There are no approved posts to export yet. Open the review page, approve the posts "
                          "you are happy with, then run this again.")
    if check_only:
        report.exported = [{"post_id": post.id, "folder": os.path.join(run_dir, name)} for _p, post, name, _d in todo]
        return report

    if todo:
        os.makedirs(run_dir, exist_ok=True)
        for stale in os.listdir(run_dir):                 # leftovers of a run that was stopped half way
            if stale.startswith(_TMP_PREFIX):
                shutil.rmtree(os.path.join(run_dir, stale), ignore_errors=True)
        manifest_path = os.path.join(run_dir, MANIFEST)
        manifest = {"brand": brand.id, "brand_name": brand.name, "run": run_name, "posts": []}
        if os.path.isfile(manifest_path):
            old = read_json(manifest_path, "This folder's list of posts (manifest.json)")
            if isinstance(old, dict) and isinstance(old.get("posts"), list):
                manifest["posts"] = [e for e in old["posts"] if isinstance(e, dict)]

        for path, post, name, digests in todo:
            final = os.path.join(run_dir, name)
            if os.path.exists(final):                     # finished by a stopped run, never listed: adopt or refuse
                if _same_words(final, post):
                    report.already.append({"post_id": post.id, "folder": final})
                else:
                    report.refused.append({"post_id": post.id, "reason": "a folder called '%s' is already there "
                                           "with different words. Rename or remove it yourself, then run this "
                                           "again" % name})
                    continue
            else:
                try:
                    _build_post_folder(brand, post, run_dir, name, digests)
                except MediaChanged as e:                 # swapped between the check and the copy: only this post
                    report.refused.append({"post_id": post.id, "reason": str(e)})
                    continue
                report.exported.append({"post_id": post.id, "folder": final})
            sha = P.approval_sha(post, digests)
            manifest["posts"].append(_entry(brand, post, name, path, sha))
            to_mark.setdefault(path, {})[post.id] = sha

        write_json(manifest_path, manifest)
        _write_text(os.path.join(run_dir, "README.txt"), _readme(brand, run_name, manifest["posts"]))
        _write_text(os.path.join(run_dir, "schedule.csv"), _schedule_csv(brand, manifest["posts"]),
                    encoding="utf-8-sig")                 # the mark lets Excel read accents correctly
    elif report.already:
        folders = sorted({os.path.dirname(a["folder"]) for a in report.already if a["folder"]})
        report.folder = folders[-1] if folders else run_dir

    _mark_exported(store, to_mark)
    return report


# What the posting record can say about a post (`store.posting_block`), worded for a folder of
# posts to put up by hand: whatever is going out through the scheduling service must not go out twice.
_ON_ITS_WAY_OUT = {
    "sending": "it is being sent through the scheduling service right now, so posting it by hand would post it twice",
    "unsettled": "an earlier send of it through the scheduling service never got a clear answer. Run a results "
                 "check first, so it is not posted twice",
    "sent": "it has already been scheduled through the scheduling service. Run a results check to bring the batch "
            "up to date",
    "sent-before": "an earlier version of it already went out through the scheduling service",
}


def _why_not(store, post, batch_path, digests):
    """Why an approved post still must not be exported, or None. `digests` is `posts.media_digests(post)`."""
    approval = P.approval_state(post, digests)
    if approval == "changed" or approval == "none":
        return "it was changed after it was approved, so nobody has approved what it says now. Approve it again " \
               "on the review page"
    if approval != "current":
        return "it " + P.APPROVAL_VOID_WORDS[approval]
    code, in_flight = store.posting_block(post, batch_path)
    if in_flight:
        return _ON_ITS_WAY_OUT.get(code) or in_flight.rstrip(".")
    store.relint(post)
    if post.lint_errors:
        first = re.sub(r"^\[ERROR\]\s*[^:]+:\s*", "", post.lint_errors[0])
        return "it no longer passes this brand's checks (%s)" % first.rstrip(".")
    if post.sourcing == "blocked":
        return "the fact check found something in it that does not match the brand's own material"
    return None


def _same_words(folder, post):
    try:
        with open(os.path.join(folder, "post.txt"), "r", encoding="utf-8", newline="") as f:
            return f.read() == post_text(post)
    except OSError:
        return False


def _mark_exported(store, to_mark):
    """One atomic write per batch. A post is only marked if it is still exactly what was exported."""
    for path, wanted in to_mark.items():
        with store.writing([path]):
            posts, meta, stamp = store.read(path)
            lines = []
            for post in posts:
                if post.id in wanted and post.status == "approved" and P.approval_sha(post) == wanted[post.id]:
                    post.status = "exported"
                    post.rev += 1
                    lines.append({"post_id": post.id, "at": now_iso(), "action": "exported", "actor": "export",
                                  "note": "written to the ready-to-post folder", "rev": post.rev})
            if lines:
                store.write(path, posts, meta, stamp)
                for line in lines:
                    append_history(path, line)


def export_ready_folder(brand, batch_paths, only_status="approved"):
    """Write this brand's approved posts to its ready-to-post folder and return that folder.
    `brand` is a Brand or a brand id: there is no default. See the top of this file for the rules."""
    return Path(export_posts(brand, batch_paths, only_status=only_status).folder)
