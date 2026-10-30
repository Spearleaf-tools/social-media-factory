"""voice.py - talk instead of type on the onboarding page (card F6).

    text = transcribe_bytes(audio_bytes, "audio/webm")      # in memory only; never a file
    what = understand(text, question_key)                   # a command, an answer card, or "for the chat"

Listening: the browser records one answer into memory and sends the bytes to the local page server,
which passes them straight to ElevenLabs speech-to-text as an in-memory stream. Nothing writes the
audio to a temporary file, a cache, the Inputs folder, a log or a report, and the bytes are dropped
once the words come back. The browser never sees the key.

It reuses Video's ElevenLabs endpoint, model and key name from smf/video/transcribe.py WITHOUT
editing that file (its own helper takes a file path, which would force audio onto disk).

Understanding: a short phrase that is one of the page's commands ("go back", "skip", "hang on",
"type instead", "don't save that", ...) becomes that command. A question to the assistant, or
anything else the page cannot place, goes to the chat ("for_chat"). Everything else comes back as
words for the person to check and confirm. Speech alone never confirms an answer.
"""
from __future__ import annotations

import io
import re

from smf import keys
from smf.onboarding_page import secrets_check
from smf.video.transcribe import ENDPOINT, KEY_NAME, MODEL, PRICE_PER_HOUR_USD

MAX_BYTES = 8 * 1024 * 1024          # about eight minutes of compressed speech: far more than one answer
AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac")

DIDNT_CATCH = "I didn't catch that. Try again, or type it."
NO_KEY = "Talking needs an ElevenLabs key, and there isn't one yet. You can type instead."
SPOKEN_SECRET = ("That sounded like a password or key. I've deleted it. Because it was spoken, it has already "
                 "gone to the speech service, so replace that key in your account. Keys go in your keys file, "
                 "never here.")
FOR_CHAT = "I want to make sure I get that right. Let's handle that in the chat."


class VoiceError(Exception):
    """A plain sentence for the person. Never holds a key, audio, or a raw error."""


def available():
    """True when an ElevenLabs key is present. The key itself never leaves this module."""
    return keys.has(KEY_NAME)


def cost_estimate(seconds):
    return round(seconds / 3600.0 * PRICE_PER_HOUR_USD, 4)


def _post(audio, mime, api_key):
    import requests
    return requests.post(ENDPOINT, headers={"xi-api-key": api_key},
                         files={"file": ("answer", io.BytesIO(audio), mime)},
                         data={"model_id": MODEL}, timeout=60)


def transcribe_bytes(audio, mime, post=None):
    """Send one recorded answer to ElevenLabs and return the words. `post` is the network call,
    replaced by a stand-in in tests. The bytes are only ever held in memory."""
    if not available():
        raise VoiceError(NO_KEY)
    if not isinstance(audio, (bytes, bytearray)) or not audio:
        raise VoiceError(DIDNT_CATCH)
    if len(audio) > MAX_BYTES:
        raise VoiceError("That recording was too long. Try a shorter answer, or type it.")
    mime = (mime or "").split(";")[0].strip().lower()
    if mime not in AUDIO_TYPES:
        raise VoiceError(DIDNT_CATCH)
    import os
    api_key = os.environ.get(KEY_NAME, "")
    if keys.damaged(api_key, KEY_NAME):
        raise VoiceError("The ElevenLabs key in your keys file looks damaged, so nothing was sent. You can type instead.")
    try:
        r = (post or _post)(bytes(audio), mime, api_key)
    except Exception:
        raise VoiceError(DIDNT_CATCH)
    finally:
        audio = None                                     # nothing keeps the recording past this call
    status = getattr(r, "status_code", 0)
    if status in (401, 403):
        refused = VoiceError("ElevenLabs refused the key. Check the key and that the account has credit. You can type instead.")
        refused.refused = True                           # remembered, so the page and status both say "not working"
        raise refused
    if status != 200:
        raise VoiceError(DIDNT_CATCH)
    try:
        payload = r.json()
    except ValueError:
        raise VoiceError(DIDNT_CATCH)
    text = re.sub(r"\s+", " ", str((payload or {}).get("text") or "")).strip()
    text = re.sub(r"\((?:[^()]{0,30})\)", "", text).strip()      # sound events like "(laughs)"
    if not text:
        raise VoiceError(DIDNT_CATCH)
    return text


