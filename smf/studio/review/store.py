"""store.py - what the review page may do to a batch, and how it does it without losing work.

There is no web server in this file, so the export tool can share the same rules.

THE BRAND COMES FIRST
A store is opened for ONE brand. Every batch is loaded through `posts.load_batch(path, brand.id)`,
which refuses a file that belongs to anyone else, and every check uses THIS brand's rules.

WHAT "APPROVED" MEANS
Approving stamps `approved_at` and `approved_text_sha` (see `posts.approval_sha`): a fingerprint
of exactly what the person was looking at. Any later change to the words or the media clears the
stamp and the post goes back to `lint_pass` or `draft`, because nobody has approved the new version.
A post whose facts were never checked against the brand's own material can only be approved when
the person says, explicitly, that they checked the facts themselves; that is written on the post.

WRITING SAFELY
Three things can write the same batch at once: this page, a Claude session remaking posts, and
a run that is sending the batch.
  * Every change here happens under `batch_lock`, a lock FILE beside the batch, because the
    sender is another program and a lock inside this one means nothing to it. The sender takes
    the same lock to read a post again and reserve it in the posting record.
  * While the posting record holds an unsettled send of a post (it is going out right now, or
    nobody knows whether it went out), this page will not change, approve or turn down that
    post. Changing the words would make it look like a new post to the record, and that is how
    one post goes out twice. The person is told to run a results check first.
  * Every change names the `rev` the person was looking at. A different `rev` on disk means the
    post moved on, so nothing is written and the page is told to show the new version.
  * Approving also names the fingerprint of what was on screen, so a person can never approve
    words they were not shown, even if another tool forgot to bump `rev`.
  * The file is read fresh for every change, checked again just before saving, and replaced in
    one step (`posts.save_batch`), so a crash never leaves half a batch.
  * The first change to a batch keeps an untouched copy beside it (`<name>.bak`).

THE HISTORY FILE
Beside each batch sits `<name>.history.jsonl`: one line per action, only ever added to. It is what
makes undo possible, and it is where "this person has seen this version" is remembered, so the
batch file itself only changes when a post really changes.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sqlite3
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import datetime, timezone

from smf import brands
from smf.brands import BrandError
from smf.posting.ledger import LEDGER_FILE, Ledger, LedgerError, Lock, standing
from smf.studio import posts as P
from smf.studio.files import StudioError
from smf.studio.lint import PLATFORM_CHAR_LIMITS, Rules

ACTOR = "review-page"
APPROVABLE_FROM = frozenset({"draft", "lint_pass"})
# Once a post has left the building, the review page only looks at it.
LOCKED = frozenset({"scheduled", "posted", "exported"})
UNDOABLE = frozenset({"edit", "approve", "approve-all", "reject", "remake"})
REMAKE_KINDS = ("words", "image")

# What the page will show, and what export will copy. Anything else in `media_paths` is refused.
MEDIA_KINDS = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
               ".mp4": "video", ".mov": "video", ".m4v": "video", ".webm": "video", ".pdf": "document"}

# Roughly where a feed stops showing a caption and offers "see more". Drawn on the card so the
# person judges the part most readers will actually see. Approximate, and networks move it.
FOLD_MARKERS = {"linkedin": 140, "instagram": 125}
FOLDS_AS_OF = "June 2026"
FOLDS_LAST_RESEARCHED = "2026-06-11"

UNVERIFIED_BADGE = "unverified: the facts in this post have not been checked against your own material"
FACTS_FAILED_BADGE = ("fact check failed: something in this post does not match your own material. "
                      "Edit it or ask for a remake.")
ACKNOWLEDGED_NOTE = "Approved with unverified facts: the reviewer confirmed they checked the facts themselves"

LOCK_WAIT_SECONDS = 10              # a send holds the lock for a moment at a time, never for a whole upload
# Why an approval stopped counting, said to someone who is looking at the post. `posts` has the
# same three cases worded for a report the person reads away from the page.
APPROVAL_NOTES = {
    "changed": "This post was changed after it was approved, so the approval no longer counts. Read it again and "
               "approve it if it is right.",
    "media-changed": "A picture or video on this post changed after it was approved, so the approval no longer "
                     "counts. Look at it again and approve it if it is right.",
    "media-unchecked": "This post was approved before the Factory started checking what is inside a picture or "
                       "video, and not just its name. Nothing is wrong with it: look it over once and approve it "
                       "again.",
}
IN_FLIGHT = {
    "sending": "This post is being sent to the scheduling service right now, so it cannot be changed. Reload the "
               "page in a minute to see how it went.",
    "unsettled": "An earlier send of this post never got a clear answer, so nobody knows whether it went out. Run a "
                 "results check first (or settle it by hand). Until then it cannot be changed, approved or turned "
                 "down here, because a changed copy could go out as a second post.",
    "sent": "This post has already been scheduled, and this page has not caught up yet. Run a results check to bring "
            "it up to date. It cannot be changed here.",
    "sent-before": "An earlier version of this post already went out from this batch, so this version will not be "
                   "sent as well. If it really is a new post, ask Claude to give it its own id.",
}

# Everything undo has to put back, and everything a change can touch.
_REMEMBERED = ("text", "thread", "media_paths", "alt_text", "first_comment", "link", "status", "feedback",
               "approved_at", "approved_text_sha", "sourcing", "facts_check", "lint_errors", "lint_warnings")


class Refusal(StudioError):
    """Something the review page will not do, in plain words. `status` is the web status code and
    `extra` rides along in the answer (for example the fresh copy of a post that moved on)."""

    def __init__(self, message, status=400, **extra):
        StudioError.__init__(self, message)
        self.message = message
        self.status = status
        self.extra = extra


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def batch_lock(batch_path, wait_seconds=LOCK_WAIT_SECONDS):
    """The lock EVERY writer of a batch file takes: this page, the export, and a run that sends.
    A file beside the batch, made the one way that is atomic on Windows, Mac and Linux alike."""
    return Lock(os.path.abspath(os.fspath(batch_path)) + ".lock", wait_seconds)


def open_brand(brand):
    """A Brand, from a Brand or a brand id. No brand named, or an unknown one, is a BrandError."""
    if isinstance(brand, brands.Brand):
        return brand
    return brands.load(brand)


# ----------------------------------------------------------------------------- media stays inside the brand
def resolve_media(brand, raw):
    """(real_path, problem). The file one `media_paths` entry points at, but only when it truly
    lives inside THIS brand's folder and is a kind of file a post can carry.

    problem is "" when all is well, otherwise one of: "outside" (absolute path elsewhere, '..',
    or a link that leads out), "missing", "type". The check is made on the real location, after
    links and '..' are followed, so there is no spelling of a path that gets around it."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "missing"
    raw = raw.strip()
    absolute = os.path.isabs(raw) or raw.startswith(("/", "\\")) or bool(re.match(r"^[A-Za-z]:", raw))
    if absolute:
        candidate = raw
    else:
        candidate = os.path.join(brand.home, *[p for p in re.split(r"[\\/]+", raw) if p not in ("", ".")])
    home = os.path.normcase(os.path.realpath(brand.home))
    real = os.path.realpath(candidate)
    if not os.path.normcase(real).startswith(home + os.sep):
        return None, "outside"
    if not os.path.isfile(real):
        return None, "missing"
    if os.path.splitext(real)[1].lower() not in MEDIA_KINDS:
        return None, "type"
    return real, ""


_ORIGIN_WORDS = {"stock": "stock photo", "generated": "generated image"}


def picture_origins(path):
    """What a reviewer should know about where a picture came from, in plain words: "stock
    photo" or "generated image" when the picture is one, or was drawn with one inside it. Read
    from the picture's own record, or from the render report saved beside a drawn picture.
    Empty for the brand's own photos and for pictures drawn from words alone."""
    if not path:
        return []
    found = []
    try:
        with open(path + ".source.json", "r", encoding="utf-8") as f:
            found.append(str((json.load(f) or {}).get("source") or ""))
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(os.path.dirname(path), "render-report.json"), "r", encoding="utf-8") as f:
            report = json.load(f)
        for row in report.get("images") or []:
            if isinstance(row, dict) and row.get("file") == os.path.basename(path):
                found.extend(str(use.get("source") or "") for use in row.get("uses") or [] if isinstance(use, dict))
    except (OSError, ValueError, AttributeError):
        pass
    return [_ORIGIN_WORDS[s] for s in ("stock", "generated") if s in found]


def media_name(raw):
    return re.split(r"[\\/]+", str(raw or "").strip())[-1] or "file"


_MEDIA_PROBLEMS = {
    "outside": "[ERROR] media-outside: '%s' is not inside this brand's folder, so it cannot be shown or posted. "
               "Move the file into the brand's folder.",
    "missing": "[ERROR] media-missing: '%s' is not where the post says it is. Remake the visual or fix the path.",
    "type": "[ERROR] media-type: '%s' is not an image, a video or a PDF.",
}


# ----------------------------------------------------------------------------- consent and proof
def consent_findings(brand, post):
    """What the brand's proof library says about this post. The rules are not ours: they belong to
    `smf.studio.proof` (may a file ride on a post?) and `smf.studio.grounding` (what is linked?).

      * A FILE from the proof folder that is marked do-not-publish, or that nobody has accounted
        for, stops the post. A customer's screenshot never goes out on a guess.
      * Linked proof that is private is allowed: it may inform the writing as background, and the
        fact check is what catches it leaking into the words. The reviewer is told, so they look.
    """
    from smf.studio import grounding, proof

    out = []
    for raw in post.media_paths:
        _real, problem = resolve_media(brand, raw)
        if problem:
            continue                                      # already reported as a media problem
        try:
            reason = proof.media_block_reason(brand, raw)
        except sqlite3.Error:
            reason = "the proof library could not be read, so nobody can tell whether it may be published"
        if reason:
            out.append("[ERROR] media-not-cleared: '%s' cannot go out: %s." % (media_name(raw), reason))
    try:
        found, missing = grounding.load_proof(brand, [str(i) for i in (post.proof_ids or [])])
    except (sqlite3.Error, StudioError):
        found, missing = [], []
    for item in found:
        if item.get("may_publish") not in ("anonymised", "yes"):
            out.append("[WARN] private-proof: this post leans on '%s', which is private background. Check that "
                       "nothing from it shows in the words or the image." % item.get("title", item["proof_id"]))
        elif item.get("may_publish") == "anonymised":
            out.append("[WARN] proof-anonymised: '%s' may only appear with names removed. Check that no name, "
                       "face or logo shows." % item.get("title", item["proof_id"]))
    for pid in missing:
        out.append("[WARN] proof-unknown: this post cites proof '%s', which is not in this brand's proof library."
                   % pid)
    return out


# ----------------------------------------------------------------------------- the history file
def history_path(batch_path):
    folder, name = os.path.split(batch_path)
    return os.path.join(folder, os.path.splitext(name)[0] + ".history.jsonl")


def read_history(batch_path):
    path = history_path(batch_path)
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue                # one torn line must never take the review page down
            if isinstance(entry, dict):
                out.append(entry)
    return out


