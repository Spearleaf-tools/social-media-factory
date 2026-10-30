"""demand_report.py - "what are people asking for?", built from this brand's own listening runs.

A listening run answers "what did we hear about these words". A demand report steps back: across
one or more listening runs, what do people keep asking for, in what words, and where does that
meet what this brand talks about?

It costs nothing and fetches nothing. It only re-reads listening runs that are already saved, and
ONLY runs that belong to the same brand: the store refuses a run made for anyone else.

What it writes:
    summary.md               the report, laid out for a person and Claude to go through together
    topic_candidates.json    one entry per theme, each carrying a `source_ref` that points back
                             to this report, ready to become topics in the brand's topic bank

What it does NOT do: decide. It counts, groups, quotes with links and notes where a theme shares
WORDS with one of the brand's pillars. Sharing words is a hint, not a match; whether a theme is
worth a topic is a judgement, and that is made in the conversation.

Nothing in a report is evidence for a claim. People saying something online does not make it
true, and for a brand in a regulated field it is never grounds for a claim of any kind.
"""
from __future__ import annotations

import os

from smf.research import listen, numbers, store

JOB = "demand-report"
QUESTIONS_SHOWN = 20
PER_KIND = 4


def _pillar_hints(brand, theme):
    """Which pillars share a word with this theme. Word overlap only, and labelled as such."""
    theme_words = set(listen.tokens(theme["label"] + " " + " ".join(theme.get("also_mentions") or [])))
    hints = []
    for p in brand.data.get("pillars") or []:
        shared = sorted(theme_words & set(listen.tokens("%s %s" % (p.get("name", ""), p.get("about", "")))))
        if shared:
            hints.append({"pillar": p.get("id"), "name": p.get("name"), "shared_words": shared})
    return hints


def build(brand, runs):
    """Pure once the runs are loaded: `runs` is a list of (folder, record, posts)."""
    posts, terms, folders = [], [], []
    for folder, record, run_posts in runs:
        folders.append(store.rel(brand, folder))
        for t in (record.get("asked") or {}).get("terms") or []:
            if t not in terms:
                terms.append(t)
        posts += run_posts
    reading = listen.analyse(posts, terms)
    by_id = {p["id"]: p for p in reading["posts"]}

    themes = []
    for t in reading["themes"]:
        if t["id"] == "other":
            continue
        members = [by_id[i] for i in t["post_ids"] if i in by_id]

        def best(kind):
            chosen = sorted((p for p in members if kind in p["kinds"]), key=lambda p: (-p["score"], p["id"]))
            return [{"text": listen._clip(p["text"]), "url": p["url"], "source": p["source"], "score": p["score"]}
                    for p in chosen[:PER_KIND]]
        themes.append(dict(t, questions=best("question"), complaints=best("complaint"), requests=best("request"),
                           pillar_hints=_pillar_hints(brand, t)))
    themes.sort(key=lambda t: (-t["posts"], -t["reaction"], t["label"]))

    questions = sorted((p for p in reading["posts"] if "question" in p["kinds"]),
                       key=lambda p: (-p["score"], p["id"]))[:QUESTIONS_SHOWN]
    dates = sorted(d for d in (numbers.parse_when(p.get("posted_at")) for p in reading["posts"]) if d)
    return {"terms": terms, "from_runs": folders, "posts": len(reading["posts"]), "by_source": reading["by_source"],
            "kinds": reading["kinds"], "themes": themes, "phrases": reading["phrases"],
            "questions": [{"text": listen._clip(p["text"]), "url": p["url"], "source": p["source"],
                           "score": p["score"]} for p in questions],
            "unplaced": next((t["posts"] for t in reading["themes"] if t["id"] == "other"), 0),
            "posted_between": [dates[0].date().isoformat(), dates[-1].date().isoformat()] if dates else None}


def candidates(brand, report, report_folder):
    """One topic candidate per theme. `source_ref` is where a topic says it came from."""
    ref = store.rel(brand, report_folder)
    out = []
    for t in report["themes"]:
        sample = (t["questions"] or t["requests"] or t["complaints"] or [{}])[0]
        out.append({"source_ref": "%s#%s" % (ref, t["id"]), "source_kind": "research:demand-report",
                    "theme": t["label"], "also_mentions": t["also_mentions"], "posts": t["posts"],
                    "kinds": t["kinds"], "pillar_hints": [h["pillar"] for h in t["pillar_hints"]],
                    "heard_as": sample.get("text", ""), "heard_at": sample.get("url"),
                    "status": "candidate",
                    "note": "A theme people raised, not a fact. The topic, its angle and its wording are chosen "
                            "with the person. Quotes are for understanding and are never reused as copy."})
    return out


