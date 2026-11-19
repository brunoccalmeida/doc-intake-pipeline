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
    return _normalize(tesserocr.image_to_text(image, lang=OCR_LANGUAGE, path=str(tessdata_dir)))


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n")
