"""``doc_intake.batch``: an inbox folder in, one run folder out with a CSV review queue."""

import csv
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from doc_intake import batch
from doc_intake.batch import RunReport, ready_documents, run_inbox, spreadsheet_safe
from doc_intake.core.config import Settings
from doc_intake.core.ingest import Document, OcrDataMissingError, PageText
from doc_intake.core.llm import LLMRequest, LLMResponse
from doc_intake.packs.receipt import RECEIPT

NOW = datetime(2026, 11, 22, 15, 30, tzinfo=UTC)
SETTLE = timedelta(seconds=60)


@pytest.mark.parametrize(
    "text",
    [
        '=HYPERLINK("http://evil.example","Click")',
        "+1+1",
        "-2+3",
        "@SUM(A1:A2)",
        "\t=1",
        "\r=1",
        "\n=1",
        # Full-width forms: read as a formula in some locales (OWASP).
        "\N{FULLWIDTH EQUALS SIGN}1",
        "\N{FULLWIDTH PLUS SIGN}1",
        "\N{FULLWIDTH HYPHEN-MINUS}1",
        "\N{FULLWIDTH COMMERCIAL AT}1",
    ],
)
def test_a_cell_that_could_start_a_formula_is_turned_into_text(text: str) -> None:
    assert spreadsheet_safe(text) == "'" + text


@pytest.mark.parametrize("text", ["-12.50", "12.50", "-3", "0", "ACME Sdn Bhd", "", "2026-11-22"])
def test_a_plain_number_or_ordinary_text_is_kept_as_is(text: str) -> None:
    # A plain number cannot run anything, and stays a number in the sheet.
    assert spreadsheet_safe(text) == text


