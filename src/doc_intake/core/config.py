"""Runtime settings, read from the environment and validated once at startup.

Every variable carries the ``DOC_INTAKE_`` prefix so it cannot collide with
another tool's. A ``.env`` in the working directory (kept out of Git; see
``.env.example``) is read when present; real environment variables win over it.
Instantiating ``Settings()`` raises ``ValidationError`` on any invalid value,
so the program stops before touching a document (fail fast).
"""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type ProviderName = Literal["claude", "openai"]


class Settings(BaseSettings):
    """Validated configuration of one pipeline run."""

    model_config = SettingsConfigDict(
        env_prefix="DOC_INTAKE_",
        env_file=".env",
        env_file_encoding="utf-8",
        frozen=True,
        # A validation error would print the raw input, keys included (they
        # become SecretStr only after validation).
        hide_input_in_errors=True,
    )

    log_level: LogLevel = "INFO"
    # Tesseract language data (eng.traineddata), fetched by "uv run poe fetch-tessdata".
    # Not checked here: only OCR needs it, and OCR fails naming the fix when it is missing.
    tessdata_dir: Path = Path(".cache/tessdata")
    # SROIE golden set (images and converted records), fetched by "uv run poe fetch-golden".
    # Outside Git: SROIE has no published licence (docs/DATA.md).
    sroie_dir: Path = Path(".cache/golden/sroie")
    # Recorded provider responses the eval replays: a clone of the private
    # recordings repository (they quote the documents; docs/DATA.md).
    recordings_dir: Path = Path(".cache/recordings")

    # LLM extraction (docs/ARCHITECTURE.md D2, D3). Each vendor's recommended
    # general-purpose model is the default; the eval (#6) is what should move it.
    provider: ProviderName = "claude"
    claude_model: str = "claude-opus-5-5"
    openai_model: str = "gpt-6.2-astra"
    # Optional here, so ingest and tests run without one; building the
    # configured provider fails naming the missing variable (providers package).
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    # An "ant auth login" profile, the alternative to a stored Anthropic key
    # for local runs (docs/ARCHITECTURE.md D13). Blank counts as unset.
    anthropic_profile: str | None = None
    # Retries after the first call when the answer fails validation.
    max_retries: Annotated[int, Field(ge=0)] = 2

    @field_validator("anthropic_profile", mode="before")
    @classmethod
    def _blank_profile_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _one_anthropic_credential(self) -> Self:
        key = self.anthropic_api_key
        if key is not None and key.get_secret_value().strip() and self.anthropic_profile:
            raise ValueError(
                "set DOC_INTAKE_ANTHROPIC_API_KEY or DOC_INTAKE_ANTHROPIC_PROFILE, not both:"
                " with two credentials it is unclear which account a run bills"
            )
        return self

    @property
    def model(self) -> str:
        """The model of the selected provider: what a run asks for."""
        match self.provider:
            case "claude":
                return self.claude_model
            case "openai":
                return self.openai_model
