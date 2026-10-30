"""montage_cli.py - the narrated-film verb. Every action needs --brand and --film.

    montage  footage  list what is in the brand's footage folder (Inputs/Footage): new files are
                      added to footage.json with their length, notes a person wrote are kept, a
                      file that has gone is marked missing. Needs only --brand
             draft    write a plan whose lines already exist and whose shots do not: from the
                      brand's own onboarding answers (--from-brand) or a finished script
                      (--from-script FILE), with the footage folder as its sources. Never
                      overwrites a plan that has lines
             new      start a film: writes a plan to fill in (never overwrites one)
             check    everything that can be known before rendering: shots past the end of their
                      source, shots across a scene change, still-looking shots, unsourced numbers,
                      uncredited footage. Free; sends nothing
             voice    make the narration's takes with ElevenLabs: says how much text it would send
                      and sends nothing, unless --confirm. Only lines without a take are sent
             words    where each word falls in one line's take (--line N), so a cut can land on a
                      word. Transcribing costs a little: it says how much, and sends only with --confirm
             music    make the music bed to order with ElevenLabs Music, when the plan's music is
                      {"compose": {"prompt": ...}}: says what would be sent (the words, the length, the
                      model) and that it uses credits from their plan, and sends nothing unless
                      --confirm. With no prompt, the words are drafted from the brand's own settings
                      into the plan for the person to approve, and nothing is sent on that run. The
                      bed is saved in the film's music folder and becomes the plan's music file;
                      the same words, length and model are never made twice
             render   check, then make the film, a contact sheet from the finished film, credits and
                      a report (--dry-run lists every shot and makes nothing)
             titles   a motion-title clip for every piece of on-screen text the plan already has (its
                      title, each line's "on_screen" words, the brand's wordmark and handle), in the
                      brand's colours and fonts, rendered by HyperFrames (needs Node 22+; a pilot).
                      Each becomes a source title-<n> suggested on its line; nothing is placed

Each returns 0 when it did its job and 1 when it could not, with a plain sentence saying why.
"""
from __future__ import annotations

import argparse

from smf import brands
from smf.video.common import VideoError, fmt_ts

ACTIONS = ("footage", "draft", "new", "check", "voice", "words", "music", "render", "titles")


def _guard(fn):
    """Run one action; turn the tools' own errors into a sentence and exit code 1."""
    def wrapped(args):
        try:
            return fn(args)
        except (brands.BrandError, VideoError) as e:
            print(str(e))
            for f in getattr(e, "findings", None) or []:
                print("  - %s" % f)
            return 1
        except OSError as e:
            print("A file could not be read or written (%s). Nothing else was changed. Check that the disk has "
                  "room and that the brand's folder is not open in another program." % (e.strerror or "unknown reason"))
            return 1
    wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
    return wrapped


def _show(title, items):
    if items:
        print(title)
        for item in items:
            print("  - %s" % item)


def _say_footage(found, brief=False):
    """What a scan of the footage folder found, in sentences."""
    if not brief:
        print("%d file%s in the footage folder (%s). The list is %s."
              % (found["files"], "" if found["files"] == 1 else "s", found["folder"], found["path"]))
    if found["added"]:
        print("New: %s." % ", ".join(found["added"]))
    if found["returned"]:
        print("Back again: %s." % ", ".join(found["returned"]))
    if found["missing"]:
        print("Missing (the file has gone; its notes are kept until it is back): %s." % ", ".join(found["missing"]))
    if found["unnamed"]:
        print("No note yet on what is in: %s. Look at a few frames of each with the person and write it under "
              "\"shows\", with \"credit\" for anything that is not their own." % ", ".join(found["unnamed"]))
    if not brief and found["files"] == 0:
        print("Nothing to cut from yet. Ask the person to put their footage and pictures in that folder: finished "
              "videos, raw recordings, screen captures, renders, logo animations, stills.")


