"""find_clips.py - a compliance linter and a skim helper. Not a judge of what will do well.

It reads a recording's transcript and produces two lists:

  PASS         stretches worth reading first: dense with numbers, strong reactions, a flat
               contradiction, or the subjects this brand's audience asks about.
  QUARANTINE   stretches the brand's compliance gate flagged, with the reason. Nothing is deleted;
               a flag means "a person decides, and for HOLD a named person signs off".

WHY IT DOES NOT RANK. It is tempting to turn those signals into a score and sort by it. That was
tried against real published clips and the score had no relationship with how the clips performed;
it did no better than guessing from length. So the number shown here (`density`) is only "how much
is going on per second", it is labelled as a hint, and the choosing is left to a person who reads
the transcript. See playbooks/clip-rubric.md for how to choose.

Everything brand-specific comes from the brand: the gate from its compliance settings, the
off-camera voices from `video.host_names`, and the "on-topic" words from its own audience
questions, pillars and offers. With no brand it refuses to run.
"""
from __future__ import annotations

import os
import re

from smf.video import cutlist, gate
from smf.video.common import (CUT_LIST_FILE, Transcript, as_brand, fmt_ts, output_dir, tokens_of, write_json_atomic,
                              write_text_atomic)

MAX_WINDOW = 75.0        # a window never grows past this many seconds
MIN_WINDOW = 8.0         # shorter than this is a remark, not a clip
MERGE_GAP = 6.0          # signal-bearing sentences this close together belong to one window
MIN_LINE_WORDS = 6       # a "line worth lifting" is at least this long
MIN_SCORE = 3
SAME_TAKE = 0.55         # word overlap above which two windows are the same thing said twice

_FILLER_OPENERS = frozenset("and but so or um uh well like then now because cause yeah yes okay ok right".split())
_STOPWORDS = frozenset("""about above after again against because before being below between could doing down
during each every from further have having here into just like more most much only other over same should some
such than that their theirs them then there these they this those through under until very want what when where
which while will with would your yours really actually thing things people make makes made know knows good best
better does dont cant need needs help helps going still even also well""".split())
_SURPRISE_WORDS = frozenset("wow whoa unbelievable incredible shocking shocked surprising surprised astonishing "
                            "ridiculous crazy wild".split())
_SURPRISE_PHRASES = ("no idea", "nobody tells you", "hard to believe", "blew my mind", "never knew", "had no clue")
_CONTRARIAN = frozenset("not never isn't aren't wasn't don't doesn't wrong myth mistake rarely few opposite stop".split())
_UNIT = re.compile(r"\b\d[\d,.]*\s?(?:%|percent|x|times|grams?|kilos?|kg|degrees?|minutes?|hours?|days?|weeks?|"
                   r"months?|years?|dollars?|pounds?|euros?|people|customers?|clients?|orders?)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d[\d,.]*\b")
_QUESTION_OPENER = re.compile(r"^(?:why|how|what|when|who|which|is|are|do|does|did|can|could|would|should|so)\b",
                              re.IGNORECASE)


def topic_words(brand):
    """The words that mark an on-subject moment for THIS brand, taken from what it said about its
    own business, audience, pillars and offers. Nothing is shipped in; a bakery and a clinic get
    different sets."""
    data = brand.data
    audience = data.get("audience") or {}
    texts = [(data.get("business") or {}).get("what_we_do", ""), audience.get("who", "")]
    texts += list(audience.get("problems") or []) + list(audience.get("questions_they_ask") or [])
    for p in data.get("pillars") or []:
        texts += [p.get("name", ""), p.get("about", "")]
    for o in data.get("offers") or []:
        texts += [o.get("name", ""), o.get("what", "")]
    words = set()
    for t in texts:
        for tok in tokens_of(t):
            if len(tok) >= 5 and tok not in _STOPWORDS and "TODO" not in t:
                words.add(tok)
    return words


