"""keys.py - where keys come from, and how we talk about them without ever showing one.

Order of precedence (first one that has a value wins):
    1. the computer's environment      for people who already manage keys their own way
    2. keys.env in this folder         the default; a plain file, never committed
    3. Doppler                         only when FACTORY_USE_DOPPLER=1 and the doppler program exists

Honest note about safety: this project's settings ask Claude not to open keys.env. That stops
accidental reads. It is NOT a wall, because the tools themselves must read the file to work.
So the rule in this codebase is stronger than the setting: nothing here ever prints, logs or
returns a key value. Diagnostics say WHICH key, WHERE it came from, and WHAT is wrong with it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
from smf.brands import replace_patiently

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# A random secret made once per computer and kept in .factory/ (never in the repository). It lets a
# key check remember WHICH key it checked without storing the key or anything a key can be read from.
CHECK_SECRET = os.path.join(ROOT, ".factory", "key-check-secret")
KEYS_FILE = os.path.join(ROOT, "keys.env")

# name -> (what it is for, plain words)
KNOWN_KEYS = {
    "METRICOOL_USER_TOKEN": "posting and scheduling (Metricool)",
    "METRICOOL_USER_ID": "posting and scheduling (Metricool)",
    "ELEVENLABS_API_KEY": "transcribing recordings for clips (ElevenLabs)",
    "APIFY_API_TOKEN": "research (Apify)",
    "OPENAI_API_KEY": "AI-made pictures (OpenAI)",
}

_sources = {}       # name -> "environment" | "keys.env" | "doppler"
_loaded = False
_problems = []      # plain-language notes about the keys file itself


def parse_env_file(path):
    """KEY=VALUE lines. '#' comments, blank lines, optional quotes, optional 'export '."""
    out, problems = {}, []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except OSError:
        return out, problems
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            problems.append("line %d of keys.env is not in NAME=value form" % n)
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not name.replace("_", "").isalnum():
            problems.append("line %d of keys.env has an odd name" % n)
            continue
        if value:
            out[name] = value
    return out, problems


def _from_doppler():
    exe = shutil.which("doppler")
    if not exe:
        _problems.append("FACTORY_USE_DOPPLER is on, but the doppler program is not installed")
        return {}
    try:
        p = subprocess.run([exe, "secrets", "download", "--no-file", "--format", "json"],
                           capture_output=True, text=True, timeout=30, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        _problems.append("Doppler did not answer")
        return {}
    if p.returncode != 0:
        _problems.append("Doppler refused (is this folder linked to a Doppler project?)")
        return {}
    try:
        data = json.loads(p.stdout)
    except ValueError:
        _problems.append("Doppler answered with something unreadable")
        return {}
    return {k: str(v) for k, v in data.items() if v}


def load(force=False):
    """Fill os.environ from keys.env (and Doppler when enabled). Returns {name: source}."""
    global _loaded
    if _loaded and not force:
        return dict(_sources)
    _sources.clear()
    del _problems[:]
    for name in list(os.environ):
        if name in KNOWN_KEYS and os.environ.get(name):
            _sources[name] = "environment"
    file_values, problems = parse_env_file(KEYS_FILE)
    _problems.extend(problems)
    for name, value in file_values.items():
        if not os.environ.get(name):
            os.environ[name] = value
            _sources[name] = "keys.env"
    if os.environ.get("FACTORY_USE_DOPPLER", "").strip() in ("1", "true", "yes"):
        for name, value in _from_doppler().items():
            if name in KNOWN_KEYS and not os.environ.get(name):
                os.environ[name] = value
                _sources[name] = "doppler"
    _loaded = True
    return dict(_sources)


def has(name):
    load()
    return bool(os.environ.get(name))


def _check_secret():
    try:
        with open(CHECK_SECRET, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if len(text) >= 32:
            return text
    except OSError:
        pass
    text = secrets.token_hex(32)
    os.makedirs(os.path.dirname(CHECK_SECRET), exist_ok=True)
    tmp = CHECK_SECRET + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    replace_patiently(tmp, CHECK_SECRET)
    return text


def fingerprint(name):
    """A short, one-way mark of the key now in place (12 characters of an HMAC with this computer's own
    secret), or None when there is no key. Replacing a key changes it, so an old check result no longer
    applies (spec rev 11, "A result belongs to the key that was checked"). Never the key itself."""
    load()
    value = os.environ.get(name, "")
    if not value:
        return None
    return hmac.new(_check_secret().encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def source(name):
    load()
    return _sources.get(name)


def problems():
    load()
    return list(_problems)


# name -> what a person would call it
SPOKEN = {
    "METRICOOL_USER_TOKEN": "Metricool key",
    "METRICOOL_USER_ID": "Metricool user id",
    "ELEVENLABS_API_KEY": "ElevenLabs key",
    "APIFY_API_TOKEN": "Apify key",
    "OPENAI_API_KEY": "OpenAI key",
}


def _fits_in_a_header(value):
    """The rule the web machinery itself applies: no control characters (a line break is the one
    people hit, by pasting a key across two lines), and every character has to fit the encoding
    headers are written in."""
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return True


def damaged(value, name=None):
    """Empty when `value` can travel in a web request. Otherwise ONE fixed sentence saying which key
    is damaged and how to mend it, and never the value. A key pasted with a line break, or with an
    invisible character picked up from a web page, makes Python's own error quote the whole key
    back, so this is asked BEFORE a request is built.

    `value` is the key alone or a header built around it ("Bearer <key>"). `name` is the key's name
    when the caller knows it; otherwise it is recognised from the loaded keys."""
    load()
    value = str(value or "")
    if _fits_in_a_header(value):
        return ""
    if name is None:
        name = next((n for n in KNOWN_KEYS
                     if len(os.environ.get(n) or "") >= 6 and os.environ[n] in value), None)
    what = "The %s" % SPOKEN[name] if name in SPOKEN else "A key"
    fault = "has a line break or a stray character in it"
    where = source(name) if name else None
    if where == "environment":
        return ("%s on this computer %s. It was set outside the keys file, so set it again there as one line "
                "with nothing extra, and try again." % (what, fault))
    if where == "doppler":
        return "%s in Doppler %s. Save it again there as one line with nothing extra, and try again." % (what, fault)
    return ("%s in your keys file %s. Open the keys file, paste the key again on one line, save, and try again."
            % (what, fault))


def redact(text):
    """Remove every loaded key value from a piece of text before it is shown or logged. Whole
    values are replaced, so redact FIRST and shorten afterwards: a text cut through the middle of
    a key leaves a piece of it that no longer matches."""
    load()
    text = str(text)
    for name in KNOWN_KEYS:
        value = os.environ.get(name)
        if value and len(value) >= 6:
            text = text.replace(value, "[%s hidden]" % name)
    return text
