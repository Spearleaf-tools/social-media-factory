"""listen.py - what an audience says in its own words, on Reddit and X.

The point of listening is vocabulary and demand. Not "what should we say" but "what do they ask,
what annoys them, and which exact phrases do they reach for". A post that answers a real question
in the asker's own vocabulary does not need a clever hook.

What this tool does to the posts it fetches, all in plain Python with no model involved:

  sort by kind     question / complaint / request, by simple readable word rules (see KINDS).
                   A post can be more than one kind. The rules are deliberately dumb and visible:
                   they are a first sort for a person to correct, not a judgement.
  find phrases     two-to-four word phrases, counted by HOW MANY DIFFERENT POSTS use them, not
                   how many times one person repeats them.
  group by theme   keyword clustering, described below.

HOW THE GROUPING WORKS (and why it always gives the same answer)
  1. Each post becomes a set of terms: its words, and pairs of words used close together, minus
     filler words and minus the search words themselves (every post contains those, so they
     separate nothing). A pair counts in either order: "dense crumb" and "the crumb is so dense"
     are one term, named the way most people wrote it.
  2. Each term is counted by how many posts contain it.
  3. Terms are tried as theme anchors in a fixed order: most posts first; on a tie a pair goes
     before a single word (it covers just as many posts and says more); then alphabetical. A
     total order, so nothing is left to chance.
  4. An anchor claims every post that contains it and is not yet claimed. If that is at least
     MIN_THEME posts, they become a theme named after the anchor. Otherwise the anchor is skipped.
  5. Whatever is left is filed under "everything else".
Posts are sorted by id first, so the same posts always produce the same themes in the same order,
on any computer. There is no randomness and no model: a person can follow every step by hand.

Privacy: author names are not kept. A quote is cited by its link.
"""
from __future__ import annotations

import os
import re

from smf.research import numbers, store
from smf.research.apify import Apify, money

SOURCES = {"reddit": "reddit_search", "x": "x_search"}
MIN_THEME = 3
MAX_THEMES = 12
QUOTE_CHARS = 280
QUOTES_PER_THEME = 4
NEAR = 2                    # two words this close together (filler removed) count as a pair

STOP = frozenset("""
a about above after again against all also am an and any are aren as at be because been before being below
between both but by can cannot could couldn did didn do does doesn doing don down during each even ever every few
for from further get gets getting go going got had hadn has hasn have haven having he her here hers herself him
himself his how however i if in into is isn it its itself just know let like ll make makes many may me might more
most much must my myself need no nor not now of off on once one only or other our ours ourselves out over own
people really re s said same say says see seem shall she should shouldn so some something still such t take than
that the their theirs them themselves then there these they thing things think this those though through to too
under until up us use used using ve very want was wasn way we well were weren what when where which while who
whom why will with without won would wouldn yes yet you your yours yourself yourselves anyone someone everyone
been amp http https www com im ive dont cant
""".split())

KINDS = {
    "question": {
        "starts": ("how ", "what ", "why ", "where ", "which ", "who ", "when ", "can ", "could ", "should ",
                   "is there", "are there", "does ", "do ", "did ", "has anyone", "anyone ", "any "),
        "contains": ("?",),
    },
    "complaint": {
        "contains": ("frustrat", "annoy", "hate ", "tired of", "sick of", "fed up", "waste of", "disappoint",
                     "struggl", "doesn't work", "doesnt work", "does not work", "not working", "stopped working",
                     "too expensive", "overpriced", "rip off", "ripoff", "terrible", "awful", "useless",
                     "gave up", "giving up", "can't figure", "cant figure", "confusing", "keeps failing",
                     "never works", "worst", "nightmare"),
    },
    "request": {
        "contains": ("i wish", "wish there", "wish i", "looking for", "recommend", "suggestion", "alternative to",
                     "is there a way", "is there an app", "is there a tool", "need help", "need a ", "need an ",
                     "any advice", "any tips", "where can i", "how do i find", "best way to", "would love",
                     "if only"),
    },
}


