"""Draw the demo's receipt: a fictional shop, printed faded, with specks like a scan.

    uv run python -m demo.make_receipt

Writes ``demo/receipt.png``, which is committed: the demo replays a recorded
answer keyed by the OCR text and the image bytes (``evals.recording``), and a
re-run on another Pillow or platform may differ by a pixel. Run this only to
change the receipt, then record its answer again (``demo/README.md``).

Everything printed is invented, so the image and the model's answer about it
can be public, unlike the SROIE receipts (``docs/DATA.md``). No currency is
printed, on purpose: the pack must return null with a reason, not guess one
from the country.
"""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RECEIPT_PATH = Path(__file__).with_name("receipt.png")

# One string per printed line, amounts set apart with spaces. Right-aligned
# amounts and dot leaders were tried: OCR then read the amounts as a second
# column, or misread the words next to the dots.
LINES = (
    "FICTIONAL FIG BAKERY",
    "12 Example Street",
    "Sample Town",
    "",
    "Receipt No: 004521",
    "Date: 14/11/2026   09:42",
    "",
    "2 x Sourdough loaf      13.00",
    "1 x Fig tart             6.50",
    "1 x Long black           3.90",
    "",
    "TOTAL                   23.40",
    "Paid by card            23.40",
    "",
    "Thank you, come again!",
)


def draw_receipt(seed: int = 23) -> Image.Image:
    """The receipt, deterministic for a given Pillow: same seed, same pixels."""
    rng = random.Random(seed)  # noqa: S311 - specks for a picture, not security
    font = ImageFont.load_default(size=30)
    page = Image.new("L", (760, 900), color=236)  # off-white thermal paper
    draw = ImageDraw.Draw(page)
    for row, line in enumerate(LINES):
        # Faded print: grey ink whose darkness drifts down the receipt.
        ink = 95 + rng.randrange(0, 40)
        draw.text((70, 60 + row * 52), line, fill=ink, font=font)
    for _ in range(1500):
        x, y = rng.randrange(page.width), rng.randrange(page.height)
        draw.point((x, y), fill=rng.randrange(120, 200))
    return page.filter(ImageFilter.GaussianBlur(0.8)).rotate(
        1.2, resample=Image.Resampling.BICUBIC, fillcolor=236
    )


def main() -> None:
    draw_receipt().save(RECEIPT_PATH)
    print(f"wrote {RECEIPT_PATH}")


if __name__ == "__main__":
    main()
