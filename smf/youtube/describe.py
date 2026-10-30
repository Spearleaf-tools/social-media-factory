"""describe.py - the description under a long video, and the chapters inside it.

A description is a search surface, not a caption. It is the longest piece of text attached to
the video, it is read by the platform and by AI answer tools, and its first two lines are all
most people ever see. So it has a fixed order:

    line 1      the question the video answers (the search phrase, word for word, when there is
                one) and the start of the answer
    line 2      the one link that goes with the video's ask, when the brand has one
    then        the short answer, written out: 40 to 80 words a person could read aloud
    then        the chapters
    then        other wordings of the same question that the video also answers
    then        who is speaking, and the brand's standing disclaimer when it has one
    last        three to five hashtags

CHAPTERS (the platform's rules, as of June 2026)
The list must start at 00:00, have at least three entries, run in rising order, and no chapter
may be shorter than ten seconds. Break one of those and the platform shows no chapters at all,
silently. Timestamps are written `00:00`, and `1:02:03` once a video passes the hour. A chapter
is named as a question or a claim the viewer can choose ("Why the dough felt ready and was
not"), never as a position ("Part 2").

Chapters can be worked out from the structure before anything is filmed (each segment's share of
the running time), and then replaced with the real times from the edit.

Nothing here writes the answer. The words come from the person and their script; this module
lays them out and checks them.
"""
from __future__ import annotations

import re

from smf.studio import grounding
from smf.studio.lint import PLATFORM_CHAR_LIMITS
from smf.youtube import YouTubeError, as_brand
from smf.youtube import titles as T

MIN_CHAPTERS = 3
MIN_CHAPTER_SECONDS = 10
CHAPTER_TITLE_MAX = 60
DESCRIPTION_LIMIT = PLATFORM_CHAR_LIMITS["youtube"]
SHOWN_BEFORE_MORE = 150          # roughly what shows before "more", as of June 2026
THIN_WORDS = 80
HASHTAGS_AIM = 5
HASHTAGS_IGNORED_ABOVE = 60
ROUND_TO = 5                     # planned chapter times are rounded to five seconds

_STAMP = re.compile(r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?!\d)[\s\-:|]*(.*)$")
_POSITION_NAME = re.compile(r"^(?:part|section|chapter|segment|step)\s*\d+\s*$|^(?:intro|introduction|outro|"
                            r"conclusion|the end)\s*$", re.IGNORECASE)
_URL = re.compile(r"https?://\S+")
_HASHTAG = re.compile(r"(?<!\w)#[A-Za-z]\w*")
_PLACEHOLDER = re.compile(r"\bTODO\b")


