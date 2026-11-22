"""The demo's voice-over: one committed clip per spoken line (#42, ``demo/README.md``).

    uv run poe demo-voice

Generates the clip of every line in ``demo/storyboard.py`` that has none yet,
by running ``demo/voice.py`` on its own locked Python (Kokoro does not install
on this project's), and lists the clips no line uses any more. The render only
reads the clips: the voice gives no bit-for-bit guarantee across machines, so
generating it on every render would change the video from one machine to the
next.

A clip is named by a key over its words and every setting of the voice, so a
changed line or voice can never pick up an old clip.
"""

import hashlib
import json
import subprocess
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from demo import storyboard

CLIPS = Path("demo/voice-clips")
SPEAKER = Path("demo/voice.py")  # the script that speaks, on its own Python


@dataclass(frozen=True, slots=True)
class Voice:
    """Everything that shapes the sound of a line, besides its words."""

    package: str  # pinned in demo/voice.py and its lock, demo/voice.py.lock
    model_url: str
    model_sha256: str
    voices_url: str
    voices_sha256: str
    name: str
    speed: float
    lang: str


# Kokoro-82M v1.0 (Apache-2.0 weights, hexgrad/Kokoro-82M on Hugging Face) as
# ONNX, from kokoro-onnx's release. The release publishes no checksum: these are
# the files the owner heard and approved (#42), so the script refuses any other.
_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
VOICE = Voice(
    package="kokoro-onnx==0.6.1",
    model_url=f"{_RELEASE}/kokoro-v1.0.onnx",
    model_sha256="7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    voices_url=f"{_RELEASE}/voices-v1.0.bin",
    voices_sha256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    name="af_heart",  # American English, Kokoro's top-graded voice (VOICES.md)
    speed=1.0,
    lang="en-us",
)


def key(text: str, voice: Voice = VOICE) -> str:
    settings = json.dumps({"text": text, **asdict(voice)}, sort_keys=True)
    return hashlib.sha256(settings.encode()).hexdigest()[:16]


def clip(text: str, voice: Voice = VOICE) -> Path:
    return CLIPS / f"{key(text, voice)}.wav"


def seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def main() -> None:
    CLIPS.mkdir(parents=True, exist_ok=True)
    wanted = {clip(line.narration) for line in storyboard.SCRIPT}
    for line in storyboard.SCRIPT:
        path = clip(line.narration)
        if path.exists():
            print(f"kept      {path.name}  {line.narration}")
            continue
        # A fixed tool with arguments from this repository.
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "uv", "run", "--locked", "--script", str(SPEAKER),
                "--text", line.narration, "--out", str(path),
                "--voice", json.dumps(asdict(VOICE)),
            ],
            check=True,
        )  # fmt: skip
        print(f"generated {path.name}  {seconds(path):.2f} s  {line.narration}")
    for orphan in sorted(set(CLIPS.glob("*.wav")) - wanted):
        print(f"unused    {orphan.name}: delete it (no line speaks it any more)")


if __name__ == "__main__":
    main()
