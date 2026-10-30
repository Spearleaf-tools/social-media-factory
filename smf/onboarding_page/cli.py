"""cli.py - `factory.py onboard-page`: onboarding on its own page, and the agent's side of the hand-off.

    onboard-page [--draft FILE | --demo] [--brand ID] [--port N] [--no-browser] [--layout one-page|steps|classic]
                         start the page (keeps running; start it in the background). The page is design B,
                         one question at a time; --layout one-page opens design A (every question on one long
                         page) and --layout classic the first page (eight questions)
    onboard-page --wait  wait until the person clicks Finish. Prints "complete" and the answers file,
                         or "still answering" after about 9 minutes: then simply run it again
    onboard-page --status    in progress / complete / finished / stopped, never the answers
    onboard-page --result FILE   hand the page the result once the brand is built and checked
    onboard-page --brand-answers FILE   turn the confirmed answers into new-brand / update-brand answers
                         (writes FILE, and FILE's voice samples next to it, word for word)
    onboard-page --summary BRAND        write brand-summary.html in that brand's folder
    onboard-page --stop  close the page once the person has seen the result

--wait is used twice: once until they click Finish ("complete"), and once after --result until their
last tap ("first-post" or "done"). Exit codes for --wait: 0 complete / first-post / done,
3 still answering or still looking (run it again), 1 no page or stopped.
"""
from __future__ import annotations

import argparse
import os
import json

from smf.onboarding_page import session as S

STILL_ANSWERING = 3
# Spec rev 12, N1 (Oct 17; design review: "Show one question at a time"): design B is the onboarding page. A stays
# available by name, and the first page (eight questions) as "classic", until they are retired.
DEFAULT_LAYOUT = "steps"


def _parser():
    p = argparse.ArgumentParser(prog="factory.py onboard-page",
                                description="Onboarding on its own page, on this computer.")
    act = p.add_mutually_exclusive_group()
    act.add_argument("--wait", action="store_true", help="wait until the person finishes the page")
    act.add_argument("--status", action="store_true", help="where the onboarding page is up to")
    act.add_argument("--result", metavar="FILE", help="hand the page the built brand's result")
    act.add_argument("--stop", action="store_true", help="close the onboarding page")
    act.add_argument("--brand-answers", metavar="FILE", help="write the confirmed answers as brand answers")
    act.add_argument("--summary", metavar="BRAND", help="write brand-summary.html for this brand")
    act.add_argument("--keep-answers", metavar="BRAND", help="after the build: keep the answers in the brand, for adding more later")
    act.add_argument("--dont-use", metavar="SOURCE", help="with --brand: a file marked \"don't use\" after reading; takes it out at once")
    act.add_argument("--proof-added", nargs=2, metavar=("ANSWER_ID", "PROOF_ID"), help="with --brand: record which proof item came from which answer")

    act.add_argument("--material", nargs="?", const="", metavar="BRAND", help="make and print the folder for the owner's material")
    p.add_argument("--draft", metavar="FILE", help="answers drafted from the website (shown as Please check)")
    p.add_argument("--settled", action="store_true", help="with --dont-use: what it listed for the chat is settled")
    p.add_argument("--answers-file", metavar="FILE", help="with --brand-answers or --keep-answers: the chat's own answers file, not the page's")
    p.add_argument("--demo", action="store_true", help="open the page with the made-up bakery and its book, to try every screen")
    p.add_argument("--brand", metavar="ID", help="update this existing brand instead of making a new one")
    p.add_argument("--layout", choices=sorted(S.LAYOUTS) + ["classic"], default=DEFAULT_LAYOUT,
                   help="the page design: steps (B, one question at a time, the default), one-page (A) or classic (the first page, eight questions)")
    p.add_argument("--port", type=int, help="the port to try first")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.add_argument("--timeout", type=int, default=S.WAIT_LIMIT, help=argparse.SUPPRESS)
    return p


def _read_file(path, what):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        raise S.SessionError("%s could not be found or opened: %s" % (what, path))
    except ValueError as e:
        raise S.SessionError("%s is not readable (%s)." % (what, e))


