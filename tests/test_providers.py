"""Concrete providers: chosen by configuration, and their request schemas.

No test here calls a provider (AGENTS.md invariant 4): they build clients and
schemas offline. The live call is the manual run recorded in the PR.
"""

from collections.abc import Iterator
from typing import Any, cast

import pytest
from pydantic import SecretStr

from core.config import Settings
from packs.receipt import Receipt
from providers import MissingApiKeyError, make_provider
from providers.claude import ClaudeProvider, claude_output_format
from providers.gpt import OpenAIProvider, openai_text_format

# The shell's DOC_INTAKE_* variables are cleared for every test here.
pytestmark = pytest.mark.usefixtures("no_doc_intake_env")


def settings(**values: object) -> Settings:
    # _env_file=None: a developer's .env must not change the outcome either.
    return Settings.model_validate({"_env_file": None, **values})


def objects(schema: object) -> Iterator[dict[str, Any]]:
    """Every JSON object schema nested anywhere in ``schema``."""
    if isinstance(schema, dict):
        node = cast(dict[str, Any], schema)
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from objects(value)
    elif isinstance(schema, list):
        for item in cast(list[object], schema):
            yield from objects(item)


def keywords(schema: object) -> set[str]:
    if isinstance(schema, dict):
        node = cast(dict[str, Any], schema)
        found = set(node)
        for key, value in node.items():
            if key != "properties":
                found |= keywords(value)
            else:
                for prop in cast(dict[str, Any], value).values():
                    found |= keywords(prop)
        return found
    if isinstance(schema, list):
        found: set[str] = set()
        for item in cast(list[object], schema):
            found |= keywords(item)
        return found
    return set()


def test_claude_is_built_when_configured() -> None:
    provider = make_provider(settings(provider="claude", anthropic_api_key=SecretStr("k")))
    assert isinstance(provider, ClaudeProvider)


def test_openai_is_built_when_configured() -> None:
    provider = make_provider(settings(provider="openai", openai_api_key=SecretStr("k")))
    assert isinstance(provider, OpenAIProvider)


@pytest.mark.parametrize(
    ("provider", "variable"),
    [("claude", "DOC_INTAKE_ANTHROPIC_API_KEY"), ("openai", "DOC_INTAKE_OPENAI_API_KEY")],
)
def test_missing_key_fails_naming_the_variable(provider: str, variable: str) -> None:
    with pytest.raises(MissingApiKeyError, match=variable):
        make_provider(settings(provider=provider))


def test_claude_schema_requires_every_key_and_forbids_extras() -> None:
    schema = claude_output_format(Receipt)["schema"]
    for node in objects(schema):
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


def test_claude_schema_has_no_keyword_the_api_rejects() -> None:
    # Structured outputs reject numeric and string constraints with a 400; the
    # SDK moves them into descriptions and our Pydantic model enforces them.
    schema = claude_output_format(Receipt)["schema"]
    assert not keywords(schema) & {"minimum", "maximum", "minLength", "maxLength", "pattern"}


def test_openai_schema_is_strict() -> None:
    text_format = openai_text_format("receipt", Receipt)
    assert text_format.get("strict") is True
    assert text_format["name"] == "receipt"
    for node in objects(text_format["schema"]):
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


def test_openai_schema_has_no_ref_beside_other_keys() -> None:
    # Pydantic writes a described field as {"$ref": ..., "description": ...};
    # strict mode needs a $ref alone, so the SDK inlines those.
    def refs(schema: object) -> Iterator[dict[str, Any]]:
        if isinstance(schema, dict):
            node = cast(dict[str, Any], schema)
            if "$ref" in node:
                yield node
            for value in node.values():
                yield from refs(value)
        elif isinstance(schema, list):
            for item in cast(list[object], schema):
                yield from refs(item)

    schema = openai_text_format("receipt", Receipt)["schema"]
    assert all(set(node) == {"$ref"} for node in refs(schema))
