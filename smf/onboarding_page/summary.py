"""summary.py - the one-page brand summary (spec 14.5), saved as brand-summary.html in the brand's folder.

It opens in any browser, prints to one or two pages, and loads nothing from anywhere. It is built
from the brand's own settings, its voice samples and the brand check, in this order:

    1 name and date set up      2 what you do        3 who you reach and their questions
    4 who speaks                5 how you sound      6 colours
    7 rules (private)           8 what you chose     9 still open
   10 next steps and the accounts your choices need, with costs

Never in it: keys, passwords, account details, raw transcripts. Every value is escaped.
"""
from __future__ import annotations

import colorsys
import html
import os
import re
import time

from smf import brands, checklist, status
from smf.onboarding_page import secrets_check
from smf.brands import replace_patiently

SAMPLES_TO_SHOW = 2


def colour_name(hex_colour):
    """A plain name a person would use: 'Cream', 'Dark brown', 'Orange'."""
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    if light > 0.92:                                            # very pale: people say white or cream
        return "Cream" if r > b + 0.02 else "White"
    if sat < 0.12:
        return "Black" if light < 0.12 else "Dark grey" if light < 0.4 else "Grey" if light < 0.75 else "Light grey"
    deg = h * 360
    hue = ("Red" if deg < 15 or deg >= 345 else "Orange" if deg < 40 else "Yellow" if deg < 65 else
           "Green" if deg < 165 else "Teal" if deg < 195 else "Blue" if deg < 255 else
           "Purple" if deg < 290 else "Pink")
    if hue == "Orange" and light < 0.3:
        hue = "Brown"
    return ("Dark " + hue.lower()) if light < 0.3 else ("Light " + hue.lower()) if light > 0.8 else hue


