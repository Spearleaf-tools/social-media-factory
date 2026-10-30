"""doctor.py - prove the installed pieces really work, by using them.

`status` says what SHOULD work. `doctor` actually does a tiny version of each job:
draws a card, reads a timezone, and (when the video tools are installed) makes a one-second
video, cuts it, and measures it. Everything happens in a throwaway folder whose name contains a
space, an apostrophe and an accent, because real people's folders do.

    python factory.py doctor            quick checks
    python factory.py doctor --deep     also downloads the small speech model and transcribes a test tone
    python factory.py doctor --json
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

from smf import bootstrap

REQUIRED_ENCODERS = ["libx264", "aac"]
REQUIRED_FILTERS = ["format", "crop", "scale", "overlay", "atempo", "aresample", "afade", "setsar", "setpts",
                    "trim", "split", "fps", "eq", "volume", "vignette", "streamselect", "silencedetect",
                    "sendcmd", "pad", "noise", "hstack", "fade", "cropdetect", "color", "asetpts", "amix",
                    "concat", "sine"]

CARD_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:1080px;height:1350px;background:#f6f4ef;font-family:Arial,Helvetica,sans-serif}
.card{position:absolute;inset:60px;border:6px solid #1a2522;display:flex;flex-direction:column;justify-content:center;padding:80px}
h1{font-size:96px;line-height:1.02;margin:0;color:#1a2522}p{font-size:40px;color:#5f6b66}
</style></head><body><div class="card"><h1>Renderer check</h1><p>Café — it's working.</p></div></body></html>"""


def _scratch():
    base = os.path.join(bootstrap.STATE_DIR, "tmp", "doctor's café test")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    return base


def check_imports(tier, modules):
    """Import each package in its OWN process. Two of the video packages each carry a copy of the
    same media library; loading both into one process makes macOS print an alarming (harmless)
    warning, and a broken native library should fail one check, not take the doctor down."""
    missing = []
    for m in modules:
        r = subprocess.run([sys.executable, "-c", "import %s" % m], capture_output=True, text=True)
        if r.returncode != 0:
            last = (r.stderr.strip().splitlines() or ["failed"])[-1]
            missing.append("%s (%s)" % (m, last[:80]))
    return (not missing), ("all import" if not missing else "cannot import: " + ", ".join(missing))


def check_timezones():
    from zoneinfo import ZoneInfo
    from datetime import datetime
    dt = datetime(2026, 7, 1, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    return dt.utcoffset() is not None, "timezone database works (%s)" % dt.tzname()


def check_renderer(scratch):
    from playwright.sync_api import sync_playwright
    page_file = os.path.join(scratch, "card.html")
    out = os.path.join(scratch, "card.png")
    with open(page_file, "w", encoding="utf-8") as f:
        f.write(CARD_HTML)
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350})
        from pathlib import Path
        page.goto(Path(page_file).as_uri())
        page.screenshot(path=out)
        browser.close()
    from PIL import Image
    with Image.open(out) as im:
        size = im.size
    ok = size == (1080, 1350) and os.path.getsize(out) > 5000
    return ok, "drew a %dx%d card in %.1fs" % (size[0], size[1], time.time() - t0)


def check_video(scratch):
    from smf import media
    ff, fp = media.ensure_ffmpeg()
    enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    fil = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    missing = [e for e in REQUIRED_ENCODERS if (" " + e + " ") not in enc]
    have_filters = set()
    for line in fil.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            have_filters.add(parts[1])
    missing += ["filter:" + f for f in REQUIRED_FILTERS if f not in have_filters]
    if missing:
        return False, "the video program is missing: " + ", ".join(missing)

    # make two one-second parts, then cut + join them the way the clip tools do
    parts = []
    for i, colour in enumerate(("navy", "darkgreen")):
        part = os.path.join(scratch, "part %d.mp4" % i)
        r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", "color=c=%s:s=1080x1920:r=30:d=1" % colour,
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                            "-vf", "crop=1080:1350:0:285,scale=720:900,eq=contrast=1.05,vignette,format=yuv420p",
                            "-af", "afade=t=in:d=0.1,aresample=48000",
                            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", part],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return False, "could not encode a test clip: " + r.stderr.strip()[-200:]
        parts.append(part)
    listing = os.path.join(scratch, "join.txt")
    with open(listing, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '%s'\n" % p.replace("'", "'\\''"))
    joined = os.path.join(scratch, "joined.mp4")
    r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", listing, "-c", "copy", joined], capture_output=True, text=True)
    if r.returncode != 0:
        return False, "could not join clips from a folder with an apostrophe in its name: " + r.stderr.strip()[-200:]
    dur = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", joined],
                         capture_output=True, text=True).stdout.strip()
    ok = dur and abs(float(dur) - 2.0) < 0.2
    return bool(ok), "encoded, joined and measured a test video (%.2fs)" % float(dur or 0)


