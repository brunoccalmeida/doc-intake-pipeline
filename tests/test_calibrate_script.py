"""``scripts/calibrate.py``: an acceptance policy from reviewed run folders (#65)."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from doc_intake.acceptance import AcceptancePolicy, FieldEvidence, load_policy
from doc_intake.core.extract import Pack
from doc_intake.packs.invoice import Invoice
from doc_intake.review import Label, ReviewError
from scripts import calibrate
from scripts.calibrate import main

# A value no output may print (AGENTS.md invariant 6).
PRIVATE_TOTAL = Decimal("4321.09")


def total(file: str, truth: Decimal = PRIVATE_TOTAL) -> Label:
    verdict = "confirmed" if truth == PRIVATE_TOTAL else "corrected"
    return Label(file, "total", verdict, PRIVATE_TOTAL, truth, source="image", queued=True)


RUNS = {
    # 356 clean image-read totals: the first count under a 2% target with the
    # eight receipt fields (D22; SciPy oracle in the PR of #66).
    "run-1": [total(f"{i}.png") for i in range(200)],
    "run-2": [
        *(total(f"{i}.png") for i in range(156)),
        Label("x.png", "date", "corrected", None, None, source="image", queued=True),
        Label("y.png", "date", "confirmed", None, None, source="image", queued=True),
        Label("z.png", "company", "confirmed", "ACME", "ACME", source="text"),
    ],
    "text-only": [Label("z.png", "company", "confirmed", "ACME", "ACME", source="text")],
}


def read[S: BaseModel](folder: Path, pack: Pack[S]) -> list[Label]:
    if folder.name == "broken":
        raise ReviewError("row 3 (a.png, total): unknown verdict")
    return RUNS[folder.name]


@pytest.fixture(autouse=True)
def fake_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calibrate, "read_reviewed_run", read)


def test_the_policy_adds_up_every_folder_and_the_table_says_what_it_accepts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path = tmp_path / "policy.json"
    run_1, run_2 = tmp_path / "run-1", tmp_path / "run-2"

    code = main(["--target", "0.02", "--out", str(out_path), str(run_1), str(run_2), str(run_1)])

    assert code == 0
    assert load_policy(out_path) == AcceptancePolicy(
        pack="receipt",
        target=0.02,
        evidence={
            "company": FieldEvidence(reviewed=0, errors=0),
            "address": FieldEvidence(reviewed=0, errors=0),
            "date": FieldEvidence(reviewed=2, errors=0),
            "total": FieldEvidence(reviewed=356, errors=0),
            "currency": FieldEvidence(reviewed=0, errors=0),
            "net": FieldEvidence(reviewed=0, errors=0),
            "tax": FieldEvidence(reviewed=0, errors=0),
            "rounding": FieldEvidence(reviewed=0, errors=0),
        },
        # A folder given twice counts once: twice would narrow the bound.
        runs=["run-1", "run-2"],
    )
    out = capsys.readouterr().out
    # Bounds from the SciPy reference of tests/test_acceptance.py.
    assert out.splitlines()[:9] == [
        "field     reviewed  errors  upper bound  accepted",
        "company          0       0     100.000%  no",
        "address          0       0     100.000%  no",
        "date             2       0      92.251%  no",
        "total          356       0       1.999%  yes",
        "currency         0       0     100.000%  no",
        "net              0       0     100.000%  no",
        "tax              0       0     100.000%  no",
        "rounding         0       0     100.000%  no",
    ]
    assert "target 2.000%" in out
    assert str(PRIVATE_TOTAL) not in out


def test_the_audit_rate_is_configurable(tmp_path: Path) -> None:
    out_path = tmp_path / "policy.json"

    main(
        [
            "--target",
            "0.05",
            "--audit-rate",
            "0.25",
            "--out",
            str(out_path),
            str(tmp_path / "run-1"),
        ]
    )

    assert load_policy(out_path).audit_rate == 0.25


def test_a_policy_that_leaves_out_a_run_the_previous_one_used_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The bound holds however often it is looked at only along one growing
    # sequence of labels: dropping a run with an error would pick the sample.
    out_path = tmp_path / "policy.json"
    main(["--target", "0.02", "--out", str(out_path), str(tmp_path / "run-1")])
    before = out_path.read_text(encoding="utf-8")

    code = main(["--target", "0.02", "--out", str(out_path), str(tmp_path / "run-2")])

    assert code == 1
    assert out_path.read_text(encoding="utf-8") == before
    assert "run-1" in capsys.readouterr().err


def test_a_policy_with_another_target_than_the_previous_one_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A target moved after seeing the labels is chosen to let a field pass.
    out_path = tmp_path / "policy.json"
    main(["--target", "0.02", "--out", str(out_path), str(tmp_path / "run-1")])

    code = main(["--target", "0.05", "--out", str(out_path), str(tmp_path / "run-1")])

    assert code == 1
    assert load_policy(out_path).target == 0.02
    assert "target" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("folder", "message"),
    [
        ("broken", "broken: row 3 (a.png, total): unknown verdict"),
        ("text-only", "no value read from the image was reviewed"),
    ],
)
def test_nothing_to_calibrate_on_exits_1_and_writes_no_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], folder: str, message: str
) -> None:
    out_path = tmp_path / "policy.json"

    code = main(["--target", "0.02", "--out", str(out_path), str(tmp_path / folder)])

    assert code == 1
    assert not out_path.exists()
    assert message in capsys.readouterr().err


def test_the_invoice_pack_calibrates_every_invoice_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    packs: list[str] = []

    def read_invoices[S: BaseModel](folder: Path, pack: Pack[S]) -> list[Label]:
        packs.append(pack.name)
        return [total(f"{i}.jpg") for i in range(356)]

    monkeypatch.setattr(calibrate, "read_reviewed_run", read_invoices)
    out_path = tmp_path / "policy.json"

    code = main(["--pack", "invoice", "--target", "0.02", "--out", str(out_path), str(tmp_path)])

    assert code == 0
    assert packs == ["invoice"]
    policy = load_policy(out_path)
    assert policy.pack == "invoice"
    assert list(policy.evidence) == list(Invoice.model_fields)
    out = capsys.readouterr().out
    assert [line.split()[0] for line in out.splitlines()[1:10]] == list(Invoice.model_fields)
    # Nine invoice fields share the 5%, not the receipt's eight.
    assert "shared by the\n9 fields" in out


def test_a_policy_for_another_pack_is_not_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Each pack has its own policy file: replacing one would drop its labels.
    out_path = tmp_path / "policy.json"
    main(["--target", "0.02", "--out", str(out_path), str(tmp_path / "run-1")])
    before = out_path.read_text(encoding="utf-8")

    code = main(
        ["--pack", "invoice", "--target", "0.02", "--out", str(out_path), str(tmp_path / "run-1")]
    )

    assert code == 1
    assert out_path.read_text(encoding="utf-8") == before
    assert "for the receipt pack, not invoice" in capsys.readouterr().err