# ----------------------------------------------------------------------------- understanding (F6.2)
# Spoken commands (spec 3c). Matched only when the whole utterance is short and is the command,
# so "I'd like to go back to basics with our bread" is an answer, not "go back".
COMMANDS = (
    ("back", ("go back", "back", "previous question", "last question")),
    ("skip", ("skip", "skip it", "skip this", "i'm not sure", "im not sure", "i am not sure", "not sure")),
    # v2 (spec rev 9, shared behaviour): "next" moves on and leaves unconfirmed text as a draft; it never
    # confirms and never discards. Today's page (index.html) still treats it as skip.
    ("next", ("next", "next question", "move on")),
    ("pause", ("pause", "hang on", "give me a second", "give me a sec", "one second", "wait", "hold on")),
    ("type", ("type instead", "let me type", "i'll type", "ill type", "i want to type")),
    ("undo", ("undo", "undo that", "don't save that", "dont save that", "do not save that",
              "delete my last answer", "delete that", "scratch that")),
    ("repeat", ("repeat the question", "repeat that", "say that again", "ask me that differently",
                "ask it differently", "what was the question")),
    ("explain", ("explain that", "give me an example", "can you give me an example", "example",
                 "what does that mean", "explain")),
    ("start_over", ("start over", "start again", "begin again")),
    ("finish_chat", ("finish in chat", "finish in the chat", "let's finish in chat", "lets finish in chat")),
    ("continue", ("continue", "go on", "okay continue", "ok continue", "i'm back", "im back", "resume")),
    # Keeping what the page heard, or saying it again. The page decides what "yes" may do: it never
    # confirms a name, a handle or a rule, which always need a tap (spec 3b).
    ("confirm", ("yes", "yeah", "yep", "yes please", "yes that's right", "yes thats right", "that's right",
                 "thats right", "correct", "that's correct", "thats correct", "use that", "use it",
                 "use these words", "keep it", "keep that", "sounds good", "looks good", "perfect")),
    ("retry", ("try again", "no", "nope", "no try again", "say it again", "let me try again", "again",
               "redo", "redo that")),
    ("save", ("save them", "save", "that's all", "thats all", "that's it", "thats it", "done", "i'm done",
              "im done", "save my samples", "save these")),
)
MAX_COMMAND_WORDS = 7

# Talking about the interview itself, or to the assistant: never guessed into an answer.
ABOUT_THE_INTERVIEW = re.compile(
    r"^(?:did i|who are you|are you|tell me a|tell me about yourself|i don't understand|i dont understand|"
    r"i have two businesses|i changed my mind|that's wrong|thats wrong|no that's wrong|no thats wrong|"
    r"hey nova|hi nova|hello nova)\b", re.I)
# Asking the assistant a question. On "Who you reach" people say their customers' real questions
# out loud ("Should I run through it?"), so there a question is an answer, not a request.
A_QUESTION = re.compile(r"^(?:what|why|how|can you|could you|do you|what's|whats|where|should i|can i|is it)\b", re.I)
QUESTIONS_ARE_ANSWERS = ("audience", "voice_samples")


def _plain(text):
    return " ".join(re.findall(r"[a-z0-9']+", (text or "").lower().replace("’", "'")))


def understand(text, question_key=None):
    """What a transcript means on the page. Returns one of:
        {"kind": "command", "command": <name>}
        {"kind": "for_chat", "message": FOR_CHAT, "heard": text}
        {"kind": "secret", "message": SPOKEN_SECRET}             (the words are already gone)
        {"kind": "answer", "text": text}                          (shown for the person to check; never saved by speech)
    """
    if secrets_check.looks_secret(text):
        return {"kind": "secret", "message": SPOKEN_SECRET}
    plain = _plain(text)
    spoken_words = (text or "").split()                  # every word counts, in any alphabet
    if plain and len(spoken_words) <= MAX_COMMAND_WORDS:
        for name, phrases in COMMANDS:
            for phrase in phrases:
                if plain == phrase or plain in ("please " + phrase, phrase + " please"):
                    return {"kind": "command", "command": name}
    if ABOUT_THE_INTERVIEW.search(plain):
        return {"kind": "for_chat", "message": FOR_CHAT, "heard": text}
    asking = A_QUESTION.search(plain) or (text or "").rstrip().endswith("?")
    if asking and question_key not in QUESTIONS_ARE_ANSWERS:
        return {"kind": "for_chat", "message": FOR_CHAT, "heard": text}
    return {"kind": "answer", "text": text}
