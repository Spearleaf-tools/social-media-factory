"""plan.py - the strategy above the writing. No post is planned from a blank page.

Every slot in a plan is given, in this order:

    a JOB            reach (grow who sees the brand), lead_gen (turn attention into an enquiry),
                     or trust (let people see who they would be dealing with)
    a HOOK FAMILY    the kind of opening that suits the job
    a TEMPLATE       the skeleton of the argument
    a VISUAL FORMAT  what the image or video looks like
    a CALL TO ACTION matched to the job (see cta.py)

Three rules keep a feed from wearing people out:

  * THE MIX. Per ten posts: four reach, three lead-gen, three trust. Once an audience is warm the
    mix can shift to three, four, three (`warmed=True`). The mix is applied to any count.
  * NO MORE THAN TWO LEAD-GEN POSTS IN A ROW. A feed that asks three times running reads as a
    sales machine. Only the two built-in mixes are offered, because for those the rule can always
    be kept, whatever the count.
  * THE VISUALS SWEEP FROM POLISHED TO RAW. A batch in one visual style stops being seen. Every
    batch of two or more includes at least one polished format and at least one raw one, the same
    format never runs twice in a row when there is another to choose, and the topical/meme format
    appears at most once.

And one rule keeps a topic fresh across platforms: a topic gets a DIFFERENT SHAPE on each
platform, so the same idea reads as a series rather than a copy. Shapes come from
`playbooks/shapes/index.json`; if that file is not there, a small built-in list is used.

Platforms always come from the brand (`brand.platforms_for(identity)`). Asking for a platform the
identity does not post on is an error, never a silent skip.

    from smf.studio import plan
    slots = plan.plan_week(brand, "person", count=10)
    record = plan.plan_topic(topic, brand, "person", job="reach")
    plan.plan_run(brand, "week-of-june-9", "person")      # plans the run's approved topics
"""
from __future__ import annotations

import os

from smf import brands
from smf.studio import cta as cta_mod
from smf.studio import topics as topics_mod
from smf.studio.files import StudioError, as_brand, read_json, write_json

JOBS = {
    "reach": {"name": "Reach", "purpose": "Be seen by more of the right people. Useful enough to save or pass on.",
              "ends_with": "a save, a share or a follow; never an offer",
              "judged_by": "views, saves, shares, new followers"},
    "lead_gen": {"name": "Lead-gen", "purpose": "Turn attention into an enquiry by pointing at one real offer.",
                 "ends_with": "one offer or keyword from the brand's own library",
                 "judged_by": "enquiries, bookings, replies that start a sale"},
    "trust": {"name": "Trust", "purpose": "Show who the reader would be dealing with: beliefs, standards, history.",
              "ends_with": "a genuine question, or nothing at all",
              "judged_by": "saves, thoughtful comments, direct messages"},
}
MIX = {"reach": 4, "lead_gen": 3, "trust": 3}
WARMED_MIX = {"reach": 3, "lead_gen": 4, "trust": 3}
MAX_LEAD_GEN_IN_A_ROW = 2

