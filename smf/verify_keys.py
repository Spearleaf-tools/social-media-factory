"""verify_keys.py - check each key with ONE harmless read, and say what is wrong in plain words.

    python factory.py status --verify

Every check here is a read: "who am I" style calls that cost nothing and change nothing. They go
through the same transport as posting with writes switched OFF, so a mistake in this file cannot
send, upload or schedule anything. Results are remembered in .factory/state.json as ok / not ok
plus a reason. No key, and nothing derived from a key, is ever written to disk or printed.
"""
from __future__ import annotations

import os
import time

from smf import bootstrap, keys
from smf.posting.provider import ProviderError, Transport


def _metricool(transport):
    from smf.posting.metricool import Metricool
    accounts = Metricool(transport).list_accounts()
    if not accounts:
        return False, ("The key works, but this Metricool account has no brands yet. Add a brand in Metricool and "
                       "connect its social accounts there.")
    connected = sum(1 for a in accounts if a.get("networks"))
    return True, "%d brand(s) found, %d with social accounts connected" % (len(accounts), connected)


def _elevenlabs(transport):
    transport.request("GET", "https://api.elevenlabs.io/v1/user",
                      headers={"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", ""), "Accept": "application/json"})
    return True, "the key is accepted"


def _apify(transport):
    transport.request("GET", "https://api.apify.com/v2/users/me",
                      headers={"Authorization": "Bearer " + os.environ.get("APIFY_API_TOKEN", ""),
                               "Accept": "application/json"})
    return True, "the token is accepted"


SERVICES = [
    ("Metricool", ["METRICOOL_USER_TOKEN", "METRICOOL_USER_ID"], _metricool),
    ("ElevenLabs", ["ELEVENLABS_API_KEY"], _elevenlabs),
    ("Apify", ["APIFY_API_TOKEN"], _apify),
]

PLAIN = {
    "unauthorized": "The service refused the key. Check it was pasted whole, with no spaces, and has not been deleted there.",
    "no-api-access": None,                 # Metricool's own message already explains the plan requirement
    "network": "The service could not be reached. Check the internet connection and try again.",
    "server": "The service had a problem of its own. Try again in a few minutes.",
    "rejected": "The service did not accept the request. The key may be for a different kind of account.",
}


def verify(transport=None):
    """Check every service whose key values are all present. Returns [{service, ok, reason}]."""
    keys.load()
    transport = transport or Transport(allow_writes=False, timeout=30)
    state = bootstrap.load_state()
    verified = dict(state.get("verified_keys", {}))
    report = []
    for name, names, check in SERVICES:
        have = [k for k in names if keys.has(k)]
        if not have:
            for k in names:
                verified.pop(k, None)
            continue
        if len(have) < len(names):
            missing = [k for k in names if k not in have]
            ok, reason = False, "%s also needs %s in the keys file." % (name, " and ".join(missing))
        else:
            try:
                ok, reason = check(transport)
            except ProviderError as e:
                ok, reason = False, PLAIN.get(e.kind) or keys.redact(str(e))
            except Exception as e:                      # never let a surprise print a key or a stack trace
                ok, reason = False, "The check could not be finished (%s)." % type(e).__name__
        for k in names:
            if keys.has(k):
                verified[k] = _result(k, ok, reason)
        report.append({"service": name, "ok": bool(ok), "reason": keys.redact(reason)})
    state = bootstrap.load_state()
    state["verified_keys"] = verified
    bootstrap.save_state(state)
    return report


def _result(key_name, ok, reason):
    """What is remembered about one key: ok or not, why, when, and a fingerprint of the key that was
    checked (keys.fingerprint), never the key."""
    return {"ok": bool(ok), "reason": "" if ok else keys.redact(reason),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"), "fp": keys.fingerprint(key_name)}


def record(key_names, ok, reason=""):
    """Remember the result of really using a key (the onboarding page's voice, today), the same way
    `status --verify` does, so a key that has worked no longer shows as unverified."""
    keys.load()
    state = bootstrap.load_state()
    verified = dict(state.get("verified_keys", {}))
    for k in key_names:
        if keys.has(k):
            verified[k] = _result(k, ok, reason)
    state["verified_keys"] = verified
    bootstrap.save_state(state)


def checked(key_name, state=None):
    """The remembered result for the key now in place, or None. A result for a different (replaced) key,
    or one saved before fingerprints existed, does not count: that key is unverified until checked again."""
    state = bootstrap.load_state() if state is None else state
    rec = (state.get("verified_keys") or {}).get(key_name)
    if not rec or not rec.get("fp") or rec.get("fp") != keys.fingerprint(key_name):
        return None
    return rec


def key_state(key_name, state=None):
    """One of: missing, unverified, verified, not_working. Status and the onboarding page both use this,
    so they can never disagree about a key."""
    if not keys.has(key_name):
        return "missing"
    rec = checked(key_name, state)
    if rec is None:
        return "unverified"
    return "verified" if rec.get("ok") else "not_working"
