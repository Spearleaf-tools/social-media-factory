"""topics.py - what the brand will talk about, decided by a person, grounded in the brand's own material.

Code never invents a topic. It does three things:

  1. GATHERS the planning inputs from the brand itself: its pillars, the problems and questions
     its audience has, its offers, what is written under Brand/, and the question files under
     Inputs/Questions. Claude proposes topics FROM that, and says where each one came from.
  2. STORES the decisions. Each topic is proposed, then approved, cut, or sent back for revision.
  3. CHECKS that every approved topic says where in the brand's material it comes from
     (`source_ref`). A topic with no source cannot be approved, and only approved topics get written.

Where things live, all inside the brand's folder:
    Studio/topic-bank.json            ideas kept for later, across runs
    Studio/runs/<run>/topics.json     the topics for one run of work (a week, a campaign)

A topic record:
    {"topic_id": "flat-loaf", "title": "Why a loaf comes out flat", "status": "proposed",
     "lane": "evergreen", "pillar": "sourdough-at-home",
     "source_ref": "audience.questions_they_ask[1]", "proof_ids": ["PRF-0001"],
     "platform_shapes": {"linkedin": "three-tips"}, "note": ""}

`source_ref` is free text, because good ideas also come from a phone call or a comment. When it
LOOKS like a pointer into the brand's files (a path, "pillar:<id>", "offer:<id>", "proof:<id>",
"fact:<id>", "journal:<entry id>", "audience.questions_they_ask[2]") it is checked, and a pointer to
nothing is reported. A pointer to a PRIVATE journal entry is refused: private thinking is never a post.

The owner's influences (the people who inspire them) are shown to planning as reference for
structure and format only, never as words, titles or frameworks to borrow.
"""
from __future__ import annotations

import os
import re
import unicodedata

from smf.studio import grounding
from smf.studio import journal
from smf.studio.files import (StudioError, as_brand, inside, own_lines, read_json, read_text, relative, text_files,
                              write_json)

STATUSES = ("proposed", "approved", "cut", "revise")
LANES = ("evergreen", "news", "opinion")
BANK_FILE = ("Studio", "topic-bank.json")
RUNS_DIR = ("Studio", "runs")
PER_FILE_CHARS = 6000
ALL_FILES_CHARS = 40000
JOURNAL_CHARS = 20000
INFLUENCE_RULE = ("Reference for structure and format only: how they open, pace and lay out a piece. Never copy "
                  "their words, titles, catchphrases or frameworks, and never name them in a post unless the owner asks.")

_RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,60}$")
_AUDIENCE_REF = re.compile(r"^audience\.(problems|questions_they_ask)\[(\d+)\]$")


class TopicError(StudioError):
    """A topic, or a topics file, that cannot be used as it stands."""


