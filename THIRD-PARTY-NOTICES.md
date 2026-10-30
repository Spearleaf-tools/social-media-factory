# Third-party notices

Social Media Factory is covered by its own [LICENSE](LICENSE). It also uses other people's work.
This page says what, under which licence, and whether it is **inside this repository** or
**downloaded by your computer during setup** from its official source.

## Inside this repository

Only four third-party files ship in the repository: three fonts and one small face-finder
model, each with its licence text in the same folder. Every binary file in the repository is listed with its checksum and origin in
[`BINARIES.lock`](BINARIES.lock).

| Font | Copyright | Licence | Where |
|---|---|---|---|
| Inter | Copyright 2020 The Inter Project Authors (https://github.com/rsms/inter) | SIL Open Font License 1.1 | `smf/studio/render/fonts/inter/` |
| Geist Mono | Copyright 2024 The Geist Project Authors (https://github.com/vercel/geist-font.git) | SIL Open Font License 1.1 | `smf/studio/render/fonts/geist-mono/` |
| Anton | Copyright 2020 The Anton Project Authors (https://github.com/googlefonts/AntonFont.git) | SIL Open Font License 1.1 | `smf/studio/render/fonts/anton/` |

The fonts are unmodified. Under the OFL they may be bundled and redistributed with software,
including commercially, provided they are not sold by themselves and their licence text stays
with them.

| Model | Copyright | Licence | Where |
|---|---|---|---|
| YuNet face detection (`face_detection_yunet_2023mar.onnx`), from the OpenCV Zoo | Copyright (c) 2020 Shiqi Yu | MIT | `smf/video/models/` |

The model is unmodified. It is used on your own computer only, to find where the speaker is in a
frame so that a tall or square version of a wide video is centred on them. It identifies nobody,
stores nothing, and no picture leaves your computer.

## Downloaded by your computer during setup (not part of this repository)

`factory.py setup` installs these from their official sources into this folder or your user
cache. The exact versions are pinned in `requirements/*.txt`. Each is governed by its own
licence, which you accept by installing it.

| What | Used for | Licence |
|---|---|---|
| uv (Astral) | Installing a private Python and the packages | MIT or Apache-2.0 |
| CPython | Running the tools | PSF License |
| Pillow | Image handling | MIT-CMU (HPND) |
| NumPy, SciPy | Arithmetic for images and audio | BSD-3-Clause |
| Flask and its dependencies | The local review page | BSD-3-Clause |
| Requests, tzdata | Web requests, time zones | Apache-2.0 |
| Markdown | Turning text into pages | BSD-3-Clause |
| Playwright for Python | Driving the page renderer | Apache-2.0 |
| Chromium (headless shell) | Drawing carousels, cards, thumbnails and decks | BSD-3-Clause and others; see the Chromium project |
| faster-whisper, CTranslate2 | Speech to text on your computer, for checking cuts | MIT |
| Whisper `base` model weights | The speech model faster-whisper loads | MIT (OpenAI) |
| OpenCV (headless) | Finding faces for framing | Apache-2.0 |
| static-ffmpeg | Fetches FFmpeg and FFprobe for your system | MIT (the wrapper) |
| FFmpeg and FFprobe binaries | Cutting, joining and encoding video | **GPL** builds (they include x264). They are downloaded to your computer by static-ffmpeg; this repository does not contain or redistribute them. See https://ffmpeg.org/legal.html |
| yt-dlp | Fetching one video you point it at, for research | The Unlicense |

## Outside services

The Social Media Factory can talk to Metricool, ElevenLabs and Apify **only with keys you
provide**, under the terms you agreed with each of them. You are responsible for their fees and
for following their terms and the terms of any site you research. Nothing in this repository
contains a key or an account.

## Knowledge files

The rulebooks in `playbooks/` are original writing. Platform facts in them are restated from
public sources as of the date at the top of each file, and every example in them is invented.
If you believe anything in this repository reproduces your work, open an issue and it will be
looked at promptly.
