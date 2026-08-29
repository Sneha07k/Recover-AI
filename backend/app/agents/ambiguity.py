from app.policies.constants import HIGH_VALUE_TRANSACTION_THRESHOLD
from app.strategy.engine import StrategyRecommendation


def is_ambiguous(
    recommendation: StrategyRecommendation, amount: float, close_call_ratio: float = 0.15
) -> bool:
    """
    Flags a case as worth the LLM agent's attention if EITHER:
      - the top two candidate strategies are close in expected value
        (the deterministic engine's "best" pick isn't clearly best), or
      - the transaction is high-value enough to warrant extra scrutiny
        regardless of how confident the deterministic engine is.

    Most failures should return False here â€” that's the point. The agent
    is expensive and slow; it should only see the genuinely hard cases.
    """
    sorted_candidates = sorted(recommendation.candidates, key=lambda c: c[3], reverse=True)
    if len(sorted_candidates) < 2:
        return False

    top_ev = sorted_candidates[0][3]
    second_ev = sorted_candidates[1][3]
    close_call = abs(top_ev - second_ev) < close_call_ratio * max(amount, 1)
    high_value = amount > HIGH_VALUE_TRANSACTION_THRESHOLD

    return close_call or high_value

