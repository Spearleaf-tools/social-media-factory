"""variants_cli.py - the verbs for versions of a clip and the words under them.

    variants plan      decide each clip's versions and write the plan. Makes no video
    variants render    make the versions (add --preview for clips still waiting for sign-off)
    variants verify    open every finished version and check what is in it
    variants deliver   copy checked versions, with their words, into the brand's video inbox
    variants status    where every clip stands

    describe contract  the page Claude writes one clip's descriptions from
    describe check     check every description that has been written

Every one of them needs --brand and --recording; there is no default brand. Each returns 0 when
it did its job and 1 when it could not, with a plain sentence saying why.
"""
from __future__ import annotations

import argparse

from smf import brands
from smf.studio.files import StudioError
from smf.video.common import VideoError, locate

VARIANT_ACTIONS = ("plan", "render", "verify", "deliver", "status")
DESCRIBE_ACTIONS = ("contract", "check")


def _parser(verb, action, about):
    ap = argparse.ArgumentParser(prog="factory.py %s %s" % (verb, action), description=about)
    ap.add_argument("--brand", required=True, help="which brand this is for (there is no default)")
    ap.add_argument("--recording", required=True, help="the recording's folder name inside Inputs/Recordings")
    return ap


def _action(verb, actions, args):
    if not args or args[0] not in actions:
        print("Say what to do: %s. For example: python factory.py %s %s --brand my-brand --recording \"my recording\""
              % (", ".join(actions), verb, actions[0]))
        return None
    return args[0]


def _guard(fn, args):
    try:
        return fn(args)
    except (brands.BrandError, VideoError, StudioError) as e:
        print(str(e))
        return 1
    except OSError as e:
        print("A file could not be read or written (%s). Nothing else was changed. Check that the disk has room and "
              "that the brand's folder is not open in another program." % (e.strerror or "unknown reason"))
        return 1


# ----------------------------------------------------------------------------- variants
def cli_variants(args):
    action = _action("variants", VARIANT_ACTIONS, args)
    if action is None:
        return 1
    return _guard({"plan": _plan, "render": _render, "verify": _verify, "deliver": _deliver, "status": _status}[action],
                  args[1:])


def _plan(args):
    from smf.video import variants as V
    ap = _parser("variants", "plan", "Decide each clip's versions and write the plan. Makes no video.")
    ap.add_argument("--clip", action="append", help="just this clip (for example A1); repeat for more")
    ap.add_argument("--versions", type=int, default=3, help="how many versions of each clip (1 to %d)" % V.MAX_VERSIONS)
    ap.add_argument("--seed", default="", help="any word; a different one gives a different choice of versions")
    ap.add_argument("--which", choices=("auto", "fine", "rough"), default="auto", help="which cuts to work from")
    ap.add_argument("--no-text-in-picture", action="store_true",
                    help="you are saying nothing readable is in THIS recording's picture (no sign, label, logo, screen "
                         "or clock). Mirrored versions need this and the brand's own permission")
    ap.add_argument("--centre-on", action="append", default=[], metavar="A1=0.3",
                    help="where the person is, left (0) to right (1), when the picture has to be cropped")
    a = ap.parse_args(args)
    centre = {}
    for pair in a.centre_on:
        clip, sep, where = pair.partition("=")
        try:
            centre[clip.strip()] = float(where)
        except ValueError:
            sep = ""
        if not sep:
            raise VideoError("Write it like --centre-on A1=0.3 (0 is the far left of the picture, 1 the far right).")
    brand = brands.load(a.brand)
    m = V.plan_variants(brand, a.recording, clip_ids=a.clip, n=a.versions, seed=a.seed,
                        no_text_in_footage=a.no_text_in_picture, centre_on=centre, which=a.which, say=print)
    print("\nPlanned %d version(s) each of %d clip(s), from the %s cuts. Nothing has been made yet."
          % (a.versions, len(m["clips"]), m["made_from"]))
    for r in m["refused"]:
        print("Left out  %s: %s." % (r["id"], r["why"]))
    for note in sorted({n for c in m["clips"] for n in c["notes"]}):
        print("Note: " + note)
    if m["music"]["note"]:
        print("Note: " + m["music"]["note"])
    if a.no_text_in_picture and not m["mirror"]["brand_allows"]:
        print("Note: no version is mirrored, because this brand's settings do not allow it (video.allow_mirror).")
    waiting = [c["id"] for c in m["clips"] if not c["may_be_delivered"]]
    if waiting:
        print("On HOLD, waiting for sign-off: %s. They can be made as previews only." % ", ".join(waiting))
    print("Next: variants render.")
    return 0


def _render(args):
    from smf.video import variants as V
    ap = _parser("variants", "render", "Make the versions in the plan.")
    ap.add_argument("--clip", action="append")
    ap.add_argument("--version", action="append", help="just this version (for example v2); repeat for more")
    ap.add_argument("--preview", action="store_true",
                    help="also make stamped previews of clips still waiting for sign-off, for that person to watch")
    ap.add_argument("--again", action="store_true", help="make finished files again")
    a = ap.parse_args(args)
    r = V.render_variants(brands.load(a.brand), a.recording, clip_ids=a.clip, versions=a.version, preview=a.preview,
                          again=a.again, say=print)
    print("\n%d made, %d already there, %d could not be made." % (len(r["made"]), len(r["already"]), len(r["failed"])))
    if r["waiting"]:
        print("%d clip(s) are waiting for sign-off and were not made. Add --preview to make watch-only copies."
              % len(r["waiting"]))
    if r["made"] and not r["failed"]:
        print("Next: look at them, then variants verify.")
    return 1 if r["failed"] else 0


