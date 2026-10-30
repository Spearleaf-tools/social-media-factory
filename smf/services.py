"""services.py - the outside services, from one list (smf/services.json).

    from smf import services
    services.load()                    the list, as written
    services.cost_line(s, today)       the price words, or "last checked ... see the link" once stale
    services.markdown()                SERVICES.md, the plain guide (written by `factory.py guide`)

Prices live only in services.json, each with the date it was checked and its source, so SERVICES.md,
the setup checklist, GUIDE.md and the setup skill's walkthroughs never disagree (spec rev 11, "One
source, so nothing drifts"). SERVICES.md shows the date beside every price, so it never goes out of
date silently; what Claude says in the chat switches to "check the link" once a price is older than
stale_after_days.
"""
from __future__ import annotations

import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "smf", "services.json")
MARKDOWN = os.path.join(ROOT, "SERVICES.md")


def load():
    with open(PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def by_id(service_id):
    return next((s for s in load()["services"] if s["id"] == service_id), None)


def for_key(key_name):
    return next((s for s in load()["services"] if key_name in s["keys"]), None)


def _date(text):
    return datetime.date(*(int(x) for x in text.split("-")))


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")      # fixed English names: the page must read the same on any computer


def checked_words(service):
    d = _date(service["checked"])
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


def is_stale(service, today=None):
    today = today or datetime.date.today()
    return (today - _date(service["checked"])).days > load()["stale_after_days"]


def cost_line(service, today=None):
    """What to say about the price right now: the price, or, once it is stale, where to check it."""
    if is_stale(service, today):
        return "Price last checked %s; check it here before signing up: %s" % (checked_words(service), service["source"])
    return service["cost"]


ADD_KEY = ("**Add it.** Say *add my keys*. Your keys file opens in your own editor. %s, with no spaces, "
           "then save, close the file and say *done*. Claude never reads it back.")


def _paste(service):
    """Which value goes after which `NAME=`: two different values for Metricool, never the same one twice."""
    words = service.get("key_words") or {}
    parts = ["%s after `%s=`" % (words.get(k, "the key"), k) for k in service["keys"]]
    return "Paste " + " and ".join(parts)


SPENDING_WORDS = {"subscription": "Subscription", "credit": "Prepaid credit",
                  "plan": "Free plan; paid plans renew monthly", "free": "Free"}
CHECK = ("**Check it.** Say *check my setup*. Each feature says **ready** (checked with the service), **unverified** "
         "(the key is there and gets checked the first time it's used, or now if you say *check my keys online*), "
         "**needs a key**, or **key not working** with the reason in plain words.")
WRONG = ("**If something goes wrong.** The usual causes: a space pasted with the key, the wrong key copied, or no "
         "credit left on the account. Take a screenshot with nothing private showing, and ask Claude.")

INTRO = """# Outside services: what they're for, what they cost, how to set them up

**You can start with nothing beyond Claude.** Writing posts, making carousels and cards, reviewing them
and saving a ready-to-post folder need no other account and cost nothing more. (Posting by hand still
needs your own social accounts.) The services below are only for the features that use them, so set up
a service only when you want one of its features.

This page is made from `smf/services.json`, the one place the prices live, so it always says the same as
Claude. Every price shows the date it was checked: prices change, so follow the link before you pay.

## Words, explained once

- **Account and plan:** your login with a company, and what you pay them.
- **API key** (or token): a long password that lets the Social Media Factory use a service as you. Whoever
  has it can spend your money there, so it lives only in your keys file. You can delete it and make a new
  one any time.
- **Keys file:** a plain text file in your Social Media Factory folder (`keys.env`) that only your
  computer reads. It is never uploaded.
- **Subscription, free plan, credit:** a subscription charges on a set date whatever you use. A free
  plan is never charged; paid plans of the same service are subscriptions. Prepaid credit runs out
  (sometimes slightly over). A reminder or an alert is never a limit.

## Always

%(always)s

## At a glance

| Service | What it's for | Cost | How spending is limited |
|---|---|---|---|
%(table)s

## Posting: four ways, in the order we suggest

1. **Post by hand from the ready-to-post folder.** No extra account or cost. Where everyone starts.
2. **Metricool,** when posting by hand becomes the bottleneck. Then build trust a step at a time: two
   scheduled posts first, check them the next day ("did my posts go out?"), then full scheduling.
3. **Direct apps with Meta, TikTok and YouTube: not offered yet.** Each platform wants weeks of paperwork,
   so don't start it for nothing.
4. **An AI posting through your browser: never.** It breaks every platform's rules, and the account can
   be banned without warning.

## Someone helping you set it up

Your business should own its own accounts, with a recovery email and phone it controls. A helper gets
their own login through the service's team or member invite where there is one, never your password. If
a helper pays for an account you use, they paste the key in with you there, and you don't change its
billing or plan.
"""


def _section(s):
    out = ["## %s" % s["name"], "",
           "**What it does for you:** %s." % s["for"].rstrip("."),
           "",
           "**Do you need it?** For %s. If you didn't pick any of those, skip it." % s["needed_for"],
           "",
           "**What it costs:** %s *(Checked %s: [price page](%s).)*" % (s["cost"], checked_words(s), s["source"]),
           "",
           "**Limiting what you spend:** %s" % s["limit"], ""]
    before = list(s.get("before", []))
    before += ["An email address your business controls.", "Your phone, for security codes."]
    if s.get("spending") != "free":
        before.append("A card, if you choose a paid plan.")
    out += ["**Before you start:**", ""] + ["- %s" % b for b in before] + [""]
    out += ["**Step by step:**", ""] + ["%d. %s" % (i + 1, step) for i, step in enumerate(s["steps"])] + [""]
    if s["keys"]:
        out += [ADD_KEY % _paste(s), "", CHECK + (" " + s["key_note"] if s.get("key_note") else ""), "", WRONG, ""]
    out += ["**Removing access:** %s" % s["remove"], ""]
    return out


def markdown():
    data = load()
    table = "\n".join("| %s | %s | %s | %s |" % (s["name"], s["for"][0].upper() + s["for"][1:], s["cost"].split(". ")[0] + ".",
                                                SPENDING_WORDS.get(s["spending"], s["spending"]))
                      for s in data["services"])
    text = INTRO % {"always": "\n".join("- %s" % a for a in data["always"]), "table": table}
    lines = [text]
    for s in data["services"]:
        lines += _section(s)
    return "\n".join(lines).rstrip() + "\n"
