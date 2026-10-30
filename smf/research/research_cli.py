"""research_cli.py - `factory.py research <job> --brand <id> ...`

Every job needs --brand: research is saved inside one brand's folder and there is no default.

Anything that costs money shows its estimate FIRST and then stops, unless --confirm is given.
So the way to use a paid job is always two steps: run it once to see the price, tell the person,
and run it again with --confirm only after they say yes. Five jobs are free and take no
--confirm, because they spend nothing: `actors` and `estimate` only look things up, `demand`
re-reads what is already saved, `video` runs on this computer, and `papers` uses free services.

What this prints is read by Claude, who then tells the person in plain words. Results are named
by where they sit inside the brand's folder.
"""
from __future__ import annotations

import argparse

from smf import brands
from smf.research import store
from smf.research.apify import Apify, ApifyError, REGISTRY_NAME

PAID = "Costs a little on Apify. Shows the price and stops, unless --confirm is given."
FREE = "Free."


def _parser():
    ap = argparse.ArgumentParser(prog="factory.py research", description="Find out what is working and what "
                                 "people are asking for. Every job needs --brand.")
    sub = ap.add_subparsers(dest="verb", metavar="<job>")

    def add(name, about, paid):
        p = sub.add_parser(name, help=about, description="%s %s" % (about, PAID if paid else FREE))
        p.add_argument("--brand", required=True, help="which brand this research is for (there is no default)")
        if paid:
            p.add_argument("--confirm", action="store_true", help="the person has seen the price and said yes")
            p.add_argument("--limit", type=int, help="the most to collect in this run")
        return p

    add("actors", "Check that every research tool still exists and still costs about what we expect.", False)

    p = add("estimate", "What would a job cost? Spends nothing.", False)
    p.add_argument("--job", required=True, help="a job name from the actor list, for example reddit_search")
    p.add_argument("--n", type=int, required=True, help="how many results, pages or videos")

    p = add("creator", "Study how a short-form creator's videos are built.", True)
    p.add_argument("--platform", choices=["instagram", "tiktok", "youtube"], default="instagram")
    p.add_argument("--handle", action="append", required=True, help="an account name; repeat for more than one")
    p.add_argument("--transcripts", action="store_true", help="a paid extra (Instagram only), priced separately")

    p = add("youtube", "What is working on YouTube now: a keyword's demand, or a channel's outliers.", True)
    p.add_argument("--keyword", action="append", help="check whether a topic is alive; repeat for more")
    p.add_argument("--channel", action="append", help="find a channel's outliers; repeat for more")
    p.add_argument("--within-days", type=int, help="with --keyword: only videos this recent")

    p = add("listen", "What an audience says in its own words on Reddit and X.", True)
    p.add_argument("--term", action="append", required=True, help="what to search for; repeat for more")
    p.add_argument("--source", action="append", choices=["reddit", "x"], help="default: both")
    p.add_argument("--community", help="Reddit only: stay inside one community")
    p.add_argument("--since", choices=["day", "week", "month", "year", "all"], help="Reddit only: how far back")

    p = add("demand", "Turn this brand's listening runs into a 'what people are asking for' report.", False)
    p.add_argument("--run", action="append", help="a listening folder inside the brand; default: the newest")
    p.add_argument("--latest", type=int, default=1, help="how many of the newest listening runs to combine")

    p = add("serp", "What Google shows for a list of questions or keywords.", True)
    p.add_argument("--query", action="append", required=True, help="a question or keyword; repeat for more")
    p.add_argument("--pages", type=int, default=1, help="results pages per query (1 is usually enough)")
    p.add_argument("--country", help="two-letter country code, for example us or gb")
    p.add_argument("--language", help="two-letter language code, for example en")

    p = add("video", "Mine one video (a link, or a file on this computer) for facts, numbers and lessons.", False)
    p.add_argument("--source", required=True, help="a web link, or the path to a video file")
    p.add_argument("--every", type=float, default=2.0, help="seconds between stills")
    p.add_argument("--keep-every-change", action="store_true",
                   help="for slide-heavy videos where numbers matter: keep every change, however small")
    p.add_argument("--opening-seconds", type=int, default=0, help="also save one still a second for the opening")
    p.add_argument("--no-transcript", action="store_true")
    p.add_argument("--language", help="the language spoken, for example en; default: detect it")

    p = add("papers", "Find published research on a question.", False)
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--since-year", type=int)
    p.add_argument("--contact-email", help="YOUR OWN email, only to widen the search for free copies. Optional.")
    return ap


