"""``uv run poe extract``: the checks that must run before any paid call.

The happy path needs a real provider and costs money, so it is a manual run
(AGENTS.md invariant 4); what is tested here fails before any call.
"""

import hashlib
import json
from pathlib import Path

import pytest

from core.pricing import UnknownModelPriceError
from providers import MissingCredentialError
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
