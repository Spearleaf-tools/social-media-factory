"""lint.py - the copy checker. Universal rules plus the brand's own rules, nothing hardcoded.

A caption PASSES when it has no ERROR findings. WARN findings are shown to the person reviewing
and never block.

Universal (every brand, because the platform enforces it or a reader is harmed):
    character limits per platform; a thread only on X; media required on Instagram (in gates.py).
Brand (from the brand's settings, all adjustable in onboarding):
    never-mention names, banned words and phrases, the plain-language pack, em-dashes,
    sentence and paragraph length, no @ or # on chosen platforms, regulated-industry terms.

    from smf.studio.lint import Rules, lint_caption
    rules = Rules.for_brand(brand)
    findings = lint_caption(text, "linkedin", rules)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Hard per-platform character caps. Over the limit is an ERROR: the platform will refuse it.
PLATFORM_CHAR_LIMITS = {
    "twitter": 280, "instagram": 2200, "linkedin": 3000, "facebook": 63206,
    "threads": 500, "bluesky": 300, "tiktok": 2200, "youtube": 5000, "pinterest": 500, "gmb": 1500,
}

# The plain-language pack: words and phrases that read as filler or machine-written. On by
# default for every brand; a brand can switch the pack off or add its own.
PLAIN_LANGUAGE_WORDS = [
    "comprehensive", "cutting-edge", "state-of-the-art", "game-changer", "game changer", "innovative",
    "groundbreaking", "revolutionary", "supercharge", "world-class", "best-in-class", "top-notch",
    "unparalleled", "delve", "embark", "navigate the landscape", "at the forefront", "beacon", "myriad",
    "plethora", "multifaceted", "synergy", "paradigm", "leverage", "spearhead", "garner", "interplay",
    "intricacies", "paramount", "noteworthy", "undoubtedly", "moreover", "furthermore", "tapestry", "boasts",
]
PLAIN_LANGUAGE_PHRASES = [
    "in today's", "in the world of", "whether you're looking for", "it's important to note that",
    "it's worth mentioning", "let's dive in", "let's explore", "let's break this down",
    "here's what you need to know", "now let's look at", "without further ado", "stands as a testament",
    "is a testament to", "serves as a reminder", "marking a pivotal moment", "key turning point",
    "evolving landscape", "represents a shift", "marks a shift", "indelible mark", "deeply rooted",
    "underscores its importance", "reflects broader", "setting the stage for", "contributing to the broader",
    "industry reports indicate", "observers have cited", "experts argue", "some critics argue",
    "several sources", "is widely regarded", "at its core", "what really matters", "the real question is",
    "the deeper issue", "the heart of the matter", "the future looks bright", "exciting times lie ahead",
    "step in the right direction", "journey toward excellence", "possibilities are endless",
    "i hope this helps", "let me know if", "would you like me to", "you're absolutely right", "navigating the",
    # spoken-video filler
    "buckle up", "crushing it", "next level", "moving the needle", "absolutely wild", "mind-blowing",
    "in this video i'm going to", "today i want to talk about", "hopefully this was helpful",
    "as you can see", "without going too deep", "studies show", "research suggests", "experts say",
    "trust me bro", "literally just", "i'm not gonna lie",
]
SOFT_WORDS = [
    "realm", "robust", "foster", "intricate", "nuanced", "valuable", "pivotal", "vital", "crucial", "tailor",
    "enhance", "elevate", "optimal", "strive", "enduring", "renowned", "passionate", "dedicated", "underscore",
    "vibrant", "breathtaking", "captivating", "nestled", "bespoke", "holistic",
]
# Promises a business usually cannot keep. WARN: soften, or make sure a real offer backs it.
OVERPROMISE_RULES = [
    (r"\bwill fix\b", "Use 'can help fix' or 'helps fix'"),
    (r"\bwill solve\b", "Use 'can help solve'"),
    (r"\bwill eliminate\b", "Use 'can reduce' or 'helps address'"),
    (r"\bwill prevent\b", "Use 'can help prevent'"),
    (r"\bwill cure\b", "Use 'may help with'"),
    (r"\balways works\b", "Use 'typically' or 'in most cases'"),
    (r"\b100% effective\b", "Remove, or say what the evidence actually shows"),
    (r"\bnever fails\b", "Remove or soften"),
    (r"\bpermanently\b", "Use 'long-lasting' or 'durable'"),
    (r"\bguarantee[sd]?\b", "Fine only when it names a guarantee the brand really offers (see its offers)"),
]
# "It's not just X, it's Y": only a tell when the contrast actually pairs up.
NEGATIVE_PARALLELISM = [
    r"\bnot only\b[^.?!]*\bbut\b",
    r"\bit'?s not just\b[^.?!]*\bit'?s\b",
    r"\bit'?s not merely\b[^.?!]*\bit'?s\b",
]

_TRAILING_TAGS = re.compile(r"(?:\s*(?:#\w+|@\w+))+\s*$")
_WORD = re.compile(r"\S+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")
# A letter must follow @ or #, so "#1" (number one) is not a hashtag.
_MENTION_OR_HASHTAG = re.compile(r"(?<!\w)[@#][A-Za-z]\w*")
_GENERIC_LEAD_WORDS = {"pool", "spa", "health", "care", "injury", "mental", "market", "academy", "group",
                       "company", "studio", "clinic", "dental", "law", "the", "and", "first", "best", "home"}


@dataclass
class Finding:
    severity: str        # "ERROR" | "WARN"
    rule: str
    detail: str
    excerpt: str = ""

    def __str__(self):
        loc = ' - "%s"' % self.excerpt if self.excerpt else ""
        return "[%s] %s: %s%s" % (self.severity, self.rule, self.detail, loc)


@dataclass
class Rules:
    """Everything brand-specific the checker needs. Build it from a Brand; never from a default."""
    no_em_dashes: bool = True
    max_sentence_words: int = 22
    max_paragraph_words: int = 50
    max_paragraph_sentences: int = 3
    no_tags_on: tuple = ("facebook", "linkedin")
    plain_language_pack: bool = True
    banned_words: list = field(default_factory=list)
    banned_phrases: list = field(default_factory=list)
    never_mention: list = field(default_factory=list)
    own_brands: list = field(default_factory=list)
    drop_terms: list = field(default_factory=list)      # regulated: must never publish
    hold_terms: list = field(default_factory=list)      # regulated: needs disclaimer + sign-off
    _never_patterns: list = field(default_factory=list, repr=False)

    @classmethod
    def for_brand(cls, brand):
        s = brand.style
        comp = brand.data.get("compliance", {}) or {}
        r = cls(no_em_dashes=bool(s["no_em_dashes"]), max_sentence_words=int(s["max_sentence_words"]),
                max_paragraph_words=int(s["max_paragraph_words"]),
                max_paragraph_sentences=int(s["max_paragraph_sentences"]),
                no_tags_on=tuple(p.lower() for p in s["no_tags_on"]),
                plain_language_pack=bool(s["plain_language_pack"]),
                banned_words=[w.lower() for w in s["banned_words"]],
                banned_phrases=[p.lower() for p in s["banned_phrases"]],
                never_mention=list(brand.data.get("never_mention", [])),
                own_brands=list(brand.data.get("own_brands", [])) + [brand.name],
                drop_terms=[t.lower() for t in comp.get("drop_terms", [])],
                hold_terms=[t.lower() for t in comp.get("hold_terms", [])])
        r.compile()
        return r

    def compile(self):
        """Name patterns: the full name, plus a distinctive first word so 'Harbour Street' alone
        is still caught. Never a pattern under 5 letters, never a generic word, never an own brand."""
        own = {o.lower() for o in self.own_brands}
        seen, out = set(), []

        def add(raw, label):
            if raw not in seen:
                seen.add(raw)
                out.append((re.compile(raw, re.IGNORECASE), label))

        for name in sorted(self.never_mention):
            if not name.strip() or name.lower() in own:
                continue
            add(r"(?<!\w)" + re.escape(name.strip()) + r"(?!\w)", name)
            parts = name.split()
            if len(parts) >= 2:
                lead = parts[0]
                if len(lead) >= 5 and lead.lower() not in _GENERIC_LEAD_WORDS and lead.lower() not in own:
                    add(r"(?<!\w)" + re.escape(lead) + r"(?!\w)", name)
        self._never_patterns = out
        return self


def _strip_trailing_tags(text):
    return _TRAILING_TAGS.sub("", text).rstrip()


def _words(s):
    return len(_WORD.findall(s))


def _sentences(paragraph):
    return [s for s in _SENTENCE_SPLIT.split(paragraph.strip()) if s.strip()]


def lint_caption(text, platform, rules):
    """All findings for one caption. `rules` is required: there is no default brand."""
    if not isinstance(rules, Rules):
        raise TypeError("lint_caption needs the brand's Rules (Rules.for_brand(brand)); there is no default brand")
    findings = []
    low = text.lower()
    plat = (platform or "").lower()

    limit = PLATFORM_CHAR_LIMITS.get(plat)
    if limit is not None and len(text) > limit:
        findings.append(Finding("ERROR", "char-limit", "%d characters; %s allows %d." % (len(text), plat, limit),
                                text[max(0, limit - 15):limit + 15].strip()[:60]))

    if plat in rules.no_tags_on:
        for tag in _MENTION_OR_HASHTAG.findall(text):
            kind = "mentions" if tag.startswith("@") else "hashtags"
            findings.append(Finding("ERROR", "no-tags", "This brand does not use %s on %s." % (kind, plat), tag))

    if rules.no_em_dashes:
        for bad in ("—", "–", "--"):
            if bad in text:
                findings.append(Finding("ERROR", "em-dash", "No long dashes. Use a comma, a full stop or brackets.", bad))
                break

    # Beats are separated by blank lines. A multi-line beat is a list (steps, line items) and is
    # exempt from the paragraph caps; every line still obeys the sentence cap.
    body = _strip_trailing_tags(text)
    for beat in [p for p in re.split(r"\n\s*\n", body) if p.strip()]:
        if "\n" in beat.strip():
            for line in beat.splitlines():
                item = _LIST_MARKER.sub("", line.strip())
                for s in _sentences(item) or [item]:
                    if _words(s) > rules.max_sentence_words:
                        findings.append(Finding("WARN", "sentence-words", "Line is %d words (aim for %d or fewer)."
                                                % (_words(s), rules.max_sentence_words), s[:60]))
            continue
        sents = _sentences(beat)
        if _words(beat) > rules.max_paragraph_words:
            findings.append(Finding("WARN", "paragraph-words", "Paragraph is %d words (aim for %d or fewer)."
                                    % (_words(beat), rules.max_paragraph_words), beat[:60]))
        if len(sents) > rules.max_paragraph_sentences:
            findings.append(Finding("WARN", "paragraph-sentences", "Paragraph has %d sentences (aim for %d or fewer)."
                                    % (len(sents), rules.max_paragraph_sentences), beat[:60]))
        for s in sents:
            if _words(s) > rules.max_sentence_words:
                findings.append(Finding("WARN", "sentence-words", "Sentence is %d words (aim for %d or fewer)."
                                        % (_words(s), rules.max_sentence_words), s[:60]))

    words = list(rules.banned_words) + (PLAIN_LANGUAGE_WORDS if rules.plain_language_pack else [])
    for w in words:
        if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low):
            findings.append(Finding("ERROR", "banned-word", "Banned word: '%s'." % w, w))
    phrases = list(rules.banned_phrases) + (PLAIN_LANGUAGE_PHRASES if rules.plain_language_pack else [])
    for p in phrases:
        if p in low:
            findings.append(Finding("ERROR", "banned-phrase", "Banned phrase: '%s'." % p, p))

    if rules.plain_language_pack:
        for pat in NEGATIVE_PARALLELISM:
            m = re.search(pat, low)
            if m:
                findings.append(Finding("ERROR", "negative-parallelism",
                                        "'Not only X but Y' reads as filler. Say the point directly.", m.group(0)[:50]))
        for w in SOFT_WORDS:
            if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low):
                findings.append(Finding("WARN", "soft-word", "Overused word '%s'. Swap it if that is easy." % w, w))

    for pat, suggestion in OVERPROMISE_RULES:
        m = re.search(pat, low)
        if m:
            findings.append(Finding("WARN", "overpromise", suggestion, m.group(0)))

    for term in rules.drop_terms:
        if term and term in low:
            findings.append(Finding("ERROR", "never-publish", "This brand's rules say '%s' must never publish." % term, term))
    for term in rules.hold_terms:
        if term and term in low:
            findings.append(Finding("WARN", "needs-sign-off",
                                    "'%s' needs the brand's disclaimer and a named sign-off before it ships." % term, term))

    for pattern, canonical in rules._never_patterns:
        m = pattern.search(text)
        if m:
            findings.append(Finding("ERROR", "never-mention",
                                    "'%s' is on this brand's never-mention list. Describe them by industry instead."
                                    % canonical, m.group(0)))
    return findings


def is_clean(text, platform, rules):
    return not any(f.severity == "ERROR" for f in lint_caption(text, platform, rules))
