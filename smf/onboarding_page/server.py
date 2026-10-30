"""server.py - the onboarding page's local web server.

    from smf.onboarding_page.server import create_app, serve
    serve(draft=None, brand=None)        # picks a free port, opens the browser, runs until stopped

It follows the review page's pattern (smf/studio/review/server.py, reused and not edited): this
computer only (127.0.0.1, deliberately not a setting), nothing fetched from the internet, a browser
security policy on every answer, and visitors from other web pages turned away. On top of that,
every address carries the session's private code, so a page elsewhere cannot even find it.

What it answers (all under /<code>/):
    GET  /<code>/                 the page
    GET  /<code>/api/questions    the eight questions (questions.json), in the skill's order
    GET  /<code>/api/fields       the v2 designs' questions: the 31 core fields and Go deeper (fields.json)
    GET  /<code>/api/session      the answers so far, the hand-off state, the result once there is one
    POST /<code>/api/answer       {key, answer}   save one answer (checked for keys first)
    POST /<code>/api/finish       {via: "page" | "chat"}   the person is done; the agent takes over
    POST /<code>/api/open-folder  opens THIS session's brand folder in Finder or File Explorer (nothing else)
    GET  /<code>/sample           the first sample picture, only from inside that brand's folder
    POST /<code>/api/closing      {choice: "first-post" | "done"}   the last tap, handed to the agent by --wait
    POST /<code>/api/reflection   {question, answer}   the closing question, kept on this computer

The server stops itself when `onboard-page --stop` is run, or when a newer session replaces it.
"""
from __future__ import annotations

import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from smf import brands
from smf.onboarding_page import secrets_check, voice
from smf.onboarding_page import session as S
from smf.studio.review.server import CONTENT_POLICY, HOST, LOCAL_NAMES, pick_port