def cli_onboard_page(args):
    a = _parser().parse_args(args)
    try:
        if a.wait:
            return _wait(a.timeout)
        if a.status:
            return _status()
        if a.result:
            S.set_result(_read_file(a.result, "The result file"))
            print("finished: the page is showing the result.")
            return 0
        if a.brand_answers:
            return _brand_answers(a.brand_answers, a.answers_file)
        if a.summary:
            return _summary(a.summary)
        if a.keep_answers:
            return _keep_answers(a.keep_answers, a.answers_file)
        if a.dont_use or a.proof_added:
            if not a.brand:
                raise S.SessionError("Say which brand: add --brand <id>.")
            return _dont_use(a.dont_use, a.brand, a.settled) if a.dont_use else _proof_added(a.brand, *a.proof_added)
        if a.material is not None:
            from smf import brands
            print(S.material_dir(brands.load(a.material) if a.material else None))
            return 0
        if a.stop:
            if S.request_stop() is None:
                print("No onboarding page is running here.")
            else:
                print("stopping: the onboarding page will close within a second.")
            return 0
        if a.demo and not a.draft:                  # a made-up bakery with a book: "What we found", quotes, the order
            a.draft = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_draft.json")
        draft = _read_file(a.draft, "The website draft") if a.draft else None
        if a.brand:
            from smf import brands
            brands.load(a.brand)                       # an unknown brand is refused before anything opens
        from smf.onboarding_page import server
        layout = None if a.layout == "classic" else a.layout
        return server.serve(draft=draft, brand=a.brand, port=a.port, open_browser=not a.no_browser, layout=layout)
    except S.SessionError as e:
        print(str(e))
        return 1


def _wait(limit):
    state, session = S.wait(limit=limit)
    if state == "complete":
        print("complete")
        print("Answers file: %s" % session["intake"])
        left = S.placeholders(S.load_intake(session))
        if left:
            print("Not confirmed (treat as placeholders): %s" % ", ".join(left))
        return 0
    if state == "first-post":
        print("first-post: they want to write their first post now. Stop the page and carry on in the chat.")
        return 0
    if state == "done":
        print("done: they have seen their brand. Stop the page.")
        return 0
    if state in ("still answering", "still looking"):
        print("%s: run `factory.py onboard-page --wait` again." % state)
        return STILL_ANSWERING
    if state == "stopped":
        print("stopped: the page closed before the person finished. Their confirmed answers are in %s; "
              "finish the rest in the chat." % session["intake"])
        return 1
    print("No onboarding page is running here.")
    return 1


def _status():
    st = S.status()
    print(st["state"])
    if st["state"] == "no page":
        return 0
    if st.get("address") and st["state"] != "stopped":
        print("Page: %s" % st["address"])
    print("Answers file: %s" % st.get("answers_file"))
    if st.get("still_open"):
        print("Not confirmed yet: %s" % ", ".join(st["still_open"]))
    if st.get("microphone"):
        print("Microphone check: %s" % {"ok": "working", "denied": "permission was refused in the browser",
                                       "missing": "no microphone found", "unsupported": "this browser can't record",
                                       "insecure": "the page wasn't opened at its own address"}.get(st["microphone"], st["microphone"]))
    return 0


def _chat_answers(path):
    """The chat's answers file (the same shape as the page's): checked before anything is built from it."""
    try:
        intake = S.read_json(path)
    except (OSError, ValueError):
        raise S.SessionError("The chat's answers file (%s) can't be read." % path)
    from smf.onboarding_page import secrets_check
    if secrets_check.any_secret(intake):              # first, so no message can ever repeat it
        # The same check the page makes on every answer; the value is never shown back.
        raise S.SessionError("Something in the chat's answers looks like a password or key, so nothing was built. "
                             "Take it out of the answers file; keys go in your keys file, never in your answers.")
    problems = S.validate_intake(intake) if isinstance(intake, dict) else ["not an answers file"]
    if problems:
        raise S.SessionError("The chat's answers file isn't in the shape the page writes: " + "; ".join(problems[:5]))
    return intake


