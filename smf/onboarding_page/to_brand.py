"""to_brand.py - turns the page's answers file into the answers `new-brand` / `update-brand` read.

Only CONFIRMED answers are carried over. Anything skipped, unconfirmed or handed to the chat is left
out, so the brand keeps its placeholder there and `check-brand` lists it, exactly like a skipped
answer in the chat onboarding. Nothing is invented to fill a gap.

What the page collects but the settings file cannot hold on its own comes back as `notes` for the
agent to settle with the person in the chat (for example "who signs off on what"), never guessed.

    name, answers, notes, voice_md = build(intake)                  # a new brand
    name, answers, notes, voice_md = build(intake, current=data)    # an update: `data` is the brand's settings now

Version 2 answers (spec rev 10) carry their ids into the brand, so `brands.update` merges lists by id. A list
item the person removed and confirmed arrives as {"id": ..., "remove": true}. Offers keep their ids; "none yet"
on a rung only takes that rung away from an offer (`"rung": None`), never deletes it. Proof waits for the proof
library and is never written into the settings.
"""
from __future__ import annotations

import re

from smf import brands
from smf.onboarding_page import session as S


def _confirmed(value):
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict) and v.get("status") == "confirmed"]
    return value if isinstance(value, dict) and value.get("status") == "confirmed" else None


def _source(item):
    """The brand's word for how an answer got there, from the answers file's `source` and `origin`.
    Drafted from anything but the website has no brand word, so none is written."""
    if item.get("source") == "typed":
        return "typed"
    # Rev 13 (M6): the owner's own writing, quoted from their book, documents or website, and confirmed.
    if item.get("source") == "draft" and item.get("quoted") is True:
        return "quoted"
    if item.get("source") in ("draft", "draft-edited") and item.get("origin") == "website":
        return "drafted-from-website"
    # Rev 12: words a starter pack or Claude suggested, which the person kept (and maybe edited).
    if item.get("source") in ("draft", "draft-edited") and item.get("origin") in S.GENERATED_ORIGINS:
        return "drafted"
    return None


def _provenance(item):
    """Where a kept suggestion came from (spec rev 12, N3), stored beside its brand `source`."""
    got = {k: item[k] for k in ("origin", "generator", "refs", "parts", "prompted_by") if item.get(k)}
    return got if (got.get("origin") in S.GENERATED_ORIGINS or any(got.get(k) for k in ("generator", "refs", "parts", "prompted_by"))) else None


