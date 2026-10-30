"""validate.py - the script checker. The brand's rules decide; nothing here is hardcoded to a brand.

A script PASSES when it has no ERROR findings. WARN findings are shown and never block. Every
finding says where it is and what to do about it, in plain words.

Three families of check:

  1. THE BRAND'S RULES, applied to every word a viewer hears or reads. These come from
     `Rules.for_brand(brand)`: the sentence cap, banned words and phrases, long dashes, the
     never-mention list, and the regulated-industry terms. One thing is stricter here than for a
     written post: a sentence over the brand's cap is an ERROR, because a line that cannot be said
     in one breath cannot be recorded. Never-mention names are also checked in the visual
     directions, since a name that is filmed is a name that is published.

  2. THE SHAPE OF A SCRIPT. One idea. An opening whose three parts (the words on screen, the
     first picture, the first spoken line) agree with one promise and with each other. A visual
     direction beside every spoken line. A call to action that fits the script's job.

  3. SOURCING. A spoken line that states a fact needs a note saying where in the brand's own
     material it comes from. Numbers are traced to the brand's evidence. What cannot be traced is
     labelled unverified, and the opening may never lean on it.

    from smf.scripts.validate import check_script
    report = check_script(text, brand, batch="october-week-1", script_id="03")
    report["ok"], report["sourcing"], report["findings"]
"""
from __future__ import annotations

import re

from smf.scripts import brief as B
from smf.studio import cta as cta_lib
from smf.studio import grounding, topics
from smf.studio.files import as_brand
from smf.studio.lint import Finding, Rules, lint_caption

# How fast people talk on camera, in words per second. Used only to warn that a script will not
# fit its length; a person's own pace varies, so this never blocks.
SLOW_PACE, FAST_PACE = 2.0, 3.0
ON_SCREEN_WORDS = 8
MIN_LINES, MAX_LINES = 2, 9
MAX_SENTENCES_PER_LINE = 3
IDEA_WORDS = 32

# Findings the written-post checker raises that do not apply to a single spoken line.
_NOT_FOR_SPEECH = {"paragraph-words", "paragraph-sentences", "char-limit", "no-tags"}
# Raised as warnings for a written post, but a spoken line has to be sayable.
_STRICTER_WHEN_SPOKEN = {"sentence-words"}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_TODO = re.compile(r"\bTODO\b")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_PERCENT = re.compile(r"%|\bper ?cent\b", re.IGNORECASE)

# Words that carry no subject. Two lines that only share these do not agree about anything.
_EMPTY_WORDS = frozenset("""
a about after again all also always am an and any are as at be because been before being both but by can could
did do does doing done down each even ever every few for from get gets getting go goes going got had has have
having he her here hers him his how i if in into is it its just keep know let like make makes making many may me
might more most much must my need never new no not now of off on once one only or other our out over own really
same say see she should show so some still such take tell than that the their them then there these they thing
things this those through to too try under until up use used very want was way we well were what when where which
while who why will with without would yes yet you your yours video watch look here's that's it's don't
""".split())

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000}
_NUMBER_WORD = re.compile(r"\b(?:%s)(?:[ -](?:%s))*\b" % ("|".join(list(_TEENS) + list(_TENS) + list(_SCALES) + list(_UNITS)),
                                                          "|".join(list(_UNITS) + list(_TEENS) + list(_TENS) + list(_SCALES) + ["and"])),
                          re.IGNORECASE)


# ----------------------------------------------------------------------------- small helpers
def _words(text):
    return len((text or "").split())


def _sentences(text):
    return [s for s in _SENTENCE_END.split((text or "").strip()) if s.strip()]


