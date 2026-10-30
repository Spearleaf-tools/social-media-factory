"""status.py - what is ready, what is not, and the next step. Strictly read-only and offline.

Reads smf/features.json (the same table the /start menu and the guide use) and works out a
state for every feature. It never shows a key value, only which key and where it came from.
"""
from __future__ import annotations

import json
import os

from smf import bootstrap, brands, keys
from smf.checks import CHECKS

HERE = os.path.dirname(os.path.abspath(__file__))
# The made-up bakery ships with every copy so demos and tests have something to work on. It is an
# example, not the person's brand: on its own it never makes a feature "ready".
EXAMPLE_BRANDS = ("maple-and-main",)
ONBOARD_NEXT = "onboard your brand (say \"onboard my brand\")"


def load_features():
    with open(os.path.join(HERE, "features.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate(feature, state, have_brand):
    """Returns (state_name, reason, next_step)."""
    if not feature.get("built", False):
        return "not built yet", "", ""
    needs = feature.get("needs", {})
    for tier in needs.get("tiers", []):
        if tier not in state.get("tiers", {}):
            cmd = "python factory.py setup" + ("" if tier == "core" else " --tier " + tier)
            return "needs setup", "the %s packages are not installed" % tier, cmd
    for name in needs.get("checks", []):
        ok, why = CHECKS[name]()
        if not ok:
            return "needs setup", why, ""
    missing = [k for k in needs.get("keys", []) if not keys.has(k)]
    if missing:
        what = keys.KNOWN_KEYS.get(missing[0], missing[0])
        return "needs input", "missing key for %s: %s" % (what, ", ".join(missing)), "add it to the keys file"
    any_key = needs.get("any_key", [])
    if any_key and not any(keys.has(k) for k in any_key):
        return "needs input", "needs one of: %s" % ", ".join(any_key), "add it to the keys file"
    if needs.get("brand") and not have_brand:
        return "needs input", "no brand of yours has been onboarded yet (the bakery is only an example)", ONBOARD_NEXT
    if needs.get("keys") or any_key:
        from smf import verify_keys
        # A result only counts for the key that was checked: a replaced key is unverified again.
        results = {k: verify_keys.checked(k, state) for k in needs.get("keys", [])}
        unverified = [k for k, rec in results.items() if rec is None]
        if unverified:
            return "unverified", "key present but not checked online yet", "python factory.py status --verify"
        bad = [k for k, rec in results.items() if rec.get("ok") is False]
        if bad:
            return "blocked", results[bad[0]].get("reason") or "the service refused the key", ""
    # keys that unlock only part of a feature: it is ready without them, and the row says what they add
    without = [(k, what) for k, what in (needs.get("optional_keys") or {}).items() if not keys.has(k)]
    if without:
        return "ready", "; ".join("add %s for %s" % (k, what) for k, what in without), ""
    return "ready", "", ""


USAGE = """
python factory.py status             what is ready, what is not, and the next step
python factory.py status --verify    also ask each service whether its key works (uses the internet; never shows a key)
python factory.py status --json      the same as JSON
"""


def main(args):
    opts, _words, rc = bootstrap.read_options(args, "status", USAGE, flags=("--json", "--verify"))
    if rc is not None:
        return rc
    as_json = bool(opts.get("--json"))
    if opts.get("--verify"):
        from smf import verify_keys
        results = verify_keys.verify()
        if not as_json:
            if not results:
                print("There are no keys to check yet. Writing, visuals, review and the ready-to-post folder "
                      "need none.\n")
            for r in results:
                print("%s: %s" % (r["service"], "working (%s)" % r["reason"] if r["ok"] else "NOT working. " + r["reason"]))
            if results:
                print("")
    data = load_features()
    state = bootstrap.load_state()
    found = brands.list_brands()
    own = [b for b in found if b not in EXAMPLE_BRANDS]
    keys.load()

    rows = []
    for feat in data["features"]:
        st, why, nxt = evaluate(feat, state, bool(own))
        rows.append({"id": feat["id"], "section": feat["section"], "name": feat["name"],
                     "state": st, "reason": why, "next": nxt})

    report = {
        "installed": {"python": bool(bootstrap.env_python()), "tiers": sorted(state.get("tiers", {})),
                      "renderer": bool(state.get("renderer")), "titles": bool(bootstrap.title_programs())},
        "brands": found,
        "example_brands": [b for b in found if b in EXAMPLE_BRANDS],
        "keys": {k: (keys.source(k) or "missing") for k in keys.KNOWN_KEYS},
        "keys_file_problems": keys.problems(),
        "features": rows,
    }
    if as_json:
        print(json.dumps(report, indent=2))
        return 0

    print("SOCIAL MEDIA FACTORY - status\n")
    inst = report["installed"]
    if not inst["python"]:
        print("This computer is not set up yet. Next step: python factory.py setup\n")
    else:
        print("Installed: %s%s%s" % (", ".join(inst["tiers"]) or "nothing yet",
                                     "" if inst["renderer"] else "  (page renderer missing)",
                                     "  (title renderer missing)" if "video" in inst["tiers"] and not inst["titles"] else ""))
    shown = ["%s (the made-up example)" % b if b in EXAMPLE_BRANDS else b for b in found]
    print("Brands:    %s" % (", ".join(shown) if found else "none yet"))
    print("Keys:")
    for k, v in report["keys"].items():
        print("   %-24s %s" % (k, v))
    for p in report["keys_file_problems"]:
        print("   note: " + p)
    names = {s["id"]: s["name"] for s in data["sections"]}
    current = None
    for r in rows:
        if r["section"] != current:
            current = r["section"]
            print("\n%s" % names.get(current, current).upper())
        line = "  [%s] %s" % (r["state"], r["name"])
        if r["reason"]:
            line += "  - " + r["reason"]
        if r["next"]:
            line += "  -> " + r["next"]
        print(line)
    return 0
