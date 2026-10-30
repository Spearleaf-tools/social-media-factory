"""contract.py - what Claude writes FROM, and the check the draft has to pass afterwards.

`build_contract` gathers, for ONE post (a brand, one of its identities, a platform, an approved
topic, a shape and a job), everything the writer is allowed to use:

    who is speaking      the identity, the brand's voice with that identity's overrides, and the
                         brand's OWN words read from the files it listed as voice sources (from
                         the thinking journal, only the owner's own public entries)
    who inspires them    the owner's influences, for structure and format only, never to copy
    who is listening     the audience, and what is different about them on this platform
    the platform         its mechanics from the playbook (and a warning if those are old)
    the shape            the structure this post takes
    the ending           the call to action its job allows
    the rules            the brand's style rules, never-mention list and compliance terms
    the facts            the verified facts, research stats and linked proof for this topic

and ends on the rule that governs all of it: use only what is in this contract; never invent a
fact, a number, a quote or a customer. When the brand has no facts, the contract says so and
tells the writer to state none, instead of leaving a gap to be filled with something plausible.

`validate_draft` is the other half. It runs the copy checker, traces every number, compares the
draft with what the brand has already written, checks the ending against the job, and runs the
takeaway pre-screens. It reads EVERY field that publishes with the post (the caption, each tweet
of a thread, the first comment, the alt text), because a claim in any of them reaches a reader.
It returns ONE report in plain language, with a `sourcing` value:

    passed       every number traced and was confirmed, every claim is one the brand has written
                 down, the topic says where it came from, nothing unverifiable
    unverified   nothing is provably wrong, but something cannot be traced: no source on the
                 topic, a customer story or quote with no proof linked, proof that cannot be
                 found, a figure that matches a fact about something else, a figure whose only
                 evidence is research nobody has confirmed, or a claim in words the brand's own
                 files do not make
    blocked      a number that traces to nothing, or one that comes only from private proof

Missing evidence is never `passed`. A post may still go to review while `unverified`; the
reviewer sees the flag and decides.
"""
from __future__ import annotations

import json
import os
import re

from smf import brands
from smf.studio import cta as cta_mod
from smf.studio import dedup, grounding, journal, platforms, quality
from smf.studio import plan as plan_mod
from smf.studio import topics as topics_mod
from smf.studio.files import StudioError, as_brand, inside, own_lines, read_text, relative, text_files
from smf.studio import posts as posts_mod
from smf.studio.lint import PLATFORM_CHAR_LIMITS, Rules
from smf.studio.posts import Post

OWN_WORDS_BUDGET = 12000          # characters of the brand's own writing shown to the writer
SOURCE_EXCERPT_CHARS = 3000
SHAPE_DOC_CHARS = 6000
HARD_RULE = ("Use only what is in this contract. Never invent a fact, a number, a quote or a customer. "
             "If something you want to say is not here, leave it out and say what was missing.")


class ContractError(StudioError):
    """The contract cannot be built as asked."""


class Contract(object):
    """The contract as data (`.data`, a plain dict) and as a page to read (`.markdown`)."""

    def __init__(self, data, markdown):
        self.data = data
        self.markdown = markdown

    def __getitem__(self, key):
        return self.data[key]

    def to_json(self):
        return json.dumps(self.data, indent=2, ensure_ascii=False)


# ----------------------------------------------------------------------------- who is speaking
def voice_for(brand, identity_id):
    voice = dict(brand.data.get("voice") or {})
    override = (voice.get("by_identity") or {}).get(identity_id)
    out = {"register": voice.get("register", ""), "do": list(voice.get("do") or []),
           "dont": list(voice.get("dont") or []), "signature_phrases": list(voice.get("signature_phrases") or []),
           "identity_note": "", "point_of_view": ""}
    if isinstance(override, str):
        out["identity_note"] = override.strip()
    elif isinstance(override, dict):
        for key in ("register", "do", "dont", "signature_phrases"):
            if override.get(key):
                out[key] = override[key] if isinstance(override[key], str) else list(override[key])
        out["identity_note"] = str(override.get("note") or "").strip()
        out["point_of_view"] = str(override.get("pov") or "").strip()
    return out


