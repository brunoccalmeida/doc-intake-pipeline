"""Render the demo video: one VHS tape per shot, its caption burned in, then joined.

    uv run poe demo

Runs inside the demo image (``demo/Dockerfile``), from the mounted repository.
Each shot in ``demo/shots`` is a VHS tape with one ``# Caption:`` line. VHS has
no caption command (v0.12.1), so ffmpeg burns the caption for the whole shot in
a band below the terminal: tied to the shot, not to a clock, it cannot drift
out of sync when a command takes longer. The joined video is refused above the
limits of where it is published (``demo/README.md``).
"""

import re
import subprocess
from pathlib import Path

SHOTS = Path("demo/shots")
OUT = Path(".cache/demo")
VIDEO = OUT / "doc-intake-demo.mp4"

# The frame: the terminal (Set Width/Height in demo/setup.tape) on top, the
# caption band below it.
WIDTH = 1920
HEIGHT = 1080
TERMINAL_HEIGHT = 880
BAND_COLOR = "0x11111b"  # Catppuccin Mocha "crust", under the terminal's theme
# An image a shot shows (# Image:) is drawn at its own pixels, not as terminal
# characters, centred over the terminal.
IMAGE_HEIGHT = 800

# Upwork portfolio video: at most 60 s. GitHub attachment on a free plan: 10 MB.
MAX_SECONDS = 60.0
MAX_BYTES = 10_000_000

_CAPTION = re.compile(r"# Caption: (.+)")
_IMAGE = re.compile(r"# Image: (.+)")
_SHOT = re.compile(r"(\d+)-.+\.tape")
# Characters libass reads as markup ({\b1}, \N): a caption is plain text.
_ASS_MARKUP = re.compile(r"[{}\\]")


def shot_tapes(directory: Path) -> list[Path]:
    """The shot tapes in the order of the number their names start with."""
    tapes = sorted(directory.glob("*.tape"))
    unnumbered = [tape.name for tape in tapes if not _SHOT.fullmatch(tape.name)]
    if unnumbered:
        raise ValueError(f"shot tapes must be named <number>-<name>.tape: {unnumbered}")
    return sorted(tapes, key=lambda tape: int(tape.name.split("-", 1)[0]))


def caption(tape: Path) -> str:
    """The one caption of a shot, as plain text."""
    lines = tape.read_text(encoding="utf-8").splitlines()
    found = [match.group(1).strip() for line in lines if (match := _CAPTION.fullmatch(line))]
    if not found:
        raise ValueError(f"{tape}: no caption (a '# Caption: ...' line)")
    if len(found) > 1:
        raise ValueError(f"{tape}: {len(found)} captions, one per shot")
    if _ASS_MARKUP.search(found[0]):
        raise ValueError(f"{tape}: ASS markup in the caption: {found[0]}")
    return found[0]


def image(tape: Path) -> Path | None:
    """The image a shot shows over the terminal, if it names one."""
    lines = tape.read_text(encoding="utf-8").splitlines()
    found = [match.group(1).strip() for line in lines if (match := _IMAGE.fullmatch(line))]
    if len(found) > 1:
        raise ValueError(f"{tape}: {len(found)} images, at most one per shot")
    return Path(found[0]) if found else None


def video_filter(subtitle: Path, *, image: bool) -> str:
    """ffmpeg's filter graph for a shot: the band, the image if any, the caption."""
    framed = f"[0:v]pad={WIDTH}:{HEIGHT}:0:0:color={BAND_COLOR}"
    caption = f"ass={subtitle.as_posix()}"
    if not image:
        return f"{framed},{caption}"
    return (
        f"{framed}[framed];[1:v]scale=-1:{IMAGE_HEIGHT}[image];"
        f"[framed][image]overlay=(W-w)/2:({TERMINAL_HEIGHT}-h)/2,{caption}"
    )


def ass_script(text: str) -> str:
    """An ASS subtitle that shows ``text`` for the whole shot, centred in the band."""
    # ASS colours are &HAABBGGRR: the theme's text colour (#cdd6f4).
    return f"""\
[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, \
BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,46,&H00F4D6CD,&H00F4D6CD,&H00000000,&H00000000,\
-1,0,0,0,100,100,0,0,1,0,0,2,90,90,45,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,9:59:59.99,Caption,,0,0,0,,{text}
"""


def check_limits(seconds: float, size: int) -> None:
    """Refuse a video too long or too large for where it is published."""
    if seconds > MAX_SECONDS:
        raise ValueError(f"the video runs {seconds:.1f} s, above the {MAX_SECONDS:.0f} s limit")
    if size > MAX_BYTES:
        raise ValueError(f"the video has {size} bytes, above the {MAX_BYTES} limit")


def _run(*args: str) -> str:
    # Fixed tools (vhs, ffmpeg, ffprobe) with paths from this repository.
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout  # noqa: S603


def _seconds(video: Path) -> float:
    shown = _run(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)
    )
    return float(shown)


def main() -> None:
    tapes = shot_tapes(SHOTS)
    captions = {tape: caption(tape) for tape in tapes}  # every caption checked before rendering
    parts = OUT / "shots"
    parts.mkdir(parents=True, exist_ok=True)

    for tape in tapes:
        raw = parts / f"{tape.stem}.raw.mp4"
        _run("vhs", "--quiet", "--output", str(raw), str(tape))
        subtitle = parts / f"{tape.stem}.ass"
        subtitle.write_text(ass_script(captions[tape]), encoding="utf-8")
        shown = image(tape)
        inputs = ["-i", str(raw), *(["-i", str(shown)] if shown else [])]
        # Same codec, size and rate for every shot, so they join without re-encoding.
        _run(
            "ffmpeg", "-y", "-loglevel", "error", *inputs,
            "-filter_complex", video_filter(subtitle, image=shown is not None),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "50",
            str(parts / f"{tape.stem}.mp4"),
        )  # fmt: skip
        print(f"{tape.name}: {_seconds(parts / f'{tape.stem}.mp4'):.1f} s")

    listing = parts / "shots.txt"
    listing.write_text("".join(f"file '{tape.stem}.mp4'\n" for tape in tapes), encoding="utf-8")
    _run(
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-i", str(listing),
        "-c", "copy", "-movflags", "+faststart", str(VIDEO),
    )  # fmt: skip
    seconds, size = _seconds(VIDEO), VIDEO.stat().st_size
    print(f"{VIDEO}: {seconds:.1f} s, {size} bytes")
    check_limits(seconds, size)


if __name__ == "__main__":
    main()
