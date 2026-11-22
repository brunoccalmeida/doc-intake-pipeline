"""Render the demo video from the pipeline's real output: replay only, no cost.

    uv run poe demo

Runs inside the demo image (``demo/Dockerfile``), from the mounted repository.
Takes the evidence (``demo/evidence.py``), draws the shots
(``demo/storyboard.py``) and streams them to ffmpeg, each still held for its
duration and crossfaded into the next, then lays each shot's committed
voice-over clip (``demo/narration.py``) under it. The video is refused above
the limits of where it is published (``demo/README.md``).
"""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from demo import evidence, make_receipt, narration, storyboard
from doc_intake.core.config import Settings

OUT = Path(".cache/demo")
VIDEO = OUT / "doc-intake-demo.mp4"
FPS = 25
FADE_SECONDS = 0.4  # each frame dissolves into the next over its last 0.4 s

# Upwork portfolio video: at most 60 s. GitHub attachment on a free plan: 10 MB.
MAX_SECONDS = 60.0
MAX_BYTES = 10_000_000

# Each spoken line starts this long after its shot does, once the picture has settled.
VOICE_LEAD = 0.3
# Loudness of the voice-over, by ffmpeg's loudnorm (EBU R128 measurement). -16 LUFS
# is a common target for speech on the web, not a published platform rule (#42).
LOUDNESS = -16.0
TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11.0
# Headroom kept under TRUE_PEAK when the peaks set the target: loudnorm's own
# true-peak reading of the output may differ a little from the first pass's.
PEAK_MARGIN = 0.5

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


def voice_starts(shot_seconds: Sequence[float], *, lead: float) -> list[float]:
    """When each shot's line starts: ``lead`` seconds into its shot."""
    starts: list[float] = []
    elapsed = 0.0
    for seconds in shot_seconds:
        starts.append(elapsed + lead)
        elapsed += seconds
    return starts


def loudnorm(measured: dict[str, str]) -> str:
    """loudnorm's second pass: one linear gain from what the first pass measured.

    With the measurements, loudnorm keeps the voice as it was approved and only
    scales it (https://ffmpeg.org/ffmpeg-filters.html#loudnorm). It falls back
    to compressing it on the fly if the gain would lift the peaks past
    TRUE_PEAK, or if the voice's loudness range is above LOUDNESS_RANGE. For
    the peaks, the target drops as far as they need: a quieter video, never a
    changed voice. A wider range is the render's error to report (``_voice_over``).
    """
    loudness, peak = float(measured["input_i"]), float(measured["input_tp"])
    target = min(LOUDNESS, TRUE_PEAK - PEAK_MARGIN - (peak - loudness))
    return ":".join(
        (
            f"loudnorm=I={target:.2f}",
            f"TP={TRUE_PEAK}",
            f"LRA={LOUDNESS_RANGE}",
            f"measured_I={measured['input_i']}",
            f"measured_TP={measured['input_tp']}",
            f"measured_LRA={measured['input_lra']}",
            f"measured_thresh={measured['input_thresh']}",
            "linear=true",
        )
    )


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


def stderr_of(command: Sequence[str]) -> str:
    """Run a command for what it prints on stderr; on failure, raise with that stderr.

    ffmpeg prints loudnorm's report on stderr, and on a failure the same
    stream holds the cause: a bare non-zero exit would hide it.
    """
    # A fixed tool with paths from this repository.
    done = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        tail = "\n".join(done.stderr.strip().splitlines()[-20:])
        raise RuntimeError(f"{command[0]} failed with exit code {done.returncode}:\n{tail}")
    return done.stderr


def _loudnorm_report(stderr: str) -> dict[str, str]:
    # loudnorm prints its JSON report last, after ffmpeg's own lines.
    report: dict[str, str] = json.loads(stderr[stderr.rindex("{") : stderr.rindex("}") + 1])
    return report


def _voice_over(shots: Sequence[storyboard.Shot], silent: Path, video: Path) -> None:
    """Lay each shot's committed clip under the video, at one loudness, as AAC."""
    clips = [narration.clip(shot.narration) for shot in shots]
    missing = [str(clip) for clip in clips if not clip.exists()]
    if missing:
        raise FileNotFoundError(f"no voice-over clip, run 'uv run poe demo-voice': {missing}")
    starts = voice_starts([shot.seconds for shot in shots], lead=VOICE_LEAD)
    delayed = "".join(
        f"[{index}:a]adelay=delays={round(start * 1000)}:all=1[v{index}];"
        for index, start in enumerate(starts)
    )
    mixed = "".join(f"[v{index}]" for index in range(len(clips)))
    mix = f"{delayed}{mixed}amix=inputs={len(clips)}:normalize=0"
    inputs = [argument for clip in clips for argument in ("-i", str(clip))]

    first = stderr_of(
        [
            "ffmpeg", "-hide_banner", "-nostats", *inputs,
            "-filter_complex", f"{mix},loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}"
            f":LRA={LOUDNESS_RANGE}:print_format=json",
            "-f", "null", "-",
        ]
    )  # fmt: skip
    second = stderr_of(
        [
            "ffmpeg", "-y", "-hide_banner", "-nostats", *inputs, "-i", str(silent),
            # loudnorm works at 192 kHz; back to 48 kHz, then silence to the video's end.
            "-filter_complex",
            f"{mix},{loudnorm(_loudnorm_report(first))}:print_format=json,"
            "aresample=48000,apad[voice]",
            "-map", f"{len(clips)}:v", "-map", "[voice]", "-shortest",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ac", "1",
            "-movflags", "+faststart", str(video),
        ]
    )  # fmt: skip
    report = _loudnorm_report(second)
    if report["normalization_type"] != "linear":  # dynamic mode compresses the voice
        raise RuntimeError(
            f"loudnorm fell back to {report['normalization_type']} normalization: the voice's "
            f"loudness range ({report['input_lra']} LU) is above {LOUDNESS_RANGE} LU, "
            f"or its peaks ({report['input_tp']} dBTP) leave no room under {TRUE_PEAK}"
        )


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
    encoded, silent = OUT / "encoded.mp4", OUT / "silent.mp4"
    _encode(shots, silent)
    _voice_over(shots, silent, encoded)
    silent.unlink()
    seconds, size = _seconds(encoded), encoded.stat().st_size
    print(f"{seconds:.1f} s, {size} bytes")
    check_limits(seconds, size)
    encoded.replace(VIDEO)
    print(f"written: {VIDEO}")


if __name__ == "__main__":
    main()
