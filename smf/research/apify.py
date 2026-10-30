"""apify.py - the one doorway to Apify, and the rules that keep research cheap and predictable.

Apify rents out small programs called actors. Each actor collects one kind of public data and
charges a fraction of a cent per result. All research in the Factory goes through this file, and
everything that is specific to one actor lives in `apify_actors.json` beside it.

FOUR RULES, enforced here so that no job and no skill can forget them

1. The cost is said first. Every run prints its estimate before anything else happens.
2. Nothing is spent without a yes. `run()` refuses unless it is called with `confirm=True`, and,
   separately, the transport refuses to START a run unless it was built to allow it. Looking
   things up (is this actor alive, is that run finished, fetch the results) is free and always
   allowed; starting a run is the only thing that costs money. A dry run starts nothing.
3. Every run has a hard cap, three ways:
     - the actor is told the limit in its own input (and the input list is trimmed to fit);
     - Apify is told the most the run may charge, in dollars. This is the one that protects the
       wallet if an actor ignores its own limit, because Apify enforces it, not the actor;
     - whatever comes back is trimmed to the cap again on this computer.
   A run is also given a time limit, because several actors have none of their own.
4. A key is never shown. The token travels in a header, never in a web address, and every
   message is scrubbed of it before it is raised or printed.

An actor that has been renamed, removed, repriced or reshaped is reported as "needs attention"
with the name of the entry to fix. It is never a crash.
"""
from __future__ import annotations

import copy
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from smf import keys

API = "https://api.apify.com/v2"
REGISTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apify_actors.json")
REGISTRY_NAME = "smf/research/apify_actors.json"
TOKEN_NAME = "APIFY_API_TOKEN"

READ_METHODS = frozenset({"GET", "HEAD"})
FINISHED = frozenset({"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"})
DEFAULT_WAIT_SECS = 600          # how long one run may take before it is stopped
SYNC_LIMIT_SECS = 290            # Apify's one-request endpoint gives up at 300 seconds
LOWEST_CEILING_USD = 0.10
PRICE_DRIFT = 0.25               # live price this far from the estimate = the entry is stale
EMPTY = (None, "", [], {})


class ApifyError(Exception):
    """Something the person can act on. `kind` says what sort of problem it is."""

    def __init__(self, message, kind="error", definitive=True):
        Exception.__init__(self, message)
        self.kind = kind                # not-configured | unauthorized | out-of-credit | not-allowed
        #                                 | needs-attention | timeout | rate-limited | run-failed
        #                                 | refused | not-confirmed | network | server | error
        self.definitive = definitive    # False: a run MAY have started; check before retrying


class NotConfirmed(ApifyError):
    """run() was called without confirm=True. Carries the plan so the caller can show it."""

    def __init__(self, plan):
        ApifyError.__init__(self, "Nothing was run and nothing was spent. %s Say yes to go ahead."
                            % plan["estimate"]["text"], "not-confirmed")
        self.plan = plan


class DryRunViolation(Exception):
    """Something tried to start a run during a dry run. A bug in the caller, never a user error."""


class _HttpProblem(Exception):
    def __init__(self, status, error_type, message):
        Exception.__init__(self, message)
        self.status, self.error_type, self.message = status, error_type, message