# ----------------------------------------------------------------------------- planning inputs
def planning_inputs(brand):
    """Everything Claude should read before proposing topics, taken ONLY from the brand.

    Returns a dict with the brand's own answers (pillars, audience, offers), its written material
    (`material`: files under Brand/ and Inputs/Questions with the blank-template lines removed),
    what it already has (`existing_topics`, `proof`), and `gaps`: plain sentences about what is
    missing, so a thin brand gets an honest "add this first" instead of made-up subjects."""
    brand = as_brand(brand)
    data = brand.data
    audience = data.get("audience") or {}
    pillars = [p for p in (data.get("pillars") or []) if isinstance(p, dict)]
    offers = [o for o in (data.get("offers") or []) if isinstance(o, dict)]

    material, used = [], 0
    for folder in (brand.path("Brand"), brand.path("Inputs", "Questions")):
        for path in text_files(folder):
            if journal.is_journal(brand, path):
                continue                                  # read below, entry by entry, so private ones stay out
            rel = relative(brand, path)
            text, cut = read_text(path, PER_FILE_CHARS)
            lines = own_lines(brand, rel, text)
            if not lines:
                continue                                  # an untouched template says nothing about the brand
            body = "\n".join(lines)
            if used + len(body) > ALL_FILES_CHARS:
                body, cut = body[:max(0, ALL_FILES_CHARS - used)], True
            if not body:
                break
            used += len(body)
            material.append({"file": rel, "text": body, "shortened": bool(cut)})

    book = journal.load(brand)
    entries, used = [], 0
    for e in reversed(book["entries"]):                   # newest first, so a long journal keeps what is fresh
        if e["private"]:
            continue
        if used + len(e["text"]) > JOURNAL_CHARS:
            break
        used += len(e["text"])
        entries.append({"id": e["id"], "date": e["date"], "kind": e["kind"], "asked": e["asked"], "text": e["text"]})
    entries.reverse()
    journal_part = {"entries": entries, "older": "\n".join(book["older"])[:max(0, JOURNAL_CHARS - used)],
                    "private_left_out": sum(1 for e in book["entries"] if e["private"]) + len(book["private_older"]),
                    "left_out_for_length": sum(1 for e in book["entries"] if not e["private"]) - len(entries)}

    bank = load_bank(brand)
    proof = [{"proof_id": p["proof_id"], "kind": p["kind"], "title": p["title"], "may_publish": p["may_publish"]}
             for p in grounding.list_proof(brand)]
    facts, _notes = grounding.load_facts(brand)

    gaps = []
    if not pillars:
        gaps.append("No content pillars yet: the three to five subjects this brand could talk about for a year.")
    if not (audience.get("problems") or audience.get("questions_they_ask")):
        gaps.append("No audience problems or questions yet. The questions real customers ask are the best topics.")
    if not offers:
        gaps.append("No offers yet, so lead-gen posts have nowhere to send a reader.")
    if not material and not entries and not book["older"]:
        gaps.append("Nothing written under Brand/ or Inputs/Questions yet beyond the blank templates.")
    if not facts and not proof:
        gaps.append("No verified facts and no proof yet, so posts cannot state numbers or results.")

    return {"brand": brand.id, "name": brand.name, "goal": data.get("goal", ""),
            "business": data.get("business") or {},
            "pillars": pillars,
            "audience": {"who": audience.get("who", ""), "problems": list(audience.get("problems") or []),
                         "questions_they_ask": list(audience.get("questions_they_ask") or []),
                         "by_platform": dict(audience.get("by_platform") or {})},
            "offers": offers, "material": material, "journal": journal_part,
            "influences": influences(brand), "influence_rule": INFLUENCE_RULE,
            "facts": [{"id": f["id"], "claim": f["claim"], "source": f["source"]} for f in facts],
            "proof": proof,
            "existing_topics": [{"topic_id": t.get("topic_id"), "title": t.get("title"), "status": t.get("status")}
                                for t in bank],
            "gaps": gaps,
            "rule": "Propose topics only from what is on this page. Every topic must carry a source_ref that says "
                    "where on this page it came from. If the page is thin, say what is missing instead of inventing."}


def planning_brief(brand):
    """The same inputs as a page Claude (or a person) can read top to bottom."""
    p = planning_inputs(brand)
    out = ["# Planning inputs for %s" % p["name"], "", p["rule"], ""]
    business = p["business"]
    if business.get("what_we_do"):
        out += ["## The business", business["what_we_do"], ""]
    out.append("## Pillars")
    out += ["- pillar:%s  %s%s" % (x.get("id"), x.get("name"), (": " + x["about"]) if x.get("about") else "")
            for x in p["pillars"]] or ["- (none yet)"]
    out += ["", "## Audience", p["audience"]["who"] or "(not described yet)", "", "Problems:"]
    out += ["- audience.problems[%d]  %s" % (i, t) for i, t in enumerate(p["audience"]["problems"])] or ["- (none yet)"]
    out.append("Questions they ask:")
    out += ["- audience.questions_they_ask[%d]  %s" % (i, t)
            for i, t in enumerate(p["audience"]["questions_they_ask"])] or ["- (none yet)"]
    out += ["", "## Offers"]
    out += ["- offer:%s  %s%s" % (o.get("id"), o.get("name"), (": " + o["what"]) if o.get("what") else "")
            for o in p["offers"]] or ["- (none yet)"]
    out += ["", "## Verified facts"]
    out += ["- fact:%s  %s (source: %s)" % (f["id"], f["claim"], f["source"]) for f in p["facts"]] or ["- (none yet)"]
    out += ["", "## Proof library"]
    out += ["- proof:%s  [%s, may publish: %s] %s" % (x["proof_id"], x["kind"], x["may_publish"], x["title"])
            for x in p["proof"]] or ["- (none yet)"]
    out += ["", "## In their own files"]
    for m in p["material"]:
        out += ["### %s%s" % (m["file"], " (shortened)" if m["shortened"] else ""), m["text"], ""]
    if not p["material"]:
        out += ["(nothing beyond the blank templates yet)", ""]
    j = p["journal"]
    if j["entries"] or j["older"] or j["private_left_out"]:
        out += ["## Their thinking journal",
                "Their own thinking, word for word. Cite an entry as journal:<id>. Only \"their words\" are theirs: "
                "a note from Claude is context, never their voice and never a quote.", ""]
        for e in j["entries"]:
            who = "their words" if e["kind"] == "owner" else "note from Claude, not their words"
            out.append("- journal:%s  (%s, %s)" % (e["id"], e["date"], who))
            if e["asked"]:
                out.append("  Claude asked: %s" % e["asked"])
            out += ["  " + line for line in e["text"].splitlines()]
        if j["older"]:
            out += ["", "Older notes (written before entries were labelled; cite as Brand/journal.md. They may mix "
                    "their words with summaries, so quote only what is in quotation marks):", j["older"]]
        if j["left_out_for_length"]:
            out.append("(%d older entries left out to keep this page a readable length.)" % j["left_out_for_length"])
        if j["private_left_out"]:
            out.append("(%d private entries or lines left out on purpose. Never ask to see them for a post.)"
                       % j["private_left_out"])
        out.append("")
    if p["influences"]:
        out += ["## Who inspires them (structure and format only)", p["influence_rule"]]
        out += ["- %s%s" % (i["name"], (": " + i["why"]) if i["why"] else "") for i in p["influences"]]
        out.append("")
    if p["existing_topics"]:
        out += ["## Already in the topic bank (do not propose these again)"]
        out += ["- %s  [%s] %s" % (t["topic_id"], t["status"], t["title"]) for t in p["existing_topics"]]
        out.append("")
    if p["gaps"]:
        out += ["## What is missing"] + ["- " + g for g in p["gaps"]] + [""]
    return "\n".join(out)