# Openings, grouped by the job they serve. Within a job, the first is the one to reach for first.
HOOK_FAMILIES = [
    {"id": "against-the-clock", "job": "reach", "name": "Against the clock",
     "how": "Do something useful inside a stated time limit and show the result."},
    {"id": "side-by-side", "job": "reach", "name": "Side by side",
     "how": "Start from the same ingredients and show two different outcomes."},
    {"id": "open-question", "job": "reach", "name": "The question people argue about",
     "how": "Ask what the audience really disagrees on, then answer it with a number or a list."},
    {"id": "held-answer", "job": "reach", "name": "The held answer",
     "how": "Name the result first and keep the reason for the body."},
    {"id": "ranked", "job": "reach", "name": "Ranked from worst to best",
     "how": "Rank the common options and say why each sits where it does."},
    {"id": "start-again-plan", "job": "lead_gen", "name": "If I were starting again",
     "how": "Lay out the plan you would follow from zero, step by step."},
    {"id": "numbered-promise", "job": "lead_gen", "name": "A numbered promise",
     "how": "Promise a set number of steps or checks and deliver exactly that many."},
    {"id": "result-first", "job": "lead_gen", "name": "The result first",
     "how": "Open on a real, sourced result, then explain how it happened."},
    {"id": "kinds-of-reader", "job": "trust", "name": "Two or three kinds of reader",
     "how": "Describe two or three kinds of reader so people recognise themselves."},
    {"id": "against-the-grain", "job": "trust", "name": "Against the grain",
     "how": "State a belief the brand holds that most of its field does not, and give the reason."},
    {"id": "do-not-do-this", "job": "trust", "name": "Please do not do this",
     "how": "Warn against a common mistake the brand has seen cost people."},
    {"id": "honest-admission", "job": "trust", "name": "An honest admission",
     "how": "Say what the speaker got wrong, and what changed because of it. True stories only."},
]

# Skeletons, grouped by job, each with the shapes that carry it well.
TEMPLATES = [
    {"id": "where-are-you-now", "job": "lead_gen", "name": "Where are you now",
     "shapes": ["three-tips", "bullet-insight"]},
    {"id": "fresh-start-plan", "job": "lead_gen", "name": "The fresh-start plan",
     "shapes": ["bullet-insight", "three-tips"]},
    {"id": "result-then-method", "job": "lead_gen", "name": "Result, then method",
     "shapes": ["before-after-story", "myth-vs-reality"]},
    {"id": "half-the-checklist", "job": "lead_gen", "name": "Half the checklist now, the rest on request",
     "shapes": ["bullet-insight", "five-questions"]},
    {"id": "numbered-list", "job": "reach", "name": "The numbered list",
     "shapes": ["three-tips", "bullet-insight"]},
    {"id": "belief-flipped", "job": "reach", "name": "A common belief, flipped",
     "shapes": ["myth-vs-reality", "three-objections"]},
    {"id": "good-better-best", "job": "reach", "name": "Good, better, best",
     "shapes": ["myth-vs-reality", "three-tips"]},
    {"id": "walkthrough", "job": "reach", "name": "The walkthrough",
     "shapes": ["three-tips", "bullet-insight"]},
    {"id": "everyday-comparison", "job": "reach", "name": "The everyday comparison",
     "shapes": ["five-lessons", "bullet-insight"]},
    {"id": "quiz-first", "job": "reach", "name": "Quiz first, answer after",
     "shapes": ["five-questions", "myth-vs-reality"]},
    {"id": "how-we-got-here", "job": "trust", "name": "How we got here",
     "shapes": ["before-after-story", "five-lessons"]},
    {"id": "what-i-got-wrong", "job": "trust", "name": "What I got wrong",
     "shapes": ["five-lessons", "before-after-story"]},
    {"id": "what-we-believe", "job": "trust", "name": "What we believe",
     "shapes": ["bullet-insight", "three-objections"]},
    {"id": "line-we-will-not-cross", "job": "trust", "name": "The line we will not cross",
     "shapes": ["three-objections", "problem-agitate-solve"]},
]

# Ordered from polished to raw, so walking the list walks the spectrum.
VISUAL_FORMATS = [
    {"id": "brand-card", "name": "Brand statement card", "tier": "polished", "jobs": ["trust", "reach"]},
    {"id": "carousel", "name": "Teaching carousel", "tier": "polished", "jobs": ["reach", "lead_gen"]},
    {"id": "stat-card", "name": "Stat or proof card", "tier": "polished", "jobs": ["lead_gen", "trust"]},
    {"id": "quote-card", "name": "Quote card", "tier": "native", "jobs": ["trust", "reach"]},
    {"id": "notes-card", "name": "Notes-style card", "tier": "native", "jobs": ["reach", "lead_gen"]},
    {"id": "bold-text", "name": "Bold text on a plain ground", "tier": "raw", "jobs": ["reach", "lead_gen"]},
    {"id": "topical", "name": "Topical or meme", "tier": "raw", "jobs": ["reach"]},
    {"id": "real-photo-or-video", "name": "A real photo or a talking video", "tier": "raw", "jobs": ["trust", "reach"]},
    {"id": "screenshot", "name": "An unedited screenshot", "tier": "raw", "jobs": ["lead_gen", "trust"]},
]
ONCE_PER_BATCH = ("topical",)

