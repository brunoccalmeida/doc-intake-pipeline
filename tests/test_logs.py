"""Where the scripts send the run log: JSON lines on stderr, at the configured level."""

import json

import pytest

from doc_intake.core.ingest import EmptyDocumentError
from doc_intake.core.runlog import log_unreadable
from scripts.logs import configure_run_log


def emit() -> None:
    log_unreadable(
        EmptyDocumentError("x"), pack_name="sale", document_id="d", run_id="r", provider_name="p"
    )


def test_each_entry_is_one_bare_json_line_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    configure_run_log("INFO")
    emit()

    captured = capsys.readouterr()
    assert captured.out == ""
    [line] = captured.err.splitlines()
    assert json.loads(line)["document_id"] == "d"


def test_configuring_twice_does_not_duplicate_lines(capsys: pytest.CaptureFixture[str]) -> None:
    configure_run_log("INFO")
    configure_run_log("INFO")
    emit()

    assert len(capsys.readouterr().err.splitlines()) == 1


def test_a_level_above_info_silences_the_run_log(capsys: pytest.CaptureFixture[str]) -> None:
    configure_run_log("WARNING")
    emit()

    assert capsys.readouterr().err == ""
