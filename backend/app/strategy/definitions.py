from dataclasses import dataclass

from app.models.enums import RecoveryStrategy


@dataclass(frozen=True)
class StrategyParams:
    cost: float
    probability_multiplier: float
    amount_multiplier: float



STRATEGY_DEFINITIONS: dict[RecoveryStrategy, StrategyParams] = {

    RecoveryStrategy.RETRY: StrategyParams(
        cost=5, probability_multiplier=1.0, amount_multiplier=1.0
    ),
    
    RecoveryStrategy.DELAYED_RETRY: StrategyParams(
        cost=5, probability_multiplier=1.15, amount_multiplier=1.0
    ),
   
    RecoveryStrategy.ALTERNATE_PAYMENT: StrategyParams(
        cost=15, probability_multiplier=1.30, amount_multiplier=1.0
    ),
   
    RecoveryStrategy.INCENTIVE: StrategyParams(
        cost=10, probability_multiplier=1.20, amount_multiplier=0.90
    ),
    RecoveryStrategy.CUSTOMER_REMINDER: StrategyParams(
        cost=8, probability_multiplier=1.10, amount_multiplier=1.0
    ),
   
    RecoveryStrategy.ESCALATION: StrategyParams(
        cost=50, probability_multiplier=1.05, amount_multiplier=1.0
    ),
   
    RecoveryStrategy.STOP: StrategyParams(
        cost=0, probability_multiplier=0.0, amount_multiplier=1.0
    ),
}

