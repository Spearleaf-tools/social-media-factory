"""writing_cli.py - the writing tools as verbs. Each takes the words after the verb and returns an
exit code (0 fine, 1 something needs attention, 2 the command was not understood).

    python factory.py plan      --brand maple-and-main --identity person --count 10
    python factory.py plan      --brand maple-and-main --identity person --run week-of-june-9
    python factory.py topics    inputs  --brand maple-and-main
    python factory.py topics    add     --brand maple-and-main --run week-of-june-9 --title "..." --source-ref "..."
    python factory.py topics    approve --brand maple-and-main --run week-of-june-9 --id flat-loaf
    python factory.py contract  --brand maple-and-main --identity person --platform linkedin --run week-of-june-9 --topic flat-loaf
    python factory.py validate-draft --brand ... --identity ... --platform ... --run ... --topic ... --draft post.txt
    python factory.py facts     add --brand maple-and-main --claim "We proof our sourdough for 18 hours." --source "Ava's recipe card"
    python factory.py journal   add --brand maple-and-main --text "their words, exactly as said" [--private] [--asked "..."]
    python factory.py journal   list --brand maple-and-main

Every verb needs --brand. There is no default brand, so leaving it out is an error that lists the
brands on this computer. Everything printed is for a person: what happened, and the next step.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from smf import brands
from smf.studio import contract as contract_mod
from smf.studio import grounding
from smf.studio import journal as journal_mod
from smf.studio import plan as plan_mod
from smf.studio import platforms, quality
from smf.studio import topics as topics_mod
from smf.studio.files import StudioError, read_text


class _Misunderstood(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    """argparse, but a mistake becomes a plain sentence and an exit code instead of ending the program."""

    def error(self, message):
        raise _Misunderstood(message)


def _explain(message):
    if "--brand" in message:
        return ("Say which brand this is for with --brand <id>. Brands here: %s."
                % (", ".join(brands.list_brands()) or "none yet (ask Claude to onboard one)"))
    return "That command was not understood: %s. Add --help to see what it accepts." % message


def _run(parser, args, action):
    """Parse, run, and turn every expected failure into a sentence."""
    try:
        parsed = parser.parse_args(args)
    except _Misunderstood as e:
        print(_explain(str(e)))
        return 2
    except SystemExit as e:                      # --help
        return int(e.code or 0)
    try:
        return action(parsed)
    except (brands.BrandError, StudioError) as e:
        print(str(e))
        return 1
    except ValueError as e:
        print(str(e))
        return 1


def _identity(brand, given):
    """The identity asked for. With none given, a brand that has exactly one uses it; a brand with
    several has to be told, because choosing who speaks is never a guess."""
    if given:
        brand.identity(given)
        return given
    if len(brand.identities) == 1:
        return brand.identities[0]
    raise brands.BrandError("%s has more than one identity (%s). Say who is speaking with --identity."
                            % (brand.name, ", ".join(brand.identities)))


def _stale_line():
    try:
        return platforms.load().warning()
    except StudioError as e:
        return str(e)


# ----------------------------------------------------------------------------- plan
def _print_slots(slots):
    head = ["#", "Job", "Opening", "Template", "Visual", "Ends with", "Topic"]
    rows = [[str(s["slot"]), s["job_name"], s["hook_family"]["name"], s["template"]["name"],
             "%s (%s)" % (s["visual_format"]["name"], s["visual_format"]["tier"]),
             s["cta_id"] or "soft close", s["topic_title"] or "(to fill)"] for s in slots]
    widths = [max(len(head[i]), *(len(r[i]) for r in rows)) for i in range(len(head))]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(head)))
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))


def cli_plan(args):
    ap = _Parser(prog="factory.py plan", description="Plan a batch: a job, an opening, a template, a visual "
                                                     "and an ending for every slot.")
    ap.add_argument("--brand", required=True)
    ap.add_argument("--identity")
    ap.add_argument("--count", type=int, help="how many posts to plan (default 10, or one per approved topic)")
    ap.add_argument("--run", help="plan this run's approved topics and save the plan into it")
    ap.add_argument("--platforms", nargs="*", help="only these platforms (they must be linked to the identity)")
    ap.add_argument("--warmed", action="store_true", help="the audience is warm: one more lead-gen, one less reach")
    ap.add_argument("--json", action="store_true")

    def action(a):
        brand = brands.load(a.brand)
        identity = _identity(brand, a.identity)
        if a.run:
            result = plan_mod.plan_run(brand, a.run, identity, platforms=a.platforms, warmed=a.warmed)
            slots = result["slots"]
        else:
            slots = plan_mod.plan_week(brand, identity, count=a.count, platforms=a.platforms, warmed=a.warmed)
            result = {"slots": slots, "topics": [], "warnings": [], "problems": plan_mod.check_plan(slots)}
        if a.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        print("Plan for %s, speaking as '%s', on %s.\n" % (brand.name, identity, ", ".join(slots[0]["platforms"])))
        _print_slots(slots)
        mix = {}
        for s in slots:
            mix[s["job_name"]] = mix.get(s["job_name"], 0) + 1
        print("\nMix: " + ", ".join("%d %s" % (n, j) for j, n in mix.items()) + ".")
        for t in result["topics"]:
            shapes = t["plans"][identity]["platform_shapes"]
            print("  %s: %s" % (t["title"], ", ".join("%s as %s" % (p, v["shape"]) for p, v in shapes.items())))
        for s in slots:
            if s["cta_note"]:
                print("Note: " + s["cta_note"])
                break
        for w in result["warnings"] + result["problems"]:
            print("Note: " + w)
        if a.run:
            print("\nSaved into the run '%s'. Next: build a contract for each topic and platform." % a.run)
        else:
            print("\nNothing was saved. Add --run <name> to plan a run's approved topics.")
        return 0

    return _run(ap, args, action)


# ----------------------------------------------------------------------------- topics
def cli_topics(args):
    ap = _Parser(prog="factory.py topics", description="Gather planning inputs, and record decisions on topics.")
    sub = ap.add_subparsers(dest="action")
    parsers = {}
    for name, about in (("inputs", "everything to read before proposing topics"), ("list", "the topics in a run"),
                        ("add", "add a proposed topic to a run"), ("approve", "approve a topic"),
                        ("cut", "cut a topic"), ("revise", "send a topic back for another go"),
                        ("check", "is every approved topic sourced")):
        p = sub.add_parser(name, help=about)
        p.add_argument("--brand", required=True)
        parsers[name] = p
    parsers["inputs"].add_argument("--json", action="store_true")
    for name in ("list", "add", "approve", "cut", "revise", "check"):
        parsers[name].add_argument("--run", required=True)
    parsers["add"].add_argument("--title", required=True)
    parsers["add"].add_argument("--source-ref", default="", help="where in the brand's own material this comes from")
    parsers["add"].add_argument("--lane", default="evergreen", choices=topics_mod.LANES)
    parsers["add"].add_argument("--pillar", default="")
    parsers["add"].add_argument("--proof", nargs="*", default=[])
    parsers["add"].add_argument("--note", default="")
    for name in ("approve", "cut", "revise"):
        parsers[name].add_argument("--id", required=True)
        parsers[name].add_argument("--note")
        parsers[name].add_argument("--source-ref")

    def action(a):
        if not a.action:
            print("Say what to do with topics: inputs, list, add, approve, cut, revise or check.")
            return 2
        brand = brands.load(a.brand)
        if a.action == "inputs":
            if a.json:
                print(json.dumps(topics_mod.planning_inputs(brand), indent=2, ensure_ascii=False))
            else:
                print(topics_mod.planning_brief(brand))
            return 0
        if a.action == "list":
            rows = topics_mod.load_run(brand, a.run)
            if not rows:
                print("The run '%s' has no topics yet. Propose some from the planning inputs first." % a.run)
                return 0
            for t in rows:
                print("%-9s %-10s %s  <- %s" % (t.get("status"), t.get("lane"), t.get("title"),
                                                t.get("source_ref") or "NO SOURCE"))
            return 0
        if a.action == "add":
            topic = topics_mod.new_topic(a.title, source_ref=a.source_ref, lane=a.lane, pillar=a.pillar,
                                         proof_ids=a.proof, note=a.note)
            added, warnings = topics_mod.add_topics(brand, a.run, [topic])
            print("Added '%s' to the run '%s' as %s (proposed)." % (a.title, a.run, added[0]))
            if not a.source_ref:
                print("It has no source yet, so it cannot be approved until it says where it comes from.")
            for w in warnings:
                print("Note: " + w)
            return 0
        if a.action in ("approve", "cut", "revise"):
            status = {"approve": "approved", "cut": "cut", "revise": "revise"}[a.action]
            topic, warnings = topics_mod.set_status(brand, a.run, a.id, status, note=a.note, source_ref=a.source_ref)
            print("'%s' is now %s." % (topic["title"], status))
            for w in warnings:
                print("Note: " + w)
            return 0
        problems, warnings = topics_mod.check_topics(brand, topics_mod.load_run(brand, a.run))
        for line in problems:
            print("To fix: " + line)
        for line in warnings:
            print("Note: " + line)
        if not problems and not warnings:
            print("Every topic in '%s' is in order." % a.run)
        return 1 if problems else 0

    return _run(ap, args, action)


# ----------------------------------------------------------------------------- contract
def _topic_shape_job(topic, identity, platform, shape, job):
    planned = (topic.get("plans") or {}).get(identity) or {}
    per = (planned.get("platform_shapes") or {}).get(platform) or {}
    pinned = (topic.get("platform_shapes") or {}).get(platform)
    shape = shape or per.get("shape") or (pinned.get("shape") if isinstance(pinned, dict) else pinned)
    job = job or planned.get("job")
    if not shape or not job:
        raise StudioError("This topic has not been planned for '%s' on %s yet. Run the plan for its run first, "
                          "or say --shape and --job." % (identity, platform))
    return shape, job


def cli_contract(args):
    ap = _Parser(prog="factory.py contract", description="Build what Claude writes from, for one post.")
    ap.add_argument("--brand", required=True)
    ap.add_argument("--identity")
    ap.add_argument("--platform", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--topic", required=True, help="the topic id inside the run")
    ap.add_argument("--shape")
    ap.add_argument("--job", choices=sorted(plan_mod.JOBS))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="also save the page to this file")

    def action(a):
        brand = brands.load(a.brand)
        identity = _identity(brand, a.identity)
        platform = a.platform.strip().lower()
        topic = topics_mod.get_topic(brand, a.run, a.topic)
        shape, job = _topic_shape_job(topic, identity, platform, a.shape, a.job)
        built = contract_mod.build_contract(brand, identity, platform, topic, shape, job)
        text = built.to_json() if a.json else built.markdown
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        print(text)
        return 0

    return _run(ap, args, action)


# ----------------------------------------------------------------------------- validate
def cli_validate(args):
    ap = _Parser(prog="factory.py validate-draft", description="Check one draft before it goes to review.")
    ap.add_argument("--brand", required=True)
    ap.add_argument("--identity")
    ap.add_argument("--platform", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--topic", required=True, help="the topic id inside the run")
    ap.add_argument("--draft", required=True, help="a text file holding the draft, or - to read it from the keyboard")
    ap.add_argument("--proof", nargs="*", help="proof ids linked to this post (default: the topic's)")
    ap.add_argument("--post-id", help="this post's id, so checking it again does not match itself")
    ap.add_argument("--job", choices=sorted(plan_mod.JOBS))
    for name in quality.TAKEAWAY_CRITERIA:
        ap.add_argument("--" + name.replace("_", "-"), type=int, choices=range(1, 6), metavar="1-5",
                        help="the reviewer's score for " + name.replace("_", " "))
    ap.add_argument("--json", action="store_true")

    def action(a):
        brand = brands.load(a.brand)
        identity = _identity(brand, a.identity)
        topic = topics_mod.get_topic(brand, a.run, a.topic)
        if a.draft == "-":
            text = sys.stdin.read()
        else:
            try:
                text, _cut = read_text(a.draft)
            except OSError:
                print("The draft file could not be opened: %s" % a.draft)
                return 1
        if not text.strip():
            print("The draft is empty, so there is nothing to check.")
            return 1
        scores = {n: getattr(a, n) for n in quality.TAKEAWAY_CRITERIA if getattr(a, n) is not None}
        rubric = quality.RubricScore(**scores) if scores else None
        report = contract_mod.validate_draft(text.strip(), brand, identity, a.platform, topic, proof_ids=a.proof,
                                             post_id=a.post_id, job=a.job, rubric=rubric)
        if a.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(contract_mod.format_report(report))
            stale = _stale_line()
            if stale:
                print("\nNote: " + stale)
        return 0 if report["ok"] else 1

    return _run(ap, args, action)


# ----------------------------------------------------------------------------- facts
def cli_facts(args):
    """The way a true number gets into the brand's files, so a draft that states it can pass."""
    ap = _Parser(prog="factory.py facts", description="List or add the verified facts a brand may state in public.")
    sub = ap.add_subparsers(dest="action")
    listing = sub.add_parser("list", help="the facts on file")
    listing.add_argument("--brand", required=True)
    adding = sub.add_parser("add", help="record one fact and where it comes from")
    adding.add_argument("--brand", required=True)
    adding.add_argument("--claim", required=True, help="the fact, as a sentence")
    adding.add_argument("--source", required=True, help="who said it, which document, or where it can be checked")
    adding.add_argument("--values", nargs="*", help="only when the sentence spells a number out in words")

    def action(a):
        if not a.action:
            print("Say what to do with facts: list or add.")
            return 2
        brand = brands.load(a.brand)
        if a.action == "add":
            row = grounding.add_fact(brand, a.claim, a.source, values=a.values)
            print("Saved as %s. Posts for %s may now state: %s." % (row["id"], brand.name, ", ".join(row["values"]) or
                                                                   "this fact (it has no number in it)"))
            return 0
        facts, notes = grounding.load_facts(brand)
        if not facts:
            print("No verified facts yet. That is fine: posts simply will not state numbers until there are some.")
        for f in facts:
            print("%s  %s  (source: %s)" % (f["id"], f["claim"], f["source"]))
        for n in notes:
            print("Note: " + n)
        return 0

    return _run(ap, args, action)


