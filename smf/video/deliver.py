"""deliver.py - copy finished, checked versions into the brand's video inbox, with their words.

The inbox is the folder the posting tools read (`video.inbox_folder` in the brand's settings).
Each delivery goes into a folder of its own inside it, named after the recording, so clips from
two recordings can never collide or be mistaken for each other:

    <inbox>/<recording>/rye-loaf__v1.mp4             a version (two underscores, as posting expects)
    <inbox>/<recording>/rye-loaf__v1.tiktok.txt      its words for one platform
    <inbox>/<recording>/rye-loaf__v1.txt             its words where nothing more exact was written
    <inbox>/<recording>/delivery-manifest.json       what was delivered, when, from what, on whose say

WHAT IS NEVER DELIVERED, whatever flags are passed:
  * a clip on HOLD that nobody has signed off. The sign-off is read again at this moment, from the
    cut list, not taken from a plan that may be days old;
  * a file whose own record says it needed a disclaimer and did not get one, or a HOLD clip whose
    record says nothing about a disclaimer at all;
  * a preview. Previews live in their own folder under their own names and are never looked at here;
  * a file that is no longer the file that was made (its fingerprint is compared);
  * words that were blocked by the description check.

WHAT NEEDS A PERSON'S SAY-SO:
  * a version that has not passed the check (verify.py). A person may say they watched it
    themselves; their name goes into the manifest beside it;
  * words that are `unverified`. A person may let them through; the manifest says so.

NOTHING IS EVER OVERWRITTEN. A file that is already in the inbox is left exactly as it is. If it is
the same file, that is reported as already delivered; if it differs, it is reported and left alone.

THE MANIFEST IS WRITTEN NOW, from what is known now. A folder of bare video files says nothing
about where they came from or whether they may be posted, and working that out later from file
names is slow and sometimes wrong. Each delivery is added to the folder's manifest; earlier
deliveries in it are kept.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

from smf.video import describe as D
from smf.video import gate
from smf.video import variants as V
from smf.video import verify as VF
from smf.video.common import VideoError, as_brand, locate, read_json, safe_name, write_json_atomic

MANIFEST_FILE = "delivery-manifest.json"


def inbox_for(brand, recording):
    """The folder this recording's versions are delivered into. The brand's own inbox, as the
    posting tools understand it: never a default outside the brand, never another brand's folder."""
    from smf.posting import shorts as SH
    try:
        inbox, _inside = SH.inbox_folder(brand)
    except SH.ShortsError as e:
        raise VideoError(str(e))
    return os.path.join(inbox, safe_name(recording))


def _copy_new(source, target):
    """Copy `source` to `target` only if nothing is there. Returns "delivered", "already" or "different".
    The copy is made under a working name and renamed, so a stopped copy never leaves half a file
    under a real name."""
    if os.path.exists(target):
        same = os.path.getsize(target) == os.path.getsize(source) and V.sha256_of(target) == V.sha256_of(source)
        return "already" if same else "different"
    fd, working = tempfile.mkstemp(prefix=".arriving-", suffix=".part", dir=os.path.dirname(target))
    os.close(fd)
    try:
        shutil.copyfile(source, working)
        if os.path.exists(target):                                  # someone else got there first: theirs stays
            return "different"
        os.rename(working, target)
    finally:
        if os.path.exists(working):
            os.remove(working)
    return "delivered"


def _write_new(text, target):
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8-sig", errors="replace") as f:
            return "already" if f.read().strip() == text.strip() else "different"
    fd, working = tempfile.mkstemp(prefix=".arriving-", suffix=".part", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.strip() + "\n")
        if os.path.exists(target):
            return "different"
        os.rename(working, target)
    finally:
        if os.path.exists(working):
            os.remove(working)
    return "delivered"


