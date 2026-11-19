"""Runtime settings, read from the environment and validated once at startup.

Every variable carries the ``DOC_INTAKE_`` prefix so it cannot collide with
another tool's. A ``.env`` in the working directory (kept out of Git; see
``.env.example``) is read when present; real environment variables win over it.
Instantiating ``Settings()`` raises ``ValidationError`` on any invalid value,
so the program stops before touching a document (fail fast).
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr
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
    )

    log_level: LogLevel = "INFO"
    # Tesseract language data (eng.traineddata), fetched by "uv run poe fetch-tessdata".
    # Not checked here: only OCR needs it, and OCR fails naming the fix when it is missing.
    tessdata_dir: Path = Path(".cache/tessdata")
    # SROIE golden set (images and converted records), fetched by "uv run poe fetch-golden".
    # Outside Git: SROIE has no published licence (docs/DATA.md).
    sroie_dir: Path = Path(".cache/golden/sroie")

    # LLM extraction (docs/ARCHITECTURE.md D2, D3). Each vendor's recommended
    # general-purpose model is the default; the eval (#6) is what should move it.
    provider: ProviderName = "claude"
    claude_model: str = "claude-opus-5-5"
    openai_model: str = "gpt-6.2-astra"
    # Optional here, so ingest and tests run without one; building the
    # configured provider fails naming the missing variable (providers package).
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    # Retries after the first call when the answer fails validation.
    max_retries: Annotated[int, Field(ge=0)] = 2