@_guard
def cli_montage(args):
    from smf.video import montage
    action = args[0] if args and not args[0].startswith("-") else None
    if action not in ACTIONS:
        print("Say what to do with the film: %s. For example: factory.py montage check --brand <id> --film "
              "\"<name>\"" % ", ".join(ACTIONS))
        return 1
    ap = argparse.ArgumentParser(prog="factory.py montage %s" % action,
                                 description="A narrated film cut from many sources.")
    ap.add_argument("--brand", required=True, help="which brand this is for (there is no default)")
    ap.add_argument("--film", required=(action != "footage"),
                    help="the film's name; its folder is Output/video/films/<name>")
    ap.add_argument("--title", help="new, draft: the film's title, if different from its name")
    ap.add_argument("--from-brand", action="store_true", help="draft: the lines are the brand's own onboarding answers")
    ap.add_argument("--from-script", metavar="FILE", help="draft: the lines come from this finished script")
    ap.add_argument("--confirm", action="store_true", help="voice, words, music: really send (it costs a little)")
    ap.add_argument("--line", type=int, help="words: which line of the narration, counting from 1")
    ap.add_argument("--dry-run", action="store_true", help="render: list every shot and make nothing")
    a = ap.parse_args(args[1:])
    brand = brands.load(a.brand)

    if action == "footage":
        found = montage.scan_footage(brand)
        _say_footage(found)
        return 0

    if action == "draft":
        out = montage.draft(brand, a.film, from_brand=a.from_brand, script=a.from_script, title=a.title)
        print("Drafted '%s' from %s: %d lines, each with where its words came from, and no shots yet. The plan is "
              "at %s." % (a.film, out["from"], out["lines"], out["path"]))
        if out["no_footage"]:
            print("The footage folder is empty (%s). Put the footage and pictures the film may use in there, then "
                  "run montage footage; the draft's sources are a placeholder until then." % out["footage"]["folder"])
        else:
            print("%d sources, from the footage folder. %d line%s %s a suggested shot to look at."
                  % (out["sources"], out["suggested"], "" if out["suggested"] == 1 else "s",
                     "has" if out["suggested"] == 1 else "have"))
            _say_footage(out["footage"], brief=True)
        _show("Not said yet (the brand's files have nothing for these; ask, never fill them in):" if a.from_brand
              else "Trouble reading the script:", out["missing"])
        if out["own_voice"]:
            print("The voice is the brand's own, from its settings (%s)." % out["model"])
        else:
            print("The brand has no voice of its own in its settings yet, so the plan's voice is a placeholder: put "
                  "the ElevenLabs voice id in, or save it once for every film under the brand's video settings.")
        if out["words_to_check"]:
            print("Words the voice may say wrong, for \"say_as\": %s." % ", ".join(out["words_to_check"]))
        print("Next: read the lines with the person and take their changes, then place shots by looking at frames, "
              "then montage check.")
        return 0

    if action == "new":
        path = montage.create(brand, a.film, title=a.title)
        print("Started '%s'. Its plan is at %s. Fill in the sources, the voice and the lines, then run "
              "montage check." % (a.film, path))
        return 0

    if action == "titles":
        out = montage.titles(brand, a.film, say=print)
        new = [t for t in out["titles"] if not t["reused"]]
        old = [t for t in out["titles"] if t["reused"]]
        if not out["titles"]:
            print("There is nothing to make a title from: the plan has no title, no line has \"on_screen\" words, "
                  "and the brand has no wordmark. A title only ever carries words that are already there.")
            return 0
        if new:
            took = sum(t["took"] or 0 for t in new)
            print("Made %d title clip%s in the brand's colours (%.0f seconds of rendering):"
                  % (len(new), "" if len(new) == 1 else "s", took))
            for t in new:
                print("  - %s: %s, %.1fs, suggested on line %d (\"%s\")"
                      % (t["name"], {"opening": "the opening title", "words": "words on screen",
                                     "end_card": "the end card"}[t["kind"]], t["seconds"], t["line"],
                         " / ".join(t["text"])))
        if old:
            print("%d already made for the same words, size and frame rate, so %s left as %s: %s."
                  % (len(old), "it was" if len(old) == 1 else "they were", "it is" if len(old) == 1 else "they are",
                     ", ".join(t["name"] for t in old)))
        _show("Fonts:", out["notes"])
        if out["without"]:
            print("No title for line%s %s: %s no \"on_screen\" words. A title carries only words already in the plan."
                  % ("s" if len(out["without"]) > 1 else "", ", ".join(str(n) for n in out["without"]),
                     "they have" if len(out["without"]) > 1 else "it has"))
        print("Each is a source in the plan, suggested on its line and placed nowhere. Open the clips in %s and look "
              "before placing one: add a shot from it to that line (the opening title can go in \"opening\" with its "
              "seconds), then montage check." % out["folder"])
        return 0

    if action == "check":
        found = montage.check(brand, a.film)
        tl = found["timeline"]
        _show("Fix these before rendering:", found["errors"])
        _show("Look at these (you decide):", found["warnings"])
        print("%d lines, %d shots, %s%s." % (len(tl["lines"]), len(tl["shots"]), fmt_ts(tl["seconds"]),
                                             " (estimated)" if found["estimated"] else ""))
        if found["errors"]:
            return 1
        print("Nothing is stopping a render.")
        return 0

    if action == "voice":
        out = montage.make_voice(brand, a.film, confirm=a.confirm)
        if out["mode"] == "recording":
            print("The narration is your own recording, so there is nothing to make: render cuts each line out of it.")
            return 0
        if not out["to_make"]:
            print("Every line already has its take. Nothing was sent.")
            return 0
        lines = ", ".join(str(n) for n in out["to_make"])
        if not out["sent"]:
            print("%d line%s need%s a take (%s): %d characters of text, taken from your ElevenLabs plan's allowance. "
                  "Nothing was sent. Run the same command with --confirm to make them."
                  % (len(out["to_make"]), "s" if len(out["to_make"]) > 1 else "",
                     "" if len(out["to_make"]) > 1 else "s", lines, out["characters"]))
            return 0
        print("Made %d take%s (lines %s). Lines that already had one were left alone, so nothing timed to them moved."
              % (out["made"], "" if out["made"] == 1 else "s", lines))
        return 0

    if action == "words":
        if not a.line:
            raise VideoError("Say which line with --line, counting from 1.")
        out = montage.line_words(brand, a.film, a.line, confirm=a.confirm)
        if out["words"] is None:
            print("Finding where each word falls in line %d costs %s. Nothing was sent. Run the same command with "
                  "--confirm to do it." % (a.line, out["cost_words"]))
            return 0
        print("Line %d, seconds from the start of its take:" % a.line)
        print("  " + "  ".join("%s@%.2f" % (w["word"], w["start"]) for w in out["words"]))
        return 0

    if action == "music":
        out = montage.make_music(brand, a.film, confirm=a.confirm)
        if out["mode"] == "file":
            print("The music is a track of your own, so there is nothing to make: render plays it under the voice.")
            return 0
        if out["mode"] == "bed":
            print("The music is the built-in quiet bed, so there is nothing to make and nothing to pay for.")
            return 0
        length = "%s%s" % (fmt_ts(out["seconds"]),
                           " (pinned)" if out["pinned"] else " (the film's %slength plus a few seconds)"
                           % ("estimated " if out["estimated"] else ""))
        if out["drafted"]:
            print("The plan had no words for the music, so these were drafted from the brand's own settings (%s in "
                  "brand-master.json) and "
                  "written into the plan: \"%s\". Read them with the person and change anything that is not right; "
                  "nothing was sent. Then run the same command%s to make %s of %s music with ElevenLabs Music (%s), "
                  "which uses credits from their ElevenLabs plan."
                  % (", ".join(out["drafted_from"]), out["prompt"], "" if a.confirm else " with --confirm", length,
                     "instrumental" if out["instrumental"] else "sung", out["model"]))
            return 0
        if out["reused"]:
            print("The music bed is already made (%s in the film's folder) from the same words and model, and it "
                  "is long enough for the film. Nothing was sent; the plan plays it under the voice." % out["file"])
            return 0
        if not out["sent"]:
            print("ElevenLabs Music (%s) would make %s of %s music from these words: \"%s\". That uses credits "
                  "from your ElevenLabs plan. Nothing was sent. Run the same command with --confirm to make it."
                  % (out["model"], length, "instrumental" if out["instrumental"] else "sung", out["prompt"]))
            if out["estimated"]:
                print("The length is an estimate because the voice has not been made yet. Make the voice first and "
                      "the bed will be cut to fit; made now, it may need making again if the film runs longer.")
            return 0
        print("Made the music bed: %s, saved as %s in the film's folder. The plan now plays it under the voice. "
              "Listen to it before rendering. Running this again costs nothing unless the words, the length or the "
              "model change."
              % (length, out["file"]))
        return 0

    report = montage.render(brand, a.film, dry_run=a.dry_run, say=print)
    _show("Look at these (you decide):", report.get("warnings"))
    tl = report["timeline"]
    if report["dry_run"]:
        print("That is the whole film: %s. Nothing was made." % fmt_ts(tl["seconds"]))
        return 0
    print("Made the film: %s, %d shots. Its picture and sound match (%.2fs and %.2fs). Open the contact sheet "
          "(%s) and watch the film before anyone else does: the sheet is taken from the finished film, not the plan."
          % (fmt_ts(tl["seconds"]), len(tl["shots"]), report["picture_seconds"], report["sound_seconds"],
             montage.SHEET_FILE))
    return 0
