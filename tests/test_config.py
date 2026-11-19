"""Settings come from the environment and are validated once, at startup.

A wrong value must stop the program before it touches any document (fail
fast), naming the variable, instead of surfacing later as odd behaviour.
"""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import Settings


@pytest.fixture(autouse=True)
def isolated(no_doc_intake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Run each test in an empty directory with no DOC_INTAKE_ variable set.

    A developer's real .env or shell must not change a test's outcome. The
    blanked API keys (conftest.no_real_api_key) are removed too, after moving
    to a directory with no .env, so the defaults themselves are tested.
    """
    monkeypatch.chdir(tmp_path)
    for name in [name for name in os.environ if name.startswith("DOC_INTAKE_")]:
        monkeypatch.delenv(name)
    return tmp_path


def test_defaults_when_nothing_is_configured() -> None:
    assert Settings().log_level == "INFO"


def test_value_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOC_INTAKE_LOG_LEVEL", "DEBUG")
    assert Settings().log_level == "DEBUG"


def test_value_is_read_from_dotenv(isolated: Path) -> None:
    (isolated / ".env").write_text("DOC_INTAKE_LOG_LEVEL=WARNING\n", encoding="utf-8")
    assert Settings().log_level == "WARNING"


def test_environment_wins_over_dotenv(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated / ".env").write_text("DOC_INTAKE_LOG_LEVEL=WARNING\n", encoding="utf-8")
    monkeypatch.setenv("DOC_INTAKE_LOG_LEVEL", "ERROR")
    assert Settings().log_level == "ERROR"


def test_invalid_value_fails_naming_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOC_INTAKE_LOG_LEVEL", "LOUD")
    with pytest.raises(ValidationError, match="log_level"):
        Settings()


def test_tessdata_dir_defaults_to_the_project_cache() -> None:
    assert Settings().tessdata_dir == Path(".cache/tessdata")


def test_tessdata_dir_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOC_INTAKE_TESSDATA_DIR", "/opt/tessdata")
    assert Settings().tessdata_dir == Path("/opt/tessdata")


def test_extraction_defaults() -> None:
    settings = Settings()
    assert settings.provider == "claude"
    assert settings.max_retries == 2
    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is None


def test_recordings_dir_defaults_to_the_project_cache() -> None:
    assert Settings().recordings_dir == Path(".cache/recordings")


@pytest.mark.parametrize(
    ("provider", "model"), [("claude", "claude-opus-5-5"), ("openai", "gpt-6.2-astra")]
)
def test_model_is_the_selected_provider_s(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str
) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", provider)
    assert Settings().model == model


def test_negative_retries_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOC_INTAKE_MAX_RETRIES", "-1")
    with pytest.raises(ValidationError, match="max_retries"):
        Settings()


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "gemini")
    with pytest.raises(ValidationError, match="provider"):
        Settings()


def test_api_key_is_hidden_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    # A key printed in a traceback or log line is a leaked key.
    monkeypatch.setenv("DOC_INTAKE_ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    settings = Settings()
    assert "sk-test-not-a-real-key" not in repr(settings)
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-test-not-a-real-key"