DEFAULT_PORT = 8652
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class Refusal(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def create_app(code):
    """The Flask app for one session, identified by its private code."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = voice.MAX_BYTES + 64 * 1024      # one recorded answer at most
    lock = threading.Lock()                     # one answer at a time: read, change, write

    def live_session():
        session = S.load_session()
        if session is None or session.get("code") != code:
            raise Refusal("This onboarding page has been replaced or closed. Go back to the chat.", 410)
        return session

    # --- who may talk to it ---------------------------------------------------------------
    @app.before_request
    def only_this_page():
        host = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in LOCAL_NAMES:
            raise Refusal("The onboarding page only answers on this computer.", 403)
        origin = request.headers.get("Origin")
        # Exactly this page: the same computer AND the same port. Another program's page on this
        # computer (a different port) is turned away too, even before the private code is checked.
        if origin and urlsplit(origin).netloc.lower() != (request.host or "").lower():
            raise Refusal("The onboarding page only answers to itself.", 403)
        if request.method == "POST" and request.path.endswith("/api/listen"):
            # A recording arrives as raw audio. An audio content type cannot be sent by another web
            # page without the browser asking first, so this keeps the same protection as JSON.
            if not (request.mimetype or "").startswith("audio/"):
                raise Refusal("That did not arrive in the shape the onboarding page sends.", 415)
        elif request.method == "POST" and not request.is_json:
            raise Refusal("That did not arrive in the shape the onboarding page sends.", 415)

    @app.after_request
    def lock_down(resp):
        resp.headers["Content-Security-Policy"] = CONTENT_POLICY
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(Refusal)
    def refused(e):
        return jsonify({"error": e.message}), e.status

    @app.errorhandler(S.SessionError)
    def session_problem(e):
        return jsonify({"error": str(e)}), 409

    @app.errorhandler(HTTPException)
    def plain_http_error(e):
        # The same sentence for a wrong code and a wrong address: a guess learns nothing.
        return jsonify({"error": "There is nothing at that address."}), 404 if e.code in (404, 405) else (e.code or 400)

    @app.errorhandler(Exception)
    def unexpected(_e):
        return jsonify({"error": "Something went wrong on the page. Your confirmed answers are safe. "
                                 "Reload the page, or go back to the chat."}), 500

    def check_code(given):
        if not given or not secrets.compare_digest(str(given), code):
            raise Refusal("There is nothing at that address.", 404)

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise Refusal("That did not arrive in the shape the onboarding page sends.")
        return data

    # --- the page -------------------------------------------------------------------------
    @app.get("/<given>/")
    def index(given):
        check_code(given)
        layout = live_session().get("layout")
        return Response(page_html(layout), mimetype="text/html")

    @app.get("/<given>/api/fields")
    def api_fields(given):
        check_code(given)
        return jsonify(S.fields())

    @app.get("/<given>/api/packs")
    def api_packs(given):
        """The bundled starter packs (spec rev 12, N3): read from this computer, never fetched."""
        check_code(given)
        return jsonify(S.starter_packs())

    @app.get("/<given>/api/session")
    def api_session(given):
        check_code(given)
        session = live_session()
        intake = S.load_intake(session)
        return jsonify(view(session, intake))

    @app.get("/<given>/api/questions")
    def api_questions(given):
        check_code(given)
        return jsonify({"questions": S.questions()})

    @app.post("/<given>/api/answer")
    def api_answer(given):
        check_code(given)
        data = body()
        key, answer = data.get("key"), data.get("answer")
        if secrets_check.any_secret(answer):
            # Thrown away before anything is written or shown back.
            raise Refusal(secrets_check.MESSAGE, 422)
        problems = S.validate_answer(key, answer)
        if problems:
            raise Refusal("That answer could not be saved: " + "; ".join(problems[:3]))
        if S.confirmed_without_tap(key, answer):
            raise Refusal(S.NOT_TAPPED, 422)
        if S.reads_like_example(key, answer):
            raise Refusal(S.LIKE_THE_EXAMPLE, 409)
        with lock:
            session = live_session()
            intake = S.load_intake(session)
            if intake.get("state") == "complete":
                raise Refusal("Your answers are already with Claude. Make any change in the chat.", 409)
            # The brand changed in the chat while this page was open (#43, gap 10): ask before anything is
            # confirmed over it. Reopening shows what changed, beside the person's answers.
            if intake.get("brand") and intake.get("opened_fingerprint") and answer_confirms(answer):
                try:
                    now = S.brand_fingerprint(brands.load(intake["brand"], allow_invalid=True))
                except brands.BrandError:
                    now = intake["opened_fingerprint"]
                if now and now != intake["opened_fingerprint"]:
                    raise Refusal("Your brand was changed in the chat while this page was open, so nothing was "
                                  "confirmed. Ask Claude to open the page again: it shows what changed, and keeps "
                                  "your answers beside it.", 409)
            # A file marked "don't use" since this page loaded (M3): nothing from it is saved back, even from
            # a stale screen.
            banned = {x.get("id") for x in ((intake["answers"].get("inventory") or {}).get("sources") or [])
                      if isinstance(x, dict) and x.get("dont_use")}
            if banned and refs_from(answer, banned):
                raise Refusal("Part of that came from a file you marked \"don't use\", so it wasn't saved. Reload "
                              "the page: that wording is gone, and you can answer in your own words.", 409)
            intake["answers"][key] = answer
            skipped = [k for k in intake.get("skipped", []) if k != key]
            if (isinstance(answer, dict) and answer.get("status") == "skipped") or answer == []:
                skipped.append(key)
            intake["skipped"] = skipped
            S.write_json(session["intake"], intake)
        return jsonify(view(session, intake))

    @app.post("/<given>/api/typing")
    def api_typing(given):
        """{field, snap}: what's typed on a question but not confirmed yet, as plain values (snap null clears it).
        Checked for keys like any answer; never part of the answers, never in the brand."""
        check_code(given)
        data = body()
        fid, snap, rev = data.get("field"), data.get("snap"), data.get("rev")
        if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
            raise Refusal("That did not arrive in the shape the onboarding page sends.")
        problem = S.typing_problems(fid, snap)
        if not isinstance(fid, str) or problem == "That isn't one of the page's questions.":
            raise Refusal(problem or "That isn't one of the page's questions.")
        with lock:
            session = live_session()
            intake = S.load_intake(session)
            if intake.get("state") == "complete":
                raise Refusal("Your answers are already with Claude. Make any change in the chat.", 409)
            revs = intake.setdefault("typing_rev", {})
            if rev < revs.get(fid, -1):
                return jsonify({"ok": True, "stale": True})          # an older save arriving late: the newer one stands
            typing = intake.setdefault("typing", {})
            revs[fid] = rev
            if problem:
                if problem == secrets_check.MESSAGE:                 # what was kept before goes too: never resurrected
                    typing.pop(fid, None)
                    S.write_json(session["intake"], intake)
                raise Refusal(problem, 422 if problem == secrets_check.MESSAGE else 400)
            if snap is None:
                typing.pop(fid, None)
            else:
                typing[fid] = snap
            S.write_json(session["intake"], intake)
        return jsonify({"ok": True})

    @app.post("/<given>/api/candidate")
    def api_candidate(given):
        """{key, part, cid}: the owner decided one alternative beside their answer (used, added or kept theirs)."""
        check_code(given)
        data = body()
        key, part, cid = data.get("key"), data.get("part") or "", data.get("cid")
        if key not in S.ANSWER_KEYS or not isinstance(cid, str) or not isinstance(part, str):
            raise Refusal("That did not arrive in the shape the onboarding page sends.")
        with lock:
            session = live_session()
            intake = S.load_intake(session)
            if intake.get("state") == "complete":
                raise Refusal("Your answers are already with Claude. Make any change in the chat.", 409)
            if not S.decide_candidate(intake, key, part, cid):
                raise Refusal("That suggestion was already decided. The page has the latest now.", 409)
            S.write_json(session["intake"], intake)
        return jsonify(view(session, intake))

    @app.post("/<given>/api/finish")
    def api_finish(given):
        check_code(given)
        via = body().get("via", "page")
        if via not in ("page", "chat"):
            raise Refusal("That did not arrive in the shape the onboarding page sends.")
        with lock:
            session = live_session()
            intake = S.load_intake(session)
            if intake.get("state") != "complete":
                intake["state"] = "complete"
                intake["finished_via"] = via
                intake["completed_at"] = S.now_iso()
                intake["completed"] = time.time()
                S.write_json(session["intake"], intake)
        return jsonify(view(session, intake))

    # --- talking (card F6) ----------------------------------------------------------------
    @app.get("/<given>/api/voice")
    def api_voice(given):
        """Whether talking can work: the same key state status uses (missing, unverified, verified,
        not_working), so the page and "check my setup" never disagree."""
        check_code(given)
        from smf import verify_keys
        state = verify_keys.key_state(voice.KEY_NAME)
        # The price is shown only when they ask to talk (spec rev 12, N8), from the one price list.
        from smf import services
        try:
            cost = services.cost_line(services.by_id("elevenlabs")).split(". ")[0].rstrip(".") + "."
        except (KeyError, OSError, TypeError, ValueError):
            cost = ""
        return jsonify({"available": state in ("unverified", "verified"), "state": state, "cost": cost})

    @app.post("/<given>/api/microphone")
    def api_microphone(given):
        """What the browser's microphone check found, so `--status` can explain "the page won't hear me"."""
        check_code(given)
        state = body().get("state")
        if state not in ("ok", "denied", "missing", "unsupported", "insecure"):
            raise Refusal("That did not arrive in the shape the onboarding page sends.")
        with lock:
            session = live_session()
            intake = S.load_intake(session)
            intake["microphone"] = {"state": state, "at": S.now_iso()}
            S.write_json(session["intake"], intake)
        return jsonify({"saved": True})

    @app.post("/<given>/api/consent")
    def api_consent(given):
        """Asked every session, before any recording (spec, journey step 0b)."""
        check_code(given)
        if body().get("recording") is not True:
            raise Refusal("That did not arrive in the shape the onboarding page sends.")
        with lock:
            session = live_session()
            intake = S.load_intake(session)
            intake["consent"] = {"recording": True, "at": S.now_iso()}
            S.write_json(session["intake"], intake)
        return jsonify({"saved": True})

    @app.post("/<given>/api/listen")
    def api_listen(given):
        """One recorded answer, in memory: sent to ElevenLabs, turned into words, then dropped.
        Speech never saves an answer; the words come back for the person to check."""
        check_code(given)
        session = live_session()
        intake = S.load_intake(session)
        if not (intake.get("consent") or {}).get("recording"):
            raise Refusal("I need your OK before I listen. Choose Use voice, or type instead.", 403)
        if intake.get("state") == "complete":
            raise Refusal("Your answers are already with Claude. Make any change in the chat.", 409)
        if (request.content_length or 0) > voice.MAX_BYTES:
            raise Refusal("That recording was too long. Try a shorter answer, or type it.", 413)
        audio = request.get_data(cache=False)            # held in memory, never written anywhere
        try:
            text = voice.transcribe_bytes(audio, request.mimetype, post=app.config.get("VOICE_POST"))
        except voice.VoiceError as e:
            if getattr(e, "refused", False):             # first use is a real check: remember it, as status does
                _remember_key(False, str(e))
            raise Refusal(str(e), 422)
        finally:
            audio = None
        _remember_key(True, "")
        return jsonify(voice.understand(text, request.args.get("q")))

    def _remember_key(ok, reason):
        from smf import verify_keys
        if app.config.get("VOICE_POST"):                 # a stand-in for ElevenLabs (tests) is not a real check
            return
        try:
            verify_keys.record([voice.KEY_NAME], ok, reason)
        except Exception:                                # remembering must never cost the person their answer
            pass

    # --- the ending (step F5.3) -----------------------------------------------------------
    def finished_brand():
        """The brand THIS session built, from the agent's result. Never a path from the browser."""
        session = live_session()
        result = session.get("result") or {}
        if not result.get("ok") or not result.get("brand"):
            raise Refusal("Your brand isn't ready yet.", 409)
        try:
            return session, brands.load(result["brand"])
        except brands.BrandError:
            raise Refusal("Your brand isn't ready yet.", 409)

    @app.post("/<given>/api/open-folder")
    def api_open_folder(given):
        check_code(given)
        _session, brand = finished_brand()
        home = os.path.realpath(brand.home)
        root = os.path.realpath(brands.CLIENT_DIR)
        if os.path.commonpath([home, root]) != root or not os.path.isdir(home):
            raise Refusal("That folder can't be opened from here.", 403)
        opened = open_folder(home)
        where = " › ".join(["Documents", os.path.basename(brands.ROOT) or "social-media-factory",
                                 "Client", brand.name])
        return jsonify({"opened": opened, "where": where})

    @app.get("/<given>/sample")
    def sample(given):
        check_code(given)
        session, brand = finished_brand()
        rel = (session.get("result") or {}).get("demo_image") or ""
        path = os.path.realpath(os.path.join(brands.ROOT, rel)) if rel else ""
        home = os.path.realpath(brand.home)
        if (not path or os.path.commonpath([path, home]) != home or not os.path.isfile(path)
                or os.path.splitext(path)[1].lower() not in IMAGE_TYPES):
            raise Refusal("There is nothing at that address.", 404)
        with open(path, "rb") as f:
            return Response(f.read(), mimetype=IMAGE_TYPES[os.path.splitext(path)[1].lower()])

    @app.post("/<given>/api/open-material")
    def api_open_material(given):
        """Opens THIS session's material folder: the brand's Inputs/Material, or the new brand's temporary one."""
        check_code(given)
        session = live_session()
        intake = S.load_intake(session)
        brand = None
        if intake.get("brand"):
            try:
                brand = brands.load(intake["brand"])
            except brands.BrandError:
                raise Refusal("That folder can't be opened from here.", 403)
        path = os.path.realpath(S.material_dir(brand))
        allowed = os.path.realpath(brand.home if brand is not None else S.tmp_dir())
        if os.path.commonpath([path, allowed]) != allowed:
            raise Refusal("That folder can't be opened from here.", 403)
        return jsonify({"opened": open_folder(path)})

    @app.get("/<given>/summary")
    def brand_summary(given):
        check_code(given)
        _session, brand = finished_brand()
        path = brand.path("brand-summary.html")
        if not os.path.isfile(path):
            raise Refusal("There is nothing at that address.", 404)
        with open(path, "r", encoding="utf-8") as f:
            return Response(f.read(), mimetype="text/html")

    @app.post("/<given>/api/closing")
    def api_closing(given):
        """The person's last tap: write my first post, or I'm done. `--wait` hands it to the agent."""
        check_code(given)
        choice = body().get("choice")
        if choice not in ("first-post", "done"):
            raise Refusal("That did not arrive in the shape the onboarding page sends.")
        finished_brand()
        with lock:
            session = live_session()
            intake = S.load_intake(session)
            intake["closing"] = choice
            S.write_json(session["intake"], intake)
        return jsonify(view(session, intake))

    @app.post("/<given>/api/reflection")
    def api_reflection(given):
        """The one closing question. Saved in the answers file on this computer only, never sent."""
        check_code(given)
        data = body()
        question, answer = str(data.get("question") or "")[:200], str(data.get("answer") or "")[:1000]
        if question not in REFLECTION_QUESTIONS:
            raise Refusal("That did not arrive in the shape the onboarding page sends.")
        if secrets_check.looks_secret(answer):
            raise Refusal(secrets_check.MESSAGE, 422)
        with lock:
            session = live_session()
            intake = S.load_intake(session)
            if intake.get("state") != "complete":
                raise Refusal("Finish the questions first.", 409)
            intake["reflection"] = {"question": question, "answer": answer.strip(), "skipped": not answer.strip(),
                                    "at": S.now_iso()}
            S.write_json(session["intake"], intake)
        return jsonify({"saved": True})

    return app


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
REFLECTION_QUESTIONS = ("What surprised you?", "What’s the first thing you can’t wait to make?",
                        "What would make this even better?", "Where did you pause or get stuck?")


def open_folder(path):
    """Open a folder in Finder or File Explorer. True if the request went to the computer."""
    try:
        if sys.platform == "win32":
            os.startfile(path)                                  # noqa: S606 - a folder this server chose
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except (OSError, AttributeError):
        return False


def page_html(layout=None):
    """The page for this session: today's page, or a v2 design with the shared engine and look put
    inline (the security policy runs inline scripts and styles only)."""
    def read(name):
        with open(os.path.join(STATIC_DIR, name), "r", encoding="utf-8") as f:
            return f.read()
    if layout not in S.LAYOUTS:
        return read("index.html")
    html = read(S.LAYOUTS[layout])
    return (html.replace("/*@V2_COMMON_CSS@*/", read("v2-common.css"))
                .replace("/*@V2_COMMON_JS@*/", read("v2-common.js")))


def refs_from(value, ids):
    """True when anything inside `value` points at one of the source ids (refs, or what it was derived from)."""
    if isinstance(value, dict):
        refs = list(value.get("refs") or []) if isinstance(value.get("refs"), list) else []
        if any(isinstance(r, str) and r.split() and r.split()[0] in ids for r in refs):
            return True
        return any(refs_from(v, ids) for v in value.values() if isinstance(v, (dict, list)))
    if isinstance(value, list):
        return any(refs_from(x, ids) for x in value)
    return False


def answer_confirms(answer):
    """True when saving this answer confirms something (an answer, a part or a list item)."""
    if isinstance(answer, dict):
        return answer.get("status") == "confirmed" or any(answer_confirms(v) for v in answer.values() if isinstance(v, (dict, list)))
    if isinstance(answer, list):
        return any(answer_confirms(x) for x in answer)
    return False


def view(session, intake):
    """Everything the page needs, and nothing else (no file paths, no code)."""
    now = time.time()
    out = {"state": "complete" if intake.get("state") == "complete" else "in_progress",
           "answers": intake.get("answers", {}), "skipped": intake.get("skipped", []),
           "placeholders": S.placeholders(intake, S.asked_keys(session.get("layout"))),
           "followups": intake.get("followups") or {},
           "candidates": intake.get("candidates") or {}, "new_keys": intake.get("new_keys") or [],
           "typing": intake.get("typing") or {}, "typing_rev": intake.get("typing_rev") or {},
           "brand_changed": bool(intake.get("brand_changed")), "reopened": bool(intake.get("brand")),
           "via": intake.get("finished_via"), "consented": bool((intake.get("consent") or {}).get("recording")),
           "result": None, "handoff": None}
    if out["state"] == "complete":
        picked = session.get("picked_up")
        completed = intake.get("completed") or now
        if session.get("result"):
            r = session["result"]
            out["result"] = {k: r.get(k) for k in ("ok", "message", "steps", "brand")}
            out["result"]["has_sample"] = bool(r.get("demo_image"))
            out["result"]["has_summary"] = bool(r.get("summary"))
            out["closing"] = intake.get("closing")
            out["reflected"] = bool(intake.get("reflection"))
            out["handoff"] = "finished"
        elif not picked:
            # Nobody has picked the answers up. After a minute, say so honestly.
            out["handoff"] = "backstop" if now - completed >= S.PICKUP_BACKSTOP else "waiting"
        else:
            out["handoff"] = "trouble" if now - picked >= S.BUILD_TIMEOUT else "building"
    return out


# ----------------------------------------------------------------------------- running it
def _watch(server, code, every=0.5):
    """Stop the server when the session asks it to, or when a newer session has replaced it."""
    while True:
        time.sleep(every)
        try:
            session = S.load_session()
        except S.SessionError:
            continue
        if session is None or session.get("code") != code or session.get("stop"):
            server.shutdown()
            return


def serve(draft=None, brand=None, port=None, open_browser=True, layout=None):
    """Start a session and run the page until it is stopped. Always on 127.0.0.1. `layout` picks
    a v2 design ("one-page" or "steps"); without it, today's page runs."""
    from werkzeug.serving import make_server

    if brand:                                       # add more (rev 13, M5): start from the brand's own answers
        from smf import brands
        intake = S.reopen_intake(brands.load(brand), draft)
    else:
        intake = S.intake_from_draft(draft, brand)
    port = pick_port(port or DEFAULT_PORT)
    session = S.new_session(port, intake, brand, layout=layout)
    app = create_app(session["code"])
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    server = make_server(HOST, port, app, threaded=True)
    # flush: when the agent starts this in the background there is no terminal to show it.
    print("The onboarding page is open at %s" % session["url"], flush=True)
    print("Answers file: %s" % session["intake"], flush=True)
    print("It runs on this computer only and sends nothing anywhere. "
          "Stop it with: factory.py onboard-page --stop", flush=True)
    threading.Thread(target=_watch, args=(server, session["code"]), daemon=True).start()
    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(session["url"],)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("The onboarding page is closed. Confirmed answers are in the answers file.", flush=True)
    return 0
