from app.policies.constants import HIGH_VALUE_TRANSACTION_THRESHOLD
from app.strategy.engine import StrategyRecommendation


def is_ambiguous(
    recommendation: StrategyRecommendation, amount: float, close_call_ratio: float = 0.15
) -> bool:
   
    sorted_candidates = sorted(recommendation.candidates, key=lambda c: c[3], reverse=True)
    if len(sorted_candidates) < 2:
        return False

    top_ev = sorted_candidates[0][3]
    second_ev = sorted_candidates[1][3]
    close_call = abs(top_ev - second_ev) < close_call_ratio * max(amount, 1)
    high_value = amount > HIGH_VALUE_TRANSACTION_THRESHOLD

    return close_call or high_value

