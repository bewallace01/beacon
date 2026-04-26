"""Per-token pricing for known models.

Prices are USD per 1,000,000 tokens (in / out). Update as vendors adjust.
Unknown models cost zero, which is intentional: we don't want to silently
guess and then enforce a wrong cap.
"""
from typing import Optional

# (input_per_million, output_per_million) in USD
PRICING: dict[str, tuple[float, float]] = {
    # OpenAI (https://openai.com/api/pricing/)
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-2024-08-06": (2.50, 10.00),
    "gpt-4o-2024-11-20": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
    # Anthropic (https://anthropic.com/pricing). Numbers reflect historical
    # tier pricing. Verify against the current vendor page before relying on
    # these for tight caps.
    "claude-opus-4-7": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
}


def compute_cost_usd(
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> float:
    """Cost in USD for one LLM call. Missing fields are treated as 0."""
    if not model:
        return 0.0
    prices = PRICING.get(model)
    if prices is None:
        return 0.0
    in_per_m, out_per_m = prices
    in_tok = input_tokens or 0
    out_tok = output_tokens or 0
    return (in_tok * in_per_m + out_tok * out_per_m) / 1_000_000.0