# ----------------------------------------------------------------------------- timestamps
def stamp(seconds):
    """Seconds -> `00:00`, or `1:02:03` from the hour mark."""
    seconds = max(0, int(round(float(seconds))))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def to_seconds(text):
    """`04:30` or `1:02:03` -> seconds. Anything else is an error in plain words."""
    m = re.match(r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*$", str(text or ""))
    if not m or int(m.group(3)) > 59 or (m.group(1) and int(m.group(2)) > 59):
        raise YouTubeError("'%s' is not a time. Write chapter times like 00:00, 04:30 or 1:02:03." % text)
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def parse_chapters(text):
    """Chapter lines found in a block of text: [{"at": seconds, "title": str}], in the order written."""
    out = []
    for line in str(text or "").splitlines():
        m = _STAMP.match(line)
        if not m or not m.group(4).strip():
            continue
        if int(m.group(3)) > 59:
            continue
        at = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        out.append({"at": at, "title": m.group(4).strip()})
    return out


def format_chapters(chapters):
    return "\n".join("%s %s" % (stamp(c["at"]), str(c["title"]).strip()) for c in chapters)


def chapters_from_structure(structure):
    """Planned chapters from a structure: each segment starts where the shares before it end.

    structure = {"length_minutes": 9, "segments": [{"title": ..., "share": 5}, ...]}
    Shares are percentages of the running time. Times are rounded to five seconds, the first is
    always 00:00, and a segment with `"chapter": false` (a ten second re-hook, say) is folded
    into the one before it."""
    segments = list((structure or {}).get("segments") or [])
    try:
        total = float((structure or {}).get("length_minutes") or 0) * 60.0
    except (TypeError, ValueError):
        total = 0.0
    if not segments or total <= 0:
        return []
    out, used = [], 0.0
    for seg in segments:
        try:
            share = float(seg.get("share") or 0)
        except (TypeError, ValueError):
            share = 0.0
        at = total * used / 100.0
        used += share
        if seg.get("chapter") is False:
            continue
        rounded = 0 if not out else int(round(at / ROUND_TO) * ROUND_TO)
        out.append({"at": rounded, "title": str(seg.get("chapter_title") or seg.get("title") or "").strip()})
    return out


def check_chapters(chapters, length_seconds=None):
    """(problems, warnings) for a chapter list, against the platform's rules and good naming."""
    problems, warnings = [], []
    chapters = list(chapters or [])
    if not chapters:
        return ["There are no chapters. Add timestamps: people who skip stay, and search and AI tools link "
                "straight into a labelled section."], []
    if len(chapters) < MIN_CHAPTERS:
        problems.append("There are %d chapters. YouTube shows none at all unless there are at least %d."
                        % (len(chapters), MIN_CHAPTERS))
    if chapters[0].get("at") != 0:
        problems.append("The first chapter starts at %s. It has to start at 00:00 or YouTube ignores the whole list."
                        % stamp(chapters[0].get("at") or 0))
    for i, c in enumerate(chapters, 1):
        title = str(c.get("title") or "").strip()
        if not title:
            problems.append("Chapter %d (%s) has no name." % (i, stamp(c.get("at") or 0)))
            continue
        if len(title) > CHAPTER_TITLE_MAX:
            warnings.append("Chapter %d's name is %d characters; keep it under %d so it is not cut off: \"%s\""
                            % (i, len(title), CHAPTER_TITLE_MAX, title[:50]))
        if _POSITION_NAME.match(title):
            warnings.append("Chapter %d is called \"%s\". Name it for what the viewer gets there (a question or "
                            "a claim), so that someone skimming the list knows where to jump." % (i, title))
    for i in range(1, len(chapters)):
        gap = (chapters[i].get("at") or 0) - (chapters[i - 1].get("at") or 0)
        if gap <= 0:
            problems.append("Chapter %d (%s) does not come after chapter %d (%s). Times must rise."
                            % (i + 1, stamp(chapters[i].get("at") or 0), i, stamp(chapters[i - 1].get("at") or 0)))
        elif gap < MIN_CHAPTER_SECONDS:
            problems.append("Chapter %d is only %d seconds long. YouTube needs every chapter to last at least %d."
                            % (i, gap, MIN_CHAPTER_SECONDS))
    if length_seconds:
        last = chapters[-1].get("at") or 0
        if last >= length_seconds:
            problems.append("The last chapter starts at %s, which is after the video ends (%s)."
                            % (stamp(last), stamp(length_seconds)))
        elif length_seconds - last < MIN_CHAPTER_SECONDS:
            problems.append("The last chapter is shorter than %d seconds." % MIN_CHAPTER_SECONDS)
    return problems, warnings


# ----------------------------------------------------------------------------- building
def speaker_line(brand, identity_id):
    """One line saying who is speaking, built only from the brand's own settings."""
    try:
        who = brand.identity(identity_id)
    except Exception:
        return ""
    name = str(who.get("display_name") or "").strip()
    role = str(who.get("role") or "").strip()
    if who.get("kind") == "person" and name:
        return "%s%s, %s." % (name, (", " + role) if role else "", brand.name)
    return "%s." % (name or brand.name)


def needs_disclaimer(brand):
    """The brand's standing disclaimer, when it is a regulated business that has written one."""
    regulated = str((brand.data.get("business") or {}).get("regulated") or "none").strip().lower()
    text = str((brand.data.get("compliance") or {}).get("disclaimer") or "").strip()
    return text if (text and regulated not in ("", "none")) else ""


def build(brand, brief):
    """The description for one video, laid out in the fixed order. Words come from the brief:
    nothing is composed here. Whatever is still missing is left as a visible TODO so the check
    refuses it rather than letting a gap ship."""
    brand = as_brand(brand)
    desc = brief.get("description") or {}
    keyword = str(brief.get("keyword") or "").strip()
    opening = str(desc.get("opening") or "").strip()
    answer = str(desc.get("answer") or "").strip()
    cta = brief.get("call_to_action") or {}

    first = opening or (T.with_keyword(keyword) if keyword else "TODO: the question this video answers, in one line")
    lines = [first]
    link, ask = str(cta.get("link") or "").strip(), str(cta.get("text") or "").strip()
    if link:
        lines.append(("%s %s" % (ask.rstrip(".:"), link)).strip() if ask else link)
    lines += ["", answer or "TODO: the short answer, one short paragraph in the presenter's own words", ""]

    chapters = list(brief.get("chapters") or []) or chapters_from_structure(brief.get("structure"))
    if chapters:
        lines += ["Chapters", format_chapters(chapters), ""]
    also = [str(q).strip() for q in (desc.get("also_answers") or []) if str(q).strip()]
    if also:
        lines += ["Also answered in this video:"] + ["- %s" % q for q in also[:12]] + [""]
    who = speaker_line(brand, brief.get("identity"))
    if who:
        lines += [who]
    standing = needs_disclaimer(brand)
    if standing:
        lines += [standing]
    if who or standing:
        lines.append("")
    tags = ["#" + re.sub(r"[^A-Za-z0-9]", "", str(t)) for t in (desc.get("hashtags") or []) if str(t).strip()]
    tags = [t for t in tags if len(t) > 1]
    if tags:
        lines.append(" ".join(tags[:HASHTAGS_AIM]))
    return "\n".join(lines).strip() + "\n"


# ----------------------------------------------------------------------------- checking
def prose_only(text):
    """The description without its chapter lines, links and hashtags: the part that makes claims."""
    kept = [ln for ln in str(text or "").splitlines() if not _STAMP.match(ln) and not _PLACEHOLDER.search(ln)]
    return _HASHTAG.sub("", _URL.sub("", "\n".join(kept)))


def check(brand, text, keyword=None, link=None, proof_ids=(), length_seconds=None, final=True):
    """(problems, warnings) for a finished description.

    `final=False` is for a video that is still being packaged: gaps that will be filled later
    (a TODO, a thin answer) are warnings then, and problems once the video is called packaged."""
    brand = as_brand(brand)
    text = str(text or "")
    problems, warnings = [], []
    soft = warnings if not final else problems
    if not text.strip():
        return (["There is no description yet."] if final else []), ([] if final else ["There is no description yet."])

    if len(text) > DESCRIPTION_LIMIT:
        problems.append("The description is %d characters. YouTube allows %d." % (len(text), DESCRIPTION_LIMIT))
    if _PLACEHOLDER.search(text):
        soft.append("The description still has a TODO in it. Fill it in from the script, or take the line out.")
    words = len(re.findall(r"\S+", prose_only(text)))
    if words < THIN_WORDS:
        warnings.append("The description is %d words. A full one (the question, the short answer, the chapters) is "
                        "what search and AI answer tools read; aim for %d words or more." % (words, THIN_WORDS))

    first_lines = [ln for ln in text.splitlines() if ln.strip()][:2]
    if keyword and T._plain(keyword):
        ok, _why = T.keeps_keyword(text[:SHOWN_BEFORE_MORE], keyword)
        if not ok:
            warnings.append("The search phrase \"%s\" is not in the first %d characters, word for word. That opening "
                            "is what shows before \"more\" and what search reads first."
                            % (str(keyword).strip(), SHOWN_BEFORE_MORE))
    if link and not any(str(link).strip() in ln for ln in first_lines):
        warnings.append("The link for this video's ask is not in the first two lines, which are the only ones "
                        "that show without expanding.")

    chapter_problems, chapter_warnings = check_chapters(parse_chapters(text), length_seconds)
    (problems if final else warnings).extend(chapter_problems)
    warnings.extend(chapter_warnings)

    tags = _HASHTAG.findall(text)
    if len(tags) > HASHTAGS_IGNORED_ABOVE:
        problems.append("There are %d hashtags. Past %d YouTube ignores every one of them."
                        % (len(tags), HASHTAGS_IGNORED_ABOVE))
    elif len(tags) > HASHTAGS_AIM:
        warnings.append("There are %d hashtags. Three to five that fit is the useful range; only the first three "
                        "are shown." % len(tags))

    standing = needs_disclaimer(brand)
    if standing and standing not in text:
        soft.append("%s is a regulated business and its standing disclaimer is not in the description: \"%s\""
                    % (brand.name, standing))

    report = grounding.ground_draft(T.claims_only(prose_only(text)), brand, proof_ids=proof_ids)
    if report["ungrounded"]:
        problems.append("The description states %s, which does not trace to anything in %s's facts, research or "
                        "linked proof. Record it as a fact with its source, or take it out."
                        % (", ".join(report["ungrounded"]), brand.name))
    warnings.extend(report["hints"])
    more_problems, more_warnings = T.brand_findings(brand, text)
    problems.extend(more_problems)
    warnings.extend(more_warnings)
    return problems, warnings