FALLBACK_SHAPES = [
    {"id": "three-tips", "name": "Three tips", "best_for": ["linkedin", "instagram", "facebook"], "length": "medium",
     "identity": "any", "when": "One method the reader can use, split into three moves."},
    {"id": "myth-vs-reality", "name": "Myth against reality", "best_for": ["instagram", "twitter"], "length": "short",
     "identity": "any", "when": "The audience believes something that is holding them back."},
    {"id": "problem-agitate-solve", "name": "Problem, why it hurts, the way out", "best_for": ["linkedin", "facebook"],
     "length": "medium", "identity": "any", "when": "The reader has the problem but has not faced its cost."},
    {"id": "three-objections", "name": "Three objections, answered", "best_for": ["linkedin"], "length": "long",
     "identity": "any", "when": "People hesitate for reasons that can be answered plainly."},
    {"id": "five-lessons", "name": "Five lessons from one experience", "best_for": ["linkedin", "facebook"],
     "length": "long", "identity": "any", "when": "One real experience taught several things worth passing on."},
    {"id": "bullet-insight", "name": "One insight in bullets", "best_for": ["twitter", "linkedin"], "length": "short",
     "identity": "any", "when": "A single point that scans well as short lines."},
    {"id": "five-questions", "name": "Five questions worth asking", "best_for": ["linkedin", "facebook"],
     "length": "medium", "identity": "any", "when": "The reader needs better questions more than answers."},
    {"id": "before-after-story", "name": "Before and after, told as a story", "best_for": ["instagram", "facebook"],
     "length": "medium", "identity": "person", "when": "A true change the speaker lived through, with its evidence."},
]
_SHORT_PLATFORMS = ("twitter", "instagram", "threads", "bluesky", "tiktok", "pinterest")
_LENGTH_FIT = {True: {"short": 0, "medium": 1, "long": 2}, False: {"long": 0, "medium": 0, "short": 1}}


class PlanError(StudioError):
    """The plan that was asked for cannot be made."""


# ----------------------------------------------------------------------------- shapes
def shapes_index_file():
    return os.path.join(brands.ROOT, "playbooks", "shapes", "index.json")


def load_shapes():
    """(shapes, source). The playbook's index when it is there and usable, else the built-in list."""
    path = shapes_index_file()
    if os.path.isfile(path):
        try:
            data = read_json(path, "The shapes index (playbooks/shapes/index.json)")
        except StudioError:
            data = None
        rows = data.get("shapes") if isinstance(data, dict) else None
        shapes = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("id"):
                shapes.append({"id": str(row["id"]), "name": row.get("name") or str(row["id"]),
                               "best_for": [str(p).lower() for p in (row.get("best_for") or [])],
                               "length": row.get("length") or "medium",
                               "identity": (row.get("identity") or "any").lower(), "when": row.get("when") or ""})
        if shapes:
            return shapes, "playbooks/shapes/index.json"
    return [dict(s) for s in FALLBACK_SHAPES], "built-in list"


def shape_by_id(shape_id):
    shapes, _src = load_shapes()
    for s in shapes:
        if s["id"] == shape_id:
            return s
    raise PlanError("There is no shape called '%s'. The shapes are: %s." % (shape_id, ", ".join(s["id"] for s in shapes)))


