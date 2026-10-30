"""send.py - the one road from an approved batch to the scheduling service.

    report = schedule_batch(brand, batch_path, provider)                  # a dry run: nothing is sent
    report = schedule_batch(brand, batch_path, provider, confirm=True)    # really schedules

Everything that posts (a batch of written posts, the daily shorts, the test-and-promote loop)
goes through this function, so there is exactly one set of gates and one ledger.

THE GATES, in order. A post is sent only when every one of them passes, and each says why not:
  1. status     the post is `approved`
  2. approval   what was approved is exactly what the post says now: the words, and what is
                INSIDE every picture and video (a file remade under the same name is a new file)
  3. copy       the copy check, re-run with THIS brand's rules, finds no errors
  4. time       the scheduled time is still in the future
  5. facts      the facts were checked, or the reviewer wrote down that they checked them
  6. media      every attached file exists, is inside this brand's folder, is cleared to publish
  7. account    this brand has this exact (identity, platform) account, it is connected, it has
                the service's id for it, no other brand on this computer claims that id, the key
                in use can really see it, and it still points at the same page or profile it
                pointed at when a person linked it

THE ORDER OF A REAL SEND (this is what makes a crash safe)
  claim -> upload media -> last look -> schedule -> mark sent -> save the batch
CLAIM: under the lock the review page also takes, the post is read from disk again, checked to be
the very version this run put through the gates, and reserved in the ledger. From then on the
review page refuses to change it, so "turn it down" can never race a send: whichever gets the
lock first wins, and the other one is told.
UPLOAD: each file is checked against the fingerprint the person approved, on the bytes that are
actually read for sending.
LAST LOOK: uploads can take a long time. Just before the one request that cannot be taken back,
the reservation is confirmed to still be this run's, the post is read from disk once more, and
the clock is checked again. If any of them says no, no scheduling request is made.

The reservation is written BEFORE anything leaves the computer. If the run dies half way, the
next run finds the reservation and refuses to send again until a results check has looked at the
service's own calendar. A refusal the service was clear about (`definitive`) is marked failed and
can simply be retried. Anything unclear is marked unknown, and the post is parked as `blocked`
with a note saying to run a results check. The batch is saved after EACH post, never at the end.
An outcome is only ever written onto the version that was sent: if something rewrote the post
while it was going out, the newer version is left as it is, with a note for the person.

A DRY RUN IS DRY
Without `confirm`, no upload and no schedule call is made at all, the ledger is only read, and
the batch file is not touched. The report says exactly what would be sent and to which account.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from smf import brands
from smf.brands import BrandError
from smf.posting import state as S
from smf.posting.ledger import Ledger, LedgerError, operation_key, standing
from smf.posting.provider import DryRunViolation, ProviderError
from smf.studio import posts as P
from smf.studio import proof
from smf.studio.lint import Rules
from smf.studio.review.store import ACKNOWLEDGED_NOTE, batch_lock, resolve_media

SENT_LOG = "sent-log.jsonl"
# The provider reads a whole file into memory to upload it. Past this size that stops being safe
# on an ordinary laptop, so the file is refused with a reason instead of tried.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
UNCLEAR_MARK = "Not sure whether this went out:"
UNCLEAR_NOTE = (UNCLEAR_MARK + " the scheduling service did not give a clear answer. Do not edit or re-approve "
                "this post. Run a results check: it looks at the service's own calendar, then either marks this "
                "post as scheduled or frees it to be sent again.")
ALREADY_OUT = frozenset({"scheduled", "posted", "exported"})


class SendError(Exception):
    """The whole run cannot go ahead. Worded for the person."""


# ----------------------------------------------------------------------------- small helpers
def _norm(text):
    return " ".join((text or "").split())


def text_sha(text):
    return hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()


def local_time(post, brand):
    """The post's time on the brand's own clock, for showing to a person."""
    try:
        when = datetime.fromisoformat((post.scheduled_time_iso or "").replace("Z", "+00:00"))
    except ValueError:
        return post.scheduled_time_local or ""
    if when.tzinfo is None:
        return when.strftime("%Y-%m-%d %H:%M")
    return when.astimezone(ZoneInfo(brand.timezone)).strftime("%Y-%m-%d %H:%M")


def can_write(provider):
    """True / False when the provider says whether it may write, None when it does not say."""
    transport = getattr(provider, "transport", None)
    allow = getattr(transport, "allow_writes", None)
    return None if allow is None else bool(allow)


def other_brand_claims(brand, provider_name):
    """{(platform, account id as text): [ids of OTHER brands on this computer that name it]}.
    One account belongs to one brand. Two brands naming it means one of them is wrong, and the
    cost of guessing which is a post on a stranger's page."""
    claims = {}
    for other_id in brands.list_brands():
        if other_id == brand.id:
            continue
        try:
            other = brands.load(other_id, allow_invalid=True)
        except BrandError:
            continue                                    # unreadable settings cannot claim anything
        accounts = other.data.get("accounts") or {}
        if not isinstance(accounts, dict) or (accounts.get("provider") or "none") != provider_name:
            continue
        for t in accounts.get("targets") or []:
            if isinstance(t, dict) and t.get("provider_brand_id") is not None:
                claims.setdefault((t.get("platform"), str(t.get("provider_brand_id"))), []).append(other_id)
    return claims