def load_own_words(brand, budget=OWN_WORDS_BUDGET):
    """The brand's own writing, from the files it named in voice.sources plus Studio/exemplars.
    Returns (chunks, notes). Blank templates are skipped, because guidance text is not a voice.
    Whole files are kept in order until the budget is used; a single huge file is cut to fit."""
    brand = as_brand(brand)
    notes, paths = [], []
    for rel in (brand.data.get("voice") or {}).get("sources") or []:
        path = inside(brand, rel)
        if path is None:
            notes.append("The voice source '%s' is outside the brand's folder, so it was not read." % rel)
        elif os.path.isfile(path):
            paths.append(path)
        elif os.path.isdir(path):
            paths.extend(text_files(path, (".md", ".txt")))
    paths.extend(text_files(brand.path("Studio", "exemplars"), (".md", ".txt")))

    chunks, used, left_out, seen = [], 0, 0, set()
    for path in paths:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        rel = relative(brand, path)
        if journal.is_journal(brand, path):
            body = journal.owner_words(brand)            # their own public entries; never private, never Claude's notes
        else:
            text, _cut = read_text(path)
            body = "\n".join(own_lines(brand, rel, text))
        if not body:
            continue
        if used + len(body) > budget:
            if not chunks:
                chunks.append({"file": rel, "text": body[:budget], "shortened": True})
                used = budget
            else:
                left_out += 1
            continue
        chunks.append({"file": rel, "text": body, "shortened": False})
        used += len(body)
    if left_out:
        notes.append("%d more file(s) of their own words were left out to keep this page a readable length." % left_out)
    return chunks, notes


# ----------------------------------------------------------------------------- the topic
def _check_topic(brand, topic):
    if not isinstance(topic, dict) or not str(topic.get("title") or "").strip():
        raise ContractError("A contract is written for one topic record (with a title). Pick a topic from a run first.")
    label = "'%s'" % topic["title"]
    if topic.get("status") != "approved":
        raise ContractError("The topic %s has not been approved (it is '%s'). Only approved topics are written."
                            % (label, topic.get("status") or "undecided"))
    if not str(topic.get("source_ref") or "").strip():
        raise ContractError("The topic %s does not say where in %s's own material it comes from. Add a source_ref "
                            "before it is written." % (label, brand.name))
    if topics_mod.resolve_source_ref(brand, topic["source_ref"]).get("private"):
        raise ContractError("The topic %s comes from a private journal entry. Private thinking is never written into "
                            "a post. Make the entry public first, only if the owner says so." % label)


def _source_material(brand, topic):
    found = topics_mod.resolve_source_ref(brand, topic.get("source_ref"))
    out = {"source_ref": topic.get("source_ref", ""), "kind": found["kind"], "found": found["ok"],
           "detail": found["detail"], "excerpt": ""}
    if found["kind"] == "journal" and found["ok"]:
        entry = found["entry"]
        out["detail"] = "%s's journal, %s (%s)" % (brand.name, entry["date"], "their own words" if entry["kind"] == "owner"
                                                   else "a note from Claude, not their words")
        out["excerpt"] = (("Claude asked: %s\n\n" % entry["asked"]) if entry["asked"] else "") + entry["text"]
        out["excerpt"] = out["excerpt"][:SOURCE_EXCERPT_CHARS]
    elif found["kind"] == "file" and found["ok"] and journal.is_journal(brand, inside(brand, found["detail"])):
        book = journal.load(brand)
        public = ["%s: %s" % (e["date"], e["text"]) for e in book["entries"] if not e["private"] and e["kind"] == "owner"]
        out["excerpt"] = "\n".join(book["older"] + public)[:SOURCE_EXCERPT_CHARS]
    elif found["kind"] == "file" and found["ok"]:
        path = inside(brand, found["detail"])
        text, _cut = read_text(path, SOURCE_EXCERPT_CHARS * 3)
        out["excerpt"] = "\n".join(own_lines(brand, found["detail"], text))[:SOURCE_EXCERPT_CHARS]
    return out


def _shape_block(shape_id, kind, warnings):
    shape = plan_mod.shape_by_id(shape_id)
    if shape["identity"] not in ("any", kind):
        warnings.append("The shape '%s' is meant for a %s voice, and this identity is a %s. It can work, but "
                        "check it reads naturally." % (shape["id"], shape["identity"], kind))
    doc = os.path.join(brands.ROOT, "playbooks", "shapes", shape["id"] + ".md")
    structure, example_left_out = "", False
    if os.path.isfile(doc):
        text, _cut = read_text(doc)
        structure, example_left_out = _structure_only(text)
    return {"id": shape["id"], "name": shape["name"], "when": shape["when"], "length": shape["length"],
            "structure": structure[:SHAPE_DOC_CHARS], "example_left_out": example_left_out}


def _structure_only(text):
    """A shape's page, fitted into a contract: the structure stays, the worked example goes.
    An example is full of invented details, and everything in a contract reads as usable, so an
    example left in would be an invitation to borrow a made-up fact. Headings are pushed down two
    levels so the page sits inside the contract's own outline."""
    kept, cut = [], False
    for line in text.splitlines():
        if re.match(r"^#{1,6}\s+(?:a\s+)?worked\s+example", line, re.IGNORECASE):
            cut = True
            break
        if line.startswith(">") or (line.startswith("# ") and not kept):
            continue
        kept.append("##" + line if line.startswith("#") else line)
    return "\n".join(kept).strip(), cut


def _planned(topic, identity, platform):
    return ((((topic.get("plans") or {}).get(identity) or {}).get("platform_shapes") or {}).get(platform)) or {}


