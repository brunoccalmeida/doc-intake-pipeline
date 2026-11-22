"""Concrete LLM providers, chosen by configuration (``docs/ARCHITECTURE.md`` D2).

This package is the only place a vendor SDK is imported; ruff's banned-api
rule (TID251) rejects ``anthropic`` or ``openai`` anywhere else, so ``core``
stays vendor-neutral and switching providers is a setting.
"""

from pydantic import SecretStr

from doc_intake.core.config import Settings
from doc_intake.core.llm import LLMProvider
from doc_intake.providers.claude import ClaudeProvider
from doc_intake.providers.credentials import MissingCredentialError
from doc_intake.providers.gpt import OpenAIProvider

__all__ = ["MissingCredentialError", "make_provider"]


def make_provider(settings: Settings) -> LLMProvider:
    """Build the provider ``settings.provider`` names, with its credential and model."""
    match settings.provider:
        case "claude":
            # Settings already refuses a key and a profile together (D13).
            if settings.anthropic_profile:
                return ClaudeProvider(
                    profile=settings.anthropic_profile, model=settings.claude_model
                )
            key = _require(
                settings.anthropic_api_key,
                "DOC_INTAKE_ANTHROPIC_API_KEY, or DOC_INTAKE_ANTHROPIC_PROFILE after"
                ' "ant auth login",',
            )
            return ClaudeProvider(api_key=key, model=settings.claude_model)
        case "openai":
            key = _require(settings.openai_api_key, "DOC_INTAKE_OPENAI_API_KEY")
            return OpenAIProvider(api_key=key, model=settings.openai_model)


def _require(key: SecretStr | None, variable: str) -> str:
    if key is None or not key.get_secret_value().strip():
        raise MissingCredentialError(
            f"set {variable} (in the environment or .env) to use this provider"
        )
    return key.get_secret_value()
