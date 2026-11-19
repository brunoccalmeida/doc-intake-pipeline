"""Runtime settings, read from the environment and validated once at startup.

Every variable carries the ``DOC_INTAKE_`` prefix so it cannot collide with
another tool's. A ``.env`` in the working directory (kept out of Git; see
``.env.example``) is read when present; real environment variables win over it.
Instantiating ``Settings()`` raises ``ValidationError`` on any invalid value,
so the program stops before touching a document (fail fast).
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Validated configuration of one pipeline run."""

    model_config = SettingsConfigDict(
        env_prefix="DOC_INTAKE_",
        env_file=".env",
        env_file_encoding="utf-8",
        frozen=True,
    )

    log_level: LogLevel = "INFO"