def _cta_for(brand, topic, identity, platform, job, used_counts):
    library = cta_mod.load_library(brand)
    wanted = _planned(topic, identity, platform).get("cta_id")
    if wanted and job == "lead_gen":
        for c in cta_mod.eligible_for_lead_gen(library, platform):
            if c["id"] == wanted:                 # the plan already chose this one; keep the promise
                return cta_mod.select_cta(brand, job, platform, used_counts, library={"ctas": [c]})
    return cta_mod.select_cta(brand, job, platform, used_counts, library=library)


def _number_text(value):
    return "%d" % value if float(value).is_integer() else "%g" % value


# ----------------------------------------------------------------------------- build
def build_contract(brand, identity, platform, topic, shape, job, used_counts=None, today=None):
    """Everything the writer may use for one post. Raises a plain error for an unknown brand,
    identity, shape or job, for a platform the identity does not post on, and for a topic that is
    not approved or has no source."""
    brand = as_brand(brand)
    who = brand.identity(identity)
    platform = str(platform or "").strip().lower()
    if platform not in brand.platforms_for(identity):
        raise ContractError("%s does not post on %s as '%s' (it has: %s)."
                            % (brand.name, platform or "that platform", identity,
                               ", ".join(brand.platforms_for(identity))))
    if job not in plan_mod.JOBS:
        raise ContractError("'%s' is not a job a post can have. The jobs are: %s." % (job, ", ".join(plan_mod.JOBS)))
    _check_topic(brand, topic)

    warnings = []
    rules_book = platforms.load()
    stale = rules_book.warning(today)
    if stale:
        warnings.append(stale)
    mechanics = rules_book.mechanics_for(platform)
    if not mechanics.get("known"):
        warnings.append(mechanics["note"])

    voice = voice_for(brand, identity)
    own_words, word_notes = load_own_words(brand)
    warnings.extend(word_notes)
    audience = brand.data.get("audience") or {}
    here = (audience.get("by_platform") or {}).get(platform)

    proof_ids = list(topic.get("proof_ids") or [])
    topic_text = " ".join(str(topic.get(k) or "") for k in ("title", "pillar", "note", "source_ref"))
    evidence = grounding.facts_for_topic(brand, topic_text, proof_ids)
    warnings.extend(evidence["notes"])
    if evidence["unknown_proof_ids"]:
        warnings.append("This topic links proof that is not in the proof library: %s."
                        % ", ".join(evidence["unknown_proof_ids"]))
    usable_proof = [p for p in evidence["proof"] if p.get("may_publish") in ("anonymised", "yes")]
    private_proof = [p for p in evidence["proof"] if p.get("may_publish") not in ("anonymised", "yes")]
    numbers = set()
    for f in evidence["facts"]:
        numbers |= set(f["values"])
    for s in evidence["stats"]:
        if s["confirmed"]:                  # research nobody has confirmed is background, never a figure to state
            numbers |= {n["value"] for n in grounding.extract_numbers(s["finding"])}
    for p in usable_proof:
        numbers |= {n["value"] for n in grounding.extract_numbers("%s. %s" % (p.get("title", ""), p.get("detail", "")))}

    style = brand.style
    comp = brand.data.get("compliance") or {}
    ending = _cta_for(brand, topic, identity, platform, job, used_counts)
    if ending.get("note"):
        warnings.append(ending["note"])
    planned = _planned(topic, identity, platform)
    hook = next((h for h in plan_mod.HOOK_FAMILIES if h["id"] == planned.get("hook_family")), None)

    data = {
        "brand": {"id": brand.id, "name": brand.name,
                  "what_we_do": (brand.data.get("business") or {}).get("what_we_do", ""),
                  "regulated": (brand.data.get("business") or {}).get("regulated", "none")},
        "speaker": {"identity": identity, "kind": who["kind"], "display_name": who["display_name"],
                    "role": who.get("role", ""),
                    "person_or_company": ("One person speaking. Write as \"I\". \"We\" only for things the team does."
                                          if who["kind"] == "person" else
                                          "The company speaking. Write to \"you\", as \"we\". Never \"I\"."),
                    "voice": voice, "own_words": own_words},
        "influences": {"people": topics_mod.influences(brand), "rule": topics_mod.INFLUENCE_RULE},
        "audience": {"who": audience.get("who", ""), "problems": list(audience.get("problems") or []),
                     "questions_they_ask": list(audience.get("questions_they_ask") or []),
                     "on_this_platform": here if here else ""},
        "platform": {"name": platform, "hard_character_limit": PLATFORM_CHAR_LIMITS.get(platform),
                     "mechanics": mechanics, "universal_rules": rules_book.universal_rules,
                     "rules_researched": rules_book.meta.get("last_researched", ""), "rules_are_old": bool(stale)},
        "topic": {"topic_id": topic.get("topic_id", ""), "title": topic["title"], "lane": topic.get("lane") or "evergreen",
                  "pillar": topic.get("pillar", ""), "note": topic.get("note", ""),
                  "source": _source_material(brand, topic)},
        "job": dict(plan_mod.JOBS[job], id=job),
        "hook_family": hook,
        "shape": _shape_block(shape, who["kind"], warnings),
        "cta": ending,
        "rules": {"no_long_dashes": bool(style["no_em_dashes"]), "max_sentence_words": style["max_sentence_words"],
                  "max_paragraph_words": style["max_paragraph_words"],
                  "max_paragraph_sentences": style["max_paragraph_sentences"],
                  "no_tags_here": platform in [p.lower() for p in style["no_tags_on"]],
                  "plain_language_pack": bool(style["plain_language_pack"]),
                  "banned_words": list(style["banned_words"]), "banned_phrases": list(style["banned_phrases"]),
                  "never_mention": list(brand.data.get("never_mention") or []),
                  "own_brands": list(brand.data.get("own_brands") or []),
                  "never_publish_terms": list(comp.get("drop_terms") or []),
                  "needs_sign_off_terms": list(comp.get("hold_terms") or []),
                  "disclaimer": comp.get("disclaimer", ""), "sign_off_by": comp.get("sign_off_by", "")},
        "facts": {"brand_facts": evidence["facts"], "research_stats": evidence["stats"],
                  "research_stats_left_out": evidence["stats_left_out"], "proof": usable_proof,
                  "private_proof": [{"proof_id": p["proof_id"], "title": p["title"]} for p in private_proof],
                  "numbers_you_may_state": sorted(numbers),
                  "none": not (evidence["facts"] or evidence["stats"] or usable_proof)},
        "hard_rule": HARD_RULE,
        "warnings": warnings,
    }
    return Contract(data, render_markdown(data))