def _finish(out):
    """Say what happened, the same way for every job."""
    if not out.get("ran"):
        print("Nothing was run and nothing was spent. If the person agrees to that cost, run this again with "
              "--confirm.")
        return 0
    print("Saved %d to the brand's folder: %s" % (out.get("count", 0), out["folder"]))
    print("Read summary.md in that folder first.")
    if out.get("partial"):
        print("NOTE: the run stopped early, so this is only part of what was asked for.")
    for w in out.get("warnings") or []:
        print("NOTE: %s" % w)
    return 0


def _actors(client):
    reports = client.health_all()
    bad = 0
    for r in reports:
        print("%-24s %-16s %s" % (r["job"], r["state"].upper() if r["state"] != "ok" else "ok", r["actor"] or ""))
        if r["state"] != "ok":
            bad += 1
            print("    %s" % r["detail"])
        elif r.get("live_usd_per_unit") is not None:
            print("    live price $%.5f, estimate $%.5f" % (r["live_usd_per_unit"], r["est_usd_per_unit"] or 0))
        else:
            print("    %s" % r["detail"])
    print("%d of %d research tools are fine.%s" % (len(reports) - bad, len(reports),
          "" if not bad else " The rest need attention in %s." % REGISTRY_NAME))
    return 1 if bad else 0


def cli_research(args):
    ap = _parser()
    if not args or args[0] in ("-h", "--help", "help"):
        ap.print_help()
        return 0
    a = ap.parse_args(args)
    try:
        brand = brands.load(a.brand)
        confirm = bool(getattr(a, "confirm", False))
        limit = getattr(a, "limit", None)

        if a.verb == "actors":
            return _actors(Apify())
        if a.verb == "estimate":
            print(Apify().estimate(a.job, a.n)["text"])
            return 0
        if a.verb == "creator":
            from smf.research import creator_study
            return _finish(creator_study.study(brand, a.handle, a.platform, limit, a.transcripts, confirm))
        if a.verb == "youtube":
            from smf.research import youtube_now
            if bool(a.keyword) == bool(a.channel):
                print("Give either --keyword (is a topic alive?) or --channel (which videos beat their channel?), "
                      "not both and not neither.")
                return 2
            if a.keyword:
                return _finish(youtube_now.search(brand, a.keyword, limit, a.within_days, confirm))
            return _finish(youtube_now.channels(brand, a.channel, limit, confirm))
        if a.verb == "listen":
            from smf.research import listen
            return _finish(listen.listen(brand, a.term, a.source or ("reddit", "x"), limit, a.community, a.since,
                                         confirm))
        if a.verb == "demand":
            from smf.research import demand_report
            return _finish(demand_report.report(brand, a.run, a.latest))
        if a.verb == "serp":
            from smf.research import serp
            return _finish(serp.search(brand, a.query, a.pages, a.country, a.language, confirm))
        if a.verb == "video":
            from smf.research import video_miner
            return _finish(video_miner.mine(brand, a.source, every=a.every,
                                            local_every=a.every if a.keep_every_change else video_miner.LOCAL_EVERY,
                                            opening_seconds=a.opening_seconds, language=a.language,
                                            transcript=not a.no_transcript))
        if a.verb == "papers":
            from smf.research import literature
            return _finish(literature.search(brand, a.query, a.limit, a.since_year, a.contact_email))
    except (brands.BrandError, store.ResearchError, ApifyError) as e:
        print(str(e))
        return 1
    ap.print_help()
    return 2
