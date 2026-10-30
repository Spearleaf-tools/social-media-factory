"""Research tests: the price is said first, nothing is spent without a yes, a run cannot run away,
a broken tool is reported instead of crashing, a key is never shown, and one brand's research
never lands in, or is read by, another brand.

    python -m unittest discover -s tests -t . -v

No network. Every answer from the research service in this file is invented, and so is every
account, channel, post and paper.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smf import brands                                                      # noqa: E402
from smf.research import (apify, creator_study, demand_report, listen,      # noqa: E402
                          literature, numbers, serp, store, video_miner, youtube_now)
from smf.research.apify import Apify, ApifyError, DryRunViolation, NotConfirmed, Transport   # noqa: E402
from tests.test_brands import BAKERY, CLINIC                                # noqa: E402

TOKEN = "apify_api_INVENTEDtoken0123456789"
NOW = datetime(2030, 6, 1, tzinfo=timezone.utc)
TODAY = date(2030, 6, 1)


class FakeResponse(io.BytesIO):
    def __init__(self, payload, status=200):
        io.BytesIO.__init__(self, payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"))
        self.status, self.headers = status, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(req, code, etype="", message=""):
    body = json.dumps({"error": {"type": etype, "message": message}}).encode("utf-8")
    return urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(body))


class FakeApify(object):
    """Stands in for the research service. Records every request, in order, in a log it can share."""

    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.requests = []
        self.items = []                 # what the "dataset" holds
        self.ignore_limit = False       # a badly behaved tool that returns more than it was told to
        self.statuses = ["SUCCEEDED"]   # what each status check answers, in turn; the last one repeats
        self.missing = set()            # actor ids that answer "not found"
        self.actor_info = {}            # actor id -> the public listing to answer with
        self.fail_start_with = None

    def __call__(self, req, timeout=None):
        method, url = req.get_method(), req.full_url
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        self.requests.append({"method": method, "path": parts.path, "query": query, "body": body,
                              "headers": {k.lower(): v for k, v in req.header_items()}, "url": url})
        self.log.append("%s %s" % (method, parts.path))
        path = parts.path

        if method == "GET" and path.startswith("/v2/acts/"):
            actor = urllib.parse.unquote(path.split("/v2/acts/")[1])
            if actor in self.missing:
                raise http_error(req, 404, "record-not-found", "Actor with this name was not found")
            return FakeResponse({"data": self.actor_info.get(actor, {"isPublic": True, "isDeprecated": False})})
        if method == "POST" and path.endswith("/runs"):
            if self.fail_start_with is not None:
                raise self.fail_start_with(req)
            if urllib.parse.unquote(path.split("/v2/acts/")[1].split("/")[0]) in self.missing:
                raise http_error(req, 404, "record-not-found", "Actor with this name was not found")
            return FakeResponse({"data": {"id": "run-1", "defaultDatasetId": "set-1", "status": "RUNNING"}}, 201)
        if method == "GET" and path.startswith("/v2/actor-runs/"):
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return FakeResponse({"data": {"id": "run-1", "defaultDatasetId": "set-1", "status": status}})
        if method == "POST" and path.endswith("/abort"):
            return FakeResponse({"data": {"id": "run-1", "status": "ABORTED"}})
        if method == "GET" and path.startswith("/v2/datasets/"):
            n = len(self.items) if self.ignore_limit else int(query.get("limit", len(self.items)))
            return FakeResponse(self.items[:n])
        if method == "POST" and path.endswith("/run-sync-get-dataset-items"):
            n = len(self.items) if self.ignore_limit else int(query.get("limit", len(self.items)))
            return FakeResponse(self.items[:n])
        raise AssertionError("unexpected request %s %s" % (method, url))

    @property
    def starts(self):
        return [r for r in self.requests if r["method"] not in ("GET", "HEAD")]


def reel(n, views, days_ago=30, caption=None, pinned=False, owner="invented.baker"):
    when = datetime.fromtimestamp(NOW.timestamp() - days_ago * 86400, timezone.utc)
    return {"id": "r%d" % n, "shortCode": "c%d" % n, "url": "https://example.com/reel/%d" % n,
            "ownerUsername": owner, "caption": caption or "Invented caption number %d. More words follow here." % n,
            "hashtags": ["bread", "invented"], "timestamp": when.isoformat().replace("+00:00", "Z"),
            "videoDuration": 20 + n, "videoPlayCount": views, "likesCount": views // 20, "commentsCount": 3,
            "isPinned": pinned, "latestComments": [{"ownerUsername": "a.private.person", "text": "not ours to keep"}]}


class ResearchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="research ' é ")
        self.patches = [mock.patch.object(brands, "CLIENT_DIR", os.path.join(self.tmp.name, "Client")),
                        mock.patch.object(brands, "ROOT", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.bakery = brands.create("maple-and-main", "Maple & Main Bakery", json.loads(json.dumps(BAKERY)))
        self.clinic = brands.create("stride-physio", "Stride Physio", json.loads(json.dumps(CLINIC)))
        self.log = []
        self.service = FakeApify(self.log)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def client(self, allow_runs=True, token=TOKEN):
        c = Apify(transport=Transport(allow_runs=allow_runs, opener=self.service), token=token,
                  out=lambda text: self.log.append("SAID " + text))
        c._sleep = lambda s: None
        return c

    def files_under(self, brand):
        return sorted(str(p.relative_to(brand.home)).replace(os.sep, "/")
                      for p in Path(brand.path("Inputs", "Research")).rglob("*") if p.is_file())


# ============================================================================ money
class TestTheCostIsSaidFirstAndNothingIsSpentWithoutAYes(ResearchCase):
    def test_without_confirm_the_price_is_shown_and_no_request_of_any_kind_is_made(self):
        with self.assertRaises(NotConfirmed) as cm:
            self.client().run("reddit_search", ["sourdough starter"], max_items=40)
        self.assertEqual(self.service.requests, [])                          # not even a lookup
        self.assertTrue(self.log[0].startswith("SAID Estimated cost:"), self.log)
        self.assertIn("estimate", self.log[0])
        self.assertIn("Nothing was run and nothing was spent", str(cm.exception))
        self.assertEqual(cm.exception.plan["max_items"], 40)

    def test_only_the_value_true_counts_as_a_yes(self):
        for almost in ("yes", 1, "true", None, 0):
            with self.assertRaises(NotConfirmed):
                self.client().run("x_search", ["rye bread"], max_items=10, confirm=almost)
        self.assertEqual(self.service.starts, [])

    def test_with_a_yes_the_price_is_still_said_before_anything_starts(self):
        self.service.items = [{"id": "p1", "postUrl": "https://example.com/p/1", "title": "An invented post"}]
        self.client().run("reddit_search", ["sourdough starter"], max_items=5, confirm=True)
        said = next(i for i, line in enumerate(self.log) if line.startswith("SAID Estimated cost:"))
        started = next(i for i, line in enumerate(self.log) if line.startswith("POST "))
        self.assertLess(said, started, self.log)

    def test_a_dry_run_transport_is_a_second_lock_that_does_not_depend_on_the_flag(self):
        # Even if some caller wrongly passed confirm=True, a client built for a dry run cannot start a run.
        with self.assertRaises(DryRunViolation):
            self.client(allow_runs=False).run("x_search", ["rye bread"], max_items=10, confirm=True)
        self.assertEqual(self.service.starts, [])

    def test_a_job_without_a_yes_saves_nothing_and_reports_the_estimate(self):
        out = creator_study.study(self.bakery, ["@invented.baker"], "instagram", 30, client=self.client())
        self.assertIs(out["ran"], False)
        self.assertGreater(out["estimate"]["usd"], 0)
        self.assertEqual(self.files_under(self.bakery), [])
        self.assertEqual(self.service.requests, [])

    def test_listening_says_the_whole_price_before_the_first_source_runs(self):
        self.service.items = [{"id": "1", "url": "https://example.com/1", "title": "Invented question here?",
                               "text": "An invented post that is long enough to keep."}]
        listen.listen(self.bakery, ["sourdough"], ("reddit", "x"), 20, confirm=True, client=self.client(), today=TODAY)
        total = next(i for i, line in enumerate(self.log) if "Estimated cost in total" in line)
        self.assertLess(total, next(i for i, line in enumerate(self.log) if line.startswith("POST ")), self.log)

    def test_the_estimate_is_labelled_an_estimate_and_carries_its_date_and_ceiling(self):
        e = self.client().estimate("serp", 10)
        self.assertTrue(e["is_estimate"])
        self.assertIn("estimate", e["text"])
        self.assertIn("2026-09-20", e["text"])
        self.assertAlmostEqual(e["usd"], 0.001 + 10 * 0.0045)
        self.assertEqual(e["ceiling_usd"], 0.5)             # this tool refuses a lower ceiling, so we never send one

    def test_a_paid_extra_is_priced_in_before_the_yes(self):
        plain = self.client().estimate("creator_instagram", 30)["usd"]
        extra = self.client().estimate("creator_instagram", 30, ["transcripts"])["usd"]
        self.assertAlmostEqual(extra - plain, 30 * 0.048)


class TestARunCannotRunAway(ResearchCase):
    def test_the_cap_is_sent_to_the_tool_and_to_the_platform_and_applied_again_here(self):
        self.service.items = [{"id": str(i), "url": "https://example.com/%d" % i, "text": "invented %d" % i}
                              for i in range(500)]
        self.service.ignore_limit = True                      # a tool that ignores what it was told
        res = self.client().run("x_search", ["rye bread"], max_items=25, confirm=True)
        start = self.service.starts[0]
        self.assertEqual(start["body"]["maxItems"], 25)                        # 1. told to the tool
        self.assertIn("maxTotalChargeUsd", start["query"])                     # 2. a money ceiling the platform enforces
        self.assertGreater(float(start["query"]["maxTotalChargeUsd"]), 0)
        self.assertIn("timeout", start["query"])                               #    and a time limit
        fetch = [r for r in self.service.requests if r["path"].startswith("/v2/datasets/")][0]
        self.assertEqual(fetch["query"]["limit"], "25")                        #    asked for no more than the cap
        self.assertEqual(res["count"], 25)                                     # 3. trimmed here regardless
        self.assertTrue(any("more than the limit" in w for w in res["warnings"]))

    def test_a_cap_below_one_is_refused_because_some_tools_read_zero_as_unlimited(self):
        for bad in (0, -5, None.__class__, 2.5, True, "10"):
            with self.assertRaises(ApifyError) as cm:
                self.client().plan("youtube_channel", ["@invented-channel"], max_items=bad)
            self.assertEqual(cm.exception.kind, "refused")
        self.assertEqual(self.service.requests, [])

    def test_a_cap_above_the_jobs_ceiling_is_refused(self):
        with self.assertRaises(ApifyError) as cm:
            self.client().plan("serp", ["why is my loaf dense"], max_items=10000)
        self.assertIn("100", str(cm.exception))

    def test_a_per_account_cap_is_divided_so_the_total_stays_inside_the_budget(self):
        plan = self.client().plan("creator_instagram", ["one", "two", "three"], max_items=30)
        self.assertEqual(plan["actor_input"]["resultsLimit"], 10)
        self.assertEqual(plan["units"], 30)
        many = self.client().plan("creator_instagram", ["h%d" % i for i in range(9)], max_items=4)
        self.assertEqual(len(many["inputs"]), 4)                               # extra accounts dropped, and said so
        self.assertEqual(many["actor_input"]["resultsLimit"], 1)
        self.assertTrue(many["notes"])

    def test_a_tool_with_no_limit_setting_is_capped_by_trimming_what_is_sent(self):
        links = ["https://example.com/watch?v=%d" % i for i in range(20)]
        plan = self.client().plan("youtube_transcripts", links, max_items=3)
        self.assertEqual(plan["actor_input"]["urls"], links[:3])

    def test_queries_for_the_search_tool_are_sent_as_lines_not_a_list(self):
        plan = self.client().plan("serp", ["why is my loaf dense", "best flour for rye"], max_items=2)
        self.assertEqual(plan["actor_input"]["queries"], "why is my loaf dense\nbest flour for rye")
        self.assertEqual(plan["actor_input"]["maxPagesPerQuery"], 1)

    def test_a_setting_the_job_does_not_list_is_refused_so_a_paid_extra_cannot_be_switched_on(self):
        for sneaky in ({"aiModeSearch": {"enableAiMode": True}}, {"perplexitySearch": {"enablePerplexity": True}},
                       {"maximumLeadsEnrichmentRecords": 5}):
            with self.assertRaises(ApifyError) as cm:
                self.client().run("serp", ["rye"], max_items=1, extra=sneaky, confirm=True)
            self.assertEqual(cm.exception.kind, "refused")
        with self.assertRaises(ApifyError):
            self.client().run("reddit_search", ["rye"], max_items=5, extra={"aiAnalysis": True}, confirm=True)
        self.assertEqual(self.service.starts, [])

    def test_a_run_that_never_finishes_is_stopped_so_it_stops_charging(self):
        self.service.statuses = ["RUNNING"]
        c = self.client()
        ticks = iter(range(0, 100000, 50))
        c._now = lambda: next(ticks)                                          # every look at the clock is 50s later
        with self.assertRaises(ApifyError) as cm:
            c.run("x_search", ["rye bread"], max_items=10, confirm=True, wait_secs=120)
        self.assertEqual(cm.exception.kind, "timeout")
        self.assertTrue(any(r["path"].endswith("/abort") for r in self.service.starts), "the run was never stopped")

    def test_results_already_paid_for_are_kept_when_a_run_stops_early(self):
        self.service.statuses = ["RUNNING", "TIMED-OUT"]
        self.service.items = [{"id": "1", "url": "https://example.com/1", "text": "an invented post"}]
        res = self.client().run("x_search", ["rye bread"], max_items=10, confirm=True)
        self.assertTrue(res["partial"])
        self.assertEqual(res["count"], 1)
        self.assertTrue(any("time limit" in w for w in res["warnings"]))

    def test_the_one_request_mode_is_capped_the_same_way(self):
        self.service.items = [{"id": str(i), "url": "https://example.com/%d" % i, "text": "x"} for i in range(90)]
        self.service.ignore_limit = True
        res = self.client().run("x_search", ["rye"], max_items=7, confirm=True, mode="sync")
        self.assertEqual(res["count"], 7)
        self.assertEqual(self.service.starts[0]["body"]["maxItems"], 7)
        self.assertIn("maxTotalChargeUsd", self.service.starts[0]["query"])


class TestTheActorTableItself(unittest.TestCase):
    """Structural checks on apify_actors.json, so an edit cannot quietly remove a safety."""

    def setUp(self):
        self.jobs = apify.load_registry()

    def test_every_job_has_what_the_client_relies_on(self):
        for name, j in self.jobs.items():
            for key in ("actor", "purpose", "input_template", "output_map", "unit", "est_usd_per_unit", "checked",
                        "notes", "inputs_field", "cap_scope", "default_cap", "max_cap", "required_fields"):
                self.assertIn(key, j, "%s is missing %s" % (name, key))
            self.assertRegex(j["actor"], r"^[\w.-]+/[\w.-]+$", name)
            self.assertIn(j["unit"], ("result", "page", "video"), name)
            self.assertIn("cap_field", j, name)
            self.assertGreaterEqual(j["default_cap"], 1)
            self.assertLessEqual(j["default_cap"], j["max_cap"])
            self.assertTrue(set(j["required_fields"]) <= set(j["output_map"].values()), name)
            self.assertNotIn(j["inputs_field"], j["input_template"], name)

    def test_no_job_can_pass_a_setting_that_its_fixed_settings_pin(self):
        for name, j in self.jobs.items():
            pinned_off = {k for k, v in j["input_template"].items() if v is False or v == 0}
            self.assertEqual(pinned_off & set(j.get("allowed_inputs") or []), set(), name)

    def test_paid_text_analysis_is_pinned_off_because_claude_does_the_reading(self):
        reddit = self.jobs["reddit_search"]
        self.assertIs(reddit["input_template"]["aiAnalysis"], False)
        self.assertEqual(reddit["input_template"]["customLabels"], {})

    def test_every_expensive_search_extra_is_pinned_off(self):
        t = self.jobs["serp"]["input_template"]
        self.assertIs(t["aiModeSearch"]["enableAiMode"], False)
        self.assertIs(t["perplexitySearch"]["enablePerplexity"], False)
        self.assertIs(t["chatGptSearch"]["enableChatGpt"], False)
        self.assertIs(t["geminiSearch"]["enableGemini"], False)
        self.assertIs(t["copilotSearch"]["enableCopilot"], False)
        self.assertIs(t["websiteContentScraper"]["enable"], False)
        self.assertEqual(t["maximumLeadsEnrichmentRecords"], 0)
        self.assertIs(t["focusOnPaidAds"], False)

    def test_prices_say_they_are_estimates(self):
        with open(apify.REGISTRY, "r", encoding="utf-8") as f:
            meta = json.load(f)["_meta"]
        self.assertIn("ESTIMATE", meta["prices"])


# ============================================================================ failures
class TestABrokenToolIsReportedNotACrash(ResearchCase):
    def test_a_renamed_actor_needs_attention_in_the_health_check(self):
        self.service.missing.add("apify~google-search-scraper")
        rep = self.client().health("serp")
        self.assertEqual(rep["state"], "needs attention")
        self.assertIn("renamed or removed", rep["detail"])
        self.assertIn("apify_actors.json", rep["detail"])

    def test_the_health_check_needs_no_key_sends_no_key_and_starts_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("smf.keys.KEYS_FILE", "/nonexistent/keys.env"):
            import smf.keys
            smf.keys.load(force=True)
            reports = self.client(allow_runs=False, token=None).health_all()
        self.assertEqual(len(reports), len(apify.load_registry()))
        self.assertTrue(all(r["state"] == "ok" for r in reports), reports)
        self.assertEqual(self.service.starts, [])
        self.assertTrue(all("authorization" not in r["headers"] for r in self.service.requests))

    def test_the_health_check_never_raises_even_when_the_network_is_down(self):
        def down(req, timeout=None):
            raise urllib.error.URLError("no route to host")
        c = Apify(transport=Transport(opener=down), token=None, out=lambda t: None)
        rep = c.health("serp")
        self.assertEqual(rep["state"], "could not check")
        self.assertIn("internet", rep["detail"])

    def test_a_price_rise_needs_attention_and_a_price_drop_does_not(self):
        def listing(price):
            return {"isPublic": True, "isDeprecated": False, "pricingInfos": [{"pricingModel": "PAY_PER_EVENT",
                    "pricingPerEvent": {"actorChargeEvents": {"apify-default-dataset-item": {
                        "eventTieredPricingUsd": {"FREE": {"tieredEventPriceUsd": price}}}}}}]}
        self.service.actor_info["xquik~x-tweet-scraper"] = listing(0.0009)
        up = self.client().health("x_search")
        self.assertEqual((up["state"], up["repriced"]), ("needs attention", True))
        self.assertIn("gone UP", up["detail"])
        self.service.actor_info["xquik~x-tweet-scraper"] = listing(0.00001)
        self.assertEqual(self.client().health("x_search")["state"], "ok")
        self.service.actor_info["xquik~x-tweet-scraper"] = listing(0.00015)
        same = self.client().health("x_search")
        self.assertEqual((same["state"], same["repriced"], same["live_usd_per_unit"]), ("ok", False, 0.00015))

    def test_a_retired_actor_and_a_raised_minimum_need_attention(self):
        self.service.actor_info["harshmaur~reddit-scraper"] = {"isPublic": True, "isDeprecated": True}
        self.assertIn("retired", self.client().health("reddit_search")["detail"])
        self.service.actor_info["harshmaur~reddit-scraper"] = {"isPublic": True, "pricingInfos": [
            {"minimalMaxTotalChargeUsd": 2.0}]}
        self.assertIn("$2.00", self.client().health("reddit_search")["detail"])

    def test_a_renamed_actor_at_run_time_is_a_plain_error(self):
        self.service.missing.add("xquik~x-tweet-scraper")
        with self.assertRaises(ApifyError) as cm:
            self.client().run("x_search", ["rye"], max_items=5, confirm=True)
        self.assertEqual(cm.exception.kind, "needs-attention")
        self.assertIn("xquik/x-tweet-scraper", str(cm.exception))

    def test_a_tool_that_changed_its_output_shape_is_flagged_with_what_to_compare(self):
        self.service.items = [{"identifier": "1", "permalink": "https://example.com/1", "content": "renamed fields"}]
        res = self.client().run("x_search", ["rye"], max_items=5, confirm=True)
        self.assertEqual(res["count"], 0)
        self.assertTrue(any(w.startswith("needs attention") for w in res["warnings"]), res["warnings"])
        self.assertEqual(res["their_fields_seen"], ["content", "identifier", "permalink"])

    def test_each_kind_of_refusal_gets_its_own_plain_words(self):
        cases = {401: ("unauthorized", "did not accept the key"), 402: ("out-of-credit", "out of credit"),
                 403: ("not-allowed", "would not let"), 400: ("needs-attention", "settings"),
                 429: ("rate-limited", "slow down"), 503: ("server", "problem of its own")}
        for code, (kind, words) in cases.items():
            self.service.fail_start_with = lambda req, code=code: http_error(req, code, "x", "invented detail")
            with self.assertRaises(ApifyError) as cm:
                self.client().run("x_search", ["rye"], max_items=5, confirm=True)
            self.assertEqual(cm.exception.kind, kind, code)
            self.assertIn(words, str(cm.exception), code)
        self.assertIs(cm.exception.definitive, False)        # after a server fault a run MAY have started

    def test_no_key_says_so_and_mentions_the_free_plan(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("smf.keys.KEYS_FILE", "/nonexistent/keys.env"):
            import smf.keys
            smf.keys.load(force=True)
            with self.assertRaises(ApifyError) as cm:
                self.client(token=None).run("x_search", ["rye"], max_items=5, confirm=True)
        self.assertEqual(cm.exception.kind, "not-configured")
        self.assertIn("free plan", str(cm.exception))
        self.assertIn("APIFY_API_TOKEN", str(cm.exception))
        self.assertEqual(self.service.starts, [])

    def test_a_damaged_actor_table_is_a_sentence(self):
        bad = Path(self.tmp.name) / "actors.json"
        bad.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(ApifyError) as cm:
            apify.load_registry(str(bad))
        self.assertIn("damaged", str(cm.exception))


class TestAKeyIsNeverShown(ResearchCase):
    def test_the_key_travels_in_a_header_and_never_in_an_address(self):
        self.service.items = [{"id": "1", "url": "https://example.com/1", "text": "an invented post"}]
        self.client().run("x_search", ["rye"], max_items=5, confirm=True)
        self.assertTrue(self.service.starts)
        for r in self.service.requests:
            self.assertNotIn(TOKEN, r["url"])
        self.assertEqual(self.service.starts[0]["headers"]["authorization"], "Bearer " + TOKEN)

    def test_a_service_that_echoes_the_key_back_cannot_get_it_into_an_error(self):
        for code in (400, 401, 402, 403, 404, 408, 429, 500):
            self.service.fail_start_with = lambda req, code=code: http_error(
                req, code, "x", "bad token %s in header %s" % (TOKEN, req.get_header("Authorization")))
            with self.assertRaises(ApifyError) as cm:
                self.client().run("x_search", ["rye"], max_items=5, confirm=True)
            self.assertNotIn(TOKEN, str(cm.exception), code)
            self.assertNotIn(TOKEN[-12:], str(cm.exception), code)

    def test_a_network_fault_that_names_the_key_cannot_get_it_into_an_error(self):
        self.service.fail_start_with = lambda req: urllib.error.URLError("proxy refused " + TOKEN)
        with self.assertRaises(ApifyError) as cm:
            self.client().run("x_search", ["rye"], max_items=5, confirm=True)
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertIs(cm.exception.definitive, False)

    def test_the_key_is_not_written_into_the_saved_research(self):
        self.service.items = [reel(i, 1000 + i) for i in range(10)]
        creator_study.study(self.bakery, ["invented.baker"], "instagram", 10, confirm=True, client=self.client(),
                            today=TODAY, now=NOW)
        for name in self.files_under(self.bakery):
            self.assertNotIn(TOKEN, Path(self.bakery.path(*name.split("/"))).read_text(encoding="utf-8"), name)


# ============================================================================ arithmetic
class TestOutlierMaths(unittest.TestCase):
    def vids(self, views, channel="invented-channel", days_ago=60):
        when = datetime.fromtimestamp(NOW.timestamp() - days_ago * 86400, timezone.utc).isoformat()
        return [{"url": "u%d" % i, "channel": channel, "views": v, "posted_at": when} for i, v in enumerate(views)]

    def score(self, videos):
        return numbers.score_against_own_normal(videos, "channel", now=NOW)

    def test_the_normal_is_the_median_so_one_viral_video_does_not_hide_the_rest(self):
        views = [1000, 1100, 900, 1000, 1200, 950, 1050, 1000, 3000, 500000]
        scored, groups = self.score(self.vids(views))
        self.assertEqual(groups["invented-channel"]["baseline_median"], 1025.0)   # a MEAN would be about 51,000
        by = {v["url"]: v for v in scored}
        self.assertEqual(by["u9"]["standing"], "outlier")
        self.assertEqual(by["u8"]["standing"], "outlier")     # 2.9x: invisible against a mean, plain against a median
        self.assertEqual(by["u8"]["outlier_score"], round(3000 / 1025.0, 2))
        self.assertEqual(by["u0"]["standing"], "typical")

    def test_too_few_videos_means_no_score_and_a_reason(self):
        scored, groups = self.score(self.vids([1000, 50000, 900, 1100]))
        self.assertTrue(all(v["outlier_score"] is None for v in scored))
        self.assertIs(groups["invented-channel"]["scored"], False)
        self.assertIn("at least 8", groups["invented-channel"]["why_not"])

    def test_a_tiny_channel_gets_no_score_because_forty_views_against_ten_means_nothing(self):
        scored, groups = self.score(self.vids([10, 12, 9, 11, 10, 8, 13, 10, 40]))
        self.assertTrue(all(v["outlier_score"] is None for v in scored))
        self.assertIn("too small", groups["invented-channel"]["why_not"])

    def test_a_median_of_zero_never_divides(self):
        scored, _ = self.score(self.vids([0, 0, 0, 0, 0, 0, 0, 0, 900]))
        self.assertTrue(all(v["outlier_score"] is None for v in scored))

    def test_a_video_still_collecting_views_is_kept_out_of_the_normal_and_marked_provisional(self):
        settled = self.vids([1000] * 9)
        fresh = self.vids([200], days_ago=2)[0]
        fresh["url"] = "fresh"
        scored, groups = self.score(settled + [fresh])
        g = groups["invented-channel"]
        self.assertEqual((g["in_baseline"], g["baseline_median"]), (9, 1000.0))
        new = [v for v in scored if v["url"] == "fresh"][0]
        self.assertTrue(new["provisional"])
        self.assertIn("understates", new["score_note"])

    def test_pinned_videos_are_scored_but_cannot_inflate_the_normal(self):
        vids = self.vids([1000] * 9) + [dict(self.vids([900000])[0], url="pin", pinned=True)]
        scored, groups = self.score(vids)
        self.assertEqual(groups["invented-channel"]["baseline_median"], 1000.0)
        self.assertEqual([v for v in scored if v["url"] == "pin"][0]["standing"], "outlier")

    def test_each_account_is_measured_against_itself(self):
        big = self.vids([900000] * 8 + [1000000], channel="big")
        small = self.vids([1000] * 8 + [9000], channel="small")
        scored, _ = self.score(big + small)
        top = sorted((v for v in scored if v["outlier_score"]), key=lambda v: -v["outlier_score"])[0]
        self.assertEqual(top["channel"], "small")             # 9x its own normal beats 1.1x, whatever the raw views

    def test_a_missing_view_count_is_not_a_zero(self):
        vids = self.vids([1000] * 9) + [{"url": "none", "channel": "invented-channel", "views": None,
                                         "posted_at": None}]
        scored, groups = self.score(vids)
        self.assertEqual(groups["invented-channel"]["in_baseline"], 9)
        self.assertEqual([v for v in scored if v["url"] == "none"][0]["score_note"], "no view count")

    def test_numbers_and_dates_are_read_the_way_sites_write_them(self):
        self.assertEqual(numbers.to_number("12.3K"), 12300.0)
        self.assertEqual(numbers.to_number("1.2M subscribers"), 1200000.0)
        self.assertEqual(numbers.to_number("69,916 views"), 69916.0)
        self.assertIsNone(numbers.to_number("no figure"))
        self.assertIsNone(numbers.to_number(True))
        self.assertEqual(numbers.age_days("3 months ago", NOW), 90)
        self.assertEqual(numbers.age_days("2030-05-22T00:00:00Z", NOW), 10)
        self.assertEqual(numbers.age_days(NOW.timestamp() - 86400 * 5, NOW), 5)
        self.assertIsNone(numbers.age_days("sometime", NOW))

    def test_the_input_is_not_changed(self):
        vids = self.vids([1000] * 9)
        before = json.dumps(vids, sort_keys=True)
        self.score(vids)
        self.assertEqual(json.dumps(vids, sort_keys=True), before)


class TestYouTubeDemand(unittest.TestCase):
    def row(self, i, kw, views, days, subs=50000, channel=None):
        when = datetime.fromtimestamp(NOW.timestamp() - days * 86400, timezone.utc).isoformat()
        return {"id": "v%s%d" % (kw[:1], i), "url": "https://example.com/v/%s%d" % (kw[:1], i), "keyword": kw,
                "title": "Invented title %d" % i, "channel": channel or "channel-%d" % i, "views": views,
                "subscribers": subs, "published_at": when}

    def test_alive_stale_and_too_thin(self):
        alive = [self.row(i, "sourdough", 10000 + i, 100) for i in range(6)] + \
                [self.row(i + 6, "sourdough", 9000, 1500) for i in range(4)]
        stale = [self.row(i, "bread machine", 50000, 1600) for i in range(9)] + [self.row(9, "bread machine", 40, 30)]
        thin = [self.row(i, "spelt", 5000, 50) for i in range(3)]
        r = youtube_now.analyse_search(alive + stale + thin, now=NOW)["keywords"]
        self.assertEqual(r["sourdough"]["verdict"], "alive")
        self.assertEqual(r["bread machine"]["verdict"], "stale")
        self.assertEqual(r["spelt"]["verdict"], "too thin to say")
        self.assertIn("at least 8", r["spelt"]["why"])

    def test_a_small_channel_win_and_a_keyword_one_channel_owns(self):
        rows = [self.row(i, "rye", 8000, 90, channel="the-owner") for i in range(5)] + \
               [self.row(i + 5, "rye", 8000, 90) for i in range(4)] + [self.row(9, "rye", 60000, 40, subs="2.1K")]
        r = youtube_now.analyse_search(rows, now=NOW)["keywords"]["rye"]
        self.assertEqual(r["small_channel_wins"], 1)
        self.assertEqual(r["winners"][0]["views_per_subscriber"], round(60000 / 2100.0, 2))
        self.assertEqual((r["owner"], r["owner_share"]), ("the-owner", 0.5))

    def test_undated_results_do_not_get_a_verdict(self):
        rows = [dict(self.row(i, "rye", 8000, 90), published_at=None) for i in range(10)]
        self.assertEqual(youtube_now.analyse_search(rows, now=NOW)["keywords"]["rye"]["verdict"], "too thin to say")


# ============================================================================ listening
POSTS = [
    ("a1", "Why is my sourdough crumb so dense? I followed the recipe exactly.", 40),
    ("a2", "Dense crumb again. I am so frustrated, third loaf this week.", 12),
    ("a3", "How do I fix a dense crumb without buying a dutch oven?", 25),
    ("a4", "Is there a way to keep a starter alive while I travel for two weeks?", 30),
    ("a5", "My starter died while I was away. Looking for a travel routine that works.", 9),
    ("a6", "Any tips to keep a starter alive in the fridge for a month?", 14),
    ("a7", "Supermarket sourdough is a rip off, it is just white bread with vinegar.", 55),
    ("a8", "Proofing times confuse me. How do I know when the dough is ready?", 18),
    ("a9", "Underproofed again, the dough never seems ready when the recipe says.", 7),
    ("b1", "Totally unrelated post about a bicycle.", 1),
]


def heard(posts=POSTS, source="reddit"):
    return [{"id": "%s:%s" % (source, pid), "source": source, "url": "https://example.com/p/%s" % pid, "text": text,
             "community": "invented", "posted_at": "2030-05-0%dT00:00:00Z" % (1 + i % 9), "score": score,
             "replies": 1, "kinds": listen.kinds_of(text)} for i, (pid, text, score) in enumerate(posts)]


class TestClusteringIsDeterministic(unittest.TestCase):
    def test_the_same_posts_in_any_order_give_exactly_the_same_themes(self):
        import random
        base = json.dumps(listen.cluster(heard(), ["sourdough"]), sort_keys=True)
        for seed in range(12):
            shuffled = heard()
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(json.dumps(listen.cluster(shuffled, ["sourdough"]), sort_keys=True), base, seed)

    def test_themes_are_named_after_what_people_said_not_after_the_search_word(self):
        labels = [t["label"] for t in listen.cluster(heard(), ["sourdough"])]
        self.assertIn("dense crumb", labels)                 # the two-word phrase wins over "dense" or "crumb" alone
        self.assertFalse(any("sourdough" in label for label in labels), labels)
        self.assertEqual(labels[-1], "everything else")

    def test_every_post_lands_in_exactly_one_theme(self):
        themes = listen.cluster(heard(), ["sourdough"])
        ids = [i for t in themes for i in t["post_ids"]]
        self.assertEqual(sorted(ids), sorted(p["id"] for p in heard()))

    def test_sorting_into_kinds_uses_visible_word_rules(self):
        self.assertEqual(listen.kinds_of("Why is my loaf dense?"), ["question"])
        self.assertEqual(listen.kinds_of("I am so frustrated with this oven"), ["complaint"])
        self.assertIn("request", listen.kinds_of("Looking for a good rye flour"))
        self.assertEqual(listen.kinds_of("We baked on Sunday."), [])
        both = listen.kinds_of("Is there a way to stop this? It is a nightmare.")
        self.assertEqual(both, ["question", "complaint", "request"])

    def test_phrases_are_counted_by_how_many_posts_use_them_not_how_often_one_person_repeats_them(self):
        shouty = heard([("s1", "dense crumb dense crumb dense crumb dense crumb, help", 1),
                        ("s2", "a nice open crumb at last", 1), ("s3", "another open crumb today", 1)])
        found = {p["phrase"]: p["posts"] for p in listen.phrases(shouty, set())}
        self.assertEqual(found.get("open crumb"), 2)
        self.assertNotIn("dense crumb", found)               # one person, however loud, is one post

    def test_author_names_are_not_kept(self):
        rows = [{"id": "1", "url": "https://example.com/1", "title": "An invented question about rye?",
                 "body": "Some invented detail.", "score": "1.2K", "authorName": "a.private.person"}]
        tidy = listen.tidy(rows, "reddit")[0]
        self.assertNotIn("a.private.person", json.dumps(tidy))
        self.assertEqual(tidy["score"], 1200)


# ============================================================================ brands never mix
class TestResearchStaysInsideItsBrand(ResearchCase):
    def study(self, brand, handle="invented.baker"):
        self.service.items = [reel(i, 1000 + 10 * i) for i in range(10)]
        return creator_study.study(brand, [handle], "instagram", 10, confirm=True, client=self.client(),
                                   today=TODAY, now=NOW)

    def test_a_run_lands_in_the_named_brand_and_nowhere_else(self):
        out = self.study(self.bakery)
        self.assertEqual(out["folder"], "Inputs/Research/creator-study/2030-06-01-instagram-invented-baker")
        self.assertEqual(sorted(n.rsplit("/", 1)[1] for n in self.files_under(self.bakery)),
                         ["run.json", "study.json", "summary.md", "videos.json"])
        self.assertEqual(self.files_under(self.clinic), [])
        rec = json.loads(Path(self.bakery.path(*out["folder"].split("/"), "run.json")).read_text(encoding="utf-8"))
        self.assertEqual(rec["brand"], "maple-and-main")

    def test_no_brand_is_an_error_not_a_guess(self):
        for nothing in (None, "", 0):
            with self.assertRaises(brands.BrandError):
                creator_study.study(nothing, ["invented.baker"], client=self.client())
        with self.assertRaises(brands.BrandError):
            listen.listen("no-such-brand", ["rye"], client=self.client())
        self.assertEqual(self.service.requests, [])

    def test_a_hostile_label_cannot_steer_the_folder_out_of_the_brand(self):
        for label in ("../../stride-physio/Inputs/Research/x", "..\\..\\stride-physio", "/etc/passwd", "a/../../b",
                      "Ava's \"clips\" (final) é%", "...", ""):
            folder = store.new_run_dir(self.bakery, "listen", label, TODAY)
            self.assertTrue(store._inside(folder, self.bakery.path("Inputs", "Research", "listen")), label)
            self.assertEqual(os.path.dirname(folder), self.bakery.path("Inputs", "Research", "listen"), label)
        self.assertEqual(self.files_under(self.clinic), [])

    def test_a_write_aimed_outside_the_brands_research_folder_is_refused(self):
        with self.assertRaises(store.ResearchError):
            store.write_text(self.bakery, self.clinic.path("Inputs", "Research", "listen", "x", "summary.md"), "no")
        with self.assertRaises(store.ResearchError):
            store.write_json(self.bakery, self.bakery.path("brand-master.json"), {})     # inside the brand, outside research
        self.assertFalse(os.path.exists(self.clinic.path("Inputs", "Research", "listen", "x")))

    def test_an_earlier_run_is_never_overwritten(self):
        a, b = self.study(self.bakery)["folder"], self.study(self.bakery)["folder"]
        self.assertNotEqual(a, b)
        self.assertTrue(b.endswith("-2"))

    def heard_run(self, brand):
        folder = store.new_run_dir(brand, "listen", "sourdough", TODAY)
        store.write_json(brand, os.path.join(folder, "posts.json"), heard())
        store.write_record(brand, folder, "listen", {"terms": ["sourdough"], "sources": ["reddit"]},
                           {"count": len(POSTS), "estimated_usd": 0.1, "ceiling_usd": 0.2})
        return folder

    def test_a_demand_report_is_built_from_this_brands_listening_only(self):
        self.heard_run(self.bakery)
        out = demand_report.report(self.bakery, today=TODAY)
        self.assertEqual(out["folder"], "Inputs/Research/demand-report/2030-06-01-sourdough")
        self.assertEqual(out["themes"][0], ("dense crumb", 3))
        self.assertEqual([n for n in self.files_under(self.clinic)], [])

    def test_a_demand_report_refuses_another_brands_listening(self):
        theirs = self.heard_run(self.clinic)
        with self.assertRaises(store.ResearchError) as cm:
            demand_report.report(self.bakery, [theirs], today=TODAY)
        self.assertIn("not part of Maple & Main Bakery's research", str(cm.exception))

    def test_a_copied_in_run_that_names_another_brand_is_refused(self):
        mine = self.heard_run(self.bakery)
        rec = json.loads(Path(mine, "run.json").read_text(encoding="utf-8"))
        rec["brand"] = "stride-physio"                         # a folder copied across by hand
        Path(mine, "run.json").write_text(json.dumps(rec), encoding="utf-8")
        with self.assertRaises(store.ResearchError) as cm:
            demand_report.report(self.bakery, today=TODAY)
        self.assertIn("different brand", str(cm.exception))

    def test_topic_candidates_carry_a_source_ref_back_to_the_report(self):
        self.heard_run(self.bakery)
        out = demand_report.report(self.bakery, today=TODAY)
        cands = json.loads(Path(self.bakery.path(*out["folder"].split("/"), "topic_candidates.json"))
                           .read_text(encoding="utf-8"))
        self.assertEqual(cands[0]["source_ref"], "Inputs/Research/demand-report/2030-06-01-sourdough#t01")
        self.assertEqual(cands[0]["status"], "candidate")
        self.assertTrue(all(c["heard_at"].startswith("https://example.com/") for c in cands))

    def test_a_regulated_brand_is_told_that_what_people_say_online_is_not_evidence(self):
        self.heard_run(self.clinic)
        out = demand_report.report(self.clinic, today=TODAY)
        text = Path(self.clinic.path(*out["folder"].split("/"), "summary.md")).read_text(encoding="utf-8")
        self.assertIn("regulated field (health)", text)
        self.heard_run(self.bakery)
        plain = demand_report.report(self.bakery, today=TODAY)
        self.assertNotIn("regulated field", Path(self.bakery.path(*plain["folder"].split("/"), "summary.md"))
                         .read_text(encoding="utf-8"))


class TestWhatGetsSaved(ResearchCase):
    def test_a_creator_study_counts_lays_out_and_teaches_structure_not_words(self):
        self.service.items = ([reel(i, 1000, caption="How we shape a loaf. Step %d of the day." % i) for i in range(8)]
                              + [reel(8, 9000, caption="Why is your loaf flat? Three causes, one fix."),
                                 reel(9, 300, caption="A quiet morning at the bakery.")])
        out = creator_study.study(self.bakery, ["@invented.baker"], "instagram", 10, confirm=True,
                                  client=self.client(), today=TODAY, now=NOW)
        self.assertEqual(self.service.starts[0]["body"]["username"], ["invented.baker"])     # the @ is dropped
        home = self.bakery.path(*out["folder"].split("/"))
        text = Path(home, "summary.md").read_text(encoding="utf-8")
        self.assertIn("Never reuse someone else's", text)
        self.assertIn("You are responsible", text)
        self.assertIn("normal is **1,000 views**", text)
        self.assertIn("9.0x", text)
        self.assertIn("Worksheet", text)
        study = json.loads(Path(home, "study.json").read_text(encoding="utf-8"))
        self.assertEqual((study["strong_side"]["videos"], study["strong_side"]["opens_with_a_question"]), (1, 1))
        self.assertEqual(study["weak_side"]["videos"], 1)
        saved = Path(home, "videos.json").read_text(encoding="utf-8")
        self.assertNotIn("a.private.person", saved)          # commenters' names in the raw rows are never kept

    def test_transcripts_are_refused_where_the_platform_does_not_offer_them(self):
        with self.assertRaises(store.ResearchError) as cm:
            creator_study.study(self.bakery, ["invented.baker"], "tiktok", 10, transcripts=True, confirm=True,
                                client=self.client())
        self.assertIn("video miner", str(cm.exception))
        self.assertEqual(self.service.starts, [])

    def test_a_search_results_run_gathers_the_questions_people_also_ask(self):
        self.service.items = [{"searchQuery": {"term": "why is my loaf dense", "page": 1},
                               "organicResults": [{"position": 1, "title": "Invented guide", "description": "x",
                                                   "url": "https://www.example.com/dense"}],
                               "peopleAlsoAsk": [{"question": "Can you overproof sourdough?"},
                                                 {"question": "can you overproof sourdough"}],
                               "relatedQueries": [{"title": "dense sourdough fix"}]}]
        out = serp.search(self.bakery, ["why is my loaf dense"], confirm=True, client=self.client(), today=TODAY)
        pages = json.loads(Path(self.bakery.path(*out["folder"].split("/"), "pages.json")).read_text(encoding="utf-8"))
        self.assertEqual([q["question"] for q in pages["all_questions"]], ["Can you overproof sourdough?"])
        self.assertEqual(pages["queries"][0]["results"][0]["site"], "example.com")
        with self.assertRaises(store.ResearchError):
            serp.search(self.bakery, ["rye"], pages_per_query=50, client=self.client())


# ============================================================================ papers
PAPER_XML = """<?xml version="1.0"?><!DOCTYPE PubmedArticleSet><PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>900001</PMID><Article>
 <Journal><Title>Invented Journal of Running</Title><JournalIssue><PubDate><MedlineDate>2029 Nov-Dec</MedlineDate>
 </PubDate></JournalIssue></Journal><ArticleTitle>An invented trial of <i>gradual</i> loading</ArticleTitle>
 <Abstract><AbstractText Label="METHODS">Sixty invented runners.</AbstractText>
 <AbstractText Label="RESULTS">An invented result.</AbstractText></Abstract>
 <AuthorList><Author><LastName>Okafor</LastName><Initials>T</Initials></Author></AuthorList>
 <PublicationTypeList><PublicationType>Journal Article</PublicationType>
 <PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList></Article></MedlineCitation>
 <PubmedData><ArticleIdList><ArticleId IdType="pubmed">900001</ArticleId></ArticleIdList>
 <ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">10.0000/someone-elses-paper</ArticleId>
 <ArticleId IdType="pmc">PMC7777777</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""


