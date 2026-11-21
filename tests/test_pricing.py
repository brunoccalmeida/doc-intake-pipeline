"""Cost of a call from its token counts, in exact USD (``docs/ARCHITECTURE.md`` D5)."""

from decimal import Decimal

import pytest

from core.pricing import PRICES, UnknownModelPriceError, cost_usd, price_of


def test_cost_is_tokens_times_the_price_per_million_exactly() -> None:
    # Opus 5.5: $4 input and $20 output per million tokens.
    assert cost_usd("claude-opus-5-5", input_tokens=1_500, output_tokens=400) == Decimal("0.014")


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # $0.10 input and $0.50 output per million tokens.
        ("gpt-6-luna", Decimal("0.00035")),
        # $8 input and $40 output per million tokens.
        ("gpt-6.2-astra", Decimal("0.028")),
    ],
)
def test_openai_models_are_priced(model: str, expected: Decimal) -> None:
    assert cost_usd(model, input_tokens=1_500, output_tokens=400) == expected


def test_cost_of_nothing_is_zero() -> None:
    assert cost_usd("claude-opus-5-5", input_tokens=0, output_tokens=0) == 0


def test_a_model_without_a_price_fails_naming_it() -> None:
    with pytest.raises(UnknownModelPriceError, match="'model-x'"):
        cost_usd("model-x", input_tokens=1, output_tokens=1)


def test_price_of_a_known_model_is_its_row() -> None:
    assert price_of("claude-opus-5-5") is PRICES["claude-opus-5-5"]


def test_price_of_an_unknown_model_fails_before_any_call_is_paid() -> None:
    with pytest.raises(UnknownModelPriceError, match="'model-x'"):
        price_of("model-x")


def test_every_price_is_a_non_negative_decimal() -> None:
    for price in PRICES.values():
        assert isinstance(price.input_per_mtok, Decimal)
        assert isinstance(price.output_per_mtok, Decimal)
        assert price.input_per_mtok >= 0
        assert price.output_per_mtok >= 0