def score(text, topics):
    """(score, reasons) for one sentence. A hint about where to look, nothing more."""
    toks = set(tokens_of(text, keep_numbers=True))
    low = text.lower()
    reasons = {}
    units = len(_UNIT.findall(text))
    if units:
        reasons["numbers with units"] = units * 2
    numbers = len(_NUMBER.findall(text))
    if numbers:
        reasons["numbers"] = min(numbers, 2)
    surprise = len(toks & _SURPRISE_WORDS) + sum(1 for p in _SURPRISE_PHRASES if p in low)
    if surprise:
        reasons["strong reaction"] = surprise
    on_topic = len(toks & topics)
    if on_topic:
        reasons["on the brand's subjects"] = min(on_topic, 3)      # capped: a core word turns up everywhere
    if (toks & _CONTRARIAN) and (numbers or on_topic):
        reasons["contradicts something"] = 1                        # only counts next to something concrete
    return sum(reasons.values()), reasons


def looks_like_host(text):
    """With no voice labels, the best available guess at an interviewer's line: short, opens on a
    question word or a filler, or ends in a question mark. Such a line can sit inside a window,
    but it is never offered as the line worth lifting."""
    toks = tokens_of(text, keep_numbers=True)
    if len(toks) < MIN_LINE_WORDS or toks[0] in _FILLER_OPENERS:
        return True
    return bool(_QUESTION_OPENER.match(text.strip())) or text.strip().endswith("?")


def build_windows(transcript, policy, rules, topics):
    items = []
    for s in transcript.segments:
        sc, why = score(s["text"], topics)
        items.append({"seg": s, "score": sc, "why": why})

    windows, cur = [], None
    for item in items:
        if item["score"] <= 0:
            continue
        s = item["seg"]
        if cur and s["start"] - cur["end"] <= MERGE_GAP and (s["end"] - cur["start"]) <= MAX_WINDOW:
            cur["end"] = s["end"]
            cur["score"] += item["score"]
            cur["members"].append(item)
        else:
            if cur:
                windows.append(cur)
            cur = {"start": s["start"], "end": s["end"], "score": item["score"], "members": [item]}
    if cur:
        windows.append(cur)

    for w in windows:
        inside = [s for s in transcript.segments if s["start"] >= w["start"] - 0.01 and s["end"] <= w["end"] + 0.01]
        if policy.labelled:
            liftable = [s for s in inside if policy.may_publish(s["speaker"])]
            w["text"] = " ".join(s["text"] for s in liftable)       # the gate reads only what could be in a clip
            liftable = [s for s in liftable if len(tokens_of(s["text"], keep_numbers=True)) >= MIN_LINE_WORDS]
        else:
            w["text"] = " ".join(s["text"] for s in inside)
            liftable = [s for s in inside if not looks_like_host(s["text"])]
        pool = liftable or inside
        best = max(pool, key=lambda s: score(s["text"], topics)[0])
        w["line"], w["line_at"], w["line_by"] = best["text"], best["start"], best["speaker"]
        w["has_liftable_line"] = bool(liftable)
        w["duration"] = round(max(w["end"] - w["start"], 1.0), 1)
        w["density"] = round(w["score"] / w["duration"], 3)           # per second, so length cannot win by itself
        w["why"] = sorted({k for m in w["members"] for k in m["why"]})
        w["verdict"] = gate.check(w["text"], rules)
    return windows


def collapse_retakes(windows):
    """When the same thing was said twice (a second take), keep the denser one and note the other."""
    kept = []
    for w in sorted(windows, key=lambda x: x["density"], reverse=True):
        mine = set(tokens_of(w["text"], keep_numbers=True))
        twin = None
        for k in kept:
            theirs = set(tokens_of(k["text"], keep_numbers=True))
            if mine and len(mine & theirs) / float(len(mine | theirs) or 1) >= SAME_TAKE:
                twin = k
                break
        if twin is not None:
            twin.setdefault("other_takes", []).append(round(w["start"], 1))
        else:
            kept.append(w)
    return kept