class Transport(object):
    """HTTP with one rule: lookups are always allowed, starting anything only when allow_runs is True."""

    def __init__(self, allow_runs=False, timeout=90, opener=None):
        self.allow_runs = bool(allow_runs)
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self.reads = 0
        self.starts = 0

    def request(self, method, url, headers=None, body=None, timeout=None):
        method = method.upper()
        if method in READ_METHODS:
            self.reads += 1
        else:
            if not self.allow_runs:
                raise DryRunViolation("%s attempted during a dry run" % method)
            self.starts += 1
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._open(req, timeout=timeout or self.timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            # Kept whole on purpose. Hiding a key replaces the WHOLE value, so shortening first can
            # cut a key in half and leave a piece behind that no longer matches. The only shortening
            # happens in _explain(), after the text has been scrubbed.
            raw = e.read().decode("utf-8", "replace")
            etype, message = "", raw
            try:
                err = (json.loads(raw) or {}).get("error") or {}
                etype, message = str(err.get("type") or ""), str(err.get("message") or raw)
            except (ValueError, AttributeError):
                pass
            raise _HttpProblem(e.code, etype, message)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise _HttpProblem(0, "network", str(e))
        except AssertionError:
            raise                                     # a test double objecting, not the service
        except Exception as e:
            # Anything else the request machinery throws. Only its kind is kept: its own words can
            # quote a header, and a header holds the key.
            raise _HttpProblem(0, "network", type(e).__name__)


# ----------------------------------------------------------------------------- the registry
def load_registry(path=None):
    """Read the actor table. A damaged table is a plain error, not a traceback."""
    try:
        with open(path or REGISTRY, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except OSError:
        raise ApifyError("The list of research tools (%s) is missing." % REGISTRY_NAME, "needs-attention")
    except ValueError as e:
        raise ApifyError("The list of research tools (%s) is damaged and cannot be read (%s)."
                         % (REGISTRY_NAME, e), "needs-attention")
    jobs = data.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ApifyError("The list of research tools (%s) has no jobs in it." % REGISTRY_NAME, "needs-attention")
    return jobs


def money(usd):
    """Dollars the way a person says them. Tiny amounts are not given false precision."""
    usd = float(usd or 0)
    if usd <= 0:
        return "nothing"
    if usd < 0.01:
        return "less than 1 cent"
    if usd < 1:
        cents = int(math.ceil(usd * 100 - 1e-9))
        return "about %d cent%s" % (cents, "" if cents == 1 else "s")
    return "about $%.2f" % usd


def dig(item, path):
    """Follow 'a.b' into nested data. 'tags[].name' gathers `name` from every entry of `tags`."""
    node = item
    parts = path.split(".")
    for i, part in enumerate(parts):
        if part.endswith("[]"):
            seq = node.get(part[:-2]) if isinstance(node, dict) else None
            if not isinstance(seq, list):
                return None
            rest = ".".join(parts[i + 1:])
            found = [dig(x, rest) if rest else x for x in seq]
            return [x for x in found if x not in EMPTY]
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


# ----------------------------------------------------------------------------- the client
class Apify(object):
    def __init__(self, transport=None, token=None, allow_runs=False, registry=None, out=None):
        self.jobs = registry if registry is not None else load_registry()
        self.transport = transport or Transport(allow_runs=allow_runs)
        self._given_token = token
        self.out = out or print
        self._now = time.monotonic
        self._sleep = time.sleep

    # ------------------------------------------------------------ keys, and never showing one
    def _token(self):
        keys.load()
        token = self._given_token or os.environ.get(TOKEN_NAME) or ""
        if not token.strip():
            raise ApifyError(
                "Research is not set up yet: %s is missing from the keys file. Apify has a free plan with a "
                "small monthly credit, which is enough to try every research job. Make an account at apify.com, "
                "copy the API token from your account settings, and paste it into keys.env as %s=your-token."
                % (TOKEN_NAME, TOKEN_NAME), "not-configured")
        broken = keys.damaged(token.strip(), TOKEN_NAME)       # asked first: a bad header's own error quotes the key
        if broken:
            raise ApifyError(broken + " Nothing was run and nothing was spent.", "not-configured")
        return token.strip()

    def _scrub(self, text):
        text = str(text)
        token = (self._given_token or os.environ.get(TOKEN_NAME) or "").strip()
        if len(token) >= 6:
            text = text.replace(token, "[%s hidden]" % TOKEN_NAME)
        return keys.redact(text)

    # ------------------------------------------------------------ the registry
    def job(self, name):
        j = self.jobs.get(name)
        if not isinstance(j, dict) or not j.get("actor"):
            raise ApifyError("There is no research job called '%s'. Jobs here: %s."
                             % (name, ", ".join(sorted(self.jobs))), "refused")
        return j

    @staticmethod
    def _path_id(actor):
        return urllib.parse.quote(actor.replace("/", "~"), safe="~")

    # ------------------------------------------------------------ estimate and plan (no network)
    def estimate(self, job, n, options=()):
        j = self.job(job)
        n = max(0, int(n))
        per = float(j.get("est_usd_per_unit") or 0)
        for name in options or ():
            per += float(self._option(j, name).get("est_usd_per_unit") or 0)
        usd = float(j.get("est_usd_per_run") or 0) + per * n
        ceiling = max(LOWEST_CEILING_USD, float(j.get("min_ceiling_usd") or 0),
                      math.ceil((usd * 1.5 + 0.05) * 100 - 1e-9) / 100.0)
        unit = j.get("unit", "result")
        text = ("Estimated cost: %s for up to %d %s%s. This is an estimate from prices checked on %s, not a "
                "quote; the most this run can be charged is $%.2f, and Apify enforces that limit."
                % (money(usd), n, unit, "" if n == 1 else "s", j.get("checked", "an earlier date"), ceiling))
        return {"job": job, "actor": j["actor"], "units": n, "unit": unit, "usd": round(usd, 4),
                "ceiling_usd": round(ceiling, 2), "checked": j.get("checked"), "is_estimate": True, "text": text}

    @staticmethod
    def _option(j, name):
        opt = (j.get("options") or {}).get(name)
        if not isinstance(opt, dict):
            raise ApifyError("This job has no paid extra called '%s'. It offers: %s."
                             % (name, ", ".join(sorted(j.get("options") or {})) or "none"), "refused")
        return opt

    def plan(self, job, inputs, max_items=None, options=(), extra=None, wait_secs=None):
        """Everything a run WOULD do, worked out without touching the network."""
        j = self.job(job)
        cap = j.get("default_cap", 25) if max_items is None else max_items
        top = int(j.get("max_cap") or 500)
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
            raise ApifyError("A run needs a limit of at least 1. (Some tools treat 0 as 'no limit', so a limit "
                             "below 1 is never sent.)", "refused")
        if cap > top:
            raise ApifyError("The most this job collects in one run is %d. Ask for %d or fewer, or run it twice."
                             % (top, top), "refused")

        seen, clean = set(), []
        for raw in ([inputs] if isinstance(inputs, str) else list(inputs or [])):
            s = str(raw or "").strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                clean.append(s)
        if not clean:
            raise ApifyError("There is nothing to look up. Give at least one name, keyword or link.", "refused")

        notes = []
        body = copy.deepcopy(j.get("input_template") or {})
        allowed = set(j.get("allowed_inputs") or [])
        for k, v in (extra or {}).items():
            if v in EMPTY:
                continue
            if k not in allowed:
                raise ApifyError("'%s' is not a setting this job accepts, so nothing was run. It accepts: %s."
                                 % (k, ", ".join(sorted(allowed)) or "no extra settings"), "refused")
            body[k] = v
        for name in options or ():
            body.update(copy.deepcopy(self._option(j, name).get("set") or {}))

        field, scope = j.get("cap_field"), j.get("cap_scope", "total")
        if field is None:
            if len(clean) > cap:
                notes.append("Only the first %d of %d were kept, to stay inside the limit." % (cap, len(clean)))
            clean = clean[:cap]
            units = len(clean)
        elif scope == "per_input":
            if len(clean) > cap:
                notes.append("Only the first %d of %d were kept, to stay inside the limit." % (cap, len(clean)))
                clean = clean[:cap]
            each = max(1, cap // len(clean))
            body[field] = each
            units = each * len(clean)
        else:
            body[field] = cap
            units = cap

        body[j["inputs_field"]] = "\n".join(clean) if j.get("inputs_as") == "lines" else clean
        wait = int(wait_secs or j.get("wait_secs") or DEFAULT_WAIT_SECS)
        return {"job": job, "actor": j["actor"], "inputs": clean, "max_items": cap, "units": units,
                "options": list(options or ()), "actor_input": body, "wait_secs": wait, "notes": notes,
                "estimate": self.estimate(job, units, options)}

    # ------------------------------------------------------------ plumbing
    def _call(self, method, path, params=None, body=None, token=None, actor=None, timeout=None):
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token       # a header, never the address
        try:
            _status, _headers, raw = self.transport.request(method, url, headers=headers, body=body, timeout=timeout)
        except _HttpProblem as p:
            raise self._explain(p, method, actor)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise ApifyError("Apify answered with something unreadable. Try again in a minute.", "server",
                             definitive=(method in READ_METHODS))

    def _explain(self, p, method, actor):
        where = " (%s)" % actor if actor else ""
        fix = " This needs attention: update or replace its entry in %s." % REGISTRY_NAME
        detail = self._scrub(p.message)[:300]          # hide keys first, shorten second
        started = method not in READ_METHODS
        if p.status == 0:
            tail = (" It is unclear whether a run started. Look in the Apify console before trying again, so you "
                    "do not pay twice.") if started else ""
            return ApifyError("Could not reach Apify. Check the internet connection.%s" % tail, "network",
                              definitive=not started)
        if p.status == 401:
            return ApifyError("Apify did not accept the key. Check that %s in the keys file is the whole token from "
                              "your Apify account, with no spaces around it." % TOKEN_NAME, "unauthorized")
        if p.status == 402:
            return ApifyError("Your Apify account is out of credit, or this run would go past your spending limit. "
                              "Nothing was collected. Add credit on Apify's billing page, or wait for the free "
                              "monthly credit to renew.", "out-of-credit")
        if p.status == 403:
            return ApifyError("Apify would not let this account use that research tool%s. Some tools need a paid "
                              "Apify plan, or a one-time approval on the tool's own page." % where, "not-allowed")
        if p.status == 404:
            return ApifyError("The research tool for this job%s could not be found. It has probably been renamed "
                              "or removed.%s" % (where, fix), "needs-attention")
        if p.status == 400:
            return ApifyError("The research tool%s did not accept the request, which usually means its settings "
                              "have changed. Nothing was collected. (%s)%s" % (where, detail, fix), "needs-attention")
        if p.status == 408:
            return ApifyError("The run took too long and was stopped at the time limit. Try again with a smaller "
                              "limit.", "timeout")
        if p.status == 429:
            return ApifyError("Apify asked us to slow down. Wait a minute and try again.", "rate-limited")
        tail = " Look in the Apify console before trying again, so you do not pay twice." if started else ""
        return ApifyError("Apify had a problem of its own (HTTP %d).%s" % (p.status, tail), "server",
                          definitive=not started)

    # ------------------------------------------------------------ health (free, no key needed)
    def health(self, job):
        """Is this job's actor still there, still public, and still about the same price?
        A free lookup that needs no key. Never raises: the answer is always a plain report."""
        try:
            j = self.job(job)
        except ApifyError as e:
            return {"job": job, "actor": None, "state": "needs attention", "detail": str(e)}
        rep = {"job": job, "actor": j["actor"], "state": "ok", "detail": "found and open to use",
               "est_usd_per_unit": j.get("est_usd_per_unit"), "live_usd_per_unit": None, "repriced": False}
        try:
            data = (self._call("GET", "/acts/" + self._path_id(j["actor"]), actor=j["actor"]) or {}).get("data") or {}
        except ApifyError as e:
            rep["state"] = "needs attention" if e.kind == "needs-attention" else "could not check"
            rep["detail"] = str(e)
            return rep

        problems = []
        if data.get("isDeprecated"):
            problems.append("its maker has marked it as retired")
        if data.get("isPublic") is False:
            problems.append("it is no longer public")
        pricing = (data.get("pricingInfos") or [{}])[-1] or {}
        live = self._live_price(pricing, j)
        rep["live_usd_per_unit"] = live
        est = float(j.get("est_usd_per_unit") or 0)
        if live is None:
            rep["detail"] = "found and open to use (its live price could not be read, so the estimate is unchecked)"
        elif est > 0 and abs(live - est) / est > PRICE_DRIFT:
            rep["repriced"] = True
            if live > est:
                problems.append("its price has gone UP: now $%.5f per %s, the estimate assumes $%.5f"
                                % (live, j.get("unit", "result"), est))
            else:
                rep["detail"] = ("found and open to use (it is now cheaper than the estimate: $%.5f per %s)"
                                 % (live, j.get("unit", "result")))
        floor = pricing.get("minimalMaxTotalChargeUsd")
        if isinstance(floor, (int, float)) and floor > float(j.get("min_ceiling_usd") or 0) + 1e-9 \
                and floor > LOWEST_CEILING_USD:
            problems.append("it now refuses a spending limit under $%.2f; set min_ceiling_usd to match" % floor)
        if problems:
            rep["state"] = "needs attention"
            rep["detail"] = "; ".join(problems) + ". Update its entry in %s." % REGISTRY_NAME
        return rep

    @staticmethod
    def _live_price(pricing, j):
        events = ((pricing.get("pricingPerEvent") or {}).get("actorChargeEvents")) or {}
        if not isinstance(events, dict) or j.get("price_event") not in events:
            return None
        total = 0.0
        for name in [j["price_event"]] + list(j.get("price_addon_events") or []):
            ev = events.get(name)
            if not isinstance(ev, dict):
                return None
            tier = ((ev.get("eventTieredPricingUsd") or {}).get("FREE") or {}).get("tieredEventPriceUsd")
            price = tier if tier is not None else ev.get("eventPriceUsd")
            if not isinstance(price, (int, float)):
                return None
            total += float(price)
        return round(total, 6)

    def health_all(self):
        return [self.health(name) for name in self.jobs]

    # ------------------------------------------------------------ run (the only thing that costs money)
    def run(self, job, inputs, max_items=None, options=(), extra=None, confirm=False, mode="async",
            wait_secs=None):
        plan = self.plan(job, inputs, max_items, options, extra, wait_secs)
        self.out(plan["estimate"]["text"])                      # rule 1: the cost is said first
        for note in plan["notes"]:
            self.out(note)
        if confirm is not True:                                 # rule 2: nothing is spent without a yes
            raise NotConfirmed(plan)
        token = self._token()

        actor, cap = plan["actor"], plan["max_items"]
        limits = {"maxTotalChargeUsd": plan["estimate"]["ceiling_usd"]}
        if mode == "sync":
            raw, partial, run_id, warnings = self._run_sync(plan, token, limits)
        else:
            raw, partial, run_id, warnings = self._run_async(plan, token, limits)

        raw = [x for x in (raw or []) if isinstance(x, dict)]
        if len(raw) > cap:
            warnings.append("The tool returned %d, more than the limit of %d. The extra %d were dropped."
                            % (len(raw), cap, len(raw) - cap))
        raw = raw[:cap]                                         # rule 3, third layer
        items, coverage, more = self.normalise(job, raw)
        return {"job": job, "actor": actor, "ran": True, "items": items, "count": len(items),
                "partial": partial, "warnings": warnings + more, "coverage": coverage,
                "their_fields_seen": sorted(raw[0].keys()) if raw else [], "run_id": run_id,
                "estimated_usd": plan["estimate"]["usd"], "ceiling_usd": plan["estimate"]["ceiling_usd"],
                "inputs": plan["inputs"], "max_items": cap}

    def _run_sync(self, plan, token, limits):
        wait = min(plan["wait_secs"], SYNC_LIMIT_SECS)
        params = dict(limits, timeout=wait, clean="true", format="json", limit=plan["max_items"])
        data = self._call("POST", "/acts/%s/run-sync-get-dataset-items" % self._path_id(plan["actor"]),
                          params=params, body=plan["actor_input"], token=token, actor=plan["actor"],
                          timeout=wait + 30)
        return (data if isinstance(data, list) else []), False, None, []

    def _run_async(self, plan, token, limits):
        actor, wait = plan["actor"], plan["wait_secs"]
        started = self._call("POST", "/acts/%s/runs" % self._path_id(actor), params=dict(limits, timeout=wait),
                             body=plan["actor_input"], token=token, actor=actor)
        run = (started or {}).get("data") or {}
        run_id, dataset = run.get("id"), run.get("defaultDatasetId")
        if not run_id:
            raise ApifyError("Apify answered without a run number, so it is unclear whether the run started. Look "
                             "in the Apify console before trying again.", "server", definitive=False)

        deadline = self._now() + wait
        status = run.get("status") or "RUNNING"
        while status not in FINISHED:
            left = deadline - self._now()
            if left <= 0:
                break
            self._sleep(min(2.0, max(0.0, left)))
            seen = self._call("GET", "/actor-runs/%s" % urllib.parse.quote(str(run_id)),
                              params={"waitForFinish": int(max(1, min(30, left)))}, token=token, actor=actor,
                              timeout=60)
            run = (seen or {}).get("data") or run
            status = run.get("status") or status
            dataset = run.get("defaultDatasetId") or dataset

        warnings, partial = [], False
        if status not in FINISHED:
            self._stop(run_id, token, actor)
            status = "TIMED-OUT"
        if status != "SUCCEEDED":
            partial = True
        items = []
        if dataset:
            got = self._call("GET", "/datasets/%s/items" % urllib.parse.quote(str(dataset)),
                             params={"clean": "true", "format": "json", "limit": plan["max_items"]},
                             token=token, actor=actor)
            items = got if isinstance(got, list) else []
        if status == "SUCCEEDED":
            return items, False, run_id, warnings
        if not items:
            if status == "TIMED-OUT":
                raise ApifyError("The run took longer than %d seconds, so it was stopped before it returned "
                                 "anything. It cannot cost more than the limit shown above. Try again with a "
                                 "smaller limit." % wait, "timeout")
            raise ApifyError("The research tool (%s) started but stopped without returning anything. Most often "
                             "the account, channel or link does not exist or is private. If it keeps happening the "
                             "tool itself may be broken: run the actors check." % actor, "run-failed")
        warnings.append({"TIMED-OUT": "The run hit its time limit and was stopped. These are the results it had "
                                      "collected by then.",
                         "ABORTED": "The run was stopped early. These are the results it had collected by then.",
                         "FAILED": "The tool failed part-way. These are the results it had collected by then."}
                        .get(status, "The run did not finish cleanly."))
        return items, partial, run_id, warnings

    def _stop(self, run_id, token, actor):
        """Tell Apify to stop a run that has outlived its welcome, so it stops charging. Best effort."""
        try:
            self._call("POST", "/actor-runs/%s/abort" % urllib.parse.quote(str(run_id)), token=token, actor=actor,
                       timeout=30)
        except ApifyError:
            pass

    # ------------------------------------------------------------ their fields -> our fields
    def normalise(self, job, raw_items):
        """Rename the actor's fields to ours using the job's output_map. Returns
        (items, coverage, warnings). An actor that changes its output shape shows up here as a
        required field that no result has, and is reported as needing attention."""
        j = self.job(job)
        mapping = j.get("output_map") or {}
        required = list(j.get("required_fields") or [])
        items, coverage, unusable = [], {}, 0
        for raw in raw_items:
            out = {}
            for theirs, ours in mapping.items():
                if ours in out:
                    continue
                value = dig(raw, theirs)
                if value not in EMPTY:
                    out[ours] = value
            if required and not any(f in out for f in required):
                unusable += 1                       # an error row, or a row in a shape we cannot read
                continue
            for f in out:
                coverage[f] = coverage.get(f, 0) + 1
            items.append(out)

        warnings = []
        if raw_items and not items:
            warnings.append("needs attention: the tool (%s) returned %d rows but none could be read, so its output "
                            "has probably changed shape. Compare `their_fields_seen` in this run's record with the "
                            "output_map for '%s' in %s." % (j["actor"], len(raw_items), job, REGISTRY_NAME))
        else:
            missing = [f for f in required if items and not coverage.get(f)]
            if missing:
                warnings.append("needs attention: no result had %s, so the tool (%s) has probably renamed a field. "
                                "Compare `their_fields_seen` in this run's record with the output_map for '%s' in %s."
                                % (" or ".join(missing), j["actor"], job, REGISTRY_NAME))
            if unusable:
                warnings.append("%d row%s could not be read and %s left out."
                                % (unusable, "" if unusable == 1 else "s", "was" if unusable == 1 else "were"))
        return items, coverage, warnings
