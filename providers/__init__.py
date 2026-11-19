"""Concrete LLM providers, chosen by configuration (``docs/ARCHITECTURE.md`` D2).

This package is the only place a vendor SDK is imported; ruff's banned-api
rule (TID251) rejects ``anthropic`` or ``openai`` anywhere else, so ``core``
stays vendor-neutral and switching providers is a setting.
"""

from pydantic import SecretStr

from core.config import Settings
from core.llm import LLMProvider
from providers.claude import ClaudeProvider
from providers.gpt import OpenAIProvider


class MissingApiKeyError(Exception):
    """The configured provider has no API key; the message names the variable."""


def make_provider(settings: Settings) -> LLMProvider:
    """Build the provider ``settings.provider`` names, with its key and model."""
    match settings.provider:
        case "claude":
            key = _require(settings.anthropic_api_key, "DOC_INTAKE_ANTHROPIC_API_KEY")
            return ClaudeProvider(api_key=key, model=settings.claude_model)
        case "openai":
            key = _require(settings.openai_api_key, "DOC_INTAKE_OPENAI_API_KEY")
            return OpenAIProvider(api_key=key, model=settings.openai_model)


def _require(key: SecretStr | None, variable: str) -> str:
    if key is None or not key.get_secret_value().strip():
        raise MissingApiKeyError(
            f"set {variable} (in the environment or .env) to use this provider"
        )
    return key.get_secret_value()
