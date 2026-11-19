"""Recorded provider responses: keyed by what was asked, replayed without a network.

The key is a hash of everything that shapes the answer (provider, requested
model, instructions, images, prompt, output schema), so changing any of them needs a
new recording instead of silently scoring a stale one (``docs/ARCHITECTURE.md``
D4). Replay never calls a provider; a missing recording fails, naming the fix.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.llm import ImageInput, LLMRequest, LLMResponse
from core.result import ExtractedField, StrictModel
from evals.recording import (
    PIN_PATH,
    MissingRecordingError,
    RecordingProvider,
    RecordingStore,
    ReplayProvider,
    load_pin,
    request_key,
)


class Sale(StrictModel, frozen=True):
    company: ExtractedField[str]


class OtherSale(StrictModel, frozen=True):
    seller: ExtractedField[str]


IMAGE = ImageInput(label="Image of page 1:", media_type="image/png", data=b"page 1 png")
REQUEST = LLMRequest(
    instructions="Read the seller.",
    images=(IMAGE,),
    prompt="<document>ACME</document>",
    schema_name="sale",
    output_schema=Sale,
)
RESPONSE = LLMResponse(text='{"company": null}', input_tokens=120, output_tokens=30, model="m-1")


@dataclass
class CountingProvider:
    """Answers every request with ``RESPONSE`` and counts the calls."""

    requests: list[LLMRequest] = field(default_factory=list[LLMRequest])

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return RESPONSE


def key(request: LLMRequest = REQUEST, provider: str = "claude", model: str = "m-1") -> str:
    return request_key(request, provider=provider, model=model)


def test_key_is_a_stable_sha256_of_the_request() -> None:
    assert key() == key()
    assert len(key()) == 64
    assert int(key(), 16) >= 0


@pytest.mark.parametrize(
    "changed",
    [
        lambda: key(replace(REQUEST, prompt="<document>OTHER</document>")),
        lambda: key(replace(REQUEST, instructions="Read the buyer.")),
        lambda: key(replace(REQUEST, schema_name="other")),
        lambda: key(replace(REQUEST, output_schema=OtherSale)),
        lambda: key(model="m-2"),
        lambda: key(provider="openai"),
        lambda: key(replace(REQUEST, images=(replace(IMAGE, data=b"other png"),))),
        lambda: key(replace(REQUEST, images=(replace(IMAGE, label="Image of page 2:"),))),
        lambda: key(replace(REQUEST, images=(replace(IMAGE, media_type="image/jpeg"),))),
        lambda: key(replace(REQUEST, images=())),
    ],
    ids=[
        "prompt",
        "instructions",
        "schema-name",
        "schema",
        "model",
        "provider",
        "image-bytes",
        "image-label",
        "image-type",
        "no-image",
    ],
)
def test_key_changes_with_anything_that_shapes_the_answer(changed: object) -> None:
    assert callable(changed)
    assert changed() != key()


def test_recording_calls_the_provider_once_and_replay_returns_the_same(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    inner = CountingProvider()
    recorder = RecordingProvider(inner, store, provider="claude", model="m-1")

    first = recorder.complete(REQUEST)
    again = recorder.complete(REQUEST)
    replayed = ReplayProvider(store, provider="claude", model="m-1").complete(REQUEST)

    assert len(inner.requests) == 1  # an existing recording is not paid for twice
    assert first == again == replayed == RESPONSE


def test_replay_without_a_recording_fails_naming_the_fix(tmp_path: Path) -> None:
    replay = ReplayProvider(RecordingStore(tmp_path), provider="claude", model="m-1")

    with pytest.raises(MissingRecordingError, match=r"poe eval --record") as caught:
        replay.complete(REQUEST)

    assert key() in str(caught.value)


def test_replay_of_another_model_is_missing(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    RecordingProvider(CountingProvider(), store, provider="claude", model="m-1").complete(REQUEST)

    with pytest.raises(MissingRecordingError):
        ReplayProvider(store, provider="claude", model="m-2").complete(REQUEST)


def test_a_corrupted_recording_fails_instead_of_replaying(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    RecordingProvider(CountingProvider(), store, provider="claude", model="m-1").complete(REQUEST)
    (tmp_path / f"{key()}.json").write_text('{"key": "not the key"}', encoding="utf-8")

    with pytest.raises(ValidationError):
        ReplayProvider(store, provider="claude", model="m-1").complete(REQUEST)


def test_a_recording_under_the_wrong_name_fails(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    RecordingProvider(CountingProvider(), store, provider="claude", model="m-1").complete(REQUEST)
    other = key(model="m-2")
    (tmp_path / f"{key()}.json").rename(tmp_path / f"{other}.json")

    with pytest.raises(ValueError, match="holds the recording of another request"):
        ReplayProvider(store, provider="claude", model="m-2").complete(REQUEST)


def test_the_pinned_recordings_commit_is_well_formed() -> None:
    pin = load_pin(PIN_PATH)

    assert pin.repository == "brunoccalmeida/doc-intake-recordings"
    assert len(pin.commit) == 40
