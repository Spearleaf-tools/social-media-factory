"""gate.py - the two checks that stand between a recording and a clip. Both come from the brand.

1. THE COMPLIANCE GATE: does this passage contain a claim the brand must never publish (DROP), or
   one that needs the brand's disclaimer and a named person's sign-off (HOLD)? Everything else is
   PASS. The rules are the brand's own `compliance` settings. A brand in a regulated field also
   gets a pack of claim patterns for that field. A brand with `regulated: none` runs with a
   nearly empty gate: its own terms and its never-mention list, nothing else.

2. THE SPEAKER GATE: who may appear in a clip? Anyone the brand lists under `video.host_names` is
   off camera and never appears. In a recording with more than one voice, a voice nobody has
   named yet does not appear either: not knowing who is speaking is a reason to stop, not to guess.

Both fail closed. No brand, no gate: there is nothing sensible to fall back on, because the
fallback would be one company's rules deciding what another company may say.

The gate flags. A person decides. Nothing here deletes anything.

    rules = GateRules.for_brand(brand)
    verdict = check("hip drops cure runner's knee", rules)     # Verdict(DROP, ["a cure claim ..."])
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from smf.studio.lint import Rules
from smf.video.common import VideoError, as_brand, norm_token

PASS, HOLD, DROP = "PASS", "HOLD", "DROP"
_RANK = {PASS: 0, HOLD: 1, DROP: 2}

# How far either side of an off-camera voice is kept out of a clip. A transcriber's "the voice
# changed here" is a decision about labels, not the moment the sound stops, so the bare boundary
# still carries the tail of the other voice. This MUST stay larger than rough_cut.MAX_LEAD: the
# rough cut is allowed to move a cut outward by up to MAX_LEAD to catch a whole word, and a pad
# smaller than that travel is no pad at all.
EXCLUDE_PAD = 0.75
# The hard limit. However a cut point is found, it is never placed closer than this to an
# off-camera voice. The pad above decides what is ASKED for; this decides what can be RENDERED.
WALL_GUARD = 0.30
# A kept sliver shorter than this is a stutter, not content.
MIN_PIECE = 0.5
# How a report records that a person vouched for a recording (see SpeakerPolicy).
ATTESTED = "a person said nobody is off camera"

_NUM = (r"(?:\d[\d,.]*|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|"
        r"sixty|seventy|eighty|ninety|hundred|thousand|half)")
_DOSE_UNIT = (r"(?:mg|milligrams?|mcg|micrograms?|ml|millilit(?:re|er)s?|iu|international units|tablets?|"
              r"capsules?|pills?|drops|sachets?)")
_CARE = (r"(?:medication|medications|medicine|medicines|meds|prescription|prescriptions|painkillers?|tablets|"
         r"pills|doctor|gp|surgeon|specialist|consultant|surgery|operation|treatment|scan|scans|injection|"
         r"injections)")

# The health pack. Written for the Factory; every pattern is a KIND of sentence, not a vocabulary
# of any one speciality. Invented lines each one catches are in tests/test_video.py.
HEALTH_PACK = [
    (DROP, "a cure claim", r"\b(?:cure|cures|cured|curing|miracle)\b"),
    (DROP, "a guaranteed result", r"\b(?:guarantee[sd]?|works every time|(?:always|never) (?:works|fails))\b"),
    (DROP, "a guaranteed result", r"\b(?:100|a hundred|one hundred) ?(?:%|percent\b)"),
    (DROP, "telling people to go without their usual care",
     r"\binstead of (?:your |the |a |any |seeing (?:your |a |the )?)?" + _CARE + r"\b"),
    (DROP, "telling people to go without their usual care",
     r"\b(?:stop|quit|ditch|skip|come off|throw away|bin) (?:taking |using )?(?:your |the |all (?:your )?)?" + _CARE + r"\b"),
    (DROP, "telling people to go without their usual care",
     r"\b(?:don'?t|do not|won'?t|will not|never) need (?:a |an |your |the |any )?" + _CARE + r"\b"),
    (DROP, "a specific dose",
     r"\b" + _NUM + r"(?:[\s-]+(?:(?:and|a|to|or)[\s-]+)?" + _NUM + r")*[\s-]*(?:a\s+)?" + _DOSE_UNIT + r"\b"),
    (HOLD, "dosing language", r"\b(?:dose|doses|dosage|dosing|milligrams?|prescrib\w+|protocol)\b"),
    (HOLD, "dosing language", r"\b(?:once|twice|" + _NUM + r" times) (?:a|per|every) day\b"),
    (HOLD, "one person's result (say it is one person's experience, not what everyone can expect)",
     r"\b(?:one of my|a|my) (?:patient|client)s?\b"),
    (HOLD, "a claim about what a treatment does",
     r"\b(?:heals?|healed|reverses?|reversed|eliminates?|gets? rid of|fix(?:es)? (?:your|the))\b"),
]
PACKS = {"generic": [], "health": HEALTH_PACK}


@dataclass
class Verdict:
    status: str
    reasons: list = field(default_factory=list)

    def __str__(self):
        return self.status if not self.reasons else "%s (%s)" % (self.status, "; ".join(self.reasons))


@dataclass
class GateRules:
    """Everything the compliance gate needs. Build it from a Brand; there is no default."""
    brand_id: str
    brand_name: str
    regulated: str = "none"
    pack: str = "generic"
    drop_terms: list = field(default_factory=list)
    hold_terms: list = field(default_factory=list)
    disclaimer: str = ""
    sign_off_by: str = ""
    _patterns: list = field(default_factory=list, repr=False)
    _never: list = field(default_factory=list, repr=False)

    @classmethod
    def for_brand(cls, brand):
        brand = as_brand(brand)                       # raises in plain words when no brand is named
        comp = brand.data.get("compliance") or {}
        regulated = (brand.data.get("business") or {}).get("regulated") or "none"
        pack = comp.get("pack") or "generic"
        if regulated == "health":
            pack = "health"                           # the field decides, even if the pack was left at generic
        if pack not in PACKS:
            raise VideoError("%s asks for a compliance pack called '%s', which this copy of the Factory does "
                             "not have. The packs are: %s." % (brand.name, pack, ", ".join(sorted(PACKS))))
        drop = [t.strip().lower() for t in comp.get("drop_terms") or [] if t and t.strip()]
        hold = [t.strip().lower() for t in comp.get("hold_terms") or [] if t and t.strip()]
        if regulated not in ("none", "health") and not drop and not hold:
            raise VideoError("%s works in a regulated field (%s) but has no compliance rules yet, so clips cannot "
                             "be checked. In the brand's settings, list the claims that must never be published "
                             "and the ones that need a disclaimer and a sign-off, then try again."
                             % (brand.name, regulated))
        rules = cls(brand_id=brand.id, brand_name=brand.name, regulated=regulated, pack=pack, drop_terms=drop,
                    hold_terms=hold, disclaimer=(comp.get("disclaimer") or "").strip(),
                    sign_off_by=(comp.get("sign_off_by") or "").strip())
        rules._patterns = [(status, why, re.compile(rx, re.IGNORECASE)) for status, why, rx in PACKS[pack]]
        rules._never = list(Rules.for_brand(brand)._never_patterns)
        return rules


def _term_pattern(term):
    """A brand's own term, matched from the start of a word. 'allergen' also catches 'allergens';
    'cure' does not catch 'secure'. Catching a little too much is the safe direction here."""
    return re.compile(r"(?<!\w)" + re.escape(term).replace(r"\ ", r"\s+"), re.IGNORECASE)


def check(text, rules):
    """The verdict for one passage. `rules` is required: there is no default brand.
    The gate leans toward flagging: holding back a harmless clip costs a minute of someone's
    attention, and letting a bad claim through costs far more."""
    if not isinstance(rules, GateRules):
        raise TypeError("check() needs the brand's GateRules (GateRules.for_brand(brand)); there is no default brand")
    text = (text or "").replace("\u2019", "'")
    found = []
    for term in rules.drop_terms:
        if _term_pattern(term).search(text):
            found.append((DROP, "'%s' is on %s's never-publish list" % (term, rules.brand_name)))
    for status, why, pattern in rules._patterns:
        m = pattern.search(text)
        if m:
            found.append((status, "%s: '%s'" % (why, m.group(0).strip())))
    for term in rules.hold_terms:
        if _term_pattern(term).search(text):
            found.append((HOLD, "'%s' needs %s's disclaimer and a sign-off" % (term, rules.brand_name)))
    for pattern, canonical in rules._never:
        if pattern.search(text):
            found.append((HOLD, "it names '%s', which is on the never-mention list" % canonical))
    if not found:
        return Verdict(PASS, [])
    worst = max(found, key=lambda f: _RANK[f[0]])[0]
    reasons = []
    for status, why in sorted(found, key=lambda f: -_RANK[f[0]]):
        if why not in reasons:
            reasons.append(why)
    return Verdict(worst, reasons)


def stricter(a, b):
    return a if _RANK[a] >= _RANK[b] else b


# ----------------------------------------------------------------------------- who may appear
_UNNAMED = re.compile(r"^(?:speaker|spk|voice|person|s)[\s_-]*\d+$|^unknown$", re.IGNORECASE)


def _name_tokens(name):
    return [t for t in (norm_token(p) for p in re.split(r"[\s._-]+", name or "")) if t]


class SpeakerPolicy(object):
    """Who may appear in a clip cut from one recording.

    The question is "who is on camera", and the brand answers half of it: its `video.host_names`
    are the people who are NOT. The other half is fail-closed:

      * a host never appears, however they are spelled ("Jonah", "JONAH PELL");
      * when the recording has two or more voices, a voice that has only a machine label
        (speaker_1) does not appear until a person names it;
      * when the recording has exactly one voice, it needs no name: there is nobody to confuse it with;
      * when the transcript carries no voice labels at all (it came from a subtitle file), nothing
        can be checked. That is reported as `unverified`, and if the brand has hosts the cut is
        refused until a person says that nobody is off camera in this recording.

    `everyone_on_camera=True` is that statement. It is a claim a person makes about one recording;
    it is never inferred, and the tools write it into their reports.
    """

    def __init__(self, brand, speakers, everyone_on_camera=False):
        brand = as_brand(brand)
        self.brand_name = brand.name
        self.hosts = [h.strip() for h in (brand.data.get("video") or {}).get("host_names") or [] if h and h.strip()]
        self._host_tokens = [set(_name_tokens(h)) for h in self.hosts if _name_tokens(h)]
        self.present = sorted({s for s in speakers if s})
        self.labelled = bool(self.present)
        self.everyone_on_camera = bool(everyone_on_camera)

    @classmethod
    def for_transcript(cls, brand, transcript, everyone_on_camera=False):
        return cls(brand, transcript.speakers, everyone_on_camera)

    @property
    def status(self):
        if self.everyone_on_camera:
            return ATTESTED
        return "checked" if self.labelled else "unverified"

    def is_host(self, name):
        toks = set(_name_tokens(name))
        if not toks:
            return False
        return any(h <= toks or toks <= h for h in self._host_tokens)

    @staticmethod
    def is_unnamed(name):
        return not (name or "").strip() or bool(_UNNAMED.match(name.strip()))

    def may_publish(self, name):
        """The only authority on whether a voice may be inside a clip."""
        if self.everyone_on_camera:
            return True
        if not self.labelled:
            return not self.hosts
        if self.is_unnamed(name):
            return len(self.present) == 1
        return not self.is_host(name)

    def on_camera(self):
        return [s for s in self.present if self.may_publish(s)]

    def off_camera(self):
        return [s for s in self.present if not self.may_publish(s)]

    def require_checkable(self):
        """Stop when the gate cannot do its job, instead of passing everything by default."""
        if self.everyone_on_camera:
            return
        if not self.labelled and self.hosts:
            raise VideoError(
                "This transcript does not say who is speaking, and %s has people who stay off camera (%s). "
                "Without voice labels their words cannot be kept out of a clip. Transcribe the recording with "
                "ElevenLabs so each voice is labelled. If nobody is off camera in this particular recording, "
                "say so and run it again with --nobody-off-camera." % (self.brand_name, ", ".join(self.hosts)))
        if self.labelled and not self.on_camera():
            unnamed = [s for s in self.present if self.is_unnamed(s)]
            if unnamed:
                raise VideoError(
                    "Nobody in this recording is cleared to appear in a clip yet, because the voices only have "
                    "machine labels (%s). Read the first lines of the transcript, work out who is who, and name "
                    "them (transcribe ... --name %s=\"Their Name\")." % (", ".join(unnamed), unnamed[0]))
            raise VideoError("Every voice in this recording (%s) is on %s's off-camera list, so there is nobody "
                             "left to make clips of." % (", ".join(self.present), self.brand_name))

    def describe(self):
        if self.everyone_on_camera:
            return "Everyone in this recording may appear (a person said nobody is off camera)."
        if not self.labelled:
            return "The transcript does not say who is speaking, so the speaker check is unverified."
        on, off = self.on_camera(), self.off_camera()
        text = "May appear in clips: %s." % (", ".join(on) or "nobody yet")
        if off:
            text += " Kept out: %s." % ", ".join(off)
        return text


def off_camera_turns(turns, policy):
    """The stretches that must not be inside a clip. A turn a few hundredths of a second long is
    an artefact of lining words up, carries no sound, and is ignored."""
    return [t for t in turns if not policy.may_publish(t.get("speaker")) and (t["end"] - t["start"]) > 0.05]


def subtract(start, end, blocks):
    """One stretch minus a list of (from, to) exclusions -> the pieces that survive, in order."""
    pieces = [(start, end)]
    for a, z in blocks:
        nxt = []
        for s, e in pieces:
            if z <= s or a >= e:
                nxt.append((s, e))
                continue
            if s < a:
                nxt.append((s, a))
            if z < e:
                nxt.append((z, e))
        pieces = nxt
    return [(s, e) for s, e in pieces if e - s >= MIN_PIECE]


def publishable_pieces(segment, turns, policy, pad=EXCLUDE_PAD):
    """Cut every off-camera voice out of one segment of a clip.

    `segment` is {"start", "end", "starts_with", "ends_with"} in TRANSCRIPT time. An off-camera turn
    in the middle SPLITS the segment. Each surviving piece comes back with:

      starts_with / ends_with   only on a piece that still holds that quoted word. Boundary words
                                say where the person meant the segment to begin and end. On an
                                edge made by removing a voice they would drag the cut back toward
                                the very sound that was just taken out, so they are dropped there.
                                They are kept when trimming only removed silence (a time that was
                                written a little early, say): the quoted word is still inside.
      lost_head / lost_tail     seconds of ON-camera talking that the trim cost at that edge.
      wall_lo / wall_hi         the nearest off-camera sound on each side, plus a guard. Whatever
                                moves a cut point later may not move it past a wall.
    """
    if pad <= WALL_GUARD:
        raise ValueError("the exclusion pad must be larger than the wall guard")
    off = off_camera_turns(turns, policy)
    blocks = [(t["start"] - pad, t["end"] + pad) for t in off]
    on = [t for t in turns if policy.may_publish(t.get("speaker"))]

    def spoken(a, z):
        return sum(max(0.0, min(t["end"], z) - max(t["start"], a)) for t in on) if z > a else 0.0

    out = []
    pieces = subtract(segment["start"], segment["end"], blocks)
    for i, (s, e) in enumerate(pieces):
        piece = {"start": round(s, 3), "end": round(e, 3), "starts_with": "", "ends_with": "",
                 "wall_lo": None, "wall_hi": None, "lost_head": 0.0, "lost_tail": 0.0}
        if i == 0:
            piece["lost_head"] = round(spoken(segment["start"], s), 2)
            if piece["lost_head"] <= 0.05:
                piece["starts_with"] = segment.get("starts_with", "")
        if i == len(pieces) - 1:
            piece["lost_tail"] = round(spoken(e, segment["end"]), 2)
            if piece["lost_tail"] <= 0.05:
                piece["ends_with"] = segment.get("ends_with", "")
        before = [t["end"] for t in off if t["end"] <= s + 0.01]
        after = [t["start"] for t in off if t["start"] >= e - 0.01]
        if before:
            piece["wall_lo"] = round(max(before) + WALL_GUARD, 3)
        if after:
            piece["wall_hi"] = round(min(after) - WALL_GUARD, 3)
        out.append(piece)
    return out


def off_camera_seconds(start, end, turns, policy):
    """How much off-camera talking sits inside a stretch (before any of it is removed)."""
    total = 0.0
    for t in off_camera_turns(turns, policy):
        total += max(0.0, min(t["end"], end) - max(t["start"], start))
    return round(total, 2)


def lower_third_for(brand, speaker_name):
    """The exact line shown under a person's face, from the brand's own settings, or "".

    It is the identity's `credential_line` when the speaker is one of the brand's people. Failing
    that, their display name and role. For anyone else it is empty: a credential is a claim, and
    the Factory does not make claims the brand did not write down."""
    brand = as_brand(brand)
    want = set(_name_tokens(speaker_name))
    people = [i for i in brand.data.get("identities", []) if i.get("kind") == "person"]
    chosen = None
    for ident in people:
        have = set(_name_tokens(ident.get("display_name", "")))
        if want and have and (want <= have or have <= want):
            chosen = ident
            break
    if chosen is None and not want and len(people) == 1:
        chosen = people[0]
    if chosen is None:
        return ""
    if (chosen.get("credential_line") or "").strip():
        return chosen["credential_line"].strip()
    role = (chosen.get("role") or "").strip()
    return "%s, %s" % (chosen["display_name"], role) if role else chosen["display_name"]
