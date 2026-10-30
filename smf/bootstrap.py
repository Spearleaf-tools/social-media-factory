"""bootstrap.py - get a computer from "nothing installed" to "the Social Media Factory runs".

Standard library only, old-Python-safe syntax: this module runs BEFORE the Social Media Factory has its own
Python, on whatever interpreter started factory.py.

What setup does, in order. Every step is safe to repeat; a step that is already done is skipped,
so an interrupted setup continues where it stopped.

  1. find or install `uv`      a single small program that installs Python and packages.
                               Installed INSIDE this folder (.factory/bin), no admin password,
                               no changes to the shell profile or PATH.
  2. create the environment    uv downloads its own Python 3.12 if the computer has none.
  3. install the packages      requirements/<tier>.txt
  4. install the page renderer Chromium, used to draw carousels and cards (core tier only)
  5. create keys.env           an empty keys file the user fills in later, only if needed
  video tier, step 4-5        the video programs (ffmpeg), then the title renderer: a portable
                               Node from nodejs.org and HyperFrames, both INSIDE this folder
                               (.factory/node), checked against a known checksum, no PATH change,
                               no admin password. HyperFrames keeps its own Chrome in its cache.

Nothing here needs a key, and nothing here talks to a social network.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(ROOT, ".factory")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "setup.log")
PYTHON_VERSION = "3.12"
TIERS = ("core", "video")
WINDOWS = os.name == "nt"

# A Windows path longer than ~260 characters breaks installs. The page renderer unpacks deep
# folders inside the environment, so when this folder already sits deep, the environment goes
# somewhere short instead.
WINDOWS_DEEP_PATH = 70


# ----------------------------------------------------------------------------- output
def utf8_output():
    """Make what this program prints readable whoever is reading it.

    A brand name, a post or a person's name can be in any language. When another program reads
    this one's output through a pipe on Windows, Python writes it in the computer's old Western
    code page, which holds no Chinese, no Arabic and no emoji: the work finishes, and then SAYING
    so fails. UTF-8 holds every language, so both streams are switched to it, and anything that
    still cannot be written is replaced rather than stopping the program.

    Safe to call anywhere: a stream that has been stood in for, closed or taken away is left alone."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass                                        # not a real file stream, or already gone


def child_surroundings(extra=None):
    """A copy of this program's surroundings for a Python it starts, asking that one to read and
    write UTF-8 as well. Without this the second Python looks at the console's code page again and
    the same problem comes back one level down."""
    out = dict(os.environ)
    out["PYTHONIOENCODING"] = "utf-8"
    out["PYTHONUTF8"] = "1"
    if extra:
        out.update(extra)
    return out


# ----------------------------------------------------------------------------- state
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    from smf import brands                              # standard library only, and 3.8-safe
    brands.write_text_atomic(STATE_FILE, json.dumps(state, indent=2, sort_keys=True))


def log(text):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n")
    except OSError:
        pass


def say(text=""):
    print(text)
    sys.stdout.flush()
    log(text)


# ----------------------------------------------------------------------------- reading a command's options
def read_options(args, verb, usage, flags=(), values=(), words=False):
    """Check a command's options BEFORE it does anything, so asking for help or mistyping an
    option never sets the command off. Returns (options, words, exit_code): when exit_code is
    not None, the help or a plain message has been printed and the command must return it.

    flags take no value (--force); values take the next word (--tier video, or --tier=video);
    words are plain words such as brand ids, refused unless `words` is True. Only exact option
    names count: an abbreviation like --for is refused, never guessed."""
    if "--help" in args or "-h" in args:
        print(usage.strip())
        return {}, [], 0
    import difflib
    known = list(flags) + list(values)
    opts, plain, i = {}, [], 0

    def stop(message):
        print("%s\nFor help: python factory.py %s --help" % (message, verb))
        return {}, [], 2

    while i < len(args):
        a = args[i]
        if a.startswith("-") and a != "-":
            name, _eq, given = a.partition("=")
            if name in flags and not _eq:
                opts[name] = True
            elif name in values:
                if not _eq:
                    i += 1
                    given = args[i] if i < len(args) and not args[i].startswith("-") else ""
                if not given:
                    return stop("%s needs a value after it." % name)
                opts[name] = given
            else:
                close = difflib.get_close_matches(name, known, n=1, cutoff=0.6)
                return stop("%s doesn't know %s.%s" % (verb, a, " Did you mean %s?" % close[0] if close else ""))
        elif words:
            plain.append(a)
        else:
            return stop("%s doesn't take '%s'." % (verb, a))
        i += 1
    return opts, plain, None


