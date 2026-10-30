"""media.py - one place that makes the video programs (ffmpeg, ffprobe) available.

The tools call `ffmpeg` and `ffprobe` by name. Instead of asking people to install them with
Homebrew or an installer, the video tier brings its own copies (the static-ffmpeg package
downloads the right build for this computer the first time) and this module puts them at the
front of PATH for the current process, so every computer runs the same version.
"""
from __future__ import annotations

import shutil

_done = False


def ensure_ffmpeg():
    """Returns (ffmpeg_path, ffprobe_path). Raises RuntimeError with a plain message if missing."""
    global _done
    if not _done:
        try:
            import static_ffmpeg
        except ImportError:
            raise RuntimeError("The video tools are not installed yet. Run: python factory.py setup --tier video")
        static_ffmpeg.add_paths(weak=False)
        _done = True
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ff or not fp:
        raise RuntimeError("The video programs could not be found after install. Run: python factory.py doctor")
    return ff, fp


def node_programs():
    """Returns (node, hyperframes): the Factory's own Node and HyperFrames, installed by the video
    tier into .factory/node. Never the computer's own. Raises RuntimeError with a plain message if
    they are missing."""
    from smf import bootstrap
    programs = bootstrap.title_programs()
    if not programs:
        raise RuntimeError(bootstrap.TITLES_HINT)
    return programs
