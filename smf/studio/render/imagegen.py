"""imagegen.py - an image made for a brand by OpenAI's image model, with the person's own key.

    plan = imagegen.plan("a warm loaf on a floured board, morning light", shape="tall")
    print(plan["text"])                      # the price and the exact request, before anything
    rel = imagegen.generate(brand, plan["prompt"], shape="tall", confirm=True)

THREE RULES, enforced here so no skill can forget them
  1. The cost is said first, and so is the request. `plan()` gives both, and spends nothing.
  2. Nothing is spent without a yes. `generate()` refuses unless it is called with
     confirm=True, and the refusal carries the plan so it can be shown. Every try is a new
     charge, so every try needs its own yes.
  3. A key is never shown. It travels in a header, and every message is scrubbed of it.

What the person asks for is what is requested: a scene, an object, a texture, a person. The
image is saved in the brand's own folder (Brand/brand-kit/photos/generated/) with a record of
the request, the model, the date and what it cost, so it is never mistaken for a photograph the
brand took. `spent()` adds those records up.

The request text leaves this computer and goes to OpenAI. Nothing else about the brand is sent.

PRICES are OpenAI's own per-image figures for the model below, read from its model page on the
date given. Only a model with a price in this table can be used, so the cost can always be
said first. When OpenAI changes its prices or its models, this table is the one place to update.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from smf import keys
from smf.brands import BrandError
from smf.studio.render import library

ENDPOINT = "https://api.openai.com/v1/images/generations"
KEY_NAME = "OPENAI_API_KEY"
DEFAULT_MODEL = "gpt-image-1.5"
PRICES_CHECKED = "2026-10-09"
PRICES_SOURCE = "https://developers.openai.com/api/docs/models/gpt-image-1.5"
SHAPES = {"square": "1024x1024", "tall": "1024x1536", "wide": "1536x1024"}
QUALITIES = ("low", "medium", "high")
PRICES_USD = {                     # model -> quality -> size -> dollars for one image
    "gpt-image-1.5": {
        "low": {"1024x1024": 0.009, "1024x1536": 0.013, "1536x1024": 0.013},
        "medium": {"1024x1024": 0.034, "1024x1536": 0.05, "1536x1024": 0.05},
        "high": {"1024x1024": 0.133, "1024x1536": 0.20, "1536x1024": 0.20},
    },
}
MAX_PROMPT = 4000
TIMEOUT_SECS = 240


class ImageError(BrandError):
    """An image could not be made. The message is for the person, and never holds a key."""


class NotConfirmed(ImageError):
    """generate() was called without confirm=True. Carries the plan so it can be shown."""

    def __init__(self, plan):
        ImageError.__init__(self, "Nothing was made and nothing was spent. %s Say yes to go ahead." % plan["text"])
        self.plan = plan


def _money(amount):
    cents = amount * 100.0
    return "about %s cent%s" % (("%.1f" % cents).rstrip("0").rstrip("."), "" if cents == 1 else "s") \
        if amount < 1 else "about $%.2f" % amount


def plan(prompt, shape="tall", quality="medium", model=DEFAULT_MODEL):
    """What one try would ask for and what it would cost. Spends nothing and sends nothing."""
    text = " ".join(str(prompt or "").split())
    if not text:
        raise ImageError("Say what the image should show.")
    if len(text) > MAX_PROMPT:
        raise ImageError("That description is very long (over %d characters). Shorten it." % MAX_PROMPT)
    if shape not in SHAPES:
        raise ImageError("'%s' is not a shape. Choose: %s." % (shape, ", ".join(SHAPES)))
    if quality not in QUALITIES:
        raise ImageError("'%s' is not a quality. Choose: %s." % (quality, ", ".join(QUALITIES)))
    if model not in PRICES_USD:
        raise ImageError("The price of '%s' is not recorded here, so its cost could not be said first. Models "
                         "with a recorded price: %s." % (model, ", ".join(PRICES_USD)))
    size = SHAPES[shape]
    price = PRICES_USD[model][quality][size]
    return {"prompt": text, "shape": shape, "size": size, "quality": quality, "model": model, "price_usd": price,
            "text": ("One %s image at %s quality costs %s on your OpenAI account (OpenAI's price as of %s). "
                     "This is what would be sent to OpenAI: \"%s\"."
                     % (shape, quality, _money(price), PRICES_CHECKED, text))}


def spent(brand):
    """(how many generated images this brand has, what they cost in dollars), from their records."""
    count, total = 0, 0.0
    for row in library.list_images(brand):
        if row["source"] == "generated":
            record = library.read_record(Path(brand.home) / row["image"])
            count += 1
            total += float(record.get("cost_usd") or 0)
    return count, round(total, 4)


def _scrub(text, key):
    text = keys.redact(str(text))
    return text.replace(key, "[%s hidden]" % KEY_NAME) if key and len(key) >= 6 else text


def _explain(status, body, key):
    message = ""
    try:
        message = str((json.loads(body).get("error") or {}).get("message") or "")
    except (ValueError, AttributeError):
        pass
    message = _scrub(message, key)[:300]
    if status == 401:
        return "OpenAI did not accept the key. Open the keys file, paste the OpenAI key again on one line, save, and try again."
    if status == 429:
        return ("OpenAI says the account is out of credit or is being used too fast. Check the billing page of the "
                "OpenAI account, then try again. (%s)" % message if message else
                "OpenAI says the account is out of credit or is being used too fast. Check its billing page.")
    if status == 400:
        return "OpenAI turned this request down: %s Change the description and try again." % (message or "no reason given.")
    return "OpenAI could not make the image just now (error %s). %s" % (status, message or "Try again in a minute.")


def generate(brand, prompt, name=None, shape="tall", quality="medium", model=DEFAULT_MODEL, shows_person=None,
             confirm=False, opener=None):
    """Make one image and save it in the brand's folder. Returns its path relative to the brand's
    folder (use it in a design as brand:<that path>). Raises NotConfirmed, carrying the plan,
    unless confirm is True."""
    todo = plan(prompt, shape, quality, model)
    if confirm is not True:                                  # rule 2: nothing is spent without a yes
        raise NotConfirmed(todo)
    keys.load()
    key = os.environ.get(KEY_NAME, "").strip()
    if not key:
        raise ImageError("There is no OpenAI key yet, so nothing was made or spent. Making images uses your own "
                         "OpenAI account (%s for one like this). Add a line %s=<your key> to the keys file "
                         "yourself; never paste a key into the chat." % (_money(todo["price_usd"]), KEY_NAME))
    body = json.dumps({"model": todo["model"], "prompt": todo["prompt"], "size": todo["size"],
                       "quality": todo["quality"], "n": 1}).encode("utf-8")
    request = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT_SECS) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ImageError(_explain(e.code, e.read().decode("utf-8", "replace"), key))
    except (urllib.error.URLError, OSError, ValueError):
        raise ImageError("OpenAI could not be reached, or its answer could not be read. It is not certain whether "
                         "this try was charged; check the usage page of the OpenAI account before trying again.")
    try:
        picture = base64.b64decode(answer["data"][0]["b64_json"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise ImageError("OpenAI answered without an image. This try may have been charged; check the usage page "
                         "of the OpenAI account before trying again.")
    with tempfile.TemporaryDirectory(prefix="smf-image-") as tmp:
        scratch = Path(tmp) / "image.png"
        scratch.write_bytes(picture)
        try:
            from PIL import Image
            with Image.open(str(scratch)) as im:
                im.verify()
        except Exception:
            raise ImageError("OpenAI sent something that is not a picture. This try may have been charged; check "
                             "the usage page of the OpenAI account.")
        return library.file_image(
            brand, scratch, "generated", where_from=todo["prompt"], licence="Made for this brand with its own OpenAI account",
            shows_person=shows_person, name=name or todo["prompt"][:40],
            extra={"model": todo["model"], "quality": todo["quality"], "size": todo["size"],
                   "cost_usd": todo["price_usd"]})