def influences(brand):
    """The people who inspire the owner, from the brand settings: [{"name", "why"}]. A name alone is fine."""
    out = []
    for item in as_brand(brand).data.get("influences") or []:
        if isinstance(item, dict):
            name, why = str(item.get("name") or "").strip(), str(item.get("why") or "").strip()
        else:
            name, why = str(item or "").strip(), ""
        if name:
            out.append({"name": name, "why": why})
    return out


# ----------------------------------------------------------------------------- one topic
def slug(text):
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return s[:48].strip("-") or "topic"


def new_topic(title, source_ref="", lane="evergreen", pillar="", proof_ids=(), platform_shapes=None, note="",
              topic_id=None, status="proposed"):
    """Build a clean topic record. It is a plain dict so it round-trips through JSON untouched."""
    if not str(title or "").strip():
        raise TopicError("A topic needs a title: the subject in a few words.")
    topic = {"topic_id": topic_id or slug(title), "title": str(title).strip(), "status": status, "lane": lane,
             "pillar": pillar or "", "source_ref": str(source_ref or "").strip(),
             "proof_ids": [str(p) for p in (proof_ids or [])], "platform_shapes": dict(platform_shapes or {}),
             "note": note or ""}
    return topic


def resolve_source_ref(brand, ref):
    """Does a source_ref that looks like a pointer actually point at something?
    Returns {"kind", "ok", "detail"}. Free text is kind "note" and always ok."""
    brand = as_brand(brand)
    ref = str(ref or "").strip()
    if not ref:
        return {"kind": "missing", "ok": False, "detail": "no source given"}
    m = _AUDIENCE_REF.match(ref)
    if m:
        items = (brand.data.get("audience") or {}).get(m.group(1)) or []
        ok = int(m.group(2)) < len(items)
        return {"kind": "audience", "ok": ok,
                "detail": items[int(m.group(2))] if ok else "the brand settings have no such entry"}
    for prefix, group, key in (("pillar:", brand.data.get("pillars") or [], "id"),
                               ("offer:", brand.data.get("offers") or [], "id")):
        if ref.lower().startswith(prefix):
            wanted = ref[len(prefix):].strip()
            hit = [g for g in group if str(g.get(key)) == wanted]
            return {"kind": prefix[:-1], "ok": bool(hit),
                    "detail": hit[0].get("name", "") if hit else "the brand settings have no %s called '%s'"
                    % (prefix[:-1], wanted)}
    if ref.lower().startswith("proof:"):
        found, _missing = grounding.load_proof(brand, [ref[6:].strip()])
        return {"kind": "proof", "ok": bool(found),
                "detail": found[0]["title"] if found else "the proof library has no item with that id"}
    if ref.lower().startswith("journal:"):
        entry = journal.get(brand, ref[8:].strip())
        if entry is None:
            return {"kind": "journal", "ok": False, "private": False, "detail": "the journal has no entry with that id"}
        if entry["private"]:
            return {"kind": "journal", "ok": False, "private": True,
                    "detail": "that journal entry is private, so it cannot be the source of a post"}
        return {"kind": "journal", "ok": True, "private": False, "detail": entry["text"][:200], "entry": entry}
    if ref.lower().startswith("fact:"):
        facts, _notes = grounding.load_facts(brand)
        hit = [f for f in facts if f["id"] == ref[5:].strip()]
        return {"kind": "fact", "ok": bool(hit), "detail": hit[0]["claim"] if hit else "the facts file has no such fact"}
    head = re.split(r"[#:]", ref, 1)[0].strip()
    looks_like_path = "/" in head or "\\" in head or head.lower().endswith((".md", ".txt", ".csv", ".json", ".srt"))
    if looks_like_path:
        path = inside(brand, head)
        if path is None:
            return {"kind": "file", "ok": False, "detail": "that path is outside the brand's folder"}
        ok = os.path.isfile(path)
        return {"kind": "file", "ok": ok, "detail": relative(brand, path) if ok else "there is no such file in the brand's folder"}
    return {"kind": "note", "ok": True, "detail": ref}


