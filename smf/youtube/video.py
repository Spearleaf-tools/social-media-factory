"""video.py - one folder per video, one record in it, and a check that reads it in plain words.

    Client/<brand>/Output/youtube/<date>-<slug>/brief.json      the record (state: written atomically)
    Client/<brand>/Output/youtube/<date>-<slug>/brief.md        the same, as a page a person reads

A video is packaged BEFORE it is scripted or filmed: the topic and where it comes from, title
options and the pattern each one uses, the chosen title, thumbnail concepts, the opening, the
structure, the ask, the description with chapters, the tags. `check()` reads all of it against
the brand's own rules and facts and says what is wrong in sentences.

    idea -> packaged -> scripted -> filmed -> published

Only a clean check moves a video to `packaged`. Only a checked script with a current teleprompter
moves it to `scripted`. `filmed` and `published` are a person's say-so. A video can always be
moved back.

THE RULES THE CHECK ENFORCES
  * the record belongs to the brand that opened it (a record naming another brand is refused)
  * a title: within the platform's limit, keeps the search phrase word for word when there is
    one, and keeps the promises it makes about the video (a running time, a count of parts)
  * any number, in a title, a thumbnail, the opening or the description, traces to the brand's
    facts, research or linked proof (`smf.studio.grounding`)
  * never-mention names and the brand's regulated terms are caught everywhere a viewer could
    read or hear them (`smf.studio.lint.Rules.for_brand`), so a word that is fine for one brand
    stops another brand's video
  * the ask points only at an offer the brand really has
  * the description is in order and its chapters obey the platform's rules

STRUCTURES are data: each is a list of segments with its share of the running time, so the same
skeleton stretches to any length and the planned chapters fall out of it. They mirror the four
skeletons described in `playbooks/youtube-longform.md`.
"""
from __future__ import annotations

import copy
import os
import re
import time

from smf.studio import grounding, topics as topic_bank
from smf.studio.files import read_json, relative, write_json
from smf.youtube import YouTubeError, as_brand, inside_folder, slugify, write_text
from smf.youtube import describe as D
from smf.youtube import script as S
from smf.youtube import titles as T

VIDEOS_DIR = ("Output", "youtube")
BRIEF_JSON = "brief.json"
BRIEF_MD = "brief.md"
SCHEMA = 1
STATUSES = ("idea", "packaged", "scripted", "filmed", "published")
TAGS_TOTAL_LIMIT = 500          # characters across all tags, the platform's limit (as of June 2026)
MIN_TITLE_OPTIONS = 3
MAX_TITLE_OPTIONS = 5

_VIDEO_ID = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]{0,60}$")
_PLACEHOLDER = re.compile(r"\bTODO\b")

# ----------------------------------------------------------------------------- the ask, by stage
# Where the viewer is decides how direct the ask may be. These are instructions for the writer,
# never copy: the words come from the brand's own offers and voice.
STAGES = {
    "learning": {
        "name": "Learning the subject",
        "who": "Someone meeting the subject for the first time. They searched a question, not a supplier.",
        "ask": "A next step that costs nothing and teaches more: the next video, a free guide the brand really has.",
        "early": "No ask in the first minutes. Earn the right first.",
        "midway": "At most one passing mention, right after something useful has been delivered.",
        "close": "Point to the next video. Mention an offer only if it is free and helps them learn.",
        "offer": "optional"},
    "comparing": {
        "name": "Comparing ways to solve it",
        "who": "Someone who knows the problem and is weighing up how to deal with it, or whom to trust.",
        "ask": "The offer that lets them try the brand with little risk.",
        "early": "One sentence near the start that the offer exists, then straight back to the subject.",
        "midway": "Name the offer inside the section where it is the natural tool for the job.",
        "close": "Say plainly what the offer is, who it suits and who it does not, and where the link is.",
        "offer": "expected"},
    "ready": {
        "name": "Ready to choose",
        "who": "Someone asking about price, timing, or what working with the brand is like.",
        "ask": "The brand's main offer, stated directly.",
        "early": "Say in the opening that the video ends with how to get started.",
        "midway": "Answer the price or time question with real figures from the brand's files.",
        "close": "The direct ask, once, with the link in the first two lines of the description.",
        "offer": "expected"},
}

