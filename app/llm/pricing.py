"""Model prices, for the estimated cost in the usage records.

USD per million tokens (input, output), from the Mistral model pages on
2026-10-13. Verify before relying on a cost figure: prices change.
"""

from decimal import Decimal

FAKE_MODEL = "fake"

PRICES_USD_PER_MILLION: dict[str, tuple[Decimal, Decimal]] = {
    "mistral-small-2603": (Decimal("0.15"), Decimal("0.60")),
    "mistral-medium-2604": (Decimal("1.50"), Decimal("7.50")),
    FAKE_MODEL: (Decimal("0"), Decimal("0")),
}

MILLION = Decimal(1_000_000)


class UnknownModelPriceError(Exception):
    pass


def require_known_price(model: str) -> None:
    """Called at startup: a model without a price would make spend invisible."""
    if model not in PRICES_USD_PER_MILLION:
        raise UnknownModelPriceError(
            f"No price is known for model '{model}'. Add it to app/llm/pricing.py."
        )


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    require_known_price(model)
    input_price, output_price = PRICES_USD_PER_MILLION[model]
    return (input_tokens * input_price + output_tokens * output_price) / MILLION
