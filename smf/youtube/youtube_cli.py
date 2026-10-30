"""youtube_cli.py - `factory.py youtube <step> --brand <id> ...`

    new           start a video folder from a topic (in words, or an approved topic from the bank)
    titles        the pattern library, a score for any title, and a video's options: add, choose
    set           fill in the rest of the package: opening, structure, the ask, description, tags
    check         read the whole package against the brand's rules and facts, in plain words
    thumbnail     draw thumbnail concepts, measure them at feed size, choose one
    deck          draw a support deck: slides as pictures, one PDF, and a sheet of all of them
    teleprompter  check the script and make the plain-words file read on camera
    questions     keyword exports -> which videos to make: build, status, apply, briefs, enrich
    status        where every video has got to, and moving one along

Every step needs --brand. There is no default brand and no "latest video": a step that is not
told which brand (and, where it matters, which video) stops and says so. Nothing here posts,
uploads or fetches anything. Research that costs money lives under `factory.py research`.
"""
from __future__ import annotations

import argparse
import json
import os

from smf import brands
from smf.studio.files import StudioError
from smf.youtube import YouTubeError, read_text
from smf.youtube import deck as DK
from smf.youtube import describe as D
from smf.youtube import questions as Q
from smf.youtube import script as S
from smf.youtube import thumbnail as TH
from smf.youtube import titles as T
from smf.youtube import video as V


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    """Says what is missing in a sentence instead of printing a usage dump and exiting."""

    def error(self, message):
        if "--brand" in message:
            message = ("say which brand this is for with --brand. Brands here: %s"
                       % (", ".join(brands.list_brands()) or "none yet"))
        raise _Usage("That could not be run: %s." % message.rstrip("."))


def _json(path, what):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        raise YouTubeError("%s could not be found or opened." % what)
    except ValueError as e:
        raise YouTubeError("%s could not be read as JSON (%s). Nothing was saved." % (what, e))


def _say(lines):
    for line in lines if isinstance(lines, (list, tuple)) else [lines]:
        print(line)


def _where(brand, video_id):
    return "%s's Output folder, under youtube/%s" % (brand.name, video_id)


# ----------------------------------------------------------------------------- the steps
def do_new(brand, a):
    brief = V.new_video(brand, topic=a.topic, source_ref=a.source_ref or "", keyword=a.keyword or "",
                        identity=a.identity, stage=a.stage, topic_id=a.topic_id, run=a.run)
    _say(["Started the video '%s'." % brief["video_id"], "It is in %s." % _where(brand, brief["video_id"])])
    if not brief["source_ref"]:
        _say("It does not yet say where in the brand's own material this topic comes from. Add that before it is packaged.")
    if brief["keyword"]:
        _say("Search phrase, never to be reworded: \"%s\"." % brief["keyword"])
    _say("Demand has not been checked. With the research key, `factory.py research youtube --brand %s --keyword ...` "
         "says whether recent videos on this are being watched; without it, this step is skipped." % brand.id)
    return 0


def do_titles(brand, a):
    if a.patterns:
        for p in T.patterns_for(a.job):
            _say(["", "%s  [%s]  (%s)" % (p["name"], p["id"], p["job"]), "  shape:    %s" % p["template"],
                  "  use when: %s" % p["when"], "  not when: %s" % p["avoid_when"],
                  "  needs:    %s" % (", ".join(p["needs"]) or "nothing special"),
                  "  invented examples: %s  /  %s" % (p["examples"]["bakery"], p["examples"]["clinic"])])
        _say(["", "Additions in brackets after a search phrase:"] +
             ["  %-14s %s   e.g. (%s)" % (t["id"], t["template"], t["example"]) for t in T.TAILS])
        return 0
    if a.score:
        problems, warnings = T.check_title(brand, a.score, keyword=a.keyword)
        _say(T.explain(T.signals(a.score, a.keyword, own_names=brand.data.get("own_brands") or [])))
        _say(["  problem: " + p for p in problems] + ["  advice: " + w for w in warnings])
        return 1 if problems else 0
    if not a.video:
        raise YouTubeError("Say which video with --video, or use --patterns or --score.")
    brief = V.load(brand, a.video)
    if a.add or a.from_keyword:
        text = a.add
        pattern = a.pattern or "own"
        if a.from_keyword:
            if not brief.get("keyword"):
                raise YouTubeError("This video has no search phrase to build a title from.")
            text, pattern = T.with_keyword(brief["keyword"], a.tail), a.pattern or "question-as-typed"
        warnings = V.add_title(brand, brief, text, pattern)
        V.save(brand, brief)
        _say(["Added: %s" % text] + ["  advice: " + w for w in warnings])
    if a.choose:
        picked = V.choose_title(brief, a.choose)
        V.save(brand, brief)
        _say("Chosen: %s" % picked["text"])
    _say("Title options for %s:" % a.video)
    for i, o in enumerate(brief["titles"], 1):
        _say("  %d. %s   (%s, %s characters, score %s)%s"
             % (i, o["text"], o.get("pattern"), o.get("chars"), o.get("score"),
                "   <- chosen" if o["text"] == brief.get("chosen_title") else ""))
    if not brief["titles"]:
        _say("  none yet. Write three to five from different patterns (`--patterns` lists them).")
    return 0


