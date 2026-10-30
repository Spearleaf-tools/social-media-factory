"""manifest.py - the record of one batch of scripts: what was pitched, what a person approved,
what has been written and checked, and what has been filmed.

    Client/<brand>/Studio/scripts/<batch>/manifest.json

A script moves forward one step at a time:

    pitched -> approved -> draft -> validated -> recorded          (and `cut` for a pitch that was turned down)

    pitched     an idea on the pitch sheet. Nothing is written until a person says yes.
    approved    a person said yes to the pitch. A starter script file is waiting to be filled in.
    draft       the script has been written, and the checker still finds something to fix
                (or the script changed after it last passed).
    validated   the script passes every check, exactly as it stands now.
    recorded    it has been filmed.

Three behaviours matter more than the rest:

  * Several writers may finish at the same moment. Every change is read, changed and written
    back while holding a lock file, and the write itself is atomic. The lock is a file that must
    not already exist, which behaves the same on Windows, Mac and Linux.
  * A manifest that cannot be read STOPS the work. It is never treated as an empty batch,
    because an empty batch says "nothing has been pitched or filmed yet" and the next step would
    happily pitch the same subjects again or write over finished scripts.
  * A batch belongs to one brand. A manifest that names another brand is refused.
"""
from __future__ import annotations

import os
import time

from smf.scripts import ScriptsError
from smf.scripts import paths as P
from smf.studio.files import StudioError, as_brand, read_json, write_json

STEPS = ("pitched", "approved", "draft", "validated", "recorded")
CUT = "cut"
STATUSES = STEPS + (CUT,)
TRACKS = ("topics", "recording")

# From each status, where a script may go next. Forward one step at a time; `draft` and
# `validated` are only ever set by the checker, never by hand.
_MOVES = {
    "pitched": ("approved", CUT),
    "approved": ("draft", "validated", "pitched", CUT),
    "draft": ("validated", "draft"),
    "validated": ("recorded", "draft", "validated"),
    "recorded": ("validated",),
    CUT: ("pitched",),
}
_SET_BY_THE_CHECKER = ("draft", "validated")

LOCK_NAME = "manifest.lock"
LOCK_WAIT_SECONDS = 20
LOCK_STALE_SECONDS = 120          # a change takes milliseconds; a lock this old was left by a crash


class ManifestError(ScriptsError):
    """The batch record cannot be used as it stands."""


class ManifestBusy(ManifestError):
    """Someone else is changing this batch right now."""


# ----------------------------------------------------------------------------- the lock
class Lock(object):
    """Hold this while reading, changing and writing a manifest.

    Creating a file with "fail if it already exists" is atomic on every operating system, so
    whoever creates the lock file owns the batch until they remove it. A lock file older than
    LOCK_STALE_SECONDS was left behind by something that crashed, and is taken over."""

    def __init__(self, folder, wait_seconds=LOCK_WAIT_SECONDS):
        self.path = os.path.join(folder, LOCK_NAME)
        self.wait = wait_seconds
        self.fd = None

    def __enter__(self):
        deadline = time.time() + self.wait
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, ("%d %f" % (os.getpid(), time.time())).encode("ascii"))
                return self
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    continue                                    # it was released between the two calls
                if age > LOCK_STALE_SECONDS:
                    try:
                        os.unlink(self.path)
                    except OSError:
                        pass
                    continue
                if time.time() > deadline:
                    raise ManifestBusy("Another task is updating this batch of scripts right now. Wait a moment "
                                       "and run the same command again. Nothing was changed.")
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            os.unlink(self.path)
        except OSError:
            pass


# ----------------------------------------------------------------------------- reading
def _what(brand, batch):
    return "The record of %s's script batch '%s'" % (brand.name, batch)


