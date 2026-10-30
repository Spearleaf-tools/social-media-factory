"""checklist.py - the accounts and keys THIS brand needs, and nothing it does not.

Built from what the person said they want to make (brand settings: `wants`) and the one feature
table (`smf/features.json`). Written into the brand's folder as a page they can read, and
re-made whenever they turn on something new. It shows whether each key is present and where it
came from. It never shows a key.

    python factory.py checklist --brand maple-and-main
"""
from __future__ import annotations

import argparse
import time

from smf import brands, keys, status

# what the person says they want -> the features that delivers
WANTS = {
    "posts": ["write-posts", "export-folder"],
    "visuals": ["make-visuals"],
    "short-form-scripts": ["write-scripts"],
    "clips": ["make-clips", "clip-versions", "two-camera"],
    "descriptions": ["make-clips", "clip-versions"],
    "long-form-youtube": ["youtube-video"],
    "scheduling": ["schedule-posts", "daily-shorts", "check-results"],
    "research": ["research"],
}
WANT_NAMES = {
    "posts": "Written posts for your platforms", "visuals": "Carousels, cards and PDFs",
    "short-form-scripts": "Short-form video scripts", "clips": "Clips cut from your recordings",
    "descriptions": "Descriptions and captions for finished videos",
    "long-form-youtube": "Long-form YouTube videos", "scheduling": "Scheduling to your accounts",
    "research": "Research into what is working",
}


# one entry per outside service that needs a key, built from smf/services.json (the one price list)
def _services():
    from smf import services
    out = []
    for s in services.load()["services"]:
        if not s["keys"]:
            continue                                # Claude itself: no key in the keys file
        out.append({"name": s["name"], "keys": s["keys"], "for": s["for"], "cost": services.cost_line(s),
                    "signup": s["signup"], "where": s["steps"][-1], "limit": s["limit"]})
    return out


SERVICES = _services()


def needed_services(wants, features):
    wanted_features = set()
    for w in wants:
        wanted_features.update(WANTS.get(w, []))
    needed_keys = set()
    for f in features:
        if f["id"] in wanted_features:
            needed_keys.update(f.get("needs", {}).get("keys", []))
    return [s for s in SERVICES if needed_keys & set(s["keys"])]


def build(brand):
    data = status.load_features()
    wants = brand.data.get("wants") or []
    services = needed_services(wants, data["features"])
    keys.load()
    lines = ["# %s: accounts checklist" % brand.name, "",
             "Made %s from what you said you want to make. Ask Claude to \"update my checklist\" after you "
             "change your mind about anything." % time.strftime("%Y-%m-%d"), ""]
    if not wants:
        lines += ["You have not said what you want to make yet, so nothing is needed.",
                  "Writing posts, making carousels, reviewing them and saving a ready-to-post folder need no accounts at all.", ""]
    else:
        lines += ["## What you want to make", ""] + ["- %s" % WANT_NAMES.get(w, w) for w in wants] + [""]
    free = [w for w in wants if not needed_services([w], data["features"])]
    if free:
        lines += ["**No account needed for:** %s." % ", ".join(WANT_NAMES.get(w, w).lower() for w in free), ""]
    if not services:
        lines += ["## Accounts to set up", "", "None. Everything you chose works without any outside account.", ""]
    else:
        lines += ["## Accounts to set up", ""]
        for s in services:
            have = [k for k in s["keys"] if keys.has(k)]
            state = "DONE" if len(have) == len(s["keys"]) else ("PARTLY DONE" if have else "TO DO")
            lines += ["### [%s] %s" % (state, s["name"]), "",
                      "- **What it is for:** %s." % s["for"],
                      "- **What it costs:** %s" % s["cost"],
                      "- **Limiting what you spend:** %s" % s["limit"],
                      "- **Sign up:** %s (step by step: SERVICES.md, or ask Claude to \"walk me through %s\")" % (
                          s["signup"], s["name"].split(" (")[0]),
                      "- **Where the key is:** %s" % s["where"],
                      "- **Then:** ask Claude to \"open my keys file\", paste the value after the equals sign, save, "
                      "and say \"done\". Never paste a key into the chat.", ""]
            missing = [k for k in s["keys"] if k not in have]
            if have and missing:
                lines += ["  Still missing in the keys file: %s" % ", ".join(missing), ""]
    path = brand.path("accounts-checklist.md")
    brands.write_text_atomic(path, "\n".join(lines).rstrip() + "\n")
    return path, services


def main(args):
    ap = argparse.ArgumentParser(prog="factory.py checklist")
    ap.add_argument("--brand", required=True)
    a = ap.parse_args(args)
    try:
        brand = brands.load(a.brand, allow_invalid=True)
    except brands.BrandError as e:
        print(str(e))
        return 1
    path, services = build(brand)
    keys.load()
    print("Accounts checklist for %s" % brand.name)
    if not services:
        print("  Nothing to set up: what this brand wants to make needs no outside account.")
    for s in services:
        have = [k for k in s["keys"] if keys.has(k)]
        state = "done" if len(have) == len(s["keys"]) else ("partly done" if have else "to do")
        print("  [%s] %s - %s" % (state, s["name"], s["cost"]))
    print("The full page is in the brand's folder: accounts-checklist.md")
    return 0
