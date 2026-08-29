import numpy as np

from app.models.enums import CustomerType, FailureType, PaymentMethod, RecoveryStrategy
from app.simulator.ground_truth import (
    RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE,
    TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE,
    TRANSIENT_PROBABILITY_BY_METHOD,
)
from app.strategy.definitions import STRATEGY_DEFINITIONS


def simulate_recovery_outcome(
    rng: np.random.Generator,
    payment_method: PaymentMethod,
    customer_type: CustomerType,
    strategy: RecoveryStrategy,
    amount: float,
) -> tuple[bool, float]:
    """
    Pure version of the Action Executor's outcome logic (Phase 9), taking
    an explicit RNG instead of using global random state, and never
    touching the database.

    Why this matters for fair comparison: the FIRST draw (is this failure
    secretly transient or permanent?) depends only on payment_method and
    customer_type — NOT on the strategy. So if you call this function with
    the same rng seed but a different strategy, you get the exact same
    underlying "truth" about the failure both times. The SECOND draw (did
    the attempt succeed?) is the same raw random number in both calls, but
    compared against a different threshold — the chosen strategy's
    probability_multiplier. A better strategy raises that threshold,
    making the identical draw more likely to count as a success. This is
    what makes cross-strategy comparison causal rather than coincidental.
    """
    transient_prob = TRANSIENT_PROBABILITY_BY_METHOD[payment_method]
    transient_prob += TRANSIENT_ADJUSTMENT_BY_CUSTOMER_TYPE[customer_type]
    transient_prob = min(max(transient_prob, 0.05), 0.95)
    failure_type = (
        FailureType.TRANSIENT
        if rng.random() < transient_prob
        else FailureType.PERMANENT
    )
    base_prob = RECOVERY_SUCCESS_PROBABILITY_BY_FAILURE_TYPE[failure_type]

    params = STRATEGY_DEFINITIONS[strategy]
    true_prob = min(base_prob * params.probability_multiplier, 0.97)
    succeeded = rng.random() < true_prob

    amount_recovered = amount * params.amount_multiplier if succeeded else 0.0
    return succeeded, amount_recovered