# ----------------------------------------------------------------------------- structures
# Shares are percentages of the running time. `split` marks the segment that is divided into
# the video's counted parts (its chapters); `counts` marks parts a title's number refers to.
STRUCTURES = {
    "straight-answer": {
        "name": "The straight answer", "minutes": (5, 8),
        "use_when": "A question people type into search. Say it, answer it short, then answer it in full.",
        "segments": [
            {"title": "The question, said aloud", "share": 4, "note": "In the words people type. Promise the short answer, then the full one."},
            {"title": "The short answer", "share": 12, "note": "Complete in under a minute. A viewer who leaves here should still be helped."},
            {"title": "The full answer", "share": 60, "split": (2, 4), "counts": True, "note": "Why, how, the exception. One idea per chapter."},
            {"title": "The common mistake", "share": 14},
            {"title": "What to do next", "share": 10, "note": "One ask. Then point at the next video."}]},
    "worked-example": {
        "name": "The worked example", "minutes": (10, 15),
        "use_when": "A real case from start to finish, where every step can be shown.",
        "segments": [
            {"title": "The outcome, on screen", "share": 3, "note": "Before any explanation. Real figures only."},
            {"title": "Why this case matters to you", "share": 6},
            {"title": "Where it started", "share": 10, "note": "Say that one fault did the most harm, and hold back which."},
            {"title": "The changes", "share": 55, "split": (3, 5), "counts": True, "note": "One change per chapter: show it, explain it, show what it altered. At half way, say what the next chapter settles."},
            {"title": "The fault that mattered most", "share": 15},
            {"title": "Who this works for", "share": 11, "note": "And who it does not. One ask."}]},
    "live-test": {
        "name": "The live test", "minutes": (8, 12),
        "use_when": "Seeing is believing and the outcome is not known in advance.",
        "segments": [
            {"title": "The question, test already running", "share": 4},
            {"title": "The method", "share": 8, "note": "What is being tried, and which outcome would mean what."},
            {"title": "The rounds", "share": 60, "split": (2, 5), "counts": True, "note": "One chapter per round. Keep the scoreboard on screen. At half way, say what the next round decides."},
            {"title": "What it means for you", "share": 20},
            {"title": "What to watch next", "share": 8}]},
    "countdown": {
        "name": "The countdown of mistakes", "minutes": (8, 12),
        "use_when": "The brand has watched the same few errors many times.",
        "segments": [
            {"title": "The pattern, and its count", "share": 3},
            {"title": "What is coming", "share": 4, "note": "A hint at number one."},
            {"title": "The mistakes", "share": 75, "split": (3, 7), "counts": True, "note": "Count down. For each: show it, say what it costs, give the repair, show the result. Win them back before the top two."},
            {"title": "Which to fix first", "share": 10},
            {"title": "One ask", "share": 8}]},
}


# ----------------------------------------------------------------------------- folders
def videos_root(brand):
    return as_brand(brand).path(*VIDEOS_DIR)


def video_dir(brand, video_id):
    """The folder for one video, or an error. The id is checked BEFORE it is joined to a path,
    and the result must really sit inside this brand's youtube folder."""
    brand = as_brand(brand)
    if not isinstance(video_id, str) or not _VIDEO_ID.match(video_id):
        raise YouTubeError("'%s' is not a video here. A video is named by its date and a few words, like "
                           "2026-06-11-why-is-my-loaf-dense. Videos for %s: %s."
                           % (video_id if isinstance(video_id, str) else "", brand.name,
                              ", ".join(list_ids(brand)) or "none yet"))
    folder = os.path.join(videos_root(brand), video_id)
    if not inside_folder(folder, brand.home):
        raise YouTubeError("That name would put the video outside %s's folder, so nothing was opened." % brand.name)
    return folder


def list_ids(brand):
    root = videos_root(brand)
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root)
                  if _VIDEO_ID.match(n) and os.path.isfile(os.path.join(root, n, BRIEF_JSON)))


def _today(today=None):
    return today or time.strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------- the record
