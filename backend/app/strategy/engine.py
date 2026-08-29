from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.events.schemas import Event
from app.models.enums import PaymentMethod, RecoveryStrategy
from app.models.models import StrategyDecision
from app.strategy.definitions import STRATEGY_DEFINITIONS
from app.strategy.probability import predict_recovery_probability


@dataclass
class StrategyRecommendation:
    strategy: RecoveryStrategy
    estimated_probability: float
    cost: float
    expected_value: float
    reasoning: str
    candidates: list[tuple[RecoveryStrategy, float, float, float]]


def recommend_strategy(
    db: Session,
    transaction_id: int,
    customer_id: int,
    payment_method: PaymentMethod,
    amount: float,
    force_rule_based: bool = False,
) -> StrategyRecommendation:
    """
    Computes expected value for every candidate strategy and returns the
    best one. STOP is always included with expected_value == 0, which
    guarantees the result never has negative expected value.
    """
    base_probability = predict_recovery_probability(
        db,
        customer_id,
        payment_method,
        amount,
        exclude_transaction_id=transaction_id,
        force_rule_based=force_rule_based,
    )

    candidates = []
    for strategy, params in STRATEGY_DEFINITIONS.items():
        if strategy == RecoveryStrategy.STOP:
            probability = 0.0
            expected_value = 0.0
        else:
            probability = min(base_probability * params.probability_multiplier, 0.95)
            expected_value = (
                probability * amount * params.amount_multiplier - params.cost
            )
        candidates.append((strategy, probability, params.cost, expected_value))

    best_strategy, best_probability, best_cost, best_ev = max(
        candidates, key=lambda c: c[3]
    )

    reasoning = (
        f"Base recovery probability {base_probability:.2f}; chose {best_strategy.value} "
        f"(adjusted probability {best_probability:.2f}, cost \u20b9{best_cost:.2f}) with the "
        f"highest expected value (\u20b9{best_ev:.2f}) among {len(candidates)} candidates."
    )

    return StrategyRecommendation(
        strategy=best_strategy,
        estimated_probability=best_probability,
        cost=best_cost,
        expected_value=best_ev,
        reasoning=reasoning,
        candidates=candidates,
    )


def recommend_strategy_on_payment_failed(db: Session, event: Event) -> StrategyDecision:
    """
    Consumer for PAYMENT_FAILED events. Persists the recommended strategy
    and its expected-value reasoning. NOTE: nothing is executed here â€” no
    retry actually happens, no money moves. Phase 8 adds the policy gate;
    Phase 9 wires in real execution.
    """
    transaction_id = event.entity_id
    customer_id = event.payload["customer_id"]
    payment_method = PaymentMethod(event.payload["payment_method"])
    amount = event.payload["amount"]

    recommendation = recommend_strategy(
        db, transaction_id, customer_id, payment_method, amount
    )

    decision = StrategyDecision(
        transaction_id=transaction_id,
        customer_id=customer_id,
        payment_method=payment_method,
        amount=amount,
        strategy=recommendation.strategy,
        estimated_probability=recommendation.estimated_probability,
        cost=recommendation.cost,
        expected_value=recommendation.expected_value,
        reasoning=recommendation.reasoning,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision
