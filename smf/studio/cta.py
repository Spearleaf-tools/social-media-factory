"""cta.py - the call to action matches the job the post is doing. The writer never invents one.

Every planned post has one job, and the job decides how it may end:

    lead_gen   an OFFER or a KEYWORD from the brand's own library. This is the only job that
               may point at something the brand sells.
    reach      ask for a save, a share or a follow, in rotation. Never an offer, never a keyword.
    trust      a genuine question, or no ask at all. Never an offer, never a keyword.

The library lives at Client/<brand>/Studio/cta_library.json and is seeded from the offers in the
brand's settings, using the brand's OWN wording for each next step. Nothing is hardcoded here:
no keywords, no phrases, no fallback offer. A brand with no offers simply gets a soft close on
its lead-gen posts, with a note saying how to change that.

A KEYWORD call to action ("comment GUIDE and I will send it") is a promise that something arrives
when a reader does it. It is only ever used when its entry says `"ready": true`, meaning the brand
has really set up the reply. A planned-but-not-built keyword is never written into a post.

    {"brand": "maple-and-main", "ctas": [
      {"id": "offer-weekend-class", "kind": "offer", "offer_id": "weekend-class",
       "text": "Book a Saturday class at the counter or on our website.", "link": "",
       "platforms": ["all"], "active": true, "ready": true},
      {"id": "kw-starter", "kind": "keyword", "keyword": "STARTER", "delivers": "the starter feeding card",
       "text": "Comment STARTER and I will send you our feeding card.", "platforms": ["instagram"],
       "active": true, "ready": false}
    ]}
"""
from __future__ import annotations

import os
import re

from smf.studio.files import StudioError, as_brand, read_json, write_json

JOBS = ("reach", "lead_gen", "trust")
LIBRARY_FILE = ("Studio", "cta_library.json")

# What the writer is told to do for the jobs that never sell. These are instructions, not copy:
# the words in the post come from the brand's voice. A brand can put its own wording in the
# library (kind "reach" or "soft") and that wording wins.
REACH_ASKS = [
    ("save", "Close by inviting the reader to save the post so they can use it later."),
    ("share", "Close by inviting the reader to send the post to one person it would help."),
    ("follow", "Close by inviting the reader to follow for more on this subject. No @handle on platforms "
               "where this brand does not use them."),
]
TRUST_ASKS = [
    ("soft", "Close with one genuine question the reader could answer from their own experience."),
    ("none", None),
]
_ROTATION_KEY = {"reach": "__reach__", "trust": "__trust__"}

# "comment WORD": the word counts as a keyword only when it is in capitals or is a known keyword,
# so "comment below" is never mistaken for one.
_KEYWORD_SCAN = re.compile(r"(?i:\bcomment)\s+[\"'\u201c\u2018]?([A-Za-z][A-Za-z0-9-]{1,19})\b")


class CtaError(StudioError):
    """The brand's call-to-action library could not be used."""


# ----------------------------------------------------------------------------- the library
def library_path(brand):
    return brand.path(*LIBRARY_FILE)


def _from_offers(brand):
    out = []
    for offer in brand.data.get("offers") or []:
        text = str(offer.get("call_to_action") or "").strip()
        if not text:
            continue                                  # an offer with no next step gives the writer nothing to say
        out.append({"id": "offer-%s" % offer["id"], "kind": "offer", "offer_id": offer["id"],
                    "offer_name": offer.get("name", ""), "text": text, "link": str(offer.get("link") or ""),
                    "platforms": ["all"], "active": True, "ready": True, "from": "the offers in the brand settings"})
    return out


def load_library(brand):
    """The brand's library. With no file yet, the offers in the brand's settings ARE the library,
    so an untouched brand works without a setup step. Reading never writes."""
    brand = as_brand(brand)
    path = library_path(brand)
    if not os.path.isfile(path):
        return {"brand": brand.id, "ctas": _from_offers(brand), "saved": False}
    data = read_json(path, "%s's call-to-action library (Studio/cta_library.json)" % brand.name)
    if not isinstance(data, dict) or not isinstance(data.get("ctas", []), list):
        raise CtaError("%s's call-to-action library is not in the expected shape. Ask Claude to repair it." % brand.name)
    if data.get("brand") not in (None, brand.id):
        raise CtaError("This call-to-action library belongs to %s, not to %s. Nothing was used from it."
                       % (data.get("brand"), brand.id))
    data["ctas"] = [c for c in data.get("ctas", []) if isinstance(c, dict) and c.get("id")]
    data["saved"] = True
    return data


def seed_library(brand):
    """Create or top up the library file from the brand's offers. Entries already in the file are
    left exactly as they are (they may have been edited by hand); new offers are added; an offer
    that no longer exists in the settings is switched off rather than deleted."""
    brand = as_brand(brand)
    current = load_library(brand)
    entries = list(current["ctas"]) if current["saved"] else []
    have = {c["id"] for c in entries}
    added, switched_off = [], []
    for c in _from_offers(brand):
        if c["id"] not in have:
            entries.append(c)
            added.append(c["id"])
    live_offers = {o["id"] for o in brand.data.get("offers") or []}
    for c in entries:
        if c.get("kind") == "offer" and c.get("offer_id") not in live_offers and c.get("active", True):
            c["active"] = False
            c["note"] = "switched off: this offer is no longer in the brand settings"
            switched_off.append(c["id"])
    write_json(library_path(brand), {"brand": brand.id, "ctas": entries})
    return {"added": added, "switched_off": switched_off, "total": len(entries)}


