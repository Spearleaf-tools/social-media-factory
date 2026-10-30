"""serp.py - what Google shows for a list of questions or keywords.

Three things on a results page are useful for planning content, and all three are collected:

    the results            who already answers this, with what title, how recently
    "people also ask"      the follow-up questions Google has learned people have. These are
                           real questions from real searches and are often better topics than
                           the keyword that was typed
    related searches       how people rephrase the same need

One unit of cost is one results page (about ten results). The default is one page per query,
because the first page is where the useful signal is.

Everything this actor sells beyond the plain results page is switched off in the actor table
and cannot be switched on from here; several of those extras cost many times the page itself.
"""
from __future__ import annotations

import os
import re

from smf.research import store
from smf.research.apify import Apify, NotConfirmed

RESULTS_SHOWN = 10


def analyse(pages):
    """Pure: normalised pages in, one tidy entry per query out (pages of the same query are joined)."""
    by_query, order = {}, []
    for page in pages:
        q = str(page.get("query") or "").strip() or "unknown"
        if q not in by_query:
            by_query[q] = {"query": q, "pages": 0, "results": [], "people_also_ask": [], "related": []}
            order.append(q)
        entry = by_query[q]
        entry["pages"] += 1
        for r in page.get("results") or []:
            if isinstance(r, dict) and r.get("url"):
                entry["results"].append({"position": r.get("position"), "title": r.get("title"), "url": r.get("url"),
                                         "site": _site(r.get("url")), "snippet": r.get("description"),
                                         "date": r.get("date")})
        for a in page.get("people_also_ask") or []:
            text = (a.get("question") if isinstance(a, dict) else None) or ""
            if text.strip():
                entry["people_also_ask"].append(text.strip())
        for rel in page.get("related") or []:
            text = (rel.get("title") if isinstance(rel, dict) else None) or ""
            if text.strip():
                entry["related"].append(text.strip())

    questions, seen = [], set()
    for q in order:
        for key in ("people_also_ask", "related"):
            by_query[q][key] = _unique(by_query[q][key])
        for text in by_query[q]["people_also_ask"]:
            k = re.sub(r"\W+", " ", text.lower()).strip()
            if k not in seen:
                seen.add(k)
                questions.append({"question": text, "seen_for": q})
    sites = {}
    for q in order:
        for site in {r["site"] for r in by_query[q]["results"] if r["site"]}:
            sites[site] = sites.get(site, 0) + 1
    return {"queries": [by_query[q] for q in order], "all_questions": questions,
            "sites_seen_for_several": [{"site": s, "queries": n} for s, n in
                                       sorted(sites.items(), key=lambda kv: (-kv[1], kv[0])) if n >= 2][:15]}


def _site(url):
    m = re.match(r"^https?://(?:www\.)?([^/:?#]+)", str(url or ""), re.I)
    return m.group(1).lower() if m else ""


def _unique(texts):
    out, seen = [], set()
    for t in texts:
        k = re.sub(r"\W+", " ", t.lower()).strip()
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def render(brand, reading):
    lines = ["# What Google shows", "", "For **%s**. %d quer%s." % (
        brand.name, len(reading["queries"]), "y" if len(reading["queries"]) == 1 else "ies"), "",
        store.RULES_OF_USE, ""]
    if reading["all_questions"]:
        lines += ["## Questions people also ask", "",
                  "These come from Google, which learned them from real searches. Each is a candidate topic.", ""]
        lines += ["- %s  _(seen for: %s)_" % (q["question"], q["seen_for"]) for q in reading["all_questions"]]
        lines.append("")
    if reading["sites_seen_for_several"]:
        lines += ["## Sites that show up for more than one query", "",
                  ", ".join("%s (%d)" % (s["site"], s["queries"]) for s in reading["sites_seen_for_several"]), ""]
    for q in reading["queries"]:
        lines += ["## \"%s\"" % q["query"], ""]
        if q["results"]:
            lines += [store.md_table(["#", "Title", "Site", "Date", "Link"],
                                     [[r["position"], r["title"], r["site"], r["date"] or "-", r["url"]]
                                      for r in q["results"][:RESULTS_SHOWN]]), ""]
        else:
            lines += ["No results came back for this one.", ""]
        if q["related"]:
            lines += ["People also search: " + "; ".join(q["related"]), ""]
    lines += ["## Worksheet (Claude fills this in with you)", "",
              "1. Which of the questions above can %s answer from its own experience?" % brand.name,
              "2. Where are the current results old, thin or all from the same few sites? That is room.",
              "3. Titles here show what already exists. They are not a source of titles: write your own.",
              "4. Each question kept becomes a topic in the brand's topic bank, with this report as its source.", ""]
    return "\n".join(lines)


def search(brand, queries, pages_per_query=1, country=None, language=None, confirm=False, client=None, today=None):
    """Fetch results pages and save a reading. Without confirm=True it returns the cost and saves nothing."""
    brand = store.as_brand(brand)
    queries = [q for q in ([queries] if isinstance(queries, str) else list(queries or [])) if str(q).strip()]
    try:
        pages = int(pages_per_query)
    except (TypeError, ValueError):
        pages = 0
    if pages < 1 or pages > 5:
        raise store.ResearchError("Pages per query must be between 1 and 5. One is usually enough.")
    client = client or Apify(allow_runs=confirm)
    extra = {"countryCode": (country or "").lower() or None, "languageCode": language or None}
    try:
        result = client.run("serp", queries, max_items=max(1, len(set(q.lower() for q in queries))) * pages,
                            extra=extra, confirm=confirm)
    except NotConfirmed as e:
        return {"ran": False, "estimate": e.plan["estimate"], "plan": e.plan}

    reading = analyse(result["items"])
    run_dir = store.new_run_dir(brand, "serp", "-".join(result["inputs"][:3]), today)
    store.write_json(brand, os.path.join(run_dir, "pages.json"), reading)
    store.write_text(brand, os.path.join(run_dir, "summary.md"), render(brand, reading))
    store.write_record(brand, run_dir, "serp", {"queries": result["inputs"], "pages_per_query": pages,
                                                "country": country, "language": language}, result)
    return {"ran": True, "folder": store.rel(brand, run_dir), "count": result["count"],
            "warnings": result["warnings"], "partial": result["partial"], "estimate_usd": result["estimated_usd"],
            "questions": len(reading["all_questions"])}