# ----------------------------------------------------------------------------- environment location
def venv_dir():
    state = load_state()
    if state.get("venv") and os.path.isdir(state["venv"]):
        return state["venv"]
    if WINDOWS and len(ROOT) > WINDOWS_DEEP_PATH:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        tag = hashlib.sha1(ROOT.encode("utf-8")).hexdigest()[:8]
        return os.path.join(base, "SocialMediaFactory", "env-" + tag)
    return os.path.join(ROOT, ".venv")


def _python_in(venv):
    return os.path.join(venv, "Scripts", "python.exe") if WINDOWS else os.path.join(venv, "bin", "python")


def _venv_of(py):
    return os.path.dirname(os.path.dirname(py))


ENV_ID_FILE = "factory-env-id.txt"


def env_id(venv, make=False):
    """A name for THIS environment, kept in a small file inside it.

    Setup writes notes saying which groups of packages it installed. A note is only worth
    something next to the environment it was written about: rebuilding the environment throws the
    file away, so every note that names the old one stops matching and those groups go in again."""
    path = os.path.join(venv, ENV_ID_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            found = f.read().strip()
        if found:
            return found
    except OSError:
        pass
    if not make or not os.path.isdir(venv):
        return ""
    token = "%s-%s" % (time.strftime("%Y%m%d%H%M%S"), hashlib.sha256(os.urandom(16)).hexdigest()[:8])
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(token + "\n")
    except OSError:
        return ""
    return token


def env_python():
    """Absolute path of the Social Media Factory's own Python, or None if setup has not run."""
    p = _python_in(venv_dir())
    return p if os.path.isfile(p) else None


def running_inside_env():
    try:
        return os.path.realpath(sys.prefix) == os.path.realpath(venv_dir())
    except OSError:
        return False


# ----------------------------------------------------------------------------- running things
class StepFailed(Exception):
    def __init__(self, message, hint=""):
        Exception.__init__(self, message)
        self.hint = hint


def run(cmd, env_extra=None, what=""):
    """Run a command, stream a short progress line, keep the full output in the setup log."""
    env = dict(os.environ)
    for name, value in (env_extra or {}).items():
        if value is None:
            env.pop(name, None)                         # None means "leave this one out entirely"
        else:
            env[name] = value
    log("$ " + " ".join(str(c) for c in cmd))
    started = time.time()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=ROOT)
    except OSError as e:
        raise StepFailed("could not start: %s (%s)" % (cmd[0], e))
    tail = []
    for raw in iter(p.stdout.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip()
        log("  " + line)
        tail.append(line)
        tail = tail[-25:]
    p.wait()
    log("  -> exit %s after %.0fs" % (p.returncode, time.time() - started))
    if p.returncode != 0:
        raise StepFailed("%s did not finish (exit %s)." % (what or cmd[0], p.returncode), "\n".join(tail[-12:]))
    return "\n".join(tail)


NETWORK_HINT = (
    "This step downloads files. If it keeps failing:\n"
    "  - check the internet connection, then run the same command again (it continues where it stopped)\n"
    "  - on a work computer, a company proxy or security tool may be blocking the download;\n"
    "    ask IT to allow astral.sh, github.com, pypi.org, files.pythonhosted.org, playwright.azureedge.net,\n"
    "    nodejs.org, registry.npmjs.org and storage.googleapis.com\n"
    "  - the full output is in .factory/setup.log"
)


# ----------------------------------------------------------------------------- step 1: uv
def _uv_name():
    return "uv.exe" if WINDOWS else "uv"


def find_uv():
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(STATE_DIR, "bin", _uv_name()),
        shutil.which("uv"),
        os.path.join(home, ".local", "bin", _uv_name()),
        os.path.join(home, ".cargo", "bin", _uv_name()),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def windows_powershell_module_path(module_path):
    """The module path to hand Windows PowerShell 5.1, without PowerShell 7's own folders.

    Started from PowerShell 7 (the usual shell in a code editor), PSModulePath lists 7's folders
    first. 5.1 then loads 7's copy of its security module, cannot, and stops before doing anything.
    7's folders are the ones with a folder called exactly "PowerShell" in them; 5.1's are called
    "WindowsPowerShell". None means nothing is left, so the setting is better left out altogether."""
    kept = [p for p in (module_path or "").split(";")
            if p.strip() and "powershell" not in [part.lower() for part in p.replace("/", "\\").split("\\")]]
    return ";".join(kept) or None


def install_uv():
    target = os.path.join(STATE_DIR, "bin")
    os.makedirs(target, exist_ok=True)
    # The install folder is passed through the ENVIRONMENT, never spliced into a command string,
    # so a folder name with spaces, an apostrophe or accents cannot break the command.
    extra = {"UV_UNMANAGED_INSTALL": target}
    if WINDOWS:
        extra["PSModulePath"] = windows_powershell_module_path(os.environ.get("PSModulePath"))
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
               "irm https://astral.sh/uv/install.ps1 | iex"]
    else:
        cmd = ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]
    run(cmd, env_extra=extra, what="Installing the package installer (uv)")
    uv = find_uv()
    if not uv:
        raise StepFailed("uv was downloaded but could not be found afterwards.", NETWORK_HINT)
    return uv