# ----------------------------------------------------------------------------- choosing
def _on_platform(entry, platform):
    plats = [str(p).lower() for p in (entry.get("platforms") or ["all"])]
    return "all" in plats or (platform or "").lower() in plats


def eligible_for_lead_gen(library, platform):
    """Offers and keywords that may really be used: switched on, right platform, and for a
    keyword, the reply actually set up."""
    out = []
    for c in library.get("ctas", []):
        if c.get("kind") not in ("offer", "keyword") or not c.get("active", True) or not _on_platform(c, platform):
            continue
        if c.get("kind") == "keyword" and (not c.get("ready") or not str(c.get("keyword") or "").strip()):
            continue
        if not str(c.get("text") or "").strip():
            continue
        out.append(c)
    return out


def _own_wording(library, kind, key, platform):
    for c in library.get("ctas", []):
        if c.get("kind") == kind and c.get("id") == key and c.get("active", True) and _on_platform(c, platform) \
                and str(c.get("text") or "").strip():
            return c["text"].strip()
    return None


def select_cta(brand, job, platform, used_counts=None, library=None):
    """The call to action for one slot. `used_counts` is the caller's running tally for the batch
    (changed in place) so offers rotate instead of one being repeated all week.

    Returns {cta_id, kind, text, instruction, link, note}. `text` is the brand's own wording when
    there is some; `instruction` tells the writer what to do when there is not."""
    brand = as_brand(brand)
    if job not in JOBS:
        raise CtaError("'%s' is not a job a post can have. The jobs are: %s." % (job, ", ".join(JOBS)))
    used = used_counts if used_counts is not None else {}
    library = library or load_library(brand)

    if job == "lead_gen":
        pool = eligible_for_lead_gen(library, platform)
        pool = [c for c in pool if c.get("max_uses") is None or used.get(c["id"], 0) < int(c["max_uses"])]
        if not pool:
            return {"cta_id": None, "kind": "none", "text": None, "link": "",
                    "instruction": "End on a soft close: one genuine question, or a one-line takeaway.",
                    "note": "%s has no offer or keyword ready for %s, so this lead-gen post cannot send the reader "
                            "anywhere yet. Add an offer with its next step in the brand settings to change that."
                            % (brand.name, platform)}
        choice = min(pool, key=lambda c: used.get(c["id"], 0))       # least used; library order breaks ties
        used[choice["id"]] = used.get(choice["id"], 0) + 1
        if choice["kind"] == "keyword":
            instruction = ("Use this keyword call to action as the last line. The word %s must appear exactly, "
                           "and no other keyword may be offered." % choice["keyword"])
        else:
            instruction = "Close with this next step, in the brand's own wording. Do not add a second offer."
        return {"cta_id": choice["id"], "kind": choice["kind"], "text": choice["text"].strip(),
                "link": choice.get("link", ""), "keyword": choice.get("keyword", ""),
                "delivers": choice.get("delivers", ""), "instruction": instruction, "note": ""}

    asks = REACH_ASKS if job == "reach" else TRUST_ASKS
    turn = used.get(_ROTATION_KEY[job], 0)
    used[_ROTATION_KEY[job]] = turn + 1
    key, instruction = asks[turn % len(asks)]
    kind = "reach" if job == "reach" else "soft"
    if key == "none":
        return {"cta_id": "none", "kind": "none", "text": None, "link": "",
                "instruction": "No ask in this post. End on the point itself.", "note": ""}
    return {"cta_id": key, "kind": kind, "text": _own_wording(library, kind, key, platform), "link": "",
            "instruction": instruction, "note": ""}


# ----------------------------------------------------------------------------- checking a draft
def check_cta(text, brand, platform, job=None, library=None):
    """Does the draft end the way its job allows? Finds keywords nobody set up, more than one
    keyword, and an offer or keyword stapled onto a reach or trust post."""
    brand = as_brand(brand)
    library = library or load_library(brand)
    keywords = {str(c.get("keyword")).upper(): c for c in library.get("ctas", [])
                if c.get("kind") == "keyword" and str(c.get("keyword") or "").strip()}
    usable = {str(c.get("keyword")).upper() for c in eligible_for_lead_gen(library, platform)
              if c.get("kind") == "keyword"}
    found, issues = [], []
    for m in _KEYWORD_SCAN.finditer(text or ""):
        word = m.group(1)
        if not word.isupper() and word.upper() not in keywords:
            continue
        up = word.upper()
        if up in found:
            continue
        found.append(up)
        if up in usable:
            continue
        if up in keywords:
            issues.append("The keyword %s is in the library but is not ready for %s (its reply has to be set up "
                          "and switched on first)." % (up, platform))
        else:
            issues.append("The keyword %s is not in %s's call-to-action library. A post may only promise "
                          "something the brand has set up." % (up, brand.name))
    if len(found) > 1:
        issues.append("The draft offers more than one keyword (%s). Use one." % ", ".join(found))

    offers_used = []
    low = " ".join((text or "").lower().split())
    for c in library.get("ctas", []):
        if c.get("kind") != "offer":
            continue
        wording = " ".join(str(c.get("text") or "").lower().split())
        link = str(c.get("link") or "").strip().lower()
        if (wording and wording in low) or (link and link in low):
            offers_used.append(c["id"])
    if job in ("reach", "trust"):
        if found:
            issues.append("This is a %s post, so it should not carry a keyword call to action. Keep keywords for "
                          "lead-gen posts." % job)
        if offers_used:
            issues.append("This is a %s post, so it should not end on an offer (%s). Keep offers for lead-gen posts."
                          % (job, ", ".join(offers_used)))
    return {"valid": not issues, "keywords_found": found, "offers_found": offers_used, "issues": issues}
