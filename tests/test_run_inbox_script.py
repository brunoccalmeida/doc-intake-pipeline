"""``uv run poe inbox``: one scheduled run over an inbox folder."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from doc_intake.acceptance import AcceptancePolicy, FieldEvidence
from doc_intake.core.llm import LLMProvider
from doc_intake.core.pricing import UnknownModelPriceError
from scripts import run_inbox
from scripts.run_inbox import main

DEMO = Path("demo")


def recorded_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # The provider and model the demo's answers were recorded with.
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")


def unreachable_provider(settings: object) -> LLMProvider:
    raise AssertionError("replay built a real provider")


def test_a_replayed_run_queues_the_review_and_exits_0(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded_model(monkeypatch)
    monkeypatch.setattr(run_inbox, "make_provider", unreachable_provider)
    inbox, runs = tmp_path / "inbox", tmp_path / "runs"
    inbox.mkdir()
    for name in ("receipt.png", "receipt-review.png"):
        shutil.copy(DEMO / name, inbox / name)

    code = main([str(inbox), str(runs), "--settle", "0", "--replay", str(DEMO / "recordings")])

    assert code == 0  # needs_review is the queue working, not an error
    [folder] = list(runs.iterdir())
    out = capsys.readouterr().out
    assert out.splitlines() == [
        f"{folder / 'results.csv'}: 2 documents, 1 needs review, 0 failed",
    ]


def test_a_failed_document_exits_1_so_the_scheduler_flags_the_run(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded_model(monkeypatch)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "broken.pdf").write_bytes(b"not a pdf")

    code = main([str(inbox), str(tmp_path / "runs"), "--settle", "0", "--replay", str(tmp_path)])

    assert code == 1
    assert capsys.readouterr().out.endswith(": 1 documents, 0 needs review, 1 failed\n")


def test_an_empty_inbox_says_so_and_exits_0(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded_model(monkeypatch)
    (tmp_path / "inbox").mkdir()

    code = main([str(tmp_path / "inbox"), str(tmp_path / "runs"), "--replay", str(tmp_path)])

    assert code == 0
    assert capsys.readouterr().out == "nothing ready in the inbox\n"


def test_a_model_without_a_price_fails_before_touching_the_inbox(
    no_doc_intake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "model-x")
    # The inbox does not exist: the price check is what fails first.
    with pytest.raises(UnknownModelPriceError, match="'model-x'"):
        main([str(tmp_path / "inbox"), str(tmp_path / "runs")])


def write_policy(path: Path, *, pack: str = "receipt") -> Path:
    # 356 clean image-read totals: the first count under a 2% target with the
    # receipt's eight fields (D22, D23).
    policy = AcceptancePolicy(
        pack=pack,
        target=0.02,
        evidence={"total": FieldEvidence(reviewed=356, errors=0)},
        runs=["2026-11-22T15-30-00Z"],
    )
    path.write_text(policy.model_dump_json(), encoding="utf-8")
    return path


def test_a_policy_accepts_the_image_read_total_of_the_demo_receipt(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded_model(monkeypatch)
    policy = write_policy(tmp_path / "policy.json")
    monkeypatch.setenv("DOC_INTAKE_ACCEPTANCE_POLICY", str(policy))
    monkeypatch.setattr(run_inbox, "audit_draw", lambda: 0.99)  # not drawn for the audit
    inbox, runs = tmp_path / "inbox", tmp_path / "runs"
    inbox.mkdir()
    for name in ("receipt.png", "receipt-review.png"):
        shutil.copy(DEMO / name, inbox / name)

    code = main([str(inbox), str(runs), "--settle", "0", "--replay", str(DEMO / "recordings")])

    assert code == 0
    assert capsys.readouterr().out.endswith(": 2 documents, 0 needs review, 0 failed\n")


def no_policy(path: Path) -> None:
    pass


def policy_without_target(path: Path) -> None:
    path.write_text('{"pack": "receipt"}', encoding="utf-8")


def invoice_policy(path: Path) -> None:
    write_policy(path, pack="invoice")


def test_a_drawn_audit_sends_the_accepted_total_back_to_the_queue(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded_model(monkeypatch)
    monkeypatch.setenv("DOC_INTAKE_ACCEPTANCE_POLICY", str(write_policy(tmp_path / "p.json")))
    monkeypatch.setattr(run_inbox, "audit_draw", lambda: 0.0)  # under any audit rate
    inbox, runs = tmp_path / "inbox", tmp_path / "runs"
    inbox.mkdir()
    shutil.copy(DEMO / "receipt-review.png", inbox / "receipt-review.png")

    code = main([str(inbox), str(runs), "--settle", "0", "--replay", str(DEMO / "recordings")])

    assert code == 0
    assert capsys.readouterr().out.endswith(": 1 documents, 1 needs review, 0 failed\n")


@pytest.mark.parametrize(
    ("write", "error", "match"),
    [
        (no_policy, FileNotFoundError, "policy.json"),
        (policy_without_target, ValidationError, "target"),
        (invoice_policy, ValueError, "invoice"),
    ],
)
def test_a_policy_that_cannot_be_used_fails_before_touching_the_inbox(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    write: Callable[[Path], object],
    error: type[Exception],
    match: str,
) -> None:
    recorded_model(monkeypatch)
    write(tmp_path / "policy.json")
    monkeypatch.setenv("DOC_INTAKE_ACCEPTANCE_POLICY", str(tmp_path / "policy.json"))
    # The inbox does not exist: the policy is what fails first.
    with pytest.raises(error, match=match):
        main([str(tmp_path / "inbox"), str(tmp_path / "runs"), "--replay", str(tmp_path)])