def find(brand, transcript, top=25, everyone_on_camera=False):
    """{"pass": [...], "quarantine": [...]} for one transcript. The brand is required."""
    brand = as_brand(brand)
    rules = gate.GateRules.for_brand(brand)
    policy = gate.SpeakerPolicy.for_transcript(brand, transcript, everyone_on_camera)
    windows = collapse_retakes(build_windows(transcript, policy, rules, topic_words(brand)))
    windows.sort(key=lambda w: w["start"])

    def entry(w):
        return {"start": round(w["start"], 1), "end": round(w["end"], 1), "duration": w["duration"],
                "gate": w["verdict"].status, "reasons": list(w["verdict"].reasons), "why_look": w["why"],
                "density": w["density"], "line": w["line"], "line_at": round(w["line_at"], 1),
                "line_by": w["line_by"], "has_liftable_line": w["has_liftable_line"],
                "other_takes": w.get("other_takes", [])}

    passes = [w for w in windows if w["verdict"].status == gate.PASS and w["duration"] >= MIN_WINDOW
              and w["score"] >= MIN_SCORE and w["has_liftable_line"]]
    if len(passes) > top:                                   # trim the quietest, then put back in time order
        passes = sorted(sorted(passes, key=lambda w: w["density"], reverse=True)[:top], key=lambda w: w["start"])
    quarantine = [w for w in windows if w["verdict"].status != gate.PASS]
    return {"brand": brand.id, "speaker_check": policy.status, "on_camera": policy.on_camera(),
            "kept_out": policy.off_camera(), "pass": [entry(w) for w in passes],
            "quarantine": [entry(w) for w in quarantine]}


def as_markdown(result, recording, rules):
    lines = ["# Places to look: %s" % recording, "",
             "These are hints about where to read first, in the order they happen. They are NOT a ranking and "
             "say nothing about how a clip will do. Read the transcript, pick by the rubric "
             "(playbooks/clip-rubric.md), and copy hooks word for word.", ""]
    if result["kept_out"]:
        lines += ["Kept out of every clip: %s." % ", ".join(result["kept_out"]), ""]
    if result["speaker_check"] == "unverified":
        lines += ["Who is speaking is **unverified** for this transcript: check every line you lift by ear.", ""]

    def row(e):
        out = "- **[%s - %s]** (%ds) %s" % (fmt_ts(e["start"]), fmt_ts(e["end"]), round(e["duration"]),
                                            ", ".join(e["why_look"]))
        if e["reasons"]:
            out += "\n  - %s: %s" % (e["gate"], "; ".join(e["reasons"]))
        who = ("%s, " % e["line_by"]) if e["line_by"] else ""
        out += "\n  - line (%s%s): \"%s\"" % (who, fmt_ts(e["line_at"]), e["line"])
        if not e["has_liftable_line"]:
            out += "\n  - no clean on-camera line was found in this stretch"
        if e["other_takes"]:
            out += "\n  - said again at: %s" % ", ".join(fmt_ts(t) for t in e["other_takes"])
        return out

    lines += ["## PASS: read these first (%d)" % len(result["pass"]), ""]
    lines += [row(e) for e in result["pass"]] or ["Nothing stood out. That is a statement about the signals, not "
                                                  "about the recording; read the transcript anyway."]
    lines += ["", "## QUARANTINE: the brand's rules flagged these (%d)" % len(result["quarantine"]), ""]
    if result["quarantine"]:
        who = rules.sign_off_by or "the person who signs off for this brand (not set yet)"
        lines += ["DROP never publishes. HOLD publishes only with the brand's disclaimer and a sign-off from %s. "
                  "Nothing here was deleted." % who, ""]
    lines += [row(e) for e in result["quarantine"]] or ["Nothing was flagged."]
    return "\n".join(lines) + "\n"


def run(brand, recording, top=25, everyone_on_camera=False):
    """Read the recording's transcript, write candidates.md and candidates.json into the recording's
    Output folder, and start a cut list with its reference block filled in if there is none yet."""
    brand = as_brand(brand)
    transcript = Transcript.load(brand, recording)
    rules = gate.GateRules.for_brand(brand)
    policy = gate.SpeakerPolicy.for_transcript(brand, transcript, everyone_on_camera)
    policy.require_checkable()
    result = find(brand, transcript, top=top, everyone_on_camera=everyone_on_camera)
    result["recording"] = recording
    out = output_dir(brand, recording)
    write_text_atomic(os.path.join(out, "candidates.md"), as_markdown(result, recording, rules))
    write_json_atomic(os.path.join(out, "candidates.json"), result)
    started = False
    cut_list = os.path.join(out, CUT_LIST_FILE)
    if not os.path.exists(cut_list):
        write_text_atomic(cut_list, cutlist.starter(brand, recording, transcript, policy))
        started = True
    result["started_cut_list"] = started
    return result
