"""``doc_intake.review``: a reviewed run folder read back as labeled fields (#63)."""

import csv
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from doc_intake.batch import run_inbox
from doc_intake.core.config import Settings
from doc_intake.core.llm import LLMRequest, LLMResponse
from doc_intake.packs.receipt import RECEIPT
from doc_intake.review import Label, ReviewError, read_reviewed_run

NOW = datetime(2026, 11, 22, 15, 30, tzinfo=UTC)


def cited(value: str, quote: str) -> dict[str, object]:
    return {
        "value": value,
        "citation": {"page": 1, "source": "text", "quote": quote},
        "reason": None,
    }


# Every field but currency has a value; date and total are converted types.
ANSWER = {
    "company": cited("ACME", "ACME"),
    "address": cited("1 Main St", "1 Main St"),
    "date": cited("2026-03-04", "04/03/2026"),
    "total": cited("9.90", "TOTAL 9.90"),
    "currency": {"value": None, "citation": None, "reason": "not printed"},
}


@dataclass
class OneAnswer:
    """Answers every request with ``ANSWER`` or, by call number, an error."""

    errors: dict[int, Exception]
    calls: int = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        call, self.calls = self.calls, self.calls + 1
        if call in self.errors:
            raise self.errors[call]
        return LLMResponse(
            text=json.dumps(ANSWER), input_tokens=1, output_tokens=1, model="claude-opus-5-5"
        )