def do_set(brand, a):
    try:
        return _set(brand, a)
    except (brands.BrandError, StudioError) as e:
        raise YouTubeError("%s\nNothing was saved." % e)


def _set(brand, a):
    brief = V.load(brand, a.video)
    done = []
    if a.source_ref:
        brief["source_ref"] = a.source_ref.strip()
        done.append("where the topic comes from")
    if a.hook:
        hook = _json(a.hook, "The opening file")
        brief["hook"] = {k: str(hook.get(k) or "").strip() for k in ("promise", "say", "show", "on_screen")}
        done.append("the opening")
    if a.structure:
        parts = [p.strip() for p in (a.parts or "").split("|") if p.strip()]
        V.set_structure(brief, a.structure, a.minutes, part_titles=parts or None, parts=a.count)
        done.append("the structure")
    if a.stage:
        V.set_call_to_action(brand, brief, a.stage, a.offer, a.ask)
        done.append("the ask")
    if a.description:
        desc = _json(a.description, "The description file")
        for key in ("opening", "answer", "text"):
            if key in desc:
                brief["description"][key] = str(desc[key] or "").strip()
        for key in ("also_answers", "hashtags"):
            if key in desc:
                brief["description"][key] = [str(x).strip() for x in (desc[key] or []) if str(x).strip()]
        done.append("the description")
    if a.chapters:
        brief["chapters"] = D.parse_chapters(read_text(a.chapters, "The chapters file"))
        done.append("%d real chapters" % len(brief["chapters"]))
    if a.tags is not None:
        brief["tags"] = [t.strip() for t in a.tags.split(",") if t.strip()]
        done.append("the tags")
    if a.demand_run:
        found = V.attach_demand(brand, brief, a.demand_run)
        done.append("the demand check (%s)" % found["verdict"])
    if not done:
        raise YouTubeError("Nothing was given to set. Options: --hook, --structure, --stage, --description, "
                           "--chapters, --tags, --source-ref, --demand-run.")
    V.save(brand, brief)
    _say("Saved %s." % ", ".join(done))
    _say(V.check(brand, brief).lines())
    return 0


def do_check(brand, a):
    brief = V.load(brand, a.video)
    rep = V.check(brand, brief, final=True if a.final else None)
    V.save(brand, brief)                                  # refreshes the readable page
    _say(["%s: %s" % (a.video, brief.get("chosen_title") or brief.get("topic"))] + rep.lines())
    return 0 if rep.ok else 1


def _specs_from(data):
    if isinstance(data, dict) and isinstance(data.get("thumbnails"), list):
        return data["thumbnails"]
    return data if isinstance(data, list) else [data]


