"""Read a document file into text per page: the PDF text layer, or OCR.

A PDF page with a text layer is read directly (exact and fast). A page without
one (a scan saved as PDF) and every image is rendered and read by Tesseract.
The choice is made per page, so a PDF mixing typed and scanned pages works,
and each page records where its text came from.

The text is kept as read: citations (``docs/ARCHITECTURE.md`` D1) quote it
literally, so the only change is ``\\r\\n`` to ``\\n``. Error messages name the
file, never its content (AGENTS.md invariant 6).
"""

from pathlib import Path
from typing import Annotated, Literal

import pypdfium2 as pdfium
import tesserocr
from PIL import Image
from pydantic import Field

from core.result import StrictModel

PDF_SUFFIXES = frozenset({".pdf"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})

# "Tesseract works best on images which have a DPI of at least 300 dpi"
# (tessdoc, "Improving the quality of the output", Rescaling). A PDF canvas
# unit is 1/72 in, so the render scale is DPI / 72.
OCR_DPI = 300
OCR_LANGUAGE = "eng"

# A row or column of the image edge whose mean brightness (0 black, 255 white)
# is below this is scanner border, not paper. Mid-grey: paper with print stays
# far above it (SROIE receipts measured in issue #19).
DARK_EDGE_MAX_MEAN = 128

type TextSource = Literal["text_layer", "ocr"]


class PageText(StrictModel, frozen=True):
    """One page's text, numbered from 1 like ``Citation.page``."""

    number: Annotated[int, Field(ge=1)]
    text: str
    source: TextSource


class Document(StrictModel, frozen=True):
    """A file's text, page by page. A tuple, so a frozen document stays frozen."""

    pages: Annotated[tuple[PageText, ...], Field(min_length=1)]


class IngestError(Exception):
    """A file could not become a ``Document``; the run reports it, never skips it."""


class UnsupportedFileTypeError(IngestError):
    """The file's extension is not a PDF or a supported image."""


class UnreadableDocumentError(IngestError):
    """The file is missing, or is not the PDF or image its extension claims."""


class EmptyDocumentError(IngestError):
    """No page yielded any text, not even through OCR."""


class OcrDataMissingError(IngestError):
    """Tesseract's language data is not where the settings say."""


def ingest(path: Path, *, tessdata_dir: Path) -> Document:
    """Read ``path`` (PDF, PNG or JPEG) into text per page.

    ``tessdata_dir`` holds ``eng.traineddata``; it is only read if a page
    needs OCR.

    Raises:
        UnsupportedFileTypeError: the extension is not supported.
        UnreadableDocumentError: the file is missing or corrupt.
        EmptyDocumentError: no page has any text.
        OcrDataMissingError: a page needs OCR and the language data is missing.
    """
    suffix = path.suffix.lower()
    if suffix not in PDF_SUFFIXES | IMAGE_SUFFIXES:
        supported = ", ".join(sorted(PDF_SUFFIXES | IMAGE_SUFFIXES))
        raise UnsupportedFileTypeError(f"{path.name}: unsupported type (supported: {supported})")
    if not path.is_file():
        raise UnreadableDocumentError(f"{path.name}: file not found")

    if suffix in PDF_SUFFIXES:
        pages = _read_pdf(path, tessdata_dir)
    else:
        pages = [PageText(number=1, text=_ocr(_open_image(path), tessdata_dir), source="ocr")]

    if not any(page.text.strip() for page in pages):
        raise EmptyDocumentError(f"{path.name}: no text found on any page")
    return Document(pages=tuple(pages))


def _read_pdf(path: Path, tessdata_dir: Path) -> list[PageText]:
    # PDFium can open a file and still fail on one of its pages (load, text or
    # render), so the whole read is guarded, not only the open.
    pages: list[PageText] = []
    try:
        with pdfium.PdfDocument(path) as pdf:  # closing it closes its pages too
            for index in range(len(pdf)):
                page = pdf[index]
                text = _normalize(page.get_textpage().get_text_bounded())
                if text.strip():
                    pages.append(PageText(number=index + 1, text=text, source="text_layer"))
                else:
                    image = page.render(scale=OCR_DPI / 72).to_pil()
                    pages.append(
                        PageText(number=index + 1, text=_ocr(image, tessdata_dir), source="ocr")
                    )
    except pdfium.PdfiumError as error:
        raise UnreadableDocumentError(f"{path.name}: not a readable PDF ({error})") from error
    return pages


def _open_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            image.load()  # Pillow decodes lazily: force it so corruption fails here
            return image.copy()
    # UnidentifiedImageError and truncated files are OSErrors; the decompression
    # bomb guard (over 2x Image.MAX_IMAGE_PIXELS) is not, so it is named too.
    except (OSError, Image.DecompressionBombError) as error:
        raise UnreadableDocumentError(f"{path.name}: not a readable image ({error})") from error


def _ocr(image: Image.Image, tessdata_dir: Path) -> str:
    if not (tessdata_dir / f"{OCR_LANGUAGE}.traineddata").is_file():
        raise OcrDataMissingError(
            f"no {OCR_LANGUAGE}.traineddata in {tessdata_dir}: run 'uv run poe fetch-tessdata'"
        )
    image = _whiten_dark_borders(image)
    return _normalize(tesserocr.image_to_text(image, lang=OCR_LANGUAGE, path=str(tessdata_dir)))


def _whiten_dark_borders(image: Image.Image) -> Image.Image:
    """Paint white the dark bands a scanner leaves around the paper.

    Tesseract binarizes with one global Otsu threshold; a few rows of black
    border are enough to pull it between black and white, and faded grey print
    then falls on the white side and vanishes (issue #19). tessdoc "Improving
    the quality of the output" lists scanning-border removal for this.

    The bands are painted, not cropped: a crop leaves print touching the image
    edge, which tessdoc ("Missing borders") warns against and which made
    Tesseract drop a column of amounts. A page without such a band is returned
    as is (recordings are keyed by its text), and so is an all-dark one, which
    OCR then reports empty.
    """
    gray = image.convert("L")
    width, height = gray.size
    # Reducing by the full width leaves one pixel per row, the mean of that row
    # (and likewise per column), computed in C without a Python pixel loop.
    rows = gray.reduce((width, 1)).tobytes()
    columns = gray.reduce((1, height)).tobytes()
    vertical = _paper_span(rows)
    horizontal = _paper_span(columns)
    if vertical is None or horizontal is None:
        return image
    (top, bottom), (left, right) = vertical, horizontal
    paper = (left, top, right, bottom)
    if paper == (0, 0, width, height):
        return image
    whitened = Image.new(image.mode, image.size, "white")
    whitened.paste(image.crop(paper), paper[:2])
    return whitened


def _paper_span(means: bytes) -> tuple[int, int] | None:
    """The ``[start, end)`` range left after dropping dark means at both ends.

    ``None`` when every mean is dark: there is no paper to keep.
    """
    start = 0
    while start < len(means) and means[start] < DARK_EDGE_MAX_MEAN:
        start += 1
    end = len(means)
    while end > start and means[end - 1] < DARK_EDGE_MAX_MEAN:
        end -= 1
    return (start, end) if start < end else None


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n")