def _brand_answers(out_path, answers_file=None):
    import os
    from smf.onboarding_page import to_brand
    if answers_file:                                # the chat route: the same answers, the same rules, the same build
        intake = _chat_answers(answers_file)
    else:
        session = S.load_session()
        if session is None:
            raise S.SessionError("No onboarding page has been started here.")
        intake = S.load_intake(session)
    if intake.get("state") != "complete":
        raise S.SessionError("The person hasn't finished onboarding yet (the answers aren't marked complete).")
    problems = S.validate_intake(intake)
    if problems:                                    # checked before the brand is even looked up
        raise S.SessionError("The answers file is not in the shape the page writes: " + "; ".join(problems[:5]))
    current = None
    if intake.get("brand"):                         # an update session: lists merge with the brand's own ids
        from smf import brands
        try:
            brand = brands.load(intake["brand"], allow_invalid=True)
            current = brand.data
        except brands.BrandError:
            brand = current = None
        if brand is not None:
            pend = [k for k, w in (S.read_json(S.brand_answers_path(brand)).get("withdrawals") or {}).items()
                    if w.get("status") == "pending"] if os.path.exists(S.brand_answers_path(brand)) else []
            if pend:
                raise S.SessionError("Taking %s out isn't finished, so nothing was built. Run factory.py onboard-page "
                                     "--dont-use %s --brand %s again first." % (pend[0], pend[0], intake["brand"]))
        if brand is not None and S.brand_changed_since(intake, brand):
            raise S.SessionError("The brand was changed in the chat while the page was open, so nothing was built. "
                                 "Open the page again (onboard-page --brand %s): it shows the brand's newer values to "
                                 "check, and keeps the person's answers beside them." % intake["brand"])
    name, answers, notes, voice_md = to_brand.build(intake, current=current)
    S.write_json(out_path, answers)
    print("Brand answers: %s" % out_path)
    print("Name: %s" % (name or "(not confirmed: ask for it in the chat)"))
    if voice_md:
        voice_path = os.path.splitext(out_path)[0] + "-voice-samples.md"
        with open(voice_path, "w", encoding="utf-8") as f:
            f.write(voice_md)
        print("Voice samples, word for word (use as Brand/voice-samples.md): %s" % voice_path)
    proof = to_brand.proof_items(intake)
    made = intake.get("brand") or intake.get("kept_as")    # a new brand's session, retried after it was kept
    if proof and made:
        from smf import brands
        try:
            done = S.recorded_proof_ids(brands.load(made, allow_invalid=True))
        except brands.BrandError:
            done = {}
        proof = [p for p in proof if p.get("id") not in done]       # already in the library: never added twice
    proof_path = os.path.splitext(out_path)[0] + "-proof.json"
    if not proof and os.path.exists(proof_path):
        os.remove(proof_path)                       # a retry: what an earlier run listed is already in the library
    if proof:
        S.write_json(proof_path, proof)
        print("Proof for the proof library, %d item%s: %s. Once the brand exists, add each one with "
              "`factory.py proof add`, exactly as listed (kind, title, detail, source, may-publish); never "
              "change what they said may be published." % (len(proof), "" if len(proof) == 1 else "s", proof_path))
    left = S.placeholders(intake)
    if left:
        print("Placeholders (not confirmed; never fill them in yourself): %s" % ", ".join(left))
    for n in notes:
        print("Settle in the chat: %s" % n)
    return 0


def _keep_answers(brand_id, answers_file=None):
    from smf import brands
    if answers_file:
        intake = _chat_answers(answers_file)
        path, moved = S.keep_answers(brands.load(brand_id), intake, save=lambda x: S.write_json(answers_file, x))
    else:
        session = S.load_session()
        if session is None:
            raise S.SessionError("No onboarding page has been started here.")
        intake = S.load_intake(session)
        path, moved = S.keep_answers(brands.load(brand_id), intake, save=lambda x: S.write_json(session["intake"], x))
    print("Answers kept for adding more later: %s" % path)
    if moved:
        print("Material moved into the brand: %d file%s (Inputs/Material)" % (moved, "" if moved == 1 else "s"))
    return 0