def _check_shape(data, brand, batch):
    what = _what(brand, batch)
    if not isinstance(data, dict) or not isinstance(data.get("scripts"), list):
        raise ManifestError("%s is not in the expected shape, so nothing was read from it and nothing was "
                            "changed. Ask Claude to repair it." % what)
    if data.get("brand") != brand.id:
        raise ManifestError("This batch of scripts belongs to '%s', not to %s. Nothing was loaded."
                            % (data.get("brand"), brand.id))
    if data.get("batch") != batch:
        raise ManifestError("The folder is called '%s' but its record says the batch is '%s'. They must match. "
                            "Nothing was changed." % (batch, data.get("batch")))
    seen = set()
    for s in data["scripts"]:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not s["id"].strip():
            raise ManifestError("%s holds an entry with no id. Nothing was changed. Ask Claude to repair it." % what)
        if s["id"] in seen:
            raise ManifestError("%s holds two scripts with the id '%s'. Nothing was changed." % (what, s["id"]))
        seen.add(s["id"])
        if s.get("status") not in STATUSES:
            raise ManifestError("%s gives script %s the status '%s'. A script is one of: %s."
                                % (what, s["id"], s.get("status"), ", ".join(STATUSES)))
    return data


def exists(brand, batch):
    return os.path.isfile(P.manifest_path(as_brand(brand), batch))


def load(brand, batch):
    """The batch record, or a ManifestError. A missing or damaged record is an error, never an
    empty batch."""
    brand = as_brand(brand)
    path = P.manifest_path(brand, batch)
    if not os.path.isfile(path):
        have = P.list_batches(brand)
        raise ManifestError("%s has no batch of scripts called '%s'. It has: %s."
                            % (brand.name, batch, ", ".join(have) or "none yet"))
    try:
        data = read_json(path, _what(brand, batch))
    except ManifestError:
        raise
    except StudioError as e:
        raise ManifestError("%s Work on this batch is stopped so nothing is pitched twice or written over."
                            % str(e))
    return _check_shape(data, brand, batch)


def update(brand, batch, change, wait_seconds=LOCK_WAIT_SECONDS):
    """Read, change and write the record while holding the lock. `change(data)` edits the dict in
    place; whatever it returns is returned. If it raises, nothing is written."""
    brand = as_brand(brand)
    folder = P.batch_dir(brand, batch)
    if not os.path.isdir(folder):
        load(brand, batch)                                      # raises the plain "no such batch"
    with Lock(folder, wait_seconds):
        data = load(brand, batch)
        result = change(data)
        _check_shape(data, brand, batch)
        write_json(P.manifest_path(brand, batch), data)
        return result


def find(data, script_id):
    wanted = normalise_id(script_id)
    for s in data["scripts"]:
        if s["id"] == wanted:
            return s
    raise ManifestError("The batch '%s' has no script with the id '%s'. It has: %s."
                        % (data.get("batch"), script_id, ", ".join(s["id"] for s in data["scripts"]) or "none yet"))


def normalise_id(script_id):
    """'3', 3 and '03' all name the same script."""
    text = str(script_id).strip()
    return "%02d" % int(text) if text.isdigit() else text


# ----------------------------------------------------------------------------- a new batch
def create_batch(brand, batch, track="topics", source="", note=""):
    """Start an empty batch. Refuses to touch a batch that already exists."""
    brand = as_brand(brand)
    P.check_batch_name(batch)
    if track not in TRACKS:
        raise ManifestError("A batch is made from one of: %s." % ", ".join(TRACKS))
    folder = P.batch_dir(brand, batch)
    os.makedirs(folder, exist_ok=True)
    with Lock(folder):
        path = P.manifest_path(brand, batch)
        if os.path.exists(path):
            raise ManifestError("%s already has a batch of scripts called '%s'. Nothing was changed. "
                                "Choose another name, or carry on with that batch." % (brand.name, batch))
        data = {"brand": brand.id, "batch": batch, "created": time.strftime("%Y-%m-%d"), "track": track,
                "source": str(source or ""), "note": str(note or ""), "scripts": []}
        write_json(path, data)
    return data


# ----------------------------------------------------------------------------- what has been made before
def already_made(brand, except_batch=None):
    """Every subject this brand has pitched or made in ANY batch: {key: "batch/id title"}.
    Keys are the topic id, the recording body and the title slug. A pitch that was cut does not
    count. A damaged record in any batch stops this, because skipping it would report its
    subjects as new."""
    brand = as_brand(brand)
    out = {}
    for name in P.list_batches(brand):
        if name == except_batch:
            continue
        for s in load(brand, name)["scripts"]:
            if s.get("status") == CUT:
                continue
            label = "%s/%s %s" % (name, s["id"], s.get("title", ""))
            for key in _subject_keys(s):
                out.setdefault(key, label)
    return out


