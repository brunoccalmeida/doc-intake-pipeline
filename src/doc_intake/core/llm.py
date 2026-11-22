"""The provider interface: what the engine asks an LLM and what it gets back.

The engine depends on this ``Protocol``, never on a vendor SDK (dependency
inversion, ``docs/ARCHITECTURE.md`` D2). Concrete providers live in the
``providers`` package and are chosen by configuration; tests use a fake that
implements the same method.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel

type ImageMediaType = Literal["image/png", "image/jpeg"]


@dataclass(frozen=True, slots=True)
class ImageInput:
    """An image the model reads before the prompt, introduced by a short label."""

    label: str
    media_type: ImageMediaType
    data: bytes


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One self-contained call: instructions, images, the user prompt and the output schema.

    ``output_schema`` is the Pydantic model itself, not its JSON Schema: each
    provider turns it into the schema dialect its API enforces, with its SDK's
    own helper. ``images`` go before the prompt, each after its label:
    "Claude works best when images come before text" (Anthropic docs, "Vision").
    """

    instructions: str
    images: tuple[ImageInput, ...]
    prompt: str
    schema_name: str
    output_schema: type[BaseModel]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """The raw answer, unvalidated, with what the call cost in tokens.

    ``model`` is the model that actually answered, which can differ from the
    requested one (a server-side fallback).
    """

    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMProvider(Protocol):
    """Anything that answers an ``LLMRequest``; transport errors propagate."""

    def complete(self, request: LLMRequest) -> LLMResponse: ...


@dataclass
class Metered:
    """Wraps a provider and keeps every response, to report calls and tokens per run."""

    inner: LLMProvider
    responses: list[LLMResponse] = field(default_factory=list[LLMResponse])

    def complete(self, request: LLMRequest) -> LLMResponse:
        response = self.inner.complete(request)
        self.responses.append(response)
        return response