class TestPapers(ResearchCase):
    def index(self, seen):
        def answer(req, timeout=None):
            seen.append(req.full_url)
            if "esearch" in req.full_url:
                return FakeResponse({"esearchresult": {"count": "143", "idlist": ["900001"]}})
            if "efetch" in req.full_url:
                return FakeResponse(PAPER_XML.encode("utf-8"))
            return FakeResponse({"best_oa_location": None})
        return Transport(allow_runs=False, opener=answer)

    def test_a_paper_never_borrows_an_id_from_its_own_reference_list(self):
        paper = literature.parse_articles(PAPER_XML)[0]
        self.assertEqual(paper["doi"], "")                   # it has none of its own; the one below is a CITED paper's
        self.assertEqual(paper["free_copy"], "")
        self.assertEqual(paper["title"], "An invented trial of gradual loading")
        self.assertEqual((paper["year"], paper["kind_of_study"], paper["status"]),
                         ("2029", "randomised controlled trial", "unverified"))
        self.assertIn("Methods: Sixty invented runners.", paper["abstract"])

    def test_no_email_is_built_in_and_none_is_sent_unless_the_person_gives_theirs(self):
        seen = []
        literature.search(self.clinic, "running injury loading", 5, transport=self.index(seen), today=TODAY, pause=0)
        self.assertTrue(seen)
        self.assertFalse(any("email" in u or "%40" in u or "@" in u for u in seen), seen)
        self.assertFalse(any("unpaywall" in u for u in seen))
        source = Path(literature.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(source, r"[\w.+-]+@[\w-]+\.[a-z]{2,}")

    def test_a_given_email_is_sent_but_never_saved(self):
        seen = []
        out = literature.search(self.clinic, "running injury loading", 5, contact_email="you@example.com",
                                transport=self.index(seen), today=TODAY, pause=0)
        self.assertTrue(any("you%40example.com" in u for u in seen))
        for name in self.files_under(self.clinic):
            self.assertNotIn("you@example.com", Path(self.clinic.path(*name.split("/"))).read_text(encoding="utf-8"))
        text = Path(self.clinic.path(*out["folder"].split("/"), "summary.md")).read_text(encoding="utf-8")
        self.assertIn("`unverified`", text)
        self.assertIn("regulated field (health)", text)

    def test_a_malformed_email_is_an_error_not_a_silent_skip(self):
        with self.assertRaises(store.ResearchError):
            literature.find("running injury", 5, contact_email="not-an-email", transport=self.index([]))

    def test_papers_only_ever_look_things_up(self):
        with self.assertRaises(DryRunViolation):
            Transport(allow_runs=False, opener=lambda *a, **k: None).request("POST", "https://example.com/x")

    def test_an_entity_declaration_is_refused_rather_than_expanded(self):
        with self.assertRaises(store.ResearchError):
            literature.parse_articles('<!DOCTYPE x [<!ENTITY a "aaaa">]><PubmedArticleSet>&a;</PubmedArticleSet>')


# ============================================================================ video miner
def _pillow_font(size):
    from PIL import ImageFont
    fonts = sorted((ROOT / "smf" / "studio" / "render" / "fonts").rglob("*.ttf"))
    return ImageFont.truetype(str(fonts[0]), size) if fonts else ImageFont.load_default()


def make_slide(folder, name, big="38%", small="From 1,204 invented home bakers", ground=(251, 247, 240),
               noise=0, quality=90, blob_shift=None):
    """A synthetic still made with Pillow. Nothing here is a real picture of anything."""
    import random
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new("RGB", (1280, 720), ground)
    d = ImageDraw.Draw(img)
    if blob_shift is None:
        d.text((80, 70), "Loaves that came out dense", fill=(43, 29, 20), font=_pillow_font(54))
        d.text((80, 250), big, fill=(194, 87, 26), font=_pillow_font(190))
        d.text((80, 610), small, fill=(90, 80, 70), font=_pillow_font(26))
    else:                                                      # a soft shape that shifts: a stand-in for a person moving
        d.ellipse((480 + blob_shift, 120, 800 + blob_shift, 520), fill=(205, 170, 140))
        d.rectangle((380 + blob_shift, 500, 900 + blob_shift, 720), fill=(60, 90, 140))
        img = img.filter(ImageFilter.GaussianBlur(3))
    if noise:
        rnd, px = random.Random(7), img.load()
        for _ in range(300000):
            x, y = rnd.randrange(1280), rnd.randrange(720)
            k = rnd.randint(-noise, noise)
            px[x, y] = tuple(max(0, min(255, c + k)) for c in px[x, y])
    path = os.path.join(folder, name + ".jpg")
    img.save(path, "JPEG", quality=quality)
    return path


def _has_imaging():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_has_imaging(), "the imaging library is not installed (python factory.py setup)")
class TestFrameDeDuplication(unittest.TestCase):
    """Pure Pillow: no ffmpeg, no speech model, no network. Skipped only on a bare Python."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="stills ' é ")
        d = cls.tmp.name
        cls.s = {"A": make_slide(d, "A"), "A_noisy": make_slide(d, "A_noisy", noise=10, quality=35),
                 "B_big_number": make_slide(d, "B", big="83%"),
                 "C_small_print": make_slide(d, "C", small="From 1,240 invented home bakers"),
                 "D_other_slide": make_slide(d, "D", big="4 hrs", ground=(16, 34, 46)),
                 "H1": make_slide(d, "H1", ground=(40, 44, 52), blob_shift=0),
                 "H2": make_slide(d, "H2", ground=(40, 44, 52), blob_shift=14)}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_on(self, names, **kw):
        return video_miner.dedupe([(i * 2.0, self.s[n]) for i, n in enumerate(names)], **kw)

    def test_a_slide_held_on_screen_becomes_one_still_even_through_ugly_compression(self):
        kept = self.run_on(["A", "A_noisy", "A", "A_noisy", "A"])
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0]["absorbed"], kept[0]["absorbed_as"]), (4, {"same": 4}))
        self.assertEqual(kept[0]["t_end"], 10.0)             # and it remembers how long it was on screen

    def test_a_slide_where_only_the_big_number_changed_is_kept(self):
        kept = self.run_on(["A", "A", "A", "B_big_number", "B_big_number"])
        self.assertEqual([k["kind"] for k in kept], ["scene", "changed"])

    def test_a_slide_where_only_the_small_print_number_changed_is_kept(self):
        # The case a picture hash cannot see at all: the two stills hash IDENTICALLY.
        from PIL import Image
        with Image.open(self.s["A"]) as a, Image.open(self.s["C_small_print"]) as c:
            self.assertEqual(video_miner.bits_apart(video_miner.look_hash(a), video_miner.look_hash(c)), 0)
        kept = self.run_on(["A", "A", "A", "C_small_print", "C_small_print"])
        self.assertEqual([k["kind"] for k in kept], ["scene", "changed"])

    def test_the_gap_between_noise_and_a_real_change_is_wide(self):
        from PIL import Image
        def peak(x, y):
            with Image.open(self.s[x]) as a, Image.open(self.s[y]) as b:
                return video_miner.change_between(video_miner.compare_image(a), video_miner.compare_image(b))[1]
        noise, change = peak("A", "A_noisy"), peak("A", "C_small_print")
        self.assertLess(noise, video_miner.BLOCK_CHANGED / 2.0)
        self.assertGreater(change, video_miner.BLOCK_CHANGED * 2)

    def test_a_different_slide_is_a_new_scene_and_a_returning_slide_says_so(self):
        kept = self.run_on(["A", "A", "D_other_slide", "D_other_slide", "A", "A"])
        self.assertEqual([k["kind"] for k in kept], ["scene", "scene", "scene"])
        self.assertEqual([k["repeat_of"] for k in kept], [None, None, 1])

    def test_a_person_moving_does_not_fill_the_folder_unless_asked_to_keep_every_change(self):
        self.assertEqual(len(self.run_on(["H1", "H2"] * 5)), 4)                       # at most one every six seconds
        self.assertEqual(len(self.run_on(["H1", "H2"] * 5, local_every=2.0)), 10)     # every change, when numbers matter

    def test_nothing_is_dropped_silently_and_the_answer_is_always_the_same(self):
        names = ["A", "A_noisy", "B_big_number", "B_big_number", "D_other_slide", "A", "H1", "H2", "H1"]
        first = self.run_on(names)
        self.assertEqual(sum(1 + k["absorbed"] for k in first), len(names))
        strip = lambda ks: [(k["index"], k["t"], k["kind"], k["absorbed_as"], k["repeat_of"]) for k in ks]
        self.assertEqual(strip(first), strip(self.run_on(names)))
        self.assertTrue(all("cmp" not in k and "thumb" not in k and "hash" not in k for k in first))


class TestTheIndex(unittest.TestCase):
    def test_each_still_is_paired_with_what_was_said_around_it_and_numbers_are_flagged(self):
        spoken = {"segments": [{"start": 0.0, "end": 5.0, "text": "Welcome to the bakery."},
                               {"start": 9.0, "end": 14.0, "text": "Thirty eight percent came out dense."},
                               {"start": 40.0, "end": 44.0, "text": "Far away from either still."}]}
        kept = [{"index": 1, "file": "f1.jpg", "t": 0.0, "t_end": 4.0, "kind": "scene", "why": "x", "absorbed": 1,
                 "absorbed_as": {"same": 1}, "repeat_of": None},
                {"index": 2, "file": "f2.jpg", "t": 10.0, "t_end": 16.0, "kind": "changed", "why": "x", "absorbed": 0,
                 "absorbed_as": {}, "repeat_of": None}]
        rows = video_miner.build_index(kept, spoken)
        self.assertEqual(rows[0]["said_around_it"], "Welcome to the bakery.")
        self.assertIs(rows[0]["a_number_is_spoken_here"], False)
        self.assertEqual(rows[1]["said_around_it"], "Thirty eight percent came out dense.")
        self.assertIs(rows[1]["a_number_is_spoken_here"], True)
        self.assertEqual(rows[1]["at"], "0:10")
        self.assertEqual(video_miner.build_index(kept, None)[0]["said_around_it"], "")

    def test_the_page_claude_fills_in_states_the_law(self):
        self.assertIn("Exact or absent", video_miner.FACTS)
        self.assertIn("source not stated", video_miner.FACTS)
        self.assertIn("check the audio", video_miner.FACTS)


def _video_programs_ready():
    """True only when the video programs are ALREADY on this computer. Never downloads anything."""
    try:
        from static_ffmpeg import run
        folder = run.get_platform_dir()
    except Exception:
        return False
    return any(os.path.isfile(os.path.join(folder, n)) for n in ("ffmpeg", "ffmpeg.exe"))


@unittest.skipUnless(_video_programs_ready(),
                     "needs the video tools, which are not installed here (python factory.py setup --tier video)")
class TestMiningARealFile(ResearchCase):
    """Builds a short silent video from synthetic stills and mines it. The speech model is never
    loaded here (it would have to be downloaded), so these need ffmpeg and nothing else."""

    def make_video(self, with_sound=False):
        import subprocess
        from smf import media
        ff, _ = media.ensure_ffmpeg()
        work = os.path.join(self.tmp.name, "Ava's clips (final) é")
        os.makedirs(work, exist_ok=True)
        parts = [(make_slide(work, "A"), 8), (make_slide(work, "C", small="From 1,240 invented home bakers"), 8),
                 (make_slide(work, "D", big="4 hrs", ground=(16, 34, 46)), 6)]
        listing = os.path.join(work, "list.txt")
        with open(listing, "w", encoding="utf-8") as f:
            for path, secs in parts:
                f.write("file '%s'\nduration %d\n" % (path.replace("'", "'\\''"), secs))
            f.write("file '%s'\n" % parts[-1][0].replace("'", "'\\''"))
        video = os.path.join(work, "bread talk 100%.mp4")
        cmd = [ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing]
        if with_sound:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=22", "-c:a", "aac", "-shortest"]
        p = subprocess.run(cmd + ["-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-t", "22", video],
                           capture_output=True, text=True)
        self.assertTrue(os.path.isfile(video), p.stderr)
        return video

    def test_a_silent_file_in_a_hostile_folder_is_mined_and_the_small_print_change_survives_video_compression(self):
        video = self.make_video()
        before = os.path.getsize(video)
        out = video_miner.mine(self.bakery, video, opening_seconds=5, today=TODAY)
        self.assertEqual(out["folder"], "Inputs/Research/video/2030-06-01-bread-talk-100")
        self.assertEqual(out["stats"], {"taken": 11, "kept": 3, "absorbed_same": 8, "absorbed_moved": 0})
        home = self.bakery.path(*out["folder"].split("/"))
        index = json.loads(Path(home, "index.json").read_text(encoding="utf-8"))
        self.assertEqual([(r["at"], r["kind"]) for r in index["stills"]],
                         [("0:00", "scene"), ("0:08", "changed"), ("0:16", "scene")])
        self.assertEqual(len(os.listdir(os.path.join(home, "frames"))), 3)             # the raw stills are cleaned up
        self.assertEqual(len(os.listdir(os.path.join(home, "opening"))), 5)
        self.assertTrue(any("no sound" in w for w in out["warnings"]))                 # said plainly, not a crash
        self.assertFalse(out["transcribed"])
        # the person's own file is used where it is: not moved, not changed, not copied into the brand
        self.assertEqual(os.path.getsize(video), before)
        self.assertFalse([n for n in self.files_under(self.bakery) if n.lower().endswith(video_miner.VIDEO_TYPES)])
        self.assertEqual(self.files_under(self.clinic), [])
        rec = json.loads(Path(home, "run.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["asked"]["source"], "bread talk 100%.mp4")                # the name, never the full path
        self.assertNotIn(self.tmp.name, json.dumps(rec))

    def test_things_that_are_not_videos_are_refused_in_plain_words(self):
        for bad in ("", "not a link or a file", os.path.join(self.tmp.name, "missing.mp4")):
            with self.assertRaises(video_miner.MinerError):
                video_miner.mine(self.bakery, bad)
        notes = Path(self.tmp.name, "notes.txt")
        notes.write_text("not a video", encoding="utf-8")
        with self.assertRaises(video_miner.MinerError):
            video_miner.mine(self.bakery, str(notes))
        with self.assertRaises(video_miner.MinerError):
            video_miner.mine(self.bakery, self.make_video(), every=0.01)


# ============================================================================ the front door
class TestTheCommandLine(ResearchCase):
    def run_cli(self, args):
        from smf.research import research_cli
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf), mock.patch("sys.stderr", io.StringIO()):
            try:
                code = research_cli.cli_research(args)
            except SystemExit as e:                           # argparse refusing the arguments
                code = e.code
        return code, buf.getvalue()

    def test_every_job_refuses_to_run_without_a_brand(self):
        for job in ("actors", "estimate", "creator", "youtube", "listen", "demand", "serp", "video", "papers"):
            code, _ = self.run_cli([job])
            self.assertEqual(code, 2, job)

    def test_an_unknown_brand_is_a_sentence_that_lists_the_real_ones(self):
        code, said = self.run_cli(["estimate", "--brand", "no-such-brand", "--job", "serp", "--n", "5"])
        self.assertEqual(code, 1)
        self.assertIn("maple-and-main", said)

    def test_estimate_prints_a_price_and_spends_nothing(self):
        code, said = self.run_cli(["estimate", "--brand", "maple-and-main", "--job", "reddit_search", "--n", "60"])
        self.assertEqual(code, 0)
        self.assertIn("Estimated cost: about 14 cents for up to 60 results", said)

    def test_a_paid_job_without_confirm_shows_the_price_and_stops(self):
        with mock.patch.object(apify.urllib.request, "urlopen", side_effect=AssertionError("the network was touched")):
            code, said = self.run_cli(["listen", "--brand", "maple-and-main", "--term", "sourdough", "--limit", "20"])
        self.assertEqual(code, 0)
        self.assertIn("Estimated cost in total", said)
        self.assertIn("Nothing was run and nothing was spent", said)
        self.assertEqual(self.files_under(self.bakery), [])

    def test_the_youtube_job_wants_a_keyword_or_a_channel_not_both(self):
        code, said = self.run_cli(["youtube", "--brand", "maple-and-main"])
        self.assertEqual(code, 2)
        self.assertIn("either --keyword", said)


if __name__ == "__main__":
    unittest.main(verbosity=2)
