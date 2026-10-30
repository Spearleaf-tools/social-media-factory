"""ledger.py - the brand's memory of what was sent, written BEFORE anything is sent.

Why a ledger and not just a lock: a lock stops two runs from colliding, but it does nothing for
the run that dies at the worst moment. The service accepts a post, the computer loses power
before the result is saved, and the next run sends the same post again. So every send is a small
state machine, stored per brand under Client/<brand>/_state/:

    reserved  ->  sent  ->  confirmed          the normal path
    reserved  ->  failed                       the service definitely refused it: safe to retry
    reserved  ->  unknown                      nobody knows if it arrived: MUST be reconciled
                                               against the service's calendar before any retry

An operation's key is made from the brand, the account, and the exact words, media and time, so
"the same post" means the same thing on every run and on every computer.

Changing the words makes a new key, and that must never be a way round the record. So a post is
ALSO known by its id: while any send of a post id is unsettled (reserved or unknown), no other
version of that post may be reserved, and once a version has gone out from a batch, a changed
version of the same post from the same batch may not follow it.

The results check reads the service's calendar, which takes a while, and the record can move on
while it waits. So it never writes blind: every change it makes is "only if this send is still
exactly what I looked at" (`set_if`), decided inside the lock. And it only ever concludes "this
never arrived" from a calendar read at least NOT_FOUND_AFTER_SECONDS after the send, because a
calendar can lag behind a post it has already accepted.

If the ledger file cannot be read, everything stops. A damaged ledger is never treated as an
empty one, because an empty ledger says "nothing was ever sent".
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from smf.brands import replace_patiently

LEDGER_FILE = "posting-ledger.json"
LOCK_FILE = "posting-ledger.lock"
LOCK_STALE_SECONDS = 15 * 60
# How long after a send a calendar without the post starts to count as proof it never arrived.
# Sooner than this the send stays unknown and is looked at again by the next results check.
NOT_FOUND_AFTER_SECONDS = 15 * 60
ACTIVE = frozenset({"reserved", "unknown", "sent", "confirmed"})


class LedgerError(Exception):
    """Worded for the person. Raised instead of guessing."""


def _text_sha(text):
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def operation_key(post):
    basis = json.dumps([post.brand, post.identity, post.platform, post.text, list(post.thread),
                        list(post.media_paths), post.scheduled_time_iso], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def _version(op):
    """Everything that moves when a send moves on. Two reads with the same value saw the same send."""
    return (op.get("state"), op.get("attempt", 0), op.get("reserved_at_ts"), op.get("updated_at_ts"),
            op.get("provider_post_id") or "")


def standing(operations, post, batch="", now=None):
    """(code, operation): what the posting record says stands in the way of changing or sending
    this post, whatever its words are now. Reads only. The code is one of
        "sent"         exactly this version already went out
        "sending"      a run is sending it, or another version of it, right now
        "unsettled"    a send of it, or of another version of it, never got a clear answer
        "sent-before"  another version of it already went out from this same batch
    or (None, None) when nothing does."""
    now = time.time() if now is None else now
    key = operation_key(post)
    mine = operations.get(key)
    if mine and mine.get("state") in ("sent", "confirmed"):
        return "sent", mine
    same_post = [mine] if mine else []
    same_post += [op for k, op in sorted(operations.items()) if k != key and op.get("post_id") == post.id]
    for op in same_post:
        if op.get("state") == "unknown":
            return "unsettled", op
        if op.get("state") == "reserved":
            fresh = now - op.get("reserved_at_ts", 0) < LOCK_STALE_SECONDS
            return ("sending" if fresh else "unsettled"), op
    for op in same_post[1 if mine else 0:]:
        if op.get("state") in ("sent", "confirmed") and batch and op.get("batch") == batch:
            return "sent-before", op
    return None, None


class _Lock(object):
    """A lock file that works the same on Windows, Mac and Linux: creating a file that must not
    already exist is atomic everywhere. A lock older than LOCK_STALE_SECONDS whose owner is gone
    is taken over, so a crash cannot block posting forever."""

    def __init__(self, path, wait_seconds=30):
        self.path = path
        self.wait = wait_seconds
        self.fd = None

    def __enter__(self):
        deadline = time.time() + self.wait
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, ("%d %f" % (os.getpid(), time.time())).encode("ascii"))
                return self
            except PermissionError:
                # Windows says this while another run is deleting the lock file: wait, as for a lock
                # that is held. If it never clears, stop in plain words, never with a crash.
                if time.time() > deadline:
                    raise LedgerError("The posting lock for this brand could not be opened (permission denied). "
                                      "Nothing was sent. Close any other Social Media Factory run for this "
                                      "brand, then try again.")
                time.sleep(0.2)
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    continue                                   # it vanished between the two calls; try again
                if age > LOCK_STALE_SECONDS:
                    try:
                        os.unlink(self.path)
                    except OSError:
                        pass
                    continue
                if time.time() > deadline:
                    raise LedgerError("Another run is posting for this brand right now. Wait for it to finish, "
                                      "then try again.")
                time.sleep(0.2)

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                os.close(self.fd)
            os.unlink(self.path)
        except OSError:
            pass


Lock = _Lock      # public name: other per-brand state files use the same lock


class Ledger(object):
    def __init__(self, brand):
        self.brand_id = brand.id
        self.dir = brand.state_dir
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, LEDGER_FILE)
        self.lock_path = os.path.join(self.dir, LOCK_FILE)

    # ---------------------------------------------------------------- storage
    def _read(self):
        if not os.path.exists(self.path):
            return {"brand": self.brand_id, "operations": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise LedgerError("The record of what has been posted for this brand is damaged and cannot be read "
                              "(%s). Posting is stopped so nothing goes out twice. Ask Claude to repair it from "
                              "the service's calendar." % type(e).__name__)
        if not isinstance(data, dict) or not isinstance(data.get("operations"), dict):
            raise LedgerError("The record of what has been posted for this brand is not in the expected shape. "
                              "Posting is stopped so nothing goes out twice.")
        if data.get("brand") != self.brand_id:
            raise LedgerError("This posting record belongs to '%s', not '%s'. Posting is stopped."
                              % (data.get("brand"), self.brand_id))
        return data

    def _write(self, data):
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=self.dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        replace_patiently(tmp, self.path)

    def _update(self, fn):
        with _Lock(self.lock_path):
            data = self._read()
            result = fn(data)
            self._write(data)
            return result

    # ---------------------------------------------------------------- the state machine
    def get(self, key):
        return self._read()["operations"].get(key)

    def all(self):
        return dict(self._read()["operations"])

    def reserve(self, post, provider, provider_brand_id, batch=""):
        """Claim the right to send this exact post. Returns (key, None) when the caller may send,
        or (key, reason) when it must not: already sent, already being sent, or unresolved.
        `batch` is the name of the batch file the post came from; see the module notes."""
        key = operation_key(post)

        def fn(data):
            op = data["operations"].get(key)
            if op and op["state"] in ("sent", "confirmed"):
                return "it was already scheduled (%s)" % (op.get("provider_post_id") or "no id")
            if op and op["state"] == "unknown":
                return ("an earlier attempt may or may not have gone through. Run a results check first so "
                        "the Factory can look at the service's calendar before it tries again")
            if op and op["state"] == "reserved":
                if time.time() - op.get("reserved_at_ts", 0) < LOCK_STALE_SECONDS:
                    return "another run is sending it right now"
                op["state"] = "unknown"                        # a reservation nobody finished
                op["note"] = "a run stopped half way; treat as possibly sent"
                return ("an earlier run stopped half way through sending it. Run a results check first so the "
                        "Factory can look at the service's calendar before it tries again")
            # The same post under other words. New words make a new key, and that must not be a
            # way to send a post a second time while nobody knows what happened to the first.
            code, other = standing(data["operations"], post, batch)
            if code == "sending":
                return "another version of this post is being sent right now"
            if code == "unsettled":
                if other["state"] == "reserved":
                    other["state"] = "unknown"                 # a reservation nobody finished
                    other["note"] = "a run stopped half way; treat as possibly sent"
                return ("an earlier version of this post may or may not have gone out, and changing it does not "
                        "change that. Run a results check first (or settle it by hand) so the Factory can look at "
                        "the service's calendar. Sending it now could post it twice")
            if code == "sent-before":
                return ("an earlier version of this post already went out from this batch (the service calls it "
                        "%s). Sending the changed version would post it twice. If it really is a new post, give it "
                        "its own id" % (other.get("provider_post_id") or "no id"))
            data["operations"][key] = {
                "state": "reserved", "post_id": post.id, "identity": post.identity, "platform": post.platform,
                "provider": provider, "provider_brand_id": provider_brand_id, "provider_post_id": "",
                "scheduled_time_iso": post.scheduled_time_iso, "text_start": (post.text or "")[:80],
                "text_sha": _text_sha(post.text), "batch": batch, "attempt": (op or {}).get("attempt", 0) + 1,
                "reserved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "reserved_at_ts": time.time(), "note": ""}
            return None

        return key, self._update(fn)

    def _set(self, key, state, **extra):
        def fn(data):
            op = data["operations"].get(key)
            if not op:
                raise LedgerError("tried to update a send that was never reserved")
            op["state"] = state
            op.update(extra)
            op["updated_at"], op["updated_at_ts"] = time.strftime("%Y-%m-%d %H:%M:%S"), time.time()
        self._update(fn)

    def set_if(self, key, seen, state, **extra):
        """Change a send ONLY if it is still exactly the one `seen` showed (same state, same
        attempt, nothing written since). Decided inside the lock. Returns True when it changed.
        For anything that looked first and writes later: a results check, a person settling."""
        def fn(data):
            op = data["operations"].get(key)
            if not op or _version(op) != _version(seen):
                return False
            op["state"] = state
            op.update(extra)
            op["updated_at"], op["updated_at_ts"] = time.strftime("%Y-%m-%d %H:%M:%S"), time.time()
            return True
        return self._update(fn)

    def still_mine(self, key, seen):
        """Just before the request that cannot be taken back: is this reservation still the one
        this run made? If so its clock is started again, so nothing can call it abandoned while
        the request is in the air, and the fresh copy is returned. If a slow upload let another
        run or a results check write it off, returns None and the caller must not send."""
        def fn(data):
            op = data["operations"].get(key)
            if not op or op.get("state") != "reserved" or _version(op) != _version(seen):
                return None
            op["reserved_at_ts"] = time.time()
            return dict(op)
        return self._update(fn)

    def mark_sent(self, key, provider_post_id):
        self._set(key, "sent", provider_post_id=str(provider_post_id))

    def mark_failed(self, key, reason):
        self._set(key, "failed", note=reason[:300])

    def mark_unknown(self, key, reason):
        self._set(key, "unknown", note=reason[:300])

    def mark_confirmed(self, key, provider_post_id=None):
        extra = {"provider_post_id": str(provider_post_id)} if provider_post_id else {}
        self._set(key, "confirmed", **extra)

    def unresolved(self):
        return {k: v for k, v in self._read()["operations"].items() if v["state"] in ("unknown", "reserved")}

    # ---------------------------------------------------------------- reconciliation
    def reconcile(self, provider, timezone, window_hours=36, now=None):
        """Settle every 'unknown' (and abandoned 'reserved') send by looking at the service's own
        calendar. Found there -> sent. Not there, on a calendar read long enough after the send
        -> failed, and therefore safe to retry. Not there yet, but read too soon -> left alone.
        Read-only against the service. Every write is `set_if`: a send that moved on while the
        calendar was being read is left exactly as it is.
        A calendar that cannot be read, or that comes back in a shape this code does not know,
        is not evidence of anything: that send is left unknown and listed in "could_not_check".
        Returns {"found": [...], "not_found": [...], "too_soon": [...], "could_not_check": [...]}.
        `now` is for tests."""
        from datetime import datetime, timedelta
        from smf.posting.provider import ProviderError
        report = {"found": [], "not_found": [], "too_soon": [], "could_not_check": []}
        for key, op in sorted(self.unresolved().items()):
            asked_at = time.time() if now is None else now
            if op["state"] == "reserved" and asked_at - op.get("reserved_at_ts", 0) < LOCK_STALE_SECONDS:
                continue                                        # someone is genuinely mid-send
            try:
                when = datetime.fromisoformat(op["scheduled_time_iso"].replace("Z", "+00:00"))
            except ValueError:
                continue
            start = (when - timedelta(hours=window_hours)).strftime("%Y-%m-%dT%H:%M:%S")
            end = (when + timedelta(hours=window_hours)).strftime("%Y-%m-%dT%H:%M:%S")
            try:
                entries = provider.calendar(op["provider_brand_id"], start, end, timezone)
            except ProviderError as e:
                report["could_not_check"].append({"post_id": op["post_id"], "why": str(e)})
                continue                                        # still unknown, which is the honest answer
            # An entry that already belongs to another send is not evidence for this one. Two posts
            # to one account can open with the same words; without this, the post that never
            # arrived would be "found" as its neighbour and silently never go out.
            owned = {o.get("provider_post_id") for k, o in self._read()["operations"].items()
                     if k != key and o.get("provider_post_id") and o["state"] in ("sent", "confirmed")}
            on_network = [e for e in entries if e.get("id") not in owned and not e.get("draft")
                          and op["platform"][:4] in (e.get("network") or "")]
            exact = [e for e in on_network if op.get("text_sha") and _text_sha(e.get("text")) == op["text_sha"]]
            want = (op.get("text_start") or "").strip()
            loose = [e for e in on_network if want and (e.get("text") or "").strip().startswith(want[:60])]
            if exact:
                candidates = exact
            elif op.get("text_sha"):
                candidates = []                 # we know the exact words; a lookalike is not a match
            else:
                candidates = loose              # older records only remember how the text starts

            def distance(e):
                try:
                    there = datetime.fromisoformat(str(e.get("when", "")).replace("Z", "+00:00"))
                    return abs((there.replace(tzinfo=None) - when.replace(tzinfo=None)).total_seconds())
                except ValueError:
                    return float("inf")

            match = min(candidates, key=distance) if candidates else None
            sent_at = op.get("updated_at_ts") or op.get("reserved_at_ts") or 0
            if match:
                if self.set_if(key, op, "sent", provider_post_id=str(match["id"])):
                    report["found"].append(op["post_id"])
            elif asked_at - sent_at < NOT_FOUND_AFTER_SECONDS:
                report["too_soon"].append(op["post_id"])        # a calendar can lag; absence proves nothing yet
            elif self.set_if(key, op, "failed", note="not on the service's calendar; safe to send again"):
                report["not_found"].append(op["post_id"])
        return report
