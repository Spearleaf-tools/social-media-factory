"""multicam_verify.py - open the finished two-camera video and check it is what the plan said.

A CHECK THAT READS THE PLAN IS NOT A CHECK. The list of shots says what SHOULD be on screen. Only
the finished file says what IS. So nothing here re-derives the plan and compares it with itself;
every answer comes from the rendered file, compared against the original camera files:

  plays      the whole file decodes. A header can be perfect while the pictures inside are broken,
             and only playing it through shows that.
  length     the file is as long as the shots add up to.
  pictures   just before and just after each cut, one frame is pulled out of the finished video and
             compared with three pictures made fresh from the ORIGINAL camera files for that same
             moment: camera A, camera B, and both side by side. The nearest one has to be the one
             the list of shots promised. Sampling right beside the cut is the point: a switch that
             lands a few frames early or late shows up there and nowhere else. The comparison is
             a plain difference between small versions of the pictures. No model is involved.
  sound      at the start, the middle and the end, a few seconds of the finished video's sound is
             searched for in the original sound file. It has to be found exactly where the list of
             shots says that moment came from. Pictures checked against the cameras plus sound
             checked against the sound file is what "still in sync" means.

A check that could not look at anything (no frame readable, no sound found) is a FAILURE. "Nothing
was wrong" and "nothing was examined" must never look the same.
"""
from __future__ import annotations

import os

from smf.video import multicam, sync
from smf.video.common import (VideoError, as_brand, decodes_cleanly, fmt_ts, locate, output_dir, probe_duration,
                              programs, read_json, run, write_json_atomic)

THUMB_WIDTH = 64
BESIDE_THE_CUT = 0.12          # how far from a cut a frame is sampled, seconds (and never under 3 frames)
DEFAULT_SAMPLES = 60           # the most cuts looked at in one video; they are spread evenly
CLEARLY_NEARER = 0.6           # the right picture must be this much nearer than the next nearest...
OR_NEARER_BY = 6.0             # ...or nearer by this much, on a 0 to 255 scale
TOO_ALIKE = 4.0                # two cameras this similar cannot be told apart by looking
LENGTH_WITHIN = 0.5
SOUND_WINDOW = 6.0
SOUND_REACH = 2.0
SOUND_WITHIN = 0.06
REPORT_SUFFIX = ".check.json"
CLIPS_REPORT = "two-camera-check.json"


def _np():
    import numpy
    return numpy


def _thumb(size):
    height = max(8, int(round(THUMB_WIDTH * size[1] / float(size[0]) / 2.0)) * 2)
    return THUMB_WIDTH, height


def _frame_of_video(video, at, thumb):
    np = _np()
    ff, _fp = programs()
    r = run([ff, "-v", "error", "-ss", "%.4f" % max(0.0, at), "-i", video, "-frames:v", "1",
             "-vf", "scale=%d:%d" % thumb, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            "pull a frame out of the finished video", binary=True)
    if len(r.stdout) < thumb[0] * thumb[1] * 3:
        return None
    return np.frombuffer(r.stdout[:thumb[0] * thumb[1] * 3], np.uint8).astype("float64").reshape(thumb[1], thumb[0], 3)


def _frames_of_cameras(files, at, size, fps_text, look_at, left, thumb):
    """{"A", "B", "both"}: what each picture would be at transcript time `at`, made from the
    original camera files by the renderer's own picture recipe."""
    np = _np()
    ff, _fp = programs()
    graph = multicam.three_pictures(size, fps_text, look_at, left)
    graph += (";[pa]scale=%d:%d[ta];[pb]scale=%d:%d[tb];[pboth]scale=%d:%d[tw];[ta][tb][tw]hstack=inputs=3[out]"
              % (thumb * 3))
    cmd = [ff, "-v", "error"]
    for cam in multicam.CAMERAS:
        cmd += ["-ss", "%.4f" % max(0.0, multicam.seek_of(files[cam], at)), "-i", files[cam]["path"]]
    r = run(cmd + ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            "pull the same moment out of the two cameras", binary=True)
    need = thumb[0] * 3 * thumb[1] * 3
    if len(r.stdout) < need:
        return None
    wide = np.frombuffer(r.stdout[:need], np.uint8).astype("float64").reshape(thumb[1], thumb[0] * 3, 3)
    return {multicam.A: wide[:, :thumb[0]], multicam.B: wide[:, thumb[0]:2 * thumb[0]], multicam.BOTH: wide[:, 2 * thumb[0]:]}


def distance(a, b):
    """How different two small pictures are: the average difference per colour value, 0 to 255."""
    np = _np()
    return float(np.abs(a - b).mean())


def judge_frame(seen, candidates, expected):
    """One sampled frame -> {"verdict": right | wrong | cannot-tell, "looks_like", "distances"}."""
    distances = {k: round(distance(seen, v), 2) for k, v in candidates.items()}
    ranked = sorted(distances, key=lambda k: (distances[k], k))
    others = [distance(candidates[expected], v) for k, v in candidates.items() if k != expected]
    out = {"expected": expected, "looks_like": ranked[0], "distances": distances}
    if min(others) < TOO_ALIKE:
        out["verdict"] = "cannot-tell"                      # the pictures themselves are too alike to decide
    elif ranked[0] == expected and (distances[ranked[0]] <= CLEARLY_NEARER * distances[ranked[1]]
                                    or distances[ranked[1]] - distances[ranked[0]] >= OR_NEARER_BY):
        out["verdict"] = "right"
    elif ranked[0] == expected:
        out["verdict"] = "cannot-tell"
    else:
        out["verdict"] = "wrong"
    return out


def sample_points(shots, fps, most=DEFAULT_SAMPLES):
    """[(time in the finished video, time in the transcript, what should be on screen, which cut)].
    Two beside every cut (one each side), plus the middle of the first and last shots, so a video
    with no cuts at all is still looked at."""
    beside = max(BESIDE_THE_CUT, 3.0 / fps)
    points = []

    def inside(shot, out_time, label):
        room = 0.4 * (shot["out_end"] - shot["out_start"])
        out_time = min(max(out_time, shot["out_start"] + min(beside, room)), shot["out_end"] - min(beside, room))
        points.append({"out": round(out_time, 4), "at": round(shot["start"] + out_time - shot["out_start"], 4),
                       "expected": shot["show"], "where": label})

    cuts = [i for i in range(1, len(shots)) if shots[i]["show"] != shots[i - 1]["show"]]
    if len(cuts) > most:
        step = (len(cuts) - 1) / float(most - 1)
        cuts = sorted({cuts[int(round(i * step))] for i in range(most)})
    inside(shots[0], (shots[0]["out_start"] + shots[0]["out_end"]) / 2.0, "the first shot")
    for i in cuts:
        label = "the cut at %s" % fmt_ts(shots[i]["out_start"], 2)
        inside(shots[i - 1], shots[i - 1]["out_end"] - beside, "just before " + label)
        inside(shots[i], shots[i]["out_start"] + beside, "just after " + label)
    if len(shots) > 1:
        inside(shots[-1], (shots[-1]["out_start"] + shots[-1]["out_end"]) / 2.0, "the last shot")
    return points


def _stretches(shots):
    """Runs of shots that are continuous in BOTH clocks: inside one, finished-video time and
    transcript time move together, so a few seconds of sound can be looked up in one place."""
    runs = []
    for s in shots:
        if runs and abs(runs[-1]["end"] - s["start"]) < 0.02 and abs(runs[-1]["out_end"] - s["out_start"]) < 0.02:
            runs[-1]["end"], runs[-1]["out_end"] = s["end"], s["out_end"]
        else:
            runs.append({k: s[k] for k in ("start", "end", "out_start", "out_end")})
    return runs


def check_sound(video, shots, sound):
    """The finished video's sound, looked up in the original sound file at three places."""
    finished, original = sync.FileSound(video), sync.FileSound(sound["path"])
    how = sync.BY_SOUND
    runs = [r for r in _stretches(shots) if r["out_end"] - r["out_start"] >= 2.0]
    if not runs:
        return []
    total = shots[-1]["out_end"]
    points = []
    for target in (0.0, total / 2.0, total):
        run_ = min(runs, key=lambda r: 0.0 if r["out_start"] <= target <= r["out_end"]
                   else min(abs(r["out_start"] - target), abs(r["out_end"] - target)))
        length = min(SOUND_WINDOW, run_["out_end"] - run_["out_start"] - 0.2)
        out = min(max(target - length / 2.0, run_["out_start"] + 0.1), run_["out_end"] - 0.1 - length)
        where = run_["start"] + (out - run_["out_start"]) + sound["offset"]           # in the sound file's clock
        wide_from = max(0.0, where - SOUND_REACH)
        found = sync.locate_inside(finished.read(out, length), original.read(wide_from, length + 2 * SOUND_REACH),
                                   int(how["exclude"] * how["rate"]))
        entry = {"out": round(out, 3), "clear": sync.is_clear(found, how)}
        if found is not None:
            entry["out_by"] = round(wide_from + found["index"] / float(how["rate"]) - where, 4)
        if not any(abs(p["out"] - entry["out"]) < 0.5 for p in points):
            points.append(entry)
    return points


def check_render(video, shots, files, size, fps_text, fps, look_at=None, left=multicam.A, samples=DEFAULT_SAMPLES,
                 say=None):
    """Everything above, for one finished file. `shots` carry both clocks (start/end in the
    transcript, out_start/out_end in the finished video). Returns the result; raises only when
    nothing at all could be examined."""
    say = say or (lambda _t: None)
    problems = []
    if not os.path.isfile(video):
        raise VideoError("'%s' is not there, so there is nothing to check." % os.path.basename(video))
    plays = decodes_cleanly(video)
    if not plays:
        problems.append("the file does not play all the way through; it was probably interrupted while being made")
    planned = shots[-1]["out_end"] - shots[0]["out_start"]
    actual = probe_duration(video)
    if abs(actual - planned) > LENGTH_WITHIN:
        problems.append("it is %s long but the shots add up to %s" % (fmt_ts(actual, 2), fmt_ts(planned, 2)))

    thumb = _thumb(size)
    frames = []
    for point in sample_points(shots, fps, samples) if plays else []:
        seen = _frame_of_video(video, point["out"], thumb)
        candidates = _frames_of_cameras(files, point["at"], size, fps_text, look_at, left, thumb)
        if seen is None or candidates is None:
            frames.append(dict(point, verdict="cannot-tell", why="a frame could not be read"))
            continue
        frames.append(dict(point, **judge_frame(seen, candidates, point["expected"])))
    names = {multicam.A: "camera A", multicam.B: "camera B", multicam.BOTH: "both people"}
    for f in frames:
        if f["verdict"] == "wrong":
            problems.append("%s (%s into the video) should show %s but shows %s"
                            % (f["where"], fmt_ts(f["out"], 2), names[f["expected"]], names[f["looks_like"]]))
    looked_at = [f for f in frames if f["verdict"] != "cannot-tell"]

    sound = check_sound(video, shots, files["sound"]) if plays else []
    heard = [p for p in sound if p["clear"]]
    for p in heard:
        if abs(p["out_by"]) > SOUND_WITHIN:
            problems.append("the sound %s into the video is %.2f seconds away from where it belongs"
                            % (fmt_ts(p["out"], 0), abs(p["out_by"])))

    # Nothing examined is never a pass.
    if plays and not looked_at:
        problems.append("no picture could be checked: %s"
                        % ("the two cameras look too alike to tell apart" if frames else "no frame could be read"))
    if plays and not heard:
        problems.append("the video's sound could not be found in the original sound at all, so whether picture and "
                        "sound are in step could not be checked")
    return {"pass": not problems, "problems": problems, "plays": plays,
            "length": {"planned": round(planned, 3), "actual": round(actual, 3)},
            "pictures": {"checked": len(looked_at), "could_not_tell": len(frames) - len(looked_at),
                         "wrong": sum(1 for f in frames if f["verdict"] == "wrong"), "samples": frames},
            "sound": {"checked": len(heard), "could_not_find": len(sound) - len(heard), "places": sound}}


# ----------------------------------------------------------------------------- the two things that get checked
def verify_edit(brand, recording, name=multicam.EDIT_NAME, samples=DEFAULT_SAMPLES, say=None):
    """Check the full two-camera edit against the list of shots saved beside it."""
    brand = as_brand(brand)
    video = multicam.multicam_dir(brand, recording, name + ".mp4")
    decisions_file = multicam.decisions_path(video)
    if not os.path.isfile(video) or not os.path.isfile(decisions_file):
        raise VideoError("There is no two-camera video to check yet for '%s'. Render it first. Nothing was verified, "
                         "and that is not a pass." % recording)
    d = read_json(decisions_file, "The list of shots saved beside the video")
    files = multicam.files_from_record(brand, recording, d)
    fps = dict(multicam.COMMON_RATES).get(d["fps"]) or float(d["fps"])
    result = check_render(video, d["shots"], files, tuple(d["size"]), d["fps"], fps, d.get("look_at"),
                          d.get("left") or multicam.A, samples, say)
    out = dict(result, schema=1, kind="two-camera check", brand=brand.id, recording=recording, video=locate(brand, video))
    write_json_atomic(os.path.splitext(video)[0] + REPORT_SUFFIX, out)
    return out


def verify_clips(brand, recording, only=None, samples=12, say=None):
    """Check every two-camera clip against the shots written into the clips' report."""
    say = say or (lambda _t: None)
    brand = as_brand(brand)
    folder = output_dir(brand, recording, "rough")
    report_file = os.path.join(folder, "rough-cut-report.json")
    if not os.path.isfile(report_file):
        raise VideoError("There are no clips to check yet for '%s'. Nothing was verified, and that is not a pass."
                         % recording)
    report = read_json(report_file, "The clips' report")
    if report.get("made_with") != "two cameras":
        raise VideoError("The clips for '%s' were cut from one camera, not two, so there are no camera switches to "
                         "check. Use validate-cuts for those." % recording)
    files = multicam.files_from_record(brand, recording, report)
    fps = dict(multicam.COMMON_RATES).get(report["fps"]) or float(report["fps"])
    size = (report["shape"]["width"], report["shape"]["height"])
    wanted = {o.upper() for o in only} if only else None
    results = []
    for clip in report.get("clips", []):
        if not clip.get("file") or (wanted is not None and clip["id"].upper() not in wanted):
            continue
        entry = {"id": clip["id"], "file": clip["file"]}
        path = os.path.join(folder, clip["file"])
        if clip.get("status") != "ok" or not os.path.isfile(path):
            entry.update({"pass": False, "problems": ["it was not made properly (status: %s)" % clip.get("status", "missing")]})
        else:
            shots = [s for seg in clip["segments"] for s in seg["shots"]]
            entry.update(check_render(path, shots, files, size, report["fps"], fps, report.get("look_at"),
                                      report.get("left") or multicam.A, samples, say))
        results.append(entry)
        say("%s  %s%s" % ("ok  " if entry["pass"] else "FAIL", clip["id"],
                          "" if entry["pass"] else "  " + "; ".join(entry["problems"])))
    if not results:
        raise VideoError("No clips were found to check, so nothing was verified. That is not a pass.")
    out = {"schema": 1, "kind": "two-camera check", "brand": brand.id, "recording": recording,
           "checked": len(results), "failed": [r["id"] for r in results if not r["pass"]], "clips": results}
    write_json_atomic(os.path.join(folder, CLIPS_REPORT), out)
    return out