# ----------------------------------------------------------------------------- text
def tokens(text):
    """Lowercase words, accents kept, filler dropped, plain plurals folded (loaves stays loaves)."""
    out = []
    for w in re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", str(text or "").lower(), re.UNICODE):
        w = w.replace("’", "'").split("'")[0]
        if len(w) < 3 or w in STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
            w = w[:-1]
        out.append(w)
    return out


def terms_of(text, ignore):
    """The terms in one post, as {term: how it was written}. A term is a single word, or a PAIR of words
    used close together. A pair is the same pair in either order, because people say both "dense crumb"
    and "the crumb is so dense" and mean one thing; how it was written is kept so a theme can be named
    the way most people actually put it."""
    toks = [t for t in tokens(text) if t not in ignore]
    found = {t: t for t in toks}
    for i, a in enumerate(toks):
        for b in toks[i + 1:i + 1 + NEAR]:
            if a != b:
                found.setdefault(" ".join(sorted((a, b))), "%s %s" % (a, b))
    return found


def kinds_of(text):
    t = " " + re.sub(r"\s+", " ", str(text or "").lower()).strip() + " "
    head = t.strip()
    found = []
    for kind in ("question", "complaint", "request"):
        rule = KINDS[kind]
        if any(head.startswith(s) for s in rule.get("starts", ())) or any(c in t for c in rule.get("contains", ())):
            found.append(kind)
    return found


