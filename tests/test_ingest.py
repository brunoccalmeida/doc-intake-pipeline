"""Ingest turns a file into text per page, from the PDF text layer or from OCR.

Every fixture is generated here (no client data, nothing downloaded): a PDF
with a text layer is written by hand, and images are drawn with Pillow, so a
scanned page is an image whose words only OCR can recover.
"""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

from core.config import Settings
from core.ingest import (
    EmptyDocumentError,
    OcrDataMissingError,
    PageText,
    UnreadableDocumentError,
    UnsupportedFileTypeError,
    ingest,
)


@pytest.fixture(scope="module")
def tessdata_dir() -> Path:
    """The OCR language data; missing data is a failure, never a skip."""
    path = Settings().tessdata_dir
    if not (path / "eng.traineddata").is_file():
        pytest.fail(f"no eng.traineddata in {path}: run 'uv run poe fetch-tessdata'")
    return path


def write_pdf(path: Path, pages: list[str | Image.Image]) -> Path:
    """Write a minimal PDF, one page per item.

    A ``str`` page is a real text layer; each ``\\n`` starts a new line (``T*``
    with 40 pt leading). An image page has no text at all, like a scan: the
    image is embedded raw (8-bit grayscale) across the top of the page.
    """
    count = len(pages)
    # Objects 1-3 are shared; page i owns 4+3i (page), 5+3i (content), 6+3i (image or null).
    kids = " ".join(f"{4 + 3 * i} 0 R" for i in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, page in enumerate(pages):
        content_ref, image_ref = 5 + 3 * i, 6 + 3 * i
        if isinstance(page, str):
            lines = " T* ".join(f"({line}) Tj" for line in page.split("\n"))
            content = f"BT /F1 24 Tf 40 TL 72 720 Td {lines} ET".encode()
            image = b"null"
        else:
            gray = page.convert("L")
            height = 612 * gray.height / gray.width
            content = f"q 612 0 0 {height:.2f} 0 {792 - height:.2f} cm /Im0 Do Q".encode()
            pixels = gray.tobytes()
            image = b"<< /Type /XObject /Subtype /Image /Width %d /Height %d" % gray.size + (
                b" /ColorSpace /DeviceGray /BitsPerComponent 8 /Length %d >>\nstream\n%s\nendstream"
                % (len(pixels), pixels)
            )
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources <<"
            b" /Font << /F1 3 0 R >> /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
            % (image_ref, content_ref)
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
        objects.append(image)

    out = bytearray(b"%PDF-1.7\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    path.write_bytes(bytes(out))
    return path


def draw_text(text: str) -> Image.Image:
    """A white page with black printed text: what a scanner produces, minus the noise."""
    image = Image.new("L", (1400, 240), color=255)
    ImageDraw.Draw(image).text((40, 70), text, fill=0, font=ImageFont.load_default(size=64))
    return image


def faded_receipt_with_scanner_borders() -> Image.Image:
    """Light-grey print on white between two black bands, like SROIE X51006619346.

    A thermal roll fades to grey; the scanner lid leaves black bands above and
    below the paper. Those few dark rows were enough for Tesseract's global
    Otsu threshold to land between black and white, erasing the grey print.
    """
    image = Image.new("L", (1400, 400), color=255)
    draw = ImageDraw.Draw(image)
    draw.text((40, 150), "TOTAL 12.50 CASH", fill=200, font=ImageFont.load_default(size=64))
    draw.rectangle((0, 0, 1399, 11), fill=0)
    draw.rectangle((0, 388, 1399, 399), fill=0)
    return image


def words(page: PageText) -> set[str]:
    return set(page.text.split())


def test_pdf_with_text_layer_is_read_without_ocr(tmp_path: Path) -> None:
    pdf = write_pdf(tmp_path / "receipt.pdf", ["TOTAL 12.50", "THANK YOU"])

    # No language data: reaching OCR would raise OcrDataMissingError.
    document = ingest(pdf, tessdata_dir=tmp_path / "no-tessdata")

    assert [page.number for page in document.pages] == [1, 2]
    assert [page.source for page in document.pages] == ["text_layer", "text_layer"]
    assert {"TOTAL", "12.50"} <= words(document.pages[0])
    assert {"THANK", "YOU"} <= words(document.pages[1])


def test_line_breaks_are_newlines_and_text_is_otherwise_literal(tmp_path: Path) -> None:
    # PDFium ends lines with "\r\n" (observed with pypdfium2 5.15); a citation
    # quotes this text, so one line-break convention, nothing else changed.
    pdf = write_pdf(tmp_path / "receipt.pdf", ["TOTAL 12.50\nTHANK YOU"])

    document = ingest(pdf, tessdata_dir=tmp_path)

    assert document.pages[0].text == "TOTAL 12.50\nTHANK YOU"


def test_faded_print_between_dark_scanner_borders_is_read(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    image = tmp_path / "receipt.png"
    faded_receipt_with_scanner_borders().save(image)

    document = ingest(image, tessdata_dir=tessdata_dir)

    assert {"TOTAL", "12.50", "CASH"} <= words(document.pages[0])


def test_dark_borders_are_whitened_keeping_the_page_size(
    tmp_path: Path, tessdata_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cropping them instead left print touching the image edge, and Tesseract
    # then dropped the amount column of SROIE X51007339159 (issue #19); tessdoc
    # "Missing borders" warns about such tight crops.
    seen: list[Image.Image] = []

    def fake_image_to_text(image: Image.Image, **_: str) -> str:
        seen.append(image)
        return "TOTAL"

    monkeypatch.setattr("core.ingest.tesserocr.image_to_text", fake_image_to_text)
    page = faded_receipt_with_scanner_borders()
    path = tmp_path / "receipt.png"
    page.save(path)

    ingest(path, tessdata_dir=tessdata_dir)

    ocr_input = seen[0].convert("L")
    assert ocr_input.size == page.size
    width, height = page.size
    white = (255, 255)  # (darkest, brightest) of a pure white region
    assert ocr_input.crop((0, 0, width, 12)).getextrema() == white, "top border still dark"
    assert ocr_input.crop((0, height - 12, width, height)).getextrema() == white, (
        "bottom border still dark"
    )


def test_page_without_dark_borders_reaches_ocr_unchanged(
    tmp_path: Path, tessdata_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A recording is keyed by the document text (evals/recording.py), so the
    # border trim must leave a borderless page exactly as it was.
    page = draw_text("TOTAL 12.50 CASH")
    seen: list[Image.Image] = []

    def fake_image_to_text(image: Image.Image, **_: str) -> str:
        seen.append(image)
        return "TOTAL"

    monkeypatch.setattr("core.ingest.tesserocr.image_to_text", fake_image_to_text)
    path = tmp_path / "receipt.png"
    page.save(path)

    ingest(path, tessdata_dir=tessdata_dir)

    assert seen[0].size == page.size
    assert seen[0].tobytes() == page.tobytes(), "same size, different pixels"


def test_all_dark_image_is_empty_not_a_crash(tmp_path: Path, tessdata_dir: Path) -> None:
    # Every row is "dark border": trimming must not leave a zero-size image.
    image = tmp_path / "receipt.png"
    Image.new("L", (300, 200), color=0).save(image)

    with pytest.raises(EmptyDocumentError):
        ingest(image, tessdata_dir=tessdata_dir)


@pytest.mark.parametrize("name", ["receipt.png", "receipt.jpg", "RECEIPT.JPEG"])
def test_image_is_read_with_ocr(tmp_path: Path, tessdata_dir: Path, name: str) -> None:
    image = tmp_path / name
    draw_text("TOTAL 12.50 CASH").save(image)

    document = ingest(image, tessdata_dir=tessdata_dir)

    assert len(document.pages) == 1
    page = document.pages[0]
    assert (page.number, page.source) == (1, "ocr")
    assert {"TOTAL", "12.50", "CASH"} <= words(page)


def test_scanned_pdf_without_text_layer_is_read_with_ocr(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    scanned = tmp_path / "scanned.pdf"
    draw_text("TOTAL 12.50 CASH").save(scanned, resolution=150.0)

    document = ingest(scanned, tessdata_dir=tessdata_dir)

    assert [page.source for page in document.pages] == ["ocr"]
    assert {"TOTAL", "12.50", "CASH"} <= words(document.pages[0])


def test_ocr_without_language_data_names_the_fix(tmp_path: Path) -> None:
    image = tmp_path / "receipt.png"
    draw_text("TOTAL").save(image)

    with pytest.raises(OcrDataMissingError, match="fetch-tessdata"):
        ingest(image, tessdata_dir=tmp_path / "no-tessdata")


@pytest.mark.parametrize("name", ["receipt.docx", "receipt.txt", "receipt"])
def test_unsupported_extension_raises_a_named_error(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"anything")

    with pytest.raises(UnsupportedFileTypeError, match=name):
        ingest(path, tessdata_dir=tmp_path)


@pytest.mark.parametrize("name", ["broken.pdf", "broken.png"])
def test_corrupt_file_is_unreadable(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"not really a document")

    with pytest.raises(UnreadableDocumentError, match=name):
        ingest(path, tessdata_dir=tmp_path)


def test_missing_file_is_unreadable(tmp_path: Path) -> None:
    with pytest.raises(UnreadableDocumentError, match=r"missing\.pdf"):
        ingest(tmp_path / "missing.pdf", tessdata_dir=tmp_path)


def test_document_without_any_text_is_an_error(tmp_path: Path, tessdata_dir: Path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("L", (600, 300), color=255).save(blank)

    with pytest.raises(EmptyDocumentError, match=r"blank\.png"):
        ingest(blank, tessdata_dir=tessdata_dir)


def test_document_is_immutable(tmp_path: Path) -> None:
    # pyright already rejects these assignments statically; this test covers the
    # runtime layer, for code paths a type checker does not see (e.g. setattr).
    document = ingest(write_pdf(tmp_path / "r.pdf", ["TOTAL"]), tessdata_dir=tmp_path)
    page = document.pages[0]

    with pytest.raises(ValidationError, match="frozen"):
        document.pages = ()  # pyright: ignore[reportAttributeAccessIssue]  # deliberate
    with pytest.raises(ValidationError, match="frozen"):
        page.text = "OTHER"  # pyright: ignore[reportAttributeAccessIssue]  # deliberate


def test_mixed_pdf_chooses_text_layer_or_ocr_per_page(tmp_path: Path, tessdata_dir: Path) -> None:
    pdf = write_pdf(tmp_path / "mixed.pdf", ["THANK YOU", draw_text("TOTAL 12.50 CASH")])

    document = ingest(pdf, tessdata_dir=tessdata_dir)

    assert [page.source for page in document.pages] == ["text_layer", "ocr"]
    assert {"THANK", "YOU"} <= words(document.pages[0])
    assert {"TOTAL", "12.50", "CASH"} <= words(document.pages[1])


def test_pdf_with_a_broken_page_is_unreadable(tmp_path: Path) -> None:
    # The file opens (header and xref are fine) but its only page points to an
    # object that does not exist: PDFium fails at the page, not at the open.
    pdf = write_pdf(tmp_path / "broken-page.pdf", ["TOTAL"])
    pdf.write_bytes(pdf.read_bytes().replace(b"/Kids [4 0 R]", b"/Kids [9 0 R]"))

    with pytest.raises(UnreadableDocumentError, match=r"broken-page\.pdf"):
        ingest(pdf, tessdata_dir=tmp_path)


def test_oversized_image_is_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Pillow refuses images over 2x MAX_IMAGE_PIXELS (decompression bomb), and
    # that error is not an OSError. Lowering the limit keeps the fixture small.
    image = tmp_path / "huge.png"
    Image.new("L", (100, 100), color=255).save(image)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)

    with pytest.raises(UnreadableDocumentError, match=r"huge\.png"):
        ingest(image, tessdata_dir=tmp_path)
