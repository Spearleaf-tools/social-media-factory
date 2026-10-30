"""posting_cli.py - the posting verbs. Every one needs --brand, and every one is a dry run
unless --confirm is given.

    accounts   see what the scheduling service has; link a brand's identities to it by id
    schedule   send one approved batch through the gates and the ledger
    results    did it go out, and how did it do (only ever reads from the service); also records
               posts put up by hand and the numbers typed in for them, on this computer only
    shorts     plan one short a day from the brand's video inbox; send a saved shorts batch
    promote    the optional test-and-promote loop (does nothing unless the brand turned it on)

What "--confirm" means here: the connection to the scheduling service is built so that it CANNOT
write unless --confirm was given. Without it, an attempt to write is an error inside the
program, not a request that quietly goes out. `results` never gets a connection that can write.
"""
from __future__ import annotations

import argparse

from smf import brands
from smf.brands import BrandError
from smf.posting import accounts as A
from smf.posting import hand_posted as H
from smf.posting import promote as PR
from smf.posting import results as R
from smf.posting import send as SEND
from smf.posting import shorts as SH
from smf.posting.ledger import LedgerError
from smf.posting.provider import ProviderError
from smf.posting.state import StateError
from smf.studio.posts import DripError

PLAIN_ERRORS = (BrandError, SEND.SendError, LedgerError, StateError, ProviderError, A.AccountsError,
                R.ResultsError, SH.ShortsError, PR.PromoteError, DripError, H.HandPostedError)


def _run(work):
    try:
        return work()
    except PLAIN_ERRORS as e:
        print(str(e))
        return 1
    except Exception as e:
        # Never a traceback: it helps nobody who is not a programmer, and an error's own text can
        # quote a key. Only the kind of problem is named.
        print("This stopped because of a problem the Factory did not expect (%s). Nothing more was sent. Before "
              "trying again, run the results command for this brand to see what did go out." % type(e).__name__)
        return 1


def _parser(verb, about):
    ap = argparse.ArgumentParser(prog="factory.py %s" % verb, description=about)
    ap.add_argument("--brand", required=True, help="the brand id; there is no default brand")
    return ap


def _pairs(items, what):
    out = {}
    for item in items or []:
        name, sep, value = item.partition("=")
        if not sep or not name.strip() or not value.strip():
            raise A.AccountsError("Write %s as name=value, for example %s." % (what, "person=instagram,tiktok"))
        out[name.strip()] = value.strip()
    return out


# ----------------------------------------------------------------------------- accounts
def cli_accounts(args):
    ap = _parser("accounts", "See the scheduling service's accounts and link this brand to one by its id.")
    ap.add_argument("--provider-brand-id", help="the id of the account to link, from the list")
    ap.add_argument("--map", action="append", metavar="IDENTITY=PLATFORM,PLATFORM",
                    help="which identity posts on which platforms; repeat for each identity")
    ap.add_argument("--confirm", action="store_true", help="save the link into the brand's settings")
    a = ap.parse_args(args)

    def work():
        brand = brands.load(a.brand)
        provider = A.open_provider(brand, allow_writes=False)           # looking never needs to write
        listed = A.list_accounts(provider)
        print("Accounts this key can see (%d):" % len(listed))
        for row in A.overview(brand, listed):
            extra = ""
            if row["linked_here"]:
                extra += "   linked here as: " + ", ".join(row["linked_here"])
            if row["claimed_by_other_brands"]:
                extra += "   ALSO linked to another brand: " + ", ".join(row["claimed_by_other_brands"])
            print("  id %s  %s  [%s]%s" % (row["provider_brand_id"], row["label"],
                                          ", ".join(row["networks"]) or "nothing connected", extra))
        for c in A.connection_changes(brand, listed):
            print("  Note: the settings say %s as '%s' is %s, but the service says it is %s."
                  % (c["platform"], c["identity"], "connected" if c["settings_say"] else "not connected",
                     "connected" if c["service_says"] else "not connected"))
        for c in A.destination_changes(brand, listed):
            print("  Note: %s" % c["note"])
        if not a.provider_brand_id:
            print("To link one, pick it by its id. Names are never used, because names can look alike.")
            return 0
        mapping = {k: [p.strip() for p in v.split(",") if p.strip()] for k, v in _pairs(a.map, "--map").items()}
        entries = A.build_targets(brand, listed, a.provider_brand_id, mapping)
        print("This would be written into %s's settings:" % brand.name)
        for e in entries:
            print("  '%s' on %s -> account %s (%s)" % (e["identity"], e["platform"], e["provider_brand_id"],
                                                     "connected" if e["connected"] else "NOT connected yet"))
        if not a.confirm:
            print("Nothing was saved. Run this again with --confirm to save it.")
            return 0
        A.link(brand, entries)
        print("Saved.")
        return 0

    return _run(work)