# ----------------------------------------------------------------------------- the readable page
def _bullets(items, empty="- (nothing recorded)"):
    items = [i for i in (items or []) if str(i).strip()]
    return ["- %s" % i for i in items] if items else [empty]


def _length_text(target):
    if isinstance(target, dict):
        low, high = target.get("min"), target.get("max")
        if low and high:
            return "%s to %s characters" % (low, high)
        return ", ".join("%s: %s" % (k, v) for k, v in target.items())
    return str(target or "")


def render_markdown(c):
    sp, au, pf, tp, fx, ru = c["speaker"], c["audience"], c["platform"], c["topic"], c["facts"], c["rules"]
    mech = pf["mechanics"]
    out = ["# Write one %s post for %s" % (pf["name"], c["brand"]["name"]), "",
           "**The rule above every other:** " + c["hard_rule"], ""]
    if c["warnings"]:
        out += ["## Before you start"] + _bullets(c["warnings"]) + [""]

    out += ["## 1. Who is speaking",
            "%s%s (identity `%s`)." % (sp["display_name"], ", " + sp["role"] if sp["role"] else "", sp["identity"]),
            sp["person_or_company"], "", "How they sound: " + (sp["voice"]["register"] or "(not described yet)")]
    if sp["voice"]["point_of_view"]:
        out.append("Point of view the brand chose for this identity: " + sp["voice"]["point_of_view"])
    if sp["voice"]["identity_note"]:
        out.append("For this identity: " + sp["voice"]["identity_note"])
    out += ["", "They do:"] + _bullets(sp["voice"]["do"]) + ["They do not:"] + _bullets(sp["voice"]["dont"])
    out += ["Phrases that are really theirs (use exactly, and only where natural):"] + _bullets(sp["voice"]["signature_phrases"])
    out += ["", "### Their own words"]
    if sp["own_words"]:
        out.append("Echo this rhythm and vocabulary. Do not copy sentences, and do not take facts from here "
                   "unless they also appear in section 7.")
        for chunk in sp["own_words"]:
            out += ["", "From %s%s:" % (chunk["file"], " (shortened)" if chunk["shortened"] else ""), "", chunk["text"]]
    else:
        out.append("There are no samples of their own writing yet. Write plainly in the register above, and do not "
                   "imitate a voice you have not been shown.")
    if c["influences"]["people"]:
        out += ["", "### Who inspires them", c["influences"]["rule"]]
        out += ["- %s%s" % (i["name"], (": " + i["why"]) if i["why"] else "") for i in c["influences"]["people"]]

    out += ["", "## 2. Who they are talking to", au["who"] or "(not described yet)"]
    if au["on_this_platform"]:
        here = au["on_this_platform"]
        out.append("On %s: %s" % (pf["name"], here if isinstance(here, str) else json.dumps(here, ensure_ascii=False)))
    out += ["Their problems:"] + _bullets(au["problems"]) + ["Questions they really ask:"] + _bullets(au["questions_they_ask"])

    out += ["", "## 3. The topic", "**%s**  (lane: %s%s)" % (tp["title"], tp["lane"],
                                                                 ", pillar: " + tp["pillar"] if tp["pillar"] else "")]
    src = tp["source"]
    out.append("Where it comes from: %s%s" % (src["source_ref"], "" if src["found"] else
                                              "  (this pointer could not be found; treat the topic title as all you have)"))
    if src["found"] and src["kind"] not in ("note", "file") and src["detail"]:
        out.append("That is: " + str(src["detail"]))
    if src["excerpt"]:
        out += ["", "From that file:", "", src["excerpt"]]
    if tp["note"]:
        out.append("Note from planning: " + tp["note"])

    job = c["job"]
    out += ["", "## 4. The job of this post: %s" % job["name"], job["purpose"],
            "It ends with: %s. It is judged by: %s." % (job["ends_with"], job["judged_by"])]
    if c["hook_family"]:
        out.append("Planned opening: %s. %s" % (c["hook_family"]["name"], c["hook_family"]["how"]))

    shape = c["shape"]
    out += ["", "## 5. The shape: %s (`%s`)" % (shape["name"], shape["id"]), shape["when"]]
    if shape["structure"]:
        out += ["", shape["structure"]]
    if shape.get("example_left_out"):
        out += ["", "(The shape's own page has a worked example. It is invented, so it is left out here: nothing in "
                    "it is a fact about this brand.)"]

    out += ["", "## 6. How %s wants it written" % pf["name"]]
    if mech.get("known"):
        out.append("Length: aim for %s. Hard limit: %s characters."
                   % (_length_text(mech.get("target_len")) or "a natural length", mech.get("max_len") or pf["hard_character_limit"]))
        out += ["Opening line: " + str(mech.get("opening_line_pattern") or ""), "", "Structure:"]
        out += _bullets(mech.get("structure_template"))
        out += ["Do:"] + _bullets(mech.get("do")) + ["Do not:"] + _bullets(mech.get("dont"))
        out += ["Asking for something on this platform: " + str(mech.get("cta_policy") or ""),
                "Hashtags: " + str(mech.get("hashtag_policy") or "")]
        if mech.get("preferred_formats"):
            out += ["Formats that do well here:"] + _bullets(mech.get("preferred_formats"))
    else:
        out.append(mech.get("note", ""))
        if pf["hard_character_limit"]:
            out.append("Hard limit: %s characters." % pf["hard_character_limit"])
    if pf["universal_rules"]:
        out += ["", "On every platform:"] + _bullets(pf["universal_rules"])

    ending = c["cta"]
    out += ["", "## 7. What you may state as fact"]
    if fx["none"]:
        out.append("There are no verified facts, research stats or usable proof for this topic. State NO numbers, "
                   "statistics, results, quotes or customer stories. Teach, explain and give an opinion instead.")
    else:
        if fx["brand_facts"]:
            out += ["The brand's verified facts:"] + ["- %s  (source: %s)" % (f["claim"], f["source"]) for f in fx["brand_facts"]]
        if fx["research_stats"]:
            out += ["Research the brand collected (credit the source when you use one):"]
            out += ["- %s  (source: %s%s)%s" % (s["finding"], s["source"], ", " + s["confidence"] + " confidence"
                                                if s["confidence"] else "",
                                                "  NOT CONFIRMED: %s. Read it as background; do not state its "
                                                "figures." % s["not_confirmed_because"] if not s["confirmed"] else "")
                   for s in fx["research_stats"]]
            if fx["research_stats_left_out"]:
                out.append("(%d more stats are in the brand's research files.)" % fx["research_stats_left_out"])
        if fx["proof"]:
            out += ["Proof linked to this topic:"]
            for p in fx["proof"]:
                care = ("Remove names and anything that identifies the person or business."
                        if p.get("may_publish") == "anonymised" or p.get("names_third_party") else "May be used as it is.")
                out.append("- %s [%s] %s. %s  (source: %s) %s" % (p["proof_id"], p["kind"], p["title"],
                                                                 p.get("detail") or "", p.get("source") or "", care))
        out.append("The only numbers you may state: %s. Every other number will be caught."
                   % (", ".join(_number_text(n) for n in fx["numbers_you_may_state"]) or "none"))
    if fx["private_proof"]:
        out.append("Private background, NOT for publication (do not state its details or figures): "
                   + ", ".join("%s %s" % (p["proof_id"], p["title"]) for p in fx["private_proof"]))

    out += ["", "## 8. How it ends", ending["instruction"]]
    if ending.get("text"):
        out += ["", "    " + ending["text"]]
        if ending.get("link"):
            out.append("Link: " + ending["link"])
    out.append("Do not invent a different call to action, a keyword, a discount or a deadline.")

    out += ["", "## 9. The brand's rules (the checker enforces these)"]
    rules = []
    if ru["no_long_dashes"]:
        rules.append("No long dashes. Use a comma, a full stop or brackets.")
    rules.append("Sentences of %s words or fewer. Paragraphs of %s words and %s sentences or fewer. Lists are fine."
                 % (ru["max_sentence_words"], ru["max_paragraph_words"], ru["max_paragraph_sentences"]))
    if ru["no_tags_here"]:
        rules.append("No @mentions and no #hashtags on %s." % pf["name"])
    if ru["plain_language_pack"]:
        rules.append("Plain language: no hype words, no filler openers, no \"not only X but Y\".")
    if ru["banned_words"] or ru["banned_phrases"]:
        rules.append("Never use: " + ", ".join("\"%s\"" % w for w in ru["banned_words"] + ru["banned_phrases"]) + ".")
    if ru["never_mention"]:
        rules.append("Never name: %s. Describe them by what they do instead." % ", ".join(ru["never_mention"]))
    if ru["own_brands"]:
        rules.append("Names that are fine to use: %s." % ", ".join(ru["own_brands"]))
    if ru["never_publish_terms"]:
        rules.append("Claims that must never be published: %s." % ", ".join("\"%s\"" % t for t in ru["never_publish_terms"]))
    if ru["needs_sign_off_terms"]:
        rules.append("These need the disclaimer and a sign-off%s before they ship: %s."
                     % (" from " + ru["sign_off_by"] if ru["sign_off_by"] else "",
                        ", ".join("\"%s\"" % t for t in ru["needs_sign_off_terms"])))
    if ru["disclaimer"]:
        rules.append("The brand's disclaimer: " + ru["disclaimer"])
    if c["brand"]["regulated"] not in ("", "none", None):
        rules.append("This is a regulated field (%s). Promise no outcomes, and give no individual advice."
                     % c["brand"]["regulated"])
    out += _bullets(rules)

    out += ["", "## 10. Before you hand it back",
            "- The first line promises something the reader can check: a number, a list, \"here is\", or how or why.",
            "- The body gives at least one concrete move.",
            "- Every number is in section 7. Every name is allowed by section 9.",
            "- " + c["hard_rule"], ""]
    return "\n".join(str(line) for line in out)


