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