# ----------------------------------------------------------------------------- steps 2-4
def ensure_env(uv):
    venv = venv_dir()
    py = _python_in(venv)
    if os.path.isfile(py):
        try:
            out = subprocess.check_output([py, "-c", "import sys;print('%d.%d'%sys.version_info[:2])"])
            if out.decode().strip() == PYTHON_VERSION:
                env_id(venv, make=True)                   # an environment from an older setup gets a name now
                return py, False
        except (OSError, subprocess.CalledProcessError):
            pass
        say("   The existing environment is broken or the wrong version; rebuilding it.")
    os.makedirs(os.path.dirname(venv), exist_ok=True)
    cmd = [uv, "venv", "--python", PYTHON_VERSION, "--python-preference", "managed", venv]
    if os.path.isdir(venv):
        cmd.insert(2, "--clear")
    run(cmd, what="Creating the Social Media Factory's own Python %s" % PYTHON_VERSION)
    if not os.path.isfile(py):
        raise StepFailed("the environment was created but its Python is missing.", NETWORK_HINT)
    state = load_state()
    # Every note about what was installed described the environment that has just been replaced.
    # Keeping one would skip installing that group into an environment that does not have it, and
    # setup would finish saying all is well while ordinary commands fail on missing packages.
    had = bool(state.get("tiers")) or bool(state.get("renderer")) or bool(state.get("video_programs"))
    for note in ("tiers", "renderer", "video_programs"):
        state.pop(note, None)
    state["venv"] = venv
    save_state(state)
    env_id(venv, make=True)
    if had:
        say("   The Social Media Factory's Python had to be rebuilt, so its packages are being installed again.")
    return py, True


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# One package out of each group, used to prove the group really is in the environment. Checking
# costs one quick import; believing a note that turned out to be wrong costs the person their setup.
TIER_PROOF = {"core": "flask", "video": "faster_whisper"}