def _clean(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return [v.strip() if isinstance(v, str) else v for v in value if not (isinstance(v, str) and not v.strip())]
    return value


def _fields(answer, names):
    """The fields the answer includes (present and empty clears; absent leaves the brand as it was)."""
    return {n: _clean(answer[n]) for n in names if n in answer}


def _dict(value):
    """A group the answers file should hold as a group; anything else counts as not answered."""
    return value if isinstance(value, dict) else {}


def _items(value, names, removable, with_source=True):
    """The confirmed items of a list answer, each with its id. Removals only count on an update."""
    out = []
    for item in _confirmed(value if isinstance(value, list) else []):
        if not item.get("id"):
            continue
        if item.get("remove") is True:
            if removable:
                out.append({"id": item["id"], "remove": True})
            continue
        got = dict({"id": item["id"]}, **_fields(item, names))
        if with_source and _source(item):
            got["source"] = _source(item)
        if with_source and _provenance(item):
            got["provenance"] = _provenance(item)
        out.append(got)
    return out


def _one(answer, part_id, names=("value",)):
    """A single confirmed answer kept as {id, value, source}, or None. Confirmed blank clears it
    (the value arrives empty, which the brand reads as not answered)."""
    c = _confirmed(answer)
    if not c or "value" not in c:
        return None
    got = dict({"id": part_id}, **_fields(c, names))
    if _source(c):
        got["source"] = _source(c)
    if _provenance(c):
        got["provenance"] = _provenance(c)
    return got


def _ident_id(kind, taken):
    base = {"person": "person", "company": "company"}.get(kind, "speaker")
    out, n = base, 2
    while out in taken:
        out, n = "%s-%d" % (base, n), n + 1
    taken.add(out)
    return out


def build(intake, current=None):
    """Returns (name or None, answers dict, notes list, voice_samples markdown or None). `current` is the
    brand's settings when the answers update an existing brand (None for a new brand). A damaged or
    hand-edited answers file is refused with a plain message (SessionError), never half-built."""
    problems = S.validate_intake(intake)
    if problems:
        raise S.SessionError("The answers file is not in the shape the page writes: " + "; ".join(problems[:5]))
    a = _dict(intake.get("answers"))
    answers, notes = {}, []
    current = current or {}
    removable = bool(current)

    name = _confirmed(a.get("name"))
    name = name["value"].strip() if name and (name.get("value") or "").strip() else None
    if name:
        answers["visual"] = {"wordmark": name}
        answers["own_brands"] = [name]

    what = _confirmed(a.get("what_you_do"))
    if what and len((what.get("value") or "").strip()) >= 10:
        answers.setdefault("business", {})["what_we_do"] = what["value"].strip()
    elif what:
        notes.append("What you do is shorter than a sentence; ask for one or two full sentences.")

    aud = _confirmed(a.get("audience"))
    if aud and len((aud.get("value") or "").strip()) >= 10:
        answers["audience"] = {"who": aud["value"].strip()}
        if "questions" in aud:                      # left out: the brand's questions stay as they were
            answers["audience"]["questions_they_ask"] = _clean(aud["questions"] or [])
        if "in_the_way" in aud:
            answers["audience"]["problems"] = _clean(aud["in_the_way"] or [])
        objections = _items(aud.get("objections"), ("value", "reply"), removable)
        if objections:
            answers["audience"]["objections"] = objections
    elif aud:
        notes.append("Who you reach is shorter than a sentence; ask for a fuller description.")

    people = _confirmed(a.get("identities") if isinstance(a.get("identities"), list) else [])
    if people:
        known = {(i.get("display_name") or "").strip().casefold(): i.get("id") for i in current.get("identities") or []}
        taken = {i.get("id") for i in current.get("identities") or []} | {p.get("id") for p in people if p.get("id")}
        idents = []
        for p in people:
            kind = p.get("kind")
            if kind not in ("person", "company"):
                notes.append("Who speaks was \"something else\" (%s: %s). Settle in the chat whether that is a "
                             "person or the company." % (p.get("name", ""), p.get("other", "")))
                continue
            if not isinstance(p.get("name"), str) or not p["name"].strip():
                notes.append("A speaker was confirmed without a name: ask for it in the chat.")
                continue
            # The speaker's own id; else the brand's speaker with the same name; else a new id.
            sid = p.get("id") or known.get(p["name"].strip().casefold()) or _ident_id(kind, taken)
            item = {"id": sid, "kind": kind, "display_name": p["name"].strip()}
            for src, dst in (("role", "role"), ("handle", "handle"), ("video_line", "credential_line")):
                if (p.get(src) or "").strip():
                    item[dst] = p[src].strip()
            idents.append(item)
            answers.setdefault("own_brands", [])
            if item["display_name"] not in answers["own_brands"]:
                answers["own_brands"].append(item["display_name"])
        if idents:
            answers["identities"] = idents
            company = next((i for i in idents if i["kind"] == "company"), None)
            # Written whenever the company is confirmed, even empty: an update merges, so a handle the
            # person removed must arrive as "" or the old one stays on every picture. With no confirmed
            # company, the picture handle is left as it was.
            if company:
                answers.setdefault("visual", {})["handle"] = (company.get("handle") or "").lstrip("@")

    named = _confirmed(a.get("name"))
    if named and "handle" in named:                 # core 2, asked on its own: it wins over the company's handle
        answers.setdefault("visual", {})["handle"] = (named.get("handle") or "").strip().lstrip("@")

    colours = _confirmed(a.get("colours"))
    if colours and all(re.match(r"^#[0-9A-Fa-f]{6}$", colours.get(k) or "") for k in ("background", "text", "accent")):
        answers.setdefault("visual", {})["colors"] = {"ground": colours["background"], "ink": colours["text"],
                                                      "accent": colours["accent"]}

    rules = _confirmed(a.get("rules"))
    if rules:
        industry = rules.get("industry") or "none"
        answers.setdefault("business", {})["regulated"] = industry if industry in (
            "none", "health", "finance", "legal", "other") else "other"
        comp = {"pack": "health" if industry == "health" else "generic"}
        # A list that is there, even empty, is written: an update merges, so an emptied list must
        # arrive as [] to clear the old one. A list the answer leaves out is left as it was.
        if "never_claim" in rules:
            comp["drop_terms"] = list(rules["never_claim"] or [])
        answers["compliance"] = comp
        if rules.get("sign_off"):
            notes.append("Sign-off rules to settle in the chat (what needs a disclaimer, and who signs off): "
                         + "; ".join(rules["sign_off"]))
        if industry == "other" and rules.get("industry_other"):
            notes.append("Regulated industry described as: %s" % rules["industry_other"])
        if "never_name" in rules:
            answers["never_mention"] = list(rules["never_name"] or [])
        if "hated_words" in rules:
            answers["style"] = {"banned_words": list(rules["hated_words"] or [])}

    make = _confirmed(a.get("make"))
    if make:
        answers["wants"] = list(make.get("value") or [])
        if make.get("other"):
            notes.append("They also want: %s (not something the Social Media Factory makes yet; say so plainly)." % make["other"])

    _version_two(a, answers, notes, current, removable)

    for key in a:
        for where in _handed_to_chat(a[key], key):
            notes.append("'%s' was handed to the chat: settle it with the person before building." % where)

    return name, answers, notes, voice_markdown(intake)


def _handed_to_chat(value, where):
    """Where in an answer something was handed to the chat: the answer itself, or a part of a group."""
    if isinstance(value, list):
        return [where] if any(isinstance(x, dict) and x.get("status") == "for_chat" for x in value) else []
    if not isinstance(value, dict):
        return []
    if "status" in value:
        return [where] if value["status"] == "for_chat" else []
    return [w for part, v in value.items() for w in _handed_to_chat(v, "%s.%s" % (where, part))]


def _version_two(a, answers, notes, current, removable):
    """The rest of the core and the deeper answers (spec rev 10, "Where every field goes")."""
    why = _confirmed(a.get("why_started"))
    if why and "value" in why:
        answers.setdefault("person", {})["why_started"] = _clean(why["value"])

    voice = _confirmed(a.get("voice"))
    if voice:
        got = _fields(voice, ("do", "dont", "signature_phrases"))
        register = voice.get("register") if isinstance(voice.get("register"), str) else ""
        if len(register.strip()) >= 10:
            got["register"] = register.strip()
        elif "register" in voice:                   # the brand always needs one, so a blank never clears it
            notes.append("How you sound is shorter than a sentence; ask for one or two full sentences.")
        if got:
            answers.setdefault("voice", {}).update(got)

    _positioning(_dict(a.get("positioning")), _dict(a.get("deep")), answers, notes, removable)

    teach = _dict(a.get("teach"))
    for src, dst in (("myths", "myths"), ("mistakes", "mistakes"), ("steps", "steps_to_result")):
        got = _items(teach.get(src), ("value",), removable)
        if got:
            answers[dst] = got

    _ladder(a.get("ladder"), answers, notes, current)

    goal = _confirmed(a.get("goal"))
    if goal and goal.get("value"):
        answers["goal"] = goal["value"]

    plat = _confirmed(a.get("platforms"))
    if plat:
        speakers = {i["id"] for i in answers.get("identities", [])} | {
            i.get("id") for i in current.get("identities") or []}
        got = {}
        if isinstance(plat.get("by_speaker"), dict):
            kept = {}
            for sid, names in plat["by_speaker"].items():
                names = [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
                if sid not in speakers:
                    notes.append("Platforms were given for a speaker who isn't confirmed (%s): settle in the chat." % sid)
                    continue
                unknown = [n for n in names if n not in brands.PLATFORMS]
                if unknown:
                    notes.append("%s also wants %s: not a platform the Social Media Factory posts to yet; say so plainly."
                                 % (sid, ", ".join(unknown)))
                kept[sid] = [n for n in names if n in brands.PLATFORMS]
            got["by_speaker"] = kept
        got.update(_fields(plat, ("other",)))
        if got:
            answers["intended_platforms"] = got

    cap = _confirmed(a.get("capacity"))
    if cap:
        got = _fields(cap, ("hours_per_week", "helpers", "posts_per_week"))
        if got:
            answers["capacity"] = got

    show = []
    for item in _items(a.get("show"), ("value", "proof_id"), removable, with_source=False):
        if "value" in item:
            item["text"] = item.pop("value")
        show.append(item)
    if show:
        answers["proof_summary"] = show

    _deep(_dict(a.get("deep")), answers, removable)
    _rev12(a, answers, notes, removable)
    _influences(_dict(a.get("influences")), answers)


def _influence_row(item):
    got = dict({"id": item["id"]}, **{k: _clean(item[k]) for k in ("name", "why") if (item.get(k) or "").strip()})
    if _source(item):
        got["source"] = _source(item)
    if _provenance(item):
        got["provenance"] = _provenance(item)
    return got


def surviving_rows(rows, restored=True):
    """A replaced list's rows as the brand keeps them: confirmed (and, with `restored`, read back from the brand and
    not yet checked again), never removed, never a remove marker. Only rows with a name."""
    return [_influence_row(x) for x in rows if isinstance(x, dict) and x.get("id") and not x.get("remove")
            and (x.get("status") == "confirmed" or (restored and x.get("restored")))
            and (x.get("name") or "").strip()]


def _influences(answer, answers):
    """Who inspires them: the brand's list is replaced whole by the rows the owner confirmed, like any list question
    (each row's yes is theirs, so "Skip for now" later doesn't undo it). Only the question confirmed with no rows
    left clears it; only quotes still waiting, or nothing confirmed, leaves the brand as it was (export table)."""
    rows = answer.get("items") if isinstance(answer.get("items"), list) else []
    live = [x for x in rows if isinstance(x, dict) and not x.get("remove")]
    kept = surviving_rows(live, restored=False)
    if kept or (not live and answer.get("status") == "confirmed"):
        answers["influences"] = kept


def _kept_from(a, gen):
    """True when a confirmed answer kept something this pack (or Claude's description) suggested."""
    def mine(x):
        return isinstance(x, dict) and str(x.get("generator") or "").startswith(gen)
    teach = _dict(a.get("teach"))
    items = [i for part in ("myths", "mistakes") for i in _confirmed(teach.get(part) or [])]
    items += _confirmed(a.get("topic_ideas") or []) + _confirmed(a.get("platform_candidates") or [])
    if _confirmed(a.get("fonts")):
        items.append(a["fonts"])
    # The provenance record is only written when the owner confirms the question it describes.
    items += [p for p in _dict(a.get("provenance")).values()]
    return any(mine(i) for i in items)


def _rev12(a, answers, notes, removable):
    """Spec rev 12 ("Next phase", storage table): the first screen, the pack, how people find you, filming,
    fonts, post ideas, and where each question's words came from. Only what the person confirmed."""
    start = _confirmed(a.get("business_start"))
    if start:
        if (start.get("where") or "").strip():
            answers.setdefault("business", {})["location"] = start["where"].strip()
        if (start.get("website") or "").strip():
            answers.setdefault("business", {})["website"] = start["website"].strip()

    aud = _confirmed(a.get("audience"))
    if aud:                                         # question 4's quick choices (N6)
        got = _fields(aud, ("type", "where"))
        if got:
            answers.setdefault("audience", {}).update(got)

    pack = a.get("starter_pack")
    used = isinstance(pack, dict) and pack.get("id") and _kept_from(a, "claude-from-description" if pack["id"] == "custom"
                                                                  else "pack:%s@" % pack["id"])
    if isinstance(pack, dict) and pack.get("id") and (pack.get("status") == "confirmed" or used):
        answers.setdefault("business", {})["starter_pack"] = {k: pack[k] for k in ("id", "version") if k in pack}

    acq = _items(a.get("acquisition"), ("value",), removable)
    if acq:
        answers.setdefault("audience", {})["acquisition"] = acq

    film = _confirmed(a.get("filming"))
    if film:
        got = {"speakers": [{"id": s["id"], "mode": s["mode"]} for s in _confirmed(film.get("speakers") or [])
                            if s.get("id") and s.get("mode")]}
        if (film.get("where") or "").strip():
            got["where"] = film["where"].strip()
        answers["filming"] = got
        for s in film.get("speakers") or []:
            if isinstance(s, dict) and s.get("status") == "for_chat":
                notes.append("Filming: speaker '%s' was removed from who speaks; ask whether to keep them in videos." % s.get("id"))

    fonts = _confirmed(a.get("fonts"))
    if fonts:
        # Kept apart from visual.fonts, which the picture tools draw with (Ho's area): this is the person's
        # preference, for the brand kit to pick up.
        got = _fields(fonts, ("heading", "body"))
        if got:
            answers.setdefault("visual", {})["font_preference"] = got
            notes.append("They'd like these fonts: %s. The pictures use the brand kit's own font files; add them there "
                         "if they want them on their pictures." % ", ".join("%s for %s" % (v, "headings" if k == "heading" else "text")
                                                                           for k, v in got.items()))

    ideas = [{"id": i["id"], "field": i.get("field", ""), "text": i["text"].strip(),
              **({"generator": i["generator"]} if i.get("generator") else {})}
             for i in _confirmed(a.get("topic_ideas") or []) if i.get("id") and (i.get("text") or "").strip()]
    if ideas:
        answers["topic_ideas"] = ideas

    prov = a.get("provenance")
    out = {}
    if isinstance(prov, dict):
        for fid, p in prov.items():
            if isinstance(p, dict) and fid in SETTING_FOR:
                out[SETTING_FOR[fid]] = {k: p[k] for k in ("origin", "generator", "refs", "parts", "prompted_by", "edited", "mixed") if k in p}
    if fonts and fonts.get("generator"):
        out["visual.font_preference"] = {"origin": fonts.get("origin"), "generator": fonts["generator"]}
    if start and start.get("origin") and start.get("origin") != "person":
        out["business.location"] = {"origin": start["origin"]}
    if out:
        answers["_provenance"] = out


# Where each page question's words end up in the brand, for `_provenance` (spec rev 12, storage table).
SETTING_FOR = {"audience_who": "audience.who", "audience_way": "audience.problems",
               "audience_questions": "audience.questions_they_ask", "objections": "audience.objections",
               "steps": "steps_to_result", "rules": "compliance", "goal_platforms": "intended_platforms",
               "colours": "visual.colors", "what_you_do": "business.what_we_do"}


def _positioning(pos, deep, answers, notes, removable):
    if pos.get("parked"):
        notes.append("What you stand for was parked to answer later: ask for it in the chat when they're ready.")
        return
    out = {}
    for part in ("known_for", "core_belief"):
        got = _one(pos.get(part), part.replace("_", "-"), ("value", "experience"))
        if got:
            out[part] = got
    for part, names in (("contrarian", ("value", "experience")), ("for", ("value", "experience")),
                        ("against", ("value", "experience")), ("differentiation", ("others", "us")),
                        ("non_negotiables", ("value",))):
        got = _items(pos.get(part), names, removable)
        if got:
            out[part] = got
    story = _confirmed(pos.get("story"))
    if story:
        got = {}
        for part in ("catalyst", "core_truth"):
            if part in story:                       # confirmed blank clears it
                got[part] = {"id": part.replace("_", "-"), "value": _clean(story[part])}
                if _source(story):
                    got[part]["source"] = _source(story)
        proof = _items(story.get("proof"), ("value",), removable)      # each proof item confirmed on its own
        if proof:
            got["proof"] = proof
        if got:
            out["story"] = got
    for part in ("home_medium", "stage"):
        c = _confirmed(pos.get(part))
        if c and c.get("value"):
            out[part] = c["value"]
    for part, names in (("journey", ("want", "known_for", "do", "learn")), ("formats", ("repeatable", "enjoyable")),
                        ("world", ("people", "places", "interests", "enemy"))):
        c = _confirmed(deep.get(part))
        got = _fields(c, names) if c else {}
        if got:
            out[part] = got
    for part in ("compliments", "adjacent_topics"):
        c = _confirmed(deep.get(part))
        if c and "value" in c:
            out[part] = _clean(c["value"])
    if out:
        answers["positioning"] = out


def _ladder(ladder, answers, notes, current):
    """One offer per rung. An offer keeps its id; a new one gets an id from its name. "None yet", or a
    different offer on the rung, only takes the rung away from the offer that held it."""
    existing = [o for o in current.get("offers") or [] if isinstance(o, dict)]
    taken = {o.get("id") for o in existing}
    offers, holds = [], {}
    for r in _confirmed(ladder if isinstance(ladder, list) else []):
        rung = r.get("rung")
        if rung not in ("free", "entry", "main", "premium"):
            continue
        if r.get("none_yet"):
            holds[rung] = None
            continue
        name = (r.get("name") or "").strip()
        same = next((o.get("id") for o in existing if o.get("rung") == rung and name
                     and (o.get("name") or "").strip().casefold() == name.casefold()), None)
        if r.get("id"):
            oid = r["id"]
        elif same:
            oid = same                              # the offer already on this rung: answering again changes nothing
        elif name:
            base = brands.slugify(name) or "offer"
            oid, n = base, 2
            while oid in taken:
                oid, n = "%s-%d" % (base, n), n + 1
        else:
            notes.append("The %s rung was confirmed without a name: ask for one in the chat." % rung)
            continue
        taken.add(oid)
        offer = {"id": oid, "rung": rung}
        if name:
            offer["name"] = name
        offer.update(_fields(r, ("link", "price")))
        if "line" in r:
            offer["what"] = _clean(r["line"])
        cta = (r.get("call_to_action") or "").strip()
        if cta and brands.asks_for_keyword(cta):
            notes.append("The call to action for %s asks people to comment or message a word (\"%s\"), so it was "
                         "left out: name the next step instead (\"book on our website\"). The keyword is kept on "
                         "its own and only used once the reply is really set up." % (name or oid, cta))
        elif "call_to_action" in r:
            offer["call_to_action"] = cta
        word = r.get("keyword").strip() if isinstance(r.get("keyword"), str) else ""
        if "keyword" in r and not word and current:
            offer["keyword"] = None                 # cleared: the merge takes the old keyword away
        if word:
            if re.match(r"^[A-Z0-9]{1,10}$", word.upper()) and word.upper() not in brands.COMMON_WORDS:
                offer["keyword"] = word.upper()
            else:
                notes.append("The keyword \"%s\" for %s was left out: it must be one short, unusual word "
                             "(letters or numbers, at most 10)." % (word, name or oid))
        if "keyword_ready" in r:
            offer["keyword_ready"] = r["keyword_ready"] is True
        holds[rung] = oid
        offers.append(offer)
    placed = {o["id"] for o in offers}
    for o in existing:
        if o.get("rung") in holds and holds[o["rung"]] != o.get("id") and o.get("id") not in placed:
            offers.append({"id": o["id"], "rung": None})    # stays under "Your other offers"
    if offers:
        answers["offers"] = offers


def _deep(deep, answers, removable):
    c = _confirmed(deep.get("alternatives"))
    if c and "value" in c:
        answers.setdefault("audience", {})["alternatives"] = _clean(c["value"])
    c = _confirmed(deep.get("person"))
    if c:
        answers.setdefault("person", {}).update(
            _fields(c, ("values", "timeline", "beliefs", "never_compromise", "early_signs", "ambitions")))
    stories = _items(deep.get("stories"), ("kind", "text"), removable)
    if stories:
        answers.setdefault("person", {})["stories"] = stories
    c = _confirmed(deep.get("audience"))
    if c:
        answers.setdefault("audience", {}).update(_fields(c, ("type", "where", "hangouts", "trust_triggers")))
    c = _confirmed(deep.get("offers"))
    if c:
        answers.update(_fields(c, ("customer_journey", "dream_result", "dm_tool")))
    c = _confirmed(deep.get("voice"))
    if c:
        answers.setdefault("voice", {}).update(_fields(c, ("by_platform", "analogies", "examples")))
    words = _items(deep.get("vocabulary"), ("value",), removable)
    if words:
        answers["vocabulary"] = words
    c = _confirmed(deep.get("content_source"))
    if c and "value" in c:
        answers["content_source"] = _clean(c["value"])
    c = _confirmed(deep.get("baseline"))
    if c and isinstance(c.get("platforms"), dict):
        answers["baseline"] = c["platforms"]
    c = _confirmed(deep.get("look"))
    if c:
        visual = answers.setdefault("visual", {})
        visual.update(_fields(c, ("extra_colors", "identity_line", "likes", "dislikes")))
        if isinstance(c.get("fonts"), dict):
            visual["fonts"] = _fields(c["fonts"], ("display", "body"))
    # deep.proof (the Credibility and Interest Banks) goes to the proof library (proof_items), never the settings.


def voice_markdown(intake):
    """The confirmed voice samples, word for word, ready to become Brand/voice-samples.md. None if there are none."""
    samples = _dict(intake.get("answers")).get("voice_samples")
    samples = _confirmed(samples if isinstance(samples, list) else [])
    if not samples or all(s.get("restored") for s in samples):
        return None                                 # nothing new: the brand's own samples file stays as it is
    where = {"pasted": "pasted on the onboarding page", "typed": "typed on the onboarding page",
             "spoken": "spoken on the onboarding page"}
    kept = intake.get("brand_samples_file")
    if kept and re.search(r"^## Sample \d+\b", kept, re.M):
        # The brand has samples: its file word for word, then only the new ones, numbered after the highest.
        new = [s for s in samples if not s.get("restored")]
        start = max(int(n) for n in re.findall(r"^## Sample (\d+)\b", kept, re.M))
        out = [kept if kept.endswith("\n") else kept + "\n"]
        for i, s in enumerate(new, start + 1):
            out.append("\n## Sample %d (%s)\n\n%s\n" % (i, where.get(s.get("source"), "from onboarding"), s["text"]))
        return "".join(out)
    samples = sorted(samples, key=lambda s: 0 if s.get("restored") else 1)       # the brand's own first, then new
    out = ["# Voice samples", "",
           "Word for word, exactly as given during onboarding. Do not tidy them: the writer echoes these.", ""]
    for i, s in enumerate(samples, 1):
        out += ["## Sample %d (%s)" % (i, "kept from your brand" if s.get("restored") else
                                        where.get(s.get("source"), "from onboarding")), "", s["text"], ""]
    return "\n".join(out).rstrip() + "\n"


def brand_id_for(name):
    return brands.slugify(name)


PROOF_LINES = (("context", "Context"), ("problem", "Problem"), ("insight", "Insight"),
               ("approach", "What they did"), ("outcome", "What happened"), ("lesson", "Lesson"))
KNOWN_FROM = {"own_account": "the person's own account", "document": "a document or screenshot they provided",
              "public_source_checked": "a public source Claude checked"}


def _known_from(p, intake):
    """How a proof item is known. From the owner's own material: that file by name and page (rev 13, M6), stated
    as where it comes from, never as checked."""
    refs = [r for r in p.get("refs") or [] if isinstance(r, str) and r.strip()]
    if p.get("origin") in ("document", "website") and refs:
        inv = _dict(_dict(intake.get("answers")).get("inventory"))
        sid = refs[0].split()[0]
        src = next((x for x in inv.get("sources") or [] if isinstance(x, dict) and x.get("id") == sid), None)
        page = re.search(r"p\.\s?(\d+)", refs[0])
        if src:
            name = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", str(src.get("name") or "their document"))
            return "their own material, %s%s (not independently checked)" % (name, ", page %s" % page.group(1) if page else "")
        if refs[0].startswith("website"):
            return "their own website, %s (not independently checked)" % refs[0].split(":", 1)[-1].strip()
    return KNOWN_FROM.get(p.get("known_from"), KNOWN_FROM["own_account"])


def proof_items(intake):
    """Confirmed proof from the page, ready for `factory.py proof add` (spec rev 10, "Credibility Bank").
    The six parts stay together in the detail as labelled lines, a part not given is left out (never
    invented), and "Known from:" says how it is known. An Interest Bank item is a `fact` starting with
    "Interest:": something being learned or tested, never a result. Nothing may be published unless the
    person said so. Proof never goes into the brand's settings."""
    deep = _dict(_dict(intake.get("answers")).get("deep"))
    out = []
    for p in deep.get("proof") or []:
        if not isinstance(p, dict) or p.get("remove") or p.get("status") != "confirmed" or not (p.get("title") or "").strip():
            continue
        interest = p.get("bank") == "interest"
        title = p["title"].strip()
        lines = ["%s: %s" % (label, p[k].strip()) for k, label in PROOF_LINES if (p.get(k) or "").strip()]
        lines.append("Known from: %s" % _known_from(p, intake))
        detail = "\n".join(lines)
        if interest:
            title, detail = "Interest: " + title, "Interest: " + detail
        prov = {k: p[k] for k in ("origin", "refs", "generator") if p.get(k)}
        out.append({"id": p.get("id"), "kind": "fact" if interest else (p.get("kind") or "result"),
                    **({"provenance": prov} if prov else {}),
                    "title": title, "detail": detail,
                    "source": (p.get("source_text") or "").strip() or "the person, on the onboarding page",
                    "may_publish": p.get("may_publish") if p.get("may_publish") in ("no", "anonymised", "yes") else "no",
                    "names_third_party": bool(p.get("names_third_party"))})
    return out
