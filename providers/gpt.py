"""OpenAI models through the Responses API, with strict structured output.

Strict mode requires every property in ``required`` and ``additionalProperties:
false`` on every object (OpenAI docs, "Structured model outputs"). The SDK's
``to_strict_json_schema`` is the same conversion its own ``responses.parse``
uses; it lives in ``openai.lib._pydantic``, an underscored module, so an SDK
upgrade could move it: the schema test in ``tests/test_providers.py`` exercises
it and fails loudly if it does.
"""

import openai
from openai.lib._pydantic import to_strict_json_schema
from openai.types.responses import ResponseFormatTextJSONSchemaConfigParam
from pydantic import BaseModel

from core.llm import LLMRequest, LLMResponse

MAX_OUTPUT_TOKENS = 16_000


class MissingUsageError(RuntimeError):
    """The response carried no token usage, so its cost cannot be known."""


def openai_text_format(
    name: str, schema: type[BaseModel]
) -> ResponseFormatTextJSONSchemaConfigParam:
    return {
        "type": "json_schema",
        "name": name,
        "schema": to_strict_json_schema(schema),
        "strict": True,
    }


class OpenAIProvider:
    """An ``LLMProvider`` backed by the OpenAI Responses API."""

    def __init__(self, *, api_key: str, model: str) -> None:
        # The SDK retries connection errors, 408, 409, 429 and 5xx itself.
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        response = self._client.responses.create(
            model=self._model,
            instructions=request.instructions,
            input=request.prompt,
            text={"format": openai_text_format(request.schema_name, request.output_schema)},
            max_output_tokens=MAX_OUTPUT_TOKENS,
            # Client documents are not kept on OpenAI's side for later retrieval.
            store=False,
        )
        if response.usage is None:
            raise MissingUsageError(f"response {response.id} has no usage")
        # A refusal or an incomplete answer breaks the schema; the engine's
        # validation catches that and retries.
        return LLMResponse(
            text=response.output_text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )
