"""metricool.py - the Metricool provider.

Needs two values from the keys file: METRICOOL_USER_TOKEN and METRICOOL_USER_ID. Metricool only
offers its API on the Advanced plan and above, so a valid login on a smaller plan is still
refused; that case gets its own plain message instead of a generic "unauthorized".

Metricool's own vocabulary, for anyone reading the API docs next to this file: a "brand" there is
called a blog and has a blogId; networks are lowercase provider names; scheduled times are LOCAL
wall-clock time plus a separate timezone name, never an offset and never a trailing Z.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

from smf import keys
from smf.posting.provider import PostingProvider, ProviderError, Transport

BASE = "https://app.metricool.com/api"
S3_MIN_PART = 5 * 1024 * 1024
CHUNK = 8 * 1024 * 1024

# Factory platform name -> Metricool network name
NETWORK = {"linkedin": "linkedin", "facebook": "facebook", "instagram": "instagram", "twitter": "twitter",
           "tiktok": "tiktok", "youtube": "youtube", "threads": "threads", "bluesky": "bluesky",
           "pinterest": "pinterest", "gmb": "gmb"}
# The field on a Metricool brand that proves a network is really connected.
CONNECTED_FIELD = {"twitter": "twitter", "facebook": "facebookPageId", "instagram": "instagram",
                   "linkedin": "linkedinCompany", "gmb": "gmb", "pinterest": "pinterest", "tiktok": "tiktok",
                   "youtube": "youtube", "threads": "threads", "bluesky": "bluesky"}
# Post-level results. `dialect` picks the date parameters the endpoint expects.
METRICS = {
    "instagram": ("v1", "/stats/instagram/posts", {"post_id": ["postId"], "published_at": ["created"], "url": ["url"],
                  "text": ["content"], "views": ["views", "videoViewsTotal", "videoViews"], "likes": ["likes"],
                  "comments": ["comments"], "shares": ["shares"], "saves": ["saved"], "reach": ["reach"],
                  "impressions": ["impressionsTotal", "impressions"]}),
    "facebook": ("v1", "/stats/facebook/posts", {"post_id": ["postId"], "published_at": ["created"],
                 "url": ["permalinkUrl", "link"], "text": ["text"], "views": ["videoViews", "totalMediaViewUnique"],
                 "likes": ["reactions", "like"], "comments": ["comments"], "shares": ["shares"],
                 "reach": ["impressionsUnique"], "impressions": ["impressions"], "clicks": ["clicks"]}),
    "linkedin": ("v1", "/stats/linkedin/posts", {"post_id": ["postId", "id"], "published_at": ["created", "date"],
                 "url": ["url", "permalinkUrl", "link"], "text": ["text", "content"], "views": ["views", "impressions"],
                 "likes": ["likes", "reactions"], "comments": ["comments"], "shares": ["shares"],
                 "impressions": ["impressions"], "clicks": ["clicks"]}),
    "twitter": ("v1", "/stats/twitter/posts", {"post_id": ["postId", "id"], "published_at": ["created", "date"],
                "url": ["url"], "text": ["text", "content"], "views": ["impressions", "views"],
                "likes": ["likes", "favorites"], "comments": ["replies", "comments"],
                "shares": ["retweets", "shares"], "impressions": ["impressions"], "clicks": ["clicks"]}),
    "youtube": ("v1", "/stats/youtube/videos", {"post_id": ["videoId"], "published_at": ["publishedAt"],
                "url": ["watchUrl"], "text": ["title"], "views": ["views"], "likes": ["likes"],
                "comments": ["comments"], "shares": ["shares"], "watch_minutes": ["watchMinutes"]}),
    "tiktok": ("v2", "/v2/analytics/posts/tiktok", {"post_id": ["videoId"], "published_at": ["createTime"],
               "url": ["shareUrl"], "text": ["videoDescription", "title"], "views": ["viewCount"],
               "likes": ["likeCount"], "comments": ["commentCount"], "shares": ["shareCount"]}),
    "threads": ("v2", "/v2/analytics/posts/threads", {"post_id": ["id", "postId"],
                "published_at": ["createTime", "created"], "url": ["permalink", "url"], "text": ["text", "content"],
                "views": ["views"], "likes": ["likes"], "comments": ["replies"], "shares": ["reposts"]}),
}


def local_wall_clock(iso, tz):
    """Any ISO time -> Metricool's bare local 'YYYY-MM-DDTHH:MM:SS' in `tz`.
    A time with an offset or a Z is CONVERTED into the zone, never just trimmed: trimming a UTC
    time would schedule the post hours off. A time with no offset is taken as already local."""
    s = (iso or "").strip()
    if not s or "T" not in s:
        raise ProviderError("the post has no usable scheduled time", "rejected")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise ProviderError("the post's scheduled time is not a valid date", "rejected")
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo(tz))
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _sha256_b64(chunk):
    return base64.b64encode(hashlib.sha256(chunk).digest()).decode()


def _destination(value):
    """What the service says a network is connected to, as text that compares the same every time."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value).strip()


