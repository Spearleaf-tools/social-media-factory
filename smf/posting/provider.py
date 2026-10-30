"""provider.py - the one doorway to any scheduling service, and the rule that a dry run is dry.

Everything above this file (planning, review, the ledger, results) talks to a PostingProvider.
Metricool is the first provider. Adding another scheduler later means adding one file that
implements this interface; nothing else changes.

THE DRY-RUN RULE
A dry run makes ZERO mutating network requests: no upload, no draft, no schedule, no delete.
That is enforced here, in the transport every provider must use, not in a skill or a flag a
caller might forget. `Transport(allow_writes=False)` raises DryRunViolation the moment anything
other than a read is attempted, and the test suite runs whole dry runs against it.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from smf import keys

READ_METHODS = frozenset({"GET", "HEAD"})


class ProviderError(Exception):
    """Something the person can act on. `kind` says what sort of problem it is."""

    def __init__(self, message, kind="error", definitive=True):
        Exception.__init__(self, message)
        self.kind = kind                  # not-configured | unauthorized | no-api-access | not-connected
        #                                   | rejected | network | server | error
        self.definitive = definitive      # True: the service certainly did NOT accept the request


class DryRunViolation(Exception):
    """A write was attempted during a dry run. This is a bug in the caller, never a user error."""


class Transport(object):
    """HTTP with one rule: reads are always allowed, writes only when allow_writes is True."""

    def __init__(self, allow_writes=False, timeout=120, opener=None):
        self.allow_writes = bool(allow_writes)
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self.writes = 0
        self.reads = 0

    def request(self, method, url, headers=None, body=None, raw_body=None, timeout=None):
        method = method.upper()
        if method not in READ_METHODS and not self.allow_writes:
            raise DryRunViolation("%s attempted during a dry run" % method)
        # A key with a line break in it makes Python's own error quote the whole key. Refuse it here,
        # in a fixed sentence, before there is a request for anything to go wrong with.
        for v in (headers or {}).values():
            broken = keys.damaged(v)
            if broken:
                raise ProviderError(broken, "not-configured")
        if method in READ_METHODS:
            self.reads += 1
        else:
            self.writes += 1
        data = raw_body if raw_body is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if body is not None and raw_body is None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._open(req, timeout=timeout or self.timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            detail = keys.redact(e.read().decode("utf-8", "replace"))[:600]      # hide keys first, shorten second
            if e.code in (401, 403):
                raise ProviderError("The service refused the key (HTTP %d). %s" % (e.code, detail), "unauthorized")
            if 400 <= e.code < 500:
                raise ProviderError("The service rejected the request (HTTP %d). %s" % (e.code, detail), "rejected")
            # 5xx: the service may or may not have acted on it
            raise ProviderError("The service had a problem (HTTP %d). %s" % (e.code, detail), "server", definitive=False)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            # For a write we cannot know whether it arrived. For a read it does not matter.
            raise ProviderError("Could not reach the service (%s)." % keys.redact(str(e)), "network",
                                definitive=(method in READ_METHODS))
        except AssertionError:
            raise                                     # a test double objecting, not the service
        except Exception as e:
            # Anything else the request machinery throws. Its message is NOT repeated, even redacted:
            # Python quotes a bad header with its line breaks written out, which no longer matches
            # the key that redact() looks for. The kind of problem is enough to go on.
            raise ProviderError("Something unexpected went wrong while talking to the service (%s)."
                                % keys.redact(type(e).__name__), "error", definitive=(method in READ_METHODS))


class PostingProvider(object):
    """What any scheduling service must offer. All methods raise ProviderError in plain words."""

    name = "none"

    def list_accounts(self):
        """[{provider_brand_id, label, networks: [platform, ...]}] for the key's account. Read."""
        raise NotImplementedError

    def upload(self, local_path, provider_brand_id, expect_sha256=None):
        """Upload one media file, return its hosted URL. Write.
        `expect_sha256` is the fingerprint of the file the person approved: hash the bytes you
        actually read and refuse with ProviderError(kind="media-changed") if they differ."""
        raise NotImplementedError

    def schedule(self, post, provider_brand_id, media_urls, timezone):
        """Schedule one post, return the provider's post id as a string. Write."""
        raise NotImplementedError

    def calendar(self, provider_brand_id, start_iso, end_iso, timezone):
        """[{id, text, network, when, status, draft}] scheduled/published in the window. Read."""
        raise NotImplementedError

    def metrics(self, provider_brand_id, platform, start_date, end_date, timezone):
        """[{post_id, published_at, url, text, views, likes, comments, shares, saves, ...}]. Read."""
        raise NotImplementedError