# ----------------------------------------------------------------------------- schedule
def cli_schedule(args):
    ap = _parser("schedule", "Send one approved batch. A dry run unless --confirm is given.")
    ap.add_argument("--batch", required=True, help="the batch file to send")
    ap.add_argument("--limit", type=int, help="send only the first N posts that are ready (a small first run)")
    ap.add_argument("--confirm", action="store_true", help="really schedule the posts")
    a = ap.parse_args(args)

    def work():
        brand = brands.load(a.brand)
        provider = A.open_provider(brand, allow_writes=a.confirm)
        report = SEND.schedule_batch(brand, a.batch, provider, confirm=a.confirm, limit=a.limit)
        print(SEND.describe(report))
        bad = sum(report["counts"].get(k, 0) for k in ("failed", "unknown", "refused"))
        return 1 if bad else 0

    return _run(work)


# ----------------------------------------------------------------------------- results
def cli_results(args):
    ap = _parser("results", "Did it go out, and how did it do. Only ever reads from the scheduling service.")
    ap.add_argument("--days", type=int, default=30, help="how far back to look (default 30)")
    ap.add_argument("--only", choices=("reconcile", "health", "harvest", "summary"),
                    help="run one part instead of all four")
    ap.add_argument("--settle", metavar="POST_ID", help="settle one unclear send by hand, after looking at the "
                                                         "service's calendar yourself")
    ap.add_argument("--arrived", choices=("yes", "no"), help="with --settle: was the post on the calendar")
    ap.add_argument("--provider-post-id", default="", help="with --settle --arrived yes: the service's id for it")
    ap.add_argument("--by-hand", metavar="POST_ID", help="record that this post was put up by hand (needs --url)")
    ap.add_argument("--url", help="with --by-hand: the post's link, copied from the post itself")
    ap.add_argument("--when", help="with --by-hand: when it went up, YYYY-MM-DD HH:MM or just the date "
                                   "(default: its planned time)")
    ap.add_argument("--withdraw", metavar="POST_ID", help="take back a record of a post put up by hand")
    ap.add_argument("--numbers", metavar="POST_ID", help="save numbers for a post put up by hand: name=number ...")
    ap.add_argument("--numbers-sheet", nargs="?", const="", metavar="FILE",
                    help="write a sheet of posts put up by hand to fill in; with a FILE, read the filled sheet")
    ap.add_argument("--batch", help="with the options above: the batch file, when two batches share a post id")
    ap.add_argument("measures", nargs="*", metavar="NAME=NUMBER", help="with --numbers, e.g. views=1200 likes=40")
    ap.add_argument("--confirm", action="store_true",
                    help="needed for --settle and for saving anything about posts put up by hand")
    a = ap.parse_args(args)

    def by_hand(brand):
        # Posts put up by hand: everything stays on this computer, and no scheduling service is needed.
        if a.by_hand:
            if not a.url:
                print("Give the post's link with --url, copied from the post itself.")
                return 1
            out = H.mark_posted(brand, a.by_hand, a.url, a.when, batch=a.batch, confirm=a.confirm)
        elif a.withdraw:
            out = H.withdraw(brand, a.withdraw, batch=a.batch, confirm=a.confirm)
        elif a.numbers:
            out = H.save_numbers(brand, a.numbers, a.measures, batch=a.batch, confirm=a.confirm)
        elif a.numbers_sheet:
            out = H.read_sheet(brand, a.numbers_sheet, confirm=a.confirm)
        else:
            out = H.write_sheet(brand)
        print("\n".join(out["lines"]))
        return 0

    def work():
        brand = brands.load(a.brand)
        if a.measures and not a.numbers:
            print("Numbers like %s go with --numbers <post id>." % a.measures[0])
            return 1
        if a.by_hand or a.withdraw or a.numbers or a.numbers_sheet is not None:
            return by_hand(brand)
        if A.provider_name(brand) == "none" and a.only in (None, "summary"):
            print("%s posts by hand, with no scheduling service, so this shows what is saved on this computer."
                  % brand.name)
            print("\n".join(R.summary(brand, a.days)["lines"]))
            return 0
        if a.settle:
            if a.arrived is None:
                print("Say whether it was on the calendar: --arrived yes or --arrived no.")
                return 1
            if not a.confirm:
                print("This would mark '%s' as %s in this computer's posting record. Nothing was changed. Run it "
                      "again with --confirm." % (a.settle, "sent" if a.arrived == "yes" else "not sent"))
                return 0
            healed = R.settle_by_hand(brand, a.settle, a.arrived == "yes", a.provider_post_id)
            print("Settled. %d post(s) updated." % len(healed))
            return 0
        rc = 0
        if a.only == "summary":
            print("\n".join(R.summary(brand, a.days)["lines"]))
            return 0
        provider = A.open_provider(brand, allow_writes=False)           # results never writes to the service
        if a.only in (None, "reconcile"):
            rep = R.reconcile(brand, provider)
            print("Unclear sends: %d found on the calendar, %d were never there and can be sent again."
                  % (len(rep["found"]), len(rep["not_found"])))
            for post_id in rep["unclear"]:
                rc = 1
                print("  '%s' could not be told apart from another post. Look at the service's calendar, then "
                      "settle it with --settle." % post_id)
            # Say WHY each one is still open, rather than calling them all "too recent".
            if rep["too_soon"]:
                print("  %d send(s) are too recent to settle yet. Check again in a quarter of an hour."
                      % len(rep["too_soon"]))
            for item in rep["could_not_check"]:
                print("  '%s' could not be checked against the service's calendar this time, so it was left as it "
                      "is: %s" % (item["post_id"], item["why"]))
            named = set(rep["too_soon"]) | {item["post_id"] for item in rep["could_not_check"]}
            rest = [p for p in rep["still_waiting"] if p not in named]
            if rest:
                print("  %d send(s) are still waiting to be settled. Check again in a quarter of an hour."
                      % len(rest))
        if a.only in (None, "health"):
            health = R.publish_health(brand, provider, a.days)
            print(R.describe_health(health))
            rc = 1 if health["problems"] or health["could_not_check"] else rc
        if a.only in (None, "harvest"):
            got = R.harvest_metrics(brand, provider, a.days)
            print("Saved %d new result row(s); %d of them matched to a post the Factory sent."
                  % (got["new_rows"], got["linked"]))
            for err in got["errors"]:
                print("  Could not fetch: %s" % err)
        if a.only is None:
            print("\n".join(R.summary(brand, a.days)["lines"]))
        return rc

    return _run(work)


