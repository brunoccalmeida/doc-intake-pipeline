"""Fixtures shared by more than one test module."""

import logging
import os
from collections.abc import Iterator

import pytest

from core.runlog import RUN_LOGGER

# Every credential variable the settings read (core/config.py): the API keys
# and the ant CLI profile, which signs in just as well (D13).
CREDENTIAL_VARIABLES = (
    "DOC_INTAKE_ANTHROPIC_API_KEY",
    "DOC_INTAKE_OPENAI_API_KEY",
    "DOC_INTAKE_ANTHROPIC_PROFILE",
)


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank every credential for every test (AGENTS.md invariant 4: no paid calls).

    ``Settings`` reads ``.env`` from the working directory, and pytest runs from
    the project root, where a developer keeps a real key or profile. An
    environment variable wins over ``.env``, so an empty one hides it (a blank
    profile counts as unset): building a real provider fails with
    ``MissingCredentialError`` instead of calling the API. A test that needs a
    credential passes it explicitly. Autouse, so no test has to remember.
    """
    for name in CREDENTIAL_VARIABLES:
        monkeypatch.setenv(name, "")


@pytest.fixture(autouse=True)
def restore_run_logger() -> Iterator[None]:
    """Leave the run logger as each test found it (test isolation).

    Logging is process-wide state. A script's ``main`` configures the run
    logger not to propagate (``scripts/logs.py``), and pytest's ``caplog``
    listens on the root: without this, a test reading ``caplog`` would pass or
    fail depending on whether a script test ran before it.
    """
    logger = logging.getLogger(RUN_LOGGER)
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate


@pytest.fixture
def no_doc_intake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ``DOC_INTAKE_*`` variable for the test, except the blanked credentials.

    A developer's shell (an exported API key after a manual run, say) must not
    change a test's outcome. The credentials stay blank (``no_real_credentials``): removing
    them would let ``.env`` supply the real one again. Not autouse: the OCR
    tests read the configured tessdata directory on purpose.
    """
    for name in list(os.environ):
        if name.startswith("DOC_INTAKE_") and name not in CREDENTIAL_VARIABLES:
            monkeypatch.delenv(name)
