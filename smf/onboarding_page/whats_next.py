"""whats_next.py - after onboarding: "What's next" on the brand summary, and the "See everything it can do" menu
(spec rev 12, N7). Both are local pages that load nothing from anywhere; links open only when clicked.

The menu comes from smf/content_catalogue.json (the Full Content Reference, 54 options), grouped by the kind
of thing you want to make and filtered by platform, the brand's own platforms first. Each
card copies a concrete chat line with the brand filled in; nothing starts until it's said in the chat. Readiness
is a snapshot "as checked at" the time the page was written, from the same rules as `factory.py status`; the chat
re-checks before any work starts.
"""
from __future__ import annotations

import html
import json
import os
import time

from smf import bootstrap, status
from smf.brands import replace_patiently

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOGUE = os.path.join(os.path.dirname(HERE), "content_catalogue.json")
PACKS = os.path.join(HERE, "starter_packs.json")
MENU_NAME = "what-can-i-create.html"
# The content guide's look uses IBM Plex Sans (SIL Open Font License, fonts/OFL.txt). It's embedded in the page, so the page
# still loads nothing from anywhere.
FONT = os.path.join(HERE, "fonts", "IBMPlexSans-Variable.ttf")


def font_face():
    import base64
    try:
        with open(FONT, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return ""                                   # the system font stands in
    return ("@font-face{font-family:Plex;src:url(data:font/ttf;base64,%s) format('truetype');"
            "font-weight:100 700;font-display:swap}" % data)

# The five starting points, short video first (Oct 17 scope), each with the features it needs.
STARTS = [
    ("A video I will record", ["write-scripts"],
     "For {brand}, help me prepare a short video I will record myself. Ask me for my own explanation and any "
     "evidence, then write a script I approve before I film it."),
    ("Short clips from a recording", ["make-clips"],
     "For {brand}, find short clips in a recording I'll give you. Show me the real opening lines and let me choose "
     "the moments before you cut anything. Tell me any cost before it runs."),
    ("A social post", ["write-posts"],
     "For {brand}, help me write one social post from something I already know. Ask me one question at a time, "
     "and show me the draft to approve."),
    ("An image or carousel", ["make-visuals"],
     "For {brand}, help me make one image or carousel that explains one idea. Show me the words first, and the "
     "picture only after I approve them."),
    ("A film from several clips", ["narrated-film"],
     "For {brand}, help me plan a short film from clips I already have. Agree the story and shot list with me "
     "before cutting, and tell me any cost before anything paid runs."),
]
FIRST_REQUEST = ("Help me get started with {brand}. Check whether the Social Media Factory and my brand are ready. "
                 "Ask me one question at a time, then help me make one useful social post from something I already know.")
IDEA_REQUEST = ("For {brand}, a possible topic: {idea}. Ask me for my own explanation and any evidence, then help "
                "me prepare a short video. Agree the script with me before anything is made.")
WEEK_REQUEST = ("For {brand}, plan a week of content across my platforms. Show me the topics to approve before "
                "anything is written.")
# A brand's platform names (brands.PLATFORMS) as the menu groups them: TikTok sits with YouTube Shorts.
BRAND_PLATFORM = {"tiktok": "shorts"}
STATE_WORDS = {"ready": "Ready", "unverified": "Key not checked yet", "needs input": "Needs a key or an answer",
               "blocked": "Key not working", "needs setup": "Setup not finished", "not built yet": "Not available yet"}


def catalogue():
    with open(CATALOGUE, "r", encoding="utf-8") as f:
        return json.load(f)


def readiness():
    """{feature id: (state, reason)}, as `factory.py status` would say now, for a brand that's been onboarded."""
    state = bootstrap.load_state()
    out = {}
    for f in status.load_features()["features"]:
        try:
            s, why, _ = status.evaluate(f, state, True)
        except Exception as e:                      # one broken check never stops the page being written
            s, why = "needs setup", str(e)
        out[f["id"]] = (s, why)
    return out


def paid_services(ids):
    """The paid services the features `ids` need (their keys), with each one's cost line from services.json."""
    from smf import services
    feats = {f["id"]: f for f in status.load_features()["features"]}
    keys = set()
    for i in ids:
        needs = (feats.get(i) or {}).get("needs") or {}
        keys |= set(needs.get("keys") or []) | set(needs.get("any_key") or [])
    out = []
    for s in services.load()["services"]:
        if s.get("keys") and keys & set(s["keys"]):
            out.append((s.get("name") or s["id"], services.cost_line(s)))
    return out


def _costs(ids):
    got = paid_services(ids)
    return "".join('<p class="small cost"><b>Uses %s:</b> %s</p>' % (_e(n), _e(c)) for n, c in got)


def worst(ids, ready):
    """The least ready of the features an option relies on."""
    order = ["not built yet", "blocked", "needs setup", "needs input", "unverified", "ready"]
    states = [ready.get(i, ("not built yet", ""))[0] for i in ids] or ["not built yet"]
    return min(states, key=lambda s: order.index(s) if s in order else 0)


def video_ideas(brand):
    """The pack's three video ideas, or (with no pack) up to three of the brand's own confirmed topic ideas."""
    pack = ((brand.data.get("business") or {}).get("starter_pack") or {}).get("id")
    if pack:
        try:
            with open(PACKS, "r", encoding="utf-8") as f:
                for p in json.load(f)["packs"]:
                    if p["id"] == pack:
                        return list(p.get("video_ideas") or [])[:3]
        except (OSError, ValueError, KeyError):
            pass
    ideas = [i.get("text") for i in brand.data.get("topic_ideas") or [] if isinstance(i, dict) and i.get("text")]
    return ideas[:3]


def _e(s):
    return html.escape(str(s or ""), quote=True)


def _chip(state):
    return '<span class="ready r-%s">%s</span>' % (state.replace(" ", "-"), _e(STATE_WORDS.get(state, state)))


def _copy(line):
    return ('<div class="ask"><p class="line">%s</p><button type="button" class="copy">Copy this into the chat</button>'
            '</div>' % _e(line))


def cards_html(brand, ready=None, when=None):
    """The "What's next" section for brand-summary.html."""
    ready = readiness() if ready is None else ready
    when = when or time.strftime("%H:%M on %d %B").lstrip("0")
    bid = brand.id
    out = ['<section class="next"><h2>What\'s next</h2>',
           '<div class="card first"><h3>Not sure where to start?</h3>%s</div>' % _copy(FIRST_REQUEST.format(brand=bid)),
           '<h3 class="sub">Five starting points</h3><div class="cards">']
    for title, needs, line in STARTS:
        out.append('<div class="card"><div class="top"><b>%s</b>%s</div>%s%s</div>'
                   % (_e(title), _chip(worst(needs, ready)), _costs(needs), _copy(line.format(brand=bid))))
    out.append("</div>")
    ideas = video_ideas(brand)
    if ideas:
        out.append('<h3 class="sub">Video ideas to start from</h3><p class="small">Possible topics, not facts: the '
                   'request asks for your own explanation and evidence.</p><div class="cards">')
        for idea in ideas:
            out.append('<div class="card"><div class="top"><b>%s</b>%s</div>%s</div>'
                       % (_e(idea), _chip(worst(["write-scripts"], ready)), _copy(IDEA_REQUEST.format(brand=bid, idea=idea))))
        out.append("</div>")
    out.append('<p class="small">Ready or not as checked at %s. Claude checks again before any work starts, and '
               'names any cost before anything paid runs.</p>' % _e(when))
    out.append('<p><a class="menu" href="%s">See everything it can do</a></p>' % MENU_NAME)
    out.append('<div class="card more"><h3>Add more, whenever you like</h3><p>Start with whatever you have, and add '
               'more whenever you like: a book, documents, posts, photos. Put them in your brand\'s '
               '<b>Inputs/Material</b> folder, then copy this into the chat:</p>%s</div></section>'
               % _copy("Add more to my brand %s: I've put new material in its folder." % bid))
    return "\n".join(out)


def own_platforms(brand):
    """The menu's platform ids this brand posts on or wants to (intended_platforms), in the order it gave them."""
    by_speaker = ((brand.data.get("intended_platforms") or {}).get("by_speaker") or {}) if brand is not None else {}
    out = []
    for platforms in by_speaker.values():
        for p in platforms if isinstance(platforms, list) else []:
            p = BRAND_PLATFORM.get(p, p)
            if p not in out:
                out.append(p)
    return out


def menu_html(brand=None, ready=None, when=None):
    """The "See everything it can do" page: every option, searchable, grouped by the kind of thing you want to make
    and filtered by platform (the brand's own platforms first), with what you give and get."""
    ready = readiness() if ready is None else ready
    when = when or time.strftime("%H:%M on %d %B").lstrip("0")
    cat = catalogue()
    name = brand.id if brand is not None else "[brand]"
    by_id = {i["id"]: i for i in cat["items"]}
    names = dict(cat["platforms"])
    mine = [p for p in own_platforms(brand) if p in names]
    plats = ['<button type="button" class="plat" data-plat="%s" aria-pressed="false">%s%s</button>'
             % (p, _e(names[p]), " · yours" if p in mine else "")
             for p in mine + [p for p, _ in cat["platforms"] if p not in mine]]
    kinds, body = [], []
    for title, ids, hint in cat["kinds"]:
        sid = "kd-%d" % len(kinds)
        kinds.append('<button type="button" class="kind" data-kind="%s" aria-pressed="false">%s</button>' % (sid, _e(title)))
        cards = []
        for i in ids:
            it = by_id.get(i)
            if not it:
                continue
            st = "not built yet" if it.get("limit") else worst(it["implements"], ready)
            text = " ".join(str(it.get(k, "")) for k in ("label", "when", "input", "output", "name")).lower()
            text += " " + " ".join(names[p] for p in it.get("platforms", [])).lower()
            where = ('<p class="small"><span class="k">For</span> %s</p>' % _e(", ".join(names[p] for p in it["platforms"]))
                     if it.get("platforms") else "")
            cards.append(
                '<article class="card" data-text="%s" data-plats="%s"><div class="top"><b>%s</b>%s</div>%s'
                '<p><span class="k">You give</span> %s</p><p><span class="k">You get</span> %s</p>%s%s'
                '<details><summary>Details and the request</summary><p>%s</p><p class="small">%s · %s</p>'
                '<p class="small"><b>Useful to know:</b> %s</p>%s</details></article>'
                % (_e(text), _e(" ".join(it.get("platforms", []))), _e(it["label"]), _chip(st), where,
                   _e(it["input"]), _e(it["output"]),
                   ('<p class="limit">%s</p>' % _e(it["limit"])) if it.get("limit") else "", _costs(it["implements"]),
                   _e(it["work"]), _e(it["format"]), _e(it["kind"]), _e(it["note"]),
                   _copy(it["prompt"].replace("[brand]", name))))
        body.append('<section class="kind-block" id="%s"><h2>%s</h2><p class="small">%s</p><div class="cards">%s</div></section>'
                    % (sid, _e(title), _e(hint), "".join(cards)))
    flow = "".join("<li>%s</li>" % _e(s) for s in cat["flow"])
    page = MENU_PAGE % {
        "title": "What can I create",
        "head": '<header><p class="kicker">Social Media Factory%s</p><h1>What can I create?</h1>'
                '<p class="lead">Pick a platform, or pick a kind of post. Each card says what you give and what you get; '
                'copy its request into the chat to start. Nothing starts until you say it there.</p>'
                '<div class="card first"><h3>Not sure?</h3><p>Ask for a week of content and the Social Media Factory '
                'plans it across your platforms.</p>%s</div>'
                '<p class="small">%d things you can make. Ready or not as checked at %s.</p></header>'
                % ((" · " + _e(name)) if brand is not None else "", _copy(WEEK_REQUEST.format(brand=name)),
                   len(cat["items"]), _e(when)),
        "tools": '<div class="tools"><label for="q" class="vh">Search</label><input id="q" type="search" '
                 'placeholder="Search: carousel, clips, LinkedIn…">'
                 '<div class="row"><span class="k">Platform</span>%s</div>'
                 '<div class="row"><span class="k">Kind</span>%s</div></div>' % ("".join(plats), "".join(kinds)),
        "flow": '<section><h2>How it works</h2><ol class="flow">%s</ol></section>' % flow,
        "body": "\n".join(body), "style": STYLE, "script": SCRIPT, "font": font_face()}
    return page


def write_menu(brand):
    path = brand.path(MENU_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(menu_html(brand))
    replace_patiently(tmp, path)
    return path


STYLE = """
body{margin:0;background:#fff;color:#202020;font-family:Plex,Arial,sans-serif;line-height:1.5}
main{max-width:980px;margin:0 auto;padding:32px 16px 48px}
h1{margin:0;font-size:32px;text-wrap:balance}h2{font-size:19px;margin:0 0 4px}h3{font-size:16px;margin:0 0 6px}
.kicker{font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:600;color:#52525B;margin:0}
.lead{font-size:17px;color:#3F3F46;max-width:680px}.small{font-size:13px;color:#52525B;margin:4px 0}
section{border-top:1px solid #E4E4E7;padding:18px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:10px}
.card{border:1px solid #E4E4E7;border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0}
.card p{margin:0}.card .top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.k{font-size:12px;font-weight:700;color:#52525B;text-transform:uppercase;letter-spacing:.04em;margin-right:4px}
.ready{font-size:12px;font-weight:600;border-radius:999px;padding:2px 8px;white-space:nowrap;background:#F4F4F5;color:#52525B}
.r-ready{background:#EFF6FF;color:#1D4ED8}.r-blocked,.r-needs-setup,.r-needs-input{background:#FFF7ED;color:#C2410C}
.limit{color:#C2410C;font-size:14px}
.ask{background:#F4F4F5;border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px}
.line{font-size:14px;margin:0}
button{font:inherit;cursor:pointer;border-radius:10px;min-height:44px;padding:0 14px;border:1px solid #D4D4D8;background:#fff;color:#111}
button.copy{align-self:flex-start;font-size:14px}
details summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-weight:600;font-size:14px}
.tools{position:sticky;top:0;background:#fff;padding:10px 0;display:flex;flex-direction:column;gap:8px;z-index:2}
input[type=search]{font:inherit;border:1px solid #A1A1AA;border-radius:10px;padding:10px 12px;width:100%;box-sizing:border-box}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.row .k{min-width:72px}
.plat,.kind{font-size:14px;min-height:40px}.plat[aria-pressed=true],.kind[aria-pressed=true]{background:#111;color:#fff;border-color:#111}
.card.first{margin-top:14px;background:#FAFAFA;max-width:680px}
.flow{display:flex;flex-wrap:wrap;gap:6px;padding:0;margin:8px 0 0;list-style:none;counter-reset:s}
.flow li{counter-increment:s;border:1px solid #E4E4E7;border-radius:10px;padding:6px 10px;font-size:14px}
.flow li::before{content:counter(s) ". ";font-weight:700}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
a.menu{font-weight:600;color:#1D4ED8}
button:focus-visible,input:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid #1D4ED8;outline-offset:2px}
[hidden]{display:none!important}
@media print{.tools,button.copy{display:none}}
"""
CARD_STYLE = """
.next h3.sub{margin:14px 0 0}.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-top:10px}
.card{border:1px solid #E4E4E7;border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0}
.card.first,.card.more{margin-top:10px;background:#FAFAFA}.card p{margin:0}.card .top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.ready{font-size:12px;font-weight:600;border-radius:999px;padding:2px 8px;white-space:nowrap;background:#F4F4F5;color:#52525B}
.r-ready{background:#EFF6FF;color:#1D4ED8}.r-blocked,.r-needs-setup,.r-needs-input{background:#FFF7ED;color:#C2410C}
.ask{background:#F4F4F5;border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px}.line{font-size:14px;margin:0}
button.copy{font:inherit;font-size:14px;cursor:pointer;border-radius:10px;min-height:44px;padding:0 14px;border:1px solid #D4D4D8;background:#fff;color:#111;align-self:flex-start}
a.menu{font-weight:600;color:#1D4ED8}
@media print{button.copy{display:none}}
"""
SCRIPT = """
(function(){
  function copy(b){var t=b.parentNode.querySelector('.line').textContent;
    var ok=function(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy this into the chat';},1500);};
    var sel=function(){var r=document.createRange();r.selectNodeContents(b.parentNode.querySelector('.line'));var s=window.getSelection();s.removeAllRanges();s.addRange(r);b.textContent='Selected: press Ctrl+C';};
    try{navigator.clipboard.writeText(t).then(ok,sel);}catch(e){sel();}}
  document.querySelectorAll('button.copy').forEach(function(b){b.onclick=function(){copy(b);};});
  var q=document.getElementById('q'),on=null,plat=null;
  function apply(){var w=(q?q.value:'').toLowerCase().trim();
    document.querySelectorAll('.kind-block').forEach(function(s){var any=false;
      s.querySelectorAll('.card').forEach(function(c){var ps=c.getAttribute('data-plats');
        var hit=(!w||c.getAttribute('data-text').indexOf(w)>=0)&&(!plat||!ps||(' '+ps+' ').indexOf(' '+plat+' ')>=0);
        c.hidden=!hit;any=any||hit;});
      s.hidden=!any||(on&&s.id!==on);});}
  if(q){q.oninput=apply;}
  function toggle(cls,attr,set){document.querySelectorAll(cls).forEach(function(b){b.onclick=function(){
    var v=set(b.getAttribute(attr));
    document.querySelectorAll(cls).forEach(function(x){x.setAttribute('aria-pressed',String(x.getAttribute(attr)===v));});apply();};});}
  toggle('.kind','data-kind',function(v){on=(on===v)?null:v;return on;});
  toggle('.plat','data-plat',function(v){plat=(plat===v)?null:v;return plat;});
})();
"""
MENU_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:">
<title>%(title)s</title><style>%(font)s%(style)s</style></head><body><main>
%(head)s
%(tools)s
%(flow)s
%(body)s
</main><script>%(script)s</script></body></html>
"""