# ----------------------------------------------------------------------------- shorts
def _per_day(items):
    out = {}
    for platform, value in _pairs(items, "--per-day").items():
        if not value.isdigit():
            raise SH.ShortsError("Shorts per day must be a whole number, for example tiktok=3.")
        out[platform] = int(value)
    return out


def cli_shorts(args):
    ap = _parser("shorts", "Plan one short a day from the brand's video inbox. A preview unless --save.")
    ap.add_argument("--days", type=int, default=14, help="how many more days to plan per account (default 14)")
    ap.add_argument("--start", help="first day to use, like 2030-01-31 (default: tomorrow)")
    ap.add_argument("--per-day", action="append", metavar="PLATFORM=N", help="more than one a day, e.g. tiktok=3")
    ap.add_argument("--check-calendar", action="store_true",
                    help="also read the service's calendar for shorts booked from somewhere else")
    ap.add_argument("--save", action="store_true", help="write the plan as a batch for review, and book the days")
    ap.add_argument("--send", metavar="BATCH", help="send a saved, approved shorts batch (a dry run without --confirm)")
    ap.add_argument("--limit", type=int, help="with --send: only the first N ready posts")
    ap.add_argument("--confirm", action="store_true", help="with --send: really schedule the posts")
    a = ap.parse_args(args)

    def work():
        brand = brands.load(a.brand)
        if a.send:
            provider = A.open_provider(brand, allow_writes=a.confirm)
            report = SEND.schedule_batch(brand, a.send, provider, confirm=a.confirm, limit=a.limit)
            print(SEND.describe(report))
            return 1 if any(report["counts"].get(k) for k in ("failed", "unknown", "refused")) else 0
        provider = A.open_provider(brand, allow_writes=False) if a.check_calendar else None
        plan = SH.plan_shorts(brand, provider=provider, days=a.days, start=a.start, per_day=_per_day(a.per_day),
                              save=a.save)
        print(SH.describe(plan))
        if plan["saved"]:
            print("Saved as: %s" % plan["batch"])
        return 0

    return _run(work)