def _subject_keys(entry):
    keys = []
    if entry.get("topic_id"):
        keys.append("topic:%s" % entry["topic_id"])
    if entry.get("body"):
        keys.append("body:%s|%s" % (entry.get("source_ref", ""), entry["body"]))
    if entry.get("slug"):
        keys.append("slug:%s" % entry["slug"])
    return keys


# ----------------------------------------------------------------------------- pitches
def add_pitches(brand, batch, pitches, allow_repeat=False):
    """Record pitches at status `pitched`. One pitch per topic, or one per body of a recording's
    cut list. Ids are given out here, inside the lock, in the order the pitches arrive, so they
    come out the same however many writers start afterwards.

    Returns (added_entries, skipped) where skipped is [(title, why)]."""
    brand = as_brand(brand)
    made = {} if allow_repeat else already_made(brand, except_batch=batch)

    def change(data):
        added, skipped = [], []
        taken = {}
        for s in data["scripts"]:
            if s.get("status") != CUT:
                for key in _subject_keys(s):
                    taken[key] = "this batch, script %s" % s["id"]
        numbers = [int(s["id"]) for s in data["scripts"] if s["id"].isdigit()]
        next_number = (max(numbers) + 1) if numbers else 1
        for p in pitches:
            entry = _pitch_entry(brand, data, p)
            clash = next((taken.get(k) or made.get(k) for k in _subject_keys(entry) if k in taken or k in made), None)
            if clash:
                skipped.append((entry["title"], "already covered in %s" % clash))
                continue
            entry["id"] = "%02d" % next_number
            next_number += 1
            entry["script_file"] = "%s-%s.md" % (entry["id"], entry["slug"])
            entry["teleprompter_file"] = "%s-%s%s" % (entry["id"], entry["slug"], P.TELEPROMPTER_SUFFIX)
            for key in _subject_keys(entry):
                taken[key] = "this batch, script %s" % entry["id"]
            data["scripts"].append(entry)
            added.append(entry)
        return added, skipped

    return update(brand, batch, change)


def _pitch_entry(brand, data, pitch):
    from smf.scripts.brief import normalise_job
    from smf.studio import topics

    if not isinstance(pitch, dict) or not str(pitch.get("title") or "").strip():
        raise ManifestError("A pitch needs a title: the subject in a few words. Nothing was saved.")
    title = str(pitch["title"]).strip()
    job = normalise_job(pitch.get("job"))
    if job is None:
        raise ManifestError("The pitch '%s' needs a job: reach, leads or trust. The job decides how the video "
                            "ends and how it is judged later. Nothing was saved." % title)
    speaker = str(pitch.get("speaker") or pitch.get("identity") or "").strip()
    brand.identity(speaker)                                  # unknown speaker is an error, never a guess
    source_ref = str(pitch.get("source_ref") or "").strip()
    if not source_ref:
        raise ManifestError("The pitch '%s' does not say where in %s's own material it comes from. Every pitch "
                            "needs a source, so a script is never written from thin air. Nothing was saved."
                            % (title, brand.name))
    found = topics.resolve_source_ref(brand, source_ref)
    if not found["ok"]:
        raise ManifestError("The pitch '%s' points to '%s', but %s. Nothing was saved."
                            % (title, source_ref, found["detail"]))
    track = data.get("track")
    topic_id, body = str(pitch.get("topic_id") or "").strip(), str(pitch.get("body") or "").strip()
    if track == "recording" and not body:
        raise ManifestError("This batch is made from a recording, so the pitch '%s' must say which body of the "
                            "cut list it comes from ('body'). One pitch per body. Nothing was saved." % title)
    try:
        length = int(pitch.get("length") or 45)
    except (TypeError, ValueError):
        raise ManifestError("The pitch '%s' has a length that is not a number of seconds." % title)
    return {"id": "", "slug": P.slugify(pitch.get("slug") or title), "title": title, "status": "pitched",
            "job": job, "speaker": speaker, "pillar": str(pitch.get("pillar") or ""),
            "topic_id": topic_id, "body": body, "source_ref": source_ref,
            "source_is_checkable": found["kind"] != "note",
            "hook": str(pitch.get("hook") or "").strip(), "angle": str(pitch.get("angle") or "").strip(),
            "hook_pattern": str(pitch.get("hook_pattern") or "").strip(),
            "length": length, "script_file": "", "teleprompter_file": "",
            "pitched_at": _now(), "approved_at": "", "checked_at": "", "checked_sha": "", "sourcing": "unverified",
            "open_findings": 0, "needs_sign_off": False, "teleprompter": {}, "recorded_at": "", "numbers": {}}


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------- moving a script on
def _move(entry, status, by_checker=False):
    now = entry["status"]
    if status not in STATUSES:
        raise ManifestError("A script is one of: %s." % ", ".join(STATUSES))
    if status in _SET_BY_THE_CHECKER and not by_checker:
        raise ManifestError("Only the checker marks a script '%s'. Run the check on script %s instead."
                            % (status, entry["id"]))
    if status not in _MOVES[now]:
        raise ManifestError(_why_not(entry, status))
    entry["status"] = status