def _stem(word):
    """A rough stem, good enough to see that 'loaves' and 'loaf', or 'proofed' and 'proofing',
    are the same subject. It is only ever used to compare two short phrases."""
    w = word.split("'")[0]
    for suffix, swap in (("ies", "y"), ("ves", "f"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3 and not (suffix == "s" and w.endswith("ss")):
            w = w[:len(w) - len(suffix)] + swap
            break
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou":
        w = w[:-1]
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


def subject_words(text):
    """The words in a phrase that could be its subject, as rough stems."""
    out = set()
    for w in _WORD.findall((text or "").lower()):
        if w in _EMPTY_WORDS or (len(w) < 3 and not w.isdigit()):
            continue
        out.add(_stem(w))
    return out


def _number_value(phrase):
    """'eighteen' -> 18, 'two hundred and fifty' -> 250. None when it is not a plain number."""
    total, current, seen = 0, 0, False
    for token in re.split(r"[ -]+", phrase.lower()):
        if token == "and":
            continue
        if token in _UNITS:
            current += _UNITS[token]
        elif token in _TEENS:
            current += _TEENS[token]
        elif token in _TENS:
            current += _TENS[token]
        elif token == "hundred":
            current = (current or 1) * 100
        elif token in _SCALES:
            total += (current or 1) * _SCALES[token]
            current = 0
        else:
            return None
        seen = True
    return (total + current) if seen else None


def digits_view(text):
    """The same sentence with spelled-out numbers from thirteen upwards written as digits, so
    "eighteen hours" can be traced to a fact that says 18. Smaller number words are left alone:
    "the two loaves" is a description, not a claim, and flagging it would bury the real findings.
    (Writers are told to put every real fact in digits.)"""
    def swap(match):
        value = _number_value(match.group(0))
        return str(value) if value is not None and value >= 13 else match.group(0)
    return _NUMBER_WORD.sub(swap, text or "")


def states_a_fact(text):
    """Does this line state something a viewer could check? True for any number that is not just
    counting the script's own parts, and for any percentage."""
    view = digits_view(text)
    if _PERCENT.search(view):
        return True
    return any(not n["structural"] for n in grounding.extract_numbers(view))


# ----------------------------------------------------------------------------- 1. the brand's rules
def _brand_rule_findings(where, text, rules, spoken):
    out = []
    for f in lint_caption(text, "", rules):
        if f.rule in _NOT_FOR_SPEECH:
            continue
        severity, detail = f.severity, f.detail
        if spoken and f.rule in _STRICTER_WHEN_SPOKEN:
            severity = "ERROR"
            detail = ("%s This brand's limit is %d words. Split it so it can be said in one breath."
                      % (f.detail, rules.max_sentence_words))
        out.append(Finding(severity, f.rule, "%s: %s" % (where, detail), f.excerpt))
    return out


def _never_mention_findings(where, text, rules):
    return [Finding(f.severity, f.rule, "%s: %s" % (where, f.detail), f.excerpt)
            for f in lint_caption(text, "", rules) if f.rule == "never-mention"]


# ----------------------------------------------------------------------------- 2. the shape
def _agreement_findings(opening):
    """The three parts of an opening must each carry the subject of the promise, and the words a
    viewer reads must share a subject with the words they hear."""
    out = []
    promise = subject_words(opening.promise)
    if not promise:
        if opening.promise:
            out.append(Finding("ERROR", "hook-promise", "The opening: the promise does not name a subject. Say what "
                               "the viewer gets in a few plain words, for example 'how to tell when dough has "
                               "proofed'.", opening.promise[:60]))
        return out
    sample = ", ".join(sorted(w for w in _WORD.findall(opening.promise.lower())
                              if w not in _EMPTY_WORDS and len(w) >= 3)[:4])
    parts = (("the words on screen", opening.on_screen, "reads"),
             ("the first picture", opening.show, "sees"),
             ("the first spoken line", opening.say, "hears"))
    for name, text, verb in parts:
        if text and not (subject_words(text) & promise):
            out.append(Finding("ERROR", "hook-disagrees",
                               "The opening: %s and the promise are about different things. The viewer %s one "
                               "thing and is promised another. Bring the subject of the promise (%s) into %s, "
                               "or change the promise." % (name, verb, sample, name), text[:60]))
    if opening.on_screen and opening.say and not (subject_words(opening.on_screen) & subject_words(opening.say)):
        out.append(Finding("ERROR", "hook-disagrees",
                           "The opening: the words on screen and the first spoken line share no subject. Someone "
                           "watching without sound and someone listening would describe two different videos.",
                           opening.on_screen[:60]))
    return out


def _shape_findings(brief, brand, batch, script_id):
    out = []
    for problem in brief.problems:
        out.append(Finding("ERROR", "format", problem))

    if not brief.title or _TODO.search(brief.title):
        out.append(Finding("ERROR", "format", "The script has no title. The first line should be '# ' and the title."))

    # the header ties the file to one brand, one batch and one script
    said_brand = (brief.header.get("brand") or "").strip()
    if said_brand != brand.id:
        out.append(Finding("ERROR", "wrong-brand", "The script says it belongs to '%s', but it is being checked for %s "
                           "(%s). A script is only ever checked against its own brand's rules."
                           % (said_brand or "no brand", brand.name, brand.id)))
    if batch is not None and (brief.header.get("batch") or "").strip() != batch:
        out.append(Finding("ERROR", "wrong-batch", "The script says it belongs to the batch '%s', not '%s'."
                           % (brief.header.get("batch") or "", batch)))
    if script_id is not None and (brief.header.get("script") or "").strip() != str(script_id):
        out.append(Finding("ERROR", "wrong-script", "The script's header says it is script '%s', but the batch has it "
                           "as '%s'." % (brief.header.get("script") or "", script_id)))
    if not brief.speaker:
        out.append(Finding("ERROR", "format", "The header does not say who is speaking. Add 'Speaker:' with one of: %s."
                           % ", ".join(brand.identities)))
    elif brief.speaker not in brand.identities:
        out.append(Finding("ERROR", "speaker", "%s has no identity called '%s' (it has: %s)."
                           % (brand.name, brief.speaker, ", ".join(brand.identities))))
    if brief.job is None:
        out.append(Finding("ERROR", "job", "The header needs 'Job:' and one of reach, leads or trust. The job decides "
                           "how the script may end and how it is judged later."))
    seconds = brief.length_seconds
    if seconds is None:
        out.append(Finding("ERROR", "format", "The header needs 'Length:' in seconds, for example 'Length: 40 seconds'."))
    elif not 10 <= seconds <= 180:
        out.append(Finding("ERROR", "length", "A length of %d seconds is outside what a short video can be (10 to 180)."
                           % seconds))

    # one idea
    if not brief.idea or _TODO.search(brief.idea):
        out.append(Finding("ERROR", "one-idea", "The script does not state its one idea. Under 'The one idea', write "
                           "the single point this video makes, in one sentence."))
    else:
        if len(_sentences(brief.idea)) > 1:
            out.append(Finding("ERROR", "one-idea", "'The one idea' holds %d sentences. A short video makes one point. "
                               "Keep one sentence here and give the other point its own script."
                               % len(_sentences(brief.idea)), brief.idea[:60]))
        if _words(brief.idea) > IDEA_WORDS:
            out.append(Finding("WARN", "one-idea", "'The one idea' is %d words. If it cannot be said in about %d, it is "
                               "probably two ideas." % (_words(brief.idea), IDEA_WORDS), brief.idea[:60]))

    # the opening
    o = brief.opening
    for label, value in (("Promise", o.promise), ("On screen", o.on_screen), ("Show", o.show), ("Say", o.say)):
        if not value or _TODO.search(value):
            out.append(Finding("ERROR", "opening", "The opening is missing '%s'. An opening has a promise, the words "
                               "on screen, the first picture and the first spoken line." % label))
    if all(v and not _TODO.search(v) for v in (o.promise, o.on_screen, o.show, o.say)):
        out += _agreement_findings(o)
    if o.on_screen and _words(o.on_screen) > ON_SCREEN_WORDS:
        out.append(Finding("WARN", "on-screen-words", "The opening: %d words on screen. A viewer reads about %d before "
                           "deciding to stay." % (_words(o.on_screen), ON_SCREEN_WORDS), o.on_screen[:60]))

    # the lines
    real_lines = [ln for ln in brief.lines if ln.say or ln.show]
    if len(real_lines) < MIN_LINES:
        out.append(Finding("ERROR", "lines", "The script has %d line(s) after the opening. It needs at least %d."
                           % (len(real_lines), MIN_LINES)))
    elif len(real_lines) > MAX_LINES:
        out.append(Finding("WARN", "lines", "The script has %d lines. More than %d usually means more than one idea."
                           % (len(real_lines), MAX_LINES)))
    for ln in brief.lines:
        where = "Line %d" % ln.number
        if not ln.say or _TODO.search(ln.say):
            out.append(Finding("ERROR", "lines", "%s has no spoken words yet ('Say:')." % where))
        if not ln.show or _TODO.search(ln.show):
            out.append(Finding("ERROR", "no-picture", "%s has words but no picture. Add 'Show:' with what the viewer "
                               "sees while this is said. Every spoken line ships with its visual direction." % where))
        if ln.say and len(_sentences(ln.say)) > MAX_SENTENCES_PER_LINE:
            out.append(Finding("WARN", "line-sentences", "%s holds %d sentences under one picture. Split it so each part "
                               "gets its own picture." % (where, len(_sentences(ln.say))), ln.say[:60]))
        if ln.on_screen and _words(ln.on_screen) > ON_SCREEN_WORDS:
            out.append(Finding("WARN", "on-screen-words", "%s: %d words on screen. Keep text cards to about %d words."
                               % (where, _words(ln.on_screen), ON_SCREEN_WORDS), ln.on_screen[:60]))

    # does it fit its length
    if seconds and 10 <= seconds <= 180 and brief.spoken_words():
        n = brief.spoken_words()
        if n > seconds * FAST_PACE:
            out.append(Finding("WARN", "too-long", "About %d spoken words for %d seconds. Even a fast talker fits about "
                               "%d. Cut a line, or make the video longer." % (n, seconds, int(seconds * FAST_PACE))))
        elif n < seconds * SLOW_PACE * 0.5:
            out.append(Finding("WARN", "too-short", "Only %d spoken words for %d seconds. Either the video is shorter "
                               "than planned or a lot happens without words." % (n, seconds)))

    out += _cta_findings(brief, brand)
    return out


def _cta_findings(brief, brand):
    out, c, job = [], brief.cta, brief.job
    if not c.present:
        return [Finding("ERROR", "call-to-action", "The script has no 'Call to action' section. Add one, even if the "
                        "choice is 'Kind: none'.")]
    if c.kind not in B.CTA_KINDS:
        return [Finding("ERROR", "call-to-action", "The call to action needs 'Kind:' and one of: %s."
                        % ", ".join(sorted(B.CTA_KINDS)))]
    if job and job not in B.CTA_KINDS[c.kind]:
        allowed = sorted(k for k, jobs in B.CTA_KINDS.items() if job in jobs)
        out.append(Finding("ERROR", "call-to-action", "This is a %s script, so it cannot end with '%s'. A %s script ends "
                           "with one of: %s. Only a leads script may point at something the brand sells."
                           % (B.JOB_NAMES[job], c.kind, B.JOB_NAMES[job], ", ".join(allowed))))
    if c.kind == "none":
        if c.say:
            out.append(Finding("ERROR", "call-to-action", "The call to action says 'Kind: none' but still has spoken "
                               "words. Choose a kind, or remove the words."))
        return out
    if not c.say or _TODO.search(c.say):
        out.append(Finding("ERROR", "call-to-action", "The call to action has no spoken words yet ('Say:')."))
    if not c.show or _TODO.search(c.show):
        out.append(Finding("ERROR", "no-picture", "The call to action has words but no picture. Add 'Show:'."))

    library = cta_lib.load_library(brand)
    if c.kind == "offer":
        offers = {str(o.get("id")) for o in (brand.data.get("offers") or [])}
        if not c.offer:
            out.append(Finding("ERROR", "call-to-action", "An offer call to action needs 'Offer:' and the id of one of "
                               "%s's offers (%s)." % (brand.name, ", ".join(sorted(offers)) or "it has none yet")))
        elif c.offer not in offers:
            out.append(Finding("ERROR", "call-to-action", "%s has no offer called '%s' (it has: %s). A script may only "
                               "point at something the brand really sells."
                               % (brand.name, c.offer, ", ".join(sorted(offers)) or "none yet")))
    platforms = brief.platforms
    if not platforms and brief.speaker in brand.identities:
        platforms = brand.platforms_for(brief.speaker)      # where this speaker posts
    spoken_and_shown = " ".join(x for x in (c.say, c.on_screen) if x)
    if c.kind == "keyword":
        if not c.keyword:
            out.append(Finding("ERROR", "call-to-action", "A keyword call to action needs 'Keyword:' and the word."))
        else:
            spoken_and_shown += " comment %s" % c.keyword.upper()
    seen = set()
    for platform in platforms:
        for issue in cta_lib.check_cta(spoken_and_shown, brand, platform, job=job, library=library)["issues"]:
            if issue not in seen:
                seen.add(issue)
                out.append(Finding("ERROR", "call-to-action", "The call to action: %s" % issue))
    return out


# ----------------------------------------------------------------------------- 3. sourcing
def _source_findings(where, text, source, brand, proof_ids, in_opening):
    """Findings for one line that states a fact, plus whether it ended up unverified."""
    out, unverified = [], False
    note = (source or "").strip()
    if not note or _TODO.search(note):
        return [Finding("ERROR", "no-source", "%s states a fact but does not say where it comes from. Add 'Source:' "
                        "with where in %s's own material this is (for example fact:<id>, proof:<id> or a file in "
                        "the brand's folder). If it cannot be backed up, take the fact out."
                        % (where, brand.name), text[:60])], False
    found = topics.resolve_source_ref(brand, note)
    if not found["ok"]:
        return [Finding("ERROR", "source-missing", "%s points to '%s', but %s." % (where, note, found["detail"]),
                        text[:60])], False
    report = grounding.ground_draft(digits_view(text), brand, proof_ids=proof_ids)
    if found["kind"] == "note":
        unverified = True
        if in_opening:
            out.append(Finding("ERROR", "hook-unbacked", "%s leans on a fact whose only source is a note ('%s'). The "
                               "opening may only state what %s can show: point to a recorded fact, a proof item or a "
                               "file, or open a different way." % (where, note[:50], brand.name), text[:60]))
        else:
            out.append(Finding("WARN", "unverified", "%s: the source is a note ('%s'), so nobody can check it from the "
                               "brand's files. It is labelled unverified. Record it as a fact to change that."
                               % (where, note[:50]), text[:60]))
    if report["ungrounded"]:
        unverified = True
        numbers = ", ".join(report["ungrounded"])
        if in_opening:
            out.append(Finding("ERROR", "hook-unbacked", "%s states %s, which does not appear in any of %s's facts, "
                               "research or linked proof. The opening is never a fact the brand cannot back."
                               % (where, numbers, brand.name), text[:60]))
        else:
            out.append(Finding("WARN", "unverified", "%s states %s, which does not appear in any of %s's facts, "
                               "research or linked proof. It is labelled unverified until it does."
                               % (where, numbers, brand.name), text[:60]))
    return out, unverified


def _sourcing_findings(brief, brand):
    out, unverified = [], False
    o = brief.opening
    checks = []
    hook_text = " ".join(x for x in (o.on_screen, o.say) if x)
    if hook_text:
        checks.append(("The opening", hook_text, o.source, True))
    checks += [("Line %d" % ln.number, " ".join(x for x in (ln.say, ln.on_screen) if x), ln.source, False)
               for ln in brief.lines]
    if brief.cta.say:
        checks.append(("The call to action", " ".join(x for x in (brief.cta.say, brief.cta.on_screen) if x),
                       brief.cta.source, False))
    for where, text, source, in_opening in checks:
        if not states_a_fact(text) and not (source or "").strip():
            continue
        found, flagged = _source_findings(where, text, source, brand, brief.proof_ids, in_opening)
        out += found
        unverified = unverified or flagged
    return out, unverified


# ----------------------------------------------------------------------------- put together
def check_brief(brief, brand, batch=None, script_id=None):
    """Every finding for one script, against ONE named brand's rules.

    Returns {"ok", "sourcing", "findings", "errors", "warnings", "needs_sign_off", "sign_off_by",
             "spoken_words", "spoken_sha"}.
    `sourcing` uses the same three words as a written post: passed, unverified or blocked."""
    brand = as_brand(brand)
    rules = Rules.for_brand(brand)
    findings = _shape_findings(brief, brand, batch, script_id)

    published = [(where, text, True) for where, text in brief.spoken()]
    published += [("The opening, on screen", brief.opening.on_screen, False)] if brief.opening.on_screen else []
    published += [("Line %d, on screen" % ln.number, ln.on_screen, False) for ln in brief.lines if ln.on_screen]
    if brief.cta.on_screen:
        published.append(("The call to action, on screen", brief.cta.on_screen, False))
    for where, text, spoken in published:
        findings += _brand_rule_findings(where, text, rules, spoken)

    # a name that is filmed is a name that is published
    directions = [("The title", brief.title), ("The one idea", brief.idea), ("The opening picture", brief.opening.show)]
    directions += [("Line %d, the picture" % ln.number, ln.show) for ln in brief.lines]
    directions += [("The call to action picture", brief.cta.show)]
    directions += [("The filming notes", note) for note in brief.shoot_notes]
    for where, text in directions:
        if text:
            findings += _never_mention_findings(where, text, rules)

    sourcing_findings, unverified = _sourcing_findings(brief, brand)
    findings += sourcing_findings

    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARN"]
    blocked = any(f.rule in ("no-source", "source-missing", "hook-unbacked") for f in errors)
    sign_off = any(f.rule == "needs-sign-off" for f in warnings)
    comp = brand.data.get("compliance") or {}
    return {"ok": not errors,
            "sourcing": "blocked" if blocked else ("unverified" if unverified else "passed"),
            "findings": findings, "errors": [str(f) for f in errors], "warnings": [str(f) for f in warnings],
            "needs_sign_off": sign_off, "sign_off_by": comp.get("sign_off_by", "") if sign_off else "",
            "disclaimer": comp.get("disclaimer", "") if sign_off else "",
            "spoken_words": brief.spoken_words(), "spoken_sha": B.spoken_sha(brief)}


def check_script(text, brand, batch=None, script_id=None):
    """Check the text of a script file. See check_brief."""
    return check_brief(B.parse(text), brand, batch=batch, script_id=script_id)


def explain(report, title=""):
    """The report as a few plain lines for a person."""
    head = "'%s'" % title if title else "This script"
    if report["ok"]:
        out = ["%s passes every check. Sourcing: %s." % (head, report["sourcing"])]
    else:
        out = ["%s is not ready: %d thing(s) to fix." % (head, len(report["errors"]))]
    out += ["  fix:  %s" % _plain(e) for e in report["errors"]]
    out += ["  note: %s" % _plain(w) for w in report["warnings"]]
    if report["needs_sign_off"]:
        who = report["sign_off_by"] or "the person this brand named for sign-off"
        out.append("  This script needs the brand's disclaimer and a yes from %s before it is published." % who)
    return "\n".join(out)


def _plain(finding_text):
    return re.sub(r"^\[(?:ERROR|WARN)\]\s+[a-z-]+:\s+", "", finding_text)
