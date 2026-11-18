"""Settings come from the environment and are validated once, at startup.

A wrong value must stop the program before it touches any document (fail
fast), naming the variable, instead of surfacing later as odd behaviour.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import Settings


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Run each test in an empty directory with no DOC_INTAKE_ variable set.

    A developer's real .env or shell must not change a test's outcome.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOC_INTAKE_LOG_LEVEL", raising=False)
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