def do_thumbnail(brand, a):
    brief = V.load(brand, a.video)
    if a.spec:
        specs = _specs_from(_json(a.spec, "The thumbnail file"))
        for i, spec in enumerate(specs, 1):
            if isinstance(spec, dict):
                spec.setdefault("name", chr(96 + i) if i <= 26 else str(i))
        brief["thumbnails"] = specs
    specs = brief.get("thumbnails") or []
    if a.choose:
        if a.choose not in [str(s.get("name")) for s in specs]:
            raise YouTubeError("'%s' is not one of this video's thumbnail concepts (%s)."
                               % (a.choose, ", ".join(str(s.get("name")) for s in specs) or "none yet"))
        brief["chosen_thumbnail"] = a.choose
        V.save(brand, brief)
        _say("Chosen thumbnail: %s" % a.choose)
        return 0
    if not specs:
        raise YouTubeError("This video has no thumbnail concepts yet. Give some with --spec.")
    problems = ["Thumbnail '%s': %s" % (s.get("name"), p) for s in specs
                for p in TH.validate_spec(brand, s, proof_ids=brief.get("proof_ids"))]
    if problems:
        _say(["These thumbnails cannot be drawn yet:"] + ["  - " + p for p in problems])
        return 1
    if a.check:
        V.save(brand, brief)
        _say("These %d concepts can be drawn." % len(specs))
        return 0
    out = os.path.join(V.video_dir(brand, a.video), "thumbnails")
    _files, report = TH.render(brand, specs, out, proof_ids=brief.get("proof_ids"), title=brief.get("chosen_title") or "")
    V.save(brand, brief)
    _say("Drew %d thumbnails into %s, in the thumbnails folder." % (len(report["thumbnails"]), _where(brand, a.video)))
    for row in report["thumbnails"]:
        _say("  %s (%s): %s%s" % (row["name"], row["layout"],
                                  "reads at feed size" if row["legible"] else "DOES NOT READ at feed size: " + row["why"],
                                  "".join("; note: " + n for n in row["notes"])))
    _say("Now open the small copies (the files ending -small.png) and look. The measurement catches faint and "
         "tiny; only eyes catch confusing.")
    return 0 if report["all_legible"] else 1


def do_deck(brand, a):
    if a.types:
        for key, arch in DK.ARCHETYPES.items():
            limits = ", ".join("%s%s" % (f, (" (%d words)" % r["words"]) if "words" in r and "items" not in r else
                                         (" (%d to %d entries)" % r["items"]) if "items" in r else "")
                               for f, r in arch["fields"].items())
            _say(["", "%s  [%s]" % (arch["name"], key), "  use when: %s" % arch["use_when"], "  holds:    %s" % limits])
        return 0
    if not a.video or not a.spec:
        raise YouTubeError("Say which video with --video and give the deck with --spec (or use --types).")
    brief = V.load(brand, a.video)
    spec = _json(a.spec, "The deck file")
    folder = V.video_dir(brand, a.video)
    script = None
    if os.path.isfile(S.path_for(folder)):
        script = S.load(folder)
    problems, unverified = DK.validate(brand, spec, script=script, proof_ids=brief.get("proof_ids"))
    if problems or a.check:
        _say((["This deck cannot be drawn yet:"] + ["  - " + p for p in problems]) if problems
             else "This deck of %d slides can be drawn." % len(spec.get("slides") or []))
        _say(["  unverified: " + u for u in unverified])
        return 1 if problems else 0
    _files, report = DK.render(brand, spec, os.path.join(folder, "deck"), script=script, proof_ids=brief.get("proof_ids"))
    _say(["Drew %d slides, one PDF and a contact sheet into %s, in the deck folder."
          % (len(report["files"]), _where(brand, a.video)), "The slide headings, in order:"]
         + ["  %d. %s" % (i, h or "(a picture)") for i, h in enumerate(report["headings_in_order"], 1)]
         + ["  UNVERIFIED: " + u for u in report["unverified"]]
         + ["Open the contact sheet and read those headings top to bottom: the argument should hold with nobody "
            "talking. Then open any slide that looks crowded or empty."])
    return 0


def do_teleprompter(brand, a):
    brief = V.load(brand, a.video)
    folder = V.video_dir(brand, a.video)
    if a.starter:
        path = S.path_for(folder)
        if os.path.isfile(path):
            raise YouTubeError("This video already has a script. It was left alone.")
        from smf.youtube import write_text
        write_text(path, S.starter(brand, brief))
        _say("A starter script is in %s. Every spoken line in it is a TODO: the words come from the person."
             % _where(brand, a.video))
        return 0
    script = S.load(folder)
    problems, warnings = S.check(brand, script, brief)
    _say(["  problem: " + p for p in problems] + ["  advice: " + w for w in warnings])
    if a.check:
        state, why = S.teleprompter_state(folder, brief.get("teleprompter"), script)
        _say("Teleprompter: %s. %s" % (state, why))
        return 1 if problems or state != "current" else 0
    if problems:
        _say("The teleprompter was not made. Fix the script first.")
        return 1
    brief["teleprompter"] = S.write_teleprompter(folder, script)
    V.save(brand, brief)
    _say("Made the teleprompter: %d lines, about %.1f minutes at a talking pace. It holds only what is said."
         % (brief["teleprompter"]["lines"], brief["teleprompter"]["minutes"]))
    return 0