# ----------------------------------------------------------------------------- jobs
def job_sequence(count, warmed=False):
    """The jobs for `count` slots, in posting order: the mix applied proportionally, then woven so
    lead-gen never runs more than two in a row."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > 200:
        raise PlanError("Plan between 1 and 200 posts at a time.")
    ratio = WARMED_MIX if warmed else MIX
    per = float(sum(ratio.values()))
    exact = {j: count * n / per for j, n in ratio.items()}
    share = {j: int(v) for j, v in exact.items()}
    # Hand the leftover slots to the largest remainders; ties go in a fixed order.
    order = sorted(ratio, key=lambda j: (-(exact[j] - share[j]), j))
    for i in range(count - sum(share.values())):
        share[order[i % len(order)]] += 1

    pool, sequence, run = dict(share), [], 0
    for _ in range(count):
        choices = [j for j in ("reach", "lead_gen", "trust") if pool[j] > 0]
        others = [j for j in choices if j != "lead_gen"]
        if run >= MAX_LEAD_GEN_IN_A_ROW and others:
            choices = others
        # Take whichever job has most left, so the three stay spread out; on a tie, not lead-gen.
        pick = max(choices, key=lambda j: (pool[j], j != "lead_gen"))
        sequence.append(pick)
        pool[pick] -= 1
        run = run + 1 if pick == "lead_gen" else 0
    return sequence


def _for_job(items, job):
    return [i for i in items if i["job"] == job]


def hooks_for_job(job):
    return _for_job(HOOK_FAMILIES, job)


def templates_for_job(job):
    return _for_job(TEMPLATES, job)


# ----------------------------------------------------------------------------- visuals
# What the Factory can draw by itself, with no key and no photos, for each planned kind. The
# kinds that are missing here (a real photo or video, an untouched screenshot, a topical image)
# are things a PERSON supplies. Kept here as plain data so the planner needs nothing installed;
# a test checks it against the renderer's own table so the two cannot drift apart.
DRAWS_AS = {
    "brand-card": ["headline", "alert", "split"],
    "carousel": ["carousel"],
    "stat-card": ["stat", "split"],
    "quote-card": ["post-screenshot"],
    "notes-card": ["notes"],
    "bold-text": ["bold-text"],
}
_MEDIA_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".heic", ".mp4", ".mov", ".m4v")


def has_own_media(brand):
    """True when the brand has put photos or video of its own where the Factory can use them:
    its brand kit photos, or its proof folder. Until then, planning sticks to what can be drawn."""
    for parts in (("Brand", "brand-kit", "photos"), ("Inputs", "Proof"), ("Inputs", "Edited")):
        folder = brand.path(*parts)
        try:
            if any(name.lower().endswith(_MEDIA_TYPES) for name in os.listdir(folder)):
                return True
        except OSError:
            continue
    return False


def formats_for(brand, job):
    """Formats that suit a job. A brand with no photos or video of its own is only offered the
    kinds the Factory can draw for it, so a plan never asks for a picture nobody has. When the
    brand has switched on particular formats, only those are offered, as long as at least one of
    them suits the job."""
    all_for_job = [f for f in VISUAL_FORMATS if job in f["jobs"]]
    if not has_own_media(brand):
        all_for_job = [f for f in all_for_job if f["id"] in DRAWS_AS] or all_for_job
    enabled = set((brand.data.get("visual") or {}).get("formats_enabled") or [])
    chosen = [f for f in all_for_job if f["id"] in enabled]
    return chosen or all_for_job


def visual_rotation(brand, jobs):
    """One format per slot. A cursor sweeps the polished-to-raw list across the batch; each slot
    takes the format for its job nearest the cursor, preferring ones used least so far."""
    n, used, chosen = len(jobs), {}, []
    for i, job in enumerate(jobs):
        cursor = (i * (len(VISUAL_FORMATS) - 1)) / float(max(1, n - 1)) if n > 1 else 0
        options = [f for f in formats_for(brand, job)
                   if not (f["id"] in ONCE_PER_BATCH and used.get(f["id"], 0) >= 1)] or formats_for(brand, job)
        previous = chosen[-1]["id"] if chosen else None
        options = [f for f in options if f["id"] != previous] or options      # never the same look twice running
        pick = min(options, key=lambda f: (abs(VISUAL_FORMATS.index(f) - cursor), used.get(f["id"], 0),
                                           VISUAL_FORMATS.index(f)))
        used[pick["id"]] = used.get(pick["id"], 0) + 1
        chosen.append(pick)
    if n >= 2:
        # The guarantee: if the sweep left out one end of the spectrum, swap one slot to supply it,
        # without taking away the only slot that supplies the other end.
        for need, other, slots in (("polished", "raw", range(n)), ("raw", "polished", range(n - 1, -1, -1))):
            if any(f["tier"] == need for f in chosen):
                continue
            for i in slots:
                beside = {chosen[k]["id"] for k in (i - 1, i + 1) if 0 <= k < n}
                swap = [f for f in formats_for(brand, jobs[i]) if f["tier"] == need]
                swap = [f for f in swap if f["id"] not in beside] or swap
                only_other = chosen[i]["tier"] == other and sum(1 for f in chosen if f["tier"] == other) == 1
                if swap and not only_other:
                    chosen[i] = swap[0]
                    break
    return chosen


# ----------------------------------------------------------------------------- platforms and shapes
def platforms_for(brand, identity, platforms=None):
    """The identity's own platforms, or the subset asked for. A platform the identity does not
    post on is refused, because a post planned for it could never go out."""
    own = brand.platforms_for(identity)
    if not platforms:
        return list(own)
    asked = []
    for p in platforms:
        p = str(p).strip().lower()
        if p and p not in asked:
            asked.append(p)
    missing = [p for p in asked if p not in own]
    if missing:
        raise PlanError("%s does not post on %s as '%s' (it has: %s). Link the account first, or leave it out."
                        % (brand.name, ", ".join(missing), identity, ", ".join(own)))
    return asked


def assign_shapes(platforms, kind, preferred=(), pinned=None, batch_use=None, avoid=()):
    """A different shape for every platform.

    `pinned` are shapes a person already chose ({platform: shape_id}); they are kept. The rest are
    filled most-constrained platform first, preferring a shape that suits the platform, then one
    the template carries well, then the platform's rank in the shape's own list, then the right
    length, then the one used least in this batch.
    A shape repeats only when there are more platforms than usable shapes; the repeats are listed."""
    shapes, _src = load_shapes()
    usable = [s for s in shapes if s["identity"] in ("any", kind)] or shapes
    known = {s["id"] for s in shapes}
    batch_use = batch_use if batch_use is not None else {}
    result, taken = {}, set()
    for p in platforms:
        pin = (pinned or {}).get(p)
        pin = pin.get("shape") if isinstance(pin, dict) else pin
        if pin:
            if pin not in known:
                raise PlanError("There is no shape called '%s' (chosen for %s). The shapes are: %s."
                                % (pin, p, ", ".join(sorted(known))))
            result[p] = pin
            taken.add(pin)

    def suits(shape, platform):
        return platform in shape["best_for"]

    open_platforms = [p for p in platforms if p not in result]
    open_platforms.sort(key=lambda p: (sum(1 for s in usable if suits(s, p)) or len(usable), platforms.index(p)))
    repeats = []
    for p in open_platforms:
        fresh = [s for s in usable if s["id"] not in taken]
        pool = fresh or usable
        if not fresh:
            repeats.append(p)
        short = p in _SHORT_PLATFORMS
        pick = min(pool, key=lambda s: (0 if suits(s, p) else 1, 1 if s["id"] in avoid else 0,
                                        0 if s["id"] in preferred else 1,
                                        s["best_for"].index(p) if suits(s, p) else 0,      # listed strongest first
                                        _LENGTH_FIT[short].get(s["length"], 1),
                                        batch_use.get(s["id"], 0), usable.index(s)))
        result[p] = pick["id"]
        taken.add(pick["id"])
    for p in platforms:
        batch_use[result[p]] = batch_use.get(result[p], 0) + 1
    return {p: result[p] for p in platforms}, repeats


# ----------------------------------------------------------------------------- plan a week
def plan_week(brand, identity, count=None, platforms=None, topics=None, warmed=False):
    """`count` planned slots. With `topics`, each slot is bound to one topic in the order given
    (and `count` defaults to how many there are); slots beyond the topics are left to fill."""
    brand = as_brand(brand)
    brand.identity(identity)
    topics = list(topics or [])
    count = count if count is not None else (len(topics) or 10)
    jobs = job_sequence(count, warmed=warmed)
    visuals = visual_rotation(brand, jobs)
    plats = platforms_for(brand, identity, platforms)
    library = cta_mod.load_library(brand)
    turn = {"reach": 0, "lead_gen": 0, "trust": 0}
    cta_counts, slots = {}, []
    for i, job in enumerate(jobs):
        k = turn[job]
        turn[job] += 1
        hook = hooks_for_job(job)[k % len(hooks_for_job(job))]
        template = templates_for_job(job)[k % len(templates_for_job(job))]
        choice = cta_mod.select_cta(brand, job, plats[0], cta_counts, library=library)
        topic = topics[i] if i < len(topics) else None
        slots.append({
            "slot": i + 1, "job": job, "job_name": JOBS[job]["name"],
            "hook_family": {"id": hook["id"], "name": hook["name"], "how": hook["how"]},
            "template": {"id": template["id"], "name": template["name"]},
            "visual_format": {"id": visuals[i]["id"], "name": visuals[i]["name"], "tier": visuals[i]["tier"],
                              "draws_as": list(DRAWS_AS.get(visuals[i]["id"], []))},
            "cta_id": choice["cta_id"], "cta_kind": choice["kind"], "cta_text": choice["text"],
            "cta_instruction": choice["instruction"], "cta_note": choice["note"],
            "platforms": list(plats),
            "topic_id": (topic or {}).get("topic_id") if isinstance(topic, dict) else None,
            "topic_title": (topic or {}).get("title") if isinstance(topic, dict) else (topic if topic else None),
        })
    return slots


def check_plan(slots):
    """The promises in this module, checked against a finished plan. Returns a list of problems."""
    problems, run = [], 0
    for s in slots:
        run = run + 1 if s["job"] == "lead_gen" else 0
        if run > MAX_LEAD_GEN_IN_A_ROW:
            problems.append("slots %d to %d are all lead-gen" % (s["slot"] - run + 1, s["slot"]))
        if s["job"] != "lead_gen" and s["cta_kind"] in ("offer", "keyword"):
            problems.append("slot %d is a %s post but ends on an offer" % (s["slot"], s["job"]))
    tiers = {s["visual_format"]["tier"] for s in slots}
    if len(slots) >= 2 and not {"polished", "raw"} <= tiers:
        problems.append("the visuals do not span polished to raw")
    return problems


# ----------------------------------------------------------------------------- plan one topic
def plan_topic(topic, brand, identity, job, platforms=None, batch_use=None, visual=None):
    """Add this identity's plan to a topic record and return the record.

    Everything already on the record is kept. The plan goes under `plans[identity]`:
      {job, hook_family, template, visual_format,
       platform_shapes: {platform: {shape, hook_family, template, cta_id, cta_kind}}}
    Shapes a person pinned in the record's own `platform_shapes` are honoured. When another
    identity of the same brand has already planned this topic, its shapes are avoided where
    possible, so the founder and the company page do not publish the same structure."""
    brand = as_brand(brand)
    kind = brand.identity(identity)["kind"]
    if job not in JOBS:
        raise PlanError("'%s' is not a job a post can have. The jobs are: %s." % (job, ", ".join(JOBS)))
    if not isinstance(topic, dict) or not str(topic.get("title") or "").strip():
        raise PlanError("plan_topic needs a topic record with a title (see topics.new_topic).")
    record = dict(topic)
    record.setdefault("topic_id", topics_mod.slug(record["title"]))
    record.setdefault("lane", "evergreen")
    record.setdefault("status", "proposed")
    record.setdefault("source_ref", "")
    record.setdefault("proof_ids", [])
    record.setdefault("platform_shapes", {})
    record.setdefault("note", "")

    plats = platforms_for(brand, identity, platforms)
    hooks, templates = hooks_for_job(job), templates_for_job(job)
    preferred = [s for t in templates for s in t["shapes"]]
    plans = dict(record.get("plans") or {})
    avoid = {v["shape"] for other, p in plans.items() if other != identity
             for v in (p.get("platform_shapes") or {}).values() if isinstance(v, dict) and v.get("shape")}
    shapes, repeats = assign_shapes(plats, kind, preferred=preferred, pinned=record["platform_shapes"],
                                    batch_use=batch_use, avoid=avoid)
    library = cta_mod.load_library(brand)
    cta_counts, per_platform = {}, {}
    for k, p in enumerate(plats):
        choice = cta_mod.select_cta(brand, job, p, cta_counts, library=library)
        # Prefer a template that carries this platform's shape; otherwise rotate.
        fitting = [t for t in templates if shapes[p] in t["shapes"]]
        template = fitting[k % len(fitting)] if fitting else templates[k % len(templates)]
        per_platform[p] = {"shape": shapes[p], "hook_family": hooks[k % len(hooks)]["id"], "template": template["id"],
                           "cta_id": choice["cta_id"], "cta_kind": choice["kind"]}
    visual = visual or formats_for(brand, job)[0]
    plans[identity] = {"job": job, "hook_family": {"id": hooks[0]["id"], "name": hooks[0]["name"]},
                       "template": {"id": templates[0]["id"], "name": templates[0]["name"]},
                       "visual_format": {"id": visual["id"], "name": visual["name"], "tier": visual["tier"],
                                         "draws_as": list(DRAWS_AS.get(visual["id"], []))},
                       "platform_shapes": per_platform, "shape_repeats": repeats}
    record["plans"] = plans
    return record


# ----------------------------------------------------------------------------- plan a run
def plan_run(brand, run, identity, platforms=None, warmed=False):
    """Plan every APPROVED topic in a run for one identity, save the plans back into the run's
    topics file, and write the slot list beside it as plan-<identity>.json. Returns {"slots", "topics", ...}."""
    brand = as_brand(brand)
    brand.identity(identity)
    approved = topics_mod.approved_topics(brand, run)
    if not approved:
        raise PlanError("The run '%s' has no approved topics yet. Approve at least one topic, then plan again." % run)
    slots = plan_week(brand, identity, count=len(approved), platforms=platforms, topics=approved, warmed=warmed)
    batch_use, planned = {}, {}
    for slot, topic in zip(slots, approved):
        visual = next(f for f in VISUAL_FORMATS if f["id"] == slot["visual_format"]["id"])
        planned[topic["topic_id"]] = plan_topic(topic, brand, identity, slot["job"], platforms=platforms,
                                                batch_use=batch_use, visual=visual)
    everything = [planned.get(t.get("topic_id"), t) for t in topics_mod.load_run(brand, run)]
    warnings = topics_mod.save_run(brand, run, everything)
    _shapes, shapes_from = load_shapes()
    summary = {"brand": brand.id, "run": run, "identity": identity, "warmed": bool(warmed),
               "shapes_from": shapes_from, "slots": slots}
    write_json(os.path.join(os.path.dirname(topics_mod.run_path(brand, run)), "plan-%s.json" % identity), summary)
    return {"slots": slots, "topics": [planned[t["topic_id"]] for t in approved], "warnings": warnings,
            "problems": check_plan(slots), "shapes_from": shapes_from}