def check_topics(brand, topics):
    """(problems, warnings) for a list of topic records. Problems stop a save; warnings do not."""
    brand = as_brand(brand)
    problems, warnings, seen = [], [], set()
    pillar_ids = {str(p.get("id")) for p in (brand.data.get("pillars") or [])}
    for t in topics:
        label = "'%s'" % (t.get("title") or t.get("topic_id") or "untitled")
        tid = t.get("topic_id")
        if not tid or not str(t.get("title") or "").strip():
            problems.append("A topic is missing its id or its title.")
            continue
        if tid in seen:
            problems.append("Two topics share the id '%s'." % tid)
        seen.add(tid)
        if t.get("status") not in STATUSES:
            problems.append("%s has the status '%s'. A topic is one of: %s." % (label, t.get("status"), ", ".join(STATUSES)))
        if (t.get("lane") or "evergreen") not in LANES:
            problems.append("%s has the lane '%s'. A lane is one of: %s." % (label, t.get("lane"), ", ".join(LANES)))
        if t.get("status") == "approved" and not str(t.get("source_ref") or "").strip():
            problems.append("%s is approved but does not say where in %s's own material it comes from. "
                            "Add a source_ref, or it cannot be written." % (label, brand.name))
        elif str(t.get("source_ref") or "").strip():
            found = resolve_source_ref(brand, t["source_ref"])
            if found.get("private") and t.get("status") == "approved":
                problems.append("%s comes from a private journal entry. Private thinking is never written into a "
                                "post. Make the entry public first, only if the owner says so." % label)
            elif not found["ok"]:
                warnings.append("%s points to '%s', but %s." % (label, t["source_ref"], found["detail"]))
        if t.get("pillar") and pillar_ids and t["pillar"] not in pillar_ids:
            warnings.append("%s is filed under the pillar '%s', which this brand does not have." % (label, t["pillar"]))
        if t.get("proof_ids"):
            _found, missing = grounding.load_proof(brand, t["proof_ids"])
            if missing:
                warnings.append("%s links proof that is not in the proof library: %s." % (label, ", ".join(missing)))
    return problems, warnings


# ----------------------------------------------------------------------------- files
def _load(brand, path, what):
    if not os.path.isfile(path):
        return []
    data = read_json(path, what)
    if not isinstance(data, dict) or not isinstance(data.get("topics", []), list):
        raise TopicError("%s is not in the expected shape. Ask Claude to repair it." % what)
    if data.get("brand") not in (None, brand.id):
        raise TopicError("These topics belong to %s, not to %s. Nothing was loaded." % (data.get("brand"), brand.id))
    return [t for t in data.get("topics", []) if isinstance(t, dict)]


def _save(brand, path, topics, extra=None):
    problems, warnings = check_topics(brand, topics)
    if problems:
        raise TopicError("The topics were not saved:\n  - " + "\n  - ".join(problems))
    payload = {"brand": brand.id}
    payload.update(extra or {})
    payload["topics"] = topics
    write_json(path, payload)
    return warnings