def live_accounts(provider):
    """{provider_brand_id as text: {network: what it points at}} straight from the service. A read.
    What a network points at is "" when the service does not say."""
    out = {}
    for a in provider.list_accounts():
        where = a.get("destinations") or {}
        out[str(a.get("provider_brand_id"))] = {n: str(where.get(n) or "") for n in (a.get("networks") or [])}
    return out


# ----------------------------------------------------------------------------- the gates
def resolve_target(brand, post, provider_name, live=None, claims=None):
    """(target, reasons). The exact account this post goes to, looked up in THIS brand's settings
    and nowhere else. `live` is the service's own account list when it could be read; `claims`
    is what other brands on this computer say they own (worked out here when not given)."""
    try:
        target = brand.target(post.identity, post.platform)
    except BrandError as e:
        return None, [str(e)]
    reasons = []
    pbid = target.get("provider_brand_id")
    if not isinstance(pbid, int) or isinstance(pbid, bool):
        reasons.append("the %s account for '%s' has not been matched to an account on the scheduling service yet. "
                       "Finish linking accounts in onboarding." % (post.platform, post.identity))
    if target.get("connected") is not True:
        reasons.append("the %s account for '%s' is not connected. Connect it in the scheduling service, then "
                       "link it again." % (post.platform, post.identity))
    if reasons:
        return target, reasons
    if claims is None:
        claims = other_brand_claims(brand, provider_name)
    claimed_by = sorted(set(claims.get((post.platform, str(pbid)), [])))
    if claimed_by:
        reasons.append("the same %s account is also linked to another brand on this computer (%s). One account "
                       "belongs to one brand. Fix the settings before anything is sent there."
                       % (post.platform, ", ".join(claimed_by)))
    if live is not None:
        networks = live.get(str(pbid))
        if networks is None:
            reasons.append("the key in use cannot see the account this brand is linked to, so it may be someone "
                           "else's. Link the accounts again.")
        elif post.platform not in networks:
            reasons.append("the scheduling service says %s is not connected for this brand right now. Reconnect "
                           "it there, then try again." % post.platform)
        elif networks[post.platform]:
            # The account's id stays the same when someone reconnects it to a different page, so
            # the id alone cannot show that these words would now land somewhere else.
            linked_to = str(target.get("destination") or "")
            if not linked_to:
                reasons.append("the link to this brand's %s account was saved before the Factory kept a note of "
                               "which page or profile it points at. Run the accounts step once more to confirm it, "
                               "then send again." % post.platform)
            elif linked_to != networks[post.platform]:
                reasons.append("the %s account this brand is linked to now points somewhere else on the scheduling "
                               "service (it was %s, it is now %s), so nothing was sent there. If that is right, run "
                               "the accounts step again to confirm it. If it is not, fix the connection in the "
                               "scheduling service." % (post.platform, linked_to, networks[post.platform]))
    return target, reasons


