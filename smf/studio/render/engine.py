"""engine.py - turn a finished page into a PNG, the same way every time.

One browser is started for a whole batch of slides (starting one per slide is what makes a
ten-slide carousel slow), every picture comes out at an exact size, and the page is drawn from
files on this computer only.

    with Renderer() as r:
        info = r.render(page_html, out_path, size=(1080, 1350), label="Slide 1 of 6")

THREE PROMISES
  1. Exact size. The window is the size of the picture at a scale of one, and the screenshot
     is clipped to it. 1080x1350 by default; 1080x1080 and 1080x1920 are the other two.
  2. No internet. The browser runs offline, and every request that is not a file on this
     computer (or data built into the page) is refused AND recorded. A page that asked for
     anything else fails the render with a plain message, rather than quietly producing a
     picture that would look different on a computer with no connection.
  3. Text fits. Any element marked data-fit lives in a box marked data-fitbox. After the fonts
     have loaded, the page is measured: while text sticks out of its box, every marked element
     in that box is scaled down together (so the hierarchy survives) until it fits or reaches
     its floor (data-min). Still too long at the floor is an error that names the slide, the
     field and the line, because a clipped headline is worse than no picture.

A FREE PAGE IS LOCKED
The fixed formats build every address in a page themselves. A free design (free.py) is written
by whoever designs the picture, so it is drawn with `locked=`: scripts in the page do not run,
and the page may open its own file and the font files it was given and NOTHING else on this
computer. Anything else it asks for is refused, recorded in `blocked`, and fails the render. It
must then pass the checks in checks.py, measured on the page as drawn, and the words read from
the page come back in "texts".

Pages are written to a file and opened by address rather than injected as a string: a page
with no address of its own is not allowed to load font files from disk. Addresses are built
with pathlib's as_uri(), so folders with spaces, apostrophes and accents work.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from smf.studio.render import checks
from smf.brands import replace_patiently

SIZES = {"portrait": (1080, 1350), "square": (1080, 1080), "story": (1080, 1920)}
SIZE_ALIASES = {"4:5": "portrait", "1:1": "square", "9:16": "story", "tall": "portrait", "reel": "story"}
LOCAL_SCHEMES = ("file:", "data:", "about:", "blob:")


class RenderError(Exception):
    """A picture could not be made. The message is written for the person, not the programmer."""


def size_for(name):
    """(width, height) for a size name. Unknown names are an error, never a guess."""
    key = SIZE_ALIASES.get(str(name or "portrait").lower(), str(name or "portrait").lower())
    if key not in SIZES:
        raise RenderError("'%s' is not a picture size. Choose portrait (1080x1350), square (1080x1080) "
                          "or story (1080x1920)." % name)
    return SIZES[key]


def renderer_available():
    """(True, "") when pictures can be drawn on this computer, else (False, the reason in words)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False, "the page renderer is not installed yet (python factory.py setup installs it)"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
    except Exception as e:
        first = (str(e).strip().splitlines() or ["it would not start"])[0]
        return False, "the page renderer would not start: %s (python factory.py setup repairs it)" % first[:160]
    return True, ""


