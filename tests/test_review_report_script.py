"""``scripts/review_report.py``: the error report of reviewed run folders, printed (#64)."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from doc_intake.core.extract import Pack
from doc_intake.review import Label, ReviewError
from scripts import review_report
from scripts.review_report import main

# Values no test output may print (AGENTS.md invariant 6).
PRIVATE_TOTAL = Decimal("4321.09")
PRIVATE_COMPANY = "Hidden Corp"


def total(file: str, suggested: Decimal, truth: Decimal) -> Label:
    verdict = "confirmed" if suggested == truth else "corrected"
    return Label(file, "total", verdict, suggested, truth, source="image")


RUNS = {
    "run-1": [
        total("a.png", PRIVATE_TOTAL, PRIVATE_TOTAL),
        total("b.png", PRIVATE_TOTAL, Decimal("1.00")),
        Label("a.png", "company", "confirmed", PRIVATE_COMPANY, PRIVATE_COMPANY, source="text"),
    ],
    "run-2": [total("c.png", PRIVATE_TOTAL, PRIVATE_TOTAL)],
    "unreviewed": [],
}


def read[S: BaseModel](folder: Path, pack: Pack[S]) -> list[Label]:
    if folder.name == "broken":
        raise ReviewError("row 3 (a.png, total): unknown verdict")
    return RUNS[folder.name]


@pytest.fixture(autouse=True)
def fake_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_report, "read_reviewed_run", read)


def test_the_report_adds_up_every_folder_and_prints_no_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([str(tmp_path / "run-1"), str(tmp_path / "run-2")])

    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[:3] == [
        "field    source  reviewed  errors  error rate  upper 95%",
        "company  text           1       0       0.00%     95.00%",
        "total    image          3       1      33.33%     86.46%",
    ]
    assert "Clopper-Pearson" in out
    assert str(PRIVATE_TOTAL) not in out
    assert PRIVATE_COMPANY not in out


def test_a_folder_that_cannot_be_read_fails_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([str(tmp_path / "run-1"), str(tmp_path / "broken")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == "broken: row 3 (a.png, total): unknown verdict\n"


def test_folders_with_no_reviewed_field_fail_saying_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([str(tmp_path / "unreviewed")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "no reviewed field" in captured.err