def blank(brand, topic, identity, today=None):
    return {"schema": SCHEMA, "brand": brand.id, "video_id": "", "created": _today(today), "status": "idea",
            "identity": identity, "topic": topic, "source_ref": "", "keyword": "", "proof_ids": [],
            "demand": {"checked": False, "verdict": "", "run": "",
                       "note": "Not checked. Without a demand check nobody knows whether recent videos on this "
                               "subject are being watched. It needs the research key; the video can still be made."},
            "titles": [], "chosen_title": "",
            "thumbnails": [], "chosen_thumbnail": "",
            "hook": {"promise": "", "say": "", "show": "", "on_screen": ""},
            "structure": {},
            "call_to_action": {"stage": "learning", "offer_id": "", "text": "", "link": ""},
            "chapters": [],
            "description": {"opening": "", "answer": "", "also_answers": [], "hashtags": [], "text": ""},
            "tags": [], "teleprompter": {}, "history": []}


def new_video(brand, topic=None, source_ref="", keyword="", identity=None, stage="learning", proof_ids=(),
              topic_id=None, run=None, today=None, also_answers=()):
    """Start a video for ONE brand. Returns the record. Never reuses an existing folder.

    Give a `topic` in words, or a `topic_id` from the brand's topic bank (or from a planning
    `run`). A topic taken from the bank must be one a person has approved."""
    brand = as_brand(brand)
    if topic_id:
        pool = topic_bank.load_run(brand, run) if run else topic_bank.load_bank(brand)
        found = [t for t in pool if t.get("topic_id") == topic_id]
        if not found:
            raise YouTubeError("%s has no topic called '%s' %s." % (brand.name, topic_id,
                               ("in the run '%s'" % run) if run else "in its topic bank"))
        if found[0].get("status") != "approved":
            raise YouTubeError("The topic '%s' has not been approved yet. Only a topic a person has said yes to "
                               "becomes a video." % topic_id)
        topic = topic or found[0].get("title")
        source_ref = source_ref or found[0].get("source_ref") or ""
        proof_ids = list(proof_ids) or list(found[0].get("proof_ids") or [])
    if not str(topic or "").strip():
        raise YouTubeError("A video starts from a topic: the subject in a few words.")
    if stage not in STAGES:
        raise YouTubeError("The viewer's stage is one of: %s." % ", ".join(STAGES))
    if identity is None:
        if len(brand.identities) != 1:
            raise YouTubeError("Say who is presenting. %s has: %s." % (brand.name, ", ".join(brand.identities)))
        identity = brand.identities[0]
    brand.identity(identity)                                   # raises in plain words when it is not theirs

    brief = blank(brand, str(topic).strip(), identity, today)
    brief["source_ref"] = str(source_ref or "").strip()
    brief["keyword"] = re.sub(r"\s+", " ", str(keyword or "")).strip()
    brief["proof_ids"] = [str(p) for p in proof_ids or []]
    brief["call_to_action"]["stage"] = stage
    brief["description"]["also_answers"] = [str(q).strip() for q in also_answers if str(q).strip()]

    root = videos_root(brand)
    base = "%s-%s" % (_today(today), slugify(brief["keyword"] or brief["topic"]))
    for n in range(1, 200):
        video_id = base if n == 1 else "%s-%d" % (base, n)
        folder = video_dir(brand, video_id)
        try:
            os.makedirs(folder, exist_ok=False)
            break
        except FileExistsError:
            continue
    else:
        raise YouTubeError("There are already too many videos with that name today. Use different words.")
    brief["video_id"] = video_id
    _note(brief, "idea", "started")
    save(brand, brief)
    return brief


def _note(brief, status, note):
    brief.setdefault("history", []).append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "status": status, "note": note})


def load(brand, video_id):
    """Open one video FOR THIS BRAND. A record that names a different brand, or a different
    video than its folder, is refused: that is how one company's video stays out of another's."""
    brand = as_brand(brand)
    folder = video_dir(brand, video_id)
    path = os.path.join(folder, BRIEF_JSON)
    if not os.path.isfile(path):
        raise YouTubeError("%s has no video called '%s'. Its videos: %s."
                           % (brand.name, video_id, ", ".join(list_ids(brand)) or "none yet"))
    brief = read_json(path, "This video's record")
    if not isinstance(brief, dict):
        raise YouTubeError("This video's record is not in the expected shape. Nothing was changed. Ask Claude to "
                           "repair it.")
    if brief.get("brand") != brand.id:
        raise YouTubeError("This video's record says it belongs to '%s', not to %s. It was not opened."
                           % (brief.get("brand"), brand.name))
    if brief.get("video_id") != video_id:
        raise YouTubeError("This folder is called '%s' but its record says '%s'. They must match. Nothing was "
                           "changed." % (video_id, brief.get("video_id")))
    merged = blank(brand, brief.get("topic") or "", brief.get("identity"))
    for key, value in brief.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def save(brand, brief):
    """Write the record (atomically) and the readable page beside it."""
    brand = as_brand(brand)
    if brief.get("brand") != brand.id:
        raise YouTubeError("This record belongs to '%s', so it cannot be saved into %s." % (brief.get("brand"), brand.name))
    folder = video_dir(brand, brief.get("video_id"))
    write_json(os.path.join(folder, BRIEF_JSON), brief)
    write_text(os.path.join(folder, BRIEF_MD), render_md(brand, brief))
    return folder