def deliver(brand, recording, clip_ids=None, versions=None, watched_by="", allow_unverified_words=False,
            dry_run=False, say=None):
    """Deliver the finished versions of a recording. Returns this delivery's record.

    watched_by               a person's name. It lets through versions that have not passed the
                             check, on that person's word, and is written beside each of them. It
                             does NOT let through an unsigned HOLD clip or a missing disclaimer.
    allow_unverified_words   let `unverified` descriptions be written. `blocked` ones never are.
    dry_run                  say what would happen; copy and write nothing.
    """
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    manifest = V.load_manifest(brand, recording)
    report, _folder, _kind = V.load_report(brand, recording, manifest.get("made_from") or "auto")
    made = {(e["clip"], e["version"]): e for e in V.load_log(brand, recording) if not e.get("preview")}
    checked = VF.passed(brand, recording)
    words = D.verdicts(brand, recording)
    dest = inbox_for(brand, recording)
    wanted = {c.upper() for c in clip_ids} if clip_ids else None
    known = {c["id"].upper() for c in manifest["clips"]}
    if wanted is not None and wanted - known:
        raise VideoError("The plan has no clip called %s. It has: %s." % (", ".join(sorted(wanted - known)),
                                                                        ", ".join(sorted(known))))
    only_versions = {v.lower() for v in versions} if versions else None
    watched_by = " ".join((watched_by or "").split())

    record = {"delivered_at": time.strftime("%Y-%m-%d %H:%M:%S"), "brand": brand.id, "recording": recording,
              "made_from": manifest.get("made_from"), "to": locate(brand, dest), "dry_run": bool(dry_run),
              "watched_by": watched_by,
              "videos": [], "words": [], "refused": []}

    def refuse(clip, version, why):
        record["refused"].append({"clip": clip, "version": version, "why": why})
        say("NOT delivered  %s %s: %s" % (clip, version, why))

    for clip in manifest["clips"]:
        if wanted is not None and clip["id"].upper() not in wanted:
            continue
        signed = V.current_sign_off(brand, recording, report, clip["report_entry"])
        for v in clip["versions"]:
            if only_versions is not None and v["version"].lower() not in only_versions:
                continue
            cid, ver = clip["id"], v["version"]
            entry = made.get((cid, ver))
            if clip["gate"] not in ("SHIP", gate.HOLD):
                refuse(cid, ver, "its gate is '%s', which is not one that may be posted" % clip["gate"])
                continue
            if clip["gate"] == gate.HOLD and not signed:
                who = clip.get("sign_off_by") or "the person named in the brand's settings"
                refuse(cid, ver, "it is on HOLD and %s has not signed it off. Write their sign-off into the cut list "
                                 "once they have watched it" % who)
                continue
            if not entry or entry.get("status") != "ok":
                refuse(cid, ver, "it has not been made yet" if not entry
                       else "making it failed: %s" % entry.get("why", "unknown"))
                continue
            band = entry.get("disclaimer") or {}
            if clip["gate"] == gate.HOLD and not band.get("required"):
                refuse(cid, ver, "it is on HOLD but was made without being treated as a clip that needs its disclaimer. "
                                 "Plan and make it again")
                continue
            if band.get("required") and not band.get("present"):
                refuse(cid, ver, "its own record says it needed the disclaimer on screen and did not get it")
                continue
            source = brand.path(*entry["file"].split("/"))
            if not os.path.isfile(source):
                refuse(cid, ver, "the file is not where the record says it is")
                continue
            fingerprint = V.sha256_of(source)
            if fingerprint != entry.get("sha256"):
                refuse(cid, ver, "the file has changed since it was made. Make it again")
                continue
            if checked.get((cid, ver)) == fingerprint:
                basis = "passed the check"
            elif watched_by:
                basis = "%s said they watched it" % watched_by
            else:
                refuse(cid, ver, "it has not passed the check. Run the check, or have a person watch it and say who did")
                continue

            name = os.path.basename(source)
            target = os.path.join(dest, name)
            if dry_run:
                outcome = "already" if os.path.exists(target) else "would be delivered"
            else:
                os.makedirs(dest, exist_ok=True)
                outcome = _copy_new(source, target)
            record["videos"].append({
                "clip": cid, "version": ver, "file": name, "outcome": outcome, "sha256": fingerprint,
                "from": entry["file"], "source_clip": clip["source"]["file"], "recipe": entry["recipe"]["id"],
                "gate": clip["gate"], "signed_off": signed, "disclaimer_on_screen": bool(band.get("present")),
                "disclaimer": band.get("text", ""), "on_screen_text": clip["on_screen_text"],
                "seconds": entry.get("duration"), "cleared": basis})
            say("%-18s %s" % (outcome, name))
            if outcome == "different":
                say("  A different file with that name is already in the inbox. It was left exactly as it is.")
                continue

            stem = os.path.splitext(name)[0]
            for (w_clip, w_ver, platform), verdict in sorted(words.items()):
                if (w_clip, w_ver) != (cid, ver):
                    continue
                txt = "%s%s.txt" % (stem, "." + platform if platform else "")
                row = {"clip": cid, "version": ver, "platform": platform, "file": txt, "sourcing": verdict["sourcing"]}
                if verdict["sourcing"] == "blocked":
                    row["outcome"] = "not written: " + "; ".join(verdict["problems"][:2])
                elif verdict["sourcing"] == "unverified" and not allow_unverified_words:
                    row["outcome"] = "not written: it is unverified (%s). Fix it, or let it through on purpose" \
                                     % "; ".join(verdict["unverified"][:1])
                elif dry_run:
                    row["outcome"] = "would be written"
                else:
                    row["outcome"] = _write_new(verdict["text"], os.path.join(dest, txt))
                    if verdict["sourcing"] == "unverified":
                        row["let_through_by_a_person"] = True
                record["words"].append(row)
            usable = ("delivered", "already", "would be written")
            if not any(w["clip"] == cid and w["version"] == ver and w["outcome"] in usable for w in record["words"]):
                say("  %s has no usable words yet. The posting tools leave out a video with no words." % name)

    if not record["videos"] and not record["refused"]:
        raise VideoError("Nothing matched what was asked for, so nothing was delivered.")
    if not dry_run and record["videos"]:
        path = os.path.join(dest, MANIFEST_FILE)
        history = []
        if os.path.isfile(path):
            try:
                history = list(read_json(path, "The delivery manifest").get("deliveries", []))
            except VideoError:
                shutil.copyfile(path, path + ".unreadable-%s" % time.strftime("%Y%m%d-%H%M%S"))     # keep it; never discard
        write_json_atomic(path, {"schema": 1, "brand": brand.id, "recording": recording, "deliveries": history + [record]})
        write_json_atomic(V.variants_dir(brand, recording, "deliveries.json"),
                          {"schema": 1, "brand": brand.id, "recording": recording,
                           "deliveries": _earlier(brand, recording) + [record]})
    return record


def _earlier(brand, recording):
    path = V.variants_dir(brand, recording, "deliveries.json")
    if not os.path.isfile(path):
        return []
    try:
        return list(read_json(path, "The record of earlier deliveries").get("deliveries", []))
    except VideoError:
        return []
