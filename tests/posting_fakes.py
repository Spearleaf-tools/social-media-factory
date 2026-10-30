"""Shared helpers for the sending, shorts and test-and-promote tests.

Built ON the fake scheduling service in tests/test_posting.py rather than beside it: the same
FakeResponse, the same record of every request, the same "fail the next post" switch. This adds
what a whole send needs: uploads, a calendar kept per account, results, and a way to fail AFTER
the service accepted a post. Every account, id, response and number in here is invented.
"""
from __future__ import annotations

import copy
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from collections import defaultdict
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                    # noqa: E402
from smf.posting.metricool import CONNECTED_FIELD, Metricool              # noqa: E402
from smf.posting.provider import Transport                                # noqa: E402
from smf.studio import posts as P                                         # noqa: E402
from smf.studio.review.store import ACKNOWLEDGED_NOTE                     # noqa: E402
from tests.test_brands import BAKERY, CLINIC                              # noqa: E402
from tests.test_posting import FakeResponse, FakeService                  # noqa: E402

ACCOUNTS = [
    {"id": 101, "label": "Invented Bakery", "instagram": "invented.bakery", "facebookPageId": "000111",
     "tiktok": "invented.bakery", "youtube": "UC-invented", "linkedinCompany": "invented-bakery"},
    {"id": 102, "label": "Invented Bakery Shop", "facebookPageId": "000222", "instagram": "invented.shop",
     "tiktok": "invented.shop"},
    {"id": 555, "label": "Invented Clinic", "instagram": "invented.clinic", "tiktok": "invented.clinic"},
]


def http_error(code, body=b'{"error":"invented"}'):
    return urllib.error.HTTPError("https://app.metricool.com/api/x", code, "invented", {}, io.BytesIO(body))


class Service(FakeService):
    """The fake scheduling service, with a calendar per account."""

    def __init__(self, accounts=None):
        FakeService.__init__(self)
        self.accounts = copy.deepcopy(ACCOUNTS if accounts is None else accounts)
        self.calendar = defaultdict(list)           # account id (text) -> entries
        self.accepted = []                          # (account id, request body) for every post it took
        self.uploads = []                           # account ids that asked to upload
        self.results = defaultdict(list)            # (account id, platform) -> result rows
        self.accept_then_fail_with = None           # raise this AFTER taking the next post
        self.calendar_is_down = False
        self.order = []                             # "upload" / "post", in the order they happened

    def __call__(self, req, timeout=None):
        method, url = req.get_method(), req.full_url
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        account = (query.get("blogId") or [""])[0]
        self.requests.append((method, url.split("?")[0]))
        if "/admin/profiles-auth" in url:
            return FakeResponse(self.accounts)
        if "/v2/media/s3/upload-transactions" in url:
            if method == "PUT":
                self.uploads.append(account)
                self.order.append("upload")
                n = len(self.uploads)
                return FakeResponse({"data": {"uploadType": "SIMPLE", "presignedUrl": "https://storage.invalid/put/%d" % n,
                                              "fileUrl": "https://media.invalid/%s/%d" % (account, n)}})
            return FakeResponse({"data": {"fileUrl": json.loads(req.data.decode("utf-8"))["simple"]["fileUrl"]}})
        if url.startswith("https://storage.invalid/"):
            return FakeResponse(b"", headers={"ETag": '"invented"'})
        if "/v2/scheduler/posts" in url and method == "GET":
            if self.calendar_is_down:
                raise http_error(503)
            return FakeResponse({"data": list(self.calendar[account])})
        if "/v2/scheduler/posts" in url and method == "POST":
            if self.fail_next_post_with is not None:
                exc, self.fail_next_post_with = self.fail_next_post_with, None
                raise exc
            body = json.loads(req.data.decode("utf-8"))
            entry = {"id": 9000 + len(self.accepted), "text": body["text"], "publicationDate": body["publicationDate"],
                     "providers": [dict(p, status="PENDING") for p in body["providers"]], "draft": body["draft"]}
            self.calendar[account].append(entry)
            self.accepted.append((account, body))
            self.order.append("post")
            if self.accept_then_fail_with is not None:
                exc, self.accept_then_fail_with = self.accept_then_fail_with, None
                raise exc
            return FakeResponse({"data": {"id": entry["id"]}})
        for platform in ("tiktok", "threads"):
            if "/v2/analytics/posts/%s" % platform in url:
                return FakeResponse({"data": list(self.results[(account, platform)])})
        for platform, tail in (("instagram", "/stats/instagram/posts"), ("facebook", "/stats/facebook/posts"),
                               ("linkedin", "/stats/linkedin/posts"), ("twitter", "/stats/twitter/posts"),
                               ("youtube", "/stats/youtube/videos")):
            if tail in url:
                return FakeResponse(list(self.results[(account, platform)]))
        raise AssertionError("unexpected request %s %s" % (method, url))

    def accounts_posted_to(self):
        return sorted({account for account, _body in self.accepted})


def _linked(answers):
    """The brand's answers with every linked account carrying the page or profile the fake service
    says it points at, so the fixtures look like a brand whose accounts were linked properly."""
    data = copy.deepcopy(answers)
    for t in (data.get("accounts") or {}).get("targets") or []:
        if t.get("provider_brand_id") is not None and "destination" not in t:
            where = destination(t["provider_brand_id"], t["platform"])
            if where:
                t["destination"] = where
    return data