# ----------------------------------------------------------------------------- building it up
def add_title(brand, brief, text, pattern_id="own"):
    """Add a title option after checking it. Problems stop it being added; warnings come back."""
    brand = as_brand(brand)
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if pattern_id != "own":
        T.pattern(pattern_id)
    if any(o.get("text") == text for o in brief["titles"]):
        raise YouTubeError("That title is already one of the options.")
    if len(brief["titles"]) >= MAX_TITLE_OPTIONS:
        raise YouTubeError("There are already %d title options. More than that and nobody can choose: drop one first."
                           % MAX_TITLE_OPTIONS)
    problems, warnings = T.check_title(brand, text, keyword=brief.get("keyword"), proof_ids=brief.get("proof_ids"),
                                       length_minutes=(brief.get("structure") or {}).get("length_minutes"),
                                       parts_in_video=counted_parts(brief))
    if problems:
        raise YouTubeError("That title was not added:\n  - " + "\n  - ".join(problems))
    sig = T.signals(text, brief.get("keyword"), own_names=brand.data.get("own_brands") or [])
    brief["titles"].append({"text": text, "pattern": pattern_id, "score": sig["score"], "chars": sig["chars"]})
    return warnings


def choose_title(brief, which):
    """Choose by number (1 is the first option) or by the exact words."""
    options = brief.get("titles") or []
    picked = None
    if isinstance(which, int) or str(which).isdigit():
        i = int(which) - 1
        picked = options[i] if 0 <= i < len(options) else None
    else:
        picked = next((o for o in options if o.get("text") == str(which).strip()), None)
    if picked is None:
        raise YouTubeError("That is not one of the title options. There %s %d."
                           % ("is" if len(options) == 1 else "are", len(options)))
    brief["chosen_title"] = picked["text"]
    return picked


def set_structure(brief, template, length_minutes, part_titles=None, parts=None):
    """Lay a structure out from a template: shares of the running time, with the counted middle
    divided into the video's real parts. `part_titles` names them; `parts` just counts them."""
    if template not in STRUCTURES:
        raise YouTubeError("'%s' is not a structure. Choose from: %s." % (template, ", ".join(STRUCTURES)))
    try:
        minutes = float(length_minutes)
    except (TypeError, ValueError):
        minutes = 0
    if not 2 <= minutes <= 180:
        raise YouTubeError("The planned length is a number of minutes between 2 and 180.")
    spec = STRUCTURES[template]
    names = [str(t).strip() for t in (part_titles or []) if str(t).strip()]
    segments = []
    for seg in spec["segments"]:
        if not seg.get("split"):
            segments.append({"title": seg["title"], "share": seg["share"], "note": seg.get("note", "")})
            continue
        low, high = seg["split"]
        n = len(names) or int(parts or low)
        if not low <= n <= high:
            raise YouTubeError("%s takes between %d and %d parts; %d were given. One idea per chapter: merge two, "
                               "or pick a different structure." % (spec["name"], low, high, n))
        each = round(seg["share"] / float(n), 2)
        for i in range(n):
            segments.append({"title": names[i] if names else "TODO: name part %d as a question or a claim" % (i + 1),
                             "share": each, "counts": True, "note": seg.get("note", "") if i == 0 else ""})
    brief["structure"] = {"template": template, "name": spec["name"], "length_minutes": minutes, "segments": segments}
    return brief["structure"]


def counted_parts(brief):
    segs = (brief.get("structure") or {}).get("segments") or []
    n = sum(1 for s in segs if s.get("counts"))
    return n if segs else None


