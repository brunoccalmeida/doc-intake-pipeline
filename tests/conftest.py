"""Fixtures shared by more than one test module."""

import os

import pytest

# Every API key variable the settings read (core/config.py).
API_KEY_VARIABLES = ("DOC_INTAKE_ANTHROPIC_API_KEY", "DOC_INTAKE_OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def no_real_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank every API key for every test (AGENTS.md invariant 4: no paid calls).

    ``Settings`` reads ``.env`` from the working directory, and pytest runs from
    the project root, where a developer keeps a real key. An environment
    variable wins over ``.env``, so an empty one hides that key: building a real
    provider fails with ``MissingApiKeyError`` instead of calling the API. A test
    that needs a key passes it explicitly. Autouse, so no test has to remember.
    """
    for name in API_KEY_VARIABLES:
        monkeypatch.setenv(name, "")


@pytest.fixture
def no_doc_intake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ``DOC_INTAKE_*`` variable for the test, except the blanked keys.

    A developer's shell (an exported API key after a manual run, say) must not
    change a test's outcome. The keys stay blank (``no_real_api_key``): removing
    them would let ``.env`` supply the real one again. Not autouse: the OCR
    tests read the configured tessdata directory on purpose.
    """
    for name in list(os.environ):
        if name.startswith("DOC_INTAKE_") and name not in API_KEY_VARIABLES:
            monkeypatch.delenv(name)