def phrases(posts, ignore, top=25):
    """Two-to-four word phrases, ranked by how many DIFFERENT posts use them."""
    seen = {}
    for p in posts:
        words = [w for w in re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", p["text"].lower(), re.UNICODE)]
        mine = set()
        for n in (2, 3, 4):
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                if gram[0] in STOP or gram[-1] in STOP or all(w in ignore for w in gram):
                    continue
                mine.add(" ".join(gram))
        for g in mine:
            seen[g] = seen.get(g, 0) + 1
    ranked = sorted(((g, n) for g, n in seen.items() if n >= 2), key=lambda kv: (-kv[1], -len(kv[0].split()), kv[0]))
    kept = []
    for g, n in ranked:                                   # drop a phrase that is only part of a kept longer one
        if any(g in longer and n <= m for longer, m in kept):
            continue
        kept.append((g, n))
        if len(kept) >= top:
            break
    return [{"phrase": g, "posts": n} for g, n in kept]


# ----------------------------------------------------------------------------- clustering
def cluster(posts, query_terms, min_theme=MIN_THEME, max_themes=MAX_THEMES):
    """Deterministic keyword clustering. See the module docstring for the five steps."""
    ignore = set()
    for q in query_terms:
        ignore.update(tokens(q))
    posts = sorted(posts, key=lambda p: (str(p.get("id") or ""), str(p.get("url") or "")))
    bags = [terms_of(p["text"], ignore) for p in posts]

    df = {}
    for bag in bags:
        for term in bag:
            df[term] = df.get(term, 0) + 1
    anchors = sorted((t for t, n in df.items() if n >= min_theme),
                     key=lambda t: (-df[t], -t.count(" "), t))

    claimed, themes = [False] * len(posts), []
    for anchor in anchors:
        if len(themes) >= max_themes:
            break
        members = [i for i, bag in enumerate(bags) if not claimed[i] and anchor in bag]
        if len(members) < min_theme:
            continue
        for i in members:
            claimed[i] = True
        written = {}
        for i in members:                                     # name it the way most of these posts wrote it
            written[bags[i][anchor]] = written.get(bags[i][anchor], 0) + 1
        label = sorted(written.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        themes.append(_theme(label, [posts[i] for i in members], [bags[i] for i in members], len(themes) + 1))
    rest = [i for i, c in enumerate(claimed) if not c]
    if rest:
        other = _theme("everything else", [posts[i] for i in rest], [bags[i] for i in rest], len(themes) + 1)
        other["id"] = "other"
        themes.append(other)
    return themes


def _theme(label, members, bags, n):
    mine = set(label.split())
    also = {}
    for bag in bags:
        for key, written in bag.items():
            if not (set(key.split()) & mine):                 # skip anything that just repeats the theme's own words
                also.setdefault(key, [0, written])[0] += 1
    near, covered = [], set()
    for key, (count, written) in sorted(also.items(), key=lambda kv: (-kv[1][0], -kv[0].count(" "), kv[0])):
        words = set(key.split())
        if count < 2 or words <= covered:                     # "keep alive" already says "keep" and "alive"
            continue
        near.append(written)
        covered |= words
        if len(near) >= 5:
            break
    by_kind = {k: sum(1 for p in members if k in p["kinds"]) for k in ("question", "complaint", "request")}
    by_source = {}
    for p in members:
        by_source[p["source"]] = by_source.get(p["source"], 0) + 1
    best = sorted(members, key=lambda p: (-(p.get("score") or 0), str(p.get("id") or "")))
    return {"id": "t%02d" % n, "label": label, "also_mentions": near, "posts": len(members), "kinds": by_kind,
            "sources": by_source, "reaction": int(sum((p.get("score") or 0) for p in members)),
            "quotes": [{"text": _clip(p["text"]), "url": p.get("url"), "source": p["source"], "kinds": p["kinds"],
                        "score": p.get("score") or 0} for p in best[:QUOTES_PER_THEME]],
            "post_ids": [p.get("id") for p in members]}


def _clip(text):
    one = re.sub(r"\s+", " ", str(text or "")).strip()
    return one if len(one) <= QUOTE_CHARS else one[:QUOTE_CHARS - 1].rstrip() + "…"


# ----------------------------------------------------------------------------- the job
def tidy(items, source):
    """Normalised actor rows -> the one shape the rest of this file works on."""
    out = []
    for it in items:
        if it.get("is_repost"):
            continue
        title, body = str(it.get("title") or "").strip(), str(it.get("body") or "").strip()
        text = (title + ". " + body).strip(". ") if title and body else (title or body)
        if len(text) < 12:
            continue
        out.append({"id": "%s:%s" % (source, it.get("id") or it.get("url")), "source": source, "url": it.get("url"),
                    "community": it.get("community"), "text": text, "posted_at": it.get("posted_at"),
                    "score": int(numbers.to_number(it.get("score")) or 0),
                    "replies": int(numbers.to_number(it.get("replies")) or 0), "kinds": kinds_of(text)})
    return out


def analyse(posts, query_terms):
    seen, unique = set(), []
    for p in sorted(posts, key=lambda p: str(p["id"])):
        key = re.sub(r"\W+", " ", p["text"].lower()).strip()[:160]
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    ignore = set()
    for q in query_terms:
        ignore.update(tokens(q))
    return {"posts": unique, "themes": cluster(unique, query_terms), "phrases": phrases(unique, ignore),
            "kinds": {k: sum(1 for p in unique if k in p["kinds"]) for k in ("question", "complaint", "request")},
            "by_source": {s: sum(1 for p in unique if p["source"] == s) for s in sorted({p["source"] for p in unique})}}


def render(brand, terms, reading):
    r = reading
    lines = ["# Listening: %s" % ", ".join(terms), "", "For **%s**. %d posts read (%s)." % (
        brand.name, len(r["posts"]), ", ".join("%s: %d" % kv for kv in r["by_source"].items()) or "none"), "",
        store.RULES_OF_USE, "",
        "Sorted by simple word rules, not by a judgement: **%d** look like questions, **%d** like complaints, "
        "**%d** like requests. Treat that as a first sort and correct it as you read." % (
            r["kinds"]["question"], r["kinds"]["complaint"], r["kinds"]["request"]), ""]
    lines += ["## Themes", "",
              store.md_table(["Theme", "Also mentions", "Posts", "Questions", "Complaints", "Requests", "Reaction"],
                             [[t["label"], ", ".join(t["also_mentions"]), t["posts"], t["kinds"]["question"],
                               t["kinds"]["complaint"], t["kinds"]["request"], store.fmt_int(t["reaction"])]
                              for t in r["themes"]]), "",
              "Reaction is upvotes or likes added up. It shows what others agreed with, not how many people "
              "have the problem.", ""]
    for t in r["themes"]:
        lines += ["### %s (%d posts)" % (t["label"], t["posts"]), ""]
        for q in t["quotes"]:
            lines.append("- \"%s\" [%s, %s](%s)" % (q["text"].replace("\n", " "), q["source"],
                                                    "/".join(q["kinds"]) or "comment", q["url"] or ""))
        lines.append("")
    if r["phrases"]:
        lines += ["## Phrases they use", "", "Counted by how many different posts use the phrase.", "",
                  ", ".join("\"%s\" (%d)" % (p["phrase"], p["posts"]) for p in r["phrases"]), ""]
    lines += ["## Next", "",
              "Run the demand report on this to turn the themes into a list of what people are asking for, then go "
              "through it with Claude to choose topics. Their wording tells you what to CALL things. It is not text "
              "to reuse.", ""]
    return "\n".join(lines)


def listen(brand, terms, sources=("reddit", "x"), max_items=None, community=None, since=None, confirm=False,
           client=None, today=None):
    """Fetch posts from each source, sort, group and save. Without confirm=True nothing is fetched or saved."""
    brand = store.as_brand(brand)
    terms = [t for t in ([terms] if isinstance(terms, str) else list(terms or [])) if str(t).strip()]
    sources = [s for s in sources if s]
    bad = [s for s in sources if s not in SOURCES]
    if bad or not sources:
        raise store.ResearchError("Listening works on: %s." % ", ".join(sorted(SOURCES)))
    client = client or Apify(allow_runs=confirm)

    plans = {}
    for s in sources:
        extra = {}
        if s == "reddit":
            extra = {"withinCommunity": community, "searchTime": since}
        plans[s] = client.plan(SOURCES[s], terms, max_items, extra=extra)
    total = sum(p["estimate"]["usd"] for p in plans.values())
    ceiling = sum(p["estimate"]["ceiling_usd"] for p in plans.values())
    # The whole cost is said before the FIRST source runs, not source by source as the money goes.
    client.out("Listening on %s. Estimated cost in total: %s (an estimate, not a quote). The most it can be charged "
               "is $%.2f." % (" and ".join(sources), money(total), ceiling))
    if confirm is not True:
        for p in plans.values():
            client.out("%s: %s" % (p["job"], p["estimate"]["text"]))
        return {"ran": False, "estimate": {"usd": round(total, 4), "parts": {s: p["estimate"] for s, p in plans.items()}},
                "plan": plans}

    posts, warnings, results = [], [], {}
    for s in sources:
        extra = {"withinCommunity": community, "searchTime": since} if s == "reddit" else None
        res = client.run(SOURCES[s], terms, max_items=max_items, extra=extra, confirm=True)
        results[s] = res
        warnings += ["%s: %s" % (s, w) for w in res["warnings"]]
        posts += tidy(res["items"], s)

    reading = analyse(posts, terms)
    run_dir = store.new_run_dir(brand, "listen", "-".join(terms), today)
    store.write_json(brand, os.path.join(run_dir, "posts.json"), reading["posts"])
    store.write_json(brand, os.path.join(run_dir, "themes.json"),
                     {"themes": reading["themes"], "phrases": reading["phrases"], "kinds": reading["kinds"],
                      "by_source": reading["by_source"]})
    store.write_text(brand, os.path.join(run_dir, "summary.md"), render(brand, terms, reading))
    combined = {"count": len(reading["posts"]), "warnings": warnings, "estimated_usd": round(total, 4),
                "ceiling_usd": round(sum(r["ceiling_usd"] for r in results.values()), 2),
                "partial": any(r["partial"] for r in results.values()),
                "actor": ", ".join(r["actor"] for r in results.values()),
                "their_fields_seen": sorted({f for r in results.values() for f in r["their_fields_seen"]})}
    store.write_record(brand, run_dir, "listen", {"terms": terms, "sources": sources, "community": community,
                                                  "since": since, "limit_per_source": max_items}, combined)
    return {"ran": True, "folder": store.rel(brand, run_dir), "count": len(reading["posts"]), "warnings": warnings,
            "partial": combined["partial"], "estimate_usd": combined["estimated_usd"],
            "themes": [(t["label"], t["posts"]) for t in reading["themes"]]}
