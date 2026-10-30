"""Versioned LLM pricing table and token cost estimation."""

from decimal import ROUND_HALF_UP, Decimal

# Pricing structure: (input_cost_per_million_usd, output_cost_per_million_usd)
PRICING_TABLE_PER_MILLION: dict[str, dict[str, tuple[Decimal, Decimal]]] = {
    "gemini": {
        "gemini-1.5-flash": (Decimal("0.075"), Decimal("0.30")),
        "gemini-1.5-pro": (Decimal("1.25"), Decimal("5.00")),
        "gemini-2.0-flash": (Decimal("0.10"), Decimal("0.40")),
        "gemini-2.0-flash-lite": (Decimal("0.075"), Decimal("0.30")),
        "gemini-2.5-flash": (Decimal("0.10"), Decimal("0.40")),
        "gemini-2.5-pro": (Decimal("1.25"), Decimal("5.00")),
    },
    "openai": {
        "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
        "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
        "o1-mini": (Decimal("3.00"), Decimal("12.00")),
        "o1-preview": (Decimal("15.00"), Decimal("60.00")),
        "gpt-4-turbo": (Decimal("10.00"), Decimal("30.00")),
        "gpt-3.5-turbo": (Decimal("0.50"), Decimal("1.50")),
    },
    "groq": {
        "llama-3.3-70b-versatile": (Decimal("0.59"), Decimal("0.79")),
        "llama-3.1-70b-versatile": (Decimal("0.59"), Decimal("0.79")),
        "llama-3.1-8b-instant": (Decimal("0.05"), Decimal("0.08")),
        "llama3-70b-8192": (Decimal("0.59"), Decimal("0.79")),
        "llama3-8b-8192": (Decimal("0.05"), Decimal("0.08")),
        "mixtral-8x7b-32768": (Decimal("0.24"), Decimal("0.24")),
        "gemma2-9b-it": (Decimal("0.20"), Decimal("0.20")),
        "deepseek-r1-distill-llama-70b": (Decimal("0.75"), Decimal("0.99")),
        "qwen-2.5-coder-32b": (Decimal("0.79"), Decimal("0.79")),
        "qwen/qwen3.8-27b": (Decimal("0.50"), Decimal("0.75")),
    },
}


def calculate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> tuple[Decimal | None, str | None]:
    """Calculate estimated cost for token consumption.

    Args:
        provider: Provider identifier (e.g. 'gemini', 'openai')
        model: Model name/identifier
        input_tokens: Number of prompt tokens
        output_tokens: Number of generated tokens

    Returns:
        Tuple of (estimated_cost, currency_code) or (None, None) if unknown.
    """
    prov_norm = provider.strip().lower()
    model_norm = model.strip().lower()
    if model_norm.startswith("models/"):
        model_norm = model_norm[len("models/") :]

    provider_rates = PRICING_TABLE_PER_MILLION.get(prov_norm)
    if not provider_rates:
        return None, None

    # Exact match or prefix match (e.g. gpt-4o-2024-08-06 matches gpt-4o)
    rate: tuple[Decimal, Decimal] | None = None
    if model_norm in provider_rates:
        rate = provider_rates[model_norm]
    else:
        for known_model, rates in provider_rates.items():
            if model_norm.startswith(known_model):
                rate = rates
                break

    if rate is None:
        return None, None

    input_rate, output_rate = rate
    million = Decimal("1000000")

    input_cost = (Decimal(input_tokens) / million) * input_rate
    output_cost = (Decimal(output_tokens) / million) * output_rate
    total_cost = (input_cost + output_cost).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    return total_cost, "USD"