# ----------------------------------------------------------------------------- validate a draft
# Things code cannot verify by itself: a particular customer's story, someone's quoted words, a
# review. General statements ("when a customer asks for rye...") are not stories, so the customer
# pattern only fires when the sentence goes on to tell what that one person DID.
_PEOPLE = r"(?:customer|client|patient|student|member|guest|regular|buyer|reader|subscriber)"
_DID = (r"(?:came|told|said|asked|had|was|went|saw|lost|got|called|emailed|wrote|booked|bought|returned|walked|"
        r"brought|started|stopped|tried|found|needed|wanted|signed|ran|finished|recovered|doubled|tripled)")
_STORY_MARKERS = [
    (re.compile(r"\b(?:(?:a|one|another|this)\s+(?:\w+\s+)?" + _PEOPLE + r"|one\s+of\s+(?:our|my)\s+(?:\w+\s+)?"
                + _PEOPLE + r"s)\s+(?:\w+\s+){0,3}?" + _DID + r"\b", re.IGNORECASE),
     "a story about a particular customer"),
    (re.compile(r"[\"\u201c][^\"\u201c\u201d]{8,}[\"\u201d]\s*,?\s*(?:said|says|wrote|told)\b|\b(?:told\s+(?:me|us)|"
                r"said\s+to\s+(?:me|us))\b", re.IGNORECASE), "words quoted from someone"),
    (re.compile(r"\b(?:testimonial|five[- ]star|rated\s+us|reviewed\s+us|case\s+study)\b", re.IGNORECASE),
     "a review or a result someone else gave"),
]


