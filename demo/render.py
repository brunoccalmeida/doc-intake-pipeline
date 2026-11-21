"""Render the demo video from the pipeline's real output: replay only, no cost.

    uv run poe demo

Runs inside the demo image (``demo/Dockerfile``), from the mounted repository.
Takes the evidence (``demo/evidence.py``), draws the shots
(``demo/storyboard.py``), turns each still frame into a clip for its duration
and joins the clips. The joined video is refused above the limits of where it
is published (``demo/README.md``).
"""

import subprocess
from pathlib import Path

from core.config import Settings
from demo import evidence, make_receipt, storyboard

OUT = Path(".cache/demo")
VIDEO = OUT / "doc-intake-demo.mp4"
FRAME_RATE = "25"

# Upwork portfolio video: at most 60 s. GitHub attachment on a free plan: 10 MB.
MAX_SECONDS = 60.0
MAX_BYTES = 10_000_000


def check_limits(seconds: float, size: int) -> None:
    """Refuse a video too long or too large for where it is published."""
    if seconds > MAX_SECONDS:
        raise ValueError(f"the video runs {seconds:.1f} s, above the {MAX_SECONDS:.0f} s limit")
    if size > MAX_BYTES:
        raise ValueError(f"the video has {size} bytes, above the {MAX_BYTES} limit")


def _run(*args: str) -> None:
    # A fixed tool (ffmpeg) with paths from this repository.
    subprocess.run(args, check=True)  # noqa: S603


def _seconds(video: Path) -> float:
    # A fixed tool with a path from this repository; ffprobe comes with ffmpeg.
    shown = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout  # fmt: skip
    return float(shown)


def main() -> None:
    # The provider and model the recordings were made with, so no .env or
    # shell setting changes the keys they are looked up by.
    settings = Settings(provider="claude", claude_model="claude-opus-5-5")
    shots = storyboard.storyboard(
        evidence.receipt_evidence(make_receipt.RECEIPT.path, settings),
        evidence.receipt_evidence(make_receipt.REVIEW.path, settings),
        evidence.gate_facts(settings),
    )
    parts = OUT / "frames"
    parts.mkdir(parents=True, exist_ok=True)
    VIDEO.unlink(missing_ok=True)  # an earlier render no longer matches the evidence

    clips: list[str] = []
    for number, shot in enumerate(shots, 1):
        for index, frame in enumerate(shot.frames, 1):
            still = parts / f"{number}-{index}.png"
            frame.image.save(still)
            clip = still.with_suffix(".mp4")
            # A still held for its duration; the same codec, size and rate for
            # every clip, so they join without re-encoding.
            _run(
                "ffmpeg", "-y", "-loglevel", "error",
                "-loop", "1", "-framerate", FRAME_RATE, "-t", f"{frame.seconds}", "-i", str(still),
                "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                "-r", FRAME_RATE, str(clip),
            )  # fmt: skip
            clips.append(clip.name)
        print(f"shot {number}: {shot.seconds:.1f} s")

    listing = parts / "clips.txt"
    listing.write_text("".join(f"file '{clip}'\n" for clip in clips), encoding="utf-8")
    # Joined beside the video and moved into place only within the limits, so
    # the path to publish never holds a refused video.
    joined = parts / "joined.mp4"
    _run(
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-i", str(listing),
        "-c", "copy", "-movflags", "+faststart", str(joined),
    )  # fmt: skip
    seconds, size = _seconds(joined), joined.stat().st_size
    print(f"{seconds:.1f} s, {size} bytes")
    check_limits(seconds, size)
    joined.replace(VIDEO)
    print(f"written: {VIDEO}")


if __name__ == "__main__":
    main()
