"""Draw the demo's receipts: fictional shops, printed faded, with specks like a scan.

    uv run python -m demo.make_receipt

Writes the PNGs in ``RECEIPTS``, which are committed: the demo replays recorded
answers keyed by the OCR text and the image bytes (``evals.recording``), and a
re-run on another Pillow or platform may differ by a pixel
(``tests/test_demo.py`` checks the committed ones still match). Run this only to
change a receipt, then record its answer again (``demo/README.md``).

Everything printed is invented, so the images and the model's answers about
them can be public, unlike the SROIE receipts (``docs/DATA.md``). No currency is
printed, on purpose: the pack must return null with a reason, not guess one
from the country.
"""

import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEMO = Path(__file__).parent


@dataclass(frozen=True, slots=True)
class Receipt:
    """One receipt: what is printed, and how its print and specks fall."""

    path: Path
    # One string per printed line, amounts set apart with spaces. Right-aligned
    # amounts and dot leaders were tried: OCR then read the amounts as a second
    # column, or misread the words next to the dots.
    lines: tuple[str, ...]
    seed: int
    height: int
    # Rows printed so faint that OCR drops them, while a person (and the model,
    # which sees the image) can still read them.
    faded: frozenset[int] = frozenset()
    width: int = 760


# Shots 1, 3, 4 and 6: every value is in the OCR text, so code checks every quote.
RECEIPT = Receipt(
    path=DEMO / "receipt.png",
    lines=(
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
    ),
    seed=23,
    height=900,
)

# Shot 5: the total and the payment line are faded out of OCR's reach, so the
# total can only be read from the image, and goes to a person (D14).
REVIEW = Receipt(
    path=DEMO / "receipt-review.png",
    lines=(
        "SAMPLE STREET CAFE",
        "7 Placeholder Road",
        "Sample Town",
        "",
        "Receipt No: 001187",
        "Date: 18/11/2026   13:05",
        "",
        "1 x Flat white           4.20",
        "1 x Banana bread         5.80",
        "",
        "TOTAL                   10.00",
        "Paid by card            10.00",
        "",
        "Thank you, come again!",
    ),
    seed=31,
    height=800,
    faded=frozenset({10, 11}),
)

RECEIPTS = (RECEIPT, REVIEW)

# Measured on REVIEW (#45): at 180 OCR still reads the total, at 190 it does not.
_FADED_INK = 190


def draw_receipt(receipt: Receipt) -> Image.Image:
    """The receipt, deterministic for a given Pillow: same seed, same pixels."""
    rng = random.Random(receipt.seed)  # noqa: S311 - specks for a picture, not security
    font = ImageFont.load_default(size=30)
    page = Image.new("L", (receipt.width, receipt.height), color=236)  # off-white thermal paper
    draw = ImageDraw.Draw(page)
    for row, line in enumerate(receipt.lines):
        # Faded print: grey ink whose darkness drifts down the receipt. Drawn
        # for every row, faded or not, so the specks below stay the same.
        ink = 95 + rng.randrange(0, 40)
        draw.text(
            (70, 60 + row * 52), line, fill=_FADED_INK if row in receipt.faded else ink, font=font
        )
    for _ in range(1500):
        x, y = rng.randrange(page.width), rng.randrange(page.height)
        draw.point((x, y), fill=rng.randrange(120, 200))
    return page.filter(ImageFilter.GaussianBlur(0.8)).rotate(
        1.2, resample=Image.Resampling.BICUBIC, fillcolor=236
    )


def main() -> None:
    for receipt in RECEIPTS:
        draw_receipt(receipt).save(receipt.path)
        print(f"wrote {receipt.path}")


if __name__ == "__main__":
    main()