def other_brand_names(brand, text):
    """Names of OTHER brands set up on this computer that appear in the draft. One company's name
    in another company's post is the mix-up this whole system exists to prevent."""
    mine = {o.lower() for o in (brand.data.get("own_brands") or [])} | {brand.name.lower()}
    hits = []
    for other_id in brands.list_brands():
        if other_id == brand.id:
            continue
        try:
            other = brands.load(other_id, allow_invalid=True)
        except brands.BrandError:
            continue
        for name in [other.data.get("name", "")] + list(other.data.get("own_brands") or []):
            name = str(name).strip()
            if len(name) < 5 or name.lower() in mine:
                continue
            if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE) and name not in hits:
                hits.append(name)
    return hits


def _part_holding(draft, offset):
    """Which part of the post a number was found in, in the words a person would use."""
    at = 0
    for label, words in posts_mod.publishable_parts(draft):
        if at <= offset < at + len(words):
            return label
        at += len(words) + 2                     # the blank line publishable_text joins them with
    return "the caption"


def validate_draft(text, brand, identity, platform, topic, proof_ids=None, thread=(), post_id=None, job=None,
                   rubric=None, first_comment="", alt_text="", link=""):
    """Check one draft. Returns a single report (see the module docstring for `sourcing`).

    Every field that would publish is checked together: the caption, the thread, the first
    comment and the alt text. A link has no separate label here, so its readable words are read
    for claims written in words only; an address's digits are not figures.

    `ok` means "may go to review": no checker errors, not a repeat, an ending its job allows, the
    takeaway pre-screens met, and sourcing not blocked. `problems` must be fixed; `warnings` are
    for the reviewer; `next_steps` says what to do, in order."""
    brand = as_brand(brand)
    brand.identity(identity)
    platform = str(platform or "").strip().lower()
    topic = topic if isinstance(topic, dict) else {}
    if proof_ids is None:
        proof_ids = list(topic.get("proof_ids") or [])
    job = job or ((topic.get("plans") or {}).get(identity) or {}).get("job")
    lane = topic.get("lane") or "evergreen"
    whole = "\n\n".join([text or ""] + [seg for seg in (thread or []) if seg])
    problems, warnings, steps = [], [], []

    if platform not in brand.platforms_for(identity):
        problems.append("%s does not post on %s as '%s' (it has: %s)."
                        % (brand.name, platform or "that platform", identity, ", ".join(brand.platforms_for(identity))))

    # 1. the copy checker, over every field that publishes
    draft = Post(id=post_id or "draft", brand=brand.id, identity=identity, platform=platform, text=text or "",
                 thread=list(thread or []), first_comment=first_comment or "", alt_text=alt_text or "",
                 link=link or "")
    published = posts_mod.publishable_text(draft)
    findings = draft.lint(Rules.for_brand(brand))
    errors = [f for f in findings if f.severity == "ERROR"]
    lint_report = {"errors": [str(f) for f in errors],
                   "warnings": [str(f) for f in findings if f.severity == "WARN"]}
    problems.extend("Copy check: " + f.detail + (" (\"%s\")" % f.excerpt if f.excerpt else "") for f in errors)
    for leaked in journal.private_overlap(brand, published):
        problems.append("The draft repeats words from a private journal entry (%s). Private entries never go into "
                        "posts. Take those words out." % leaked)
    for person in topics_mod.influences(brand):
        if re.search(r"(?<!\w)%s(?!\w)" % re.escape(person["name"]), published, re.IGNORECASE):
            warnings.append("The draft names %s, one of the people who inspire %s. Influences are for structure and "
                            "format only: check the owner wants them named, and that none of their words, titles or "
                            "frameworks are borrowed." % (person["name"], brand.name))
    strangers = other_brand_names(brand, published)
    for name in strangers:
        problems.append("The draft names '%s', which is another brand set up on this computer. If that is meant, "
                        "add it to this brand's list of names that are fine to say." % name)

    # 2. where the numbers come from, and whether the claims without numbers are the brand's own
    found, _missing = grounding.load_proof(brand, proof_ids)
    private = {p["proof_id"] for p in found if p.get("may_publish") not in ("anonymised", "yes")}
    publishable = [p for p in found if p["proof_id"] not in private]
    corpus = grounding.build_corpus(brand, proof_ids)       # the brand's files are read once for both checks
    ground = grounding.ground_draft(published, brand, proof_ids, corpus=corpus)
    said = grounding.check_wording("\n\n".join([published, posts_mod.link_words(draft)]), brand, proof_ids,
                                   corpus=corpus)
    private_numbers = [n["raw"] for n in ground["numbers"]
                       if n["provenance"] and all(p["kind"] == "proof" and p["ref"] in private for p in n["provenance"])]

    # 3. has it been said, 4. does it end the way its job allows, 5. does the reader get something
    seen = dedup.similar_posts(whole, brand, identity=identity, exclude_ids=[post_id] if post_id else ())
    ending = cta_mod.check_cta(whole, brand, platform, job=job)
    takeaway = quality.takeaway_gate(whole, brand, lane=lane, has_proof=bool(publishable), rubric=rubric)

    # 6. sourcing
    reasons = []
    if ground["ungrounded"]:
        sourcing = "blocked"
        reasons.append(ground["explanation"])
        reasons.extend(ground["hints"])
        elsewhere = sorted({_part_holding(draft, n["start"]) for n in ground["numbers"]
                            if not n["structural"] and not n["grounded"]} - {"the caption"})
        if elsewhere:
            reasons.append("That is in %s. Everything that goes out with the post is checked, not only the caption."
                           % " and ".join(elsewhere))
    elif private_numbers:
        sourcing = "blocked"
        reasons.append("These figures come only from proof marked as not for publishing: %s. Take them out, or "
                       "get permission and update the proof item." % ", ".join(private_numbers))
    else:
        sourcing = "passed"
    soft = list(ground["unconfirmed"]) + list(said["unconfirmed"])
    if not str(topic.get("source_ref") or "").strip():
        soft.append("The topic does not say where in %s's own material it comes from." % brand.name)
    else:
        pointer = topics_mod.resolve_source_ref(brand, topic["source_ref"])
        if not pointer["ok"]:
            soft.append("The topic points to '%s', but %s." % (topic["source_ref"], pointer["detail"]))
    if topic.get("status") not in (None, "approved"):
        soft.append("The topic is '%s', not approved." % topic.get("status"))
    if ground["unknown_proof_ids"]:
        soft.append("Proof linked to this post is not in the proof library: %s." % ", ".join(ground["unknown_proof_ids"]))
    for pattern, what in _STORY_MARKERS:
        m = pattern.search(published)
        if m and not publishable:
            soft.append("The draft includes %s (\"%s\") and no publishable proof is linked, so it cannot be "
                        "confirmed. Link the proof it comes from, or take it out." % (what, m.group(0).strip()[:60]))
        elif m:
            warnings.append("The draft includes %s (\"%s\"). Check by eye that it matches the linked proof: %s."
                            % (what, m.group(0).strip()[:60], ", ".join(p["proof_id"] for p in publishable)))
    if sourcing == "passed" and soft:
        sourcing = "unverified"
    reasons.extend(soft)

    if sourcing == "blocked":
        problems.extend(reasons)
    else:
        warnings.extend(reasons)
    if seen.is_duplicate:
        top = seen.matches[0]
        problems.append("This is very close to a post %s has already written (%s on %s, %d%% the same). "
                        "Change the angle or the shape." % (brand.name, top["post_id"], top["platform"],
                                                            round(top["similarity"] * 100)))
    elif seen.exempt:
        warnings.append("The same words already exist under another identity of this brand. That is allowed as a "
                        "deliberate mirror; a fresh version usually does better.")
    problems.extend(ending["issues"])
    # Craft advice (does the first line promise something, is there a concrete move) guides the
    # writer; it does not block a post unless the brand asked for strict craft checks. What always
    # blocks is safety: facts, names, regulated terms and the platform's own limits.
    if bool(brand.style.get("strict_craft_checks")):
        problems.extend(takeaway["holds"])
    else:
        warnings.extend("Craft note: " + h for h in takeaway["holds"])
    warnings.extend(lint_report["warnings"])
    warnings.extend(ground["notes"])
    for a in ground["attributions"]:
        warnings.append("Credit the source for this figure: " + a)
    notes = quality.style_notes(whole)

    ok = not problems
    if ok and sourcing == "passed":
        summary = "Ready for review. Every number traces to the brand's files and nothing needs fixing."
    elif ok:
        summary = "Ready for review, flagged as unverified: nothing is wrong, but some evidence is missing."
        steps.append("Add the missing evidence listed under warnings, or let the reviewer decide.")
    else:
        summary = "Not ready. %d thing%s to fix before this goes to review." % (len(problems), "" if len(problems) == 1 else "s")
        steps.append("Fix each item under problems, then check the draft again.")

    return {"ok": ok, "sourcing": sourcing, "summary": summary, "problems": problems, "warnings": warnings,
            "next_steps": steps, "brand": brand.id, "identity": identity, "platform": platform,
            "topic_id": topic.get("topic_id", ""), "job": job or "", "lane": lane,
            "lint": lint_report, "other_brands_named": strangers, "grounding": ground, "dedup": seen.as_dict(),
            "cta": ending, "takeaway": takeaway, "style_notes": notes, "wording": said,
            "checked_sha": posts_mod.publishable_sha(draft),
            "rubric": rubric.as_dict() if rubric is not None else None}