def _samples(brand):
    """The first voice samples, with where they came from, read from Brand/voice-samples.md."""
    path = brand.path("Brand", "voice-samples.md")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return []
    out = []
    for m in re.finditer(r"^## Sample \d+ \(([^)]*)\)\n\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        body = m.group(2).strip()
        if body and not secrets_check.looks_secret(body):
            out.append((body, m.group(1)))
    return out[:SAMPLES_TO_SHOW]


def build(brand, placeholders=(), when=None, ready=None):
    """Write brand-summary.html for `brand` (a Brand or an id). Returns its path."""
    brand = brand if isinstance(brand, brands.Brand) else brands.load(brand)
    d = brand.data
    e = lambda s: html.escape(str(s or ""), quote=True)        # noqa: E731
    todo = lambda s: not s or "TODO" in str(s)                  # noqa: E731
    open_note = '<span class="open">Still open</span>'
    when = when or time.strftime("%d %B %Y").lstrip("0")

    biz, aud, voice, comp = d.get("business", {}), d.get("audience", {}), d.get("voice", {}), d.get("compliance", {})
    colours = d.get("visual", {}).get("colors", {})
    parts = []

    parts.append('<header><p class="kicker">Brand summary</p><h1>%s</h1><p class="small">Set up %s</p></header>'
                 % (e(d.get("name")), e(when)))
    parts.append("<section><h2>What you do</h2><p>%s</p></section>"
                 % (open_note if todo(biz.get("what_we_do")) else e(biz["what_we_do"])))
    qs = "".join("<li>%s</li>" % e(q) for q in aud.get("questions_they_ask", []))
    parts.append("<section><h2>Who you reach</h2><p>%s</p>%s</section>"
                 % (open_note if todo(aud.get("who")) else e(aud["who"]),
                    ("<p class='small'>The questions they ask</p><ul>%s</ul>" % qs) if qs else ""))
    who = "".join("<li><b>%s</b>%s%s</li>" % (e(i.get("display_name")), (" · " + e(i["role"])) if i.get("role") else "",
                                              (" · " + e(i["handle"])) if i.get("handle") else "")
                  for i in d.get("identities", []))
    parts.append("<section><h2>Who speaks</h2><ul>%s</ul></section>" % who)
    samples = "".join('<blockquote>%s<footer>%s</footer></blockquote>' % (e(t).replace("\n", "<br>"), e(src))
                      for t, src in _samples(brand))
    do = "".join("<li>%s</li>" % e(x) for x in voice.get("do", []))
    dont = "".join("<li>%s</li>" % e(x) for x in voice.get("dont", []))
    # Who inspires them: a name on its own or {name, why}; nothing at all when there are none.
    people = [(x, "") if isinstance(x, str) else (x.get("name"), x.get("why")) for x in d.get("influences") or []
              if isinstance(x, (str, dict))]
    inspires = "".join("<li>%s%s</li>" % (e(n), (": " + e(w)) if w else "") for n, w in people if n and str(n).strip())
    parts.append("<section><h2>How you sound</h2><p>%s</p>%s%s%s%s</section>"
                 % (open_note if todo(voice.get("register")) else e(voice["register"]),
                    ("<p class='small'>Do</p><ul>%s</ul>" % do) if do else "",
                    ("<p class='small'>Don't</p><ul>%s</ul>" % dont) if dont else "",
                    samples or "<p class='small'>No voice samples yet.</p>",
                    ("<p class='small'>Who inspires you (how they shape a piece, never their words)</p><ul>%s</ul>"
                     % inspires) if inspires else ""))
    sw = "".join('<div class="sw"><span style="background:%s"></span><b>%s</b><span class="small">%s</span></div>'
                 % (e(colours[k]), e(colour_name(colours[k])), label)
                 for k, label in (("ground", "Background"), ("ink", "Main text"), ("accent", "The colour people remember"))
                 if re.match(r"^#[0-9A-Fa-f]{6}$", colours.get(k) or ""))
    parts.append('<section><h2>Colours</h2><div class="sws">%s</div></section>' % sw)
    rules = []
    if comp.get("drop_terms"):
        rules.append("<li><b>Never claim:</b> %s</li>" % e(", ".join(comp["drop_terms"])))
    if comp.get("sign_off_by"):
        rules.append("<li><b>Sign-off by:</b> %s</li>" % e(comp["sign_off_by"]))
    if d.get("never_mention"):
        rules.append("<li><b>Never name:</b> %s</li>" % e(", ".join(d["never_mention"])))
    banned = (d.get("style") or {}).get("banned_words") or []
    if banned:
        rules.append("<li><b>Words to avoid:</b> %s</li>" % e(", ".join(banned)))
    parts.append('<section class="private"><h2>Rules <span class="open">Private: don\'t share this page</span></h2>'
                 "<ul>%s</ul></section>" % ("".join(rules) or "<li>None given.</li>"))
    pos = d.get("positioning") or {}
    stands = [v for v in (pos.get("known_for"), pos.get("core_belief")) if isinstance(v, dict) and v.get("value")
              and "TODO" not in str(v.get("value"))] + [x for k in ("contrarian", "non_negotiables", "differentiation")
                                                         for x in pos.get(k) or [] if isinstance(x, dict)]
    if stands:
        parts.append("<section><h2>What you stand for</h2><p>Saved in your brand: what you're known for, what you "
                     "believe and what every post must show.</p></section>")
    wants = d.get("wants") or []
    parts.append("<section><h2>What you chose to make</h2><ul>%s</ul></section>"
                 % ("".join("<li>%s</li>" % e(checklist.WANT_NAMES.get(w, w)) for w in wants) or "<li>Nothing chosen yet.</li>"))
    problems, warnings = brands.validate(d)
    still = list(problems) + list(warnings) + ["%s (skipped or not confirmed on the page)" % p.replace("_", " ")
                                               for p in placeholders]
    parts.append("<section><h2>Still open</h2><ul>%s</ul></section>"
                 % ("".join("<li>%s</li>" % e(s) for s in still) or "<li>Nothing. Every answer is in.</li>"))
    services = checklist.needed_services(wants, status.load_features()["features"])
    acct = "".join("<li><b>%s</b>: for %s. %s</li>" % (e(s["name"]), e(s["for"]), e(s["cost"])) for s in services)
    parts.append("<section><h2>Next steps</h2><ul><li>Ask Claude: <b>“Write my first post.”</b></li>%s</ul>"
                 "<p class='small'>Writing, visuals and review need no accounts at all.</p></section>"
                 % (("<li>Accounts your choices need:<ul>%s</ul></li>" % acct) if acct else
                    "<li>No accounts needed for what you chose.</li>"))

    # Rev 12 N7 / rev 13 M7: "What's next" cards, the menu of everything it can do, and adding more any time.
    from smf.onboarding_page import whats_next
    ready = whats_next.readiness() if ready is None else ready
    parts.append(whats_next.cards_html(brand, ready))

    body = "\n".join(parts)
    if secrets_check.looks_secret(html.unescape(re.sub(r"<[^>]+>", " ", body))):
        raise brands.BrandError("the summary would hold something that looks like a key, so it was not written. "
                                "Check the brand's files for a pasted key.")
    page = PAGE % {"title": e(d.get("name")), "body": body, "next_style": whats_next.CARD_STYLE,
                   "script": whats_next.SCRIPT}
    path = brand.path("brand-summary.html")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    replace_patiently(tmp, path)
    menu = brand.path(whats_next.MENU_NAME)
    with open(menu + ".tmp", "w", encoding="utf-8") as f:
        f.write(whats_next.menu_html(brand, ready))
    replace_patiently(menu + ".tmp", menu)
    return path


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>%(title)s: brand summary</title>
<style>
body{margin:0;background:#fff;color:#111;font-family:system-ui,-apple-system,"Segoe UI","Helvetica Neue",sans-serif;line-height:1.5}
main{max-width:760px;margin:0 auto;padding:32px 20px 48px}
h1{margin:0;font-size:34px}h2{font-size:18px;margin:0 0 8px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
section{border-top:1px solid #E4E4E7;padding:16px 0;break-inside:avoid}
.kicker{font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:600;color:#52525B;margin:0}
.small{font-size:13px;color:#52525B;margin:6px 0 2px}ul{margin:4px 0;padding-left:20px}
blockquote{margin:8px 0;padding:10px 14px;background:#F4F4F5;border-radius:10px;white-space:normal}
blockquote footer{font-size:12px;color:#52525B;margin-top:4px}
.sws{display:flex;flex-wrap:wrap;gap:14px}.sw{display:flex;flex-direction:column;gap:2px;min-width:140px}
.sw span:first-child{width:56px;height:56px;border-radius:12px;border:1px solid rgba(0,0,0,.2)}
.open{font-size:12px;font-weight:600;color:#C2410C;background:#FFF7ED;border-radius:999px;padding:2px 8px}
@media print{main{padding:0}body{font-size:11pt}}
%(next_style)s
</style></head><body><main>
%(body)s
</main><script>%(script)s</script></body></html>
"""
