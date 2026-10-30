"""server.py - the review page's local web server.

    from smf.studio.review.server import create_app, serve
    app = create_app(brand, ["Client/maple-and-main/Output/batches/week 1.json"])
    serve(brand, batch_paths)            # picks a free port, opens the browser, runs until stopped

It is started for ONE brand and will not open a batch that belongs to another. It listens on this
computer only (127.0.0.1; there is no setting to change that), and it never asks the internet for
anything: no fonts, no scripts, no tracking. A browser security policy on every answer enforces
that, so even a link inside a post cannot make the page fetch something.

What it answers:
    GET  /                        the page
    GET  /api/batch               every post, checked against this brand's rules, plus what the page needs
    GET  /api/post/<id>           one post, fresh from disk
    POST /api/post/<id>/edit      {rev, text?, thread?, alt_text?, first_comment?, media_order?}
    POST /api/post/<id>/approve   {rev, content_sha, acknowledge_unverified?}
    POST /api/post/<id>/reject    {rev, note?}
    POST /api/post/<id>/remake    {rev, note?, kind?: "words" | "image"}
    POST /api/post/<id>/undo      {rev}
    POST /api/post/<id>/seen      {content_sha}
    POST /api/approve-all         {posts: [{id, rev, content_sha}]}
    GET  /media/<id>/<n>          the n-th media file of that post, only from inside the brand's folder

Every change carries the `rev` the person was looking at. If the post has moved on, the answer is
409 with a plain sentence and the fresh post, and nothing is written. All the rules live in store.py.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import traceback
import webbrowser
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from smf.studio.review.store import BatchStore, Refusal, now_iso

HOST = "127.0.0.1"                      # this computer only. Deliberately not a setting.
DEFAULT_PORT = 8642
LOCAL_NAMES = frozenset({"127.0.0.1", "localhost"})
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# The page may load from itself and nowhere else. Its styles and script are inline in the one
# file, so those two are allowed inline; everything else is switched off.
CONTENT_POLICY = ("default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; "
                  "script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
                  "frame-ancestors 'none'")


def create_app(brand, batch_paths):
    """The Flask app for one brand's review. `brand` is a Brand or a brand id; there is no default.
    Raises BrandError (no such brand) or Refusal (no batch, or a batch that belongs to someone
    else) before anything is served."""
    store = BatchStore(brand, batch_paths)
    app = Flask(__name__, static_folder=None)
    app.config["REVIEW_STORE"] = store

    # --- who may talk to it ---------------------------------------------------------------
    @app.before_request
    def only_this_computer():
        # A web page elsewhere can aim a browser at 127.0.0.1. Turn away anything that did not
        # come from this page: a foreign Host name, a foreign Origin, or a change that is not JSON.
        host = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in LOCAL_NAMES:
            raise Refusal("The review page only answers on this computer.", 403)
        origin = request.headers.get("Origin")
        if origin and (urlsplit(origin).hostname or "").lower() not in LOCAL_NAMES:
            raise Refusal("The review page only answers to itself.", 403)
        if request.method == "POST" and not request.is_json:
            raise Refusal("That change did not arrive in the shape the review page sends.", 415)

    @app.after_request
    def lock_down(resp):
        if resp.mimetype in ("text/html", "application/json"):      # a PDF still opens in the browser's viewer
            resp.headers["Content-Security-Policy"] = CONTENT_POLICY
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(Refusal)
    def refused(e):
        body = {"error": e.message}
        body.update(e.extra)
        return jsonify(body), e.status

    @app.errorhandler(HTTPException)
    def plain_http_error(e):
        words = {404: "There is nothing at that address on the review page.",
                 405: "The review page does not do that."}
        return jsonify({"error": words.get(e.code, "The review page could not make sense of that.")}), e.code or 400

    @app.errorhandler(Exception)
    def unexpected(_e):
        # The person gets a sentence. The detail goes to a file in the brand's own state folder,
        # where Claude can read it, and never scrolls past them as a stack trace.
        try:
            os.makedirs(store.brand.state_dir, exist_ok=True)
            with open(os.path.join(store.brand.state_dir, "review-page-errors.txt"), "a", encoding="utf-8") as f:
                f.write("%s %s %s\n%s\n" % (now_iso(), request.method, request.path, traceback.format_exc()))
        except OSError:
            pass
        return jsonify({"error": "Something went wrong on the review page. Nothing was changed. "
                                 "Reload the page; if it happens again, tell Claude what you clicked."}), 500

    # --- helpers --------------------------------------------------------------------------
    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise Refusal("That change did not arrive in the shape the review page sends.")
        return data

    def rev_of(data):
        rev = data.get("rev")
        if not isinstance(rev, int) or isinstance(rev, bool):
            raise Refusal("The page did not say which version of the post it was looking at. Nothing was "
                          "changed. Reload the page and try again.")
        return rev

    def sha_of(data):
        sha = data.get("content_sha")
        if not isinstance(sha, str) or not sha:
            raise Refusal("The page did not say which version of the post it was showing. Nothing was "
                          "changed. Reload the page and try again.")
        return sha

    # --- reading --------------------------------------------------------------------------
    @app.get("/")
    def index():
        return send_file(os.path.join(STATIC_DIR, "index.html"), mimetype="text/html", max_age=0)

    @app.get("/api/batch")
    def api_batch():
        return jsonify(store.overview())

    @app.get("/api/post/<path:post_id>")
    def api_post(post_id):
        return jsonify({"post": store.one(post_id)})

    @app.get("/media/<path:post_id>/<int:index>")
    def media(post_id, index):
        return send_file(store.media_file(post_id, index), max_age=0)

    # --- changing -------------------------------------------------------------------------
    @app.post("/api/post/<path:post_id>/edit")
    def api_edit(post_id):
        data = body()
        post = store.edit(post_id, rev_of(data), text=data.get("text"), thread=data.get("thread"),
                          alt_text=data.get("alt_text"), first_comment=data.get("first_comment"),
                          media_order=data.get("media_order"))
        return jsonify({"post": post})

    @app.post("/api/post/<path:post_id>/approve")
    def api_approve(post_id):
        data = body()
        post = store.approve(post_id, rev_of(data), sha_of(data),
                             acknowledged=data.get("acknowledge_unverified") is True)
        return jsonify({"post": post})

    @app.post("/api/post/<path:post_id>/reject")
    def api_reject(post_id):
        data = body()
        return jsonify({"post": store.reject(post_id, rev_of(data), note=str(data.get("note") or "").strip())})

    @app.post("/api/post/<path:post_id>/remake")
    def api_remake(post_id):
        data = body()
        post = store.remake(post_id, rev_of(data), note=str(data.get("note") or "").strip(),
                            kind=str(data.get("kind") or "words"))
        return jsonify({"post": post})

    @app.post("/api/post/<path:post_id>/undo")
    def api_undo(post_id):
        return jsonify({"post": store.undo(post_id, rev_of(body()))})

    @app.post("/api/post/<path:post_id>/seen")
    def api_seen(post_id):
        return jsonify({"post": store.mark_seen(post_id, sha_of(body()))})

    @app.post("/api/approve-all")
    def api_approve_all():
        items = body().get("posts")
        if not isinstance(items, list) or not items:
            raise Refusal("No posts were named, so nothing was approved.")
        return jsonify(store.approve_many(items))

    return app


# ----------------------------------------------------------------------------- running it
def _is_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(preferred=DEFAULT_PORT, tries=20):
    """The preferred port if nothing is using it, otherwise the next free one, otherwise whatever
    the computer hands out. A second review, or another program on the same number, must never
    stop someone from opening their posts."""
    for port in range(preferred, preferred + tries):
        if 0 < port < 65536 and _is_free(port):
            return port
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((HOST, 0))
        return s.getsockname()[1]
    finally:
        s.close()


def serve(brand, batch_paths, port=None, open_browser=True):
    """Run the review page until it is stopped with Ctrl+C. Always on 127.0.0.1."""
    from werkzeug.serving import make_server

    app = create_app(brand, batch_paths)
    store = app.config["REVIEW_STORE"]
    port = pick_port(port or DEFAULT_PORT)
    url = "http://%s:%d/" % (HOST, port)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)     # no request log scrolling past the person
    server = make_server(HOST, port, app, threaded=True)
    # flush: when Claude starts this in the background there is no terminal, and an unflushed
    # line would leave both of them waiting for an address that was never shown.
    print("The review page for %s is open at %s" % (store.brand.name, url), flush=True)
    for path in store.files:
        print("  reviewing: %s" % os.path.basename(path), flush=True)
    print("It runs on this computer only and sends nothing anywhere. Press Ctrl+C here when you are done.",
          flush=True)
    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("\nThe review page is closed. Everything you approved is saved in the batch.", flush=True)
    return 0