def _really_installed(py, tier):
    module = TIER_PROOF.get(tier)
    if not module:
        return True
    try:
        return subprocess.call([py, "-c", "import " + module],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except OSError:
        return False


def ensure_tier(uv, py, tier, force=False):
    req = os.path.join(ROOT, "requirements", tier + ".txt")
    if not os.path.isfile(req):
        raise StepFailed("requirements/%s.txt is missing from this folder." % tier)
    state = load_state()
    done = state.get("tiers", {}).get(tier, {})
    venv = _venv_of(py)
    # A note is believed only when it was written about THIS environment and the packages it
    # claims are really in it. Anything else means the environment changed underneath the note.
    believable = (done.get("requirements_sha") == _sha(req) and done.get("python") == py
                  and done.get("env") == env_id(venv))
    if not force and believable and _really_installed(py, tier):
        return False
    run([uv, "pip", "install", "--python", py, "-r", req], what="Installing the %s packages" % tier)
    state = load_state()
    state.setdefault("tiers", {})[tier] = {"requirements_sha": _sha(req), "python": py,
                                           "env": env_id(venv, make=True),
                                           "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_state(state)
    return True


def ensure_renderer(py, force=False):
    state = load_state()
    if state.get("renderer") and not force:
        return False
    try:
        run([py, "-m", "playwright", "install", "--only-shell", "chromium"], what="Installing the page renderer")
    except StepFailed:
        # older renderer packages do not know --only-shell
        run([py, "-m", "playwright", "install", "chromium"], what="Installing the page renderer")
    state = load_state()
    state["renderer"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    return True


def ensure_video_programs(py):
    """Fetch ffmpeg + ffprobe now, during setup, rather than in the middle of someone's first clip."""
    state = load_state()
    if state.get("video_programs"):
        return False
    run([py, "-c", "import static_ffmpeg; static_ffmpeg.add_paths(weak=False)"],
        what="Downloading the video programs (ffmpeg)")
    state = load_state()
    state["video_programs"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    return True


# ----------------------------------------------------------------------------- step 5 (video): the title renderer
# Motion titles in films are drawn by HyperFrames (Apache 2.0), which runs on Node. Neither is
# something the person installs: setup fetches a portable Node from nodejs.org into THIS folder
# (.factory/node/<kind of computer>/), checks it against the checksum nodejs.org publishes, and
# installs one pinned HyperFrames beside it with that Node's own npm. Nothing touches PATH, nothing
# needs an admin password, and the tools only ever run these copies, never whatever is on the
# computer. HyperFrames fetches the Chrome it renders with into its own cache (a folder in the
# person's home folder; it will not use another). Every size is said before a download starts.
NODE_VERSION = "22.20.0"
# kind of computer -> (file on nodejs.org/dist/v<version>/, its sha256 from SHASUMS256.txt there, MB to download)
NODE_FILES = {
    "win-x64": ("node-v22.20.0-win-x64.zip", "bb819d6eb8f5bfda294bbc83a7e4ec6539da67c4233d54b0d655b9248b15e29d", 34),
    "darwin-arm64": ("node-v22.20.0-darwin-arm64.tar.gz", "cc04a76a09f79290194c0646f48fec40354d88969bec467789a5d55dd097f949", 48),
    "darwin-x64": ("node-v22.20.0-darwin-x64.tar.gz", "00df9c5df3e4ec6848c26b70fb47bf96492f342f4bed6b17f12d99b3a45eeecc", 49),
    "linux-x64": ("node-v22.20.0-linux-x64.tar.gz", "eeaccb0378b79406f2208e8b37a62479c70595e20be6b659125eb77dd1ab2a29", 54),
    "linux-arm64": ("node-v22.20.0-linux-arm64.tar.gz", "4181609e03dcb9880e7e5bf956061ecc0503c77a480c6631d868cb1f65a2c7dd", 54),
}
NODE_URL = "https://nodejs.org/dist/v%s/%s"
HYPERFRAMES_VERSION = "0.8.175"             # the one version the Factory was tried with
HYPERFRAMES_MB = 120                        # on disk after npm install (76 packages)
CHROME_MB = 115                             # HyperFrames' Chrome download (about 270 MB unpacked)
# HyperFrames phones home unless told not to, checks for updates, and offers its own AI skills.
# None of that belongs in a brand's film: the brand's words stay on this computer.
HYPERFRAMES_ENV = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_UPDATE_CHECK": "1",
                   "HYPERFRAMES_SKIP_SKILLS": "1", "CI": "1"}
TITLES_HINT = "The title renderer is not installed yet. Run: python factory.py setup --tier video"


def node_dir():
    return os.path.join(STATE_DIR, "node")


def hyperframes_dir():
    return os.path.join(node_dir(), "hyperframes")


def node_platform():
    """nodejs.org's name for this kind of computer, or None when no build is known for it."""
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("x86_64", "amd64") else None
    system = "win" if WINDOWS else "darwin" if sys.platform == "darwin" else "linux" if sys.platform.startswith("linux") else None
    tag = "%s-%s" % (system, arch) if system and arch else None
    return tag if tag in NODE_FILES else None


def node_home(tag=None):
    tag = tag or node_platform() or "unknown"
    return os.path.join(node_dir(), tag, "node-v%s-%s" % (NODE_VERSION, tag))


def node_exe(tag=None):
    home = node_home(tag)
    return os.path.join(home, "node.exe") if WINDOWS else os.path.join(home, "bin", "node")


def npm_cli(tag=None):
    home = node_home(tag)
    return os.path.join(home, *(("node_modules",) if WINDOWS else ("lib", "node_modules")), "npm", "bin", "npm-cli.js")


def node_on_path():
    """PATH for one command only, with the Factory's own Node first. npm's install scripts (esbuild's,
    for one) start "node" by name, and a computer with no Node of its own has none to find. The
    person's PATH is never changed; only the command that needs it sees this."""
    return {"PATH": os.path.dirname(node_exe()) + os.pathsep + os.environ.get("PATH", "")}


def hyperframes_cli():
    return os.path.join(hyperframes_dir(), "node_modules", "hyperframes", "bin", "hyperframes.mjs")


def title_programs():
    """(node, hyperframes) when both are installed in this folder, else None."""
    node, cli = node_exe(), hyperframes_cli()
    return (node, cli) if os.path.isfile(node) and os.path.isfile(cli) else None


def _download(url, dest, what):
    """Fetch one file with the standard library, in pieces, to dest. Logged like a step."""
    import urllib.request
    log("$ download %s -> %s" % (url, dest))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(dest + ".part", "wb") as out:
            while True:
                piece = r.read(1 << 20)
                if not piece:
                    break
                out.write(piece)
    except Exception as e:                                                # noqa: BLE001  (urllib raises many kinds)
        raise StepFailed("%s did not finish: %s" % (what, e), NETWORK_HINT)
    from smf.brands import replace_patiently                # standard library only, and 3.8-safe
    replace_patiently(dest + ".part", dest)
    log("  -> %d bytes after %.0fs" % (os.path.getsize(dest), time.time() - started))


def ensure_node(force=False):
    """A portable Node in .factory/node, from nodejs.org, checked against its published checksum."""
    tag = node_platform()
    if not tag:
        raise StepFailed("nodejs.org has no build for this kind of computer (%s %s), so motion titles cannot be "
                         "made here. Everything else works without it." % (sys.platform, platform.machine()))
    if os.path.isfile(node_exe(tag)) and not force:
        return False
    name, sha, mb = NODE_FILES[tag]
    say("   downloading Node %s (%d MB) from nodejs.org into this folder" % (NODE_VERSION, mb))
    archive = os.path.join(STATE_DIR, "tmp", name)
    _download(NODE_URL % (NODE_VERSION, name), archive, "Downloading Node")
    if _sha(archive) != sha:
        os.remove(archive)
        raise StepFailed("the Node download did not match the checksum nodejs.org publishes, so it was thrown "
                         "away and nothing was installed. Run setup again; if it happens twice, something between "
                         "this computer and nodejs.org is changing the file.", NETWORK_HINT)
    target = os.path.join(node_dir(), tag)
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(target)
    else:
        with tarfile.open(archive, "r:gz") as t:
            try:
                t.extractall(target, filter="data")                    # Python 3.12+: no paths outside target
            except TypeError:
                t.extractall(target)
    os.remove(archive)
    if not os.path.isfile(node_exe(tag)):
        raise StepFailed("Node was downloaded and unpacked but its program is not where nodejs.org's archive "
                         "usually puts it.", NETWORK_HINT)
    run([node_exe(tag), "--version"], what="Starting the downloaded Node")
    state = load_state()
    state["node"] = {"version": NODE_VERSION, "when": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_state(state)
    return True


def ensure_hyperframes(force=False):
    """One pinned HyperFrames, installed with the Factory's own Node into .factory/node/hyperframes."""
    if os.path.isfile(hyperframes_cli()) and not force:
        return False
    if not os.path.isfile(node_exe()):
        raise StepFailed("HyperFrames needs the Factory's Node first, and it is not here.", NETWORK_HINT)
    say("   installing HyperFrames %s (about %d MB) into this folder with that Node" % (HYPERFRAMES_VERSION, HYPERFRAMES_MB))
    os.makedirs(hyperframes_dir(), exist_ok=True)
    run([node_exe(), npm_cli(), "install", "--prefix", hyperframes_dir(), "--no-audit", "--no-fund",
         "--no-package-lock", "--loglevel=error", "hyperframes@%s" % HYPERFRAMES_VERSION],
        env_extra=dict(HYPERFRAMES_ENV, **node_on_path()), what="Installing HyperFrames")
    if not os.path.isfile(hyperframes_cli()):
        raise StepFailed("HyperFrames was installed but its program is not where npm usually puts it.", NETWORK_HINT)
    state = load_state()
    state["hyperframes"] = {"version": HYPERFRAMES_VERSION, "when": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_state(state)
    return True


def ensure_title_browser(force=False):
    """The Chrome HyperFrames renders with. It downloads it into its own cache folder (inside the
    person's home folder) and uses no other, so setup fetches it now rather than in the middle of
    someone's first film."""
    state = load_state()
    if state.get("title_browser") and not force:
        return False
    programs = title_programs()
    if not programs:
        raise StepFailed("HyperFrames is not installed, so its Chrome cannot be fetched.", NETWORK_HINT)
    say("   fetching the Chrome that HyperFrames renders with (about %d MB; it lives in HyperFrames' own cache "
        "folder in your home folder)" % CHROME_MB)
    run([programs[0], programs[1], "browser", "ensure"], env_extra=HYPERFRAMES_ENV,
        what="Fetching HyperFrames' Chrome")
    state = load_state()
    state["title_browser"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    return True


def ensure_keys_file():
    dst = os.path.join(ROOT, "keys.env")
    src = os.path.join(ROOT, "keys.env.example")
    if os.path.isfile(dst) or not os.path.isfile(src):
        return False
    shutil.copyfile(src, dst)
    return True


# ----------------------------------------------------------------------------- the verb
SETUP_USAGE = """
python factory.py setup                 install what this computer needs (the core tier)
python factory.py setup --tier video    also install the video tools
python factory.py setup --force         reinstall even what looks installed
Safe to stop and run again.
"""


def setup(args):
    opts, _words, rc = read_options(args, "setup", SETUP_USAGE, flags=("--force",), values=("--tier",))
    if rc is not None:
        return rc
    tier = opts.get("--tier", "core")
    force = bool(opts.get("--force"))
    if tier not in TIERS:
        say("Unknown tier. Use one of: %s" % ", ".join(TIERS))
        return 2

    log("\n===== setup %s (%s) =====" % (time.strftime("%Y-%m-%d %H:%M:%S"), tier))
    say("Setting up Social Media Factory (%s). This is safe to stop and run again." % tier)
    try:
        free_gb = shutil.disk_usage(ROOT).free / 1e9
        if free_gb < 3:
            say("   Warning: only %.1f GB of disk space is free. Setup needs about 2 GB." % free_gb)
    except OSError:
        pass

    total = {"core": 5, "video": 5}.get(tier, 3)
    try:
        say("\nStep 1 of %d - the package installer" % total)
        uv = find_uv()
        if uv:
            say("   already here")
        else:
            say("   downloading it into this folder (no admin password needed)")
            uv = install_uv()
        state = load_state()
        state["uv"] = uv
        save_state(state)

        say("\nStep 2 of %d - the Social Media Factory's own Python" % total)
        py, made = ensure_env(uv)
        say("   created" if made else "   already here")

        say("\nStep 3 of %d - the %s packages" % (total, tier))
        say("   installed" if ensure_tier(uv, py, tier, force) else "   already up to date")

        if tier == "video":
            say("\nStep 4 of %d - the video programs" % total)
            say("   downloaded" if ensure_video_programs(py) else "   already here")
            say("\nStep 5 of %d - the title renderer (Node and HyperFrames, for motion titles in films)" % total)
            say("   Node: %s" % ("downloaded" if ensure_node(force) else "already here"))
            say("   HyperFrames: %s" % ("installed" if ensure_hyperframes(force) else "already here"))
            say("   its Chrome: %s" % ("fetched" if ensure_title_browser(force) else "already here"))

        if tier == "core":
            say("\nStep 4 of %d - the page renderer (draws carousels and cards; the biggest download)" % total)
            say("   installed" if ensure_renderer(py, force) else "   already here")
            say("\nStep 5 of %d - the keys file" % total)
            say("   created keys.env (empty; you only fill it in for posting or video)"
                if ensure_keys_file() else "   already here")
    except StepFailed as e:
        say("\nSetup stopped: %s" % e)
        if e.hint:
            say(e.hint)
        if e.hint != NETWORK_HINT:
            say(NETWORK_HINT)
        return 1

    say("\nSetup finished. Next: python factory.py status")
    return 0