def set_call_to_action(brand, brief, stage, offer_id=None, text=None):
    """The ask, from the brand's OWN offers. An offer the brand does not have is never written in."""
    brand = as_brand(brand)
    if stage not in STAGES:
        raise YouTubeError("The viewer's stage is one of: %s." % ", ".join(STAGES))
    offers = {str(o.get("id")): o for o in (brand.data.get("offers") or [])}
    cta = {"stage": stage, "offer_id": "", "text": str(text or "").strip(), "link": ""}
    if offer_id:
        if offer_id not in offers:
            raise YouTubeError("%s has no offer called '%s'. Its offers: %s. Add a new one in onboarding first."
                               % (brand.name, offer_id, ", ".join(offers) or "none yet"))
        cta["offer_id"] = offer_id
        cta["text"] = cta["text"] or str(offers[offer_id].get("call_to_action") or "").strip()
        cta["link"] = str(offers[offer_id].get("link") or "").strip()
    brief["call_to_action"] = cta
    return cta


def attach_demand(brand, brief, run_folder, keyword=None):
    """Record what a saved demand check found. The research package is looked for only when this
    is called; a Factory without it still packages videos. Nothing is fetched here."""
    brand = as_brand(brand)
    try:
        from smf.research import store
    except ImportError:
        raise YouTubeError("The research tools are not part of this copy of the Factory, so a demand check cannot "
                           "be attached.")
    try:
        store.read_run(brand, run_folder, job="youtube-now")
        folder = run_folder if os.path.isabs(run_folder) else brand.path(*str(run_folder).replace("\\", "/").split("/"))
        reading = store.read_json(brand, folder, "reading.json")
    except store.ResearchError as e:
        raise YouTubeError(str(e))
    per_keyword = reading.get("keywords") or {}
    wanted = (keyword or brief.get("keyword") or "").strip().lower()
    hit = next((k for k in per_keyword if k.strip().lower() == wanted), None) or (
        list(per_keyword)[0] if len(per_keyword) == 1 else None)
    if hit is None:
        raise YouTubeError("That demand check looked at: %s. Say which of those this video is about."
                           % (", ".join(per_keyword) or "nothing"))
    found = per_keyword[hit]
    brief["demand"] = {"checked": True, "keyword": hit, "verdict": found.get("verdict", ""),
                       "why": found.get("why", ""), "run": relative(brand, folder),
                       "note": "Demand moves. Run the check again if this video is planned much later than this."}
    return brief["demand"]


# ----------------------------------------------------------------------------- the check
class Report(object):
    """What the check found, grouped by the part of the package it is about."""

    def __init__(self):
        self.problems, self.warnings = [], []

    def add(self, where, problems, warnings=()):
        self.problems.extend("%s: %s" % (where, p) for p in problems)
        self.warnings.extend("%s: %s" % (where, w) for w in warnings)

    @property
    def ok(self):
        return not self.problems

    def lines(self):
        out = []
        if self.problems:
            out.append("To fix before this video can move on:")
            out += ["  - " + p for p in self.problems]
        if self.warnings:
            out.append("Worth a look:")
            out += ["  - " + w for w in self.warnings]
        if not out:
            out.append("Everything checks out.")
        return out


def _short_text(brand, rep, where, text, proof_ids):
    """Checks shared by every short piece of text a viewer reads or hears."""
    if not str(text or "").strip():
        return
    g = grounding.ground_draft(T.claims_only(text), brand, proof_ids=proof_ids)
    problems = []
    if g["ungrounded"]:
        problems.append("it states %s, which does not trace to anything in %s's facts, research or linked proof"
                        % (", ".join(g["ungrounded"]), brand.name))
    found_problems, found_warnings = T.brand_findings(brand, text)
    rep.add(where, problems + found_problems, list(g["hints"]) + found_warnings)