# ----------------------------------------------------------------------------- promote
def cli_promote(args):
    ap = _parser("promote", "The optional test-and-promote loop. Does nothing unless the brand turned it on.")
    ap.add_argument("--step", choices=("status", "test", "results", "decide", "winners"), default="status",
                    help="status (default), test = plan the test wave, results = show the numbers, "
                         "decide = pick winners, winners = plan the winners' promotion")
    ap.add_argument("--identity", help="which identity's TikTok the test runs on, when the brand has more than one")
    ap.add_argument("--clip", help="with decide or winners: only this clip")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--decide-with-what-we-have", action="store_true",
                    help="with decide: pick from the versions that have results, even if some never went out")
    ap.add_argument("--save", action="store_true", help="with test or winners: write the batch for review")
    ap.add_argument("--send", metavar="BATCH", help="send a saved, approved batch (a dry run without --confirm)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--confirm", action="store_true", help="with --send: really schedule the posts")
    a = ap.parse_args(args)

    def work():
        brand = brands.load(a.brand)
        if not PR.is_on(brand):
            print(PR._off(brand)["message"])
            return 0
        print(PR.WARNING)
        if a.send:
            provider = A.open_provider(brand, allow_writes=a.confirm)
            report = PR.send(brand, a.send, provider, confirm=a.confirm, limit=a.limit)
            print(SEND.describe(report))
            return 1 if any(report["counts"].get(k) for k in ("failed", "unknown", "refused")) else 0
        if a.step == "status":
            print("\n".join(PR.status(brand)["lines"][1:]))
        elif a.step == "test":
            plan = PR.plan_test_wave(brand, identity=a.identity, days=a.days, save=a.save)
            print("%s%d test day(s), %d post(s) on TikTok as '%s'."
                  % ("" if plan["saved"] else "PREVIEW: ", len(plan["waves"]), len(plan["posts"]), plan["identity"]))
            for wave in plan["waves"]:
                print("  %s  %s: %s" % (wave["day"], wave["clip"],
                                        ", ".join("%s %s" % (p["time"], p["video"]) for p in wave["posts"])))
            for d in plan["deferred"] + plan["needs_a_look"]:
                print("  '%s' was left out: %s." % (d["clip"], d["why"]))
            print("Saved as: %s" % plan["batch"] if plan["saved"] else "Nothing was saved or sent.")
        elif a.step == "results":
            for clip in PR.read_results(brand)["clips"]:
                print("%s (tested %s)" % (clip["clip"], clip["day"]))
                for v in clip["versions"]:
                    print("  %s: %s" % (v["version"], "%d views, %.2f per hour, %d saves, %d shares"
                                        % (v["views"], v["views_per_hour"], v["saves"], v["shares"])
                                        if v["measured"] else ("no results yet" if v["sent"] else "not scheduled yet")))
        elif a.step == "decide":
            clips = [a.clip] if a.clip else [c["clip"] for c in PR.read_results(brand)["clips"] if not c["winner"]]
            for key in clips:
                print(PR.describe_numbers(PR.pick_winner(brand, key, allow_partial=a.decide_with_what_we_have)))
            if not clips:
                print("No clip is waiting for a decision.")
        elif a.step == "winners":
            plan = PR.plan_promotion(brand, clip_key=a.clip, days=max(a.days, 30), save=a.save)
            print("%s%d post(s) to promote winners." % ("" if plan["saved"] else "PREVIEW: ", len(plan["posts"])))
            for p in plan["posts"]:
                print("  %s  %s as '%s'  %s" % (p.scheduled_time_local, p.platform, p.identity, p.topic_id))
            for item in plan["needs_description"]:
                print("  '%s' needs a description for %s before it can go there." % (item["clip"], item["platform"]))
            for item in plan["needs_a_look"]:
                print("  '%s' was left out: %s." % (item["clip"], item["why"]))
            for note in plan["notes"]:
                print("  " + note)
            print("Saved as: %s" % plan["batch"] if plan["saved"] else "Nothing was saved or sent.")
        return 0

    return _run(work)