def _slate_lines(brand, summary):
    t = summary["tiers"]
    lines = ["%d phrases grouped into %d possible videos for %s." % (summary["keywords"], summary["groups"], brand.name),
             "  film %d, batch %d, text (written answers only) %d, parked %d. %d decided so far."
             % (t["film"], t["batch"], t["text"], t["parked"], summary["decided"])]
    if not summary["results_page_known"]:
        lines.append("  These exports do not say what the results page shows, so tiers are based on demand alone.")
    return lines


def do_questions(brand, a):
    if a.action == "build":
        if not a.file:
            raise YouTubeError("Give at least one keyword export with --file (a CSV saved from any keyword tool).")
        corpus = Q.build(brand, a.file)
        _say(_slate_lines(brand, corpus["summary"]) +
             ["The review sheet is in %s's Strategy folder, under youtube-questions (review.html). Open it in a "
              "browser, make the decisions, save the file it gives you, then hand that file back." % brand.name])
        return 0
    if a.action == "status":
        corpus = Q.load(brand)
        _say(_slate_lines(brand, Q.summarise(corpus["groups"])))
        for g in corpus["groups"][:a.top]:
            _say("  %3d. %-6s %7s  %s%s" % (g["rank"], g["tier"], "{:,}".format(g["volume"]), g["head"],
                                          ("   [%s]" % g["decision"]) if g.get("decision") else ""))
        return 0
    if a.action == "apply":
        if not a.decisions:
            raise YouTubeError("Give the decisions file the review sheet saved, with --decisions.")
        n = Q.apply_decisions(brand, a.decisions)
        _say("Applied: %d approved, %d to edit, %d parked, %d given a video of their own. %d still undecided.%s"
             % (n["approve"], n["edit"], n["park"], n["split"], n["undecided"],
                (" %d decisions were about groups that are not in this slate and were ignored." % n["unknown"]) if n["unknown"] else ""))
        return 0
    if a.action == "briefs":
        made, skipped = Q.make_briefs(brand, a.tier, identity=a.identity, approved_only=not a.all, limit=a.limit)
        _say(["Started %d video%s from the '%s' tier." % (len(made), "" if len(made) == 1 else "s", a.tier)]
             + ["  %s  ->  %s" % (m["head"], m["video_id"]) for m in made]
             + ["  skipped \"%s\": %s" % (s["head"], s["why"]) for s in skipped])
        if not made and not skipped:
            _say("Nothing to start: no approved group in that tier is waiting for a video.")
        return 0
    if a.action == "enrich":
        if not a.run:
            raise YouTubeError("Say which saved results-page check to read, with --run (a folder under the brand's "
                               "Inputs/Research/serp).")
        n = Q.enrich_from_results_pages(brand, a.run)
        _say("Read %d checked phrases and updated %d groups. The review sheet was rebuilt." % (n["queries_read"], n["groups_touched"]))
        return 0
    raise YouTubeError("The question steps are: build, status, apply, briefs, enrich.")


def do_status(brand, a):
    if a.video and a.set:
        brief = V.load(brand, a.video)
        V.set_status(brand, brief, a.set, a.note or "")
        V.save(brand, brief)
        _say("%s is now '%s'." % (a.video, brief["status"]))
        return 0
    rows = [r for r in V.summary(brand) if not a.video or r["video_id"] == a.video]
    if not rows:
        _say("%s has no long-form videos yet." % brand.name if not a.video else "%s has no video called '%s'." % (brand.name, a.video))
        return 0 if not a.video else 1
    for r in rows:
        _say("  %-10s %s   %s%s" % (r["status"], r["video_id"], r["title"],
                                  ("   (%d to fix)" % r["problems"]) if r.get("problems") else ""))
    return 0


