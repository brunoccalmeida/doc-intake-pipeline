"""No test can reach a real API key (AGENTS.md invariant 4).

``Settings`` reads ``.env`` from the working directory, and pytest runs from
the project root, where a developer keeps a real key. ``conftest.py`` blanks
the key variables for every test (environment wins over ``.env``), so building
the configured provider fails instead of making a paid call. Building it here
calls no network either way: the client is only constructed.
"""

from pathlib import Path

import pytest

from doc_intake.core.config import Settings
from doc_intake.providers import MissingCredentialError, make_provider


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_the_configured_provider_cannot_be_built_from_a_developer_s_key(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", provider)

    with pytest.raises(MissingCredentialError):
        make_provider(Settings())


@pytest.mark.usefixtures("no_doc_intake_env")
def test_clearing_the_environment_keeps_the_keys_blank() -> None:
    with pytest.raises(MissingCredentialError):
        make_provider(Settings())


def test_a_developer_s_cli_profile_is_hidden_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A profile in .env would let the provider sign in through the ant CLI and
    # make a paid call, exactly like a key.
    (tmp_path / ".env").write_text("DOC_INTAKE_ANTHROPIC_PROFILE=default\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert Settings().anthropic_profile is None
