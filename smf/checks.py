"""checks.py - small read-only tests a feature can require. Each returns (ok, plain_reason)."""
from __future__ import annotations

from smf import bootstrap


def renderer():
    if not bootstrap.load_state().get("renderer"):
        return False, "the page renderer is not installed (python factory.py setup)"
    return True, ""


def ffmpeg():
    if "video" not in bootstrap.load_state().get("tiers", {}):
        return False, "the video tools are not installed (python factory.py setup --tier video)"
    return True, ""


def titles():
    if "video" not in bootstrap.load_state().get("tiers", {}):
        return False, "the video tools are not installed (python factory.py setup --tier video)"
    if not bootstrap.title_programs():
        return False, "the title renderer is not installed (python factory.py setup --tier video)"
    return True, ""


CHECKS = {"renderer": renderer, "ffmpeg": ffmpeg, "titles": titles}