def _summary(brand_id):
    from smf import brands
    from smf.onboarding_page import summary
    session = S.load_session()
    left = []
    if session is not None:
        try:
            left = S.placeholders(S.load_intake(session))
        except S.SessionError:
            left = []
    try:
        path = summary.build(brand_id, placeholders=left)
    except brands.BrandError as e:
        print(str(e))
        return 1
    print("Summary: %s" % path)
    return 0


def _merge_plan(plan, report):
    """One withdrawal plan, kept until it's all done: the brand changes to make, the wording to check for, and
    what the owner must settle in the chat. A retry replays it; nothing in it is ever dropped before it's done."""
    def add(into, more):
        for k, v in more.items():
            if isinstance(v, dict) and isinstance(into.get(k), dict):
                add(into[k], v)
            elif isinstance(v, list) and isinstance(into.get(k), list):
                have = {x.get("id") for x in into[k] if isinstance(x, dict)}
                into[k].extend(x for x in v if not (isinstance(x, dict) and x.get("id") in have))
            else:
                into[k] = json.loads(json.dumps(v))
    add(plan.setdefault("removals", {}), report["removals"])
    for k in ("texts", "manual"):
        plan[k] = sorted(set(plan.get(k) or []) | set(report.get(k) or []))
    return plan


def _brand_still_has(brand, removals):
    """What the brand still holds that the plan takes out: list items by id, values not yet the placeholder."""
    left = []

    def walk(want, have, where):
        if isinstance(want, dict):
            if "value" in want and want.get("value") == S.WITHDRAWN_TODO:
                if not (isinstance(have, dict) and have.get("value") == S.WITHDRAWN_TODO):
                    left.append(where)
                return
            for k, v in want.items():
                walk(v, (have or {}).get(k) if isinstance(have, dict) else None, where + "." + k)
        elif isinstance(want, list):
            ids = {x.get("id") for x in (have or []) if isinstance(x, dict)}
            left.extend("%s[%s]" % (where, x["id"]) for x in want if isinstance(x, dict) and x.get("remove") and x.get("id") in ids)
        elif want == S.WITHDRAWN_TODO and have != S.WITHDRAWN_TODO:
            left.append(where)
    walk(removals, brand.data, "brand")
    return left


