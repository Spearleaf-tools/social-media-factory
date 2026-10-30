"""secrets_check.py - a safety net that deletes anything typed on the page that looks like a key.

The real protection is that the page never asks for a key or a password. This is the net under it:
every typed answer passes through `looks_secret` before it is shown back or written to any file, and
a hit means the whole answer is thrown away, never saved, never echoed. It is a net, not a
guarantee, so it leans towards catching too much: a person can always retype an answer, but a key
written into a file has to be replaced.
"""
from __future__ import annotations

import math
import re

# Shapes that real keys and tokens start with. Matched anywhere in the answer.
KNOWN_PREFIXES = re.compile(
    r"(?:\bsk[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9]{12,}"   # OpenAI, Anthropic, Stripe
    r"|\bsk-[a-z]+-[a-z]*\d*-?[A-Za-z0-9_-]{20,}"               # sk-ant-api03-…, sk-svcacct-…: a word part, then the key
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"                            # Slack
    r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"                             # Amazon (long-term and temporary)
    r"|\bAIza[0-9A-Za-z_-]{30,}"                                  # Google
    r"|\bapify_api_[A-Za-z0-9]{10,}"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]{16,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")

# "my password is ...", "the password for payroll is ...", "pw: ...", "API token: ..."
SAID_SECRET = re.compile(
    r"\b(?:pass\s*word|passwd|pass\s*code|pin\s*(?:code|number)|pw|api[\s_-]*(?:key|token)|secret[\s_-]*key"
    r"|access[\s_-]*token|auth[\s_-]*token)\b(?:\s+[\w'-]+){0,4}?\s*(?:is|was|=|:)\s*\S+",
    re.IGNORECASE)
TOKEN_LINE = re.compile(r"\btoken\s*[:=]\s*\S{8,}", re.IGNORECASE)
WHOLE_WEB_ADDRESS = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)

# One unbroken run of letters, digits and key punctuation, long enough to be a key.
LONG_RUN = re.compile(r"[A-Za-z0-9_\-+/=.]{24,}")
WEB_ADDRESS = re.compile(r"^(?:https?://|www\.)|\.(?:com|org|net|io|co|uk|us|shop|store|app)(?:/|$)", re.IGNORECASE)

MESSAGE = "That looked like a password or key. I've deleted it. Keys go in your keys file, never here."


def _entropy(s):
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def _random_looking(run):
    if WEB_ADDRESS.search(run):
        return False                                   # a long web address is not a key
    # Real keys carry digits; a long CamelCase word ("CustomerRelationshipManagement") does not.
    return bool(re.search(r"[0-9]", run)) and bool(re.search(r"[A-Za-z]", run)) and _entropy(run) >= 3.5


def looks_secret(text):
    """True when `text` holds something that looks like a key, a token or a stated password."""
    if not isinstance(text, str) or not text:
        return False
    if KNOWN_PREFIXES.search(text) or SAID_SECRET.search(text) or TOKEN_LINE.search(text):
        return True
    rest = WHOLE_WEB_ADDRESS.sub(" ", text)          # web addresses were checked above for key shapes only
    return any(_random_looking(m.group(0)) for m in LONG_RUN.finditer(rest))


def any_secret(value):
    """looks_secret over every string inside an answer (text, lists, nested groups)."""
    if isinstance(value, str):
        return looks_secret(value)
    if isinstance(value, dict):                     # names too: a key pasted as a name is still a key
        return any(any_secret(k) or any_secret(v) for k, v in value.items())
    if isinstance(value, list):
        return any(any_secret(v) for v in value)
    return False
