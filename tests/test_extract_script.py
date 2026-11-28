"""``uv run poe extract``: the checks that must run before any paid call.

The happy path needs a real provider and costs money, so it is a manual run
(AGENTS.md invariant 4); what is tested here fails before any call.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from doc_intake.core.config import Settings
from doc_intake.core.llm import LLMProvider, LLMRequest, LLMResponse
from doc_intake.core.pricing import UnknownModelPriceError
from doc_intake.packs.invoice import Invoice
from doc_intake.packs.receipt import RECEIPT, Receipt
from doc_intake.providers import MissingCredentialError
from scripts import extract_document, packs
from scripts.extract_document import main


def test_a_model_without_a_price_fails_before_reading_or_calling(
    no_doc_intake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "model-x")
    # Neither the file nor a key exists: the price check is what fails first.
    with pytest.raises(UnknownModelPriceError, match="'model-x'"):
        main([str(tmp_path / "missing.pdf")])


def test_an_unreadable_file_is_logged_by_its_hash_never_its_name(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    # A key that cannot reach anyone: the file fails to read before any call.
    monkeypatch.setenv("DOC_INTAKE_ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    path = tmp_path / "ACME-client-receipt.txt"
    path.write_bytes(b"not a receipt")

    code = main([str(path)])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    [line] = [json.loads(text) for text in captured.err.splitlines() if text.startswith("{")]
    assert line["document_id"] == hashlib.sha256(b"not a receipt").hexdigest()
    assert line["status"] == "failed"
    assert line["errors"] == ["UnsupportedFileTypeError"]
    assert "ACME" not in json.dumps(line)


def test_a_missing_key_fails_before_reading_the_file(
    no_doc_intake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    with pytest.raises(MissingCredentialError, match="DOC_INTAKE_ANTHROPIC_API_KEY"):
        main([str(tmp_path / "missing.pdf")])


ALL_NULL = json.dumps(
    {
        name: {"value": None, "citation": None, "reason": "not printed"}
        for name in Receipt.model_fields
    }
)


@dataclass
class CountingProvider:
    """Answers every request with an all-null receipt and counts the calls."""

    calls: int = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text=ALL_NULL, input_tokens=100, output_tokens=50, model="claude-opus-5-5"
        )


def printed_page(tmp_path: Path) -> Path:
    path = tmp_path / "page.png"
    image = Image.new("L", (900, 200), color=255)
    ImageDraw.Draw(image).text((40, 60), "TOTAL 9.90", fill=0, font=ImageFont.load_default(size=64))
    image.save(path)
    return path


def test_a_recorded_extraction_replays_with_no_key_and_no_call(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    page = printed_page(tmp_path)
    recordings = tmp_path / "recordings"
    provider = CountingProvider()

    def counted(settings: Settings) -> LLMProvider:
        return provider

    monkeypatch.setattr(extract_document, "make_provider", counted)

    recorded = main(["--record", str(recordings), str(page)])
    recorded_out = capsys.readouterr().out
    # Replay must not reach any provider: one that is built would fail the test.
    monkeypatch.setattr(extract_document, "make_provider", unreachable_provider)
    replayed = main(["--replay", str(recordings), str(page)])

    assert provider.calls == 1
    assert len(list(recordings.glob("*.json"))) == 1  # stored where asked, nowhere else
    assert recorded == replayed
    assert capsys.readouterr().out == recorded_out
    assert json.loads(recorded_out)["fields"]["currency"]["reason"] == "not printed"


def test_replay_without_a_recording_fails_naming_the_fix(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")

    code = main(["--replay", str(tmp_path / "empty"), str(printed_page(tmp_path))])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no recording" in captured.err
    # This command's own fix: "poe eval --record" would not record this file,
    # and would pay for every SROIE request not recorded yet.
    assert "poe extract --record" in captured.err
    assert "poe eval" not in captured.err


def unreachable_provider(settings: object) -> LLMProvider:
    raise AssertionError("replay built a real provider")


INVOICE_ALL_NULL = json.dumps(
    {
        name: {"value": None, "citation": None, "reason": "not printed"}
        for name in Invoice.model_fields
    }
)


def test_the_invoice_pack_is_chosen_with_pack(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    requests: list[LLMRequest] = []

    class InvoiceProvider:
        def complete(self, request: LLMRequest) -> LLMResponse:
            requests.append(request)
            return LLMResponse(
                text=INVOICE_ALL_NULL, input_tokens=100, output_tokens=50, model="claude-opus-5-5"
            )

    def built(settings: Settings) -> LLMProvider:
        return InvoiceProvider()

    monkeypatch.setattr(extract_document, "make_provider", built)

    code = main(["--pack", "invoice", str(printed_page(tmp_path))])

    assert code == 0
    assert list(json.loads(capsys.readouterr().out)["fields"]) == list(Invoice.model_fields)
    assert "supplier invoice" in requests[0].instructions


def test_the_receipt_pack_is_the_default() -> None:
    # Every documented `uv run poe extract <file>` keeps extracting a receipt.
    assert RECEIPT.name == packs.DEFAULT_PACK
