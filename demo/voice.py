# /// script
# requires-python = "==3.13.*"
# dependencies = ["kokoro-onnx==0.6.1", "soundfile==0.14.0"]
#
# [tool.uv]
# # Only releases at least a week old when the lock was made, as Dependabot
# # waits for the main lock (.github/dependabot.yml).
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Speak one line of the demo's voice-over into a WAV file (#42, ``demo/README.md``).

Run by ``uv run poe demo-voice`` (``demo/narration.py``), never by hand: that
script names the file by the line's key and passes the voice. It runs on its
own Python and lock (``demo/voice.py.lock``), because Kokoro's package does not
install on this project's Python 3.14, and its phonemizer (espeak-ng, GPL-3.0)
stays out of the core's environment. The voice's files are downloaded once into
``.cache/voice`` and checked against the SHA-256 in ``demo/narration.py``.
"""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

import soundfile
from kokoro_onnx import Kokoro

CACHE = Path(".cache/voice")


def fetched(url: str, sha256: str) -> Path:
    path = CACHE / url.rsplit("/", 1)[1]
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        urllib.request.urlretrieve(url, partial)  # noqa: S310 (an https URL from this repository)
        partial.replace(path)
    found = hashlib.sha256(path.read_bytes()).hexdigest()
    if found != sha256:
        raise ValueError(f"{path} has SHA-256 {found}, expected {sha256}: delete it and retry")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--voice", required=True, help="demo/narration.py's Voice, as JSON")
    arguments = parser.parse_args()
    voice = json.loads(arguments.voice)

    model = Kokoro(
        str(fetched(voice["model_url"], voice["model_sha256"])),
        str(fetched(voice["voices_url"], voice["voices_sha256"])),
    )
    samples, rate = model.create(
        arguments.text, voice=voice["name"], speed=voice["speed"], lang=voice["lang"]
    )
    # 16-bit PCM, which Python's own wave module reads (demo/narration.py): no
    # float WAV, whose PEAK chunk stamps the time and changes the file each run.
    soundfile.write(arguments.out, samples, rate, subtype="PCM_16")


if __name__ == "__main__":
    main()