class Metricool(PostingProvider):
    name = "metricool"

    def __init__(self, transport=None, token=None, user_id=None):
        keys.load()
        self.token = token or os.environ.get("METRICOOL_USER_TOKEN") or ""
        self.user_id = user_id or os.environ.get("METRICOOL_USER_ID") or ""
        if not self.token or not self.user_id:
            missing = [n for n, v in (("METRICOOL_USER_TOKEN", self.token), ("METRICOOL_USER_ID", self.user_id)) if not v]
            raise ProviderError("Posting is not set up yet: %s missing from the keys file. Metricool shows both "
                                "under Account settings > API (the Advanced plan or higher is needed)."
                                % " and ".join(missing), "not-configured")
        self.transport = transport or Transport(allow_writes=False)

    # ---------------------------------------------------------------- plumbing
    def _call(self, method, path, params=None, body=None, brand_id=None):
        q = {"userId": self.user_id}
        if brand_id is not None:
            q["blogId"] = str(brand_id)
        q.update({k: str(v) for k, v in (params or {}).items() if v is not None})
        url = "%s%s?%s" % (BASE, path, urllib.parse.urlencode(q))
        try:
            _status, _headers, raw = self.transport.request(
                method, url, headers={"X-Mc-Auth": self.token, "Accept": "application/json"}, body=body)
        except ProviderError as e:
            if e.kind == "unauthorized":
                raise ProviderError(
                    "Metricool refused the key. Either the token or the user id is wrong, or the Metricool plan "
                    "does not include the API (it needs Advanced or higher). Check Account settings > API.",
                    "no-api-access")
            raise
        if not raw:
            return None
        try:
            out = json.loads(raw)
        except ValueError:
            # For a write, the service may have acted before it answered with something unreadable.
            raise ProviderError("Metricool's answer could not be read, so it is unclear what it did.", "server",
                                definitive=(method.upper() in ("GET", "HEAD")))
        if isinstance(out, dict) and "data" in out and set(out) <= {"data", "metadata", "page"}:
            return out["data"]
        return out

    # ---------------------------------------------------------------- reads
    def list_accounts(self):
        """`destinations` is what the service says each connected network points AT: the value of
        the same field that proves the connection (a page id, a channel id, a handle). A profile
        keeps its id when someone reconnects it to a different page, so the id alone cannot show
        that a brand's posts would now land somewhere else. This value can."""
        listed = self._call("GET", "/admin/profiles-auth")
        if not isinstance(listed, list) or not all(isinstance(b, dict) for b in listed):
            raise ProviderError("Metricool's list of accounts came back empty or in a shape the Factory does not "
                                "know, so the accounts could not be checked. Try again in a few minutes.", "server")
        out = []
        for b in listed:
            where = {p: _destination(b[field]) for p, field in CONNECTED_FIELD.items() if b.get(field)}
            out.append({"provider_brand_id": b.get("id"), "label": b.get("label") or str(b.get("id")),
                        "networks": sorted(where), "destinations": where})
        return out

    def calendar(self, provider_brand_id, start_iso, end_iso, timezone):
        posts = self._call("GET", "/v2/scheduler/posts", brand_id=provider_brand_id,
                           params={"start": start_iso, "end": end_iso, "timezone": timezone})
        # No answer, or an answer in an unknown shape, is NOT an empty calendar. Whoever asked is
        # about to decide whether a post went out, and "nothing came back" proves nothing.
        if not isinstance(posts, list) or not all(isinstance(p, dict) for p in posts):
            raise ProviderError("Metricool's calendar came back empty or in a shape the Factory does not know, so "
                                "it could not be checked. Nothing was changed. Try again in a few minutes.", "server")
        out = []
        for p in posts:
            providers = [x for x in (p.get("providers") or []) if isinstance(x, dict)]
            published = p.get("publicationDate")
            out.append({"id": str(p.get("id", "")), "text": p.get("text") or "",
                        "network": ",".join(x.get("network", "") for x in providers),
                        "when": published.get("dateTime", "") if isinstance(published, dict) else "",
                        "status": ",".join(sorted({str(x.get("status", "")) for x in providers})),
                        "detail": "; ".join(str(x.get("detailedStatus") or "") for x in providers if x.get("detailedStatus")),
                        "draft": bool(p.get("draft"))})
        return out

    def metrics(self, provider_brand_id, platform, start_date, end_date, timezone):
        if platform not in METRICS:
            return []
        dialect, path, fields = METRICS[platform]
        if dialect == "v1":
            params = {"start": start_date.replace("-", ""), "end": end_date.replace("-", ""), "timezone": timezone}
        else:
            params = {"from": start_date + "T00:00:00", "to": end_date + "T23:59:59", "timezone": timezone}
        rows = self._call("GET", path, brand_id=provider_brand_id, params=params) or []
        out = []
        for rec in rows:
            row = {"platform": platform}
            for name, candidates in fields.items():
                row[name] = next((rec[k] for k in candidates if rec.get(k) not in (None, "")), None)
            out.append(row)
        return out

    # ---------------------------------------------------------------- writes
    def upload(self, local_path, provider_brand_id, expect_sha256=None):
        """`expect_sha256` is the fingerprint of the file the person approved. The bytes read here
        are the bytes that are sent, so they are the ones checked against it, and a file that was
        swapped a moment ago is refused before a single request is made."""
        if not os.path.isfile(local_path):
            raise ProviderError("an attached file is missing: %s" % os.path.basename(local_path), "rejected")
        with open(local_path, "rb") as f:
            blob = f.read()
        if not blob:
            raise ProviderError("an attached file is empty: %s" % os.path.basename(local_path), "rejected")
        if expect_sha256 and hashlib.sha256(blob).hexdigest() != expect_sha256:
            raise ProviderError("'%s' changed after it was approved" % os.path.basename(local_path), "media-changed")
        ctype = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
        size = len(blob)
        part_size = CHUNK if size > S3_MIN_PART else size
        parts = [{"size": min(s + part_size, size) - s, "startByte": s, "endByte": min(s + part_size, size),
                  "hash": _sha256_b64(blob[s:min(s + part_size, size)])} for s in range(0, size, part_size)]
        ext = os.path.splitext(local_path)[1].lstrip(".").lower()
        tx = self._call("PUT", "/v2/media/s3/upload-transactions", brand_id=provider_brand_id,
                        body={"resourceType": "planner", "contentType": ctype, "fileExtension": ext, "parts": parts})
        if tx.get("uploadType") == "SIMPLE":
            self._put_storage(tx["presignedUrl"], blob, ctype, parts[0]["hash"])
            done = self._call("PATCH", "/v2/media/s3/upload-transactions", brand_id=provider_brand_id,
                              body={"simple": {"fileUrl": tx["fileUrl"]}})
        else:
            completed = []
            for part in tx["parts"]:
                chunk = blob[part["startByte"]:part["endByte"]]
                etag = self._put_storage(part["presignedUrl"], chunk, ctype, _sha256_b64(chunk))
                completed.append({"partNumber": part["partNumber"], "etag": etag})
            done = self._call("PATCH", "/v2/media/s3/upload-transactions", brand_id=provider_brand_id,
                              body={"multipart": {"uploadId": tx["uploadId"], "key": tx["key"], "parts": completed}})
        url = (done or {}).get("convertedFileUrl") or (done or {}).get("fileUrl") or tx.get("fileUrl")
        if not url:
            raise ProviderError("the upload finished but no link came back", "server", definitive=False)
        return url

    def _put_storage(self, url, chunk, content_type, sha_b64):
        # The signed link covers content-length, content-type, host and the checksum header.
        # Leave one out and storage answers "signature does not match", which looks like a bad key
        # and is not.
        _s, headers, _b = self.transport.request(
            "PUT", url, raw_body=chunk, timeout=600,
            headers={"Content-Type": content_type, "Content-Length": str(len(chunk)),
                     "x-amz-checksum-sha256": sha_b64})
        return (headers.get("ETag") or headers.get("Etag") or "").strip('"')

    def build_body(self, post, media_urls, timezone):
        """The exact request for one post. Separate from schedule() so tests and dry runs can show it."""
        network = NETWORK.get(post.platform)
        if not network:
            raise ProviderError("Metricool cannot post to %s" % post.platform, "rejected")
        when = local_wall_clock(post.scheduled_time_iso, timezone)
        body = {"text": post.text or "", "publicationDate": {"dateTime": when, "timezone": timezone},
                "providers": [{"network": network}], "draft": False, "autoPublish": True}
        if media_urls:
            body["media"] = list(media_urls)
            body["saveExternalMediaFiles"] = True
        if post.first_comment:
            body["firstCommentText"] = post.first_comment
        if network == "youtube":
            body["youtubeData"] = {"title": (post.text or "").splitlines()[0][:100] if post.text else "",
                                   "privacy": "public", "madeForKids": False,
                                   "type": "video" if post.media_type == "video" else "short"}
        elif network == "tiktok":
            body["tiktokData"] = {"privacyOption": "PUBLIC_TO_EVERYONE", "disableComment": False,
                                  "disableDuet": False, "disableStitch": False}
        elif network == "instagram" and post.media_type in ("reel", "story"):
            body["instagramData"] = {"type": post.media_type.upper(), "showReelOnFeed": True}
        if post.thread:
            body["descendants"] = [{"text": seg, "publicationDate": {"dateTime": when, "timezone": timezone},
                                    "providers": [{"network": network}]} for seg in post.thread]
        return body

    def schedule(self, post, provider_brand_id, media_urls, timezone):
        res = self._call("POST", "/v2/scheduler/posts", brand_id=provider_brand_id,
                         body=self.build_body(post, media_urls, timezone))
        if not res or not res.get("id"):
            raise ProviderError("Metricool answered without a post id, so it is unclear whether it was scheduled",
                                "server", definitive=False)
        return str(res["id"])
