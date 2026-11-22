"""Render the demo video from the pipeline's real output: replay only, no cost.

    uv run poe demo

Runs inside the demo image (``demo/Dockerfile``), from the mounted repository.
Takes the evidence (``demo/evidence.py``), draws the shots
(``demo/storyboard.py``) and streams them to ffmpeg, each still held for its
duration and crossfaded into the next. The video is refused above the limits
of where it is published (``demo/README.md``).
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from demo import evidence, make_receipt, storyboard
from doc_intake.core.config import Settings

OUT = Path(".cache/demo")
VIDEO = OUT / "doc-intake-demo.mp4"
FPS = 25
FADE_SECONDS = 0.4  # each frame dissolves into the next over its last 0.4 s

# Upwork portfolio video: at most 60 s. GitHub attachment on a free plan: 10 MB.
MAX_SECONDS = 60.0
MAX_BYTES = 10_000_000

type Tick = tuple[int, int, float]  # frame shown, frame fading in, how far in (0 to 1)


def timeline(durations: Sequence[float], *, fps: int, fade: float) -> list[Tick]:
    """What each video frame shows: one still, or two in a crossfade.

    The fade happens inside the outgoing still's own time, so the video's
    length is the sum of the durations.
    """
    ends: list[float] = []
    total = 0.0
    for seconds in durations:
        total += seconds
        ends.append(total)
    ticks: list[Tick] = []
    current = 0
    for index in range(round(total * fps)):
        now = index / fps
        while now >= ends[current]:
            current += 1
        into_fade = now - (ends[current] - fade)
        if current + 1 < len(ends) and into_fade > 0:
            ticks.append((current, current + 1, into_fade / fade))
        else:
            ticks.append((current, current, 0.0))
    return ticks


def dissolve(
    outgoing: Image.Image, incoming: Image.Image, amount: float, *, via: Image.Image | None = None
) -> Image.Image:
    """``amount`` of the way from one still to the next.

    ``via`` makes it a dip: out to that picture over the first half, in from it
    over the second. Between shots the headline changes, and a straight
    dissolve would show both headlines on top of each other.
    """
    if via is None:
        return Image.blend(outgoing, incoming, amount)
    if amount <= 0.5:
        return Image.blend(outgoing, via, amount * 2)
    return Image.blend(via, incoming, (amount - 0.5) * 2)


def check_limits(seconds: float, size: int) -> None:
    """Refuse a video too long or too large for where it is published."""
    if seconds > MAX_SECONDS:
        raise ValueError(f"the video runs {seconds:.1f} s, above the {MAX_SECONDS:.0f} s limit")
    if size > MAX_BYTES:
        raise ValueError(f"the video has {size} bytes, above the {MAX_BYTES} limit")


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


def _encode(shots: Sequence[storyboard.Shot], video: Path) -> None:
    """Stream every video frame to ffmpeg as raw RGB: no intermediate files."""
    frames = [frame for shot in shots for frame in shot.frames]
    # The index of each shot's first frame: a fade into it is a dip.
    starts: set[int] = set()
    count = 0
    for shot in shots:
        starts.add(count)
        count += len(shot.frames)
    background = Image.new("RGB", (storyboard.WIDTH, storyboard.HEIGHT), storyboard.BACKGROUND)
    # A fixed tool with a path from this repository.
    encoder = subprocess.Popen(  # noqa: S603
        [  # noqa: S607
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{storyboard.WIDTH}x{storyboard.HEIGHT}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(video),
        ],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    if encoder.stdin is None:  # stdin=PIPE always gives one
        raise RuntimeError("ffmpeg started without a stdin")
    held = [frame.image.tobytes() for frame in frames]
    with encoder.stdin as pipe:
        for shown, fading_in, amount in timeline(
            [frame.seconds for frame in frames], fps=FPS, fade=FADE_SECONDS
        ):
            if amount == 0:
                pipe.write(held[shown])
            else:
                via = background if fading_in in starts else None
                blended = dissolve(frames[shown].image, frames[fading_in].image, amount, via=via)
                pipe.write(blended.tobytes())
    if encoder.wait() != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {encoder.returncode}")


def main() -> None:
    # The provider and model the recordings were made with, so no .env or
    # shell setting changes the keys they are looked up by.
    settings = Settings(provider="claude", claude_model="claude-opus-5-5")
    shots = storyboard.storyboard(
        evidence.receipt_evidence(make_receipt.RECEIPT.path, settings),
        evidence.receipt_evidence(make_receipt.REVIEW.path, settings),
    )
    stills = OUT / "frames"
    stills.mkdir(parents=True, exist_ok=True)
    for old in stills.glob("*.png"):
        old.unlink()  # an earlier render's stills no longer match
    for number, shot in enumerate(shots, 1):
        for index, frame in enumerate(shot.frames, 1):
            frame.image.save(stills / f"{number}-{index}.png")  # for checking by eye
        print(f"shot {number}: {shot.seconds:.1f} s")

    VIDEO.unlink(missing_ok=True)  # an earlier render no longer matches the evidence
    # Encoded beside the video and moved into place only within the limits, so
    # the path to publish never holds a refused video.
    encoded = OUT / "encoded.mp4"
    _encode(shots, encoded)
    seconds, size = _seconds(encoded), encoded.stat().st_size
    print(f"{seconds:.1f} s, {size} bytes")
    check_limits(seconds, size)
    encoded.replace(VIDEO)
    print(f"written: {VIDEO}")


if __name__ == "__main__":
    main()
