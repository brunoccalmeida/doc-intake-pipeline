"""Price per million tokens of each model, and the cost of a call in exact USD.

Prices change, so the table is versioned with the date it was checked and its
source, the vendor's official pricing page (``docs/ARCHITECTURE.md`` D5). Cost
uses the model that actually answered (``LLMResponse.model``), which a
server-side fallback can make differ from the one requested. A model missing
from the table fails instead of costing zero: an unpriced run would look free.

Only base input and output rates: the pipeline uses no prompt caching yet, so
cache write and read rates would be dead entries (YAGNI).
"""

from dataclasses import dataclass
from decimal import Decimal

PRICES_CHECKED_ON = "2026-11-19"
PRICES_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class Price:
    input_per_mtok: Decimal
    output_per_mtok: Decimal


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(input_per_mtok=Decimal(4), output_per_mtok=Decimal(20)),
}


class UnknownModelPriceError(KeyError):
    """The model has no row in ``PRICES``: add it, with its source, before running."""


def price_of(model: str) -> Price:
    """The model's row; call it on the configured model before a paid call (fail fast)."""
    try:
        return PRICES[model]
    except KeyError:
        raise UnknownModelPriceError(
            f"no price for model {model!r}; add it to core/pricing.py from {PRICES_SOURCE}"
        ) from None


def cost_usd(model: str, *, input_tokens: int, output_tokens: int) -> Decimal:
    price = price_of(model)
    return (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / _MILLION
