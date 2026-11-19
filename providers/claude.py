"""Claude through the Anthropic SDK, with native structured output.

``output_config.format`` constrains the answer to the schema. The API rejects
numeric and string constraints (``minimum``, ``pattern``...), so the SDK's
``transform_schema`` moves them into descriptions; the engine's Pydantic
validation still enforces them (Anthropic docs, "Structured outputs").
"""

import anthropic
from anthropic.types.beta import BetaJSONOutputFormatParam
from pydantic import BaseModel

from core.llm import LLMRequest, LLMResponse

# Room for the JSON and the model's thinking; a non-streaming call stays well
# under the SDK's request timeout at this size (Anthropic SDK guidance).
MAX_TOKENS = 16_000
# Opus 5.5 always thinks; effort sets how much. "medium" is its default,
# written out so a model change does not silently change it. The eval (#6)
# is what should tune it.
EFFORT = "medium"
# On a safety refusal the API re-runs the request on a model it picks for the
# refusal category; LLMResponse.model records which model answered.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def claude_output_format(schema: type[BaseModel]) -> BetaJSONOutputFormatParam:
    return {"type": "json_schema", "schema": anthropic.transform_schema(schema)}


class ClaudeProvider:
    """An ``LLMProvider`` backed by the Claude Messages API."""

    def __init__(self, *, api_key: str, model: str) -> None:
        # The SDK retries connection errors, 408, 409, 429 and 5xx itself.
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        response = self._client.beta.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=request.instructions,
            messages=[{"role": "user", "content": request.prompt}],
            output_config={
                "effort": EFFORT,
                "format": claude_output_format(request.output_schema),
            },
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        # A refusal or a max_tokens stop can break the schema; the engine's
        # validation catches that and retries, so the text is passed as is.
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )
