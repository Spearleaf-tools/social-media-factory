"""transcribe.py - turn a recording into the one transcript every clip tool reads.

Two ways in:

  * `transcribe`   sends the recording's sound to ElevenLabs speech-to-text, which returns every
                   word with its time AND which voice said it, from one system in one pass. That
                   matters: when words and voices come from two different tools they disagree at
                   exactly the moments that count, the hand-overs between people.
  * `ingest_srt`   reads a subtitle file an editor already made for the video being cut. Free and
                   instant, but it only knows sentence times and not who is speaking.

THIS SPENDS THE PERSON'S MONEY, so nothing is sent by default. A plain run measures the recording,
says what it will cost, and stops. Only `confirm=True` uploads. The key is read through
`smf.keys`, is never printed, and is scrubbed from anything the service says back.

What is written, into  Client/<brand>/Inputs/Recordings/<recording>/Transcriptions/ :

  transcript.json              the canonical file: sentences, words (with times and voices), and
                               a `source` record of exactly which file was transcribed
  transcript-timestamped.txt   the same thing for reading: one line per stretch of one voice
  transcript-on-camera.txt     only the people who may appear in clips. Clips are chosen from this
                               file, so an off-camera voice cannot be picked by accident: it is
                               not merely unselected, it is absent
  transcript.txt               plain flowing text

Voices come back as speaker_0, speaker_1 in whatever order they were found, and that order is
different from one recording to the next. So names are never guessed at transcription time: read
the first lines, see who is who, then `rename_speakers`. Renaming is free and never re-sends.
"""
from __future__ import annotations

import os
import re
import tempfile
import textwrap
import time

from smf import keys
from smf.video import gate
from smf.video.common import (ON_CAMERA_FILE, PLAIN_FILE, READABLE_FILE, TRANSCRIPT_FILE, Transcript, VideoError,
                              as_brand, fmt_ts, has_audio, locate, minutes_words, probe_duration, programs, read_json,
                              recording_dir, run, sentences_from_words, transcriptions_dir, turns_from_words,
                              write_json_atomic, write_text_atomic)

KEY_NAME = "ELEVENLABS_API_KEY"
ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = "scribe_v2"
# A published price, so it goes stale. Checked against the service's own API pricing page on the
# date below (standard speech-to-text, the same on every plan). Re-check it when the playbooks
# are refreshed, and move the date only when it really was re-checked.
PRICE_PER_HOUR_USD = 0.22
PRICE_LAST_RESEARCHED = "2026-09-20"
PRICE_AS_OF = "September 2026"
MADE_BY = "ElevenLabs speech-to-text"

NOT_SET_UP = ("Transcription is not set up yet: %s is missing from the keys file. It is an ElevenLabs key, and "
              "transcribing costs about 22 cents per hour of audio. Add the key to keys.env, then try again."
              % KEY_NAME)


# ----------------------------------------------------------------------------- cost
def estimate_cost(seconds):
    return max(0.0, float(seconds)) / 3600.0 * PRICE_PER_HOUR_USD


def cost_words(usd):
    if usd < 0.995:
        return "about %d cent%s" % (max(1, round(usd * 100)), "" if max(1, round(usd * 100)) == 1 else "s")
    return "about $%.2f" % usd


# ----------------------------------------------------------------------------- the service
def extract_audio(media, dst):
    """Sound only, one channel, 16 kHz: a small upload that loses nothing a speech model uses."""
    ff, _fp = programs()
    run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", media, "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "aac", "-b:a", "64k", dst], "pull the sound out of the recording")
    return dst


def send_to_elevenlabs(audio_path, api_key, speakers=None, model=MODEL):
    """Upload one audio file, return the service's JSON. The only function here that touches the
    network, and it is only ever called after an explicit confirm."""
    import requests
    broken = keys.damaged(api_key, KEY_NAME)             # asked first: a bad header's own error quotes the key
    if broken:
        raise VideoError(broken + " Nothing was sent, so nothing was spent.")
    data = {"model_id": model, "diarize": "true", "timestamps_granularity": "word"}
    if speakers:
        data["num_speakers"] = str(int(speakers))
    try:
        with open(audio_path, "rb") as fh:
            r = requests.post(ENDPOINT, headers={"xi-api-key": api_key},
                              files={"file": ("recording.m4a", fh, "audio/mp4")}, data=data, timeout=3600)
    except requests.RequestException:
        raise VideoError("Could not reach ElevenLabs, so nothing was transcribed. Check the internet "
                         "connection and try again.")
    if r.status_code in (401, 403):
        raise VideoError("ElevenLabs refused the key. Check that %s in keys.env is complete and that the "
                         "ElevenLabs account has credit." % KEY_NAME)
    if r.status_code != 200:
        raise VideoError("ElevenLabs could not transcribe this (it answered %d: %s)."
                         % (r.status_code, keys.redact(r.text)[:300]))      # hide keys first, shorten second
    try:
        return r.json()
    except ValueError:
        raise VideoError("ElevenLabs answered with something unreadable. Nothing was saved; try again.")


def words_from_response(payload):
    """The service's answer -> [{"word", "start", "end", "speaker"}]. Its list also holds spacing
    and sound-event entries ("(laughs)"); only real words with a time are kept."""
    out = []
    for w in (payload or {}).get("words") or []:
        if w.get("type") not in (None, "word") or w.get("start") is None:
            continue
        text = (w.get("text") or "").strip()
        if not text:
            continue
        start = float(w["start"])
        out.append({"word": text, "start": round(start, 3), "end": round(float(w.get("end", start)), 3),
                    "speaker": str(w.get("speaker_id") or "")})
    out.sort(key=lambda w: w["start"])
    return out


# ----------------------------------------------------------------------------- writing the files
def _readable(turns, with_voice=True):
    lines = []
    for t in turns:
        voice = ("%s: " % (t["speaker"] or "unlabelled")) if with_voice else ""
        lines.append("[%s - %s] %s%s" % (fmt_ts(t["start"]), fmt_ts(t["end"]), voice, t["text"]))
    return "\n".join(lines) + "\n"


def write_transcript(brand, recording, words=None, segments=None, source=None, language=""):
    """Write all four files from one set of words (or, for subtitles, one set of sentences).
    Everything is derived from the same list in the same call, so the files cannot disagree."""
    brand = as_brand(brand)
    dest = transcriptions_dir(brand, recording)
    words = words or []
    segments = segments if segments is not None else sentences_from_words(words)
    if not words and not segments:
        raise VideoError("There were no words to save: the recording may be silent, or not speech.")
    duration = max([w["end"] for w in words] + [s["end"] for s in segments])
    data = {"schema": 1, "language": language, "duration": round(duration, 3), "word_level": bool(words),
            "source": source or {}, "segments": segments, "words": words}
    transcript = Transcript(data)
    policy = gate.SpeakerPolicy.for_transcript(brand, transcript)
    turns = turns_from_words(words) if words else segments

    write_json_atomic(os.path.join(dest, TRANSCRIPT_FILE), data, compact=True)
    write_text_atomic(os.path.join(dest, READABLE_FILE), _readable(turns, with_voice=bool(transcript.speakers)))
    write_text_atomic(os.path.join(dest, PLAIN_FILE),
                      textwrap.fill(" ".join(s["text"] for s in segments), width=100) + "\n")

    header = "# %s\n# %s\n\n" % (recording, policy.describe())
    if not policy.labelled:
        body = ("# This transcript does not say who is speaking, so nobody could be left out.\n\n"
                + _readable(turns, with_voice=False))
    elif not policy.on_camera():
        body = ("# Nobody is cleared to appear yet. Name the voices first, then this file fills in.\n"
                "# The voices are: %s\n" % ", ".join(policy.present))
    else:
        body = _readable([t for t in turns if policy.may_publish(t["speaker"])])
    write_text_atomic(os.path.join(dest, ON_CAMERA_FILE), header + body)
    return transcript, policy