def check(brand, brief, final=None):
    """Read the whole package against the brand's rules and facts. Returns a Report.

    `final` decides how gaps are treated. While a video is still an idea, a missing piece is a
    warning (it is simply not written yet). Once it is, or is about to be, `packaged`, a missing
    piece is a problem. Left as None, it follows the video's status."""
    brand = as_brand(brand)
    if final is None:
        final = brief.get("status") != "idea"
    rep = Report()
    gap = (lambda where, text: rep.add(where, [text])) if final else (lambda where, text: rep.add(where, [], [text]))
    proof_ids = list(brief.get("proof_ids") or [])
    keyword = brief.get("keyword") or ""
    structure = brief.get("structure") or {}

    # where it comes from -------------------------------------------------------------
    if not str(brief.get("topic") or "").strip():
        rep.add("Topic", ["there is no topic"])
    ref = str(brief.get("source_ref") or "").strip()
    if not ref:
        gap("Topic", "it does not say where in %s's own material this comes from (a question customers ask, a "
                     "fact, a recording, the question slate)" % brand.name)
    else:
        found = topic_bank.resolve_source_ref(brand, ref)
        if not found["ok"]:
            rep.add("Topic", [], ["it points to '%s', but %s" % (ref, found["detail"])])
    try:
        brand.identity(brief.get("identity"))
    except Exception as e:
        rep.add("Presenter", [str(e)])
    if proof_ids:
        _found, missing = grounding.load_proof(brand, proof_ids)
        if missing:
            rep.add("Proof", ["these linked items are not in %s's proof library: %s" % (brand.name, ", ".join(missing))])
    if keyword:
        rep.add("Search phrase", *T.brand_findings(brand, keyword))
    if not (brief.get("demand") or {}).get("checked"):
        rep.add("Demand", [], ["not checked, so nobody knows yet whether recent videos on this are being watched"])
    elif (brief.get("demand") or {}).get("verdict") == "stale":
        rep.add("Demand", [], ["the last check found only old videos winning here. Look for a fresher angle, or make "
                               "it knowing that"])

    # titles ------------------------------------------------------------------------------
    options = brief.get("titles") or []
    if len(options) < MIN_TITLE_OPTIONS:
        gap("Titles", "there %s %d option%s. Write %d to %d, from different patterns, so there is a real choice"
            % ("is" if len(options) == 1 else "are", len(options), "" if len(options) == 1 else "s",
               MIN_TITLE_OPTIONS, MAX_TITLE_OPTIONS))
    for i, opt in enumerate(options, 1):
        if opt.get("pattern") not in ("own", None) and opt.get("pattern") not in {p["id"] for p in T.PATTERNS}:
            rep.add("Title %d" % i, ["it names the pattern '%s', which does not exist" % opt.get("pattern")])
        rep.add("Title %d" % i, *T.check_title(brand, opt.get("text"), keyword=keyword, proof_ids=proof_ids,
                                               length_minutes=structure.get("length_minutes"),
                                               parts_in_video=counted_parts(brief)))
    chosen = str(brief.get("chosen_title") or "").strip()
    if not chosen:
        gap("Chosen title", "nobody has picked one yet")
    elif chosen not in [o.get("text") for o in options]:
        rep.add("Chosen title", ["\"%s\" is not one of the options on file, so it has not been checked. Add it as an "
                                 "option first" % chosen])

    # thumbnails ----------------------------------------------------------------------------
    from smf.youtube import thumbnail as TH                    # late: it pulls in the picture tools
    concepts = brief.get("thumbnails") or []
    if not concepts:
        gap("Thumbnail", "there is no concept yet. Decide it before filming: the first seconds have to show it")
    names = []
    for i, c in enumerate(concepts, 1):
        where = "Thumbnail %s" % (c.get("name") or i)
        names.append(str(c.get("name") or i))
        rep.add(where, TH.validate_spec(brand, c, proof_ids=proof_ids), TH.advice(c, chosen or (options[0]["text"] if options else "")))
    picked = str(brief.get("chosen_thumbnail") or "").strip()
    if concepts and not picked:
        gap("Thumbnail", "nobody has picked one yet. Draw two or three, look at them small, then choose")
    elif picked and picked not in names:
        rep.add("Thumbnail", ["the chosen one, '%s', is not among the concepts (%s)" % (picked, ", ".join(names))])

    # opening, structure, ask -----------------------------------------------------------------
    hook = brief.get("hook") or {}
    if not str(hook.get("say") or "").strip():
        gap("Opening", "the first spoken lines are not written")
    else:
        for part in ("promise", "say", "on_screen"):
            _short_text(brand, rep, "Opening", hook.get(part), proof_ids)
        if not str(hook.get("show") or "").strip():
            rep.add("Opening", [], ["it says something and shows nothing. Within 30 seconds the viewer should be "
                                    "looking at what the thumbnail showed them"])
        if S._GREETING.match(str(hook.get("say"))):
            rep.add("Opening", [], ["it starts with a greeting or an introduction. Open on the point"])

    segments = structure.get("segments") or []
    if not segments:
        gap("Structure", "there is none yet. Pick a skeleton and a length, and name the parts")
    else:
        total = sum(float(s.get("share") or 0) for s in segments)
        if abs(total - 100.0) > 1.0:
            rep.add("Structure", ["the shares of the running time add up to %g, not 100" % total])
        for s in segments:
            if _PLACEHOLDER.search(str(s.get("title") or "")):
                gap("Structure", "a part still has no name (%s)" % s.get("title"))
                break
        for s in segments:
            _short_text(brand, rep, "Structure", s.get("title"), proof_ids)

    cta = brief.get("call_to_action") or {}
    stage = cta.get("stage")
    offers = {str(o.get("id")) for o in (brand.data.get("offers") or [])}
    if stage not in STAGES:
        rep.add("The ask", ["the viewer's stage is one of: %s" % ", ".join(STAGES)])
    else:
        if cta.get("offer_id") and cta["offer_id"] not in offers:
            rep.add("The ask", ["it points at the offer '%s', which %s does not have (its offers: %s)"
                                % (cta["offer_id"], brand.name, ", ".join(sorted(offers)) or "none yet")])
        if STAGES[stage]["offer"] == "expected" and not cta.get("offer_id"):
            rep.add("The ask", [], ["viewers at the '%s' stage expect a clear next step, and no offer is named. %s"
                                    % (STAGES[stage]["name"].lower(),
                                       ("Its offers: %s." % ", ".join(sorted(offers))) if offers else
                                       "This brand has no offers on file yet; add one in onboarding, or close on the next video.")])
        _short_text(brand, rep, "The ask", cta.get("text"), proof_ids)

    # description, chapters, tags ---------------------------------------------------------------
    text = str((brief.get("description") or {}).get("text") or "").strip() or D.build(brand, brief)
    length_seconds = float(structure.get("length_minutes") or 0) * 60 or None
    rep.add("Description", *D.check(brand, text, keyword=keyword, link=cta.get("link"), proof_ids=proof_ids,
                                    length_seconds=length_seconds, final=final))
    tags = [str(t) for t in (brief.get("tags") or [])]
    if sum(len(t) for t in tags) + max(0, len(tags) - 1) > TAGS_TOTAL_LIMIT:
        rep.add("Tags", ["together they are over %d characters, which is all YouTube accepts" % TAGS_TOTAL_LIMIT])
    for t in tags:
        found_problems, _w = T.brand_findings(brand, t, keep={"never-mention", "never-publish", "banned-word"})
        rep.add("Tags", found_problems)
    return rep