def _why_not(entry, status):
    now, sid = entry["status"], entry["id"]
    if now == "pitched" and status != "approved":
        return ("Script %s is still only a pitch. A person has to approve the pitch before anything is "
                "written, checked or filmed." % sid)
    if status == "recorded":
        return ("Script %s cannot be marked as filmed yet: it is '%s', and only a script that passes every "
                "check is filmed." % (sid, now))
    if now == CUT:
        return "Script %s was cut from this batch. Put it back on the pitch sheet first." % sid
    return "Script %s is '%s', so it cannot go straight to '%s'. The steps are: %s." % (sid, now, status, " -> ".join(STEPS))


def set_status(brand, batch, script_ids, status):
    """Move one or more scripts to a status a PERSON decides: approved, cut, pitched, recorded."""
    def change(data):
        moved = []
        for sid in script_ids:
            entry = find(data, sid)
            _move(entry, status)
            if status == "approved":
                entry["approved_at"] = _now()
            if status == "recorded":
                entry["recorded_at"] = _now()
            moved.append(entry)
        return moved
    return update(brand, batch, change)


def record_check(brand, batch, script_id, report, file_sha):
    """Store the result of checking one script, and move it to draft or validated."""
    def change(data):
        entry = find(data, script_id)
        if entry["status"] in ("pitched", CUT):
            raise ManifestError(_why_not(entry, "draft"))
        if entry["status"] != "recorded":
            _move(entry, "validated" if report["ok"] else "draft", by_checker=True)
        entry.update({"checked_at": _now(), "checked_sha": file_sha if report["ok"] else "",
                      "sourcing": report["sourcing"], "open_findings": len(report["errors"]),
                      "needs_sign_off": bool(report["needs_sign_off"]), "spoken_words": report["spoken_words"]})
        return dict(entry)
    return update(brand, batch, change)


def record_teleprompter(brand, batch, script_id, stamp):
    def change(data):
        find(data, script_id)["teleprompter"] = dict(stamp)
    return update(brand, batch, change)


def record_details(brand, batch, script_id, details):
    """Details read from the finished script (its format, hook pattern, call to action), kept so
    the audit can compare scripts without opening every file."""
    def change(data):
        find(data, script_id).update({k: v for k, v in details.items() if v not in (None, "")})
    return update(brand, batch, change)


def record_numbers(brand, batch, numbers_by_id):
    """Store a person's published numbers against their scripts. Only numbers are kept."""
    def change(data):
        stored = []
        for sid, numbers in numbers_by_id.items():
            entry = find(data, sid)
            clean = {k: v for k, v in numbers.items()
                     if isinstance(v, (int, float)) and not isinstance(v, bool)}
            if clean:
                entry.setdefault("numbers", {}).update(clean)
                stored.append(entry["id"])
        return stored
    return update(brand, batch, change)


def demote_changed(brand, batch, current_shas):
    """A script that changed after it passed is a draft again. `current_shas` is {id: sha of the
    file as it is now}. Returns the ids that went back to draft."""
    def change(data):
        back = []
        for entry in data["scripts"]:
            now = current_shas.get(entry["id"])
            if entry["status"] == "validated" and now is not None and now != entry.get("checked_sha"):
                _move(entry, "draft", by_checker=True)
                entry["checked_sha"] = ""
                back.append(entry["id"])
        return back
    return update(brand, batch, change)
