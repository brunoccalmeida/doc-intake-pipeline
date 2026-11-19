"""Read a document file into text per page: the PDF text layer, or OCR.

A PDF page with a text layer is read directly (exact and fast). A page without
one (a scan saved as PDF) and every image is rendered and read by Tesseract.
The choice is made per page, so a PDF mixing typed and scanned pages works,
and each page records where its text came from.

The text is kept as read: citations (``docs/ARCHITECTURE.md`` D1) quote it
literally, so the only change is ``\\r\\n`` to ``\\n``. Error messages name the
file, never its content (AGENTS.md invariant 6).
"""

import io
from pathlib import Path
from typing import Annotated, Literal, Self

import pypdfium2 as pdfium
import tesserocr
from PIL import Image, ImageDraw
from pydantic import Field, model_validator

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
type ImageMediaType = Literal["image/png", "image/jpeg"]


class PageImage(StrictModel, frozen=True):
    """An encoded page image (the file's bytes) and its media type."""

    media_type: ImageMediaType
    data: bytes


class PageText(StrictModel, frozen=True):
    """One page's text, numbered from 1 like ``Citation.page``.

    An OCR page also carries the image its text was read from, so the model
    can read what OCR misread (issue #26); a text layer page is exact and
    carries none.
    """

    number: Annotated[int, Field(ge=1)]
    text: str
    source: TextSource
    image: PageImage | None

    @model_validator(mode="after")
    def _image_matches_source(self) -> Self:
        if self.source == "ocr" and self.image is None:
            raise ValueError("an OCR page carries the image it was read from")
        if self.source == "text_layer" and self.image is not None:
            raise ValueError("a text layer page carries no image")
        return self


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
        image, page_image = _open_image(path)
        pages = [
            PageText(number=1, text=_ocr(image, tessdata_dir), source="ocr", image=page_image)
        ]

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
                    pages.append(
                        PageText(number=index + 1, text=text, source="text_layer", image=None)
                    )
                else:
                    image = page.render(scale=OCR_DPI / 72).to_pil()
                    pages.append(
                        PageText(
                            number=index + 1,
                            text=_ocr(image, tessdata_dir),
                            source="ocr",
                            image=_png(image),
                        )
                    )
    except pdfium.PdfiumError as error:
        raise UnreadableDocumentError(f"{path.name}: not a readable PDF ({error})") from error
    return pages


def _open_image(path: Path) -> tuple[Image.Image, PageImage]:
    """The decoded image for OCR, and the file itself for the model.

    The model gets the file's own bytes, not a re-encoding: every lossy pass
    blurs print (Anthropic docs, "Vision", image quality guidance). Its media
    type comes from the content, not the extension, which can lie.
    """
    try:
        with Image.open(path) as image:
            image.load()  # Pillow decodes lazily: force it so corruption fails here
            decoded, found = image.copy(), image.format
    # UnidentifiedImageError and truncated files are OSErrors; the decompression
    # bomb guard (over 2x Image.MAX_IMAGE_PIXELS) is not, so it is named too.
    except (OSError, Image.DecompressionBombError) as error:
        raise UnreadableDocumentError(f"{path.name}: not a readable image ({error})") from error
    media_type = _MEDIA_TYPES.get(found or "")
    if media_type is None:
        raise UnreadableDocumentError(f"{path.name}: the file is {found}, not a PNG or JPEG")
    return decoded, PageImage(media_type=media_type, data=path.read_bytes())


_MEDIA_TYPES: dict[str, ImageMediaType] = {"PNG": "image/png", "JPEG": "image/jpeg"}


def _png(image: Image.Image) -> PageImage:
    """A rendered page as PNG: lossless, so the model sees the pixels OCR read."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return PageImage(media_type="image/png", data=buffer.getvalue())


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
    # Paint a copy rather than paste onto a new image: a new palette ("P")
    # image would hold only white, and pasted indices would point nowhere.
    whitened = image.copy()
    draw = ImageDraw.Draw(whitened)
    bands = [
        (0, 0, width, top),  # above the paper
        (0, bottom, width, height),  # below
        (0, 0, left, height),  # left of it
        (right, 0, width, height),  # right of it
    ]
    for x0, y0, x1, y1 in bands:
        if x0 < x1 and y0 < y1:  # ImageDraw boxes are inclusive: last pixel is x1 - 1
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill="white")
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