def brand_answers(base, targets=None, video=None, **extra):
    data = copy.deepcopy(base)
    if targets is not None:
        data["accounts"]["targets"] = targets
    if video is not None:
        data["video"] = video
    data.update(extra)
    return data


def destination(account, platform, accounts=None):
    """Where the fake service says one account's network points, the way the real listing reports
    it. This is what the accounts step writes down when a person links an account."""
    for a in (ACCOUNTS if accounts is None else accounts):
        if a.get("id") == account:
            return str(a.get(CONNECTED_FIELD.get(platform, platform)) or "")
    return ""


def target(identity, platform, account, connected=True, where=None):
    """One `accounts.targets` entry, as `accounts.build_targets` would have written it: the
    account's id AND the page or profile the service said that network pointed at. Pass
    where="" for a link saved before the Factory kept that note."""
    t = {"identity": identity, "platform": platform, "connected": connected}
    if account is not None:
        t["provider_brand_id"] = account
        where = destination(account, platform) if where is None else where
        if where:
            t["destination"] = where
    return t


def approve(post, facts_checked=True):
    """What the review page does when a person approves a post."""
    post.status = "approved"
    post.approved_at = "2029-12-01T09:00:00Z"
    if facts_checked:
        post.sourcing = "passed"
    else:
        post.feedback = "%s (2029-12-01T09:00:00Z)." % ACKNOWLEDGED_NOTE
    post.approved_text_sha = P.approval_sha(post)
    return post


def approve_batch(brand, path, facts_checked=True):
    posts, meta = P.load_batch(path, brand.id)
    for p in posts:
        approve(p, facts_checked)
    P.save_batch(posts, path, meta)
    return posts


def statuses(brand, path):
    return {p.id: p.status for p in P.load_batch(path, brand.id)[0]}


# ----------------------------------------------------------------------------- invented video files
def _box(kind, payload):
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def video_bytes(width, height, seconds, turned=False, filler=64):
    """The smallest file a player would recognise as a video of this size and length: a header
    with no pictures in it. `turned` stores it sideways with a quarter-turn, the way a phone does."""
    mvhd = struct.pack(">IIIII", 0, 0, 0, 1000, int(seconds * 1000)) + b"\x00" * 80
    matrix = (0, 0x10000, 0, -0x10000, 0, 0, 0, 0, 0x40000000) if turned else (0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    tkhd = (struct.pack(">IIIIII", 0, 0, 0, 1, 0, int(seconds * 1000)) + b"\x00" * 8 + struct.pack(">hhhh", 0, 0, 0, 0)
            + struct.pack(">9i", *matrix) + struct.pack(">II", width << 16, height << 16))
    hdlr = struct.pack(">II4s", 0, 0, b"vide") + b"\x00" * 12 + b"invented\x00"
    moov = _box(b"moov", _box(b"mvhd", mvhd) + _box(b"trak", _box(b"tkhd", tkhd) + _box(b"mdia", _box(b"hdlr", hdlr))))
    return _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2") + moov + _box(b"mdat", b"\x00" * filler)


def drop_video(folder, name, words=None, width=1080, height=1920, seconds=42, turned=False, **per_platform):
    """Put an invented video in a folder, with its description beside it when `words` is given.
    `per_platform` writes platform files: linkedin="..." -> <name>.linkedin.txt"""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(video_bytes(width, height, seconds, turned, filler=64 + len(name)))
    stem = os.path.splitext(name)[0]
    if words is not None:
        Path(folder, stem + ".txt").write_text(words, encoding="utf-8")
    for platform, text in per_platform.items():
        Path(folder, "%s.%s.txt" % (stem, platform)).write_text(text, encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- the base case
class SendCase(unittest.TestCase):
    """Two invented brands on one computer, one fake service, and a hostile folder name."""

    BAKERY_ANSWERS = BAKERY
    CLINIC_ANSWERS = CLINIC

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sending ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.bakery = brands.create("maple-and-main", "Maple & Main Bakery", _linked(self.BAKERY_ANSWERS))
        self.clinic = brands.create("stride-physio", "Stride Physio", _linked(self.CLINIC_ANSWERS))
        self.service = Service()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def provider(self, allow_writes=False):
        return Metricool(Transport(allow_writes=allow_writes, opener=self.service), token="t" * 12, user_id="42")

    def card(self, brand, name="card.png"):
        path = brand.path("Output", "visuals", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"an invented picture " + name.encode("utf-8"))
        return "Output/visuals/" + name

    def post(self, brand, pid="p1", text="Rye is out at seven.", when="2030-01-05T15:00:00Z", identity="person",
             platform="instagram", media=None, approved=True, **kw):
        media = [self.card(brand)] if media is None else media
        p = P.Post(id=pid, brand=brand.id, identity=identity, platform=platform, text=text,
                   scheduled_time_iso=when, media_paths=media, **kw)
        return approve(p) if approved else p

    def batch(self, brand, posts, name="week-1.json"):
        return P.save_batch(posts, brand.path("Output", "batches", name))

    def writes(self):
        return list(self.service.writes)
