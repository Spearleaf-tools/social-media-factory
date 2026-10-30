"""platforms.py - how each network wants a post written, and how old that knowledge is.

The mechanics live in `playbooks/profiles.json`: one block per platform (length, opening line,
structure, call-to-action and hashtag habits, do and don't) plus `_meta` with the date they were
last researched and the rules that hold everywhere.

    from smf.studio import platforms
    rules = platforms.load()
    rules.get("linkedin")["target_len"]
    if rules.is_stale():
        print(rules.warning())

WHY THERE IS AN AGE CHECK
Networks change what they reward several times a year, so advice about length or hashtags goes
off quietly. A copy of the Factory that someone downloaded will often be months old, so old
rules are a WARNING the caller shows to the person, never a refusal to work. Rules with no
readable date count as stale: if we cannot tell how old they are, we say so.
"""
from __future__ import annotations

import os
from datetime import date, datetime

from smf import brands
from smf.studio.files import StudioError, read_json
from smf.studio.lint import PLATFORM_CHAR_LIMITS

MAX_AGE_DAYS = 120
PLATFORM_FIELDS = ("max_len", "target_len", "opening_line_pattern", "structure_template", "cta_policy",
                   "hashtag_policy", "preferred_formats", "do", "dont")


class PlatformRulesError(StudioError):
    """The platform rulebook is missing, unreadable, or does not cover what was asked."""


def playbook_file():
    """Worked out at call time so the Factory can be moved (and tests can point it elsewhere)."""
    return os.path.join(brands.ROOT, "playbooks", "profiles.json")


class PlatformRules(object):
    def __init__(self, data, path):
        self.path = path
        self.meta = data.get("_meta") or {}
        self._platforms = {k.lower(): v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}

    # what is covered -----------------------------------------------------------------------
    @property
    def platforms(self):
        return sorted(self._platforms)

    @property
    def universal_rules(self):
        return [str(r) for r in (self.meta.get("universal_rules") or [])]

    def covers(self, platform):
        return (platform or "").lower() in self._platforms

    def get(self, platform):
        """The mechanics for one platform. An unknown platform is an error that says what exists."""
        key = (platform or "").lower()
        if key not in self._platforms:
            raise PlatformRulesError("There is no rulebook for '%s' in this copy of the playbooks. It covers: %s."
                                     % (platform, ", ".join(self.platforms) or "nothing yet"))
        return dict(self._platforms[key])

    def mechanics_for(self, platform):
        """Like get(), but a platform without a rulebook still gets something honest to write
        against: the hard character limit and a note saying that is all we know."""
        key = (platform or "").lower()
        if key in self._platforms:
            out = dict(self._platforms[key])
            out["known"] = True
            return out
        return {"known": False, "max_len": PLATFORM_CHAR_LIMITS.get(key),
                "note": "There is no rulebook for %s in this copy of the playbooks, so only its character "
                        "limit is known. Write plainly, and ask Claude to research a rulebook for it." % key}

    # how old -------------------------------------------------------------------------------
    @property
    def last_researched(self):
        raw = self.meta.get("last_researched")
        try:
            return datetime.strptime(str(raw), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    def age_days(self, today=None):
        """Days since the rules were researched, or None when the file carries no readable date."""
        when = self.last_researched
        if when is None:
            return None
        return ((today or date.today()) - when).days

    def is_stale(self, today=None):
        age = self.age_days(today)
        return age is None or age > MAX_AGE_DAYS

    def warning(self, today=None):
        """One plain sentence for the person, or None when the rules are fresh enough."""
        age = self.age_days(today)
        if age is None:
            return ("The platform rules carry no date, so there is no way to tell how old they are. "
                    "Ask Claude to refresh the playbooks.")
        if age > MAX_AGE_DAYS:
            return ("The platform rules are %d days old (researched %s). Networks change what they reward, "
                    "so ask Claude to refresh the playbooks. Writing still works in the meantime."
                    % (age, self.last_researched.strftime("%Y-%m-%d")))
        return None

    def status(self, today=None):
        return {"last_researched": self.meta.get("last_researched") or "", "age_days": self.age_days(today),
                "stale": self.is_stale(today), "warning": self.warning(today), "platforms": self.platforms}


def load(path=None):
    """Load the platform rulebook. A missing file is a plain error that names the file."""
    path = path or playbook_file()
    if not os.path.isfile(path):
        raise PlatformRulesError("The platform rulebook is missing: playbooks/profiles.json. It ships with the "
                                 "Factory; restore it, or ask Claude to research a new one.")
    data = read_json(path, "The platform rulebook (playbooks/profiles.json)")
    if not isinstance(data, dict):
        raise PlatformRulesError("The platform rulebook (playbooks/profiles.json) is not in the expected shape. "
                                 "Ask Claude to repair it.")
    return PlatformRules(data, path)


def age_days(today=None, path=None):
    return load(path).age_days(today)


def is_stale(today=None, path=None):
    return load(path).is_stale(today)
