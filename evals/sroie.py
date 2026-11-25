"""SROIE golden set: which receipts, and how their ground truth becomes a ``Receipt``.

SROIE has no published licence (``docs/DATA.md``), so the repository keeps
only what is ours: the selection rule, the receipt ids with the SHA-256 of
each source file, and our own currency annotation. The images and SROIE's
values are downloaded and converted locally by ``scripts/fetch_golden.py``.

SROIE's ground truth is a transcription of the printed text, so it is also the
citation: the value is normalized (ISO date, ``Decimal``) and the quote keeps
the text as annotated. Every receipt is a single page. The amounts SROIE does
not annotate (net, tax, rounding) are our own reading, kept private (#66).
"""

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from doc_intake.core.result import Citation, ExtractedField, StrictModel
from doc_intake.packs.receipt import CurrencyCode, Money, Receipt, SignedMoney

GOLDEN_DIR = Path(__file__).parent / "golden"
MANIFEST_PATH = GOLDEN_DIR / "sroie.json"
# Every id of the mirror's test split, so the selection can be re-run offline.
TEST_IDS_PATH = GOLDEN_DIR / "sroie-test-ids.txt"

type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class GoldenEntry(StrictModel, frozen=True):
    """One selected receipt: its SROIE id, pinned files and our currency annotation."""

    id: Annotated[str, Field(pattern=r"^X\d{11}$")]
    image_sha256: Sha256
    entities_sha256: Sha256
    # SROIE does not annotate currency; this is read by us from the image.
    currency: ExtractedField[CurrencyCode]


class Amounts(StrictModel, frozen=True):
    """Our reading of one receipt's amounts, which SROIE does not annotate (#66).

    Read by us from the image, like the currency, but it quotes the receipt,
    so it lives in the private recordings repository (``docs/DATA.md``).
    """

    net: ExtractedField[Money]
    tax: ExtractedField[Money]
    rounding: ExtractedField[SignedMoney]


# Inside the clone of the private recordings repository (DOC_INTAKE_RECORDINGS_DIR).
AMOUNTS_PATH = Path("golden") / "sroie-amounts.json"
_AMOUNTS = TypeAdapter(dict[str, Amounts])


def load_amounts(path: Path) -> dict[str, Amounts]:
    """The annotated amounts by receipt id; a missing file says where it comes from."""
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found: the golden amounts live in the private recordings "
            "repository; clone it as docs/DATA.md says"
        )
    try:
        return _AMOUNTS.validate_json(path.read_bytes())
    except ValidationError as error:
        # Locations and rules only: the input is the private annotation, and
        # this message reaches the public CI log (D6).
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
            for e in error.errors(include_url=False, include_input=False, include_context=False)
        )
        raise ValueError(f"{path} is not a valid amounts file: {problems}") from None


class Manifest(StrictModel, frozen=True):
    """Where the set comes from and which receipts it holds."""

    source: Annotated[str, Field(pattern=r"^[\w.-]+/[\w.-]+$")]  # GitHub owner/repo
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    split: Literal["test"]
    seed: str
    size: Annotated[int, Field(ge=1)]
    receipts: list[GoldenEntry]


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def select(ids: Iterable[str], *, seed: str, size: int) -> list[str]:
    """The ``size`` ids ranked first by SHA-256 of ``"<seed>:<id>"``, in id order.

    A hash instead of ``random.sample``: Python guarantees the same sequence
    across versions only for ``random()``, not for ``sample()``, while SHA-256
    gives the same answer in any version and any language.
    """
    ranked = sorted(ids, key=lambda rid: hashlib.sha256(f"{seed}:{rid}".encode()).hexdigest())
    return sorted(ranked[:size])


# Explicit month names instead of strptime's %b, which depends on the locale.
_MONTHS = {
    name: number
    for number, name in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    )
}
_NUMERIC_DATE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})")
_NAMED_MONTH_DATE = re.compile(r"(\d{1,2}) ([A-Za-z]{3}) (\d{4})")


def parse_date(text: str) -> date:
    """Read a SROIE date, day first (the order printed in Malaysia).

    Only the formats present in the selected receipts are accepted; any other
    fails, so a new format is looked at instead of guessed. Two-digit years are
    20yy: the receipts are from 2016 to 2018.
    """
    if match := _NUMERIC_DATE.fullmatch(text):
        day, month, year = (int(part) for part in match.groups())
        year += 2000 if year < 100 else 0
    elif (match := _NAMED_MONTH_DATE.fullmatch(text)) and match[2].upper() in _MONTHS:
        day, month, year = int(match[1]), _MONTHS[match[2].upper()], int(match[3])
    else:
        raise ValueError(f"unknown date format: {text!r}")
    try:
        return date(year, month, day)
    except ValueError as error:
        raise ValueError(f"impossible date: {text!r}") from error


# "RM" is printed by most receipts, "$" by a few; the symbol is not the value.
_TOTAL = re.compile(r"(?:RM ?|\$)?(\d+\.\d{2})")


def parse_total(text: str) -> Decimal:
    """Read a SROIE total as an exact ``Decimal``, without the currency symbol."""
    match = _TOTAL.fullmatch(text)
    if match is None:
        raise ValueError(f"unknown total format: {text!r}")
    return Decimal(match[1])


def to_receipt(entities: bytes, *, currency: ExtractedField[str], amounts: Amounts) -> Receipt:
    """Convert one SROIE ground-truth file, plus our annotations, to the golden ``Receipt``."""
    raw: dict[str, str] = json.loads(entities)
    missing = [key for key in ("company", "date", "address", "total") if not raw.get(key)]
    if missing:
        raise ValueError(f"ground truth without {', '.join(missing)}")

    def cited[T](value: T, quote: str) -> ExtractedField[T]:
        return ExtractedField[T](
            value=value, citation=Citation(page=1, source="image", quote=quote), reason=None
        )

    return Receipt(
        company=cited(raw["company"], raw["company"]),
        address=cited(raw["address"], raw["address"]),
        date=cited(parse_date(raw["date"]), raw["date"]),
        total=cited(parse_total(raw["total"]), raw["total"]),
        currency=currency,
        net=amounts.net,
        tax=amounts.tax,
        rounding=amounts.rounding,
    )
