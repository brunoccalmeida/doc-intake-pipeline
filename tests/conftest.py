"""Fixtures shared by more than one test module."""

import os

import pytest


@pytest.fixture
def no_doc_intake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ``DOC_INTAKE_*`` variable for the test.

    A developer's shell (an exported API key after a manual run, say) must not
    change a test's outcome. Not autouse: the OCR tests read the configured
    tessdata directory on purpose.
    """
    for name in list(os.environ):
        if name.startswith("DOC_INTAKE_"):
            monkeypatch.delenv(name)