def cli_journal(args):
    """The owner's thinking journal: their words saved exactly, dated, and private when they say so."""
    ap = _Parser(prog="factory.py journal", description="Save the owner's own words to their thinking journal, "
                                                        "list it, or mark an entry private or public.")
    sub = ap.add_subparsers(dest="action")
    adding = sub.add_parser("add", help="save one entry, word for word")
    adding.add_argument("--brand", required=True)
    words = adding.add_mutually_exclusive_group(required=True)
    words.add_argument("--text", help="their words, exactly as they said them")
    words.add_argument("--text-file", help="a text file holding their words (for long or many-line entries)")
    adding.add_argument("--private", action="store_true", help="keep it out of planning and posts")
    adding.add_argument("--asked", default="", help="the question Claude asked, when this answers one")
    adding.add_argument("--note-from-claude", action="store_true",
                        help="this is Claude's note (a question or a suggestion), not the owner's words")
    adding.add_argument("--date", help="YYYY-MM-DD (default: today)")
    listing = sub.add_parser("list", help="every entry, private ones marked")
    listing.add_argument("--brand", required=True)
    listing.add_argument("--json", action="store_true")
    for name, about in (("private", "keep an entry out of planning and posts"), ("public", "let planning use an entry")):
        p = sub.add_parser(name, help=about)
        p.add_argument("--brand", required=True)
        p.add_argument("--id", required=True)

    def action(a):
        if not a.action:
            print("Say what to do with the journal: add, list, private or public.")
            return 2
        brand = brands.load(a.brand)
        if a.action == "add":
            text = a.text
            if a.text_file:
                try:
                    text = read_text(a.text_file)[0]
                except OSError:
                    print("The file with their words could not be opened: %s" % a.text_file)
                    return 1
            when = None
            if a.date:
                try:
                    when = datetime.strptime(a.date, "%Y-%m-%d").date()
                except ValueError:
                    print("The date '%s' is not a date. Write it as YYYY-MM-DD." % a.date)
                    return 2
            entry = journal_mod.add(brand, text, kind="claude" if a.note_from_claude else "owner",
                                    private=a.private, asked=a.asked, when=when)
            print("Saved to %s's journal as %s (%s%s)." % (brand.name, entry["id"], journal_mod.KINDS[entry["kind"]],
                                                          ", private: it stays out of planning and posts"
                                                          if entry["private"] else ""))
            if entry["kind"] == "owner" and not entry["private"]:
                print("Planning can now use it as a source: journal:%s" % entry["id"])
            return 0
        if a.action == "list":
            book = journal_mod.load(brand)
            if a.json:
                print(json.dumps(book["entries"], indent=2, ensure_ascii=False))
                return 0
            if not book["entries"] and not book["older"]:
                print("%s's journal is empty. Say \"save this\" in the chat to start it." % brand.name)
                return 0
            if book["older"]:
                print("(%d lines of older, hand-written notes at the top.)" % len(book["older"]))
            for e in book["entries"]:
                print("%s  %s%s" % (e["id"], journal_mod.KINDS[e["kind"]], "  PRIVATE" if e["private"] else ""))
                if e["asked"]:
                    print("    Claude asked: " + e["asked"])
                for line in e["text"].splitlines():
                    print("    " + line)
            return 0
        entry = journal_mod.set_private(brand, a.id, private=(a.action == "private"))
        print("%s is now %s." % (entry["id"], "private: it stays out of planning and posts" if entry["private"]
                                 else "public: planning may use it"))
        return 0

    return _run(ap, args, action)