def set_status(brand, brief, status, note=""):
    """Move a video along. Forwards is gated; backwards is always allowed."""
    brand = as_brand(brand)
    if status not in STATUSES:
        raise YouTubeError("A video is one of: %s." % ", ".join(STATUSES))
    now, want = STATUSES.index(brief.get("status") or "idea"), STATUSES.index(status)
    if want > now + 1:
        raise YouTubeError("A video moves one step at a time: %s. This one is '%s'."
                           % (" -> ".join(STATUSES), STATUSES[now]))
    if want > now and status == "packaged":
        rep = check(brand, brief, final=True)
        if not rep.ok:
            raise YouTubeError("This video is not packaged yet:\n  - " + "\n  - ".join(rep.problems))
    if want > now and status == "scripted":
        folder = video_dir(brand, brief["video_id"])
        script = S.load(folder)
        problems, _warnings = S.check(brand, script, brief)
        if problems:
            raise YouTubeError("The script is not ready:\n  - " + "\n  - ".join(problems))
        state, why = S.teleprompter_state(folder, brief.get("teleprompter"), script)
        if state != "current":
            raise YouTubeError("%s Make the teleprompter again, then mark the video as scripted." % why)
    if want > now and status == "published" and not brief.get("chapters"):
        note = (note + " " if note else "") + "(The chapters are still the planned ones. Replace them with the real times from the edit.)"
    brief["status"] = status
    _note(brief, status, note or "")
    return brief


