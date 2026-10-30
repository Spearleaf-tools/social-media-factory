/* v2-common.js - what both onboarding v2 page designs share (spec smf-spec-onboarding-v2.md rev 11).
   The server puts this file inline into one-page.html (design A) and steps.html (design B): the
   page's security policy runs inline scripts only, and nothing is ever fetched from the internet.

   One engine, two looks. A design calls V2.start(ui) with:
     ui.mount()              build its frame once the questions and session are loaded
     ui.saved(field)         a field was saved or changed state: redraw what shows it
     ui.next(field)          "next" (spoken or tapped): go to the next field in the shared order
     ui.back(field)          "back"
     ui.finished()           Finish went through
   and draws each field with V2.fieldHTML(field) + V2.wire(field). Saving never moves the page. */
(function () {
  "use strict";
  var base = location.pathname.replace(/\/$/, "") + "/api/";
  var F = null;            // fields.json: {groups, deep_groups, core, deep, extra}
  var S = null;            // the session view: answers, state, placeholders, handoff, result
  var P = null;            // starter_packs.json (rev 12, N3): bundled, read from this computer
  var UI = null;
  var prefs = { voice: false, read: false };
  var voiceAvailable = false, voiceState = "missing", voiceCost = "", consented = false;
  var local = { skip: {}, chat: {} };      // per-field marks the answers file has no place for yet
  var storeKey = "smf-v2-" + location.pathname;
  var typedKey = "smf-v2-typed-" + location.pathname;     // typing not confirmed yet (UX audit #2)

  function $(id) { return document.getElementById(id); }
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function clone(x) { return x == null ? x : JSON.parse(JSON.stringify(x)); }
  function dict(a, b) { var o = clone(a) || {}; Object.keys(b).forEach(function (k) { o[k] = b[k]; }); return o; }
  function lines(t) { return String(t || "").split("\n").map(function (s) { return s.trim(); }).filter(Boolean); }
  function filled(v) {
    if (v == null) { return false; }
    if (Array.isArray(v)) { return v.length > 0; }
    if (typeof v === "number") { return true; }
    return String(v).trim() !== "";
  }
  function loadLocal() { try { var x = JSON.parse(sessionStorage.getItem(storeKey) || "null"); if (x) { local = x; } } catch (e) {} }
  function saveLocal() { try { sessionStorage.setItem(storeKey, JSON.stringify(local)); } catch (e) {} }
  function loadPrefs() { try { var x = JSON.parse(localStorage.getItem("smf-v2-prefs") || "null"); if (x) { prefs.read = !!x.read; } } catch (e) {} }
  function savePrefs() { try { localStorage.setItem("smf-v2-prefs", JSON.stringify({ read: prefs.read })); } catch (e) {} }

  function api(path, data) {
    var opts = data === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) };
    return fetch(base + path, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok) { var e = new Error(body.error || "That didn't save. Try again."); e.status = res.status; throw e; }
        return body;
      });
    });
  }

  // ------------------------------------------------------------------ reading what's stored
  function answer(key) { return S && S.answers ? S.answers[key] : undefined; }
  function holder(field) {                       // the object (or list) this field's parts live in
    var a = answer(field.key);
    if (field.path) { return a && typeof a === "object" ? a[field.path] : undefined; }
    return a;
  }
  function byId(list, id) { return (list || []).filter(function (x) { return x && x.id === id; })[0]; }
  // Answers that are a list on their own (what you can show; how people find you), not a list inside a group.
  var TOP_LISTS = ["show", "acquisition"];
  function itemsOf(field) {
    var h = answer(field.key);
    if (TOP_LISTS.indexOf(field.key) >= 0) { return Array.isArray(h) ? h : []; }
    if (field.kind === "story_card") { return ((h && h.stories) || []).filter(function (x) { return x.kind === field.story_kind; }); }
    return h && Array.isArray(h[field.list]) ? h[field.list] : [];
  }
  function live(list) { return (list || []).filter(function (x) { return x && !x.remove; }); }

  /* One field's state: "ok" confirmed, "check" a draft to look at, "skipped", "chat", or "wait".
     Several core fields share one answer (name, audience, voice); each shows its own part's state. */
  function stateOf(field) {
    if (local.chat[field.id]) { return "chat"; }
    if (field.id === "goal_platforms") { return goalPlatformsState(); }
    var parts = partsOf(field), statuses = [];
    parts.forEach(function (p) { if (p.has) { statuses.push(p.status); } });
    // One confirmed item never makes the question "Done" while others still wait for their own yes (a quote,
    // a drafted row). Question 29 keeps rev 12 N6's rule: it counts once the goal is answered.
    if (statuses.indexOf("confirmed") >= 0 && statuses.indexOf("unconfirmed") >= 0) { return "check"; }
    if (statuses.some(function (s) { return s === "confirmed"; })) { return "ok"; }
    if (statuses.some(function (s) { return s === "unconfirmed"; })) { return "check"; }
    if (statuses.some(function (s) { return s === "for_chat"; })) { return "chat"; }
    if (local.skip[field.id] || statuses.some(function (s) { return s === "skipped"; })) { return "skipped"; }
    if (field.kind === "beliefs" || field.kind === "story" || field.kind === "home" || field.kind === "foragainst") {
      var pos = answer("positioning");
      if (pos && pos.parked) { return "skipped"; }
    }
    if (field.group === "stand") { var p2 = answer("positioning"); if (p2 && p2.parked) { return "skipped"; } }
    return "wait";
  }
  // Question 29 in the five steps (rev 14, A3): done when what to make and the platforms are confirmed. The goal is
  // optional, but a draft of it still waiting keeps it at "please check". (How people find you is its own question
  // in Make it better since Oct 23, so a draft of it never holds step 4 back.)
  function goalPlatformsState() {
    var mk = answer("make"), pl = answer("platforms"), g = answer("goal");
    var waiting = [mk, pl, g].some(function (x) { return x && x.status === "unconfirmed"; });
    if (waiting) { return "check"; }
    // Confirmed and not emptied: at least one thing to make and one platform for someone.
    // Platforms count only for someone confirmed (and still there) in "Who speaks", as the build does.
    var who = live(answer("identities")).filter(function (x) { return x.status === "confirmed"; }).map(function (x) { return x.id || x.kind; });
    var plOk = pl && pl.status === "confirmed" && (Object.keys(pl.by_speaker || {}).some(function (k) { return who.indexOf(k) >= 0 && (pl.by_speaker[k] || []).length; }) || filled(pl.other));
    if (mk && mk.status === "confirmed" && filled(mk.value) && plOk) { return "ok"; }
    if ([mk, pl].some(function (x) { return x && x.status === "for_chat"; })) { return "chat"; }
    if (local.skip.goal_platforms || [mk, pl, g].some(function (x) { return x && x.status === "skipped"; })) { return "skipped"; }
    return "wait";
  }
  // [{has: answered?, status}] for each stored piece the field shows.
  function partsOf(field) {
    var out = [];
    function obj(o, names) {
      if (!o || typeof o !== "object") { return; }
      var has = names ? names.some(function (n) { return filled(o[n]); }) : true;
      if (o.status === "skipped" || o.status === "for_chat") { has = true; }
      out.push({ has: has, status: o.status });
    }
    function list(l) { live(l).forEach(function (x) { out.push({ has: true, status: x.status }); }); }
    var a = answer(field.key);
    switch (field.kind) {
      case "name": obj(a, ["value"]); break;
      case "object": obj(holder(field), field.parts.filter(function (p) { return !p.key; }).map(function (p) { return p.name; })); break;
      case "items": case "pairs": case "story_card":
        list(itemsOf(field));
        // No rows left: a question with its own answer is done or skipped by that answer (confirmed with none).
        if (field.own_status && !live(itemsOf(field)).length && a && a.status && a.status !== "unconfirmed") { obj(a); }
        break;
      case "proof": list(a && a.proof); break;
      case "identities": case "samples": if (Array.isArray(a)) { list(a); } break;
      case "beliefs": if (a) { obj(a.core_belief, ["value"]); list(a.contrarian); } break;
      case "foragainst": if (a) { list(a["for"]); list(a.against); } break;
      case "story": obj(holder(field), ["catalyst", "core_truth"]); if (holder(field)) { list(holder(field).proof); } break;
      case "home": if (a) { obj(a.home_medium, ["value"]); obj(a.stage, ["value"]); } break;
      case "rung": obj((Array.isArray(a) ? a : []).filter(function (r) { return r.rung === field.rung; })[0], ["name", "none_yet"]); break;
      case "rules": obj(a, ["industry", "never_claim", "never_name", "sign_off", "hated_words"]); break;
      case "colours": obj(a, ["background", "text", "accent"]); break;
      // Question 29 counts as answered once the goal is confirmed or skipped; its other parts keep their own state (N6).
      case "goal_platforms": obj(answer("goal"), ["value"]); break;
      case "filming": obj(a, ["where"]); if (a) { list(a.speakers); } break;
    }
    return out;
  }
  function quoteLine(it, yesId) {
    return '<div class="quote-row"><p class="quote-src small">Quoted from ' + esc(sourceLabel((it.refs || [])[0])) + "</p>" +
      '<button type="button" class="quote-yes" data-quote-yes' + (yesId ? ' id="' + yesId + '"' : "") + ' aria-pressed="false">Yes, these are my words</button></div>';
  }
  function quoteYes(el) { var b = el && el.querySelector("[data-quote-yes]"); return !!(b && b.getAttribute("aria-pressed") === "true"); }
  function quotesIn(field) {
    var a = answer(field.key) || {}, out = [];
    if (field.kind === "beliefs") { out = [a.core_belief].concat(live(a.contrarian)); }
    else if (field.never_draft && (field.kind === "items" || field.kind === "pairs")) { out = live(itemsOf(field)); }
    return out.filter(function (x) { return x && x.quoted && x.status === "unconfirmed"; });
  }
  function draftNote(field) {
    var q = quotesIn(field);
    if (q.length) {
      var names = q.map(function (x) { return sourceName((x.refs || [])[0]); }).filter(function (n, i, all) { return all.indexOf(n) === i; });
      return "Your own words from " + (names.length === 1 ? names[0] : "your own writing") + ". Please confirm each one.";
    }
    var h = field.kind === "object" || field.kind === "name" || field.kind === "story" ? holder(field) : null;
    var origin = h && h.origin, src = h && h.source;
    if (stateOf(field) !== "check") { return ""; }
    var pv = (answer("provenance") || {})[field.id] || {};
    origin = pv.origin || origin;
    var refs = (pv.refs || (h && h.refs) || []).filter(Boolean);
    var page = refs.length ? " (" + refs.slice(0, 2).map(refLabel).join(", ") + ")" : "";
    if (origin === "document" && refs.length && isSourceRef(refs[0])) { return "Drafted from " + sourceLabel(refs[0]) + ". Please check it."; }
    if (field.kind === "colours") {
      var ca = answer("colours") || {}, co = pv.origin || ca.origin;
      if (co === "website" || (ca.found || []).filter(hexOk).length) { return "Colours from your website" + page + ". Please check them."; }
      if (co === "document") { return "Colours from your document" + page + ". Please check them."; }
      return "Suggested palette. Please check it.";
    }
    if (origin === "starter-pack" || origin === "description") { var p = pack(); return p ? suggestedLabel(p) : "Suggested. Please check."; }
    // Read back from the brand (#43, gaps 4 and 10): what the brand already says, or what was changed in the chat.
    var grp = ["positioning", "teach", "deep"].indexOf(field.key) >= 0 ? (answer(field.key) || {}) : null;
    var inGroup = grp ? fieldParts(field).reduce(function (acc, p) { var v = grp[p]; return acc.concat(Array.isArray(v) ? live(v) : v ? [v] : []); }, []) : [];
    var mine = (h ? [h] : []).concat(inGroup, field.list || field.kind === "story_card" ? live(itemsOf(field)) : [],
      Array.isArray(answer(field.key)) ? live(answer(field.key)) : []).filter(function (x) { return x && x.origin === "brand" && x.status === "unconfirmed"; });
    if (mine.length) { return mine.some(function (x) { return x.changed_in_chat; }) ? "Changed in the chat since. Please check." : "From your brand. Please check."; }
    if (origin === "document" && !refs.length) { return "Drafted from your material (source not recorded). Please check it."; }
    if (origin === "website" && !refs.length) { return "Drafted from your website (source not recorded). Please check it."; }
    var where = { website: "your website" + page, document: "your document" + page, chat: "the chat", person: "you" }[origin] || "what you shared";
    return src === "draft" || src === "draft-edited" ? "Drafted from " + where + ". Please check it." : "Please check this.";
  }

  var CORE = function () { return F.core; };
  function confirmedCount() { return F.core.filter(function (f) { return stateOf(f) === "ok"; }).length; }
  function skippedCount() { return F.core.filter(function (f) { return stateOf(f) === "skipped"; }).length; }
  function open() { return F.core.filter(function (f) { var s = stateOf(f); return s !== "ok"; }); }
  // Plain words, one colour each (design review, Oct 16: the orange and grey chips "looked like a please check thing").
  var LABEL = { wait: "Not answered yet", check: "Suggested, please check", quote: "Your words, please confirm", ok: "Done", skipped: "Skipped", chat: "For the chat", typed: "Not confirmed yet" };
  function isQuote(field) { return stateOf(field) === "check" && quotesIn(field).length > 0; }
  // Rev 14 (design review: remove, don't explain): no colour coding. A done question shows a quiet check mark; anything
  // waiting says what it needs in words on the screen itself (the draft note, "not confirmed yet").
  function chip(field, live) {
    var s = (live || typed(field)) ? "typed" : stateOf(field);
    return '<span class="chip s-' + s + '" data-chip="' + field.id + '"' + (s === "ok" ? ">\u2713 Done" : ">") + "</span>";
  }
  function chipKey() { return ""; }

  // ------------------------------------------------------------------ starter packs (rev 12, N3)
  // Suggestions by type of business. A pack only suggests what's general to a trade; nothing counts until
  // the owner keeps it, and questions, objections and steps only ever get ideas, never answers.
  function words(t) { return " " + String(t || "").toLowerCase().replace(/[^a-z0-9&]+/g, " ") + " "; }
  function matchPack(text) {
    var w = words(text), best = null, len = 0;
    ((P && P.packs) || []).forEach(function (p) {
      (p.matches || []).forEach(function (m) {
        var m2 = words(m).replace(/^ +| +$/g, ""); if (!m2) { return; }
        m2 = " " + m2 + " ";
        if (w.indexOf(m2) >= 0 && m2.length > len) { best = p; len = m2.length; }
      });
    });
    return best;
  }
  function packById(id) { return ((P && P.packs) || []).filter(function (p) { return p.id === id; })[0]; }
  // The pack in use: a bundled one, or "custom" (Claude's suggestions from the owner's own description).
  function pack() {
    var sp = answer("starter_pack");
    if (!sp || !sp.id || sp.status === "skipped") { return null; }
    if (sp.id === "custom") {
      var c = sp.suggestions || {};
      return { id: "custom", name: "what you told us", custom: true, suggestions: c.suggestions || {}, topic_ideas: c.topic_ideas || {},
               palettes: c.palettes || [], font_pair: c.font_pair, video_ideas: c.video_ideas || [], compliance_candidate: c.compliance_candidate };
    }
    return packById(sp.id);
  }
  function generator(p) { return p.custom ? "claude-from-description" : "pack:" + p.id + "@" + ((P && P.version) || 1); }
  function suggestedLabel(p) { return p.custom ? "Suggested from what you told us. Please check." : "Suggested for " + p.name + ". Please check."; }
  function allowed(field) {
    var id = field.id === "goal_platforms" ? "platforms" : field.id;
    return P && (P.allowlist || []).indexOf(id) >= 0 && !field.never_draft;
  }
  function suggestionFor(field) {
    var p = pack(); if (!p || !allowed(field)) { return null; }
    var key = field.id === "goal_platforms" ? "platforms" : field.id;
    var s = (p.suggestions || {})[key];
    return s && (!Array.isArray(s) || s.length) ? s : null;
  }
  function ideasFor(field) {
    var p = pack(); if (!p || !P || (P.topic_fields || []).indexOf(field.id) < 0) { return null; }
    var s = (p.topic_ideas || {})[field.id];
    return s && s.length ? s : null;
  }
  function choosePack(id, how) {
    var p = id === "none" ? null : packById(id), old = answer("starter_pack") || {};
    var sp = id === "none" ? { status: "skipped", source: "typed", origin: "person" }
      : { id: id, version: (P && P.version) || 1, status: how === "picked" ? "confirmed" : "unconfirmed", source: "typed", origin: "person" };
    if (id === "custom" && old.suggestions) { sp.suggestions = old.suggestions; }
    // Platforms a pack suggests wait, unassigned, until the owner says who posts where (N6). Switching replaces
    // only the ones nobody has acted on; anything confirmed stays.
    var kept = (answer("platform_candidates") || []).filter(function (c) { return c.status !== "unconfirmed"; });
    var fresh = p ? (p.suggestions.platforms || []).filter(function (pl) { return !kept.some(function (c) { return c.platform === pl; }); }).map(function (pl) {
      return { platform: pl, status: "unconfirmed", source: "draft", origin: "starter-pack", generator: generator(p) }; }) : [];
    return api("answer", { key: "starter_pack", answer: sp })
      .then(function () { return api("answer", { key: "platform_candidates", answer: kept.concat(fresh) }); })
      .then(function (s) { S = s; if (UI.packChanged) { UI.packChanged(); } });
  }
  function packLineHTML() {
    var p = pack();
    return '<div class="packline" id="packline">' + (p ? "Suggestions for <b>" + esc(p.name) + "</b>" : "No suggestions by type of business") +
      ' <button type="button" class="link" id="pack-change">' + (p ? "Change" : "Choose one") + "</button></div>";
  }
  function packPickerHTML() {
    var cur = pack();
    return '<div class="picker" role="group" aria-label="Type of business">' + ((P && P.packs) || []).map(function (p) {
      return '<button type="button" class="packcard" data-pack="' + esc(p.id) + '" aria-pressed="' + (cur && cur.id === p.id) + '"><b>' + esc(p.name) + "</b>" +
        '<span class="small">' + esc((p.video_ideas || [])[0] || "") + "</span></button>";
    }).join("") + '<button type="button" class="packcard" data-pack="none" aria-pressed="' + (!cur) + '"><b>Something else</b><span class="small">' +
      (cur && cur.custom ? "Keeping Claude's suggestions from what you told us" : "No suggestions; Claude can suggest some in the chat") + "</span></button></div>";
  }
  function wirePackPicker(root, done) {
    root.querySelectorAll("[data-pack]").forEach(function (b) {
      b.onclick = function () {
        var id = b.getAttribute("data-pack"), sp = answer("starter_pack") || {};
        if (id === "none" && sp.id === "custom") { return done && done(); }      // keep Claude's own suggestions
        choosePack(id, "picked").then(function () { if (done) { done(); } });
      };
    });
  }

  // ------------------------------------------------------------------ drawing a field
  function fid(field, part) { return "f-" + field.id + (part ? "-" + part : ""); }
  function textInput(id, label, value, type) {
    if (type === "longtext" || type === "lines") {
      var v = Array.isArray(value) ? value.join("\n") : (value || "");
      return '<label class="f" for="' + id + '">' + esc(label) + '</label><textarea id="' + id + '" rows="' + (type === "lines" ? 3 : 3) + '" data-talk>' + esc(v) + "</textarea>";
    }
    if (type === "number") {
      return '<label class="f" for="' + id + '">' + esc(label) + '</label><input type="number" min="0" step="1" inputmode="numeric" id="' + id + '" value="' + esc(value == null ? "" : value) + '">';
    }
    return '<label class="f" for="' + id + '">' + esc(label) + '</label><input type="text" id="' + id + '" value="' + esc(value || "") + '" data-talk>';
  }
  function choiceRow(id, label, options, value, multi) {
    var vals = multi ? (value || []) : [value];
    return '<div class="f">' + esc(label) + '</div><div class="choices" role="group" aria-label="' + esc(label) + '" id="' + id + '" data-multi="' + (multi ? "1" : "") + '">' +
      options.map(function (o) {
        return '<button type="button" class="choice" data-val="' + esc(o.id) + '" aria-pressed="' + (vals.indexOf(o.id) >= 0) + '">' + esc(o.label) +
          (o.hint ? ' <span class="hint">(' + esc(o.hint) + ")</span>" : "") + "</button>";
      }).join("") + "</div>";
  }
  // collapsed: with nothing saved yet, the first row waits hidden behind the add button.
  function itemRows(field, list, parts, max, collapsed) {
    var rows = live(list), hide = false;
    if (!rows.length) { rows = [{ id: "" }]; hide = !!collapsed; }
    return '<div class="items" id="' + fid(field, "items") + '">' + rows.map(function (it, i) {
      return '<div class="item" data-id="' + esc(it.id || "") + '"' + (hide ? " hidden" : "") + ">" + parts.map(function (p) {
        return textInput(fid(field, "i" + i + "-" + p.name), p.label + (rows.length > 1 ? " " + (i + 1) : ""), it[p.name], p.type || "text");
      }).join("") + (it.quoted && it.status === "unconfirmed" ? quoteLine(it) : "") + '<button type="button" class="link small" data-remove>Remove</button></div>';
    }).join("") + "</div>" +
      (max && rows.length >= max && !hide ? "" : '<button type="button" class="link" data-add>' + esc(collapsed || "Add another") + "</button>");
  }
  var EXP = { name: "experience", label: "What experience taught you this? (optional)", type: "longtext" };

  function body(field) {
    var a = answer(field.key), h = holder(field) || {};
    switch (field.kind) {
      case "name":
        return textInput(fid(field, "value"), "Brand name", h.value) +
          '<p class="spelled" id="' + fid(field, "spelled") + '" aria-live="polite">' + spell(h.value) + "</p>";
      case "object":
        var marked = false;
        return field.parts.map(function (p) {
          var src = p.key ? answer(p.key) : h, v = src ? src[p.name] : undefined;
          if (p.type === "choice" || p.type === "multi") { return choiceRow(fid(field, p.name), p.label, p.options, v, p.type === "multi"); }
          var out = textInput(fid(field, p.name), p.label, v, p.type);
          if (!marked) { marked = true; out += "<!--assist-->"; }
          return out;
        }).join("");
      case "items":
        return itemRows(field, itemsOf(field), field.item_parts, field.max);
      case "pairs":
        return itemRows(field, itemsOf(field), [{ name: "others", label: "What others do" }, { name: "us", label: "What you do instead" }], field.max);
      case "beliefs":
        var p = a || {}, cb = p.core_belief || {};
        return (quotesIn(field).length ? "" : '<p class="own">In your own words, or quoted from your own writing. Claude never makes these up for you.</p>') +
          textInput(fid(field, "core"), "Your belief, in one sentence", cb.value, "longtext") +
          (cb.quoted && cb.status === "unconfirmed" ? '<div id="' + fid(field, "core-quote") + '">' + quoteLine(cb) + "</div>" : "") +
          textInput(fid(field, "core-exp"), EXP.label, cb.experience, "longtext") +
          itemRows(field, p.contrarian, [{ name: "value", label: "Another belief" }, EXP], 3, "Add another belief (up to three more)");
      case "foragainst":
        var q = a || {};
        return '<div class="f sub">Known for (up to two)</div>' +
          itemRows({ id: field.id + "-for" }, q["for"], [{ name: "value", label: "Known for" }, EXP], 2) +
          '<div class="f sub">Against (up to two)</div>' +
          itemRows({ id: field.id + "-against" }, q.against, [{ name: "value", label: "Against" }, EXP], 2);
      case "story":
        return textInput(fid(field, "catalyst"), "What you saw that others didn't", h.catalyst, "longtext") +
          textInput(fid(field, "core_truth"), "What you believe because of it", h.core_truth, "longtext") +
          '<div class="f sub">How you’ve proved it</div>' +
          itemRows(field, h.proof, [{ name: "value", label: "Proof" }]);
      case "home":
        var r = a || {};
        return choiceRow(fid(field, "medium"), "Most at home in", [{ id: "video", label: "Video (short or long)" }, { id: "audio", label: "Audio" }, { id: "writing", label: "Writing" }, { id: "images", label: "Images" }], (r.home_medium || {}).value) +
          choiceRow(fid(field, "stage"), "Followers on your biggest platform", [{ id: "under_100k", label: "Under 100,000" }, { id: "100k_1m", label: "100,000 to 1 million" }, { id: "1m_10m", label: "1 to 10 million" }, { id: "10m_plus", label: "Over 10 million" }], (r.stage || {}).value);
      case "rung":
        var rung = (Array.isArray(a) ? a : []).filter(function (x) { return x.rung === field.rung; })[0] || {};
        return '<label class="check row-check"><input type="checkbox" id="' + fid(field, "none") + '"' + (rung.none_yet ? " checked" : "") + "> None yet</label>" +
          '<div id="' + fid(field, "fields") + '"' + (rung.none_yet ? " hidden" : "") + ">" +
          textInput(fid(field, "name"), "Its name", rung.name) + textInput(fid(field, "line"), "One line on what it is", rung.line) +
          (field.rung === "free" ? "" : textInput(fid(field, "price"), "Price (optional): an amount, “varies” or “not set yet”", rung.price)) + "</div>";
      case "rules":
        var ru = a || {};
        return choiceRow(fid(field, "industry"), "Your industry", [{ id: "none", label: "None of these" }, { id: "health", label: "Health or wellness" }, { id: "finance", label: "Finance" }, { id: "legal", label: "Legal" }, { id: "other", label: "Something else" }], ru.industry) +
          textInput(fid(field, "never_claim"), "Claims you never make (one per line)", ru.never_claim, "lines") +
          textInput(fid(field, "never_name"), "People or businesses you never name (one per line)", ru.never_name, "lines") +
          textInput(fid(field, "hated_words"), "Words you never use (one per line)", ru.hated_words, "lines") +
          textInput(fid(field, "sign_off"), "Who checks posts before they go out (one per line)", ru.sign_off, "lines");
      case "colours":
        var c = a || {}, found = (c.found || []).filter(hexOk);
        // From the website: swatches to pick from (spec rev 11, "Colours and look"). The person decides which
        // colour plays which part; nothing is assigned for them.
        var picker = found.length ? '<div class="f">From your website: choose which part you\'re setting, then tap a colour</div>' +
            choiceRow(fid(field, "role"), "Setting", [{ id: "background", label: "Background" }, { id: "text", label: "Main text" }, { id: "accent", label: "The one people remember" }], "background") +
            '<div class="swatches" id="' + fid(field, "found") + '">' + found.map(function (h) {
              return '<button type="button" class="swatch" data-hex="' + esc(h.toUpperCase()) + '" style="background:' + esc(h) + '" aria-label="Use ' + esc(h.toUpperCase()) + '"></button>';
            }).join("") + "</div>" : "";
        var pk = pack(), packPal = pk && pk.palettes && pk.palettes.length ? '<div class="f">' + esc(pk.custom ? "Palettes suggested from what you told us" : "Palettes suggested for " + pk.name) + "</div>" +
            '<div class="palettes" id="' + fid(field, "packpal") + '">' + pk.palettes.map(function (pl, i) {
              return '<button type="button" class="palette" data-i="' + i + '" aria-label="Use suggested palette ' + (i + 1) + '">' +
                ["background", "text", "accent"].map(function (k) { return '<span style="background:' + esc(pl[k]) + '"></span>'; }).join("") + "</button>";
            }).join("") + "</div>" : "";
        // A mood word steers the generator (design review, Oct 10: "type in what you want, like, bold"). All on this computer.
        var mood = '<div class="row"><label class="f" for="' + fid(field, "mood") + '" style="margin:0">Mood</label>' +
            '<select id="' + fid(field, "mood") + '"><option value="">Any</option><option>calm</option><option>bold</option><option>warm</option><option>clean</option></select>' +
            '<button type="button" id="' + fid(field, "palette") + '">Give me a palette</button></div>';
        // One way to choose first: the website's colours, else the palettes for the type of business, else the generator.
        var lead = picker || packPal || mood, more = [picker ? packPal : "", lead === mood ? "" : mood].join("");
        var nm2 = (answer("name") || {}).value || "Your brand";
        return '<div class="preview" aria-label="Sample preview"><span class="small">Sample preview, not your real content</span>' +
            '<div class="pv" id="' + fid(field, "preview") + '"><b class="pvname">' + esc(nm2) + '</b><span class="pvline">This is how a post could look.</span><span class="pvbtn">Book now</span></div>' +
            '<p class="small" id="' + fid(field, "contrast") + '" aria-live="polite"></p></div>' +
          lead + '<span class="small" id="' + fid(field, "palette-note") + '" aria-live="polite"></span>' +
          '<details class="more"><summary>More ways to choose</summary>' + more +
          '<div class="f sub">Set each colour yourself</div><div class="colours">' + [["background", "Background", c.background || "#FFFFFF"], ["text", "Main text", c.text || "#111111"], ["accent", "The one people remember", c.accent || "#C2410C"]].map(function (j) {
          return '<div class="colour"><label class="f" for="' + fid(field, j[0]) + '">' + j[1] + '</label><div class="row">' +
            '<input type="color" aria-label="' + j[1] + ' picker" id="' + fid(field, j[0] + "-pick") + '" value="' + esc(j[2]) + '">' +
            '<input type="text" class="hex" id="' + fid(field, j[0]) + '" value="' + esc(j[2]) + '" maxlength="7" spellcheck="false"></div></div>';
        }).join("") + "</div>" + fontsHTML(field) + "</details>";
      case "goal_platforms":
        var g = answer("goal") || {}, pl = answer("platforms") || {}, mk = answer("make") || {};
        var speakers = (Array.isArray(answer("identities")) ? answer("identities") : []).filter(function (x) { return x.name && x.status === "confirmed" && !x.remove; });
        var PLAT = [{ id: "linkedin", label: "LinkedIn" }, { id: "instagram", label: "Instagram" }, { id: "facebook", label: "Facebook" }, { id: "tiktok", label: "TikTok" }, { id: "youtube", label: "YouTube" }, { id: "twitter", label: "X" }];
        return choiceRow(fid(field, "make"), "What you want help with", [{ id: "posts", label: "Written posts" }, { id: "visuals", label: "Carousels and cards", hint: "swipe-through posts" }, { id: "short-form-scripts", label: "Short video scripts" }, { id: "clips", label: "Clips from recordings" }, { id: "descriptions", label: "Video descriptions" }, { id: "long-form-youtube", label: "Long YouTube videos" }, { id: "scheduling", label: "Scheduling" }, { id: "research", label: "Research" }], mk.value, true) + partState(field, "make", mk) +
          (speakers.length ? speakers.map(function (sp) {
            var sid = sp.id || sp.kind;
            return choiceRow(fid(field, "plat-" + sid), "Where " + (sp.kind === "person" && speakers.length === 1 ? "you post" : sp.name + " posts"), PLAT, (pl.by_speaker || {})[sid], true);
          }).join("") : '<p class="note">First tell us who speaks in your posts (the question before this one), then choose where they post.</p>') +
          textInput(fid(field, "plat-other"), "Somewhere else?", pl.other) + partState(field, "platforms", pl) +
          '<p class="kicker" style="margin-top:14px">Optional</p>' +
          choiceRow(fid(field, "goal"), "What a win looks like", [{ id: "reach", label: "More people seeing it" }, { id: "leads", label: "More inquiries" }, { id: "authority", label: "Being the trusted name" }], g.value) + partState(field, "goal", g);
      case "identities":
        var list = Array.isArray(a) ? a : [], kinds = list.map(function (x) { return x.kind; });
        return choiceRow(fid(field, "kinds"), "Who speaks (tap all that apply)", [{ id: "person", label: "Me, a person" }, { id: "company", label: "The company" }, { id: "other", label: "Something else" }], kinds, true) +
          '<div id="' + fid(field, "people") + '">' + list.map(function (x) { return identityRow(field, x); }).join("") + "</div>";
      case "samples":
        var ss = Array.isArray(a) && a.length ? a : [{ text: "", source: "typed" }];
        return '<div class="items" id="' + fid(field, "items") + '">' + ss.map(function (s, i) {
          return '<div class="item" data-source="' + esc(s.source || "typed") + '">' + textInput(fid(field, "s" + i), "Sample " + (i + 1) + (s.source === "spoken" ? " (spoken)" : ""), s.text, "longtext") +
            '<button type="button" class="link small" data-remove>Remove</button></div>';
        }).join("") + '</div><button type="button" class="link" data-add>Add another sample</button>';
      case "story_card":
        var st = itemsOf(field)[0] || {};
        return textInput(fid(field, "text"), "The story", st.text, "longtext");
      case "filming":
        // Optional, not counted (rev 12, N6): who speaks in the videos, on camera or as a voice-over, and where.
        var fm = a || {}, ppl = (Array.isArray(answer("identities")) ? answer("identities") : []).filter(function (x) { return x.name; });
        var MODES = [{ id: "on_camera", label: "On camera" }, { id: "voice_over", label: "Voice-over only" }, { id: "not_in_videos", label: "Not in videos" }];
        return (ppl.length ? ppl.map(function (sp) {
          var cur = byId(fm.speakers, sp.id || sp.kind) || {};
          return choiceRow(fid(field, "mode-" + (sp.id || sp.kind)), sp.name, MODES, cur.mode);
        }).join("") : '<p class="small">Add who speaks (question 8) first, or skip this for now.</p>') +
          textInput(fid(field, "where"), "Where would you film? (optional)", fm.where);
      case "proof":
        var pr = live((a && a.proof) || []);
        if (!pr.length) { pr = [{ id: "" }]; }
        return '<div class="items" id="' + fid(field, "items") + '">' + pr.map(function (it, i) { return proofCard(field, it, i); }).join("") +
          '</div><button type="button" class="link" data-add>Add another</button>';
    }
    return "";
  }
  // One piece of proof, as Caleb Ralston's Credibility Bank (six short parts), or the Interest Bank for people
  // without big wins yet: what they're learning or testing, recorded the same way, never passed off as expertise.
  var PROOF_PARTS = [["title", "In a few words, what is it?", "text"], ["context", "Who and what was going on", "longtext"],
    ["problem", "The real problem (not the symptom)", "longtext"], ["insight", "What changed your thinking", "longtext"],
    ["approach", "What you did", "longtext"], ["outcome", "What happened", "longtext"], ["lesson", "The lesson someone else can use", "longtext"],
    ["source_text", "Where it's from: a file, a link, a date, a person", "text"]];
  function proofCard(field, it, i) {
    var p = fid(field, "i" + i);
    return '<div class="item proof" data-id="' + esc(it.id || "") + '">' +
      choiceRow(p + "-bank", "Is this…", [{ id: "credibility", label: "A real result or piece of evidence" }, { id: "interest", label: "Something I'm learning or testing" }], it.bank || "credibility") +
      PROOF_PARTS.map(function (pp) { return textInput(p + "-" + pp[0], pp[1], it[pp[0]], pp[2]); }).join("") +
      choiceRow(p + "-known_from", "How do you know it?", [{ id: "own_account", label: "My own account" }, { id: "document", label: "A document or screenshot I have" }, { id: "public_source_checked", label: "A public source" }], it.known_from || "own_account") +
      choiceRow(p + "-may_publish", "May it be published?", [{ id: "no", label: "Not yet" }, { id: "anonymised", label: "Yes, without names" }, { id: "yes", label: "Yes" }], it.may_publish || "no") +
      '<button type="button" class="link small" data-remove>Remove</button></div>';
  }
  // Fonts (rev 12, N5): optional and not counted. Only fonts already on this computer are shown as samples;
  // nothing is downloaded. How fonts are drawn on pictures stays with the picture tools (Ho's area).
  var FONTS = ["Arial", "Arial Black", "Helvetica", "Verdana", "Tahoma", "Trebuchet MS", "Segoe UI", "Georgia",
               "Times New Roman", "Garamond", "Palatino Linotype", "Impact", "Courier New"];
  function fontsHTML(field) {
    var f = answer("fonts") || {}, pk = pack(), fp = pk && pk.font_pair;
    function sel(part, label) {
      var cur = f[part] || "";
      return '<div class="fontpick"><label class="f" for="' + fid(field, "font-" + part) + '">' + label + '</label><select id="' + fid(field, "font-" + part) + '">' +
        '<option value="">No preference</option>' + (cur && FONTS.indexOf(cur) < 0 ? "<option selected>" + esc(cur) + "</option>" : "") + FONTS.map(function (n) { return "<option" + (n === cur ? " selected" : "") + ">" + esc(n) + "</option>"; }).join("") +
        '</select><p class="fontsample" id="' + fid(field, "font-" + part + "-sample") + '"' + (cur ? ' style="font-family:\'' + esc(cur) + '\'"' : "") + ">The quick brown fox jumps over the lazy dog</p></div>";
    }
    return '<details class="fonts"' + (f.heading || f.body ? " open" : "") + '><summary>Fonts (optional)</summary>' +
      (fp ? '<p class="small">' + esc(pk.custom ? "Suggested" : "Suggested for " + pk.name) + ": " + esc(fp.heading) + " for headings, " + esc(fp.body) + ' for text. <button type="button" class="link" id="' + fid(field, "font-use") + '">Use these</button></p>' : "") +
      '<div class="fontrow">' + sel("heading", "Headings") + sel("body", "Text") + "</div>" +
      '<p class="small">If a sample looks plain, that font isn\'t on this computer yet; your choice is still saved.</p></details>';
  }
  // A pack's platforms wait, unassigned, until the owner taps them in for a speaker (rev 12, N6).
  function platformSuggestHTML(field, speakers) {
    var pk = pack(), pl = (pk && pk.suggestions && pk.suggestions.platforms) || [];
    if (!pl.length) { return ""; }
    var names = { linkedin: "LinkedIn", instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok", youtube: "YouTube", twitter: "X" };
    return '<div class="suggest"><p class="small"><b>' + esc(suggestedLabel(pk)) + "</b> " + pl.map(function (x) { return names[x] || x; }).join(", ") + "</p>" +
      '<div class="row">' + speakers.map(function (sp) {
        var sid = sp.id || sp.kind;
        return '<button type="button" data-plat-apply="' + esc(sid) + '">' + (sid === "you" ? "Tap these in for me" : "Tap these in for " + esc(sp.name)) + "</button>";
      }).join("") + "</div></div>";
  }
  // "Draft this for me" (N4) and the idea lists (N3), drawn under the question on request.
  function suggestHTML(field) {
    var s = suggestionFor(field), ideas = ideasFor(field), pk = pack();
    if (field.id === "colours") { s = null; }      // palettes and fonts are shown inside the question itself
    var out = "";
    if (s) { out += '<span class="small">Not sure?</span><button type="button" class="draftme" data-act="suggest" aria-expanded="false">Draft this for me</button>'; }
    if (ideas) { out += '<button type="button" class="link" data-act="ideas" aria-expanded="false">Ideas for ' + esc(pk.custom ? "your business" : pk.name) + "</button>"; }
    if (field.id === "rules" && pk && pk.compliance_candidate) {
      out += '<div class="suggest"><p class="small">Businesses like yours often follow <b>' + esc(pk.compliance_candidate) + "</b> rules. " +
        '<button type="button" class="link" data-act="compliance">This applies to my business</button></p></div>';
    }
    return out ? '<div class="assist">' + out + '</div><div class="suggest-panel" id="' + fid(field, "suggest") + '" hidden></div>' : "";
  }
  function disclaimer() { return '<p class="disclaimer small">Not reviewed by a lawyer: check with someone qualified if your industry is regulated. These are starting points, not a full compliance check.</p>'; }
  function showSuggestion(field, btn) {
    var panel = $(fid(field, "suggest")), pk = pack(), s = suggestionFor(field);
    if (!panel || !s) { return; }
    if (!panel.hidden && panel.getAttribute("data-mode") === "suggest") { panel.hidden = true; btn.setAttribute("aria-expanded", "false"); return; }
    panel.setAttribute("data-mode", "suggest"); btn.setAttribute("aria-expanded", "true");
    var head = '<p class="draft">' + esc(suggestedLabel(pk)) + "</p>";
    if (field.id === "goal_platforms") {
      var sp2 = (Array.isArray(answer("identities")) ? answer("identities") : []).filter(function (x) { return x.name; });
      if (!sp2.length) { sp2 = [{ id: "you", kind: "person", name: "You" }]; }
      panel.innerHTML = platformSuggestHTML(field, sp2) + '<p class="small">Nothing is saved until you tap Confirm.</p>';
      wirePlatformApply(field, panel);
      panel.hidden = false; return;
    }
    if (field.kind === "items") {
      // Myths and mistakes: kept only when the owner has really seen them; otherwise they stay as post ideas.
      var q = field.id === "myths" ? "Have you heard customers believe this?" : "Have you seen customers make this mistake?";
      panel.innerHTML = head + '<ul class="ideas">' + s.map(function (t, i) {
        return '<li data-i="' + i + '"><span>' + esc(t) + '</span><span class="small">' + q + '</span><span class="row"><button type="button" data-yes>Yes, keep it</button>' +
          '<button type="button" data-no>No, save as a post idea</button></span></li>';
      }).join("") + "</ul>";
      panel.querySelectorAll("li").forEach(function (li) {
        var t = s[+li.getAttribute("data-i")];
        li.querySelector("[data-yes]").onclick = function () { addRow(field, t, generator(pk)); li.innerHTML = '<span class="small">Added below. Edit it into your own words, then Confirm.</span>'; };
        li.querySelector("[data-no]").onclick = function () { saveIdea(field, t, generator(pk)).then(function () { li.innerHTML = '<span class="small">Saved as a post idea.</span>'; }); };
      });
    } else {
      var text = Array.isArray(s) ? s.join("\n") : s;
      var part = field.parts && field.parts[0], el = part && $(fid(field, part.name));
      if (field.id === "rules") { el = $(fid(field, "never_claim")); }
      var empty = el && !el.value.trim();
      panel.innerHTML = head + '<p class="candidate">' + esc(text).replace(/\n/g, "<br>") + "</p>" + (field.id === "rules" ? disclaimer() : "") +
        '<div class="row">' + (empty ? '<button type="button" class="main" data-use>Use these words</button>' :
          '<button type="button" data-add>Add to mine</button><button type="button" data-instead>Use instead</button>') +
        '<button type="button" class="link" data-dismiss>Dismiss</button></div>' +
        '<p class="small">Nothing is saved until you tap Confirm. Edit anything first.</p>';
      var put = function (how) {
        if (!el) { return; }
        el.setAttribute("data-before", el.value);
        el.value = how === "add" && el.value.trim() ? el.value.replace(/\s+$/, "") + "\n" + text : text;
        el.removeAttribute("data-gen"); el.removeAttribute("data-edited"); el.removeAttribute("data-mixed");
        el.dispatchEvent(new Event("input"));           // before marking it, so placing the words isn't an edit
        el.setAttribute("data-gen", generator(pk)); el.setAttribute("data-origin", pk.custom ? "description" : "starter-pack");
        if (how === "add" && el.getAttribute("data-before").trim()) { el.setAttribute("data-mixed", "1"); }    // mixed with their own words
        panel.innerHTML = head + '<p class="small">In the box above. Check it and make it yours, then Confirm. <button type="button" class="link" data-undo>Undo</button></p>' + (field.id === "rules" ? disclaimer() : "");
        panel.querySelector("[data-undo]").onclick = function () { el.value = el.getAttribute("data-before") || ""; el.removeAttribute("data-gen"); el.removeAttribute("data-origin"); el.removeAttribute("data-mixed"); el.removeAttribute("data-edited"); el.dispatchEvent(new Event("input")); panel.hidden = true; };
        el.focus();
      };
      if (panel.querySelector("[data-use]")) { panel.querySelector("[data-use]").onclick = function () { put("use"); }; }
      if (panel.querySelector("[data-add]")) { panel.querySelector("[data-add]").onclick = function () { put("add"); }; }
      if (panel.querySelector("[data-instead]")) { panel.querySelector("[data-instead]").onclick = function () { put("instead"); }; }
      panel.querySelector("[data-dismiss]").onclick = function () { panel.hidden = true; btn.setAttribute("aria-expanded", "false"); };
    }
    panel.hidden = false;
  }
  // Ideas for questions only the owner can answer (6, 7, 22): post ideas, or a nudge to write it their way.
  function showIdeas(field, btn) {
    var panel = $(fid(field, "suggest")), pk = pack(), ideas = ideasFor(field);
    if (!panel || !ideas) { return; }
    if (!panel.hidden && panel.getAttribute("data-mode") === "ideas") { panel.hidden = true; btn.setAttribute("aria-expanded", "false"); return; }
    panel.setAttribute("data-mode", "ideas"); btn.setAttribute("aria-expanded", "true");
    var ask = field.id === "steps" ? "Do you do it this way?" : "Has this come up with your customers?";
    panel.innerHTML = '<p class="small">Ideas only. This question needs your own words, the way it really happens for you.</p><ul class="ideas">' + ideas.map(function (t, i) {
      return '<li data-i="' + i + '"><span>' + esc(t) + '</span><span class="small">' + ask + '</span><span class="row"><button type="button" data-mine>Yes, I\'ll write it my way</button>' +
        '<button type="button" data-idea>Save as a post idea</button></span></li>';
    }).join("") + "</ul>";
    panel.querySelectorAll("li").forEach(function (li) {
      var t = ideas[+li.getAttribute("data-i")];
      li.querySelector("[data-mine]").onclick = function () {
        prompted[field.id] = { generator: generator(pk), idea: t };
        if (field.kind === "items") { addRow(field, "", null); }
        else { var el = $(fid(field, field.parts[0].name)); if (el) { if (el.value.trim()) { el.value = el.value.replace(/\s+$/, "") + "\n"; } el.focus(); } }
        li.innerHTML = '<span class="small">Write it the way your customers say it, or the way you really do it.</span>';
      };
      li.querySelector("[data-idea]").onclick = function () { saveIdea(field, t, generator(pk)).then(function () { li.innerHTML = '<span class="small">Saved as a post idea.</span>'; }); };
    });
    panel.hidden = false;
  }
  var prompted = {};            // per question: the idea that prompted the owner's own answer (kept as prompted_by)
  function addRow(field, text, gen) {
    var items = $(fid(field, "items")); if (!items) { return; }
    var rows = items.querySelectorAll(".item"), last = rows[rows.length - 1];
    var lastEmpty = last && Array.prototype.every.call(last.querySelectorAll("input, textarea"), function (e) { return !e.value.trim(); });
    if (!lastEmpty) { var add = items.nextElementSibling; if (add && add.hasAttribute("data-add")) { add.click(); } rows = items.querySelectorAll(".item"); last = rows[rows.length - 1]; }
    var box = last.querySelector("input, textarea");
    if (box) { box.value = text; box.focus(); }
    if (gen) { last.setAttribute("data-gen", gen); last.setAttribute("data-origin", gen.indexOf("pack:") === 0 ? "starter-pack" : "description"); last.setAttribute("data-text", text); }
  }
  function saveIdea(field, text, gen) {
    var list = (answer("topic_ideas") || []).slice(), n = list.length + 1;
    while (byId(list, "idea-" + n)) { n++; }
    list.push({ id: "idea-" + n, field: field.id, text: text, status: "confirmed", source: "draft", origin: gen.indexOf("pack:") === 0 ? "starter-pack" : "description", generator: gen });
    return api("answer", { key: "topic_ideas", answer: list }).then(function (s) { S = s; });
  }
  // A readable palette made here, with no internet: light background, dark text, an accent that stands out.
  function hsl(h, s, l) {
    s /= 100; l /= 100;
    var k = function (n) { return (n + h / 30) % 12; }, a = s * Math.min(l, 1 - l);
    var f = function (n) { return Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1))))); };
    return "#" + [f(0), f(8), f(4)].map(function (x) { return ("0" + x.toString(16)).slice(-2); }).join("").toUpperCase();
  }
  // A mood word steers it: calm (soft, cool), bold (strong accent), warm (reds and golds), clean (near-white, crisp).
  var MOODS = { calm: { hues: [150, 240], sat: [25, 45], light: [38, 48] }, bold: { hues: [0, 360], sat: [75, 95], light: [40, 48] },
                warm: { hues: [0, 50], sat: [60, 85], light: [38, 48] }, clean: { hues: [190, 230], sat: [55, 80], light: [36, 46] } };
  function palette(mood) {
    var m = MOODS[mood];
    for (var tries = 0; tries < 60; tries++) {
      var h = Math.floor(Math.random() * 360), ha = (h + 150 + Math.floor(Math.random() * 60)) % 360;
      if (m) { ha = m.hues[0] + Math.floor(Math.random() * (m.hues[1] - m.hues[0])); h = (ha + 180 + Math.floor(Math.random() * 40)) % 360; }
      var bg = hsl(h, mood === "clean" ? 5 + Math.random() * 10 : 20 + Math.random() * 25, 95 + Math.random() * 3), tx = hsl(h, 25 + Math.random() * 20, 12 + Math.random() * 6);
      var ac = m ? hsl(ha, m.sat[0] + Math.random() * (m.sat[1] - m.sat[0]), m.light[0] + Math.random() * (m.light[1] - m.light[0]))
        : hsl(ha, 55 + Math.random() * 25, 38 + Math.random() * 10);
      if (contrast(bg, tx) >= 7 && contrast(bg, ac) >= 3) { return { background: bg, text: tx, accent: ac }; }
    }
    return { background: "#FAF7F2", text: "#1C1917", accent: "#B45309" };
  }
  function identityRow(field, x) {
    var k = x.kind, label = { person: "The person", company: "The company", other: "Something else" }[k];
    return '<div class="item identity" data-kind="' + k + '"><div class="f sub">' + label + "</div>" +
      textInput(fid(field, k + "-name"), k === "person" ? "Name, spelled exactly" : "Name, spelled exactly", x.name) +
      '<p class="spelled" id="' + fid(field, k + "-spelled") + '">' + spell(x.name) + "</p>" +
      (k === "person" ? textInput(fid(field, k + "-role"), "Role (optional)", x.role) + textInput(fid(field, k + "-video"), "Line under their name in videos (optional)", x.video_line) : "") +
      textInput(fid(field, k + "-handle"), "Handle (optional)", x.handle) + "</div>";
  }
  function spell(t) { t = String(t || "").trim(); return t ? "Spelled: " + t.toUpperCase().split(/\s+/).map(function (w) { return w.split("").join("-"); }).join("  ") : ""; }

  var MIC = "<svg class=\"mic\" viewBox=\"0 0 24 24\" width=\"16\" height=\"16\" aria-hidden=\"true\" focusable=\"false\"><rect x=\"9\" y=\"3\" width=\"6\" height=\"11\" rx=\"3\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"/><path d=\"M5 11a7 7 0 0 0 14 0M12 18v3\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"/></svg>";
  function confirmLabel(field, s) {
    if (UI && UI.flow) { return s === "ok" ? "Save changes and continue" : "Confirm and continue"; }
    return s === "check" ? "Looks right" : s === "ok" ? "Save changes" : (field.tap || field.kind === "name" || field.kind === "identities" ? "Spelled right, confirm" : "Confirm");
  }
  // "Draft this for me" sits right under the box it fills, not after every choice (audit #6).
  function bodyWithAssist(field) {
    var b = body(field), a = suggestHTML(field), hint = field.hint ? '<p class="hint">' + esc(field.hint) + "</p>" : "";
    if (b.indexOf("<!--assist-->") >= 0) { return '<div class="body" id="' + fid(field, "body") + '">' + b.replace("<!--assist-->", hint + a) + "</div>"; }
    return '<div class="body" id="' + fid(field, "body") + '">' + b + hint + "</div>" + a;
  }
  // New material beside the owner's answer (rev 13, M5 and N4): each alternative on its own line with its own
  // choices. Use instead (or Add to mine for lists) puts the new words in the box as a proposal, not confirmed;
  // the saved answer stays until the owner confirms. Keep mine dismisses that one alternative.
  var USABLE = ["object", "name", "colours", "items", "pairs"];
  function alternativesHTML(field) {
    var alts = alternativesFor(field);
    if (!alts.length) { return ""; }
    var usable = USABLE.indexOf(field.kind) >= 0 && !field.never_draft;
    var list = usable && (field.kind === "items" || field.kind === "pairs");
    return '<div class="cands" id="' + fid(field, "cands") + '"><p class="small"><b>Your new material says:</b> your answer stays as it is until you choose.</p>' +
      alts.map(function (x, i) {
        var t = candidateTextFor(field, x.answer);
        return '<div class="cand" data-i="' + i + '"><p class="candidate">\u201c' + esc(t) + '\u201d</p>' + (x.answer && x.answer.refs ? '<p class="small">From ' + esc(sourceLabel(x.answer.refs[0])) + "</p>" : "") +
          '<div class="row">' + (usable ? '<button type="button" data-cand-use="' + i + '">' + (list ? "Add to mine" : "Use instead") + "</button>" : "") +
          (x.cid ? '<button type="button" class="link" data-cand-keep="' + i + '">Keep mine</button>' : "") + "</div></div>";
      }).join("") + "</div>";
  }
  var usedCand = {};                    // field id -> the alternative being proposed in the box, until confirmed
  // The proposal's own words, in the same shape the saved answer is compared in (draft vs draft-edited).
  function proposalText(field, v) {
    if (field.kind === "colours") { return JSON.stringify([v.background || "", v.text || "", v.accent || ""]); }
    var parts = field.kind === "name" ? [{ name: "value" }] : (field.parts || []).filter(function (p) { return !p.key; });
    return JSON.stringify(parts.map(function (p) { return v[p.name] == null ? "" : v[p.name]; }));
  }
  function showUsing(field, box) {
    var note = box && box.querySelector(".cands");
    if (!note || !usedCand[field.id]) { return; }
    note.innerHTML = '<p class="small"><b>Using the new words.</b> Not confirmed yet: check them, then confirm. <button type="button" class="link" data-cand-cancel>Cancel</button></p>';
    note.querySelector("[data-cand-cancel]").onclick = function () {
      var u = usedCand[field.id]; delete usedCand[field.id];
      if (unsaved[field.id]) { delete unsaved[field.id].usedCand; }
      UI.saved(field); restore(field, u.snap);
    };
  }
  // Apply a used proposal's source to the answer being saved: unchanged it's "draft", edited "draft-edited".
  function carryProposal(field, target, now) {
    var uc = usedCand[field.id];
    if (!uc) { return; }
    // The proposal's source replaces the old answer's completely: nothing of the old one's marks survives.
    SOURCE_MARKS.forEach(function (k) { delete target[k]; });
    delete target.restored; delete target.changed_in_chat;
    target.origin = uc.origin || "person";
    target.source = now === uc.text ? "draft" : "draft-edited";
    if (uc.refs && uc.refs.length) { target.refs = clone(uc.refs); }
    if (uc.generator) { target.generator = uc.generator; }
  }
  function wireAlternatives(field, box) {
    var alts = alternativesFor(field);
    box.querySelectorAll("[data-cand-keep]").forEach(function (b) {
      b.onclick = function () {
        var x = alts[+b.getAttribute("data-cand-keep")];
        b.disabled = true;
        api("candidate", { key: x.key, part: x.part, cid: x.cid }).then(function (s) { S = s; UI.saved(field); })
          .catch(function (e) { b.disabled = false; err(field, e.message); });
      };
    });
    box.querySelectorAll("[data-cand-use]").forEach(function (b) {
      b.onclick = function () {
        var x = alts[+b.getAttribute("data-cand-use")], v = x.answer || {};
        var prev = capture(field);
        if (field.kind === "items" || field.kind === "pairs") {
          var iparts = field.kind === "pairs" ? [{ name: "others" }, { name: "us" }] : field.item_parts;
          (Array.isArray(v) ? v : [v]).forEach(function (it) {
            if (!it || it.remove) { return; }
            addRow(field, it[iparts[0].name] || "", null);
            var items = $(fid(field, "items")), rows = items.querySelectorAll(".item"), last = rows[rows.length - 1];
            iparts.forEach(function (p) { var el = last.querySelector("[id$='-" + p.name + "']"); if (el) { el.value = it[p.name] || ""; } });
            last.setAttribute("data-cand", JSON.stringify({ origin: it.origin || v.origin, refs: it.refs || v.refs || [], generator: it.generator || v.generator || "",
                                                        text: itemText(it, iparts) }));
          });
        } else if (field.kind === "colours") {
          ["background", "text", "accent"].forEach(function (k) { var el = $(fid(field, k)); if (el) { el.value = v[k] || ""; el.dispatchEvent(new Event("input")); } });
        } else {
          (field.kind === "name" ? [{ name: "value" }] : field.parts.filter(function (p) { return !p.key; })).forEach(function (p) {
            var x2 = v[p.name];
            if (p.type === "choice" || p.type === "multi") {
              var want = Array.isArray(x2) ? x2 : (x2 ? [x2] : []), g = $(fid(field, p.name));
              if (g) { g.querySelectorAll("button.choice").forEach(function (c) { c.setAttribute("aria-pressed", String(want.indexOf(c.getAttribute("data-val")) >= 0)); }); }
              return;
            }
            var el = $(fid(field, p.name)); if (!el) { return; }
            el.value = Array.isArray(x2) ? x2.join("\n") : (x2 == null ? "" : String(x2));
            el.dispatchEvent(new Event("input"));
          });
        }
        usedCand[field.id] = { key: x.key, part: x.part, cid: x.cid, origin: v.origin, refs: v.refs || [], generator: v.generator, snap: prev,
                               text: proposalText(field, v) };
        showUsing(field, box);
        markTyped(field);
      };
    });
  }
  // Question 29's parts each show where they stand; a drafted part has its own "Yes, keep this" (N6).
  function partState(field, part, v) {
    if (!v || !v.status) { return ""; }
    if (v.status === "confirmed") { return '<p class="part-state small">Done</p>'; }
    if (v.status !== "unconfirmed") { return ""; }
    return '<p class="part-state small">Suggested, please check. <button type="button" class="quote-yes" data-part-yes="' + part +
      '" id="' + fid(field, "yes-" + part) + '" aria-pressed="false">Yes, keep this</button></p>';
  }
  function partYes(field, part) { var b = $(fid(field, "yes-" + part)); return !!(b && b.getAttribute("aria-pressed") === "true"); }
  function fieldHTML(field) {
    var s = stateOf(field), ex = field.example;
    return '<div class="field-head"><div class="kicker">' + esc(stepLabel(field)) + "</div>" + chip(field) + "</div>" +
      (isNeeded(field) ? '<p class="tag need">Needed to write your first post</p>' : '<p class="tag opt">Optional</p>') +
      '<h2 class="ask" id="' + fid(field, "ask") + '" tabindex="-1">' + esc(field.ask) + "</h2>" +
      (field.why ? '<p class="why">' + esc(field.why) + "</p>" : "") +
      (draftNote(field) ? '<p class="draft">' + esc(draftNote(field)) + "</p>" : "") +
      // One prepared follow-up per answer, from Claude's draft: a quiet line, never a pop-up, never an answer.
      (S && S.followups && S.followups[field.id] && s !== "ok" ? '<p class="followup"><b>To make this sharper:</b> ' + esc(S.followups[field.id]) + "</p>" : "") +
      alternativesHTML(field) +
      (S && S.brand_changed && s === "ok" ? '<p class="note">Your brand was changed in the chat since these answers were saved. Check this one still matches before you change it.</p>' : "") +
      (s === "chat" ? '<p class="note">You’ll answer this one in the chat. <button type="button" class="link" data-act="unchat">Answer it here instead</button></p>' : "") +
      bodyWithAssist(field) +
      '<div class="heard" id="' + fid(field, "heard") + '" aria-live="polite"></div>' +
      '<p class="error" id="' + fid(field, "error") + '" role="alert" hidden></p>' +
      '<p class="typed small" id="' + fid(field, "typed") + '"' + (typed(field) ? "" : " hidden") + ">Not confirmed yet. " +
        (s === "ok" ? "Your confirmed answer is kept until you confirm this change." : "It's kept on this computer, but it only counts once you confirm it.") + "</p>" +
      '<div class="actions">' +
        '<button type="button" class="main" data-act="confirm">' + confirmLabel(field, s) + "</button>" +
        // Design B: one primary button that confirms and moves on; "Leave it for later" keeps typing unconfirmed.
        // A needed answer can still be skipped, with a smaller button, so the main one is the easy choice.
        '<button type="button" class="' + ((UI && UI.flow ? "second" : "") + (isNeeded(field) ? " quiet" : "")).trim() + '" data-act="skip">' + (UI && UI.flow ? "Skip for now" : "Skip") + "</button>" +
      "</div>" +
      // Rev 14 (design review): two main actions; talking, the chat and the example are quieter links on their own line.
      '<div class="actions more">' +
        // Typing first; a small mic on every question that has a box to talk into (rev 12, N1).
        (hasBox(field) ? '<button type="button" class="talk link" data-act="talk" aria-pressed="false" aria-label="Talk instead of typing">' + MIC + "Talk instead</button>" : "") +
        '<button type="button" class="link" data-act="chat">Answer in the chat</button>' +
        (ex ? '<button type="button" class="link" data-act="example" aria-expanded="false">See an example</button>' : "") +
      "</div>" +
      (ex ? '<p class="example" id="' + fid(field, "example") + '" hidden><b>' + (field.never_draft ? "The made-up bakery said (an example only): " : "Example: ") + "</b>" + esc(ex) + "</p>" : "");
  }

  // ------------------------------------------------------------------ wiring a drawn field
  function wire(field, root) {
    root = root || document;
    var box = root.querySelector('[data-field="' + field.id + '"]');
    if (!box) { return; }
    box.querySelectorAll("[data-act]").forEach(function (b) {
      b.onclick = function () { act(field, b.getAttribute("data-act"), b); };
    });
    wireChoices(field, box);
    box.querySelectorAll("[data-add]").forEach(function (b) {
      b.onclick = function () {
        var items = b.previousElementSibling;
        var waiting = items.querySelector(".item[hidden]");
        if (waiting) { waiting.hidden = false; var w = waiting.querySelector("input, textarea"); if (w) { w.focus(); } return; }
        var tpl = items.querySelector(".item");
        var copy = tpl.cloneNode(true);
        copy.setAttribute("data-id", "");
        copy.setAttribute("data-source", "typed");
        // A fresh number every time, never reused after a row is removed, so no two boxes share an id.
        var n = +(items.getAttribute("data-next") || 0);
        items.querySelectorAll("input[id], textarea[id]").forEach(function (el) {
          var m = el.id.match(/-[si](\d+)(-|$)/); if (m) { n = Math.max(n, +m[1] + 1); }
        });
        items.setAttribute("data-next", String(n + 1));
        var renum = function (s) { return s.replace(/-([si])\d+(-|$)/, "-$1" + n + "$2"); };
        copy.removeAttribute("data-removed");
        copy.querySelectorAll(".quote-src").forEach(function (q) { q.remove(); });
        copy.querySelectorAll("input, textarea").forEach(function (el) { el.value = ""; el.id = renum(el.id); });
        copy.querySelectorAll("label[for]").forEach(function (l) { l.setAttribute("for", renum(l.getAttribute("for"))); l.textContent = l.textContent.replace(/ \d+( \(spoken\))?$/, " " + (n + 1)); });
        // A new row's choices start at their first option (for proof: a real result, my own account, not yet published).
        copy.querySelectorAll(".choices").forEach(function (g) {
          g.id = renum(g.id);
          g.querySelectorAll("button.choice").forEach(function (c, i) { c.setAttribute("aria-pressed", String(i === 0)); });
        });
        items.appendChild(copy);
        wireRemove(copy);
        wireChoices(field, copy);
        var first = copy.querySelector("input, textarea"); if (first) { first.focus(); }
        if (items.querySelectorAll(".item").length >= (maxOf(field, items) || 99)) { b.hidden = true; }
      };
    });
    box.querySelectorAll(".item").forEach(wireRemove);
    var nm = box.querySelector("#" + fid(field, "value"));
    if (field.kind === "name" && nm) { nm.oninput = function () { $(fid(field, "spelled")).textContent = spell(nm.value); }; }
    box.querySelectorAll(".identity input[id$='-name']").forEach(function (el) {
      el.oninput = function () { var k = el.closest(".identity").getAttribute("data-kind"); $(fid(field, k + "-spelled")).textContent = spell(el.value); };
    });
    var none = $(fid(field, "none"));
    if (none) { none.onchange = function () { $(fid(field, "fields")).hidden = none.checked; }; }
    if (field.kind === "colours") { wireColours(field); }
    wireAlternatives(field, box);
    wirePlatformApply(field, box);
    box.querySelectorAll("textarea[data-talk], input[data-talk]").forEach(function (el) {
      el.addEventListener("input", function () { if (el.hasAttribute("data-gen")) { el.setAttribute("data-edited", "1"); } });
    });
    box.addEventListener("input", function () { markTyped(field); });
    box.addEventListener("change", function () { markTyped(field); });
    box.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("button.choice, .swatch, .palette, [data-add], [data-remove]")) { markTyped(field); } });
    box.querySelectorAll("[data-part-yes]").forEach(function (b) {
      b.onclick = function () { var on = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", String(on)); b.textContent = on ? "Kept \u2713" : "Yes, keep this"; markTyped(field); };
    });
    box.querySelectorAll("[data-quote-yes]").forEach(function (b) {
      b.onclick = function () {
        var on = b.getAttribute("aria-pressed") !== "true";
        b.setAttribute("aria-pressed", String(on));
        b.textContent = on ? "Yes, my words \u2713" : "Yes, these are my words";
        markTyped(field);
      };
    });
    // Design B: Enter in a one-line box is "Confirm and continue" (never in a multi-line box, never mid-word).
    if (UI && UI.flow) {
      box.addEventListener("keydown", function (e) {
        var t = e.target;
        if (e.key !== "Enter" || e.isComposing || e.repeat || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) { return; }
        if (!t || t.tagName !== "INPUT" || ["text", "number"].indexOf(t.type) < 0) { return; }
        e.preventDefault(); act(field, "confirm");
      });
    }
  }
  function wirePlatformApply(field, box) {
    box.querySelectorAll("[data-plat-apply]").forEach(function (b) {
      b.onclick = function () {
        var pk = pack(), g = $(fid(field, "plat-" + b.getAttribute("data-plat-apply")));
        if (!g || !pk) { return; }
        (pk.suggestions.platforms || []).forEach(function (pl) { var c = g.querySelector('[data-val="' + pl + '"]'); if (c) { c.setAttribute("aria-pressed", "true"); } });
        b.textContent = "Tapped in. Untap any you don't want, then Confirm.";
      };
    });
    box.addEventListener("focusin", function (e) {
      if (rec.cur && rec.cur.field !== field.id && /INPUT|TEXTAREA/.test(e.target.tagName)) { stopRecording(true); }
    });
  }
  function wireChoices(field, root) {
    var box = document.querySelector('[data-field="' + field.id + '"]');
    root.querySelectorAll(".choices").forEach(function (g) {
      var multi = g.getAttribute("data-multi") === "1";
      g.querySelectorAll("button.choice").forEach(function (c) {
        c.onclick = function () {
          var on = c.getAttribute("aria-pressed") === "true";
          if (multi) { c.setAttribute("aria-pressed", String(!on)); }
          else { g.querySelectorAll("button.choice").forEach(function (o) { o.setAttribute("aria-pressed", String(o === c)); }); }
          if (g.id === fid(field, "kinds")) { redrawIdentities(field, box); }
        };
      });
    });
  }
  function maxOf(field, items) {
    if (items.id.indexOf("-for-") > 0 || items.id.indexOf("-against-") > 0) { return 2; }
    if (field.kind === "beliefs") { return 3; }
    return field.max;
  }
  function wireRemove(item) {
    var b = item.querySelector("[data-remove]");
    if (!b) { return; }
    b.onclick = function () {
      var items = item.parentNode;
      if (items.querySelectorAll(".item").length === 1) {
        item.querySelectorAll("input, textarea").forEach(function (el) { el.value = ""; });
        if (item.getAttribute("data-id")) { item.setAttribute("data-removed", item.getAttribute("data-id")); item.setAttribute("data-id", ""); }
        return;
      }
      if (item.getAttribute("data-id")) { items.setAttribute("data-removed", (items.getAttribute("data-removed") || "") + " " + item.getAttribute("data-id")); }
      item.parentNode.removeChild(item);
      var add = items.nextElementSibling; if (add && add.hasAttribute("data-add")) { add.hidden = false; }
    };
  }
  function redrawIdentities(field, box) {
    var picked = Array.prototype.map.call(box.querySelectorAll("#" + fid(field, "kinds") + " [aria-pressed=true]"), function (b) { return b.getAttribute("data-val"); });
    var people = $(fid(field, "people")), have = {};
    people.querySelectorAll(".identity").forEach(function (row) { have[row.getAttribute("data-kind")] = row; });
    picked.forEach(function (k) { if (!have[k]) { people.insertAdjacentHTML("beforeend", identityRow(field, { kind: k })); } });
    Object.keys(have).forEach(function (k) { if (picked.indexOf(k) < 0) { people.removeChild(have[k]); } });
    wire(field);
  }
  function lum(hex) {
    var c = [1, 3, 5].map(function (i) { var v = parseInt(hex.substr(i, 2), 16) / 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function contrast(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function hexOk(h) { return /^#[0-9A-Fa-f]{6}$/.test(h || ""); }
  function wireColours(field) {
    ["background", "text", "accent"].forEach(function (j) {
      var pick = $(fid(field, j + "-pick")), hex = $(fid(field, j));
      pick.oninput = function () { hex.value = pick.value.toUpperCase(); check(); };
      hex.oninput = function () { var v = hex.value.trim(); if (v && v[0] !== "#") { v = "#" + v; } if (hexOk(v)) { pick.value = v; } check(); };
    });
    function setColour(j, h) { $(fid(field, j)).value = h; $(fid(field, j + "-pick")).value = h; }
    var sw = $(fid(field, "found"));
    if (sw) {
      sw.querySelectorAll(".swatch").forEach(function (b) {
        b.onclick = function () {
          var role = pressed(fid(field, "role"))[0] || "background", order = ["background", "text", "accent"];
          setColour(role, b.getAttribute("data-hex")); check();
          var next = order[(order.indexOf(role) + 1) % 3];      // move on to the next part to set
          $(fid(field, "role")).querySelectorAll("button.choice").forEach(function (o) { o.setAttribute("aria-pressed", String(o.getAttribute("data-val") === next)); });
        };
      });
    }
    $(fid(field, "palette")).onclick = function () {
      var p = palette($(fid(field, "mood")) ? $(fid(field, "mood")).value : "");
      ["background", "text", "accent"].forEach(function (j) { setColour(j, p[j]); });
      $(fid(field, "palette-note")).textContent = "A suggested palette. Change anything you like, or tap again for another.";
      check();
    };
    var pp = $(fid(field, "packpal"));
    if (pp) {
      pp.querySelectorAll(".palette").forEach(function (b) {
        b.onclick = function () {
          var pl = pack().palettes[+b.getAttribute("data-i")];
          ["background", "text", "accent"].forEach(function (j) { setColour(j, pl[j]); });
          $(fid(field, "palette-note")).textContent = suggestedLabel(pack());
          check();
        };
      });
    }
    ["heading", "body"].forEach(function (part) {
      var s = $(fid(field, "font-" + part)), sample = $(fid(field, "font-" + part + "-sample"));
      if (s) { s.onchange = function () { sample.style.fontFamily = s.value ? "'" + s.value + "', serif" : ""; }; }
    });
    var fu = $(fid(field, "font-use"));
    if (fu) {
      fu.onclick = function () {
        var fp = pack().font_pair;
        ["heading", "body"].forEach(function (part) { var s = $(fid(field, "font-" + part)); if (s) { s.value = fp[part]; s.onchange(); } });
      };
    }
    function check() {
      var bg = $(fid(field, "background")).value, tx = $(fid(field, "text")).value, ac = $(fid(field, "accent")).value, out = $(fid(field, "contrast"));
      if (!hexOk(bg) || !hexOk(tx)) { out.textContent = "Type colours as six-digit hex codes, like #1A2B3C."; return; }
      var r = contrast(bg, tx), ra = hexOk(ac) ? contrast(bg, ac) : 0;
      // The sample follows every change; the button's words take whichever of white or near-black reads best.
      var pv = $(fid(field, "preview"));
      if (pv) {
        pv.style.background = bg; pv.style.color = tx;
        var btn = pv.querySelector(".pvbtn");
        if (hexOk(ac)) { var onAc = contrast(ac, "#FFFFFF") >= contrast(ac, "#111111") ? "#FFFFFF" : "#111111"; btn.style.background = ac; btn.style.color = onAc; btn.setAttribute("data-ok", String(contrast(ac, onAc) >= 4.5)); }
      }
      out.textContent = (r >= 4.5 ? "Text on background: easy to read." : "Text on background: hard to read. Pick a darker or lighter text colour.") +
        (ra ? (ra >= 3 ? " Accent on background: stands out." : " Accent on background: faint, so buttons won't stand out.") : "");
    }
    check();
  }

  // ------------------------------------------------------------------ collecting and saving
  function val(id) { var el = $(id); return el ? el.value : ""; }
  function pressed(id) { return Array.prototype.map.call(document.querySelectorAll("#" + id + " [aria-pressed=true]"), function (b) { return b.getAttribute("data-val"); }); }
  function sourceFor(old, newText, oldText) {
    if (!old || !old.source) { return "typed"; }
    if (old.source === "draft" || old.source === "draft-edited") { return String(newText || "") === String(oldText || "") ? "draft" : "draft-edited"; }
    return old.source === "typed" ? "typed" : old.source;
  }
  var SOURCE_MARKS = ["refs", "generator", "parts", "prompted_by", "excerpt"];
  function stamp(o, old, status, text, oldText) {
    o.status = status;
    o.source = sourceFor(old, text, oldText);
    o.origin = (old && old.origin) || "person";
    if (old && old.origin === "brand" && String(text || "") !== String(oldText || "")) {
      o.origin = "person"; delete o.restored; delete o.changed_in_chat;
    }
    if (old && (old.source === "draft" || old.source === "draft-edited")) {
      SOURCE_MARKS.forEach(function (k) { if (old[k] !== undefined && o[k] === undefined) { o[k] = clone(old[k]); } });
    }
    return o;
  }
  // Every part of an item counts when telling an unchanged item from an edited one (not only its first part).
  function itemText(it, parts) { return parts.map(function (p) { return (it && it[p.name]) || ""; }).join("\u241f"); }
  // An edited quote of the owner's own writing is now the owner's own typing: never shown as a quote again, but
  // where it came from is kept beside it, so a later "don't use" on that file still finds it (rev 13, M3/M6).
  function derivedFrom(old) {
    var d = {};
    ["origin", "refs", "generator"].forEach(function (k) { if (old[k] !== undefined) { d[k] = clone(old[k]); } });
    return d;
  }
  function readItems(field, containerId, parts, prefix, status, oldList, neverDraft) {
    var box = $(containerId); if (!box) { return []; }
    var used = {}, out = [];
    (oldList || []).forEach(function (x) { if (x && x.id) { used[x.id] = true; } });
    box.querySelectorAll(".item").forEach(function (row) {
      var it = {}, any = false;
      parts.forEach(function (p) {
        var el = row.querySelector("[id$='-" + p.name + "']");
        var v = el ? el.value.trim() : "";
        if (v) { it[p.name] = v; if (p.name !== "experience") { any = true; } }
      });
      var id = row.getAttribute("data-id");
      if (!any) { if (id) { out.push({ id: id, remove: true, status: "confirmed" }); } return; }
      if (!id) { var n = 1; while (used[prefix + "-" + n]) { n++; } id = prefix + "-" + n; used[id] = true; }
      var old = byId(oldList, id);
      it.id = id;
      stamp(it, old, status, itemText(it, parts), old ? itemText(old, parts) : "");
      // A myth or mistake the owner kept from a pack (after "Yes, I've seen this") keeps where it came from (N3).
      var gen = row.getAttribute("data-gen");
      if (gen && !neverDraft) {
        it.origin = row.getAttribute("data-origin"); it.generator = gen;
        it.source = (it.value || "") === (row.getAttribute("data-text") || "") ? "draft" : "draft-edited";
      }
      var cand = row.getAttribute("data-cand");
      if (cand && !neverDraft) {
        try {
          cand = JSON.parse(cand);
          SOURCE_MARKS.forEach(function (k) { delete it[k]; });
          it.origin = cand.origin || "person";
          if (cand.refs && cand.refs.length) { it.refs = cand.refs; }
          if (cand.generator) { it.generator = cand.generator; }
          it.source = itemText(it, parts) === cand.text ? "draft" : "draft-edited";
        } catch (e) {}
      }
      if (neverDraft) {
        // The quoted parts are the ones the passage supplied; what the owner adds beside them (the "us" side of a
        // pair, the experience) is theirs and doesn't undo the quote. Changing a quoted part does.
        var qp = old && old.quoted ? (old.quoted_parts || ["value", "others", "us", "name", "why"].filter(function (n) { return old[n]; })) : [];
        var same = old && old.quoted && qp.length && qp.every(function (n) { return (it[n] || "") === (old[n] || ""); });
        if (same) {
          it.source = "draft"; it.origin = old.origin;
          ["quoted", "said_by", "excerpt", "refs", "generator"].forEach(function (k) { if (old[k] !== undefined) { it[k] = old[k]; } });
          it.quoted_parts = qp;
          if (status === "confirmed" && old.status !== "confirmed") {
            if (quoteYes(row)) { it.accepted = true; } else { it.status = "unconfirmed"; }   // no yes: still waiting
          } else if (old.accepted) { it.accepted = true; }
        }
        else {
          SOURCE_MARKS.forEach(function (k) { delete it[k]; });
          if (old && old.quoted) { it.derived_from = derivedFrom(old); }
          else if (old && old.derived_from) { it.derived_from = clone(old.derived_from); }
          it.source = "typed";
          it.origin = old && old.origin === "brand" && itemText(it, parts) === itemText(old, parts) ? "brand" : "person";
        }
      }
      out.push(it);
    });
    (box.getAttribute("data-removed") || "").split(" ").filter(Boolean).forEach(function (id) { out.push({ id: id, remove: true, status: "confirmed" }); });
    box.querySelectorAll("[data-removed]").forEach(function (row) { out.push({ id: row.getAttribute("data-removed"), remove: true, status: "confirmed" }); });
    return out;
  }
  function mergeList(oldList, newItems) {
    var out = (oldList || []).map(clone), seen = {};
    newItems.forEach(function (n) {
      var i = -1; out.forEach(function (o, j) { if (o.id === n.id) { i = j; } });
      if (i >= 0) { out[i] = n; } else { out.push(n); }
      seen[n.id] = true;
    });
    return out;
  }

  /* What saving this field sends: [{key, answer}] with the whole answer for each key, so
     answers shared with other fields keep their other parts. status is "confirmed" or "skipped". */
  function collect(field, status) {
    var a = clone(answer(field.key)), out = [];
    var C = status === "skipped" ? "skipped" : "confirmed";
    function put(key, value) { out.push({ key: key, answer: value }); }
    switch (field.kind) {
      case "name": {
        var o = a || {}, v = val(fid(field, "value")).trim();
        if (C === "confirmed" && !v) { throw new Error("Type your brand name first."); }
        var n = clone(o); n.value = v || o.value; n.spelled = n.value ? spell(n.value).replace("Spelled: ", "") : undefined;
        stamp(n, o, C, v, o.value); if (C === "confirmed") { n.tapped = true; carryProposal(field, n, proposalText(field, n)); }
        put("name", n); break;
      }
      case "object": {
        // Skipping one of several questions that share an answer (name, audience, voice) leaves the others' words alone.
        if (C === "skipped" && !field.path && (sharesKey(field) || field.key === "name")) { return []; }
        var root = a && typeof a === "object" && !Array.isArray(a) ? a : {};
        if (C === "skipped") {
          var skip = { status: "skipped", source: "typed", origin: "person" };
          if (field.path) { root = clone(root); root[field.path] = skip; put(field.key, root); } else { put(field.key, skip); }
          break;
        }
        var target = field.path ? clone(root[field.path] || {}) : clone(root);
        var old = field.path ? root[field.path] : a, text = "", otherKeys = {};
        field.parts.forEach(function (p) {
          var v2;
          if (p.type === "choice") { v2 = pressed(fid(field, p.name))[0]; }
          else if (p.type === "multi") { v2 = pressed(fid(field, p.name)); }
          else if (p.type === "lines") { v2 = lines(val(fid(field, p.name))); }
          else if (p.type === "number") { var t = val(fid(field, p.name)).trim(); v2 = t === "" ? undefined : Number(t); }
          else { v2 = val(fid(field, p.name)).trim(); }
          if (p.key) { otherKeys[p.key] = otherKeys[p.key] || {}; otherKeys[p.key][p.name] = v2; return; }
          if (v2 === undefined || v2 === "" || (Array.isArray(v2) && !v2.length)) { delete target[p.name]; } else { target[p.name] = v2; text += JSON.stringify(v2); }
        });
        var oldText = ""; field.parts.forEach(function (p) { if (!p.key && old && old[p.name] !== undefined) { oldText += JSON.stringify(old[p.name]); } });
        stamp(target, old, C, text, oldText);
        if (C === "confirmed") { carryProposal(field, target, proposalText(field, target)); }   // the owner chose the new words
        if (field.key === "name" && C === "confirmed") {
          if (!(a && a.status === "confirmed")) { throw new Error("Confirm your brand name first (question 1)."); }
          target.tapped = true; target.status = "confirmed";
        }
        if (field.path) { root = clone(root); root[field.path] = target; put(field.key, root); } else { put(field.key, target); }
        Object.keys(otherKeys).forEach(function (k) {
          var other = clone(answer(k)) || { status: "unconfirmed" };
          Object.keys(otherKeys[k]).forEach(function (n) { var v3 = otherKeys[k][n]; if (Array.isArray(v3) && !v3.length) { delete other[n]; } else { other[n] = v3; } });
          if (!other.status) { other.status = "unconfirmed"; }
          put(k, other);
        });
        break;
      }
      case "items": case "pairs": {
        var parts = field.kind === "pairs" ? [{ name: "others" }, { name: "us" }] : field.item_parts.concat([]);
        var oldList = itemsOf(field);
        var items = C === "skipped" ? [] : readItems(field, fid(field, "items"), parts, field.prefix, C, oldList, field.never_draft);
        if (TOP_LISTS.indexOf(field.key) >= 0) { put(field.key, mergeList(oldList, items)); break; }
        var r = a && typeof a === "object" && !Array.isArray(a) ? a : {};
        r[field.list] = mergeList(oldList, items);
        if (field.key === "audience" && !r.status) { r.status = "unconfirmed"; }
        // A question that keeps its own answer beside its rows (who inspires you): confirmed with none left
        // clears the list on purpose; skipped leaves it as it was.
        if (field.own_status) { r.status = C; delete r.restored; }
        put(field.key, r); break;
      }
      case "beliefs": {
        var p = a || {}, cb = clone(p.core_belief) || {}, v4 = val(fid(field, "core")).trim();
        if (C === "skipped") { cb = { status: "skipped", source: "typed" }; p.contrarian = []; }
        else {
          if (v4) { cb.value = v4; } else { delete cb.value; }
          var e4 = val(fid(field, "core-exp")).trim(); if (e4) { cb.experience = e4; } else { delete cb.experience; }
          cb.status = C;
          var was = p.core_belief || {};
          var unchanged = (cb.value || "") === (was.value || "") && (cb.experience || "") === (was.experience || "");
          // The belief itself is the quote; the experience is the owner's own and doesn't undo it.
          if (was.quoted && (cb.value || "") === (was.value || "")) {   // the owner's quote, kept as quoted
            cb.source = "draft"; cb.quoted_parts = ["value"];
            if (C === "confirmed" && was.status !== "confirmed") {
              if (quoteYes($(fid(field, "core-quote")))) { cb.accepted = true; } else { cb.status = "unconfirmed"; }
            }
          }
          else {
            if (was.quoted) { cb.derived_from = derivedFrom(was); }
            cb.source = "typed"; cb.origin = was.origin === "brand" && unchanged ? "brand" : "person";
            ["quoted", "said_by", "excerpt", "refs", "generator"].forEach(function (k) { delete cb[k]; });
          }
          p.contrarian = mergeList(p.contrarian, readItems(field, fid(field, "items"), [{ name: "value" }, { name: "experience" }], "c", C, p.contrarian, true));
        }
        p.core_belief = cb; put("positioning", p); break;
      }
      case "foragainst": {
        var q = a || {};
        if (C === "skipped") { q["for"] = (q["for"] || []).map(function (x) { return { id: x.id, remove: true, status: "confirmed" }; }); q.against = []; }
        q["for"] = mergeList(q["for"], C === "skipped" ? [] : readItems(field, "f-" + field.id + "-for-items", [{ name: "value" }, { name: "experience" }], "for", C, q["for"]));
        q.against = mergeList(q.against, C === "skipped" ? [] : readItems(field, "f-" + field.id + "-against-items", [{ name: "value" }, { name: "experience" }], "against", C, q.against));
        if (C === "skipped") { local.skip[field.id] = true; saveLocal(); }
        put("positioning", q); break;
      }
      case "story": {
        var pp = a || {}, st = clone(pp.story) || {};
        var ca = val(fid(field, "catalyst")).trim(), ct = val(fid(field, "core_truth")).trim();
        if (ca) { st.catalyst = ca; } else { delete st.catalyst; }
        if (ct) { st.core_truth = ct; } else { delete st.core_truth; }
        st.proof = mergeList(st.proof, C === "skipped" ? [] : readItems(field, fid(field, "items"), [{ name: "value" }], "sp", C, st.proof));
        stamp(st, pp.story, C, ca + ct, (pp.story || {}).catalyst + (pp.story || {}).core_truth);
        pp.story = st; put("positioning", pp); break;
      }
      case "home": {
        var h = a || {}, med = pressed(fid(field, "medium"))[0], stg = pressed(fid(field, "stage"))[0];
        h.home_medium = med && C === "confirmed" ? stamp({ value: med }, h.home_medium, C, med, (h.home_medium || {}).value) : { status: C === "skipped" ? "skipped" : "unconfirmed" };
        h.stage = stg && C === "confirmed" ? stamp({ value: stg }, h.stage, C, stg, (h.stage || {}).value) : { status: C === "skipped" ? "skipped" : "unconfirmed" };
        if (C === "confirmed" && !med && !stg) { throw new Error("Tap one of each, or Skip."); }
        put("positioning", h); break;
      }
      case "rung": {
        var lad = Array.isArray(a) ? a : [], old2 = lad.filter(function (x) { return x.rung === field.rung; })[0];
        var none = $(fid(field, "none")) && $(fid(field, "none")).checked;
        var r2 = { rung: field.rung };
        if (old2 && old2.id) { r2.id = old2.id; }
        if (C === "confirmed") {
          if (none) { r2.none_yet = true; }
          else {
            var nm = val(fid(field, "name")).trim(), ln = val(fid(field, "line")).trim();
            if (!nm) { throw new Error("Give it a name, or tick None yet."); }
            r2.name = nm; if (ln) { r2.line = ln; }
            var priceBox = $(fid(field, "price")), pr = priceBox ? priceBox.value.trim() : "";
            ["link", "price", "keyword", "keyword_ready", "call_to_action"].forEach(function (k) { if (old2 && old2[k] !== undefined && !(k === "price" && priceBox)) { r2[k] = old2[k]; } });
            if (pr) { r2.price = pr; }
          }
        }
        stamp(r2, old2, C, (r2.name || "") + (r2.line || ""), old2 ? (old2.name || "") + (old2.line || "") : "");
        put("ladder", lad.filter(function (x) { return x.rung !== field.rung; }).concat([r2])); break;
      }
      case "rules": {
        var ru = clone(a) || {};
        var ind = pressed(fid(field, "industry"))[0];
        if (ind) { ru.industry = ind; }
        ["never_claim", "never_name", "hated_words", "sign_off"].forEach(function (k) { var l = lines(val(fid(field, k))); if (l.length) { ru[k] = l; } else { delete ru[k]; } });
        stamp(ru, a, C, JSON.stringify(ru), JSON.stringify(a || {}));
        if (C === "confirmed") { ru.tapped = true; }
        put("rules", ru); break;
      }
      case "colours": {
        var cc = { background: val(fid(field, "background")).toUpperCase(), text: val(fid(field, "text")).toUpperCase(), accent: val(fid(field, "accent")).toUpperCase() };
        if (C === "confirmed" && !(hexOk(cc.background) && hexOk(cc.text) && hexOk(cc.accent))) { throw new Error("Each colour needs a six-digit hex code, like #1A2B3C."); }
        if (C === "skipped") { cc = {}; }
        if (a && Array.isArray(a.found)) { cc.found = a.found; }           // the website's colours stay on offer
        stamp(cc, a, C, JSON.stringify({ background: cc.background, text: cc.text, accent: cc.accent }), a ? JSON.stringify({ background: a.background, text: a.text, accent: a.accent }) : "");
        if (C === "confirmed") { carryProposal(field, cc, proposalText(field, cc)); }
        put("colours", cc);
        // Fonts are optional and saved on their own (N5): no preference leaves them out.
        var fh = val(fid(field, "font-heading")), fb = val(fid(field, "font-body"));
        if (C === "confirmed" && (fh || fb || answer("fonts"))) {
          var fo = { status: "confirmed", source: "typed", origin: "person" }; if (fh) { fo.heading = fh; } if (fb) { fo.body = fb; }
          var fp = pack() && pack().font_pair;
          if (fp && fh === fp.heading && fb === fp.body) { fo.source = "draft"; fo.origin = pack().custom ? "description" : "starter-pack"; fo.generator = generator(pack()); }
          put("fonts", fo);
        }
        break;
      }
      case "filming": {
        var fm = { status: C, source: "typed", origin: "person", speakers: [] };
        if (C === "confirmed") {
          document.querySelectorAll("[id^='" + fid(field, "mode-") + "'].choices").forEach(function (grp) {
            var md = pressed(grp.id)[0]; if (md) { fm.speakers.push({ id: grp.id.replace(fid(field, "mode-"), ""), mode: md, status: "confirmed", source: "typed", origin: "person" }); }
          });
          var here = {}; fm.speakers.forEach(function (x) { here[x.id] = true; });
          live((a || {}).speakers).forEach(function (x) { if (!here[x.id] && !document.getElementById(fid(field, "mode-" + x.id))) { fm.speakers.push(dict(x, { status: "for_chat" })); } });
          var wh = val(fid(field, "where")).trim(); if (wh) { fm.where = wh; }
          if (!fm.speakers.length && !wh) { throw new Error("Tap how each person appears, or say where you'd film, or Skip."); }
        }
        put("filming", fm); break;
      }
      case "goal_platforms": {
        var g = pressed(fid(field, "goal"))[0];
        var by = {};
        document.querySelectorAll("[id^='" + fid(field, "plat-") + "'].choices").forEach(function (grp) {
          var sid = grp.id.replace(fid(field, "plat-"), ""), v5 = pressed(grp.id); if (v5.length) { by[sid] = v5; }
        });
        var other = val(fid(field, "plat-other")).trim(), mk = pressed(fid(field, "make"));
        if (C === "skipped") { put("goal", { status: "skipped", source: "typed", origin: "person" }); break; }
        var plat = { by_speaker: by, status: C, source: "typed", origin: "person" }; if (other) { plat.other = other; }
        var make = { value: mk, status: C, source: "typed", origin: "person" };
        // Each part counts on its own (N6): only what was answered here is saved; an empty part is left as it was.
        var oldPl = answer("platforms") || {}, oldMk = answer("make") || {};
        var plChanged = JSON.stringify([by, other || ""]) !== JSON.stringify([oldPl.by_speaker || {}, oldPl.other || ""]);
        var mkChanged = JSON.stringify(mk) !== JSON.stringify(oldMk.value || []);
        // A draft kept as it was ("Yes, keep this") keeps where it came from; a changed one is the owner's own.
        if (!plChanged && oldPl.status) { plat = stamp(plat, oldPl, C, "same", "same"); }
        if (!mkChanged && oldMk.status) { make = stamp(make, oldMk, C, "same", "same"); }
        if (!g && !Object.keys(by).length && !other && !mk.length) { throw new Error("Tap what you want help with and where you post, or Skip."); }
        var oldG = answer("goal") || {};
        if (g) {
          var gw = stamp({ value: g }, oldG, C, g, oldG.value);
          if (C === "confirmed" && oldG.status === "unconfirmed" && g === oldG.value && !partYes(field, "goal")) { gw.status = "unconfirmed"; }
          put("goal", gw);
        }
        // A part drafted earlier and left exactly as it was stays unconfirmed unless its own "Yes, keep this" is on:
        // confirming the goal never confirms it. Changing it makes it the owner's answer.
        if ((Object.keys(by).length || other) ? (plChanged || oldPl.status !== "unconfirmed" || partYes(field, "platforms")) : (plChanged && oldPl.status)) { put("platforms", plat); }
        if (mk.length ? (mkChanged || oldMk.status !== "unconfirmed" || partYes(field, "make")) : (mkChanged && oldMk.status)) { put("make", make); }
        // How people find you is its own question now: this question never touches that answer.
        break;
      }
      case "identities": {
        var rows = document.querySelectorAll("#" + fid(field, "people") + " .identity"), list = [];
        var oldL = Array.isArray(a) ? a : [];
        if (C === "skipped") { put("identities", []); break; }
        rows.forEach(function (row) {
          var k = row.getAttribute("data-kind"), nm2 = val(fid(field, k + "-name")).trim();
          if (!nm2) { return; }
          var old3 = oldL.filter(function (x) { return x.kind === k; })[0];
          var it = { kind: k, id: (old3 && old3.id) || k, name: nm2, spelled: spell(nm2).replace("Spelled: ", "") };
          [["role", "-role"], ["handle", "-handle"], ["video_line", "-video"]].forEach(function (pr) { var v6 = val(fid(field, k + pr[1])).trim(); if (v6) { it[pr[0]] = v6; } });
          stamp(it, old3, "confirmed", nm2, old3 && old3.name); it.tapped = true;
          list.push(it);
        });
        if (!list.length) { throw new Error("Tap who speaks, then type each name."); }
        put("identities", list);
        var film = answer("filming"), gone = live(film && film.speakers).filter(function (x) { return !list.some(function (y) { return y.id === x.id; }); });
        if (gone.length) {
          var goneIds = gone.map(function (x) { return x.id; }).sort().join(" ");
          var oldNames = (Array.isArray(a) ? a : []).reduce(function (m, x) { m[x.id] = x.name; return m; }, {});
          if (field._filmOk !== goneIds) { field._filmOk = goneIds; throw new Error("Removing " + gone.map(function (x) { return oldNames[x.id] || x.id; }).join(", ") + " also takes them out of your videos (the filming question). Tap Confirm again to do both, or add them back."); }
          var f2 = clone(film); f2.speakers = f2.speakers.filter(function (x) { return !gone.some(function (g) { return g.id === x.id; }); }); put("filming", f2);
        }
        field._filmOk = "";
        break;
      }
      case "samples": {
        if (C === "skipped") { put("voice_samples", []); break; }
        var outS = [], oldS = Array.isArray(answer("voice_samples")) ? answer("voice_samples") : [];
        document.querySelectorAll("#" + fid(field, "items") + " .item").forEach(function (row) {
          var t = row.querySelector("textarea").value;
          if (!t.trim()) { return; }
          var s5 = { text: t, source: row.getAttribute("data-source") || "typed", verbatim: true, status: "confirmed", origin: "person" };
          // The same words as before keep where they came from, so a later "don't use" still finds them (M3).
          var was = oldS.filter(function (x) { return x && x.text === t; })[0];
          if (was) {
            ["id", "origin", "refs", "derived_from", "excerpt", "said_by", "restored", "generator"].forEach(function (k) { if (was[k] !== undefined) { s5[k] = clone(was[k]); } });
            if (was.source) { s5.source = was.source; }
          }
          outS.push(s5);
        });
        if (!outS.length) { throw new Error("Paste, type or say at least one sample, or Skip."); }
        put("voice_samples", outS); break;
      }
      case "proof": {
        var dp = a && typeof a === "object" ? a : {}, oldP = dp.proof || [], usedP = {}, outP = [];
        oldP.forEach(function (x) { if (x && x.id) { usedP[x.id] = true; } });
        if (C !== "skipped") {
          document.querySelectorAll("#" + fid(field, "items") + " .item").forEach(function (row) {
            var it = {}, any = false;
            PROOF_PARTS.forEach(function (pp) { var el = row.querySelector("[id$='-" + pp[0] + "']"); var v = el ? el.value.trim() : ""; if (v) { it[pp[0]] = v; any = true; } });
            var id = row.getAttribute("data-id");
            if (!any) { if (id) { outP.push({ id: id, remove: true, status: "confirmed" }); } return; }
            // The library needs a title for every item, so one is asked for rather than an item quietly dropped later.
            if (!it.title) { throw new Error("Give each piece of proof a few words in the first box (“In a few words, what is it?”)."); }
            ["bank", "known_from", "may_publish"].forEach(function (k) {
              var g = row.querySelector(".choices[id$='-" + k + "']"), on = g && g.querySelector("[aria-pressed=true]");
              if (on) { it[k] = on.getAttribute("data-val"); }
            });
            it.bank = it.bank || "credibility"; it.may_publish = it.may_publish || "no"; it.known_from = it.known_from || "own_account";
            it.kind = it.bank === "interest" ? "fact" : "result";        // the Interest Bank is stored as a fact, never a result
            if (!id) { var n = 1; while (usedP["proof-new-" + n]) { n++; } id = "proof-new-" + n; usedP[id] = true; }
            it.id = id;
            outP.push(stamp(it, byId(oldP, id), C, it.title, (byId(oldP, id) || {}).title));
          });
          var items = $(fid(field, "items"));
          ((items && items.getAttribute("data-removed")) || "").split(" ").filter(Boolean).forEach(function (rid) { outP.push({ id: rid, remove: true, status: "confirmed" }); });
          if (items) { items.querySelectorAll("[data-removed]").forEach(function (row) { outP.push({ id: row.getAttribute("data-removed"), remove: true, status: "confirmed" }); }); }
          if (!outP.length) { throw new Error("Give it a few words at least, or Skip."); }
        } else { local.skip[field.id] = true; saveLocal(); }
        dp.proof = mergeList(oldP, outP); put("deep", dp); break;
      }
      case "story_card": {
        var d = a && typeof a === "object" ? a : {}, oldS = itemsOf(field)[0], tx = val(fid(field, "text")).trim();
        var id = (oldS && oldS.id) || "story-" + field.story_kind;
        var rest = (d.stories || []).filter(function (x) { return x.id !== id; });
        if (tx || C === "skipped") { rest.push(stamp({ id: id, kind: field.story_kind, text: tx || undefined }, oldS, tx ? C : "skipped", tx, oldS && oldS.text)); }
        d.stories = rest; put("deep", d); break;
      }
    }
    var pv = provenanceFor(field, C);
    if (pv) { put("provenance", pv); }
    return out;
  }
  // Where this question's words came from (N3): a pack or Claude's suggestion the owner put in the box, or an
  // idea that prompted their own words. Kept by question id, so it survives editing and reopening.
  function provenanceFor(field, C) {
    var box = document.querySelector('[data-field="' + field.id + '"]');
    var map = clone(answer("provenance")) || {}, cur = null;
    var gen = box && box.querySelector("textarea[data-gen], input[data-gen]");
    if (C === "confirmed" && gen) {
      cur = { origin: gen.getAttribute("data-origin"), generator: gen.getAttribute("data-gen") };
      if (gen.getAttribute("data-edited")) { cur.edited = true; }
      if (gen.getAttribute("data-mixed")) {
        var before = map[field.id] || { origin: ((holder(field) || {}).origin) || "person" };
        cur.mixed = true; cur.parts = [clone(before), { origin: cur.origin, generator: cur.generator }];
      }
    } else if (C === "confirmed" && prompted[field.id]) {
      cur = { origin: "person", prompted_by: prompted[field.id] };
    }
    if (!cur) {
      if (C === "skipped" && map[field.id]) { delete map[field.id]; return map; }      // nothing kept, nothing to record
      return null;
    }
    map[field.id] = cur;
    return map;
  }
  function sharesKey(field) {
    return F.core.filter(function (f) { return f.key === field.key && !f.path && f.kind === "object"; }).length > 1;
  }
  // Fields sharing this answer whose drafted text has not been checked: confirming this one would confirm them
  // too (they share one status), e.g. the brand name and a drafted handle. Lists keep their own statuses.
  function uncheckedSiblings(field) {
    if (field.path || (field.kind !== "object" && field.kind !== "name")) { return []; }
    return F.core.filter(function (f) {
      return f !== field && f.key === field.key && !f.path && (f.kind === "object" || f.kind === "name") && stateOf(f) === "check";
    });
  }

  // What's typed or tapped on a field but not saved yet, so leaving it (design B's Next, a redraw) never loses it.
  var unsaved = {}, restoring = false;
  /* What's typed or tapped on a question but not confirmed yet, as plain values only (never page code): the
     question's own boxes and choices, and its list rows (each row's id, its boxes, its choices, its quote yes and
     where its words came from). Kept on this computer: in the answers file through the page's server, so it
     survives a reopen days later, and in the browser as a second copy. It never counts and never reaches the
     brand: only a confirm does (rev 13, M5; #43 gap 8). */
  var ROW_MARKS = ["gen", "origin", "text", "cand", "source"];
  function partName(id) { return String(id).replace(/^.*-[si]\d+-/, ""); }
  function capture(field) {
    var box = document.querySelector('[data-field="' + field.id + '"]');
    if (!box) { return null; }
    var snap = { inputs: {}, pressed: {}, lists: {} };
    box.querySelectorAll(".items[id]").forEach(function (l) {
      var rows = [];
      l.querySelectorAll(".item").forEach(function (row) {
        var r = { id: row.getAttribute("data-id") || "", hidden: !!row.hidden, inputs: {}, pressed: {}, marks: {} };
        row.querySelectorAll("input[id], textarea[id]").forEach(function (el) { r.inputs[partName(el.id)] = el.type === "checkbox" ? el.checked : el.value; });
        row.querySelectorAll(".choices[id]").forEach(function (g) { r.pressed[partName(g.id)] = Array.prototype.map.call(g.querySelectorAll("[aria-pressed=true]"), function (b) { return b.getAttribute("data-val"); }); });
        ROW_MARKS.forEach(function (k) { var v = row.getAttribute("data-" + k); if (v != null) { r.marks[k] = v; } });
        if (row.querySelector("[data-quote-yes]")) { r.quoteYes = row.querySelector("[data-quote-yes]").getAttribute("aria-pressed") === "true"; }
        rows.push(r);
      });
      snap.lists[l.id] = { rows: rows, removed: l.getAttribute("data-removed") || "" };
    });
    box.querySelectorAll("input[id], textarea[id]").forEach(function (el) {
      if (!el.closest(".items")) { snap.inputs[el.id] = el.type === "checkbox" ? el.checked : el.value; }
    });
    box.querySelectorAll(".choices[id]").forEach(function (g) {
      if (!g.closest(".items")) { snap.pressed[g.id] = Array.prototype.map.call(g.querySelectorAll("[aria-pressed=true]"), function (b) { return b.getAttribute("data-val"); }); }
    });
    var cy = $(fid(field, "core-quote")); if (cy) { snap.coreYes = quoteYes(cy); }
    box.querySelectorAll("[data-part-yes]").forEach(function (b) {
      snap.partYes = snap.partYes || {}; snap.partYes[b.getAttribute("data-part-yes")] = b.getAttribute("aria-pressed") === "true";
    });
    return snap;
  }
  function restore(field, snap) {
    if (!snap) { return; }
    var was = restoring; restoring = true;
    try { restoreNow(field, snap); } finally { restoring = was; }
  }
  function setPressed(g, vals) {
    if (g) { g.querySelectorAll("button.choice").forEach(function (b) { b.setAttribute("aria-pressed", String((vals || []).indexOf(b.getAttribute("data-val")) >= 0)); }); }
  }
  function setYes(b, on) { if (b) { b.setAttribute("aria-pressed", String(!!on)); b.textContent = on ? "Yes, my words \u2713" : "Yes, these are my words"; } }
  function restoreNow(field, snap) {
    Object.keys(snap.lists || {}).forEach(function (id) {
      var l = $(id), s = snap.lists[id]; if (!l || !s || !Array.isArray(s.rows)) { return; }
      var removed = String(s.removed || "").split(" ").filter(Boolean), keepIds = {};
      s.rows.forEach(function (r) { if (r.id) { keepIds[r.id] = true; } });
      // Rows the owner removed (or that aren't in the kept typing any more) go; their ids stay marked removed.
      l.querySelectorAll(".item").forEach(function (row) {
        var rid = row.getAttribute("data-id");
        if (rid && (removed.indexOf(rid) >= 0 || !keepIds[rid])) { if (removed.indexOf(rid) < 0) { removed.push(rid); } row.parentNode.removeChild(row); }
      });
      if (removed.length) { l.setAttribute("data-removed", removed.join(" ")); } else { l.removeAttribute("data-removed"); }
      var used = [];
      s.rows.forEach(function (r) {
        var rows = Array.prototype.slice.call(l.querySelectorAll(".item"));
        var row = (r.id && rows.filter(function (x) { return x.getAttribute("data-id") === r.id; })[0]) ||
                  rows.filter(function (x) { return !x.getAttribute("data-id") && used.indexOf(x) < 0; })[0];
        if (!row) {
          var add = l.nextElementSibling;
          if (add && add.hasAttribute("data-add")) { add.click(); }
          rows = l.querySelectorAll(".item"); row = rows[rows.length - 1];
          if (!row || used.indexOf(row) >= 0) { return; }
        }
        used.push(row);
        row.hidden = !!r.hidden;
        row.setAttribute("data-id", r.id || "");
        ROW_MARKS.forEach(function (k) { if (r.marks && r.marks[k] != null) { row.setAttribute("data-" + k, r.marks[k]); } else { row.removeAttribute("data-" + k); } });
        row.querySelectorAll("input[id], textarea[id]").forEach(function (el) {
          var v = (r.inputs || {})[partName(el.id)];
          if (el.type === "checkbox") { el.checked = !!v; } else { el.value = v == null ? "" : String(v); }
        });
        row.querySelectorAll(".choices[id]").forEach(function (g) { setPressed(g, (r.pressed || {})[partName(g.id)]); });
        setYes(row.querySelector("[data-quote-yes]"), r.quoteYes);
      });
    });
    Object.keys(snap.inputs || {}).forEach(function (id) {
      var el = $(id); if (!el) { return; }
      if (el.type === "checkbox") { el.checked = !!snap.inputs[id]; el.dispatchEvent(new Event("change")); } else { el.value = String(snap.inputs[id]); el.dispatchEvent(new Event("input")); }
    });
    Object.keys(snap.pressed || {}).forEach(function (id) { setPressed($(id), snap.pressed[id]); });
    if (snap.coreYes != null) { var cq = $(fid(field, "core-quote")); setYes(cq && cq.querySelector("[data-quote-yes]"), snap.coreYes); }
    Object.keys(snap.partYes || {}).forEach(function (part) {
      var b = $(fid(field, "yes-" + part)); if (!b) { return; }
      b.setAttribute("aria-pressed", String(!!snap.partYes[part])); b.textContent = snap.partYes[part] ? "Kept ✓" : "Yes, keep this";
    });
  }
  function loadTyped() { try { var x = JSON.parse(localStorage.getItem(typedKey) || "null"); if (x) { unsaved = x; checkedTyping = clone(x); } } catch (e) {} }
  // The browser copy holds only what the server has already checked: each question's last accepted snapshot.
  var checkedTyping = {};
  function saveLocalTyped() {
    try { localStorage.setItem(typedKey, JSON.stringify(checkedTyping)); } catch (e) {}
  }
  // The server's copy is the one that lasts; each question's typing is sent in order, numbered, one after another.
  var typingQueue = Promise.resolve(), typingRev = {}, editVer = {};
  var failedTyping = {};                    // field id -> a save of its typing failed; tried again before Finish
  function sendTyping(field, snap) {
    var rev = (typingRev[field.id] = (typingRev[field.id] || 0) + 1), seen = editVer[field.id] || 0;
    var sent = snap ? clone(snap) : null;
    var run = typingQueue.then(function () {
      return api("typing", { field: field.id, snap: sent, rev: rev }).then(function (r) {
        if (r && r.stale) { return; }
        if (typingRev[field.id] === rev) { delete failedTyping[field.id]; }      // the newest copy is kept
        if (sent) { checkedTyping[field.id] = sent; } else { delete checkedTyping[field.id]; }
        saveLocalTyped();
      }, function (e) {
        if (e.status === 422) {                // looked like a key: thrown away everywhere, and said so
          delete checkedTyping[field.id];
          saveLocalTyped();
          // Only when nothing newer was typed or sent since: then "I've deleted it" is true, and the box goes back.
          if (typingRev[field.id] === rev && (editVer[field.id] || 0) === seen) {
            delete unsaved[field.id]; field._dirty = false; clearTimeout(typedTimers[field.id]); delete typedTimers[field.id];
            if (UI.current && UI.current() === field) { UI.saved(field); }
            err(field, e.message);
          } else {                                // newer typing is on its way: say so without claiming it's gone
            err(field, "That looked like a password or key, so it wasn't kept. Take it out of the box; keys go in your keys file, never here.");
          }
        } else if (e.status && e.status < 500) {  // refused for its shape: said; trying again can't help, so Finish doesn't wait
          if (typingRev[field.id] === rev) { delete failedTyping[field.id]; }   // an older failure is out of date too
          err(field, e.message);
        } else {                                // no answer: said, and kept to try again before Finish
          if (typingRev[field.id] === rev) { failedTyping[field.id] = true; }   // a newer save may still succeed
          err(field, "Your typing on this question couldn't be kept on this computer yet. It's still here; it will be tried again.");
        }                                       // nothing unchecked is written to the browser copy
      });
    });
    typingQueue = run.catch(function () {});
    return run;
  }
  function saveTyped(field) { if (field) { var u = unsaved[field.id]; sendTyping(field, u && u.dirty ? u : null); } else { saveLocalTyped(); } }
  function typed(field) { return !!(unsaved[field.id] && unsaved[field.id].dirty); }
  function keep(field) {
    var s = capture(field); if (!s) { return; }
    var wasDirty = !!(unsaved[field.id] && unsaved[field.id].dirty);
    s.dirty = wasDirty || !!field._dirty;
    if (usedCand[field.id]) { s.usedCand = clone(usedCand[field.id]); }
    unsaved[field.id] = s;
    if (s.dirty) { saveTyped(field); }
  }
  function bringBack(field) {
    var u = unsaved[field.id];
    delete usedCand[field.id];                  // never a stale proposal: restored below only if still waiting
    restore(field, u);
    if (typed(field)) { showTyped(field); }
    // A proposal still waiting in the box: only while its alternative is still there (not decided since).
    if (u && u.usedCand && alternativesFor(field).some(function (x) { return x.cid === u.usedCand.cid; })) {
      usedCand[field.id] = u.usedCand;
      showUsing(field, document.querySelector('[data-field="' + field.id + '"]'));
    }
  }
  var typedTimers = {};                  // one save timer per question, so one never cancels another
  function markTyped(field) {
    if (restoring) { return; }
    editVer[field.id] = (editVer[field.id] || 0) + 1;      // every edit counts at once, before the save timer runs
    field._dirty = true; showTyped(field);
    clearTimeout(typedTimers[field.id]);
    typedTimers[field.id] = setTimeout(function () { delete typedTimers[field.id]; keep(field); }, 400);
  }
  function showTyped(field) {
    var t = $(fid(field, "typed")); if (t) { t.hidden = false; }
    var c = document.querySelector('[data-chip="' + field.id + '"]');
    if (c) { c.outerHTML = chip(field, true); }
  }
  // Only after a confirm (or a skip that kept nothing) has been saved: the waiting copy goes, here and on the server.
  function clearTyped(field) {
    clearTimeout(typedTimers[field.id]); delete typedTimers[field.id];
    delete unsaved[field.id]; field._dirty = false;
    sendTyping(field, null);
  }
  function redrawKeeping(field) { var s = capture(field); UI.saved(field); restore(field, s); }

  function err(field, msg) { var e = $(fid(field, "error")); if (e) { e.textContent = msg || ""; e.hidden = !msg; } }
  function send(field, jobs, ownWords) {
    var chain = Promise.resolve();
    jobs.forEach(function (j) {
      if (ownWords && j.answer && typeof j.answer === "object") { j.answer.own_words = true; }
      chain = chain.then(function () { return api("answer", { key: j.key, answer: j.answer }); }).then(function (s) { S = s; });
    });
    return chain;
  }
  // Saves run one after another: each builds its whole answer from what the server last said, so two quick
  // saves on questions sharing an answer (the audience, the name) never overwrite each other.
  var queue = Promise.resolve();
  function save(field, status, ownWords) {
    var run = queue.then(function () { return saveNow(field, status, ownWords); });
    queue = run.catch(function () {});
    return run;
  }
  function saveNow(field, status, ownWords) {
    err(field, "");
    var jobs;
    try { jobs = collect(field, status); } catch (e) { err(field, e.message); return Promise.resolve(false); }
    if (status !== "skipped") {
      var sib = uncheckedSiblings(field);
      if (sib.length && !field._sibOk) {
        err(field, "Confirming this also confirms the drafted answer to: " + sib.map(function (f) { return "question " + f.n; }).join(", ") + ". Check it first, or tap Confirm again to confirm both.");
        field._sibOk = true; return Promise.resolve(false);
      }
    }
    field._sibOk = false;
    if (status === "skipped") { local.skip[field.id] = true; } else { delete local.skip[field.id]; }
    delete local.chat[field.id]; saveLocal();
    // Every wait shows something moving (design review, Oct 16: "I clicked something, and then I get something visual").
    var btn = document.querySelector('[data-field="' + field.id + '"] [data-act=' + (status === "skipped" ? "skip" : "confirm") + "]");
    if (btn) { btn.classList.add("busy"); btn.disabled = true; }
    var done = function () { if (btn) { btn.classList.remove("busy"); btn.disabled = false; } };
    var uc = status === "confirmed" ? usedCand[field.id] : null;
    return send(field, jobs, ownWords).then(function () {
      if (uc && uc.cid) { delete usedCand[field.id]; return api("candidate", { key: uc.key, part: uc.part, cid: uc.cid }).then(function (s) { S = s; }, function () {}); }
    }).then(function () {
      done();
      // Skipping never throws typing away: it stays, not confirmed, for when the owner comes back.
      if (status === "skipped") {
        var snap = capture(field);
        if (snap && (typed(field) || field._dirty)) { snap.dirty = true; unsaved[field.id] = snap; saveTyped(field); } else { clearTyped(field); }
      } else { clearTyped(field); }
      UI.saved(field);
      // The "where X posts" rows follow the speakers; anything already tapped there is kept.
      if (field.key === "identities") { redrawKeeping(fieldById("goal_platforms")); }
      return true;
    }).catch(function (e) {
      done();
      if (e.status === 409 && /own words/.test(e.message)) {
        err(field, e.message);
        var box = $(fid(field, "error"));
        box.insertAdjacentHTML("beforeend", ' <button type="button" class="link" id="' + fid(field, "own") + '">Yes, these are my own words</button>');
        $(fid(field, "own")).onclick = function () { save(field, status, true); };
      } else { err(field, e.message); }
      return false;
    });
  }

  function act(field, what, btn) {
    if (what === "confirm") {
      if (blank(field)) { err(field, "Type an answer, or tap Skip for now."); return Promise.resolve(false); }
      return save(field, "confirmed").then(function (ok) { if (ok && UI.flow) { UI.next(field); } return ok; });
    }
    if (what === "later") { stopRecording(true); if (field._dirty) { keep(field); } return UI.next(field); }
    if (what === "skip") { stopRecording(true); return save(field, "skipped").then(function (ok) { if (ok) { UI.next(field); } }); }
    if (what === "chat") { local.chat[field.id] = true; delete local.skip[field.id]; saveLocal(); UI.saved(field); return; }
    if (what === "unchat") { delete local.chat[field.id]; saveLocal(); UI.saved(field); return; }
    if (what === "example") {
      var ex = $(fid(field, "example")), on = ex.hidden; ex.hidden = !on; btn.setAttribute("aria-expanded", String(on));
      btn.textContent = on ? "Hide the example" : "What goes here? Show an example"; return;
    }
    if (what === "talk") { return rec.cur && rec.cur.field === field.id ? stopRecording(false) : startRecording(field); }
    if (what === "suggest") { return showSuggestion(field, btn); }
    if (what === "ideas") { return showIdeas(field, btn); }
    if (what === "compliance") {
      // Only turned on by the owner's tap: a type of business never switches rules on by itself (N3).
      var pk = pack(), g = $(fid(field, "industry"));
      if (g && pk) { g.querySelectorAll("button.choice").forEach(function (o) { o.setAttribute("aria-pressed", String(o.getAttribute("data-val") === pk.compliance_candidate)); }); }
      btn.parentNode.innerHTML = "Set to <b>" + esc(pk.compliance_candidate) + "</b> rules. Tap Confirm to keep it.";
      return;
    }
  }
  // Nothing typed, ticked or tapped in a written answer (an answer already confirmed may still be cleared).
  var WRITTEN = ["object", "name", "items", "pairs", "beliefs", "story", "foragainst"];
  function blank(field) {
    if (WRITTEN.indexOf(field.kind) < 0 || stateOf(field) === "ok") { return false; }
    var box = document.querySelector('[data-field="' + field.id + '"] .body');
    if (!box) { return false; }
    var typedSomething = Array.prototype.some.call(box.querySelectorAll("input[type=text], input[type=number], textarea"), function (el) { return el.value.trim() !== ""; });
    var tapped = field.kind === "object" && box.querySelector(".choices [aria-pressed=true]");
    return !typedSomething && !tapped;
  }
  function hasBox(field) { return ["home", "colours", "rung"].indexOf(field.kind) < 0; }

  // ------------------------------------------------------------------ "What you stand for": skip the strategy part
  function parkStrategy(on) {
    var p = clone(answer("positioning")) || {};
    p.parked = !!on;
    var stand = F.core.filter(function (f) { return f.group === "stand"; });
    stand.forEach(function (f) { if (on) { local.skip[f.id] = true; } else { delete local.skip[f.id]; } });
    saveLocal();
    return api("answer", { key: "positioning", answer: p }).then(function (s) { S = s; stand.forEach(function (f) { redrawKeeping(f); }); });
  }

  // ------------------------------------------------------------------ talking
  var rec = { cur: null };     // the recording now running, if any
  function speak(text) {
    return new Promise(function (done) {
      if (!prefs.read || !window.speechSynthesis) { return done(); }
      var u = new SpeechSynthesisUtterance(text); u.onend = done; u.onerror = done;
      window.speechSynthesis.cancel(); window.speechSynthesis.speak(u);
    });
  }
  function talkTarget(field) {
    var box = document.querySelector('[data-field="' + field.id + '"]');
    var act = document.activeElement;
    if (act && box && box.contains(act) && act.hasAttribute("data-talk")) { return act; }
    return box ? box.querySelector("[data-talk]") : null;
  }
  function setTalk(field, on) {
    var b = document.querySelector('[data-field="' + field.id + '"] [data-act=talk]');
    if (b) { b.setAttribute("aria-pressed", String(on)); b.innerHTML = MIC + (on ? "Stop" : "Talk"); b.classList.toggle("recording", on); }
  }
  /* One recording at a time. Each recording carries its own state (which question, which box, what the box
     said before), so a recording that is still stopping can never hand its words to the next one. */
  function startRecording(field) {
    if (rec.cur) { stopRecording(true); }
    if (!voiceAvailable) { return dictationHint(field); }
    if (!consented) { return askConsent(field); }
    var target = talkTarget(field);
    if (!target) { return err(field, "This question is answered by tapping. You can say “keep it”, “skip” or “next”."); }
    var mine = { field: field.id, target: target.id, before: target.value, chunks: [], discard: false, recorder: null, timer: null };
    rec.cur = mine;
    setTalk(field, true);
    // Read-aloud finishes before the microphone opens, and echo cancellation keeps the page's own voice out.
    speak(field.ask).then(function () { return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }).then(function (stream) {
      if (rec.cur !== mine) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }    // stopped while waiting
      var r = new MediaRecorder(stream); mine.recorder = r;
      r.ondataavailable = function (e) { if (e.data && e.data.size) { mine.chunks.push(e.data); } };
      r.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        if (rec.cur === mine) { rec.cur = null; setTalk(field, false); }
        var blob = new Blob(mine.chunks, { type: r.mimeType || "audio/webm" });
        if (!mine.discard && blob.size) { transcribe(blob, field, mine.target, mine.before); }
      };
      r.start();
      mine.timer = setTimeout(function () { if (rec.cur === mine) { stopRecording(false); } }, 120000);
      api("microphone", { state: "ok" }).catch(function () {});
    }).catch(function (e) {
      if (rec.cur === mine) { rec.cur = null; setTalk(field, false); }
      api("microphone", { state: e && e.name === "NotFoundError" ? "missing" : "denied" }).catch(function () {});
      err(field, "I can't hear your microphone. Check the browser's permission, or type instead.");
    });
  }
  function stopRecording(discard) {
    var mine = rec.cur;
    if (!mine) { return; }
    clearTimeout(mine.timer);
    mine.discard = !!discard;
    rec.cur = null;
    var f = fieldById(mine.field); if (f) { setTalk(f, false); }
    if (mine.recorder && mine.recorder.state !== "inactive") { mine.recorder.stop(); }       // onstop sends it, unless discarded
  }
  function transcribe(blob, field, targetId, before) {
    var heard = $(fid(field, "heard"));
    if (heard) { heard.innerHTML = '<p class="small busy">Turning what you said into words…</p>'; }
    fetch(base + "listen?q=" + encodeURIComponent(field.key), { method: "POST", headers: { "Content-Type": blob.type.split(";")[0] || "audio/webm" }, body: blob })
      .then(function (res) { return res.json().catch(function () { return {}; }).then(function (b) { if (!res.ok) { throw new Error(b.error || "I didn't catch that. Try again, or type it."); } return b; }); })
      .then(function (r) { understood(r, field, targetId, before); })
      .catch(function (e) { if (heard) { heard.innerHTML = ""; } err(field, e.message); });
  }
  function understood(r, field, targetId, before) {
    var heard = $(fid(field, "heard"));
    if (!heard) { return; }             // the person has moved on: a late answer never lands on another question
    heard.innerHTML = "";
    if (r.kind === "secret" || r.kind === "for_chat") { return err(field, r.message); }
    if (r.kind === "command") { return command(r.command, field, targetId); }
    var el = $(targetId);
    if (!el) { return; }
    if (el.value !== before) {          // they typed while it was listening: offer, never overwrite
      heard.innerHTML = '<p class="small">I heard: “' + esc(r.text) + '”</p><button type="button" class="link" id="' + fid(field, "use") + '">Use what I heard</button>';
      $(fid(field, "use")).onclick = function () { insertHeard(field, el, r.text); heard.innerHTML = ""; };
      return;
    }
    insertHeard(field, el, r.text);
    if (field.kind === "samples") { var row = el.closest(".item"); if (row) { row.setAttribute("data-source", "spoken"); } }
    heard.innerHTML = '<p class="small">Check what I heard, then say “keep it”, or tap Confirm. Say “try again” to redo it.</p>';
  }
  // Remember exactly what speaking changed, so "try again" can take back those words and nothing else.
  function insertHeard(field, el, text) {
    var before = el.value;
    insert(el, text);
    lastHeard[field.id] = { target: el.id, before: before, after: el.value };
  }
  function insert(el, text) {
    if (el.tagName === "TEXTAREA" && el.value.trim()) { el.value = el.value.replace(/\s+$/, "") + "\n" + text; } else { el.value = text; }
    el.dispatchEvent(new Event("input"));
  }
  var lastHeard = {};          // per question: the box the last spoken words went into, and what it said before
  function command(name, field) {
    if (name === "confirm" || name === "save") {
      if (field.tap || field.kind === "name" || field.kind === "identities" || field.kind === "rules") { return err(field, "Names, handles and rules need a tap. Check the spelling, then tap Confirm."); }
      return save(field, "confirmed");
    }
    if (name === "retry") {        // "try again": take back only what was just heard, then listen again
      var h = lastHeard[field.id], t = h && $(h.target);
      // Only when the box still says exactly what speaking made it say: anything typed since is never erased.
      if (t && t.value === h.after) { t.value = h.before; t.dispatchEvent(new Event("input")); t.focus(); }
      delete lastHeard[field.id];
      return startRecording(field);
    }
    if (name === "skip") { return act(field, "skip"); }
    if (name === "next") { return UI.next(field); }
    if (name === "back") { return UI.back(field); }
    if (name === "repeat") { prefs.read = true; return speak(field.ask); }
    if (name === "explain") { var b = document.querySelector('[data-field="' + field.id + '"] [data-act=example]'); if (b) { b.click(); } return; }
    if (name === "type" || name === "pause") { return; }
    if (name === "finish_chat") { return finish("chat"); }
  }
  // No working voice key: the mic records nothing. It puts the cursor back in the box and points to the computer's
  // own dictation, with no sign-up and no cost named mid-onboarding (rev 12, N1).
  function dictationHint(field) {
    var heard = $(fid(field, "heard")), target = talkTarget(field);
    var mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
    heard.innerHTML = '<div class="consent"><p>Use your computer\'s own dictation: ' +
      (mac ? "press the dictation key, or <b>Fn</b> twice." : "press <b>Windows + H</b>.") + " Then just talk; the words land in the box.</p>" +
      '<p class="small">Depending on your settings, your computer\'s dictation may send your voice to ' + (mac ? "Apple" : "Microsoft") + ".</p>" +
      (voiceState === "not_working" ? '<p class="small">Your ElevenLabs key isn\'t working. Say “check my setup” in the chat to fix it.</p>' : "") + "</div>";
    if (target) { target.focus(); }
  }
  function askConsent(field) {
    var heard = $(fid(field, "heard"));
    heard.innerHTML = '<div class="consent"><p>What you say goes to ElevenLabs to be turned into words. The audio isn\'t saved; the words are saved with your answers. <b>Don’t say passwords or keys out loud.</b></p>' +
      (voiceCost ? '<p class="small">It uses your ElevenLabs account: ' + esc(voiceCost) + "</p>" : "") +
      '<div class="row"><button type="button" class="main" id="' + fid(field, "consent-yes") + '">OK, start talking</button><button type="button" id="' + fid(field, "consent-no") + '">Type instead</button></div></div>';
    $(fid(field, "consent-yes")).onclick = function () {
      api("consent", { recording: true }).then(function () { consented = true; heard.innerHTML = ""; startRecording(field); }).catch(function (e) { err(field, e.message); });
    };
    $(fid(field, "consent-no")).onclick = function () { heard.innerHTML = ""; };
  }
  function fieldById(id) { return F.core.concat(F.extra || [], F.deep).filter(function (f) { return f.id === id; })[0]; }
  // The core in page order, with rev 12's optional questions placed right after the one they follow.
  function coreOrder() {
    var out = [];
    F.core.forEach(function (f) { out.push(f); (F.extra || []).forEach(function (x) { if (x.after === f.id) { out.push(x); } }); });
    return out;
  }

  /* Rev 13 (M3, M4): what Claude read from the owner's material, and what it gave each question. With an
     inventory, design B asks what's missing first, then what needs the owner's own words, then the partly
     answered, then the drafts to check; inside each group, the core order. "Check the drafts first" flips it. */
  function inventory() { var i = answer("inventory"); return i && typeof i === "object" ? i : null; }
  var GROUPS = ["missing", "your words needed", "partly", "found"];
  function coverage(field) {
    var inv = inventory(), c = inv && inv.fields && inv.fields[field.id];
    return c && GROUPS.indexOf(c.coverage) >= 0 ? c.coverage : (inv ? "unchecked" : "");
  }
  var draftsFirst = false;
  var route = null;                       // design B's fixed route, once its questions start (so labels match Next)
  function setRoute(r) { route = r; }
  // The next (dir 1) or previous (dir -1) question in a route, passing over "what you stand for" while it's set
  // aside: wherever the order put those questions, Next and Back never land on, or bounce off, them. With no `f`,
  // the first (dir 1) or last (dir -1) such question.
  function stepIn(list, f, dir) {
    var p = answer("positioning"), parked = !!(p && p.parked);
    var from = f == null ? (dir < 0 ? list.length : -1) : list.indexOf(f);
    for (var j = from + dir; j >= 0 && j < list.length; j += dir) {
      if (!(parked && list[j] && list[j].group === "stand")) { return list[j]; }
    }
    return null;
  }
  // Reopening with new material (M5): the questions it touched come first. Part keys look like "positioning.core_belief".
  function partOf(field) {
    return field.kind === "beliefs" ? "core_belief" : field.list || field.path || (field.kind === "foragainst" ? "for" : field.kind === "story" ? "story" : "");
  }
  function isNew(field) { return hasCandidate(field); }      // new material waiting beside this question
  var FIELD_PARTS = { beliefs: ["core_belief", "contrarian"], foragainst: ["for", "against"], home: ["home_medium", "stage"], story: ["story"] };
  function fieldParts(field) { return FIELD_PARTS[field.kind] || [field.list, field.path].filter(Boolean); }
  // Every alternative waiting beside this question: [{key, part, cid, answer}].
  function alternativesFor(field) {
    var c = (S && S.candidates) || {}, out = [];
    function take(box, part) {
      ((box && box.alternatives) || []).forEach(function (x) {
        if (x && x.cid) { out.push({ key: field.key, part: part, cid: x.cid, answer: x.answer }); }
        else if (x) { out.push({ key: field.key, part: part, cid: "", answer: x }); }
      });
    }
    var box = c[field.key];
    if (box && ["positioning", "teach", "deep"].indexOf(field.key) >= 0 && !box.alternatives) {
      fieldParts(field).forEach(function (p) { take(box[p], p); });
    } else if (box && !box.alternatives) {
      take(box[field.id], field.id);      // a key several questions share: kept question by question (M5)
    } else { take(box, ""); }
    return out;
  }
  function candidateFor(field) { var a = alternativesFor(field); return a.length ? { alternatives: a.map(function (x) { return x.answer; }) } : null; }
  function hasCandidate(field) { return alternativesFor(field).length > 0; }
  function candidateText(v) {
    if (v && typeof v === "object" && Array.isArray(v.alternatives)) {
      return v.alternatives.map(candidateText).filter(Boolean).join("\u201d \u00b7 or: \u201c");
    }
    if (typeof v === "string") { return v; }
    if (Array.isArray(v)) { return v.map(candidateText).filter(Boolean).join("; "); }
    if (v && typeof v === "object" && (v.background || v.accent)) {      // colours
      return ["background", "text", "accent"].filter(function (k) { return v[k]; }).map(function (k) { return k + " " + v[k]; }).join(", ");
    }
    if (v && typeof v === "object") { return v.value || v.text || v.who || v.catalyst || ((v.others || v.us) ? (v.others || "") + " / " + (v.us || "") : ""); }
    return "";
  }
  // A shared key's alternative holds only its question's own parts ({handle}, {in_the_way}, {register, do}...):
  // shown by those parts, so "Your new material says" is never empty quotes.
  function candidateTextFor(field, v) {
    var t = candidateText(v);
    if (t || !v || typeof v !== "object" || Array.isArray(v)) { return t || (Array.isArray(v) ? v.map(function (x) { return x && (x.name || x.value) || ""; }).filter(Boolean).join("; ") : ""); }
    return (field.parts || []).map(function (p) { var x = v[p.name]; return Array.isArray(x) ? x.join(", ") : (x == null ? "" : String(x)); })
      .filter(Boolean).join(" · ");
  }
  function flowOrder() {
    var base = coreOrder();
    var anyNew = F.core.some(hasCandidate);
    if (!inventory() && !anyNew) { return base; }
    var rank = draftsFirst ? ["found", "partly", "missing", "unchecked", "your words needed"] : ["missing", "unchecked", "your words needed", "partly", "found"];
    var core = F.core.slice().sort(function (a, b) {
      var fresh = (isNew(b) ? 1 : 0) - (isNew(a) ? 1 : 0);
      var d = inventory() ? rank.indexOf(coverage(a)) - rank.indexOf(coverage(b)) : 0;
      return fresh || d || a.n - b.n;
    });
    var out = [];
    core.forEach(function (f) { out.push(f); (F.extra || []).forEach(function (x) { if (x.after === f.id) { out.push(x); } }); });
    return out;
  }
  // Rev 14 (design review, Oct 22): five steps, then "One more thing" (rules); every other question is "Make it better",
  // reachable any time and never in the main route. Each question keeps its own Confirm: a step never confirms anything.
  function steps() {
    return (F.five_steps || []).map(function (s) {
      return { id: s.id, title: s.title, optional: s.optional || [], fields: s.fields.map(fieldById).filter(Boolean) };
    });
  }
  function oneMore() { return (F.one_more || []).map(fieldById).filter(Boolean); }
  function stepOf(field) { var ss = steps(); for (var i = 0; i < ss.length; i++) { if (ss[i].fields.indexOf(field) >= 0) { return i; } } return -1; }
  function inFive(field) { return stepOf(field) >= 0 || oneMore().indexOf(field) >= 0; }
  function betterFields() { return coreOrder().filter(function (f) { return !inFive(f); }); }
  // The route: the five steps' questions, then "one more thing", then any "Make it better" question with new material
  // waiting beside it (never hidden just because its question moved out of the five).
  function fiveRoute() {
    var r = [];
    steps().forEach(function (s) { r = r.concat(s.fields); });
    return r.concat(oneMore(), betterFields().filter(hasCandidate));
  }
  // A step is done when each of its questions is confirmed (an optional one may also be left), and nothing drafted waits.
  function stepDone(i) {
    var s = steps()[i];
    return !!s && s.fields.every(function (f) {
      if (hasCandidate(f)) { return false; }          // new material still waiting for a decision
      var st = typed(f) ? "typed" : stateOf(f);
      return st === "ok" || (s.optional.indexOf(f.id) >= 0 && (st === "wait" || st === "skipped"));
    });
  }
  // "ok" when done; "check" when a draft or typing in it still waits for the owner's yes; "" otherwise.
  function stepState(i) {
    var s = steps()[i];
    if (!s) { return ""; }
    if (stepDone(i)) { return "ok"; }
    return s.fields.some(function (f) { return typed(f) || hasCandidate(f) || stateOf(f) === "check"; }) ? "check" : "";
  }
  // Where to start (rev 14, A8), one rule for both designs: new material in the five steps; then a five-step question
  // that needs the owner (a draft or typing waiting, or a required question not answered: an optional one left blank or
  // skipped doesn't count); then new material in Make it better; else null (show the status: "Your brand so far").
  function startAt() {
    var five = fiveRoute().filter(inFive), opt = {};
    steps().forEach(function (s) { s.optional.forEach(function (id) { opt[id] = true; }); });
    var needs = function (f) {
      var st = stateOf(f);
      if (typed(f) || st === "check") { return true; }
      return !opt[f.id] && st === "wait";
    };
    return five.filter(hasCandidate)[0] || five.filter(needs)[0] || betterFields().filter(hasCandidate)[0] || null;
  }
  // The five answers a first post needs (Oct 23): marked on the page, and named on the finish screen while missing.
  function isNeeded(field) { return !!field && (F.needed || []).indexOf(field.id) >= 0; }
  function neededLeft() {
    return (F.needed || []).map(fieldById).filter(function (f) { return f && stateOf(f) !== "ok"; })
      .map(function (f) { return (F.needed_names || {})[f.id] || f.ask; });
  }
  function neededLeftHTML() {
    var left = neededLeft();
    return left.length ? '<p class="needed-left"><b>To write your first post we still need:</b> ' + esc(left.join(", ")) + ".</p>" : "";
  }
  function questionState(f) { return typed(f) || hasCandidate(f) ? "check" : stateOf(f); }
  function stepsDone() { return steps().filter(function (s, i) { return stepDone(i); }).length; }
  function stepLabel(field) {
    var i = stepOf(field);
    if (i >= 0) { return "Step " + (i + 1) + " of " + steps().length + " \u00b7 " + steps()[i].title; }   // needed or optional: its own tag
    if (oneMore().indexOf(field) >= 0) { return "One more thing"; }
    if (field.n || field.after) {
      var g = F.groups.filter(function (x) { return x.id === field.group; })[0];
      return "Make it better" + (g ? " \u00b7 " + g.title : "");
    }
    return "Go deeper";
  }

  var COVER_LABEL = { found: "Found in your material", partly: "Partly found", missing: "Not in what was read", unchecked: "Not checked yet", "your words needed": "Needs your own words" };
  function coverageTag() { return ""; }          // rev 14: coverage stays stored, never shown as a tag
  function counts() {
    var n = { found: 0, partly: 0, missing: 0, unchecked: 0, "your words needed": 0 };
    F.core.forEach(function (f) { if (stateOf(f) !== "ok") { n[coverage(f)] = (n[coverage(f)] || 0) + 1; } });
    return n;
  }
  function isSourceRef(ref) {
    var inv = inventory() || {}, id = String(ref || "").split(/\s+/)[0];
    return (inv.sources || []).some(function (x) { return x.id === id; });
  }
  // "website: /about (About page)" reads "About page"; "website: /about#story" reads "/about#story" (never "website" twice).
  function refLabel(ref) {
    if (isSourceRef(ref)) { return sourceLabel(ref); }
    var x = String(ref || "").replace(/^website:\s*/, ""), named = x.match(/^\/\S*\s*\((.+)\)$/);
    return named ? named[1] : x;
  }
  function sourceName(ref) { return sourceLabel(ref).replace(/, page \d+$/, ""); }
  function sourceLabel(ref) {
    var inv = inventory() || {}, id = String(ref || "").split(/\s+/)[0];
    var src = (inv.sources || []).filter(function (x) { return x.id === id; })[0];
    var name = src ? String(src.name || "").replace(/\.[a-z0-9]{2,5}$/i, "") : "";
    var page = String(ref || "").match(/p\.\s?(\d+)/);
    var wpage = String(ref || "").match(/^website:\s*(.+)$/);
    // An older or free-text locator ("About page") is shown as it was written, never as "your document".
    var where = /^website/.test(String(ref)) ? "your website" + (wpage ? " (" + wpage[1].trim() + ")" : "") :
      (name || (id && !src && !/^src-/.test(id) ? String(ref).trim() : "your document"));
    return where + (page ? ", page " + page[1] : "");
  }
  // "What we found" (M4): the first screen when Claude has read the owner's material.
  function foundHTML() {
    var inv = inventory(), srcs = inv.sources || [], n = counts(), left = n.missing + n.unchecked + n["your words needed"] + n.partly;
    var nread = srcs.filter(function (x) { return !x.dont_use && (x.status === "read" || x.status === "partly read"); }).length;
    var minutes = Math.max(5, Math.round(left * 1.2 + n.found * 0.5));
    var stat = { read: "Read", "partly read": "Partly read", "couldn't read": "Couldn't read", "not read yet": "Not read yet" };
    return '<div class="first found"><p class="kicker">Social Media Factory</p><h1>What we found</h1>' +
      '<p class="lead">' + (n.found || n.partly ? "We drafted some of your answers from what you shared. Please check them as you go."
        : "We read what you shared. Now five short steps.") + "</p>" +
      '<p class="small">Start with whatever you have, and add more whenever you like.</p>' +
      '<ul class="sources">' + srcs.map(function (x) {
        return "<li><b>" + esc(x.name) + "</b><span class=\"small\">" + (x.dont_use ? "Not used: you marked it \u201cdon\u2019t use\u201d" : esc(stat[x.status] || x.status) + (x.covered ? ": " + esc(x.covered) : "")) + (x.note ? " · " + esc(x.note) : "") + "</span></li>";
      }).join("") + "</ul>" +
      '<div class="row"><button type="button" class="main big" id="found-start">Review your five steps</button>' +
        '<button type="button" class="link" id="found-more" aria-expanded="false">Add more material</button></div>' +
      '<div class="suggest" id="found-more-panel" hidden><p class="small">Put the new files in your material folder, then copy this into the chat:</p>' +
        '<p class="candidate" id="found-ask">I\u2019ve added material for my brand; please read it.</p><div class="row"><button type="button" id="found-copy">Copy</button>' +
        '<span class="small">You can carry on here meanwhile; new drafts show up next time the page opens.</span></div></div>' +
      '<details class="settings details-edit"><summary>Your business details · <span class="edit">Edit</span></summary><div id="found-first"></div></details></div>';
  }
  function wireFound(onStart) {
    var go = function (drafts) { draftsFirst = !!drafts; onStart(); };
    $("found-start").onclick = function () { var c = counts(); go(!(c.missing + c.unchecked + c["your words needed"] + c.partly)); };
    $("found-more").onclick = function () {
      var p = $("found-more-panel"); p.hidden = !p.hidden; $("found-more").setAttribute("aria-expanded", String(!p.hidden));
      if (!p.hidden) {                          // the folder opens on this computer; the copy line stays as a fallback
        api("open-material", {}).then(function (r) {
          if (r && r.opened) { p.querySelector("p.small").textContent = "Your material folder is open. Put the new files in it, then copy this into the chat:"; }
        }, function () {});
      }
    };
    $("found-copy").onclick = function () {
      var t = $("found-ask").textContent, b = $("found-copy");
      var ok = function () { b.textContent = "Copied"; };
      try { navigator.clipboard.writeText(t).then(ok, function () { selectText(); }); } catch (e) { selectText(); }
      function selectText() { var r = document.createRange(); r.selectNodeContents($("found-ask")); var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r); b.textContent = "Selected: press Ctrl+C"; }
    };
  }

  // ------------------------------------------------------------------ finishing
  function finish(via) {
    stopRecording(true);
    var f = UI.current && UI.current();
    // Every question with a save still waiting is saved now, then Finish waits for all of them.
    Object.keys(typedTimers).forEach(function (id) { clearTimeout(typedTimers[id]); delete typedTimers[id]; var q = fieldById(id); if (q) { keep(q); } });
    if (f && f._dirty) { keep(f); }
    // A save that failed earlier is tried once more; if it still fails, Finish stops and says so (gap 8).
    Object.keys(failedTyping).forEach(function (id) { var q = fieldById(id); if (q) { saveTyped(q); } });
    return typingQueue.then(function () {
      if (Object.keys(failedTyping).length) {
        throw new Error("Some of your typing couldn't be kept on this computer, so Finish waited. Check the page is still running, then try Finish again.");
      }
      return api("finish", { via: via });
    }).then(function (s) { S = s; UI.finished(); poll(); }, function (e) {
      // Said where the person is looking: under the Finish buttons, or at the top of the page.
      var box = $("finish-error");
      if (!box) {
        box = document.createElement("p"); box.className = "error"; box.id = "finish-error"; box.setAttribute("role", "alert");
        var at = $("finish-page"), main = document.querySelector("main") || document.body;
        if (at && at.parentNode) { at.parentNode.parentNode.insertBefore(box, at.parentNode.nextSibling); } else { main.insertBefore(box, main.firstChild); }
      }
      box.textContent = e.message; box.hidden = false;
    });
  }
  var polling = null;
  function poll() {
    if (polling) { return; }
    polling = setInterval(function () { api("session").then(function (s) { S = s; if (UI.handoff) { UI.handoff(); } if (s.handoff === "finished") { clearInterval(polling); polling = null; } }).catch(function () {}); }, 1500);
  }
  // The last screen, once Claude has built and checked the brand: the result, the summary, and the person's last tap
  // (Claude's second wait in the chat needs it). A failed build shows what to do instead, never the success buttons.
  function closingHTML() {
    var r = S && S.result;
    if (!(S && S.handoff === "finished" && r)) { return ""; }
    if (!r.ok) { return '<p class="small">Go back to the chat: Claude will sort it out with you. Your answers are safe.</p>'; }
    if (S.closing === "first-post") { return '<p class="lead">Go back to the chat: Claude is ready to write your first post with you.</p>'; }
    if (S.closing === "done") { return '<p class="lead">All done. You can close this page.</p>'; }
    return (r.has_summary ? '<p><a href="summary" target="_blank" rel="noopener">See your brand summary</a></p>' : "") +
      '<div class="row"><button type="button" class="main" id="close-first">Write my first post</button>' +
      '<button type="button" id="close-done">I\u2019m done</button></div><p class="error" id="close-error" role="alert" hidden></p>';
  }
  function wireClosing(redraw) {
    ["first", "done"].forEach(function (k) {
      var b = $("close-" + k); if (!b) { return; }
      b.onclick = function () {
        var e = $("close-error"); e.hidden = true;
        $("close-first").disabled = $("close-done").disabled = true; b.classList.add("busy");
        api("closing", { choice: k === "first" ? "first-post" : "done" }).then(function (s) { S = s; redraw(); }, function (x) {
          b.classList.remove("busy"); $("close-first").disabled = $("close-done").disabled = false;
          e.textContent = x.message + " Try again."; e.hidden = false;
        });
      };
    });
  }
  function handoffText() {
    var h = S && S.handoff;
    if (h === "finished" && S.result) { return S.result.message || "Your brand is built. Go back to the chat to see it."; }
    if (h === "building") { return "Claude is building your brand from your answers. This takes a minute or two."; }
    if (h === "trouble") { return "This is taking longer than it should. Go back to the chat; your answers are safe."; }
    if (h === "backstop") { return "Your answers are saved. Go back to the chat and say “I'm done with the page”."; }
    return "Your answers are with Claude. Go back to the chat; it picks them up from here.";
  }

  // ------------------------------------------------------------------ first screen
  // One warm line, one screen, one button (rev 12, N2; design review, Oct 16: "First simple step and a call to action").
  // Through the chat these come filled in; opened on its own, the page only suggests by type of business.
  function viaChat() {
    // Opened from the chat when Claude prepared something: the first screen, or a draft from the website, a
    // document or the chat. A pack suggestion the owner kept on the page doesn't count.
    var a = (S && S.answers) || {}, chat = ["website", "document", "chat"];
    function drafted(v) { return v && typeof v === "object" && v.source === "draft" && chat.indexOf(v.origin) >= 0; }
    return Object.keys(a).some(function (k) { var v = a[k]; return drafted(v) || (Array.isArray(v) && v.some(drafted)); });
  }
  function firstScreenHTML() {
    var b = answer("business_start") || {};
    return '<div class="first"><p class="kicker">Social Media Factory</p><h1>Let\'s set up your brand</h1>' +
      '<p class="lead">' + (inventory() && (inventory().sources || []).length ? "" : "You\u2019re starting from scratch: that\u2019s fine. ") +
        'Five short steps. Five answers get you started; you can skip the rest. Your answers stay on this computer.</p>' +
      '<div class="startbox">' +
        '<label class="f" for="start-what">What\'s your business?</label><input type="text" id="start-what" placeholder="For example: auto repair" value="' + esc(b.what || "") + '">' +
        '<label class="f" for="start-where">Where?</label><input type="text" id="start-where" placeholder="Your town, or “online”" value="' + esc(b.where || "") + '">' +
        '<label class="f" for="start-web">Your website, if you have one</label><input type="text" id="start-web" placeholder="example.com" value="' + esc(b.website || "") + '" spellcheck="false">' +
      "</div>" +
      (viaChat() ? "" : '<p class="small">Without the chat you\'ll get suggestions for your type of business only. If you give your website, it\'s read in the chat when you finish; clear the box if you\'d rather not.</p>') +
      '<div class="row"><button type="button" class="main big" id="start">Start</button></div>' +
      settingsHTML() + "</div>";
  }
  function settingsHTML() {
    return '<details class="settings"><summary>Settings</summary>' +
      '<label class="check"><input type="checkbox" id="sw-read"' + (prefs.read ? " checked" : "") + "> Read the questions aloud</label>" +
      '<p class="small">Off is best in a shared space. To answer by talking, use the <b>Talk</b> button on any question.</p></details>';
  }
  function wireSettings() {
    var r = $("sw-read");
    if (r) { r.onchange = function () { prefs.read = r.checked; savePrefs(); if (!r.checked && window.speechSynthesis) { window.speechSynthesis.cancel(); } }; }
  }
  function wireFirstScreen(onStart) {
    wireSettings();
    $("start").onclick = function () {
      var what = val("start-what").trim(), where = val("start-where").trim(), web = val("start-web").trim(), old = answer("business_start") || {};
      var go = function () { prefs.voice = voiceAvailable; onStart(); };
      if (!what && !where && !web && !old.what) { return go(); }
      var bs = { status: "confirmed", source: old.source === "draft" && old.what === what && old.where === where && old.website === web ? "draft" : (old.source ? "draft-edited" : "typed"),
                 origin: old.origin || "person" };
      if (what) { bs.what = what; } if (where) { bs.where = where; } if (web) { bs.website = web; }
      $("start").disabled = true; $("start").textContent = "Starting…";
      api("answer", { key: "business_start", answer: bs }).then(function (s) {
        S = s;
        var sp = answer("starter_pack");
        if (sp && sp.id && (sp.status === "confirmed" || sp.id === "custom")) { return; }      // the owner's or Claude's choice stands
        var m = matchPack(what);
        return m ? choosePack(m.id, "matched") : null;
      }).then(go).catch(function (e) { $("start").disabled = false; $("start").textContent = "Start"; alert(e.message); });
    };
  }

  // ------------------------------------------------------------------ start
  function start(ui) {
    UI = ui; loadLocal(); loadPrefs(); loadTyped();
    window.addEventListener("pagehide", function () { stopRecording(true); var f = UI.current && UI.current(); if (f && f._dirty) { keep(f); } });
    Promise.all([api("fields"), api("session"), api("voice").catch(function () { return {}; }), api("packs").catch(function () { return { packs: [] }; })]).then(function (r) {
      // The same key state as "check my setup": missing, unverified, verified or not_working.
      voiceState = (r[2] && r[2].state) || "missing"; voiceCost = (r[2] && r[2].cost) || "";
      F = r[0]; S = r[1]; P = r[3]; voiceAvailable = !!(r[2] && r[2].available); prefs.voice = voiceAvailable;
      F.extra = F.extra || [];
      typingRev = clone((S && S.typing_rev) || {});      // numbering carries on from the server's, so nothing new looks old
      // The server's accepted copy is the one: anything only the browser still had (say, typing the server
      // refused or removed) is dropped, and the browser copy is rewritten to match.
      var kept = (S && S.typing) || {};
      unsaved = {}; checkedTyping = {};
      Object.keys(kept).forEach(function (k) { if (kept[k] && typeof kept[k] === "object") { unsaved[k] = kept[k]; unsaved[k].dirty = true; checkedTyping[k] = clone(kept[k]); } });
      saveLocalTyped();
      consented = !!(S && S.consented);
      UI.mount();
    }).catch(function (e) {
      document.body.innerHTML = '<main class="wrap"><h1>The onboarding page could not load</h1><p>' + esc(e.message) + "</p><p>Go back to the chat; your confirmed answers are safe.</p></main>";
    });
  }

  window.V2 = {
    start: start, fields: function () { return F; }, session: function () { return S; },
    stateOf: stateOf, chip: chip, LABEL: LABEL, fieldHTML: fieldHTML, wire: wire, save: save, act: act,
    confirmed: confirmedCount, skippedCount: skippedCount, open: open, finish: finish, handoffText: handoffText,
    parkStrategy: parkStrategy, firstScreenHTML: firstScreenHTML, wireFirstScreen: wireFirstScreen,
    settingsHTML: settingsHTML, wireSettings: wireSettings, chipKey: chipKey, coreOrder: coreOrder,
    flowOrder: flowOrder, inventory: inventory, isQuote: isQuote, hasCandidate: hasCandidate, reopened: function () { return !!(S && S.reopened); }, foundHTML: foundHTML, wireFound: wireFound, coverageTag: coverageTag,
    pack: pack, packLineHTML: packLineHTML, packPickerHTML: packPickerHTML, wirePackPicker: wirePackPicker, matchPack: matchPack,
    closingHTML: closingHTML, wireClosing: wireClosing, setRoute: setRoute, stepIn: stepIn,
    steps: steps, oneMore: oneMore, stepOf: stepOf, inFive: inFive, betterFields: betterFields, fiveRoute: fiveRoute,
    stepDone: stepDone, stepState: stepState, questionState: questionState, isNeeded: isNeeded, neededLeft: neededLeft, neededLeftHTML: neededLeftHTML, startAt: startAt, stepsDone: stepsDone, stepLabel: stepLabel,
    stopRecording: stopRecording, esc: esc, voiceOn: function () { return prefs.voice; }, fieldById: fieldById,
    keep: keep, bringBack: bringBack, typed: typed, idle: function () { return queue; },
    parked: function () { var p = answer("positioning"); return !!(p && p.parked); }
  };
})();