def format_report(report):
    """The report as a short page for a person."""
    out = [report["summary"], "Sourcing: %s." % report["sourcing"]]
    if report["problems"]:
        out += ["", "To fix:"] + ["  - " + p for p in report["problems"]]
    if report["warnings"]:
        out += ["", "Worth a look:"] + ["  - " + w for w in report["warnings"]]
    if report["style_notes"]:
        out += ["", "Style notes (optional):"] + ["  - \"%s\": %s" % (n["excerpt"], n["note"]) for n in report["style_notes"]]
    if report["next_steps"]:
        out += ["", "Next:"] + ["  - " + s for s in report["next_steps"]]
    return "\n".join(out)


def apply_to_post(post, report):
    """Carry the verdict onto a Post so the review page and the batch file show it.

    The report is for the exact words it read. A post whose first comment or alt text says
    something the check never saw is refused here, rather than published with someone else's
    pass on it."""
    if post.brand != report["brand"]:
        raise ContractError("That report is for %s, but the post belongs to %s." % (report["brand"], post.brand))
    checked = report.get("checked_sha")
    if checked and checked != posts_mod.publishable_sha(post):
        raise ContractError("That check was run on different words from the ones this post says now. Check the "
                            "post as it stands (its caption, its thread, its first comment and its alt text "
                            "together) before filing it.")
    post.sourcing = report["sourcing"]
    post.facts_check = dict(post.facts_check or {}, words=report["sourcing"], words_sha=checked or "")
    posts_mod.settle_sourcing(post)
    return post