TITLE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:320px;height:180px;overflow:hidden;background:#1a2522}
#root{width:100%;height:100%;position:relative}.scene{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
h1{font-family:Arial,Helvetica,sans-serif;font-size:28px;color:#f6f4ef;margin:0;animation:rise .5s ease-out both}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
</style></head><body><div id="root" data-composition-id="title" data-start="0" data-duration="1" data-width="320"
data-height="180" data-no-timeline><div class="scene" data-start="0" data-duration="1"><h1>Title check: café</h1></div></div></body></html>"""


def check_titles(scratch):
    """Render a one-second title with the Factory's own Node and HyperFrames, then measure it, the
    way montage titles does for a film."""
    from smf import media
    from smf.video import montage
    from smf.video.common import probe_duration
    media.node_programs()                                   # a plain sentence when they are not installed
    project = os.path.join(scratch, "title")
    os.makedirs(project)
    with open(os.path.join(project, "index.html"), "w", encoding="utf-8") as f:
        f.write(TITLE_HTML)
    out = os.path.join(project, "title.mp4")
    t0 = time.time()
    montage._hyperframes_render(project, out, 25, "draft")
    size, seconds = montage._probe_size(out), probe_duration(out)
    ok = size == (320, 180) and abs(seconds - 1.0) < 0.1
    return ok, "rendered a %dx%d title of %.2fs with HyperFrames in %.1fs" % (size[0], size[1], seconds, time.time() - t0)


def check_speech_model(scratch):
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")          # no "set a token" nagging; none is needed
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from smf import media
    from faster_whisper import WhisperModel
    ff, _ = media.ensure_ffmpeg()
    wav = os.path.join(scratch, "tone.wav")
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=300:duration=3", "-ar", "16000", "-ac", "1", wav], check=True)
    t0 = time.time()
    model = WhisperModel("base", device="cpu", compute_type="int8")
    loaded = time.time() - t0
    t1 = time.time()
    segments, _info = model.transcribe(wav, word_timestamps=True)
    list(segments)
    return True, "speech model loaded in %.0fs, ran in %.1fs" % (loaded, time.time() - t1)


USAGE = """
python factory.py doctor            quick checks: draws a test card, reads a timezone, tries the video tools and the title renderer
python factory.py doctor --deep     also downloads the small speech model and transcribes a test tone
python factory.py doctor --json     the same results as JSON
"""


def main(args):
    opts, _words, rc = bootstrap.read_options(args, "doctor", USAGE, flags=("--deep", "--json"))
    if rc is not None:
        return rc
    deep = bool(opts.get("--deep"))
    as_json = bool(opts.get("--json"))
    state = bootstrap.load_state()
    tiers = state.get("tiers", {})
    results = []

    def record(name, fn, *a):
        t0 = time.time()
        try:
            ok, detail = fn(*a)
        except Exception as e:
            ok, detail = False, "%s: %s" % (type(e).__name__, str(e)[:300])
        results.append({"check": name, "ok": bool(ok), "detail": detail, "seconds": round(time.time() - t0, 1)})

    if not bootstrap.running_inside_env():
        results.append({"check": "environment", "ok": False, "seconds": 0,
                        "detail": "the Social Media Factory's own Python is not set up yet (python factory.py setup)"})
    else:
        scratch = _scratch()
        results.append({"check": "environment", "ok": True, "seconds": 0,
                        "detail": "Python %d.%d at %s" % (sys.version_info[0], sys.version_info[1], sys.prefix)})
        try:
            if "core" in tiers:
                record("core packages", check_imports, "core",
                       ["PIL", "numpy", "flask", "requests", "markdown", "playwright", "tzdata"])
                record("timezones", check_timezones)
                record("page renderer", check_renderer, scratch)
            if "video" in tiers:
                record("video packages", check_imports, "video", ["faster_whisper", "cv2", "scipy", "static_ffmpeg"])
                record("video program", check_video, scratch)
                record("title renderer", check_titles, scratch)
                if deep:
                    record("speech model", check_speech_model, scratch)
        finally:
            # Only doctor's own folder: .factory/tmp also holds the onboarding page's live session and answers.
            shutil.rmtree(scratch, ignore_errors=True)

    if as_json:
        print(json.dumps(results, indent=2))
    else:
        print("SOCIAL MEDIA FACTORY - doctor\n")
        for r in results:
            print("  [%s] %-16s %s" % ("ok" if r["ok"] else "PROBLEM", r["check"], r["detail"]))
        bad = [r for r in results if not r["ok"]]
        print("\n%s" % ("Everything that is installed works." if not bad else
                        "%d problem(s). Show this output to Claude and ask it to fix them." % len(bad)))
    return 0 if all(r["ok"] for r in results) else 1
