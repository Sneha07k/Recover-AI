from dataclasses import dataclass

from app.models.enums import RecoveryStrategy


@dataclass(frozen=True)
class StrategyParams:
    cost: float
    probability_multiplier: float
    amount_multiplier: float


# Deliberately simple, explainable numbers for Phase 6. Phase 7 (agent) and
# Phase 8 (policy) build ON TOP of this reasoning â€” they don't replace it.
STRATEGY_DEFINITIONS: dict[RecoveryStrategy, StrategyParams] = {
    # A plain immediate retry: cheap, no change to the base probability.
    RecoveryStrategy.RETRY: StrategyParams(
        cost=5, probability_multiplier=1.0, amount_multiplier=1.0
    ),
    # Waiting before retrying gives transient issues (network blips,
    # temporary provider outages) time to resolve on their own.
    RecoveryStrategy.DELAYED_RETRY: StrategyParams(
        cost=5, probability_multiplier=1.15, amount_multiplier=1.0
    ),
    # Switching payment method sidesteps whatever was wrong with the
    # original method entirely â€” the biggest probability boost, but costlier.
    RecoveryStrategy.ALTERNATE_PAYMENT: StrategyParams(
        cost=15, probability_multiplier=1.30, amount_multiplier=1.0
    ),
    # A discount raises the odds the customer follows through, but reduces
    # the amount actually recovered if it works.
    RecoveryStrategy.INCENTIVE: StrategyParams(
        cost=10, probability_multiplier=1.20, amount_multiplier=0.90
    ),
    RecoveryStrategy.CUSTOMER_REMINDER: StrategyParams(
        cost=8, probability_multiplier=1.10, amount_multiplier=1.0
    ),
    # Human involvement: most expensive, modest probability boost â€” reserved
    # for cases nothing automated handles well (formalized in Phase 8).
    RecoveryStrategy.ESCALATION: StrategyParams(
        cost=50, probability_multiplier=1.05, amount_multiplier=1.0
    ),
    # Doing nothing always costs 0 and always has probability 0 -> expected
    # value is always exactly 0. This is what guarantees the engine never
    # recommends a money-losing action: STOP wins by default if every real
    # option has negative expected value.
    RecoveryStrategy.STOP: StrategyParams(
        cost=0, probability_multiplier=0.0, amount_multiplier=1.0
    ),
}