def bank_path(brand):
    return brand.path(*BANK_FILE)


def load_bank(brand):
    brand = as_brand(brand)
    return _load(brand, bank_path(brand), "%s's topic bank (Studio/topic-bank.json)" % brand.name)


def save_bank(brand, topics):
    brand = as_brand(brand)
    return _save(brand, bank_path(brand), topics)


def run_path(brand, run):
    """The folder for one run. The name becomes a folder, so it may not contain a path."""
    if not isinstance(run, str) or not _RUN_NAME.match(run) or ".." in run:
        raise TopicError("A run name is short and simple, like 'week-of-june-9': letters, numbers, spaces, dots "
                         "and dashes, starting with a letter or number.")
    return brand.path(*(RUNS_DIR + (run, "topics.json")))


def list_runs(brand):
    brand = as_brand(brand)
    folder = brand.path(*RUNS_DIR)
    if not os.path.isdir(folder):
        return []
    return sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n, "topics.json")))


def load_run(brand, run):
    brand = as_brand(brand)
    return _load(brand, run_path(brand, run), "The topics for the run '%s'" % run)


def save_run(brand, run, topics):
    brand = as_brand(brand)
    return _save(brand, run_path(brand, run), topics, {"run": run})


def _unique_id(wanted, taken):
    if wanted not in taken:
        return wanted
    n = 2
    while "%s-%d" % (wanted, n) in taken:
        n += 1
    return "%s-%d" % (wanted, n)


def add_topics(brand, run, new):
    """Add proposed topics to a run. Ids are made unique; nothing already there is changed."""
    brand = as_brand(brand)
    topics = load_run(brand, run)
    taken = {t["topic_id"] for t in topics}
    added = []
    for t in new:
        t = dict(t)
        t["topic_id"] = _unique_id(t.get("topic_id") or slug(t.get("title", "")), taken)
        taken.add(t["topic_id"])
        topics.append(t)
        added.append(t["topic_id"])
    warnings = save_run(brand, run, topics)
    return added, warnings


def set_status(brand, run, topic_id, status, note=None, source_ref=None):
    """Record a decision on one topic. Approving a topic that has no source_ref is refused."""
    brand = as_brand(brand)
    if status not in STATUSES:
        raise TopicError("A topic is one of: %s." % ", ".join(STATUSES))
    topics = load_run(brand, run)
    for t in topics:
        if t.get("topic_id") == topic_id:
            if source_ref is not None:
                t["source_ref"] = str(source_ref).strip()
            if note is not None:
                t["note"] = note
            t["status"] = status
            warnings = save_run(brand, run, topics)
            return t, warnings
    raise TopicError("The run '%s' has no topic with the id '%s'. It has: %s."
                     % (run, topic_id, ", ".join(t.get("topic_id", "?") for t in topics) or "none yet"))


def get_topic(brand, run, topic_id):
    brand = as_brand(brand)
    topics = load_run(brand, run)
    for t in topics:
        if t.get("topic_id") == topic_id:
            return t
    raise TopicError("The run '%s' has no topic with the id '%s'. It has: %s."
                     % (run, topic_id, ", ".join(t.get("topic_id", "?") for t in topics) or "none yet"))


def approved_topics(brand, run):
    """The topics that may be written. Checked again on the way out, because a topics file can be
    edited by hand between the decision and the writing."""
    brand = as_brand(brand)
    topics = load_run(brand, run)
    problems, _warnings = check_topics(brand, topics)
    if problems:
        raise TopicError("The topics for '%s' need fixing before anything is written:\n  - %s"
                         % (run, "\n  - ".join(problems)))
    return [t for t in topics if t.get("status") == "approved"]


def keep_in_bank(brand, topics):
    """Copy topics into the long-term bank (new ids only), so a cut idea is not lost."""
    brand = as_brand(brand)
    bank = load_bank(brand)
    have = {t.get("topic_id") for t in bank}
    fresh = [dict(t) for t in topics if t.get("topic_id") not in have]
    for t in fresh:
        if t.get("status") == "approved" and not str(t.get("source_ref") or "").strip():
            t["status"] = "proposed"
    if fresh:
        save_bank(brand, bank + fresh)
    return [t["topic_id"] for t in fresh]