@pytest.fixture
def run_folder(tmp_path: Path, no_doc_intake_env: None) -> Path:
    """A run of two receipts, ``a.png`` and ``b.png``, and one failed file, ``c.png``."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        # A page with no text is not a readable document: it needs some.
        image = Image.new("L", (900, 200), color=255)
        ImageDraw.Draw(image).text((40, 60), "TOTAL 9.90", fill=0, font=ImageFont.load_default(64))
        image.save(inbox / name)
        stamp = (NOW - timedelta(minutes=5)).timestamp()
        os.utime(inbox / name, (stamp, stamp))
    report = run_inbox(
        inbox,
        tmp_path / "runs",
        RECEIPT,
        OneAnswer(errors={2: RuntimeError("rate limit")}),
        tessdata_dir=Settings().tessdata_dir,
        provider_name="claude",
        max_retries=0,
        settle=timedelta(seconds=60),
        now=NOW,
    )
    assert report.folder is not None
    return report.folder


type Row = dict[str, str]


def review(folder: Path, edit: Callable[[list[Row]], object], *, delimiter: str = ",") -> None:
    """Edit ``results.csv`` as a reviewer would and save it back."""
    path = folder / "results.csv"
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    edit(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def row(rows: list[Row], file: str, field: str) -> Row:
    [found] = [r for r in rows if r["file"] == file and r["field"] == field]
    return found


def judge(file: str, field: str, verdict: str, correct: str = "") -> Callable[[list[Row]], None]:
    def edit(rows: list[Row]) -> None:
        row(rows, file, field).update(verdict=verdict, correct_value=correct)

    return edit


def test_each_verdict_becomes_a_label_and_unreviewed_fields_none(run_folder: Path) -> None:
    def edit(rows: list[Row]) -> None:
        row(rows, "a.png", "company").update(verdict="confirmed")
        row(rows, "a.png", "total").update(verdict="corrected", correct_value="19.90")
        row(rows, "a.png", "currency").update(verdict="confirmed")
        row(rows, "b.png", "date").update(verdict="corrected", correct_value="2026-04-03")
        row(rows, "b.png", "address").update(verdict="not_on_page")
        rows.reverse()  # a reviewer may sort the sheet

    review(run_folder, edit)

    assert read_reviewed_run(run_folder, RECEIPT) == [
        Label("a.png", "company", "confirmed", suggested="ACME", truth="ACME"),
        Label("a.png", "total", "corrected", suggested=Decimal("9.90"), truth=Decimal("19.90")),
        # Confirming an empty field labels it absent.
        Label("a.png", "currency", "confirmed", suggested=None, truth=None),
        Label("b.png", "address", "not_on_page", suggested="1 Main St", truth=None),
        Label("b.png", "date", "corrected", suggested=date(2026, 3, 4), truth=date(2026, 4, 3)),
    ]


def test_a_confirmed_value_comes_from_the_runs_copy_not_from_the_sheet(run_folder: Path) -> None:
    # A spreadsheet may show and save an ISO date in the local format.
    def edit(rows: list[Row]) -> None:
        row(rows, "a.png", "date").update(value="04/03/2026", verdict="confirmed")

    review(run_folder, edit)

    [label] = read_reviewed_run(run_folder, RECEIPT)
    assert label.truth == date(2026, 3, 4)


def test_a_sheet_saved_with_semicolons_and_capitalised_verdicts_reads_the_same(
    run_folder: Path,
) -> None:
    # Excel saves CSV with the list separator of the region: ";" in pt-BR.
    review(run_folder, judge("a.png", "total", " Corrected ", "19.90"), delimiter=";")

    [label] = read_reviewed_run(run_folder, RECEIPT)
    assert (label.verdict, label.truth) == ("corrected", Decimal("19.90"))


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            judge("a.png", "total", "ok"),
            r"row 5 \(a.png, total\): unknown verdict",
            id="unknown-verdict",
        ),
        pytest.param(
            judge("a.png", "total", "corrected"),
            r"row 5 \(a.png, total\): corrected needs",
            id="corrected-without-value",
        ),
        pytest.param(
            judge("a.png", "total", "corrected", "12,50"),
            r"row 5 \(a.png, total\): .*decimal",
            id="decimal-comma",
        ),
        pytest.param(
            judge("a.png", "date", "corrected", "04/03/2026"),
            r"row 4 \(a.png, date\): .*YYYY-MM-DD",
            id="date-not-iso",
        ),
        pytest.param(
            judge("a.png", "currency", "corrected", "myr"),
            r"row 6 \(a.png, currency\): .*pattern",
            id="currency-not-iso-4217",
        ),
        pytest.param(
            judge("a.png", "total", "confirmed", "19.90"),
            r"row 5 .*only a corrected verdict",
            id="confirmed-with-value",
        ),
        pytest.param(
            judge("a.png", "total", "not_on_page", "19.90"),
            r"row 5 .*only a corrected verdict",
            id="not-on-page-with-value",
        ),
        pytest.param(
            judge("a.png", "total", "", "19.90"),
            r"row 5 .*correct_value but no verdict",
            id="value-without-verdict",
        ),
        pytest.param(
            judge("c.png", "", "confirmed"),
            r"row 12 \(c.png\): .*no fields to review",
            id="verdict-on-failed-document",
        ),
    ],
)
def test_a_verdict_that_cannot_become_a_label_fails_naming_the_row(
    run_folder: Path, edit: Callable[[list[Row]], object], message: str
) -> None:
    review(run_folder, edit)

    with pytest.raises(ReviewError, match=message) as raised:
        read_reviewed_run(run_folder, RECEIPT)
    # The message may reach a log: it names the row, never the value typed
    # (AGENTS.md invariant 6).
    for typed in ("12,50", "04/03/2026", "19.90", "myr"):
        assert typed not in str(raised.value)


def test_a_row_the_run_did_not_write_fails(run_folder: Path) -> None:
    review(run_folder, judge("a.png", "total", "confirmed"))
    review(run_folder, lambda rows: rows.append({**rows[0], "file": "z.png"}))

    with pytest.raises(ReviewError, match=r"row 13 \(z.png, company\): not in this run"):
        read_reviewed_run(run_folder, RECEIPT)


def test_a_field_in_two_rows_fails(run_folder: Path) -> None:
    # Two rows for one field (a pasted row) leave its verdict ambiguous.
    review(run_folder, lambda rows: rows.append({**rows[0], "verdict": "confirmed"}))

    with pytest.raises(ReviewError, match=r"row 13 \(a.png, company\): also in row 2"):
        read_reviewed_run(run_folder, RECEIPT)


def test_a_sheet_without_the_verdict_columns_fails(run_folder: Path) -> None:
    # A sheet written before #63, or one whose columns a reviewer deleted.
    path = run_folder / "results.csv"
    header, *rest = path.read_text(encoding="utf-8-sig").splitlines()
    path.write_text("\n".join([header.replace(',"verdict"', ""), *rest]), encoding="utf-8-sig")

    with pytest.raises(ReviewError, match=r"results\.csv has no verdict column"):
        read_reviewed_run(run_folder, RECEIPT)


def test_a_sheet_not_saved_as_utf8_fails_saying_how_to_save_it(run_folder: Path) -> None:
    path = run_folder / "results.csv"
    path.write_bytes(path.read_text(encoding="utf-8-sig").replace("ACME", "Café").encode("cp1252"))

    with pytest.raises(ReviewError, match="CSV UTF-8"):
        read_reviewed_run(run_folder, RECEIPT)