def render(brand, r):
    regulated = (brand.data.get("business") or {}).get("regulated", "none")
    lines = ["# What people are asking for: %s" % ", ".join(r["terms"]), "",
             "For **%s**. Built from %d listening run%s, %d posts (%s)%s." % (
                 brand.name, len(r["from_runs"]), "" if len(r["from_runs"]) == 1 else "s", r["posts"],
                 ", ".join("%s: %d" % kv for kv in r["by_source"].items()) or "none",
                 ", posted between %s and %s" % tuple(r["posted_between"]) if r["posted_between"] else ""), "",
             store.RULES_OF_USE, ""]
    if regulated and regulated != "none":
        lines += ["> **%s works in a regulated field (%s).** What people say online is not evidence. Nothing in this "
                  "report is a claim the brand may make, and any topic that touches a result, a treatment, a return "
                  "or advice goes through the brand's sign-off like everything else." % (brand.name, regulated), ""]
    lines += ["How to read it: themes are ranked by how many different posts raised them. The sorting into questions, "
              "complaints and requests uses simple word rules, so expect some to be filed wrongly.", "",
              "## The themes, most raised first", "",
              store.md_table(["Theme", "Also mentions", "Posts", "Questions", "Complaints", "Requests",
                              "Shares words with pillar"],
                             [[t["label"], ", ".join(t["also_mentions"]), t["posts"], t["kinds"]["question"],
                               t["kinds"]["complaint"], t["kinds"]["request"],
                               ", ".join(h["name"] or h["pillar"] for h in t["pillar_hints"]) or "-"]
                              for t in r["themes"]]), "",
              "\"Shares words with pillar\" means only that: a word in common. It is a hint to look, not a match.", ""]
    for t in r["themes"]:
        lines += ["### %s (%d posts)" % (t["label"], t["posts"]), ""]
        for title, key in (("They ask", "questions"), ("They complain", "complaints"), ("They want", "requests")):
            if t[key]:
                lines.append("**%s**" % title)
                lines += ["- \"%s\" [%s](%s)" % (q["text"], q["source"], q["url"] or "") for q in t[key]]
                lines.append("")
    if r["questions"]:
        lines += ["## The questions, in their own words", ""]
        lines += ["%d. \"%s\" [%s](%s)" % (i, q["text"], q["source"], q["url"] or "")
                  for i, q in enumerate(r["questions"], 1)]
        lines.append("")
    if r["phrases"]:
        lines += ["## The words they use", "",
                  ", ".join("\"%s\" (%d)" % (p["phrase"], p["posts"]) for p in r["phrases"]), ""]
    if r["unplaced"]:
        lines += ["%d posts did not fit any theme. They are in the listening run's own files." % r["unplaced"], ""]
    lines += ["## Worksheet (Claude fills this in with you)", "",
              "1. Which themes does %s have something true and useful to say about, from its own experience?"
              % brand.name,
              "2. For each one kept: which pillar does it belong to, and what is the brand's own answer? The answer "
              "comes from the brand's files and what the person says, never from these posts.",
              "3. What do they CALL the problem? Use their word for it in the title. Do not reuse their sentences.",
              "4. Each theme kept becomes a topic in the brand's topic bank. `topic_candidates.json` beside this file "
              "has one entry per theme with its `source_ref` already filled in.", ""]
    return "\n".join(lines)


def report(brand, run_folders=None, latest=1, label=None, today=None):
    """Build a report from named listening runs, or from the newest `latest` runs of this brand."""
    brand = store.as_brand(brand)
    folders = list(run_folders or []) or store.list_runs(brand, "listen")[:max(1, int(latest))]
    if not folders:
        raise store.ResearchError("%s has no listening runs yet. Run a listening job first, then build the report."
                                  % brand.name)
    runs = []
    for folder in folders:
        record = store.read_run(brand, folder, job="listen")          # refuses another brand's run
        folder = folder if os.path.isabs(folder) else brand.path(*str(folder).replace("\\", "/").split("/"))
        runs.append((folder, record, store.read_json(brand, folder, "posts.json")))

    built = build(brand, runs)
    run_dir = store.new_run_dir(brand, JOB, label or "-".join(built["terms"]) or "report", today)
    store.write_json(brand, os.path.join(run_dir, "report.json"), built)
    store.write_json(brand, os.path.join(run_dir, "topic_candidates.json"), candidates(brand, built, run_dir))
    store.write_text(brand, os.path.join(run_dir, "summary.md"), render(brand, built))
    store.write_record(brand, run_dir, JOB, {"from_runs": built["from_runs"], "terms": built["terms"]},
                       extra={"returned": built["posts"], "cost": {"estimated_usd": 0, "note": "No cost: this only "
                              "re-reads listening runs that were already saved."}})
    return {"ran": True, "folder": store.rel(brand, run_dir), "count": built["posts"],
            "themes": [(t["label"], t["posts"]) for t in built["themes"]], "warnings": []}