# ----------------------------------------------------------------------------- the parser
def _parser():
    ap = _Parser(prog="factory.py youtube", description="Long-form YouTube packaging, one brand at a time.")
    sub = ap.add_subparsers(dest="step", parser_class=_Parser)

    def step(name, about):
        p = sub.add_parser(name, help=about)
        p.add_argument("--brand", required=True)
        return p

    p = step("new", "start a video")
    p.add_argument("--topic")
    p.add_argument("--topic-id", dest="topic_id")
    p.add_argument("--run")
    p.add_argument("--keyword")
    p.add_argument("--source-ref", dest="source_ref")
    p.add_argument("--identity")
    p.add_argument("--stage", default="learning", choices=sorted(V.STAGES))

    p = step("titles", "patterns, scores and a video's title options")
    p.add_argument("--video")
    p.add_argument("--patterns", action="store_true")
    p.add_argument("--job", choices=T.JOBS)
    p.add_argument("--score")
    p.add_argument("--keyword")
    p.add_argument("--add")
    p.add_argument("--pattern")
    p.add_argument("--from-keyword", dest="from_keyword", action="store_true")
    p.add_argument("--tail")
    p.add_argument("--choose")

    p = step("set", "fill in the opening, structure, ask, description, tags")
    p.add_argument("--video", required=True)
    p.add_argument("--source-ref", dest="source_ref")
    p.add_argument("--hook")
    p.add_argument("--structure", choices=sorted(V.STRUCTURES))
    p.add_argument("--minutes", type=float)
    p.add_argument("--parts", help="the names of the counted parts, separated by |")
    p.add_argument("--count", type=int, help="how many counted parts, when they are not named yet")
    p.add_argument("--stage", choices=sorted(V.STAGES))
    p.add_argument("--offer")
    p.add_argument("--ask")
    p.add_argument("--description")
    p.add_argument("--chapters")
    p.add_argument("--tags")
    p.add_argument("--demand-run", dest="demand_run")

    p = step("check", "read the package against the brand's rules and facts")
    p.add_argument("--video", required=True)
    p.add_argument("--final", action="store_true", help="treat every gap as a problem, as packaging does")

    p = step("thumbnail", "draw, measure and choose thumbnails")
    p.add_argument("--video", required=True)
    p.add_argument("--spec")
    p.add_argument("--check", action="store_true")
    p.add_argument("--choose")

    p = step("deck", "draw a support deck")
    p.add_argument("--video")
    p.add_argument("--spec")
    p.add_argument("--check", action="store_true")
    p.add_argument("--types", action="store_true")

    p = step("teleprompter", "check the script and make the file read on camera")
    p.add_argument("--video", required=True)
    p.add_argument("--starter", action="store_true")
    p.add_argument("--check", action="store_true")

    p = step("questions", "keyword exports -> which videos to make")
    p.add_argument("action", choices=["build", "status", "apply", "briefs", "enrich"])
    p.add_argument("--file", action="append")
    p.add_argument("--decisions")
    p.add_argument("--tier", default="film", choices=["film", "batch"])
    p.add_argument("--identity")
    p.add_argument("--limit", type=int)
    p.add_argument("--all", action="store_true", help="include groups nobody has approved yet")
    p.add_argument("--run")
    p.add_argument("--top", type=int, default=15)

    p = step("status", "where every video has got to")
    p.add_argument("--video")
    p.add_argument("--set", choices=V.STATUSES)
    p.add_argument("--note")
    return ap


_STEPS = {"new": do_new, "titles": do_titles, "set": do_set, "check": do_check, "thumbnail": do_thumbnail,
          "deck": do_deck, "teleprompter": do_teleprompter, "questions": do_questions, "status": do_status}


def cli_youtube(args):
    """The `youtube` verb. Returns 0 when the step did what was asked, 1 when something needs
    fixing, 2 when the step could not be understood."""
    try:
        a = _parser().parse_args(list(args))
    except _Usage as e:
        print(str(e))
        return 2
    if not a.step:
        print("Say which step: %s. Every step needs --brand." % ", ".join(_STEPS))
        return 2
    try:
        brand = brands.load(a.brand)
        return _STEPS[a.step](brand, a)
    except (brands.BrandError, StudioError) as e:
        print(str(e))
        return 1