def append_history(batch_path, entry):
    with open(history_path(batch_path), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def seen_marks(history):
    """{post_id: {"sha", "at"}}: the last version of each post the person had in front of them.
    Their own changes count: whoever typed the edit has seen it."""
    marks = {}
    for e in history:
        if e.get("actor") == ACTOR and e.get("post_id") and e.get("content_sha"):
            marks[e["post_id"]] = {"sha": e["content_sha"], "at": e.get("at", "")}
    return marks


# ----------------------------------------------------------------------------- the store
class Located(object):
    def __init__(self, path, posts, meta, index, stamp):
        self.path, self.posts, self.meta, self.index, self.stamp = path, posts, meta, index, stamp

    @property
    def post(self):
        return self.posts[self.index]


def _stamp(path):
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


class BatchStore(object):
    """One brand, one or more of its batch files, opened as a single review."""

    def __init__(self, brand, batch_paths):
        self.brand = open_brand(brand)
        self.rules = Rules.for_brand(self.brand)
        self.lock = threading.Lock()
        self._record = (None, {})                             # the posting record, and the file stamp it was read at
        self.files = []
        for raw in batch_paths or []:
            path = os.path.abspath(os.fspath(raw))
            if path not in self.files:
                self.files.append(path)
        if not self.files:
            raise Refusal("There is no batch to review yet for %s. Write some posts first." % self.brand.name, 404)
        owner = {}
        for path in self.files:
            posts, _meta, _stamp_ = self.read(path)           # refuses another brand's batch, here, at the door
            for p in posts:
                if p.id in owner:
                    raise Refusal("Two posts share the id '%s' (in %s and %s). Every post in one review needs "
                                  "its own id. Open the batches one at a time, or ask Claude to fix the ids."
                                  % (p.id, os.path.basename(owner[p.id]), os.path.basename(path)))
                owner[p.id] = path

    # reading ---------------------------------------------------------------------------------
    def read(self, path):
        name = os.path.basename(path)
        if not os.path.isfile(path):
            raise Refusal("The batch '%s' could not be found." % name, 404)
        try:
            stamp = _stamp(path)
            posts, meta = P.load_batch(path, self.brand.id)
        except json.JSONDecodeError as e:
            raise Refusal("The batch '%s' is damaged and cannot be read (%s). Nothing was changed. "
                          "Ask Claude to repair it." % (name, e))
        except ValueError as e:                               # it belongs to another brand
            raise Refusal("'%s' was not opened: %s" % (name, e), 403)
        except (TypeError, AttributeError, KeyError):
            raise Refusal("'%s' is not a batch of posts in the shape the Factory writes. Nothing was changed."
                          % name)
        except OSError:
            raise Refusal("The batch '%s' could not be opened." % name, 404)
        return posts, meta, stamp

    @contextmanager
    def writing(self, paths=None):
        """Hold everything a change needs: this page's own lock, then the lock file of each batch
        (always in the same order, so two reviews of the same batches cannot wait on each other)."""
        with self.lock, ExitStack() as held:
            try:
                for path in sorted(set(paths or self.files)):
                    held.enter_context(batch_lock(path))
            except LedgerError:
                raise Refusal("This batch is being updated by a run that is sending it right now. Nothing was "
                              "changed. Try again in a moment.", 409)
            yield

    def locate(self, post_id):
        for path in self.files:
            posts, meta, stamp = self.read(path)
            for i, p in enumerate(posts):
                if p.id == post_id:
                    return Located(path, posts, meta, i, stamp)
        raise Refusal("There is no post with the id '%s' in this review." % post_id, 404)

    # checking --------------------------------------------------------------------------------
    def relint(self, post):
        """Check one post against THIS brand's rules and fill its findings. Never touches status."""
        post.lint(self.rules)
        extra = list(P.media_findings(post))
        try:
            self.brand.identity(post.identity)
        except BrandError as e:
            extra.append("[ERROR] identity: %s" % e)
        for raw in post.media_paths:
            _path, problem = resolve_media(self.brand, raw)
            if problem:
                extra.append(_MEDIA_PROBLEMS[problem] % media_name(raw))
        extra.extend(consent_findings(self.brand, post))
        for finding in extra:
            (post.lint_errors if finding.startswith("[ERROR]") else post.lint_warnings).append(finding)
        return post

    # the posting record ----------------------------------------------------------------------
    def _posting_record(self):
        """{key: send} from this brand's posting record. Read again only when the file has moved,
        because the page asks about every post it draws."""
        path = os.path.join(self.brand.state_dir, LEDGER_FILE)
        try:
            st = os.stat(path)
        except OSError:
            return {}                                         # this brand has never sent anything
        stamp = (st.st_mtime_ns, st.st_size)
        if self._record[0] != stamp:
            self._record = (stamp, Ledger(self.brand).all())
        return self._record[1]

    def posting_block(self, post, batch_path):
        """(code, sentence) when the posting record says hands off this post, else (None, None).
        See IN_FLIGHT for the codes. A record that cannot be read blocks too: nobody can tell
        what is on its way out, and the sentence says how to get it repaired."""
        if post.status in LOCKED:
            return None, None
        try:
            code, _send = standing(self._posting_record(), post, os.path.basename(batch_path))
        except LedgerError as e:
            return "record-damaged", "%s Until then, posts cannot be changed or approved here." % e
        return code, IN_FLIGHT.get(code)

    def _refuse_if_in_flight(self, post, loc, approving=False):
        code, why = self.posting_block(post, loc.path)
        if why and (approving or code != "sent-before"):     # a version that will never go out may still be
            raise Refusal(why, 409, reason=code)              # edited or turned down; it may not be approved

    def approval_problem(self, post, acknowledged, linted=False, batch_path=None):
        """(code, sentence) saying why this post cannot be approved right now, or (None, None)."""
        if post.status in LOCKED:
            return "locked", ("This post has already been %s, so it cannot be changed here."
                              % post.status)
        if batch_path is not None:
            code, why = self.posting_block(post, batch_path)
            if why:
                return code, why
        if post.status == "regen_queued":
            return "remake", ("A remake has been asked for. Wait for the new version, or undo the request "
                              "if you want to keep this one.")
        voided = post.status == "approved" and not P.approval_is_current(post)
        if post.status == "approved" and not voided:
            return "already", "This post is already approved."
        if post.status not in APPROVABLE_FROM and not voided:
            return "status", {"rejected": "This post was turned down. Undo that first if you changed your mind.",
                              "blocked": "This post was stopped by a check. Edit it or ask for a remake, then "
                                         "approve the new version."}.get(
                post.status, "A post marked '%s' cannot be approved." % post.status)
        if not linted:
            self.relint(post)
        if post.lint_errors:
            n = len(post.lint_errors)
            return "lint", ("This post has %d problem%s that must be fixed before it can be approved."
                            % (n, "" if n == 1 else "s"))
        if post.sourcing == "blocked":
            return "facts-failed", ("The fact check found something in this post that does not match your own "
                                    "material. Edit it or ask for a remake; it cannot be approved as it is.")
        if post.sourcing != "passed" and not acknowledged:
            return "needs-acknowledgement", ("The facts in this post have not been checked against your own "
                                             "material. Confirm that you checked them yourself to approve it.")
        return None, None

    def _approve(self, post):
        if post.sourcing != "passed":
            post.feedback = "%s (%s)." % (ACKNOWLEDGED_NOTE, now_iso())
        post.status = "approved"
        post.approved_at = now_iso()
        post.approved_text_sha = P.approval_sha(post)

    # what the page is told -------------------------------------------------------------------
    def describe(self, post, batch_path, marks):
        """One post as the page sees it. Call after relint(post)."""
        sha = P.approval_sha(post)
        mark = marks.get(post.id)
        seen = bool(mark) and mark["sha"] == sha
        d = asdict(post)
        d.pop("media_paths")                      # the page works with positions, never with paths
        media = []
        for i, raw in enumerate(post.media_paths):
            path, problem = resolve_media(self.brand, raw)
            kind = MEDIA_KINDS.get(os.path.splitext(path)[1].lower(), "") if path else ""
            row = {"index": i, "name": media_name(raw), "kind": kind, "problem": problem}
            origins = picture_origins(path)
            if origins:                           # only words go to the page, never where the file is
                row["origins"] = origins
            media.append(row)
        try:
            who = self.brand.identity(post.identity).get("display_name") or post.identity
        except BrandError:
            who = post.identity
        state = P.approval_state(post) if post.status == "approved" else "none"
        approval = state if state in ("current", "none") else "voided"
        code, why = self.approval_problem(post, acknowledged=True, linted=True, batch_path=batch_path)
        timing = "" if post.status in LOCKED or post.status == "rejected" else (P.future_time_problem(post) or "")
        d.update({
            "batch": os.path.basename(batch_path), "content_sha": sha, "identity_name": who, "media": media,
            "approval": approval, "approval_note": APPROVAL_NOTES.get(state, "") if approval == "voided" else "",
            "locked": post.status in LOCKED,
            "seen": seen, "seen_at": mark["at"] if seen else "", "changed_since_seen": bool(mark) and not seen,
            "approve_block": why or "", "approve_block_code": code or "",
            "needs_acknowledgement": post.sourcing != "passed",
            "sourcing_note": {"passed": "", "blocked": FACTS_FAILED_BADGE}.get(post.sourcing, UNVERIFIED_BADGE),
            "timing_note": ("Check the timing: %s. Ask Claude to move it to a new time." % timing) if timing else "",
        })
        return d

    def overview(self):
        """Everything the page needs to draw itself. Reads only; nothing is written."""
        all_posts, files = [], []
        for path in self.files:
            posts, meta, _s = self.read(path)
            marks = seen_marks(read_history(path))
            for p in posts:
                all_posts.append(self.describe(self.relint(p), path, marks))
            files.append({"name": os.path.basename(path), "count": len(posts),
                          "made": str(meta.get("generated_at") or meta.get("created_at") or "")})
        limits = {}
        for plat, cap in PLATFORM_CHAR_LIMITS.items():
            limits[plat] = {"max": cap}
            if plat in FOLD_MARKERS:
                limits[plat]["fold"] = FOLD_MARKERS[plat]
        style = self.brand.style
        return {
            "brand": {"id": self.brand.id, "name": self.brand.name, "timezone": self.brand.timezone,
                      "identities": {i["id"]: i.get("display_name") or i["id"]
                                     for i in self.brand.data["identities"]}},
            "posts": all_posts, "files": files, "limits": limits,
            "folds_as_of": FOLDS_AS_OF, "folds_last_researched": FOLDS_LAST_RESEARCHED,
            "style": {"no_em_dashes": bool(style["no_em_dashes"]),
                      "max_sentence_words": int(style["max_sentence_words"])},
            "remake_kinds": list(REMAKE_KINDS), "unverified_badge": UNVERIFIED_BADGE, "now": now_iso(),
        }

    def one(self, post_id):
        loc = self.locate(post_id)
        return self.describe(self.relint(loc.post), loc.path, seen_marks(read_history(loc.path)))

    # writing ---------------------------------------------------------------------------------
    def _save(self, loc):
        try:
            if _stamp(loc.path) != loc.stamp:
                raise Refusal("The batch file was changed by something else while this was being saved. "
                              "Nothing was saved. Reload the page to see the latest version.", 409, conflict=True)
            bak = loc.path + ".bak"
            if not os.path.exists(bak):
                shutil.copyfile(loc.path, bak)
            P.save_batch(loc.posts, loc.path, loc.meta)
        except OSError:
            raise Refusal("The batch file could not be saved (is it open in another program, or is the disk "
                          "full?). Nothing was changed.", 500)
        except ValueError as e:
            raise Refusal("The batch could not be saved: %s. Nothing was changed." % e, 500)

    def write(self, path, posts, meta, stamp):
        """Save a whole batch that was read with read(): same checks, same one-step replace."""
        self._save(Located(path, posts, meta, 0, stamp))

    def _entry(self, post, action, note, before):
        return {"post_id": post.id, "at": now_iso(), "action": action, "actor": ACTOR, "note": note,
                "rev": post.rev, "content_sha": P.approval_sha(post), "prev": before}

    def _check_rev(self, post, rev, loc):
        if rev != post.rev:
            fresh = self.describe(self.relint(post), loc.path, seen_marks(read_history(loc.path)))
            raise Refusal("This post was changed by something else after you opened it. Nothing was saved. "
                          "Here is the latest version.", 409, conflict=True, post=fresh)

    def change(self, post_id, rev, action, fn, note=""):
        """Find the post on disk, make sure it is the version the person was looking at, apply
        `fn(post, loc)`, bump `rev`, save in one step, and add a line to the history file."""
        with self.writing():
            loc = self.locate(post_id)
            post = loc.post
            self._check_rev(post, rev, loc)
            self._refuse_if_in_flight(post, loc, approving=(action == "approve"))
            before = {k: copy.deepcopy(getattr(post, k)) for k in _REMEMBERED}
            if fn(post, loc) is False:                       # nothing to do; leave the file alone
                return self.describe(self.relint(post), loc.path, seen_marks(read_history(loc.path)))
            self.relint(post)                                # what is saved is always freshly checked
            post.rev += 1
            self._save(loc)
            append_history(loc.path, self._entry(post, action, note, before))
            return self.describe(post, loc.path, seen_marks(read_history(loc.path)))

    # the actions -----------------------------------------------------------------------------
    def _refuse_if_locked(self, post):
        if post.status in LOCKED:
            raise Refusal("This post has already been %s, so it cannot be changed here. Ask Claude if it "
                          "really has to change." % post.status)

    def edit(self, post_id, rev, text=None, thread=None, alt_text=None, first_comment=None, media_order=None):
        """Change the words, or drop and reorder the media. `media_order` is a list of positions
        in the media list the person was shown (the page never sends a path), so this can remove
        and rearrange a post's own files and can never point the post at a new one."""
        for value, what in ((text, "The words"), (alt_text, "The alt text"), (first_comment, "The first comment")):
            if value is not None and not isinstance(value, str):
                raise Refusal("%s did not arrive as text. Nothing was changed." % what)
        if thread is not None and not (isinstance(thread, list) and all(isinstance(t, str) for t in thread)):
            raise Refusal("The thread did not arrive as a list of tweets. Nothing was changed.")

        def fn(post, _loc):
            self._refuse_if_locked(post)
            words_before = (post.text, list(post.thread), post.first_comment)
            shown_before = P.approval_sha(post)
            if media_order is not None:
                n = len(post.media_paths)
                if not (isinstance(media_order, list) and len(set(media_order)) == len(media_order)
                        and all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n
                                for i in media_order)):
                    raise Refusal("The new order of the images did not make sense. Nothing was changed.")
                post.media_paths = [post.media_paths[i] for i in media_order]
            if text is not None:
                post.text = text
            if thread is not None:
                post.thread = [t for t in thread if t.strip()]
            if alt_text is not None:
                post.alt_text = alt_text
            if first_comment is not None:
                post.first_comment = first_comment
            if P.approval_sha(post) == shown_before:
                return False
            if (post.text, list(post.thread), post.first_comment) != words_before:
                post.sourcing = "unverified"                  # new words: nobody has checked these facts
                post.facts_check = dict(post.facts_check or {}, words="unverified", words_sha="")
            self.relint(post)
            post.approved_at = ""                             # nobody has approved THIS version
            post.approved_text_sha = ""
            post.status = "draft" if post.lint_errors else "lint_pass"
            return True

        return self.change(post_id, rev, "edit", fn, note="edited on the review page")

    def approve(self, post_id, rev, content_sha, acknowledged=False):
        def fn(post, loc):
            if content_sha != P.approval_sha(post):
                fresh = self.describe(self.relint(post), loc.path, seen_marks(read_history(loc.path)))
                raise Refusal("This post is not the version you were shown. Nothing was approved. "
                              "Here is the latest version.", 409, conflict=True, post=fresh)
            code, why = self.approval_problem(post, acknowledged, batch_path=loc.path)
            if why:
                raise Refusal(why, 400, reason=code, needs_acknowledgement=(code == "needs-acknowledgement"),
                              problems=list(post.lint_errors) if code == "lint" else [])
            self._approve(post)
            return True

        return self.change(post_id, rev, "approve", fn,
                           note="approved" + (" (facts confirmed by the reviewer)" if acknowledged else ""))

    def reject(self, post_id, rev, note=""):
        def fn(post, _loc):
            self._refuse_if_locked(post)
            post.status = "rejected"
            post.feedback = note
            post.approved_at = ""
            post.approved_text_sha = ""
            return True

        return self.change(post_id, rev, "reject", fn, note=note)

    def remake(self, post_id, rev, note="", kind="words"):
        if kind not in REMAKE_KINDS:
            raise Refusal("A remake is for the words or for the image. '%s' is neither." % kind)

        def fn(post, _loc):
            self._refuse_if_locked(post)
            post.status = "regen_queued"
            post.feedback = ("[image] " if kind == "image" else "") + note
            post.approved_at = ""
            post.approved_text_sha = ""
            return True

        return self.change(post_id, rev, "remake", fn, note="[%s] %s" % (kind, note))

    def undo(self, post_id, rev):
        def fn(post, loc):
            self._refuse_if_locked(post)
            stack = []                    # replay: actions push, each earlier undo pops one
            for e in read_history(loc.path):
                if e.get("post_id") != post_id:
                    continue
                if e.get("action") == "undo":
                    if stack:
                        stack.pop()
                elif e.get("action") in UNDOABLE and isinstance(e.get("prev"), dict):
                    stack.append(e)
            if not stack:
                raise Refusal("There is nothing left to undo on this post.")
            for key, value in stack[-1]["prev"].items():
                if key in _REMEMBERED:
                    setattr(post, key, copy.deepcopy(value))
            self.relint(post)
            if post.status == "approved" and (post.lint_errors or not P.approval_is_current(post)):
                post.status = "draft" if post.lint_errors else "lint_pass"
                post.approved_at = ""
                post.approved_text_sha = ""
            return True

        return self.change(post_id, rev, "undo", fn, note="put back the way it was")

    def mark_seen(self, post_id, content_sha):
        """Remember that the person had this exact version in front of them. The batch file is not
        touched: this is a note in the history file, so it can never collide with a remake."""
        with self.lock:
            loc = self.locate(post_id)
            post = loc.post
            if content_sha != P.approval_sha(post):
                fresh = self.describe(self.relint(post), loc.path, seen_marks(read_history(loc.path)))
                raise Refusal("This post was changed after you opened it. Here is the latest version.",
                              409, conflict=True, post=fresh)
            marks = seen_marks(read_history(loc.path))
            if not (marks.get(post_id) and marks[post_id]["sha"] == content_sha):
                append_history(loc.path, {"post_id": post_id, "at": now_iso(), "action": "seen", "actor": ACTOR,
                                          "rev": post.rev, "content_sha": content_sha})
                marks = seen_marks(read_history(loc.path))
            return self.describe(self.relint(post), loc.path, marks)

    def approve_many(self, items):
        """Approve several posts in one go, and only the safe ones: seen by the person in exactly
        this version, clean, and with checked facts. Everything else is left alone with a reason."""
        approved, skipped = [], []
        with self.writing():
            loaded = [(path,) + tuple(self.read(path)) for path in self.files]
            where = {}
            for fi, (_path, posts, _meta, _st) in enumerate(loaded):
                for p in posts:
                    where[p.id] = (fi, p)
            marks = [seen_marks(read_history(path)) for path, _p, _m, _s in loaded]
            touched = {}
            for item in items:
                pid = str(item.get("id", "")) if isinstance(item, dict) else ""
                if pid not in where:
                    skipped.append({"id": pid, "reason": "it is not in this review"})
                    continue
                fi, post = where[pid]
                sha = P.approval_sha(post)
                if item.get("rev") != post.rev or item.get("content_sha") != sha:
                    skipped.append({"id": pid, "reason": "it changed after you opened it"})
                    continue
                if not (marks[fi].get(pid) and marks[fi][pid]["sha"] == sha):
                    skipped.append({"id": pid, "reason": "you have not looked at it yet"})
                    continue
                code, why = self.approval_problem(post, acknowledged=False, batch_path=loaded[fi][0])
                if why:
                    skipped.append({"id": pid, "reason": "its facts are unverified, so it has to be approved "
                                    "on its own" if code == "needs-acknowledgement" else why})
                    continue
                before = {k: copy.deepcopy(getattr(post, k)) for k in _REMEMBERED}
                self._approve(post)
                post.rev += 1
                approved.append(pid)
                touched.setdefault(fi, []).append(self._entry(post, "approve-all", "approved with others", before))
            for fi, lines in touched.items():
                path, posts, meta, stamp = loaded[fi]
                self._save(Located(path, posts, meta, 0, stamp))
                for line in lines:
                    append_history(path, line)
        return {"approved": approved, "skipped": skipped}

    # media -----------------------------------------------------------------------------------
    def media_file(self, post_id, index):
        """The real file behind one of a post's own media entries. There is no way to ask for a
        path: only 'entry number N of post X', and even that is checked against the brand folder."""
        loc = self.locate(post_id)
        paths = loc.post.media_paths
        if index < 0 or index >= len(paths):
            raise Refusal("That post has no media in position %d." % (index + 1), 404)
        real, problem = resolve_media(self.brand, paths[index])
        if problem == "outside":
            raise Refusal("That file is not inside this brand's folder, so it is not shown.", 403)
        if problem == "type":
            raise Refusal("That file is not an image, a video or a PDF, so it is not shown.", 415)
        if problem:
            raise Refusal("That file is missing: %s" % media_name(paths[index]), 404)
        return real