def _dont_use(src, brand_id, settled=False):
    """Mark a source "don't use" after it was read, and take everything from it out at once (rev 13, M3): the
    brand's kept answers, any open page for this brand, the brand's settings and brand files. The withdrawn words
    are never printed. The plan is kept with the withdrawal, so a retry after a failure finishes the same job; it
    stays "pending" until the brand is checked clean and anything left to the chat is settled (`--settled`)."""
    import glob
    import os
    from smf import brands
    brand = brands.load(brand_id)
    path = S.brand_answers_path(brand)
    if not os.path.exists(path):
        raise S.SessionError("This brand has no kept answers to take that file out of (it was set up before the page "
                             "kept them). Remove what came from that file in the chat.")
    kept = S.read_json(path)
    inv = (kept.get("answers") or {}).get("inventory") or {}
    if not any(isinstance(x, dict) and x.get("id") == src for x in inv.get("sources") or []):
        raise S.SessionError("The brand's material has no source called %s. Its sources: %s." % (
            src, ", ".join(x.get("id", "?") for x in inv.get("sources") or []) or "none"))
    for x in inv["sources"]:
        if x.get("id") == src:
            x["dont_use"] = True
    plan = kept.setdefault("restricted_plans", {}).setdefault(src, {})        # local only, like the excerpts
    _merge_plan(plan, S.withdraw_source(kept, src))
    session = S.load_session()                      # an open page for this brand drops it too, into the same plan
    live = None
    if session:
        try:
            live = S.load_intake(session)
        except S.SessionError:
            live = None
    if live and live.get("brand") == brand.id:
        for x in ((live.get("answers") or {}).get("inventory") or {}).get("sources") or []:
            if x.get("id") == src:
                x["dont_use"] = True
        _merge_plan(plan, S.withdraw_source(live, src))
    else:
        live = None
    w = kept.setdefault("withdrawals", {}).setdefault(src, {})
    w.update({"status": "pending", "at": S.now_iso()})
    S.write_json(path, kept)                        # the whole plan is safe first ...
    if live is not None:
        S.write_json(session["intake"], live)       # ... then the open page is cleaned
    S.write_json(brand.path("_state", "inventory.json"), inv)
    problems = []
    if plan.get("removals"):
        try:
            brands.update(brand.id, plan["removals"])
        except brands.BrandError as e:
            problems.append("the brand's settings couldn't be changed (%s)" % e)
    brand = brands.load(brand.id, allow_invalid=True)
    sync = brands.sync(brand)
    if sync.get("refused") or sync.get("kept"):
        problems.append("some brand files weren't remade (%s): they were edited by hand"
                        % ", ".join(sync.get("refused", []) + sync.get("kept", [])))
    try:
        if os.path.exists(brand.path("brand-summary.html")):
            from smf.onboarding_page import summary
            summary.build(brand)
    except Exception as e:                          # the check below still runs
        problems.append("the summary page wasn't remade (%s)" % e)
    still = _brand_still_has(brand, plan.get("removals") or {})
    if still:
        problems.append("the brand still holds %d of the answers to take out" % len(still))
    files = [brand.path("brand-master.json"), brand.path("brand-summary.html")] + glob.glob(brand.path("Brand", "*.md")) + \
        glob.glob(brand.path("Studio", "*.json"))
    left = 0
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        left += sum(1 for t in plan.get("texts") or [] if len(t) >= 8 and t in text)
    if left:
        problems.append("%d piece%s of wording from that file still show%s in the brand files" % (
            left, "" if left == 1 else "s", "s" if left == 1 else ""))
    proof = S.proof_from_source(brand, src)
    chat = list(plan.get("manual") or []) + (["proof library items %s, removed by hand" % ", ".join(proof)] if proof else [])
    kept = S.read_json(path)
    w = kept["withdrawals"][src]
    if settled:                                     # settled for exactly what was listed now; anything new asks again
        w["settled_for"] = sorted(set(chat))
    if chat and not set(chat) <= set(w.get("settled_for") or []):
        problems.append("%d thing%s to settle in the chat first (then run this again with --settled)" % (
            len(chat), "" if len(chat) == 1 else "s"))
    w.update({"status": "pending" if problems else "done", "at": S.now_iso()})
    if proof:
        w["proof_to_remove"] = proof
    S.write_json(path, kept)
    print("%s is marked \"don't use\". Its drafts and answers are taken out of the page's answers." % src)
    for m in plan.get("manual") or []:
        print("Settle in the chat: %s" % m)
    if proof:
        print("Proof library items from that file, to remove by hand (the library can't remove them yet): %s"
              % ", ".join(proof))
    if problems:
        print("Not finished, so it stays pending: %s." % "; ".join(problems))
        return 1
    if proof:
        # Honest about what's left: the proof library can't remove items yet, so they're still in it.
        print("Done in the brand's settings and files. Still in the proof library until they're removed by hand: %s."
              % ", ".join(proof))
        return 0
    print("Done: nothing from that file is left in the brand's settings or files.")
    return 0


def _proof_added(brand_id, intake_id, proof_id):
    from smf import brands
    brand = brands.load(brand_id)
    path = S.brand_answers_path(brand)
    prov = {}
    try:
        kept = S.read_json(path)
        for p in ((kept.get("answers") or {}).get("deep") or {}).get("proof") or []:
            if isinstance(p, dict) and p.get("id") == intake_id:
                prov = {k: p[k] for k in ("origin", "refs", "generator") if k in p}
    except (OSError, ValueError):
        pass
    print("Recorded: %s is proof %s (%s)" % (intake_id, proof_id, S.record_proof(brand, intake_id, proof_id, prov)))
    return 0
