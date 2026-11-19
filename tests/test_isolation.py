"""No test can reach a real API key (AGENTS.md invariant 4).

``Settings`` reads ``.env`` from the working directory, and pytest runs from
the project root, where a developer keeps a real key. ``conftest.py`` blanks
the key variables for every test (environment wins over ``.env``), so building
the configured provider fails instead of making a paid call. Building it here
calls no network either way: the client is only constructed.
"""

import pytest

from core.config import Settings
from providers import MissingApiKeyError, make_provider


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_the_configured_provider_cannot_be_built_from_a_developer_s_key(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", provider)

    with pytest.raises(MissingApiKeyError):
        make_provider(Settings())


@pytest.mark.usefixtures("no_doc_intake_env")
def test_clearing_the_environment_keeps_the_keys_blank() -> None:
    with pytest.raises(MissingApiKeyError):
        make_provider(Settings())