def _verify(args):
    from smf.video import verify as VF
    ap = _parser("variants", "verify", "Open every finished version and check what is in it.")
    ap.add_argument("--clip", action="append")
    a = ap.parse_args(args)
    out = VF.verify(brands.load(a.brand), a.recording, only=a.clip, say=print)
    print("\n%d version(s) checked, %d failed." % (out["checked"], len(out["failed"])))
    for row in out["versions"]:
        for look in row["looks"]:
            print("Worth a look, %s %s: %s" % (row["clip"], row["version"], look))
    if out["failed"]:
        print("A version that failed is not delivered. Find the cause (the wrong clip, a cut that lost a word, someone "
              "off camera), fix it where it started, and make the versions again.")
    return 1 if out["failed"] else 0


def _deliver(args):
    from smf.video import deliver as DL
    ap = _parser("variants", "deliver", "Copy checked versions, with their words, into the brand's video inbox.")
    ap.add_argument("--clip", action="append")
    ap.add_argument("--version", action="append")
    ap.add_argument("--dry-run", action="store_true", help="say what would happen; copy nothing")
    ap.add_argument("--watched-by", default="", metavar="NAME",
                    help="a person who watched the versions themselves, for ones that have not passed the check")
    ap.add_argument("--allow-unverified-words", action="store_true",
                    help="let descriptions through that are unverified (never ones that are blocked)")
    a = ap.parse_args(args)
    rec = DL.deliver(brands.load(a.brand), a.recording, clip_ids=a.clip, versions=a.version, watched_by=a.watched_by,
                     allow_unverified_words=a.allow_unverified_words, dry_run=a.dry_run, say=print)
    new = [v for v in rec["videos"] if v["outcome"] in ("delivered", "would be delivered")]
    print("\n%d video(s) %s, %d already there, %d not delivered."
          % (len(new), "would be delivered" if a.dry_run else "delivered",
             len([v for v in rec["videos"] if v["outcome"] == "already"]), len(rec["refused"])))
    held_back = [w for w in rec["words"] if str(w["outcome"]).startswith("not written")]
    if held_back:
        print("%d description(s) were not written. Run describe check to see why." % len(held_back))
    if new and not a.dry_run:
        print("Nothing has been scheduled. Next: shorts, which plans them one a day for a person to approve.")
    return 0 if rec["videos"] or not rec["refused"] else 1


def _status(args):
    from smf.video import variants as V
    ap = _parser("variants", "status", "Where every clip stands.")
    a = ap.parse_args(args)
    for row in V.status(brands.load(a.brand), a.recording):
        state = "may be delivered" if row["may_be_delivered"] else \
            "on HOLD, waiting for sign-off by %s" % (row["sign_off_by"] or "a named person")
        print("%s  %s, %s. Planned: %s. Made: %s.%s"
              % (row["clip"], row["gate"], state, ", ".join(row["planned"]) or "none", ", ".join(row["made"]) or "none",
                 (" Previews: %s." % ", ".join(row["previews"])) if row["previews"] else ""))
    return 0


# ----------------------------------------------------------------------------- describe
def cli_describe(args):
    action = _action("describe", DESCRIBE_ACTIONS, args)
    if action is None:
        return 1
    return _guard({"contract": _contract, "check": _check}[action], args[1:])


def _contract(args):
    from smf.video import describe as D
    from smf.video import variants as V
    ap = _parser("describe", "contract", "The page Claude writes one clip's descriptions from.")
    ap.add_argument("--clip", action="append", help="just this clip; by default a page is written for every clip")
    ap.add_argument("--platform", action="append", help="just this platform; by default the brand's video platforms")
    ap.add_argument("--print", action="store_true", dest="show", help="also print the page")
    a = ap.parse_args(args)
    brand = brands.load(a.brand)
    clips = a.clip or [c["id"] for c in V.load_manifest(brand, a.recording)["clips"]]
    for clip_id in clips:
        contract, path = D.write_contract(brand, a.recording, clip_id, a.platform)
        print("%s: the page to write from is %s" % (contract["clip"]["id"], locate(brand, path)))
        for w in contract["warnings"]:
            print("  before you start: " + w)
        if a.show:
            print(contract.markdown)
    print("Write the words into %s, then run describe check." % locate(brand, D.store_path(brand, a.recording)))
    return 0


def _check(args):
    from smf.video import describe as D
    ap = _parser("describe", "check", "Check every description that has been written.")
    ap.add_argument("--clip", action="append")
    a = ap.parse_args(args)
    report = D.check_descriptions(brands.load(a.brand), a.recording, only=a.clip)
    print(D.format_report(report))
    return 1 if report["counts"]["blocked"] else 0
