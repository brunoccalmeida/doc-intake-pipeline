"""Concrete providers: chosen by configuration, and their request schemas.

No test here calls a provider (AGENTS.md invariant 4): they build clients and
schemas offline. The live call is the manual run recorded in the PR.
"""

import base64
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr

from doc_intake.core.config import Settings
from doc_intake.core.llm import ImageInput, LLMRequest
from doc_intake.packs.receipt import Receipt
from doc_intake.providers import MissingCredentialError, make_provider
from doc_intake.providers.claude import ClaudeProvider, claude_content, claude_output_format
from doc_intake.providers.gpt import OpenAIProvider, openai_input, openai_text_format

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
    with pytest.raises(MissingCredentialError, match=variable):
        make_provider(settings(provider=provider))


def test_claude_without_key_or_profile_names_both_variables() -> None:
    with pytest.raises(
        MissingCredentialError, match=r"DOC_INTAKE_ANTHROPIC_API_KEY.*DOC_INTAKE_ANTHROPIC_PROFILE"
    ):
        make_provider(settings(provider="claude"))


@pytest.fixture
def empty_anthropic_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An ant CLI config directory with no profile in it: no real sign-in is read."""
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))


@pytest.mark.usefixtures("empty_anthropic_config")
def test_claude_with_a_missing_profile_fails_at_construction() -> None:
    # Fails fast, at construction, naming the profile and the fix; no request is sent.
    with pytest.raises(MissingCredentialError, match=r"'work'.*ant auth login --profile work"):
        make_provider(settings(provider="claude", anthropic_profile="work"))


@pytest.mark.usefixtures("empty_anthropic_config")
def test_a_stray_sdk_key_cannot_replace_the_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    # The SDK's own resolution puts ANTHROPIC_API_KEY before any profile; an
    # explicit profile must ignore it, or a leftover export would bill another key.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stray-not-a-real-key")
    with pytest.raises(MissingCredentialError, match="'work'"):
        make_provider(settings(provider="claude", anthropic_profile="work"))


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


IMAGE_REQUEST = LLMRequest(
    instructions="Read the seller.",
    images=(
        ImageInput(label="Image of page 1:", media_type="image/jpeg", data=b"page 1 jpeg"),
        ImageInput(label="Image of page 2:", media_type="image/png", data=b"page 2 png"),
    ),
    prompt="<document>ACME</document>",
    schema_name="receipt",
    output_schema=Receipt,
)


def test_claude_content_puts_each_labelled_image_before_the_prompt() -> None:
    # "Claude works best when images come before text"; a short label before
    # each image ties it to its page (Anthropic docs, "Vision").
    assert claude_content(IMAGE_REQUEST) == [
        {"type": "text", "text": "Image of page 1:"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(b"page 1 jpeg").decode(),
            },
        },
        {"type": "text", "text": "Image of page 2:"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(b"page 2 png").decode(),
            },
        },
        {"type": "text", "text": "<document>ACME</document>"},
    ]


def test_openai_input_puts_each_labelled_image_before_the_prompt_at_original_detail() -> None:
    # "original" is what OpenAI recommends for OCR-like fine detail
    # (OpenAI docs, "Images and vision").
    jpeg = base64.b64encode(b"page 1 jpeg").decode()
    png = base64.b64encode(b"page 2 png").decode()
    assert openai_input(IMAGE_REQUEST) == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Image of page 1:"},
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{jpeg}",
                    "detail": "original",
                },
                {"type": "input_text", "text": "Image of page 2:"},
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{png}",
                    "detail": "original",
                },
                {"type": "input_text", "text": "<document>ACME</document>"},
            ],
        }
    ]


def test_request_without_images_is_the_prompt_alone() -> None:
    plain = replace(IMAGE_REQUEST, images=())
    assert claude_content(plain) == [{"type": "text", "text": "<document>ACME</document>"}]
    assert openai_input(plain) == [
        {"role": "user", "content": [{"type": "input_text", "text": "<document>ACME</document>"}]}
    ]


@pytest.mark.parametrize(
    "credential", [{}, {"api_key": "k", "profile": "work"}], ids=["none", "both"]
)
def test_claude_takes_exactly_one_credential(credential: dict[str, str]) -> None:
    # With none, the SDK would fall back to its implicit discovery (D13).
    with pytest.raises(ValueError, match="exactly one"):
        ClaudeProvider(model="claude-opus-5-5", **credential)