def media_checks(brand, post):
    """(real_paths, reasons) for every file riding on the post."""
    real_paths, reasons = [], []
    for raw in post.media_paths:
        name = os.path.basename(str(raw).replace("\\", "/")) or "a file"
        real, problem = resolve_media(brand, raw)
        if problem:
            reasons.append({"outside": "'%s' is not inside this brand's folder, so nobody has said it may be published",
                            "missing": "'%s' is not where the post says it is",
                            "type": "'%s' is not an image, a video or a PDF"}[problem] % name)
            continue
        blocked = proof.media_block_reason(brand, raw)
        if blocked:
            reasons.append("'%s' may not be published: %s" % (name, blocked))
            continue
        size = os.path.getsize(real)
        if size == 0:
            reasons.append("'%s' is an empty file" % name)
            continue
        if size > MAX_UPLOAD_BYTES:
            reasons.append("'%s' is too large to send from this computer (%d MB; the limit is %d MB). Upload it on "
                           "the platform itself." % (name, size // (1024 * 1024), MAX_UPLOAD_BYTES // (1024 * 1024)))
            continue
        real_paths.append(real)
    return real_paths, reasons


def gate(brand, post, rules, provider_name, live=None, now=None, claims=None):
    """(reasons, target, real_media_paths, media_digests). `reasons` is every reason this post may
    not be sent, as [(gate, sentence)] in gate order; an empty list means it may go. The digests
    are the fingerprints of the files as approved, one per path. Never changes the post."""
    if post.brand != brand.id:
        return [("status", "it belongs to %s, not to %s" % (post.brand, brand.id))], None, [], []
    if post.status in ALREADY_OUT:
        return [("status", "it has already been %s" % post.status)], None, [], []
    if post.status != "approved":
        if post.status == "blocked" and UNCLEAR_MARK in (post.feedback or ""):
            return [("status", "an earlier send of it was unclear. Run a results check first")], None, [], []
        return [("status", "it has not been approved (it is marked '%s')" % post.status)], None, [], []

    out = []
    digests = P.media_digests(post)
    approval = P.approval_state(post, digests)
    if approval != "current":
        out.append(("approval", "it " + P.APPROVAL_VOID_WORDS.get(approval, P.APPROVAL_VOID_WORDS["changed"])))
    probe = dataclasses.replace(post, lint_errors=[], lint_warnings=[])
    probe.lint(rules)
    errors = list(probe.lint_errors) + [f for f in P.media_findings(probe) if f.startswith("[ERROR]")]
    if not (post.text or "").strip():
        errors.insert(0, "[ERROR] no-words: it has no words. A post with no words cannot be found again on the "
                         "service's calendar if something goes wrong.")
    if errors:
        out.append(("copy", "the copy check found %d problem%s. The first: %s"
                    % (len(errors), "" if len(errors) == 1 else "s", errors[0])))
    late = P.future_time_problem(post, now=now)
    if late:
        out.append(("time", late))
    if post.sourcing == "blocked":
        out.append(("facts", "the fact check found something that does not match the brand's own material"))
    elif post.sourcing != "passed" and ACKNOWLEDGED_NOTE not in (post.feedback or ""):
        out.append(("facts", "its facts have not been checked, and nobody has confirmed they checked them. "
                             "Approve it again in the review page and tick the confirmation"))
    real_paths, media_reasons = media_checks(brand, post)
    out.extend(("media", r) for r in media_reasons)
    target, account_reasons = resolve_target(brand, post, provider_name, live, claims)
    out.extend(("account", r) for r in account_reasons)
    return out, target, real_paths, digests


# ----------------------------------------------------------------------------- one post, read again from disk
CHANGED_MEANWHILE = ("it was changed or turned down while this run was going, so it was not sent. Look at it on the "
                     "review page, then run this again")
CHANGED_WHILE_UPLOADING = ("it was changed or turned down while its files were uploading, so it was not sent. Look "
                           "at it on the review page, then run this again")
SLOT_PASSED = ("%s by the time its files had finished uploading, so it was not sent. Give it a new time, then run "
               "this again")
WRITTEN_OFF = ("its files took so long to upload that a results check or another run had already written this send "
               "off, so it was not sent. Run this again")
WENT_OUT_NOTE = ("An earlier version of this post was scheduled while this one was being changed (the scheduling "
                 "service calls it %s). This version has NOT been sent. If it should replace the earlier one, remove "
                 "that one on the scheduling service first.")
MAY_BE_OUT_NOTE = ("An earlier version of this post may have gone out while this one was being changed. Run a results "
                   "check before doing anything else with it.")


def _same_version(a, b):
    """Two copies of a post that would be the same send and show a reader the same thing."""
    return (operation_key(a) == operation_key(b)
            and (a.first_comment, a.alt_text, a.link) == (b.first_comment, b.alt_text, b.link))


def _still_the_approved_version(brand, batch_path, post):
    """Read the post from disk again: is it still approved, and still the version this run checked?"""
    try:
        posts, _meta = P.load_batch(batch_path, brand.id)
    except (OSError, ValueError, TypeError):
        return False
    fresh = next((p for p in posts if p.id == post.id), None)
    return bool(fresh and fresh.status == "approved" and fresh.approved_text_sha == post.approved_text_sha
                and _same_version(fresh, post))


def _claim(led, brand, batch_path, post, provider_name, pbid):
    """(key, refused). Reserve the post, but only if the copy on disk is still the approved
    version that went through the gates. Both happen under the lock the review page takes for
    every change, and once the reservation exists the review page refuses to touch the post. So
    a person turning a post down and a run sending it can never both win."""
    with batch_lock(batch_path):
        if not _still_the_approved_version(brand, batch_path, post):
            return None, CHANGED_MEANWHILE
        return led.reserve(post, provider_name, pbid, batch=os.path.basename(batch_path))


# ----------------------------------------------------------------------------- saving one post's outcome
def _save_post_outcome(brand, batch_path, sent, change, note_if_changed=""):
    """Re-read the batch, apply `change(post)` to the post that was `sent`, bump its `rev`, save in
    one step. Returns "saved", "missing" (the post is gone) or "changed".

    An outcome belongs to the version it happened to. If the post on disk is no longer the
    version that was sent (something rewrote it while it was going out), `change` is NOT applied:
    stamping "scheduled" onto words that were never sent would be a lie in both directions. The
    newer version is left as it is, apart from `note_if_changed` added to its notes so the person
    can see what happened. The posting record and the sent log keep the outcome under the
    version that really went.

    Runs under the lock the review page takes, and still checks that the file did not move
    between the read and the save, for the sake of tools that write a batch without the lock."""
    with batch_lock(batch_path):
        for _attempt in range(4):
            st = os.stat(batch_path)
            stamp = (st.st_mtime_ns, st.st_size)
            posts, meta = P.load_batch(batch_path, brand.id)
            target = next((p for p in posts if p.id == sent.id), None)
            if target is None:
                return "missing"
            same = _same_version(target, sent)
            if same:
                change(target)
            elif note_if_changed and note_if_changed not in (target.feedback or ""):
                target.feedback = ((target.feedback + " | ") if target.feedback else "") + note_if_changed
            else:
                return "changed"
            target.rev += 1
            st = os.stat(batch_path)
            if (st.st_mtime_ns, st.st_size) != stamp:
                continue
            P.save_batch(posts, batch_path, meta)
            return "saved" if same else "changed"
    raise SendError("The batch file kept changing while the result was being saved. The posting record is "
                    "correct; open the review page again to see the latest version.")


def strip_unclear_note(feedback):
    feedback = feedback or ""
    i = feedback.find(UNCLEAR_MARK)
    if i < 0:
        return feedback
    return feedback[:i].rstrip(" |")


def _receipt(brand, batch_path, post, key, provider_name, pbid, provider_post_id, digests=()):
    title = (post.text or "").splitlines()[0][:100] if post.text else ""
    return {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "brand": brand.id, "post_id": post.id, "operation": key,
            "identity": post.identity, "platform": post.platform, "provider": provider_name,
            "provider_brand_id": pbid, "provider_post_id": str(provider_post_id),
            "scheduled_time_iso": post.scheduled_time_iso, "text": post.text, "thread": list(post.thread),
            "text_sha256": text_sha(post.text), "title_sha256": text_sha(title),
            "media": [os.path.basename(str(m).replace("\\", "/")) for m in post.media_paths],
            "media_sha256": list(digests), "batch": os.path.basename(batch_path)}


def sent_log_path(brand):
    return os.path.join(brand.state_dir, SENT_LOG)


# ----------------------------------------------------------------------------- the run
def schedule_batch(brand, batch_path, provider, confirm=False, limit=None, now=None):
    """Send one brand's approved posts from one batch file. Returns a report; see the module notes.

    `provider` may be None for a dry run with no connection (the account is then checked against
    the brand's settings only). A real send needs a provider that is allowed to write."""
    if not isinstance(brand, brands.Brand):
        raise BrandError("no brand was named. Say which brand this is for. Brands here: %s"
                         % (", ".join(brands.list_brands()) or "none yet"))
    configured = (brand.data.get("accounts") or {}).get("provider") or "none"
    if configured == "none":
        raise SendError("%s is not set up to post through a scheduling service. Link its accounts in onboarding, "
                        "or save a ready-to-post folder instead." % brand.name)
    if provider is not None and provider.name != configured:
        raise SendError("%s is set up to post through %s, but this run was started with %s. Nothing was sent."
                        % (brand.name, configured, provider.name))
    if confirm:
        if provider is None:
            raise SendError("A real send needs a connection to the scheduling service. Nothing was sent.")
        if can_write(provider) is False:
            raise SendError("This run was set up as a dry run, so it may not send anything. Nothing was sent.")
    if not os.path.isfile(batch_path):
        raise SendError("That batch file could not be found. Nothing was sent.")
    try:
        posts, _meta = P.load_batch(batch_path, brand.id)
    except ValueError as e:
        raise SendError("%s Nothing was sent." % str(e).rstrip("."))
    except OSError:
        raise SendError("That batch file could not be opened. Nothing was sent.")

    led = Ledger(brand)
    operations = led.all()                  # a damaged record stops the run here, before anything is sent
    rules = Rules.for_brand(brand)
    claims = other_brand_claims(brand, configured)

    notes, live = [], None
    if provider is not None:
        try:
            live = live_accounts(provider)
        except ProviderError as e:
            if confirm:
                raise SendError("The scheduling service could not be reached to check the accounts, so nothing "
                                "was sent. %s" % e)
            notes.append("The scheduling service could not be reached, so the accounts were checked against "
                         "this brand's settings only. %s" % e)
    unresolved = [op for op in operations.values() if op.get("state") in ("unknown", "reserved")]
    if unresolved:
        notes.append("%d earlier send%s never got a clear answer. Run a results check so the Factory can look "
                     "at the service's calendar." % (len(unresolved), "" if len(unresolved) == 1 else "s"))

    report = {"brand": brand.id, "batch": os.path.basename(batch_path), "dry_run": not confirm, "posts": [],
              "notes": notes, "counts": {}}
    uploaded = {}                                       # (file, account id, fingerprint) -> hosted link, once per run
    batch_name = os.path.basename(batch_path)
    sendable = 0
    for post in posts:
        row = {"id": post.id, "identity": post.identity, "platform": post.platform, "outcome": "",
               "reasons": [], "gates": [], "provider_brand_id": None, "when": local_time(post, brand),
               "text": post.text, "thread": list(post.thread), "media": [], "provider_post_id": "",
               "request": None}
        report["posts"].append(row)
        key = operation_key(post)
        if post.status == "blocked" and UNCLEAR_MARK in (post.feedback or ""):
            # Parked after an unclear send. The posting record decides what happens next: a results
            # check has either found it on the service's calendar, or freed it to be sent again.
            op = (led.get(key) if confirm else operations.get(key)) or {}
            if op.get("state") in ("sent", "confirmed"):
                ppid = op.get("provider_post_id") or ""
                if confirm:
                    _save_post_outcome(brand, batch_path, post, lambda p, ppid=ppid: _mark_scheduled(p, ppid))
                row["outcome"], row["provider_post_id"] = "already-sent", ppid
                row["reasons"] = ["the results check found it on the service's calendar"]
                continue
            if op.get("state") == "failed":
                if confirm:
                    _save_post_outcome(brand, batch_path, post, free_for_retry)
                post = dataclasses.replace(post)
                free_for_retry(post)
        reasons, target, real_paths, digests = gate(brand, post, rules, configured, live, now, claims)
        if reasons:
            row["outcome"] = "skipped" if post.status in ALREADY_OUT else "blocked"
            row["gates"] = [g for g, _r in reasons]
            row["reasons"] = [r for _g, r in reasons]
            continue
        pbid = target["provider_brand_id"]
        row["provider_brand_id"] = pbid
        row["media"] = [os.path.basename(p) for p in real_paths]

        if limit is not None and sendable >= limit:
            row["outcome"] = "held"
            row["reasons"] = ["left for the next run (this run was limited to %d)" % limit]
            continue

        if not confirm:
            op = operations.get(key)
            if op and op.get("state") in ("sent", "confirmed"):
                row["outcome"] = "already-sent"
                row["provider_post_id"] = op.get("provider_post_id") or ""
                row["reasons"] = ["the posting record says it was already scheduled"]
                continue
            if op and op.get("state") in ("unknown", "reserved"):
                row["outcome"] = "refused"
                row["reasons"] = ["an earlier send of it never got a clear answer. Run a results check first"]
                continue
            in_the_way, _op = standing(operations, post, batch_name)
            if in_the_way:                              # the same post under other words
                row["outcome"] = "refused"
                row["reasons"] = [{"sent-before": "an earlier version of it already went out from this batch, so "
                                                  "sending this one would post it twice"}.get(
                    in_the_way, "an earlier version of it never got a clear answer. Run a results check first")]
                continue
            build = getattr(provider, "build_body", None)
            if build is not None:
                try:
                    row["request"] = build(post, ["(%s, uploaded at send time)" % n for n in row["media"]],
                                           brand.timezone)
                except ProviderError as e:
                    row["outcome"], row["gates"], row["reasons"] = "blocked", ["account"], [str(e)]
                    continue
            row["outcome"] = "would-send"
            sendable += 1
            continue

        # ---- a real send: the reservation is written before anything leaves this computer
        claimed, refused = _claim(led, brand, batch_path, post, provider.name, pbid)
        if claimed is None:                             # the post on disk is no longer what the gates checked
            row["outcome"], row["gates"], row["reasons"] = "blocked", ["approval"], [refused]
            continue
        key = claimed
        if refused:
            op = led.get(key) or {}
            if op.get("state") in ("sent", "confirmed"):
                ppid = op.get("provider_post_id") or ""
                _save_post_outcome(brand, batch_path, post, lambda p, ppid=ppid: _mark_scheduled(p, ppid))
                row["outcome"], row["provider_post_id"] = "already-sent", ppid
            else:
                row["outcome"] = "refused"
            row["reasons"] = ["not sent: " + refused]
            continue
        sendable += 1
        reservation = led.get(key)
        try:
            links = []
            for path, digest in zip(real_paths, digests):
                if (path, pbid, digest) not in uploaded:    # the bytes read for sending are checked against `digest`
                    uploaded[(path, pbid, digest)] = provider.upload(path, pbid, expect_sha256=digest)
                links.append(uploaded[(path, pbid, digest)])
        except DryRunViolation:
            led.mark_failed(key, "the run was not allowed to send")
            raise SendError("This run was set up as a dry run, so it may not send anything. Nothing was sent.")
        except Exception as e:                          # no post exists yet, so this one is certain
            why = str(e) if isinstance(e, ProviderError) else "a file could not be uploaded (%s)" % type(e).__name__
            led.set_if(key, reservation, "failed", note=why[:300])
            if getattr(e, "kind", "") == "media-changed":
                row["gates"] = ["approval"]
                why += ", so it was not uploaded and the post was not sent. Look at it on the review page and " \
                       "approve it again"
            else:
                why += ". It is still approved, so the next run tries again"
            row["outcome"], row["reasons"] = "failed", [why + "."]
            continue

        # ---- the last look. Uploads can take a long time, and the next request cannot be taken back.
        reservation = led.still_mine(key, reservation)
        if reservation is None:
            row["outcome"], row["reasons"] = "failed", [WRITTEN_OFF + "."]
            continue
        stop = None
        if not _still_the_approved_version(brand, batch_path, post):
            stop, row["gates"] = CHANGED_WHILE_UPLOADING, ["approval"]
        else:
            late = P.future_time_problem(post, now=now)
            if late:
                stop, row["gates"] = SLOT_PASSED % late, ["time"]
        if stop:                                        # released as failed-before-send: no request was made
            led.set_if(key, reservation, "failed", note=("not sent: " + stop)[:300])
            row["outcome"], row["reasons"] = "failed", [stop + "."]
            continue
        try:
            ppid = provider.schedule(post, pbid, links, brand.timezone)
        except ProviderError as e:
            if e.definitive:
                led.mark_failed(key, str(e))
                row["outcome"] = "failed"
                row["reasons"] = ["the service refused it: %s It is still approved, so fix the cause and run this "
                                  "again." % e]
            else:
                _park_as_unclear(led, key, brand, batch_path, post, row, str(e))
            continue
        except DryRunViolation:
            led.mark_failed(key, "the run was not allowed to send")
            raise SendError("This run was set up as a dry run, so it may not send anything. Nothing was sent.")
        except Exception as e:                          # the request may have left: nobody knows
            _park_as_unclear(led, key, brand, batch_path, post, row,
                             "something unexpected happened while sending (%s)" % type(e).__name__)
            continue
        led.mark_sent(key, ppid)
        S.append_lines(sent_log_path(brand),
                       [_receipt(brand, batch_path, post, key, provider.name, pbid, ppid, digests)])
        saved = _save_post_outcome(brand, batch_path, post, lambda p, ppid=ppid: _mark_scheduled(p, ppid),
                                   note_if_changed=WENT_OUT_NOTE % ppid)
        row["outcome"], row["provider_post_id"] = "sent", str(ppid)
        if saved == "changed":
            row["reasons"] = ["it went out as it was approved, but something changed the post while it was being "
                              "sent. The newer version was left alone and has NOT been sent; there is a note on it"]

    counts = {}
    for row in report["posts"]:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    report["counts"] = counts
    report["writes"] = getattr(getattr(provider, "transport", None), "writes", 0)
    return report


def free_for_retry(post):
    """A parked post whose earlier send is now known NOT to have arrived: approved again, as long
    as what was approved is still exactly what it says."""
    post.feedback = strip_unclear_note(post.feedback)
    post.status = "approved" if P.approval_is_current(post) else "lint_pass"


def _mark_scheduled(post, provider_post_id):
    post.status = "scheduled"
    post.provider_post_id = str(provider_post_id)
    post.feedback = strip_unclear_note(post.feedback)


def _park_as_unclear(led, key, brand, batch_path, post, row, why):
    led.mark_unknown(key, why)

    def change(p):
        p.status = "blocked"
        kept = strip_unclear_note(p.feedback)
        p.feedback = (kept + " | " if kept else "") + UNCLEAR_NOTE

    _save_post_outcome(brand, batch_path, post, change, note_if_changed=MAY_BE_OUT_NOTE)
    row["outcome"] = "unknown"
    row["reasons"] = ["nobody knows whether it went out (%s). It will not be sent again until a results check has "
                      "looked at the service's calendar." % why.rstrip(".")]


# ----------------------------------------------------------------------------- saying it plainly
def describe(report):
    """The report as sentences a person can act on."""
    c = report["counts"]
    lines = []
    if report["dry_run"]:
        lines.append("DRY RUN for %s. Nothing was sent." % report["brand"])
        lines.append("%d post(s) would be scheduled." % c.get("would-send", 0))
    else:
        lines.append("%d post(s) scheduled for %s." % (c.get("sent", 0), report["brand"]))
    for row in report["posts"]:
        if row["outcome"] in ("would-send", "sent"):
            lines.append("  %s  %s as '%s' (account %s)  %s%s"
                         % (row["when"], row["platform"], row["identity"], row["provider_brand_id"],
                            _first_words(row["text"]),
                            "  + %s" % ", ".join(row["media"]) if row["media"] else ""))
    waiting = [r for r in report["posts"] if r["outcome"] == "blocked" and r["gates"] == ["status"]]
    stopped = [r for r in report["posts"] if r["outcome"] in ("blocked", "failed", "unknown", "refused")
               and r not in waiting]
    if stopped:
        lines.append("%d post(s) were NOT sent:" % len(stopped))
        for row in stopped:
            lines.append("  %s (%s as '%s'): %s" % (row["id"], row["platform"], row["identity"],
                                                   "; ".join(row["reasons"])))
    if waiting:
        lines.append("%d post(s) are not approved yet and were left alone." % len(waiting))
    for key, words in (("already-sent", "were already scheduled earlier"), ("skipped", "had already gone out"),
                       ("held", "were left for the next run")):
        if c.get(key):
            lines.append("%d post(s) %s." % (c[key], words))
    lines.extend(report["notes"])
    if report["dry_run"] and c.get("would-send"):
        lines.append("To really schedule them, run this again with --confirm.")
    return "\n".join(lines)


def _first_words(text, n=60):
    flat = _norm(text)
    return '"%s%s"' % (flat[:n], "..." if len(flat) > n else "")


__all__ = ["schedule_batch", "describe", "gate", "free_for_retry", "SendError", "LedgerError", "UNCLEAR_MARK", "UNCLEAR_NOTE",
           "MAX_UPLOAD_BYTES", "sent_log_path", "text_sha", "strip_unclear_note", "live_accounts"]