# ----------------------------------------------------------------------------- the readable page
def render_md(brand, brief):
    brand = as_brand(brand)
    structure = brief.get("structure") or {}
    cta = brief.get("call_to_action") or {}
    demand = brief.get("demand") or {}
    hook = brief.get("hook") or {}
    out = ["# %s" % (brief.get("chosen_title") or brief.get("topic") or "Untitled video"), "",
           "For **%s**. Presented by %s. Status: **%s**." % (brand.name, brief.get("identity") or "?", brief.get("status")),
           "", "## Where this comes from", "",
           "- Topic: %s" % (brief.get("topic") or ""),
           "- From the brand's own material: %s" % (brief.get("source_ref") or "not recorded yet"),
           "- Search phrase (never reworded): %s" % (("`%s`" % brief["keyword"]) if brief.get("keyword") else "none"),
           "- Demand: %s" % (("%s. %s" % (demand.get("verdict"), demand.get("why") or "")) if demand.get("checked")
                             else demand.get("note") or "not checked"), ""]
    out += ["## Title options", ""]
    for i, o in enumerate(brief.get("titles") or [], 1):
        name = "your own wording" if o.get("pattern") in ("own", None) else T._BY_ID.get(o["pattern"], {}).get("name", o["pattern"])
        mark = "  **<- chosen**" if o.get("text") == brief.get("chosen_title") else ""
        out.append("%d. %s  _(%s; %s characters; score %s)_%s" % (i, o.get("text"), name, o.get("chars", "?"), o.get("score", "?"), mark))
    if not brief.get("titles"):
        out.append("None yet.")
    out += ["", "## Thumbnail concepts", ""]
    for c in brief.get("thumbnails") or []:
        mark = "  **<- chosen**" if str(c.get("name")) == str(brief.get("chosen_thumbnail")) else ""
        words = c.get("text") or " / ".join(str((c.get(side) or {}).get("text") or "") for side in ("left", "right")).strip(" /")
        words = " / ".join(part.strip() for part in str(words).splitlines() if part.strip())
        out.append("- **%s** (%s): \"%s\"%s%s" % (c.get("name"), c.get("layout"), words,
                                                   ("; photo: %s" % c["photo"]) if c.get("photo") else "", mark))
    if not brief.get("thumbnails"):
        out.append("None yet.")
    out += ["", "## The first 30 seconds", "",
            "- Promise: %s" % (hook.get("promise") or ""), "- Say: %s" % (hook.get("say") or ""),
            "- Show: %s" % (hook.get("show") or ""), "- On screen: %s" % (hook.get("on_screen") or ""), ""]
    out += ["## Structure", ""]
    if structure.get("segments"):
        out.append("%s, about %g minutes." % (structure.get("name") or structure.get("template"), structure.get("length_minutes") or 0))
        out.append("")
        planned = {c["title"]: c["at"] for c in D.chapters_from_structure(structure)}
        for s in structure["segments"]:
            at = D.stamp(planned[s["title"]]) if s["title"] in planned else "     "
            out.append("- %s  %s  _(%g%% of the running time)_%s" % (at, s.get("title"), float(s.get("share") or 0),
                                                                     ("  %s" % s["note"]) if s.get("note") else ""))
    else:
        out.append("Not laid out yet.")
    stage = STAGES.get(cta.get("stage"), {})
    out += ["", "## The ask", "", "- The viewer: %s" % stage.get("name", cta.get("stage")),
            "- Offer: %s" % (cta.get("offer_id") or "none"), "- Words: %s" % (cta.get("text") or ""),
            "- Link: %s" % (cta.get("link") or ""),
            "- Early: %s" % stage.get("early", ""), "- Midway: %s" % stage.get("midway", ""),
            "- At the close: %s" % stage.get("close", ""), ""]
    text = str((brief.get("description") or {}).get("text") or "").strip() or D.build(brand, brief)
    out += ["## Description", "", "```", text.rstrip(), "```", "", "## Tags", "",
            ", ".join(brief.get("tags") or []) or "None yet.", ""]
    return "\n".join(out)


def summary(brand):
    """One line per video, for `status`."""
    brand = as_brand(brand)
    rows = []
    for vid in list_ids(brand):
        try:
            b = load(brand, vid)
        except YouTubeError as e:
            rows.append({"video_id": vid, "status": "unreadable", "title": str(e), "problems": 1})
            continue
        rep = check(brand, b)
        rows.append({"video_id": vid, "status": b.get("status"), "title": b.get("chosen_title") or b.get("topic"),
                     "problems": len(rep.problems), "warnings": len(rep.warnings)})
    return rows


def deep_copy(brief):
    return copy.deepcopy(brief)