def place(folder: Path, name: str, *, age: timedelta, content: bytes = b"x") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)
    stamp = (NOW - age).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_only_settled_supported_visible_files_are_ready_in_name_order(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    old = timedelta(minutes=5)
    place(inbox, "b.PDF", age=old)
    place(inbox, "a.png", age=old)
    place(inbox, "c.jpeg", age=old)
    place(inbox, "d.jpg", age=SETTLE)  # exactly settled
    place(inbox, "still-syncing.png", age=SETTLE - timedelta(seconds=1))
    place(inbox, ".hidden.png", age=old)
    place(inbox, "receipt.png.tmp", age=old)  # a sync client's partial download
    place(inbox, "notes.txt", age=old)
    (inbox / "folder.png").mkdir()

    ready = ready_documents(inbox, settle=SETTLE, now=NOW)

    assert [path.name for path in ready] == ["a.png", "b.PDF", "c.jpeg", "d.jpg"]


def test_a_missing_inbox_fails_naming_it(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="inbox"):
        ready_documents(tmp_path / "inbox", settle=SETTLE, now=NOW)


def null_field(reason: str = "not printed") -> dict[str, object]:
    return {"value": None, "citation": None, "reason": reason}


def image_field(value: str, quote: str) -> dict[str, object]:
    # An image quote cannot be checked by code: it always goes to review (D12).
    citation = {"page": 1, "source": "image", "quote": quote}
    return {"value": value, "citation": citation, "reason": None}


ALL_NULL = {name: null_field() for name in ("company", "address", "date", "total", "currency")}
REVIEW_TOTAL = {**ALL_NULL, "total": image_field("9.90", "TOTAL 9.90")}
FORMULA_COMPANY = {**ALL_NULL, "company": image_field("=1+1", "=1+1")}


@dataclass
class ScriptedProvider:
    """Answers each request with the next scripted receipt (in document order)."""

    answers: Sequence[Mapping[str, object] | Exception]
    calls: int = 0
    seen: list[LLMRequest] = field(default_factory=list[LLMRequest])
    # The model each answer reports, by call number; the default is priced.
    models: Mapping[int, str] = field(default_factory=dict[int, str])
    # Run before answering a call, by call number: e.g. a sync client
    # replacing a file while the run is still going.
    before: Mapping[int, Callable[[], object]] = field(
        default_factory=dict[int, Callable[[], object]]
    )

    def complete(self, request: LLMRequest) -> LLMResponse:
        call = self.calls
        answer = self.answers[call]
        self.calls += 1
        self.seen.append(request)
        if call in self.before:
            self.before[call]()
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(
            text=json.dumps(answer),
            input_tokens=100,
            output_tokens=50,
            model=self.models.get(call, "claude-opus-5-5"),
        )


def printed_page(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    image = Image.new("L", (900, 200), color=255)
    ImageDraw.Draw(image).text((40, 60), text, fill=0, font=ImageFont.load_default(size=64))
    image.save(path)
    stamp = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def rows_of(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def run(
    tmp_path: Path, provider: ScriptedProvider, tessdata_dir: Path
) -> tuple[Path, Path, RunReport]:
    inbox, runs = tmp_path / "inbox", tmp_path / "runs"
    report = run_inbox(
        inbox,
        runs,
        RECEIPT,
        provider,
        tessdata_dir=tessdata_dir,
        provider_name="claude",
        max_retries=0,
        settle=SETTLE,
        now=NOW,
    )
    return inbox, runs, report


def folder_of(report: RunReport) -> Path:
    assert report.folder is not None
    return report.folder


@pytest.fixture
def tessdata_dir(no_doc_intake_env: None) -> Path:
    return Settings().tessdata_dir


def test_a_run_writes_one_row_per_field_and_moves_the_originals_beside_it(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    inbox = tmp_path / "inbox"
    printed_page(inbox, "a-ok.png", "TOTAL 1.00")
    printed_page(inbox, "b-review.png", "TOTAL 9.90")
    provider = ScriptedProvider([ALL_NULL, REVIEW_TOTAL])

    _, runs, report = run(tmp_path, provider, tessdata_dir)

    [folder] = list(runs.iterdir())
    assert folder.name == "2026-11-22T15-30-00Z"
    assert report.folder == folder
    assert (report.documents, report.needs_review, report.failed) == (2, 1, 0)
    assert list(inbox.iterdir()) == []
    assert sorted(p.name for p in (folder / "documents").iterdir()) == ["a-ok.png", "b-review.png"]
    rows = rows_of(folder / "results.csv")
    assert [(r["file"], r["field"], r["field_status"]) for r in rows] == [
        ("a-ok.png", name, "accepted") for name in ALL_NULL
    ] + [
        ("b-review.png", name, "needs_review" if name == "total" else "accepted")
        for name in ALL_NULL
    ]
    total = rows[8]
    assert total == {
        "file": "b-review.png",
        "document_status": "needs_review",
        "field": "total",
        "field_status": "needs_review",
        "value": "9.90",
        "page": "1",
        "source": "image",
        "quote": "TOTAL 9.90",
        "note": "read from the image of page 1; check it on the page",
    }
    assert rows[0]["value"] == ""
    assert rows[0]["note"] == "not printed"


def test_the_csv_opens_as_utf8_in_excel_and_disarms_formulas(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    printed_page(tmp_path / "inbox", "a.png", "TOTAL 1.00")

    _, _, report = run(tmp_path, ScriptedProvider([FORMULA_COMPANY]), tessdata_dir)

    raw = (folder_of(report) / "results.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # the BOM Excel needs to read UTF-8
    company = rows_of(folder_of(report) / "results.csv")[0]
    assert (company["value"], company["quote"]) == ("'=1+1", "'=1+1")


def test_an_unreadable_file_is_a_failed_row_and_moves_with_the_run(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    place(tmp_path / "inbox", "broken.png", age=timedelta(minutes=5), content=b"not a png")
    provider = ScriptedProvider([])

    _, _, report = run(tmp_path, provider, tessdata_dir)

    assert provider.calls == 0
    assert (report.documents, report.failed) == (1, 1)
    assert (folder_of(report) / "documents" / "broken.png").is_file()
    [row] = rows_of(folder_of(report) / "results.csv")
    assert (row["file"], row["document_status"], row["field"]) == ("broken.png", "failed", "")
    assert "broken.png" in row["note"]


def test_a_provider_error_leaves_the_file_in_the_inbox_for_the_next_run(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    printed_page(tmp_path / "inbox", "a.png", "TOTAL 1.00")
    printed_page(tmp_path / "inbox", "b.png", "TOTAL 2.00")
    provider = ScriptedProvider([ConnectionError("network down"), ALL_NULL])

    inbox, _, report = run(tmp_path, provider, tessdata_dir)

    assert [p.name for p in inbox.iterdir()] == ["a.png"]
    assert [p.name for p in (folder_of(report) / "documents").iterdir()] == ["b.png"]
    assert (report.documents, report.failed) == (2, 1)
    failed = rows_of(folder_of(report) / "results.csv")[0]
    assert (failed["file"], failed["document_status"]) == ("a.png", "failed")
    assert failed["note"] == "ConnectionError; left in the inbox for the next run"


def test_an_empty_inbox_creates_no_run_folder(tmp_path: Path, tessdata_dir: Path) -> None:
    (tmp_path / "inbox").mkdir()

    _, runs, report = run(tmp_path, ScriptedProvider([]), tessdata_dir)

    assert report.folder is None
    assert report.documents == 0
    assert not runs.exists()


def test_a_second_run_in_the_same_second_fails_instead_of_mixing_runs(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    printed_page(tmp_path / "inbox", "a.png", "TOTAL 1.00")
    run(tmp_path, ScriptedProvider([ALL_NULL]), tessdata_dir)
    printed_page(tmp_path / "inbox", "b.png", "TOTAL 2.00")
    second = ScriptedProvider([ALL_NULL])

    with pytest.raises(FileExistsError):
        run(tmp_path, second, tessdata_dir)
    assert second.calls == 0  # fails before paying for anything
    assert [p.name for p in (tmp_path / "inbox").iterdir()] == ["b.png"]


def test_a_configuration_error_stops_the_run_and_leaves_no_run_folder(tmp_path: Path) -> None:
    printed_page(tmp_path / "inbox", "a.png", "TOTAL 1.00")

    with pytest.raises(OcrDataMissingError):
        run(tmp_path, ScriptedProvider([ALL_NULL]), tmp_path / "no-tessdata")
    assert [p.name for p in (tmp_path / "inbox").iterdir()] == ["a.png"]
    assert not (tmp_path / "runs").exists()


def test_a_file_that_cannot_be_read_is_left_and_the_rest_of_the_run_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tessdata_dir: Path
) -> None:
    printed_page(tmp_path / "inbox", "a.png", "TOTAL 1.00")
    printed_page(tmp_path / "inbox", "b-locked.png", "TOTAL 2.00")
    read_bytes = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == "b-locked.png":
            raise PermissionError(13, "Permission denied", str(self))
        return read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", locked)

    inbox, _, report = run(tmp_path, ScriptedProvider([ALL_NULL]), tessdata_dir)

    assert [p.name for p in inbox.iterdir()] == ["b-locked.png"]
    assert [p.name for p in (folder_of(report) / "documents").iterdir()] == ["a.png"]
    locked_row = rows_of(folder_of(report) / "results.csv")[-1]
    assert (locked_row["file"], locked_row["document_status"]) == ("b-locked.png", "failed")
    assert locked_row["note"] == "PermissionError; left in the inbox for the next run"


def test_missing_ocr_data_stops_the_run_before_any_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A PDF with a text layer needs no OCR, so ingest alone would not notice.
    def text_layer(path: Path, *, tessdata_dir: Path) -> Document:
        page = PageText(number=1, text="TOTAL 1.00", source="text_layer", image=None)
        return Document(pages=(page,))

    monkeypatch.setattr(batch, "ingest", text_layer)
    place(tmp_path / "inbox", "a.pdf", age=timedelta(minutes=5))
    provider = ScriptedProvider([ALL_NULL])

    with pytest.raises(OcrDataMissingError, match="DOC_INTAKE_TESSDATA_DIR"):
        run(tmp_path, provider, tmp_path / "no-tessdata")
    assert provider.calls == 0


def test_an_unpriced_model_stops_the_run_and_keeps_what_was_done(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    for name in ("a.png", "b.png", "c.png"):
        printed_page(tmp_path / "inbox", name, "TOTAL 1.00")
    # A fallback model with no price row: paid, but its cost cannot be logged.
    provider = ScriptedProvider([ALL_NULL, ALL_NULL, ALL_NULL], models={1: "model-x"})

    inbox, _, report = run(tmp_path, provider, tessdata_dir)

    assert provider.calls == 2  # c.png is not paid for while the price is missing
    assert [p.name for p in inbox.iterdir()] == ["b.png", "c.png"]
    assert [p.name for p in (folder_of(report) / "documents").iterdir()] == ["a.png"]
    stopped = rows_of(folder_of(report) / "results.csv")[-1]
    assert (stopped["file"], stopped["document_status"]) == ("b.png", "failed")
    assert stopped["note"] == (
        "UnknownModelPriceError; run stopped: add the model's price, then run again"
    )
    assert (report.documents, report.failed) == (2, 1)


def test_a_file_replaced_during_the_run_is_left_for_the_next_one(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    first = printed_page(tmp_path / "inbox", "a.png", "TOTAL 1.00")
    printed_page(tmp_path / "inbox", "b.png", "TOTAL 2.00")

    def sync_replaces_a() -> None:
        printed_page(tmp_path / "inbox", "a.png", "TOTAL 3.00")

    provider = ScriptedProvider([ALL_NULL, ALL_NULL], before={1: sync_replaces_a})

    inbox, _, report = run(tmp_path, provider, tessdata_dir)

    assert [p.name for p in inbox.iterdir()] == ["a.png"]
    assert first.read_bytes() != b""  # the new version, still there to process
    replaced = rows_of(folder_of(report) / "results.csv")[0]
    assert (replaced["file"], replaced["document_status"]) == ("a.png", "failed")
    assert replaced["note"] == "changed during the run; left in the inbox for the next run"


def test_every_cell_is_quoted_so_a_semicolon_cannot_split_one(
    tmp_path: Path, tessdata_dir: Path
) -> None:
    # Excel with ";" as list separator (pt-BR, de-DE) splits an unquoted cell
    # there, and "=..." would start a new cell (OWASP, "CSV Injection").
    printed_page(tmp_path / "inbox", "a.png", "TOTAL 1.00")
    semicolon = {**ALL_NULL, "company": image_field("x;=1+1", "x;=1+1")}

    _, _, report = run(tmp_path, ScriptedProvider([semicolon]), tessdata_dir)

    text = (folder_of(report) / "results.csv").read_text(encoding="utf-8-sig")
    assert '"x;=1+1"' in text
    assert all(line.startswith('"') for line in text.splitlines())
