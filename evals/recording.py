"""Record provider responses once, with a real key, and replay them in CI for free.

A recording is keyed by the SHA-256 of everything that shapes the answer: the
provider, the requested model, the instructions, the prompt and the output
schema (``docs/ARCHITECTURE.md`` D4). Change any of them, a prompt edit or a
new model, and the key changes: replay then fails, asking for a new recording
instead of scoring an answer to a question nobody asks anymore. A retry is a
request like any other (its prompt holds the rejected answer), so a whole
extraction replays call by call.

The recordings hold document content (the model's answer quotes the receipt),
so they live outside this public repository (``docs/DATA.md``).
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from pydantic import Field

from core.llm import LLMProvider, LLMRequest, LLMResponse
from core.result import StrictModel

RECORD_COMMAND = "uv run poe eval --record"
# Which commit of the private recordings repository CI replays: pinned like an
# action's SHA, so the same pipeline commit always scores the same recordings.
PIN_PATH = Path(__file__).parent / "recordings.json"

type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RecordingsPin(StrictModel, frozen=True):
    repository: Annotated[str, Field(pattern=r"^[\w.-]+/[\w.-]+$")]  # GitHub owner/repo
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


def load_pin(path: Path) -> RecordingsPin:
    return RecordingsPin.model_validate_json(path.read_text(encoding="utf-8"))


class RecordedResponse(StrictModel, frozen=True):
    text: str
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    model: str


class Recording(StrictModel, frozen=True):
    """One stored answer and what it answered: the key, provider and requested model."""

    key: Sha256
    provider: str
    model: str
    response: RecordedResponse


class MissingRecordingError(LookupError):
    """No recording answers this request: the prompt, schema or model changed."""


def request_key(request: LLMRequest, *, provider: str, model: str) -> str:
    """SHA-256 of a canonical JSON of the request, the provider and the requested model."""
    canonical = json.dumps(
        {
            "provider": provider,
            "model": model,
            "instructions": request.instructions,
            "prompt": request.prompt,
            "schema_name": request.schema_name,
            "schema": request.output_schema.model_json_schema(),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class RecordingStore:
    """A directory of ``<key>.json`` files, one per recorded request."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def get(self, key: str) -> LLMResponse | None:
        path = self.directory / f"{key}.json"
        if not path.is_file():
            return None
        recording = Recording.model_validate_json(path.read_text(encoding="utf-8"))
        if recording.key != key:
            raise ValueError(f"{path.name} holds the recording of another request")
        return LLMResponse(**recording.response.model_dump())

    def put(self, key: str, *, provider: str, model: str, response: LLMResponse) -> None:
        recording = Recording(
            key=key,
            provider=provider,
            model=model,
            response=RecordedResponse(**asdict(response)),
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{key}.json"
        # newline="\n": the same bytes on every OS, so the recordings repository
        # does not churn when it is written from Windows.
        path.write_text(recording.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")


class ReplayProvider:
    """An ``LLMProvider`` that only answers from recordings; it never calls the network."""

    def __init__(self, store: RecordingStore, *, provider: str, model: str) -> None:
        self._store = store
        self._provider = provider
        self._model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        key = request_key(request, provider=self._provider, model=self._model)
        response = self._store.get(key)
        if response is None:
            raise MissingRecordingError(
                f"no recording {key} for provider {self._provider!r}, model {self._model!r}: "
                f"the prompt, schema or model changed; record locally with a real key "
                f"('{RECORD_COMMAND}', costs money) and publish the recordings"
            )
        return response


class RecordingProvider:
    """Answers from a recording when there is one; otherwise asks ``inner`` and records it."""

    def __init__(
        self, inner: LLMProvider, store: RecordingStore, *, provider: str, model: str
    ) -> None:
        self._inner = inner
        self._store = store
        self._provider = provider
        self._model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        key = request_key(request, provider=self._provider, model=self._model)
        recorded = self._store.get(key)
        if recorded is not None:
            return recorded
        response = self._inner.complete(request)
        self._store.put(key, provider=self._provider, model=self._model, response=response)
        return response