# Measures the page and shrinks marked text until it fits. Runs inside the page.
FIT_SCRIPT = r"""
() => {
  const report = {shrunk: [], problems: []};
  const size = el => parseFloat(getComputedStyle(el).fontSize);
  const inkBox = el => { const r = document.createRange(); r.selectNodeContents(el); return r.getBoundingClientRect(); };
  const started = new Map();
  for (const el of document.querySelectorAll('[data-fit]')) started.set(el, size(el));

  for (const box of document.querySelectorAll('[data-fitbox]')) {
    // `own` texts are measured against THIS box. `inside` also counts texts in boxes nested in
    // it: when the outer box is too full, everything inside it gives way together.
    const inside = [...box.querySelectorAll('[data-fit]')];
    const own = inside.filter(el => el.closest('[data-fitbox]') === box);
    if (!inside.length) continue;
    const limits = () => {
      const b = box.getBoundingClientRect(), cs = getComputedStyle(box);
      return {left: b.left + parseFloat(cs.paddingLeft), right: b.right - parseFloat(cs.paddingRight),
              top: b.top + parseFloat(cs.paddingTop), bottom: b.bottom - parseFloat(cs.paddingBottom)};
    };
    const sticking = () => {
      const lim = limits(), out = [];
      for (const el of own) {
        // Sideways, measure the letters themselves: one long word pokes out of its own element.
        // Up and down, measure the element: with tight line spacing the letters' own boxes are
        // taller than the lines they sit on, and that overhang is not an overflow.
        const ink = inkBox(el), block = el.getBoundingClientRect();
        if (!ink.width && !ink.height) continue;
        if (ink.right > lim.right + 1.5 || ink.left < lim.left - 1.5) out.push({el, kind: 'wide'});
        else if (block.bottom > lim.bottom + 1.5 || block.top < lim.top - 1.5) out.push({el, kind: 'tall'});
      }
      if (!out.length && (box.scrollHeight > box.clientHeight + 1.5 || box.scrollWidth > box.clientWidth + 1.5)) {
        const tallest = inside.slice().sort((a, b) => inkBox(b).height - inkBox(a).height)[0];
        out.push({el: tallest, kind: box.scrollHeight > box.clientHeight + 1.5 ? 'tall' : 'wide'});
      }
      return out;
    };
    // A "lead" text (a poster headline, a giant number) starts oversized on purpose and comes
    // down alone to its designed size (data-soft) before anything else is touched. That is how
    // a short headline ends up filling the card instead of floating in it.
    const step = (els, floorOf) => {
      let moved = false;
      for (const el of els) {
        const floor = floorOf(el), now = size(el), next = Math.max(floor, Math.floor(now * 0.96));
        if (next < now) { el.style.fontSize = next + 'px'; moved = true; }
      }
      return moved;
    };
    let bad = sticking(), rounds = 0;
    while (bad.length && rounds++ < 120) {
      const leads = inside.filter(el => el.dataset.soft && size(el) > parseFloat(el.dataset.soft));
      const moved = leads.length ? step(leads, el => parseFloat(el.dataset.soft))
                                 : step(inside, el => parseFloat(el.dataset.min || '0'));
      if (!moved) break;
      bad = sticking();
    }
    const lim = limits();
    for (const item of bad) {
      const r = inkBox(item.el);
      report.problems.push({field: item.el.dataset.fit, kind: item.kind, text: item.el.innerText || '',
        need: item.kind === 'wide' ? r.width : r.height,
        have: item.kind === 'wide' ? (lim.right - lim.left) : (lim.bottom - lim.top)});
    }
  }
  // Texts in the same group finish at the size of the smallest one. Making text smaller can
  // never push it out of a box it already fits, so nothing needs measuring again.
  const groups = {};
  for (const el of document.querySelectorAll('[data-fitgroup]')) {
    (groups[el.dataset.fitgroup] = groups[el.dataset.fitgroup] || []).push(el);
  }
  for (const members of Object.values(groups)) {
    const smallest = Math.min(...members.map(size));
    members.forEach(el => { el.style.fontSize = smallest + 'px'; });
  }
  for (const [el, was] of started) {
    const designed = el.dataset.soft ? Math.min(was, parseFloat(el.dataset.soft)) : was;
    if (size(el) < designed - 0.5) report.shrunk.push({field: el.dataset.fit, from: Math.round(designed), to: Math.round(size(el))});
  }
  return report;
}
"""

FONT_SCRIPT = """
() => document.fonts.ready.then(() => [...document.fonts].map(f => ({family: f.family.replace(/["']/g, ''), status: f.status})))
"""


def _too_long_message(label, problem):
    text = " ".join((problem.get("text") or "").split())
    lines = [ln.strip() for ln in (problem.get("text") or "").splitlines() if ln.strip()] or [text]
    if problem.get("kind") == "wide":
        culprit = max((w for ln in lines for w in ln.split()), key=len, default=text)
        advice = "Use a shorter word, or put a space or a line break in it."
    else:
        culprit = max(lines, key=len)
        advice = "Shorten it, or split the idea over two slides."
    hint = ""
    need, have = float(problem.get("need") or 0), float(problem.get("have") or 0)
    if need > have > 0 and problem.get("kind") != "wide":
        room = max(8, int(len(text) * (have / need) * 0.9))
        hint = " About %d characters fit there." % room
    if len(culprit) > 90:
        culprit = culprit[:87].rstrip() + "..."
    return ('%s, %s: this line is too long to fit, even at the smallest readable size: "%s". %s%s'
            % (label, problem.get("field") or "text", culprit, advice, hint))


class Renderer(object):
    """A browser kept open for one batch of pictures. Use it as a context manager."""

    def __init__(self, keep_pages=False):
        self.keep_pages = keep_pages
        self.refused = []            # every address the pages asked for that was not a local file
        self.blocked = []            # every local file a LOCKED page asked for and was not allowed
        self._pw = self._browser = self._context = self._locked_context = None
        self._allow = set()

    # ------------------------------------------------------------------ start and stop
    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            raise RenderError("The page renderer is not installed yet. Next step: python factory.py setup")
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
            self._context = self._browser.new_context(offline=True, service_workers="block",
                                                      device_scale_factor=1, java_script_enabled=True)
            self._context.route("**/*", self._guard)
        except Exception as e:
            self.__exit__(None, None, None)
            first = (str(e).strip().splitlines() or ["it would not start"])[0]
            raise RenderError("The page renderer would not start (%s). Next step: python factory.py setup"
                              % first[:160])
        return self

    def __exit__(self, *_exc):
        for closer in (getattr(self._locked_context, "close", None),
                       getattr(self._context, "close", None), getattr(self._browser, "close", None),
                       getattr(self._pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        self._pw = self._browser = self._context = self._locked_context = None
        return False

    def _guard(self, route):
        url = route.request.url
        if url.lower().startswith(LOCAL_SCHEMES):
            route.continue_()
        else:
            self.refused.append(url)
            route.abort()

    # ------------------------------------------------------------------ a locked page
    def _locked(self):
        """The context free pages are drawn in: page scripts off, and its own guard."""
        if self._locked_context is None:
            self._locked_context = self._browser.new_context(offline=True, service_workers="block",
                                                             device_scale_factor=1, java_script_enabled=False)
            self._locked_context.route("**/*", self._locked_guard)
        return self._locked_context

    def _locked_guard(self, route):
        url = route.request.url
        low = url.lower()
        if low.startswith(("data:", "about:")):
            route.continue_()
        elif low.startswith("file:") and _real(url2pathname(unquote(urlparse(url).path))) in self._allow:
            route.continue_()
        else:
            (self.blocked if low.startswith("file:") else self.refused).append(url)
            route.abort()

    # ------------------------------------------------------------------ one picture
    def render(self, page_html, out_path, size=(1080, 1350), label="This picture", locked=None):
        """Draw one page to `out_path`. Returns {"shrunk": [...], "fonts": [...]}, and "texts" (the
        words read from the drawn page) for a locked page.
        Raises RenderError for text that cannot fit, a font that failed, or a page that tried
        to reach the internet. `locked` is for a free page: {"allow": [files it may open],
        "min_px": the smallest text allowed}; such a page must also pass checks.py."""
        if self._context is None:
            raise RenderError("The renderer is not running. Use it inside a `with Renderer() as r:` block.")
        out_path = Path(os.path.abspath(str(out_path)))        # a page's address has to be absolute
        out_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = int(size[0]), int(size[1])
        pages_dir = Path(tempfile.mkdtemp(prefix=".pages-", dir=str(out_path.parent)))
        page_file = pages_dir / (out_path.stem + ".html")
        page_file.write_text(page_html, encoding="utf-8")
        if locked is not None:
            self._allow = {_real(page_file)} | {_real(f) for f in locked.get("allow") or ()}
        page = (self._context if locked is None else self._locked()).new_page()
        refused_before, blocked_before, texts = len(self.refused), len(self.blocked), None
        try:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(page_file.as_uri(), wait_until="load")
            fonts = page.evaluate(FONT_SCRIPT)
            broken = sorted({f["family"] for f in fonts if f["status"] == "error"})
            if broken:
                raise RenderError("%s: a font file could not be read (%s). If it is one of this brand's own "
                                  "fonts, replace the file in Brand/brand-kit/fonts; otherwise run "
                                  "python factory.py setup." % (label, ", ".join(broken)))
            fit = page.evaluate(FIT_SCRIPT)
            asked = self.refused[refused_before:]
            if asked:
                raise RenderError("%s: the page tried to load something from the internet (%s). Pictures are "
                                  "drawn only from files on this computer, so nothing was saved. Remove the "
                                  "web address, or save that file into the brand's folder and point to it there."
                                  % (label, ", ".join(sorted(set(a[:80] for a in asked)))))
            if self.blocked[blocked_before:]:
                names = sorted({os.path.basename(urlparse(u).path)[:60] or u[:60] for u in self.blocked[blocked_before:]})
                raise RenderError("%s: the page tried to open a file it is not allowed to use (%s). A free design "
                                  "can use this brand's fonts and nothing else on this computer, so nothing was "
                                  "saved." % (label, ", ".join(names)))
            if fit["problems"]:
                raise RenderError(_too_long_message(label, fit["problems"][0]))
            clip = {"x": 0, "y": 0, "width": width, "height": height}
            tmp = out_path.with_name("." + out_path.name + ".part")
            page.screenshot(path=str(tmp), type="png", clip=clip, animations="disabled", caret="hide")
            if locked is not None:
                min_px = int(locked.get("min_px") or checks.min_text_px((width, height)))
                seen = page.evaluate(checks.CHECK_SCRIPT, {"w": width, "h": height, "min": min_px})
                problems = list(seen["problems"])
                if not problems and seen["spots"]:
                    page.evaluate(checks.HIDE_TEXT_SCRIPT)
                    behind = page.screenshot(type="png", clip=clip, animations="disabled", caret="hide")
                    problems = (checks.edge_problems(tmp, behind)
                                + checks.contrast_problems(seen["spots"], behind, (width, height)))
                if problems:
                    raise RenderError(checks.problem_message(label, problems, min_px))
                texts = seen["texts"]
            replace_patiently(str(tmp), str(out_path))
        finally:
            leftover = out_path.with_name("." + out_path.name + ".part")
            if leftover.exists():
                leftover.unlink()
            try:
                page.close()
            except Exception:
                pass
            if self.keep_pages:
                kept = out_path.with_suffix(".html")
                try:
                    os.replace(str(page_file), str(kept))
                except OSError:
                    pass
            shutil.rmtree(str(pages_dir), ignore_errors=True)
        info = {"shrunk": fit["shrunk"],
                "fonts": sorted({f["family"] for f in fonts if f["status"] == "loaded"})}
        if texts is not None:
            info["texts"] = texts
        return info


def _real(path):
    """One spelling for a file, whatever links or dots its address went through."""
    return os.path.normcase(os.path.realpath(str(path)))