# ----------------------------------------------------------------------------- transcribe
def plan(brand, recording, media):
    """Measure the recording and say what sending it would cost. Touches no network."""
    brand = as_brand(brand)
    recording_dir(brand, recording)                          # validates the name
    if not media or not os.path.isfile(media):
        raise VideoError("That recording could not be found. Give the video or audio file itself.")
    if not has_audio(media):
        raise VideoError("'%s' has no sound in it, so there is nothing to transcribe." % os.path.basename(media))
    seconds = probe_duration(media)
    existing = os.path.isfile(os.path.join(transcriptions_dir(brand, recording), TRANSCRIPT_FILE))
    keys.load()
    return {"brand": brand.id, "recording": recording, "media": media, "seconds": seconds,
            "cost_usd": round(estimate_cost(seconds), 4), "cost_words": cost_words(estimate_cost(seconds)),
            "key_present": keys.has(KEY_NAME), "already_transcribed": existing}


def plan_words(p):
    lines = ["This recording is %s long. Transcribing it with ElevenLabs will cost %s "
             "(about 22 cents per hour of audio, as of %s)." % (minutes_words(p["seconds"]), p["cost_words"], PRICE_AS_OF)]
    if p["already_transcribed"]:
        lines.append("It already has a transcript. Sending it again would cost the same again.")
    if not p["key_present"]:
        lines.append(NOT_SET_UP)
    lines.append("Nothing has been sent. To go ahead, run this again with --confirm.")
    return "\n".join(lines)


def transcribe(brand, recording, media, confirm=False, speakers=None, again=False, send=None, say=None):
    """Dry by default. Returns the plan when `confirm` is false and makes no network call at all.
    `send(audio_path, api_key, speakers)` is injectable so the whole path can be tested offline."""
    brand = as_brand(brand)
    p = plan(brand, recording, media)
    if not confirm:
        return {"sent": False, "plan": p}
    if p["already_transcribed"] and not again:
        raise VideoError("'%s' already has a transcript, and transcribing it again costs money again (%s). "
                         "If the first one is wrong and you really want a fresh one, add --again."
                         % (recording, p["cost_words"]))
    if not p["key_present"]:
        raise VideoError(NOT_SET_UP)
    api_key = os.environ.get(KEY_NAME, "")
    send = send or send_to_elevenlabs
    say = say or (lambda _text: None)
    with tempfile.TemporaryDirectory(prefix="smf-audio-") as scratch:
        audio = extract_audio(media, os.path.join(scratch, "recording.m4a"))
        say("Sending %s of sound to ElevenLabs (%s)..." % (minutes_words(p["seconds"]), p["cost_words"]))
        payload = send(audio, api_key, speakers)
    words = words_from_response(payload)
    if not words:
        raise VideoError("ElevenLabs found no words in this recording. Nothing was saved.")
    source = {"media": locate(brand, media), "media_name": os.path.basename(media),
              "duration": round(p["seconds"], 3), "size_bytes": os.path.getsize(media), "made_by": MADE_BY,
              "model": MODEL, "transcribed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "estimated_cost_usd": p["cost_usd"]}
    transcript, policy = write_transcript(brand, recording, words=words, source=source,
                                          language=str((payload or {}).get("language_code") or ""))
    return {"sent": True, "plan": p, "transcript": transcript, "policy": policy}


# ----------------------------------------------------------------------------- naming the voices
def rename_speakers(brand, recording, mapping):
    """Give the voices their real names, once somebody has checked who is who.

    Refuses a map that leaves a voice out, and refuses a new name that collides with a voice that
    is not being renamed. A half-applied rename is worse than none, because it looks finished."""
    brand = as_brand(brand)
    path = os.path.join(transcriptions_dir(brand, recording), TRANSCRIPT_FILE)
    data = read_json(path, "The transcript for '%s'" % recording)
    transcript = Transcript(data, path)
    if not transcript.word_level or not transcript.labelled:
        raise VideoError("This transcript has no voice labels to rename (it came from a subtitle file).")
    mapping = {str(k).strip(): str(v).strip() for k, v in (mapping or {}).items()}
    if not mapping or any(not k or not v for k, v in mapping.items()):
        raise VideoError("Say which voice gets which name, like speaker_0=\"Ava Lindqvist\".")
    present = transcript.speakers
    unknown = [k for k in mapping if k not in present]
    if unknown:
        raise VideoError("There is no voice called %s in this transcript. The voices are: %s."
                         % (", ".join(unknown), ", ".join(present)))
    unnamed_left = [s for s in present if s not in mapping and gate.SpeakerPolicy.is_unnamed(s)]
    if unnamed_left:
        raise VideoError("Name every voice in one go, so no clip is cut from a half-labelled recording. "
                         "Still unnamed: %s." % ", ".join(unnamed_left))
    clash = set(mapping.values()) & (set(present) - set(mapping))
    if clash or len(set(mapping.values())) != len(mapping):
        raise VideoError("Two voices would end up with the same name (%s). Each voice needs its own."
                         % ", ".join(sorted(clash) or sorted(mapping.values())))
    words = [dict(w, speaker=mapping.get(w["speaker"], w["speaker"])) for w in transcript.words]
    source = dict(transcript.source)
    source["voices_named"] = dict(source.get("voices_named") or {}, **mapping)
    return write_transcript(brand, recording, words=words, source=source, language=transcript.language)


# ----------------------------------------------------------------------------- subtitles
_SRT_TIME = re.compile(r"(\d+:\d{2}:\d{2}[,.]\d{1,3}|\d+:\d{2}[,.]\d{1,3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{1,3}|\d+:\d{2}[,.]\d{1,3})")
_SRT_TAG = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def parse_srt(text):
    """Subtitle text -> [{"start", "end", "text", "speaker": ""}]. Cue numbers are optional and
    styling tags are dropped."""
    segments = []
    for block in re.split(r"\r?\n\s*\r?\n", (text or "").strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        at = next((i for i, ln in enumerate(lines) if _SRT_TIME.search(ln)), None)
        if at is None:
            continue
        m = _SRT_TIME.search(lines[at])
        body = _SRT_TAG.sub("", " ".join(lines[at + 1:])).strip()
        if not body:
            continue

        def seconds(stamp):
            parts = stamp.replace(",", ".").split(":")
            total = 0.0
            for part in parts:
                total = total * 60 + float(part)
            return round(total, 3)
        start, end = seconds(m.group(1)), seconds(m.group(2))
        if end > start:
            segments.append({"start": start, "end": end, "text": body, "speaker": ""})
    segments.sort(key=lambda s: s["start"])
    return segments


def ingest_srt(brand, recording, srt_path, media=None):
    """File an editor's subtitle file as this recording's transcript. Its times match the edited
    video it was made for, which is the point: the cut list will refer to a file the editor has."""
    brand = as_brand(brand)
    if not srt_path or not os.path.isfile(srt_path):
        raise VideoError("That subtitle file could not be found.")
    with open(srt_path, "r", encoding="utf-8-sig", errors="replace") as f:
        segments = parse_srt(f.read())
    if not segments:
        raise VideoError("No subtitles could be read from '%s'. It should be an .srt file." % os.path.basename(srt_path))
    if media and not os.path.isfile(media):
        raise VideoError("The video these subtitles belong to could not be found.")
    source = {"media": locate(brand, media) if media else "", "media_name": os.path.basename(media) if media else "",
              "made_by": "an editor's subtitle file (%s)" % os.path.basename(srt_path),
              "transcribed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "note": "Sentence times only. No word times and no voice labels."}
    return write_transcript(brand, recording, words=[], segments=segments, source=source)
